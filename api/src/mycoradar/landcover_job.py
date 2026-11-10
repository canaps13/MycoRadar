"""Normalize bounded public landcover extracts offline; never infer unmapped absence."""

import argparse
import gzip
import hashlib
import io
import json
import math
import platform
import re
import unicodedata
import zlib
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal, Never, Self

import pyproj
import shapely
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pyproj.exceptions import ProjError
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from mycoradar.grid import TO_WGS84, project, reproject, validate_polygon
from mycoradar.grid_job import Provenance, canonical_json, write_artifact

VERSION = "landcover-v1"
MAX_BYTES = 10 * 1024 * 1024
MAX_FEATURES = 1000
MAX_VERTICES = 100000
Text = Annotated[str, StringConstraints(min_length=1, max_length=300)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Coordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class LandcoverError(ValueError):
    """Fixed diagnostics only, without input documents or operator paths."""


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Properties(Contract):
    identifier: Text = "id"
    vegetation_code: Text = "code_tfv"
    vegetation_label: Text = "tfv"
    vegetation_group: Text | None = "tfv_g11"
    dominant_taxa: Text | None = "essence"
    source_year: Text | None = None


class Manifest(Contract):
    schema_version: Literal["landcover-manifest-v1"]
    path: Text
    sha256: Digest
    entity_sha256: Digest
    compression: Literal["none", "gzip"]
    crs: Text
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]
    provenance: Provenance
    properties: Properties = Properties()
    source_year: Annotated[int, Field(strict=True, ge=1800, le=2100)] | None = None
    year_meaning: Literal["acquisition", "reference", "unavailable"] = "unavailable"
    year_evidence_url: Text | None = None
    product_production_period: tuple[int, int] | None = None
    product_metadata_url: Text
    repair_invalid: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        west, south, east, north = self.bbox
        if (
            not all(math.isfinite(v) for v in self.bbox)
            or not (-180 <= west < east <= 180 and -86 <= south < north <= 86)
            or east - west > 2
            or north - south > 2
        ):
            raise ValueError("bounded WGS84 bbox required")
        has_year = self.source_year is not None or self.properties.source_year is not None
        if has_year != (self.year_meaning != "unavailable") or (
            has_year and self.year_evidence_url is None
        ):
            raise ValueError("year evidence and semantics required")
        if self.source_year is not None and self.source_year > self.provenance.fetched_at.year:
            raise ValueError("future source year refused")
        period = self.product_production_period
        if (
            period is not None
            and not 1800 <= period[0] <= period[1] <= self.provenance.fetched_at.year
        ):
            raise ValueError("invalid product production period")
        return self


def _text(value: object, *, required: bool = True) -> str | None:
    if value is None or value == "":
        if required:
            raise LandcoverError("property_missing")
        return None
    if not isinstance(value, str) or len(value) > 300:
        raise LandcoverError("property_invalid")
    # Known legacy C1 punctuation is transcoded, never a scientific/taxonomic correction.
    value = value.translate({0x91: 0x2018, 0x92: 0x2019, 0x96: 0x2013})
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise LandcoverError("property_control_character")
    result = unicodedata.normalize("NFC", value).strip()
    if not result and required:
        raise LandcoverError("property_missing")
    return result or None


def _year(value: object, manifest: Manifest) -> int | None:
    if value is None or value == "":
        return manifest.source_year
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"\d{4}", value):
        result = int(value)
    else:
        raise LandcoverError("source_year_invalid")
    if not 1800 <= result <= min(2100, manifest.provenance.fetched_at.year):
        raise LandcoverError("source_year_invalid")
    if manifest.source_year is not None and result != manifest.source_year:
        raise LandcoverError("source_year_conflict")
    return result


def _polygon_parts(geometry: BaseGeometry) -> tuple[list[Polygon], int]:
    if geometry.is_empty:
        return [], 0
    if isinstance(geometry, Polygon):
        return [geometry], 0
    if isinstance(geometry, MultiPolygon | GeometryCollection):
        parts: list[Polygon] = []
        discarded = 0
        for component in geometry.geoms:
            items, count = _polygon_parts(component)
            parts.extend(items)
            discarded += count
        return parts, discarded
    return [], 1


def _geometry(value: object, remaining: int) -> tuple[BaseGeometry, int]:
    if not isinstance(value, dict) or value.get("type") not in {"Polygon", "MultiPolygon"}:
        raise LandcoverError("polygon_required")
    stack = [value.get("coordinates")]
    count = 0
    while stack:
        item = stack.pop()
        if not isinstance(item, list):
            raise LandcoverError("coordinates_invalid")
        if item and not isinstance(item[0], list):
            if len(item) != 2:
                raise LandcoverError("two_dimensions_required")
            if any(type(n) not in {int, float} for n in item):
                raise LandcoverError("coordinates_invalid")
            try:
                if not all(math.isfinite(n) for n in item):
                    raise LandcoverError("coordinates_invalid")
            except OverflowError:
                raise LandcoverError("coordinates_invalid") from None
            count += 1
            if count > remaining:
                raise LandcoverError("vertex_budget_exceeded")
        else:
            stack.extend(item)
    return shape(value), count


