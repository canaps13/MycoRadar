"""Public, immutable catalogue contracts. No observations or scientific scores."""

from collections.abc import Iterator
from datetime import datetime
from functools import cached_property
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")]
Checksum = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Country = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Position = tuple[Longitude, Latitude]
Ring = Annotated[tuple[Position, ...], Field(min_length=4)]
PolygonRings = Annotated[tuple[Ring, ...], Field(min_length=1)]
Bounds = tuple[float, float, float, float]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Polygon(Contract):
    type: Literal["Polygon"]
    coordinates: PolygonRings

    def polygons(self) -> Iterator[PolygonRings]:
        yield self.coordinates


class MultiPolygon(Contract):
    type: Literal["MultiPolygon"]
    coordinates: Annotated[tuple[PolygonRings, ...], Field(min_length=1)]

    def polygons(self) -> Iterator[PolygonRings]:
        yield from self.coordinates


Geometry = Annotated[Polygon | MultiPolygon, Field(discriminator="type")]


class PublicRecord(Contract):
    id: Identifier
    visibility: Literal["public"]
    source_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class SpatialRecord(PublicRecord):
    geometry: Geometry

    @model_validator(mode="after")
    def closed_rings(self) -> Self:
        for polygon in self.geometry.polygons():
            for ring in polygon:
                if ring[0] != ring[-1] or len(set(ring)) < 3:
                    raise ValueError("Expected a closed ring with three distinct vertices")
        return self

    @cached_property
    def bounds(self) -> Bounds:
        positions = [p for polygon in self.geometry.polygons() for ring in polygon for p in ring]
        return (
            min(p[0] for p in positions),
            min(p[1] for p in positions),
            max(p[0] for p in positions),
            max(p[1] for p in positions),
        )


class Region(SpatialRecord):
    country_code: Country
    name: Annotated[str, Field(min_length=1, max_length=200)]
    timezone: str

    @model_validator(mode="after")
    def valid_timezone(self) -> Self:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return self


class Species(PublicRecord):
    scientific_name: Annotated[str, Field(min_length=1, max_length=200)]
    region_ids: tuple[Identifier, ...]
    sensitive: Literal[False]


class Cell(SpatialRecord):
    region_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    display_cell_size_m: Annotated[int, Field(gt=0)]
    effective_resolution_m: Annotated[float, Field(gt=0)] | None
    habitat_status: Literal["unavailable"]
    fruiting_status: Literal["unavailable"]


class Source(Contract):
    id: Identifier
    provider: str
    product: str
    source_url: HttpUrl
    license: Annotated[str, Field(min_length=1)]
    license_url: HttpUrl
    attribution: Annotated[str, Field(min_length=1)]
    version: Annotated[str, Field(min_length=1)]
    sha256: Checksum
    fetched_at: AwareDatetime
    source_published_at: AwareDatetime | None
    effective_resolution_m: Annotated[float, Field(gt=0)] | None
    transformations: tuple[str, ...]
    visibility: Literal["public"]


class CollectionState(Contract):
    status: Literal["available", "partial", "unavailable"]
    reason: Annotated[str, Field(min_length=1)] | None


class Availability(Contract):
    regions: CollectionState
    species: CollectionState
    cells: CollectionState
    metadata: CollectionState


class Snapshot(Contract):
    schema_version: Literal["public-catalog-v1"]
    published_at: AwareDatetime
    availability: Availability
    regions: tuple[Region, ...]
    species: tuple[Species, ...]
    cells: tuple[Cell, ...]
    metadata: tuple[Source, ...]

    @model_validator(mode="after")
    def consistent_publication(self) -> Self:
        source_ids = {s.id for s in self.metadata}
        region_ids = {r.id for r in self.regions}
        for name in ("regions", "species", "cells", "metadata"):
            records = getattr(self, name)
            if len(records) > 50_000 or len({r.id for r in records}) != len(records):
                raise ValueError("Catalogue budget or unique identity constraint violated")
            state = getattr(self.availability, name)
            if state.status == "unavailable" and records:
                raise ValueError("Unavailable collection must contain no records")
            if state.status != "available" and not state.reason:
                raise ValueError("Incomplete publication requires a reason")
        for record in (*self.regions, *self.species, *self.cells):
            if not set(record.source_ids) <= source_ids:
                raise ValueError("Unresolved source reference")
            if isinstance(record, SpatialRecord):
                _ = record.bounds  # Compute envelopes once at startup, outside requests.
        for record in (*self.species, *self.cells):
            if isinstance(record, Species | Cell) and not set(record.region_ids) <= region_ids:
                raise ValueError("Unresolved region reference")
        for source in self.metadata:
            if source.source_published_at and source.source_published_at > source.fetched_at:
                raise ValueError("Source publication is later than collection")
        return self


class Pagination(Contract):
    limit: int
    offset: int
    total: int
    next: str | None


class Page[T](Contract):
    status: Literal["available", "partial", "unavailable"]
    reason: str | None
    catalog_version: str
    published_at: datetime
    pagination: Pagination
    items: tuple[T, ...]
    spatial_filter: Literal["envelope_intersects"] | None = None


class ErrorDetail(Contract):
    code: Literal[
        "invalid_query",
        "region_not_found",
        "catalog_version_conflict",
        "catalog_unavailable",
        "taxon_not_admitted",
    ]
    message: str


class ErrorResponse(Contract):
    status: Literal["unavailable"] = "unavailable"
    error: ErrorDetail
