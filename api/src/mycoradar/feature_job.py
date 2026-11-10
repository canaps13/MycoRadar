"""Bounded offline joins of public environmental polygons, never occurrence locations."""

import argparse
import hashlib
import json
import math
import platform
import re
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import numpy as np
import pydantic
import pyproj
import shapely
from pydantic import AwareDatetime, BeforeValidator, Field, model_validator
from pyproj.exceptions import ProjError
from shapely.errors import GEOSException
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from mycoradar.catalog_models import Contract, Geometry, Identifier, Source
from mycoradar.grid import GridError, project
from mycoradar.grid_job import canonical_json, write_artifact

MAX_BYTES = 2 * 1024 * 1024
MAX_PAIRS = 100_000
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


def explicit_timestamp(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        value,
    ):
        raise ValueError("An explicit ISO timestamp with timezone is required")
    return value


Timestamp = Annotated[AwareDatetime, BeforeValidator(explicit_timestamp)]


class FeatureSource(Source):
    # Keep strict join-file dates isolated from the public catalogue contracts.
    fetched_at: Timestamp
    source_published_at: Timestamp | None


class Footprint(Contract):
    geometry: Geometry

    @model_validator(mode="before")
    @classmethod
    def explicit_coordinates(cls, value: Any) -> Any:
        if isinstance(value, dict) and isinstance(value.get("geometry"), dict):

            def check(node: object) -> None:
                if isinstance(node, list | tuple):
                    for child in node:
                        check(child)
                elif type(node) not in (int, float):
                    raise ValueError("Explicit numeric coordinates required")

            check(value["geometry"].get("coordinates"))
        return value

    @model_validator(mode="after")
    def closed(self) -> Self:
        for polygon in self.geometry.polygons():
            for ring in polygon:
                if ring[0] != ring[-1] or len(set(ring)) < 3:
                    raise ValueError("Explicit closed rings required")
        return self


class Cell(Footprint):
    cell_id: Identifier
    display_cell_size_m: Annotated[int, Field(strict=True, gt=0)] | None


class Patch(Footprint):
    id: Identifier
    value: Number | None


class Layer(Contract):
    feature_id: Identifier
    unit: Annotated[str, Field(min_length=1, max_length=40)]
    aggregation: Literal["area_weighted_mean"]
    value_kind: Literal["continuous_intensive"]
    temporal_kind: Literal["historical_observation", "static"]
    valid_from: Timestamp
    valid_until: Timestamp
    source_data_cutoff: Timestamp | None
    source: FeatureSource
    patches: Annotated[tuple[Patch, ...], Field(max_length=1000)]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.source.license not in {"Etalab-2.0", "CC0-1.0", "CC-BY-4.0"}:
            raise ValueError("An explicitly supported open licence is required")
        if self.valid_from >= self.valid_until:
            raise ValueError("Nonempty half-open validity interval required")
        if len({p.id for p in self.patches}) != len(self.patches):
            raise ValueError("Unique patch IDs required")
        if (
            self.source.source_published_at is not None
            and self.source.source_published_at > self.source.fetched_at
        ):
            raise ValueError("Publication cannot postdate acquisition")
        if self.source_data_cutoff is not None and self.source_data_cutoff > self.source.fetched_at:
            raise ValueError("Data cutoff cannot postdate acquisition")
        return self