def _input(manifest: Manifest, root: Path) -> dict[str, Any]:
    path = (root / manifest.path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise LandcoverError("input_path_refused")
    if path.stat().st_size > MAX_BYTES:
        raise LandcoverError("input_budget_exceeded")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.sha256:
        raise LandcoverError("input_checksum_mismatch")
    if manifest.compression == "gzip":
        with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
            content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise LandcoverError("decoded_budget_exceeded")
    if hashlib.sha256(content).hexdigest() != manifest.entity_sha256:
        raise LandcoverError("entity_checksum_mismatch")
    data = json.loads(content)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise LandcoverError("collection_invalid")
    features = data.get("features")
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        raise LandcoverError("feature_budget_exceeded")
    declared = pyproj.CRS.from_user_input(manifest.crs)
    legacy = data.get("crs")
    if legacy is None:
        if not declared.equals(pyproj.CRS.from_epsg(4326), ignore_axis_order=True):
            raise LandcoverError("crs_declaration_missing")
    else:
        name = legacy["properties"]["name"]
        # Reviewed GeoServer spelling of the explicitly requested longitude/latitude CRS84.
        if name in {"urn:ogc:def:crs:CRS::84", "CRS:84"}:
            name = "OGC:CRS84"
        if not declared.equals(pyproj.CRS.from_user_input(name), ignore_axis_order=True):
            raise LandcoverError("crs_mismatch")
    # A service count is a transport check, never evidence that unmapped ground is nonforest.
    for name in ("numberMatched", "totalFeatures", "numberReturned"):
        if name in data and (type(data[name]) is not int or data[name] != len(features)):
            raise LandcoverError("selection_truncated_or_count_invalid")
    return data


def build_artifact(manifest_path: Path) -> dict[str, Any]:
    if manifest_path.stat().st_size > 100000:
        raise LandcoverError("manifest_budget_exceeded")
    manifest = Manifest.model_validate_json(manifest_path.read_bytes())
    data = _input(manifest, manifest_path.parent)
    area = project(box(*manifest.bbox), "EPSG:4326")
    if area.area > 100_000_000:
        raise LandcoverError("aoi_budget_exceeded")
    vertices = 0
    geometries = []
    for feature in data["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise LandcoverError("feature_invalid")
        geometry, count = _geometry(feature["geometry"], MAX_VERTICES - vertices)
        vertices += count
        geometries.append(geometry)
    output: list[dict[str, Any]] = []
    seen: dict[str, bytes] = {}
    repairs = non_polygon_parts = outside = duplicates = transcoded = 0
    metric_geometries = []
    for feature, geometry in zip(data["features"], geometries, strict=True):
        props = feature.get("properties")
        if not isinstance(props, dict):
            raise LandcoverError("properties_invalid")
        selection = manifest.properties
        identifier = _text(props.get(selection.identifier))
        if identifier is None:
            raise LandcoverError("identifier_missing")
        code = _text(props.get(selection.vegetation_code))
        label = _text(props.get(selection.vegetation_label))
        group = (
            _text(props.get(selection.vegetation_group), required=False)
            if selection.vegetation_group
            else None
        )
        taxa = (
            _text(props.get(selection.dominant_taxa), required=False)
            if selection.dominant_taxa
            else None
        )
        year = _year(props.get(selection.source_year) if selection.source_year else None, manifest)
        year_status = "known" if year is not None else "unavailable"
        selected: dict[str, Any] = {
            "source_id": identifier,
            "vegetation_code": code,
            "vegetation_label": label,
            "vegetation_group": group,
            "dominant_taxa": None if taxa == "NC" else taxa,
            "source_year": year,
            "year_status": year_status,
            "year_meaning": manifest.year_meaning,
        }
        original = canonical_json({"properties": selected, "geometry": feature["geometry"]})
        if identifier in seen:
            if seen[identifier] != original:
                raise LandcoverError("duplicate_identity_conflict")
            duplicates += 1
            continue
        seen[identifier] = original
        transcoded += any(
            isinstance(v, str) and any(c in v for c in ("\x91", "\x92", "\x96"))
            for v in (
                props.get(selection.vegetation_label),
                props.get(selection.vegetation_group),
                props.get(selection.dominant_taxa),
            )
        )
        if not isinstance(geometry, Polygon | MultiPolygon) or geometry.is_empty:
            raise LandcoverError("polygon_required")
        if shapely.get_coordinate_dimension(geometry) != 2:
            raise LandcoverError("two_dimensions_required")
        repaired = False
        if not geometry.is_valid:
            if not manifest.repair_invalid:
                raise LandcoverError("invalid_geometry_requires_explicit_repair")
            parts, removed = _polygon_parts(shapely.make_valid(geometry))
            non_polygon_parts += removed
            if not parts:
                raise LandcoverError("repair_has_no_area")
            geometry = unary_union(parts)
            repaired = True
            repairs += 1
        validate_polygon(geometry)
        metric = project(geometry, manifest.crs).intersection(area)
        parts, removed = _polygon_parts(metric)
        non_polygon_parts += removed
        if not parts:
            outside += 1
            continue
        metric = unary_union(parts)
        validate_polygon(metric)
        cleaned = reproject(metric, TO_WGS84)
        if isinstance(cleaned, Polygon):
            cleaned = MultiPolygon([cleaned])
        cleaned = shapely.normalize(cleaned)
        validate_polygon(cleaned)
        selected.update(
            geometry_repaired=repaired,
            mapped_area_m2=metric.area,
            effective_resolution_m=manifest.provenance.effective_resolution_m,
            coverage_status="partial",
            current_ground_cover_verified=False,
        )
        output.append(
            {
                "type": "Feature",
                "id": identifier,
                "properties": selected,
                "geometry": mapping(cleaned),
            }
        )
        metric_geometries.append(metric)
    output.sort(key=lambda f: f["id"])
    versions = {
        "adapter": VERSION,
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "python": platform.python_version(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
            + Path(__file__).with_name("grid.py").read_bytes()
            + Path(__file__).with_name("grid_job.py").read_bytes()
        ).hexdigest(),
    }
    inputs = {"manifest": manifest.model_dump(mode="json"), "engine_versions": versions}
    union_area = unary_union(metric_geometries).area if metric_geometries else 0.0
    summed_area = sum(g.area for g in metric_geometries)
    return {
        "type": "FeatureCollection",
        "schema_version": "landcover-artifact-v1",
        "job_id": hashlib.sha256(canonical_json(inputs)).hexdigest(),
        "geometry_crs": "EPSG:4326",
        "area_crs": "EPSG:6933",
        "inputs": inputs,
        "source": manifest.provenance.model_dump(mode="json"),
        "vintage": {
            "source_year": manifest.source_year,
            "year_meaning": manifest.year_meaning,
            "year_evidence_url": manifest.year_evidence_url,
            "product_production_period": manifest.product_production_period,
            "product_metadata_url": manifest.product_metadata_url,
            "note": "Product production period is not a per-feature acquisition year.",
        },
        "quality": {
            "received": len(data["features"]),
            "output": len(output),
            "duplicate_identities": duplicates,
            "outside_or_boundary_only": outside,
            "repaired_geometries": repairs,
            "non_polygon_parts_removed": non_polygon_parts,
            "legacy_punctuation_transcoded": transcoded,
            "unknown_source_year": sum(f["properties"]["source_year"] is None for f in output),
            "vegetation_counts": dict(
                sorted(Counter(f["properties"]["vegetation_code"] for f in output).items())
            ),
            "summed_mapped_area_m2": summed_area,
            "union_mapped_area_m2": union_area,
            "overlap_area_m2": max(0.0, summed_area - union_area),
        },
        "coverage_status": "partial" if output else "unavailable",
        "negative_inference_allowed": False,
        "grid_mask_status": "unavailable",
        "forest_fraction": None,
        "features": output,
        "transformations": [
            "Allowlisted properties; NFC/legacy punctuation; NC taxa remain unknown",
            "Optional explicit make_valid; 2D Polygon/MultiPolygon only",
            "MR-007 projection to equal-area EPSG:6933, bbox clipping, MultiPolygon normalization",
            "No simplification, binary forest classification, interpolation or score",
        ],
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise LandcoverError("arguments_invalid")


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        artifact = build_artifact(args.manifest)
        created = write_artifact(args.output, canonical_json(artifact))
    except (
        ValueError,
        OSError,
        TypeError,
        KeyError,
        AttributeError,
        ProjError,
        GEOSException,
        RecursionError,
        zlib.error,
    ):
        print(json.dumps({"status": "unavailable", "reason": "landcover_job_failed"}))
        return 2
    print(
        json.dumps(
            {
                "job_id": artifact["job_id"],
                "created": created,
                "coverage_status": artifact["coverage_status"],
                "quality": artifact["quality"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
