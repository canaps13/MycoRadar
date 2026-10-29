"""Public polygon inputs to a deterministic artifact; deliberately separate from FastAPI."""

import argparse
import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pyproj
import shapely
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pyproj.exceptions import ProjError
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .grid import GRID_VERSION, TO_WGS84, GridError, Mask, generate_grid, project, reproject

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(Contract):
    provider: Text
    product: Text
    source_url: Text
    license: Literal["Etalab-2.0", "CC0-1.0", "CC-BY-4.0"]
    license_url: Text
    attribution: Text
    version: Text
    fetched_at: AwareDatetime
    source_published_at: AwareDatetime | None
    effective_resolution_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    visibility: Literal["public"]


class Layer(Contract):
    path: Text
    sha256: Digest
    crs: Text
    provenance: Provenance


class GeometryRef(Contract):
    layer: Text
    property: Text | None = None
    value: Text | None = None

    @model_validator(mode="after")
    def paired_selector(self) -> "GeometryRef":
        if (self.property is None) != (self.value is None):
            raise ValueError("Selector property and value must be provided together")
        return self


class MaskRef(Contract):
    positive: GeometryRef
    coverage: GeometryRef


class Territory(Contract):
    id: Text
    name: Text
    country_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    timezone: Text
    boundary: GeometryRef
    land: MaskRef | None
    forest: MaskRef | None

    @model_validator(mode="after")
    def known_timezone(self) -> "Territory":
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown timezone") from error
        return self


class GridSpec(Contract):
    resolutions_m: tuple[Annotated[int, Field(strict=True, gt=0)], ...]
    max_candidates: int = Field(default=50_000, ge=1, le=100_000, strict=True)
    experimental_fine_grid: bool = Field(default=False, strict=True)