class Manifest(Contract):
    schema_version: Literal["feature-join-manifest-v1"]
    input_kind: Literal["synthetic", "public_environmental"]
    geometry_crs: Literal["EPSG:4326"]
    as_of: Timestamp
    target_at: Timestamp
    cells: Annotated[tuple[Cell, ...], Field(min_length=1, max_length=500)]
    layers: Annotated[tuple[Layer, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.as_of > self.target_at:
            raise ValueError("Prediction cutoff cannot postdate target")
        if len({c.cell_id for c in self.cells}) != len(self.cells):
            raise ValueError("Duplicate cell")
        if len({layer.feature_id for layer in self.layers}) != len(self.layers):
            raise ValueError("Pin one source version per feature")
        if len(self.cells) * sum(len(layer.patches) + 1 for layer in self.layers) > MAX_PAIRS:
            raise ValueError("Join work budget exceeded")
        footprints = [*self.cells, *(p for layer in self.layers for p in layer.patches)]
        vertices = sum(
            len(ring)
            for footprint in footprints
            for polygon in footprint.geometry.polygons()
            for ring in polygon
        )
        if vertices > 20_000:
            raise ValueError("Input vertex budget exceeded")
        return self


def _eligibility(layer: Layer, manifest: Manifest) -> str | None:
    source = layer.source
    if source.source_published_at is None or layer.source_data_cutoff is None:
        return "source_time_unknown"
    if (
        max(source.source_published_at, source.fetched_at, layer.source_data_cutoff)
        > manifest.as_of
    ):
        return "source_not_available_as_of"
    if not layer.valid_from <= manifest.target_at < layer.valid_until:
        return "outside_validity_interval"
    return None


def _project(footprint: Footprint) -> BaseGeometry:
    geometry = project(shape(footprint.geometry.model_dump(mode="json")), "EPSG:4326")
    if geometry.area > 100_000_000:
        raise GridError("Footprint exceeds 100 square kilometres")
    return geometry


def build_artifact(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise GridError("Invalid input file")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise GridError("Input budget exceeded")
    manifest = Manifest.model_validate_json(raw)
    projected_vertices = 0

    def bounded_project(footprint: Footprint) -> BaseGeometry:
        nonlocal projected_vertices
        geometry = _project(footprint)
        projected_vertices += int(shapely.get_num_coordinates(geometry))
        if projected_vertices > 100_000:
            raise GridError("Projected vertex budget exceeded")
        return geometry

    cells = [
        (cell, bounded_project(cell)) for cell in sorted(manifest.cells, key=lambda c: c.cell_id)
    ]
    rows = []
    comparisons = 0
    for layer in sorted(manifest.layers, key=lambda layer: layer.feature_id):
        # Validate even ineligible geometry; malformed data cannot be hidden by a date filter.
        patches = [(p, bounded_project(p)) for p in sorted(layer.patches, key=lambda p: p.id)]
        reason = _eligibility(layer, manifest)
        for cell, geometry in cells:
            value = None
            coverage = 0.0
            contributors = []
            row_reason = reason
            if row_reason is None:
                pieces = [
                    (patch, polygon.intersection(geometry))
                    for patch, polygon in patches
                    if polygon.intersects(geometry)
                ]
                pieces = [(p, piece) for p, piece in pieces if piece.area > 0]
                # A positive-area overlap invalidates even numerically equal patch values.
                overlaps = False
                if pieces:
                    boundaries = shapely.STRtree([piece for _, piece in pieces])
                    for i, (_, piece) in enumerate(pieces):
                        neighbors = boundaries.query(piece, predicate="intersects")
                        comparisons += len(neighbors)
                        if comparisons > MAX_PAIRS:
                            raise GridError("Overlap work budget exceeded")
                        if any(
                            piece.intersection(pieces[int(j)][1]).area > 0
                            for j in neighbors
                            if i < j
                        ):
                            overlaps = True
                            break
                usable = [(p, piece) for p, piece in pieces if p.value is not None]
                usable_union = unary_union([piece for _, piece in usable])
                coverage = min(1.0, usable_union.area / geometry.area)
                # No tolerance can turn a gap into coverage or a contradictory overlap into data.
                if overlaps:
                    row_reason = "overlapping_supports"
                elif not usable_union.covers(geometry):
                    row_reason = "incomplete_usable_coverage"
                else:
                    value = math.fsum(
                        p.value * (piece.area / geometry.area)
                        for p, piece in usable
                        if p.value is not None
                    )
                    if not math.isfinite(value):
                        raise GridError("Nonfinite aggregate")
                    contributors = [p.id for p, _ in usable]
            rows.append(
                {
                    "cell_id": cell.cell_id,
                    "feature_id": layer.feature_id,
                    "target_at": manifest.target_at.isoformat(),
                    "as_of": manifest.as_of.isoformat(),
                    "value": value,
                    "unit": layer.unit,
                    "status": "available" if row_reason is None else "unavailable",
                    "reason": row_reason,
                    "usable_area_fraction": coverage,
                    "contributing_patch_ids": contributors,
                    "source_id": layer.source.id,
                    "source_version": layer.source.version,
                    "source_sha256": layer.source.sha256,
                    "source_data_cutoff": (
                        layer.source_data_cutoff.isoformat() if layer.source_data_cutoff else None
                    ),
                    "source_published_at": (
                        layer.source.source_published_at.isoformat()
                        if layer.source.source_published_at
                        else None
                    ),
                    "source_fetched_at": layer.source.fetched_at.isoformat(),
                    "source_effective_resolution_m": layer.source.effective_resolution_m,
                    "effective_resolution_m": None,
                    "display_cell_size_m": cell.display_cell_size_m,
                    "location_uncertainty_m": None,
                }
            )
    versions = {
        "python": platform.python_version(),
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "numpy": np.__version__,
        "pydantic": pydantic.__version__,
        "platform": platform.platform(),
        "implementation_sha256": hashlib.sha256(
            b"".join(
                Path(__file__).with_name(name).read_bytes()
                for name in ("feature_job.py", "grid.py", "grid_job.py", "catalog_models.py")
            )
        ).hexdigest(),
    }
    identity = {"input_sha256": hashlib.sha256(raw).hexdigest(), "engine_versions": versions}
    statuses = Counter(row["status"] for row in rows)
    return {
        "schema_version": "dated-features-v1",
        "job_id": hashlib.sha256(canonical_json(identity)).hexdigest(),
        **identity,
        "input_kind": manifest.input_kind,
        "admitted_for_scientific_use": False,
        "status": "unavailable" if not statuses["available"] else "partial",
        "area_crs": "EPSG:6933",
        "aggregation": "area_weighted_mean_of_continuous_intensive_supports",
        "sources": [layer.source.model_dump(mode="json") for layer in manifest.layers],
        "features": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        artifact = build_artifact(args.manifest)
        created = write_artifact(args.output, canonical_json(artifact))
    except (
        ValueError,
        OSError,
        TypeError,
        KeyError,
        RecursionError,
        OverflowError,
        ProjError,
        GEOSException,
    ):
        print('{"error":"feature_job_failed"}')
        return 2
    print(
        json.dumps(
            {
                "job_id": artifact["job_id"],
                "rows": len(artifact["features"]),
                "status": artifact["status"],
                "created": created,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
