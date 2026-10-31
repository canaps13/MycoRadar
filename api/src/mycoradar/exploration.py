"""Bounded read-only explorer view; all spatial preparation stays offline."""

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BeforeValidator, Field, ValidationError, model_validator

from mycoradar.catalog import DEFAULT_CATALOG, Catalog
from mycoradar.catalog_api import CatalogError
from mycoradar.catalog_models import (
    Checksum,
    CollectionState,
    Contract,
    ErrorResponse,
    Geometry,
    Identifier,
    Position,
    Source,
    Species,
)

CONTEXT_PATH = Path(__file__).parent / "data" / "explorer-context.json"


def calendar_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("An explicit ISO calendar date is required")
    return date.fromisoformat(value)


class DisplaySector(Contract):
    id: Identifier
    code: str
    label_point: Position


class ExplorerContext(Contract):
    schema_version: Literal["explorer-context-v1"]
    label: str
    timezone: str
    bounds: tuple[float, float, float, float]
    context_bounds: tuple[float, float, float, float]
    source_id: Identifier
    source_sha256: Checksum
    sectors: Annotated[tuple[DisplaySector, ...], Field(min_length=1, max_length=100)]
    species_ids: Annotated[tuple[Identifier, ...], Field(max_length=100)] = ()

    @model_validator(mode="after")
    def coherent_display(self) -> Self:
        ZoneInfo(self.timezone)
        for box in (self.bounds, self.context_bounds):
            west, south, east, north = box
            if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                raise ValueError("Invalid display bounds")
        if len({s.id for s in self.sectors}) != len(self.sectors):
            raise ValueError("Duplicate display sector")
        return self


class ExplorerBundle:
    def __init__(self, catalog: Catalog, path: Path = CONTEXT_PATH) -> None:
        self.context: ExplorerContext | None = None
        self.version = "unavailable"
        try:
            content = path.read_bytes()
            expected = path.with_suffix(".sha256").read_text(encoding="ascii").strip()
            if len(content) > 100_000 or hashlib.sha256(content).hexdigest() != expected:
                return
            context = ExplorerContext.model_validate_json(content)
            snapshot = catalog.snapshot
            if snapshot is None:
                return
            source = next((s for s in snapshot.metadata if s.id == context.source_id), None)
            if source is None or source.sha256 != context.source_sha256:
                return
            for sector in context.sectors:
                region = catalog.region_index.get(sector.id)
                if region is None or context.source_id not in region.source_ids:
                    return
                w, s, e, n = region.bounds
                if not (w <= sector.label_point[0] <= e and s <= sector.label_point[1] <= n):
                    return
            if not set(context.species_ids) <= {s.id for s in snapshot.species}:
                return
            self.context = context
            self.version = hashlib.sha256(content).hexdigest()
        except (OSError, ValueError, KeyError, UnicodeError, ValidationError):
            self.context = None


class ExplorerRegion(Contract):
    id: Identifier
    code: str
    name: str
    timezone: str
    geometry: Geometry
    bounds: tuple[float, float, float, float]
    label_point: Position
    source_ids: tuple[Identifier, ...]


class UnavailableLayer(Contract):
    status: Literal["unavailable"] = "unavailable"
    score: None = None
    reason: Literal["no_scientific_publication"] = "no_scientific_publication"
    effective_resolution_m: None = None
    computed_at: None = None


class ExplorationResponse(Contract):
    status: Literal["partial"] = "partial"
    catalog_version: str
    context_version: str
    label: str
    timezone: str
    bounds: tuple[float, float, float, float]
    context_bounds: tuple[float, float, float, float]
    requested_date: date
    selected_region_id: str | None
    selected_taxon_id: str | None
    regions: tuple[ExplorerRegion, ...]
    species: tuple[Species, ...]
    species_state: CollectionState
    sources: tuple[Source, ...]
    source_age_days: None = None
    habitat: UnavailableLayer = UnavailableLayer()
    fruiting: UnavailableLayer = UnavailableLayer()