class Manifest(Contract):
    schema_version: Literal["grid-manifest-v1"]
    grid: GridSpec
    layers: dict[str, Layer]
    territories: tuple[Territory, ...]

    @model_validator(mode="after")
    def unique_territories(self) -> "Manifest":
        ids = [territory.id for territory in self.territories]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Nonempty, unique territory IDs required")
        return self


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _load_layer(layer: Layer, root: Path) -> list[dict[str, Any]]:
    path = (root / layer.path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise GridError("Layer must stay within the manifest directory")
    if path.stat().st_size > 20_000_000:
        raise GridError("Input too large; use a versioned regional extract")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != layer.sha256:
        raise GridError("Layer checksum mismatch")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise GridError("A GeoJSON FeatureCollection is required")
    declared_crs = pyproj.CRS.from_user_input(layer.crs)
    legacy = data.get("crs")
    if legacy is None:
        if not declared_crs.equals(pyproj.CRS.from_epsg(4326), ignore_axis_order=True):
            raise GridError("Projected GeoJSON needs a matching explicit legacy CRS declaration")
    else:
        properties = legacy.get("properties") if isinstance(legacy, dict) else None
        if not isinstance(properties, dict) or not isinstance(properties.get("name"), str):
            raise GridError("Invalid GeoJSON CRS declaration")
        if not declared_crs.equals(
            pyproj.CRS.from_user_input(properties["name"]), ignore_axis_order=True
        ):
            raise GridError("Manifest and GeoJSON CRS disagree")
    features = data.get("features")
    if not isinstance(features, list) or any(not isinstance(f, dict) for f in features):
        raise GridError("Invalid GeoJSON features")
    # Prevent tiny cell sizes or malicious geometry payloads from causing unbounded densification.
    coordinates = 0
    for feature in features:
        if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise GridError("GeoJSON features need explicit object properties")
        geometry_data = feature.get("geometry")
        if not isinstance(geometry_data, dict):
            raise GridError("Feature geometry must be an explicit polygon object")
        geometry = shape(geometry_data)
        coordinates += int(shapely.get_num_coordinates(geometry))
        if coordinates > 200_000:
            raise GridError("Input vertex budget exceeded")
        # Validate even features that will not be selected for this territory.
        projected_geometry = project(geometry, layer.crs)
        if int(shapely.get_num_coordinates(projected_geometry)) > 250_000:
            raise GridError("Projected vertex budget exceeded")
    return features


def build_artifact(manifest_path: Path) -> dict[str, Any]:
    if manifest_path.stat().st_size > 1_000_000:
        raise GridError("Manifest too large")
    manifest = Manifest.model_validate_json(manifest_path.read_bytes())
    features = {
        key: _load_layer(layer, manifest_path.parent) for key, layer in manifest.layers.items()
    }
    versions = {
        "grid": GRID_VERSION,
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "platform": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes() + Path(__file__).with_name("grid.py").read_bytes()
        ).hexdigest(),
    }
    inputs = {"manifest": manifest.model_dump(mode="json"), "engine_versions": versions}
    job_id = hashlib.sha256(canonical_json(inputs)).hexdigest()
    projected: dict[str, BaseGeometry] = {}

    def resolve(ref: GeometryRef, *, allow_empty: bool = False) -> BaseGeometry:
        key = ref.model_dump_json()
        if ref.layer not in manifest.layers:
            raise GridError("Referenced layer not found")
        if key not in projected:
            selected = [
                shape(feature["geometry"])
                for feature in features[ref.layer]
                if ref.property is None or feature["properties"].get(ref.property) == ref.value
            ]
            if not selected:
                if ref.property is not None:
                    raise GridError("Geometry selector matched no feature")
                geometry: BaseGeometry = Polygon()
            else:
                geometry = unary_union(selected)
            projected[key] = project(
                geometry, manifest.layers[ref.layer].crs, allow_empty=allow_empty
            )
        result = projected[key]
        if result.is_empty and not allow_empty:
            raise GridError("Boundary/coverage geometry cannot be empty")
        return result

    def mask(ref: MaskRef | None) -> Mask | None:
        if ref is None:
            return None
        return Mask(resolve(ref.positive, allow_empty=True), resolve(ref.coverage))

    output = []
    remaining_candidates = manifest.grid.max_candidates
    for territory in manifest.territories:
        batch = generate_grid(
            resolve(territory.boundary),
            manifest.grid.resolutions_m,
            land=mask(territory.land),
            forest=mask(territory.forest),
            max_candidates=remaining_candidates,
            experimental_fine_grid=manifest.grid.experimental_fine_grid,
        )
        remaining_candidates -= batch.candidate_count
        for cell in batch.cells:
            geometry = reproject(cell.geometry, TO_WGS84)
            if isinstance(geometry, Polygon):
                geometry = MultiPolygon([geometry])
            output.append(
                {
                    "type": "Feature",
                    "id": f"{territory.id}/{cell.cell_id}",
                    "geometry": mapping(geometry),
                    "properties": {
                        "cell_id": cell.cell_id,
                        "region_id": territory.id,
                        "country_code": territory.country_code,
                        "timezone": territory.timezone,
                        "grid_system": GRID_VERSION,
                        "resolution_m": cell.resolution_m,
                        "grid_area_m2": cell.geometry.area,
                        "region_area_m2": cell.region_area_m2,
                        "land_fraction": cell.land_fraction,
                        "forest_fraction": cell.forest_fraction,
                        "land_status": cell.land_status,
                        "forest_status": cell.forest_status,
                        "coverage_status": (
                            "complete"
                            if cell.land_status == cell.forest_status == "complete"
                            else "unavailable"
                            if cell.land_status == cell.forest_status == "unavailable"
                            else "partial"
                        ),
                        "display_cell_size_m": None,
                        "effective_resolution_m": None,
                        "location_uncertainty_m": None,
                        "experimental_fine_grid": cell.resolution_m < 250,
                    },
                }
            )
    return {
        "type": "FeatureCollection",
        "schema_version": "grid-artifact-v1",
        "job_id": job_id,
        "candidate_count": manifest.grid.max_candidates - remaining_candidates,
        "geometry_crs": "EPSG:4326",
        "area_crs": "EPSG:6933",
        "engine_versions": versions,
        "inputs": inputs,
        "features": output,
    }


def write_artifact(path: Path, data: bytes) -> bool:
    """Atomic, no-overwrite publication; identical retries leave the existing file untouched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            if path.read_bytes() != data:
                raise GridError("Output already exists with different content") from None
            return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        artifact = build_artifact(args.manifest)
        created = write_artifact(args.output, canonical_json(artifact))
    except (ValueError, OSError, ProjError, GEOSException, TypeError, KeyError) as error:
        parser.exit(2, f"Grid job failed: {error}\n")
    unique_cells = len({feature["properties"]["cell_id"] for feature in artifact["features"]})
    print(
        f"job_id={artifact['job_id']} memberships={len(artifact['features'])} "
        f"unique_cells={unique_cells} created={created}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