def get_explorer_catalog(request: Request) -> Catalog:
    allowed = {"region_id", "taxon_id", "valid_at", "catalog_version"}
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise CatalogError(422, "invalid_query", "Unknown or repeated explorer query parameter.")
    catalog: Catalog | None = getattr(request.app.state, "catalog", None)
    if catalog is None or catalog.snapshot is None:
        raise CatalogError(503, "catalog_unavailable", "No valid public catalogue is loaded.")
    return catalog


router = APIRouter(
    tags=["exploration"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 422, 503)},
)


@router.get("/v1/exploration", response_model=ExplorationResponse)
def explore(
    request: Request,
    catalog: Annotated[Catalog, Depends(get_explorer_catalog)],
    region_id: Identifier | None = None,
    taxon_id: Identifier | None = None,
    valid_at: Annotated[date | None, BeforeValidator(calendar_date)] = None,
    catalog_version: Annotated[str | None, Query(pattern=r"^[a-f0-9]{64}$")] = None,
) -> ExplorationResponse:
    """Explore the configured pilot, never infer a score from absent scientific inputs."""
    bundle: ExplorerBundle | None = getattr(request.app.state, "explorer", None)
    if bundle is None or bundle.context is None:
        raise CatalogError(503, "catalog_unavailable", "Explorer display publication unavailable.")
    context = bundle.context
    snapshot = catalog.snapshot
    assert snapshot is not None
    if catalog_version is not None and catalog_version != catalog.version:
        raise CatalogError(
            409, "catalog_version_conflict", "Catalogue changed; reload exploration."
        )
    if region_id and region_id not in {r.id for r in context.sectors}:
        raise CatalogError(404, "region_not_found", "Region is not in this explorer publication.")
    selected_region = catalog.region_index.get(region_id or "")
    timezone = selected_region.timezone if selected_region else context.timezone
    day = valid_at or datetime.now(UTC).astimezone(ZoneInfo(timezone)).date()
    if not date(1900, 1, 1) <= day <= date(2100, 12, 31):
        raise CatalogError(422, "invalid_query", "Exploration date must be within 1900–2100.")
    species = tuple(
        s
        for s in snapshot.species
        if s.id in context.species_ids and (region_id is None or region_id in s.region_ids)
    )
    if taxon_id and taxon_id not in {s.id for s in species}:
        raise CatalogError(404, "taxon_not_admitted", "Taxon is not admitted for this exploration.")
    regions = tuple(
        ExplorerRegion(
            id=display.id,
            code=display.code,
            name=catalog.region_index[display.id].name,
            timezone=catalog.region_index[display.id].timezone,
            geometry=catalog.region_index[display.id].geometry,
            bounds=catalog.region_index[display.id].bounds,
            label_point=display.label_point,
            source_ids=catalog.region_index[display.id].source_ids,
        )
        for display in context.sectors
    )
    source_ids = {source_id for r in regions for source_id in r.source_ids}
    source_ids.update(source_id for s in species for source_id in s.source_ids)
    return ExplorationResponse(
        catalog_version=catalog.version,
        context_version=bundle.version,
        label=context.label,
        timezone=timezone,
        bounds=context.bounds,
        context_bounds=context.context_bounds,
        requested_date=day,
        selected_region_id=region_id,
        selected_taxon_id=taxon_id,
        regions=regions,
        species=species,
        species_state=(
            snapshot.availability.species
            if species
            else CollectionState(status="unavailable", reason="pilot_taxon_not_admitted")
        ),
        sources=tuple(s for s in snapshot.metadata if s.id in source_ids),
    )


def check_bundle() -> None:
    checksum = DEFAULT_CATALOG.with_suffix(".sha256").read_text(encoding="ascii").strip()
    catalog = Catalog(DEFAULT_CATALOG, checksum)
    if ExplorerBundle(catalog).context is None:
        raise RuntimeError("Explorer bundle validation failed")
    print("Explorer bundle verified without database, web directory or geo dependencies.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-bundle", action="store_true", required=True)
    parser.parse_args()
    check_bundle()
