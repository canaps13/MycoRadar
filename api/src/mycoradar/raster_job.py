"""Read reviewed local GeoTIFF windows offline, retaining masks, units and unknowns."""

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
from typing import Annotated, Any, Literal, Never, Self

import numpy as np
import pyproj
import rasterio  # type: ignore[import-untyped]
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator
from rasterio.errors import RasterioError  # type: ignore[import-untyped]
from rasterio.io import MemoryFile  # type: ignore[import-untyped]
from rasterio.windows import Window  # type: ignore[import-untyped]

from mycoradar.grid_job import Provenance, canonical_json, write_artifact

MAX_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 100000
MAX_BLOCK_PIXELS = 1000000
Text = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class RasterJobError(ValueError):
    """Fixed operator diagnostics, without paths or upstream response text."""


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class PixelWindow(Contract):
    row: Annotated[int, Field(strict=True, ge=0)]
    column: Annotated[int, Field(strict=True, ge=0)]
    height: Annotated[int, Field(strict=True, gt=0)]
    width: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.height * self.width > MAX_PIXELS:
            raise ValueError("pixel budget exceeded")
        return self


class Conversion(Contract):
    mode: Literal["embedded", "explicit"]
    scale: Number | None = None
    offset: Number | None = None
    output_unit: Text
    expected_file_unit: Text | None = None
    evidence_url: Text

    @model_validator(mode="after")
    def unambiguous(self) -> Self:
        if self.mode == "embedded":
            if self.scale is not None or self.offset is not None:
                raise ValueError("embedded scaling cannot be applied a second time")
        elif self.scale is None or self.offset is None or self.scale == 0:
            raise ValueError("explicit finite nonzero scale and offset required")
        return self


class Exclusion(Contract):
    raw_values: tuple[Number, ...]
    reason: Text
    policy_url: Text


class Manifest(Contract):
    schema_version: Literal["raster-manifest-v1"]
    path: Text
    sha256: Digest
    band: Annotated[int, Field(strict=True, gt=0)] = 1
    crs: str
    window: PixelWindow
    provenance: Provenance
    variable: Text
    nature: Literal["soil_prediction", "terrain_model", "categorical_map", "synthetic"]
    model_statistic: Text | None = None
    depth_cm: tuple[Number, Number] | None = None
    conversion: Conversion
    valid_range: tuple[Number, Number] | None = None
    exclusion: Exclusion | None = None
    source_year: Annotated[int, Field(strict=True, ge=1800, le=2100)] | None = None
    year_evidence_url: Text | None = None
    data_cutoff: AwareDatetime | None = None
    nominal_source_grid_step_m: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def scientific_metadata(self) -> Self:
        if self.source_year is not None and (
            self.source_year > self.provenance.fetched_at.year or self.year_evidence_url is None
        ):
            raise ValueError("known source year requires dated evidence")
        if self.data_cutoff is not None and self.data_cutoff > self.provenance.fetched_at:
            raise ValueError("data cutoff cannot follow capture")
        if self.valid_range is not None and self.valid_range[0] > self.valid_range[1]:
            raise ValueError("invalid value range")
        if self.depth_cm is not None and not 0 <= self.depth_cm[0] < self.depth_cm[1]:
            raise ValueError("invalid depth interval")
        if self.nature == "soil_prediction" and (
            self.depth_cm is None or self.model_statistic is None
        ):
            raise ValueError("soil depth and prediction statistic required")
        if self.nature == "categorical_map" and self.valid_range is not None:
            raise ValueError("categorical maps require a separate codebook, not a numeric range")
        return self


def _conversion(dataset: Any, manifest: Manifest) -> tuple[float, float, dict[str, Any]]:
    index = manifest.band - 1
    embedded_scale, embedded_offset = float(dataset.scales[index]), float(dataset.offsets[index])
    if not all(math.isfinite(v) for v in (embedded_scale, embedded_offset)) or embedded_scale == 0:
        raise RasterJobError("embedded_conversion_invalid")
    conversion = manifest.conversion
    unit = dataset.units[index]
    expected = conversion.expected_file_unit or conversion.output_unit
    if unit is not None and unit != expected:
        raise RasterJobError("file_unit_conflict")
    if conversion.mode == "embedded":
        scale, offset = embedded_scale, embedded_offset
    else:
        assert conversion.scale is not None and conversion.offset is not None
        scale, offset = conversion.scale, conversion.offset
        if (embedded_scale, embedded_offset) not in {(1.0, 0.0), (scale, offset)}:
            raise RasterJobError("double_scaling_conflict")
    if manifest.nature == "categorical_map" and (scale, offset) != (1.0, 0.0):
        raise RasterJobError("categorical_scaling_refused")
    return (
        scale,
        offset,
        {
            **conversion.model_dump(mode="json"),
            "applied_scale": scale,
            "applied_offset": offset,
            "embedded_scale": embedded_scale,
            "embedded_offset": embedded_offset,
            "file_unit": unit,
            "note": "Exactly one conversion; file values are read without automatic scale/offset.",
        },
    )


def _read(content: bytes, manifest: Manifest) -> dict[str, Any]:
    with (
        rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_PAM_ENABLED="NO",
            GDAL_GEOREF_SOURCES="INTERNAL",
            GDAL_NUM_THREADS="1",
            GDAL_CACHEMAX=16 * 1024 * 1024,
        ),
        MemoryFile(content) as memory,
        memory.open(driver="GTiff") as dataset,
    ):
        if dataset.driver != "GTiff" or dataset.subdatasets:
            raise RasterJobError("standalone_geotiff_required")
        if dataset.crs is None:
            raise RasterJobError("crs_missing")
        if dataset.gcps[0] or dataset.rpcs is not None:
            raise RasterJobError("non_affine_georeferencing_refused")
        crs = pyproj.CRS.from_user_input(dataset.crs.to_wkt())
        if not crs.equals(pyproj.CRS.from_user_input(manifest.crs), ignore_axis_order=True):
            raise RasterJobError("crs_mismatch")
        if not 1 <= manifest.band <= dataset.count:
            raise RasterJobError("band_outside_dataset")
        if (
            dataset.width > 1000000
            or dataset.height > 1000000
            or dataset.width * dataset.height > 25000000
        ):
            raise RasterJobError("dataset_dimension_budget_exceeded")
        index = manifest.band - 1
        dtype = np.dtype(dataset.dtypes[index])
        if dtype.kind not in "iuf" or (dtype.kind in "iu" and dtype.itemsize > 4):
            raise RasterJobError("dtype_unsupported")
        if any(h * w > MAX_BLOCK_PIXELS for h, w in dataset.block_shapes):
            raise RasterJobError("decompression_block_budget_exceeded")
        transform = dataset.transform
        if not all(math.isfinite(v) for v in tuple(transform)) or not (
            transform.a > 0 and transform.e < 0 and transform.b == transform.d == 0
        ):
            raise RasterJobError("north_up_affine_required")
        selection = manifest.window
        if (
            selection.row + selection.height > dataset.height
            or selection.column + selection.width > dataset.width
        ):
            raise RasterJobError("window_outside_dataset")
        window = Window(selection.column, selection.row, selection.width, selection.height)
        scale, offset, conversion = _conversion(dataset, manifest)
        raw = dataset.read(manifest.band, window=window, out_dtype="float64", masked=False)
        mask = dataset.read_masks(manifest.band, window=window)
        finite = np.isfinite(raw)
        nodata = dataset.nodatavals[index]
        declared_missing = np.zeros(raw.shape, dtype=bool)
        nodata_kind = "not_declared"
        nodata_number = None
        if nodata is not None:
            if math.isnan(nodata):
                declared_missing = np.isnan(raw)
                nodata_kind = "nan"
            else:
                declared_missing = raw == nodata
                nodata_kind = "number" if math.isfinite(nodata) else "infinite"
                nodata_number = nodata if math.isfinite(nodata) else None
        policy_missing = np.zeros(raw.shape, dtype=bool)
        if manifest.exclusion is not None:
            policy_missing = np.isin(raw, manifest.exclusion.raw_values)
        with np.errstate(over="ignore", invalid="ignore"):
            physical = raw * scale + offset
        transformed_nonfinite = ~np.isfinite(physical)
        out_of_range = np.zeros(raw.shape, dtype=bool)
        if manifest.valid_range is not None:
            out_of_range = (physical < manifest.valid_range[0]) | (
                physical > manifest.valid_range[1]
            )
        invalid = (
            (mask == 0)
            | declared_missing
            | ~finite
            | policy_missing
            | transformed_nonfinite
            | out_of_range
        )
        valid = physical[~invalid]
        if manifest.nature == "categorical_map" and np.any(valid != np.floor(valid)):
            raise RasterJobError("categorical_noninteger_value")
        values = [
            [
                None if invalid[row, col] else float(physical[row, col])
                for col in range(selection.width)
            ]
            for row in range(selection.height)
        ]
        window_transform = dataset.window_transform(window)
        units = [axis.unit_name for axis in crs.axis_info]
        return {
            "source_raster": {
                "driver": dataset.driver,
                "width": dataset.width,
                "height": dataset.height,
                "count": dataset.count,
                "band": manifest.band,
                "dtype": str(dtype),
                "crs_wkt": crs.to_wkt(),
                "crs_authority": crs.to_authority(),
                "transform": list(transform)[:6],
                "block_shapes": dataset.block_shapes,
                "pixel_interpretation": dataset.tags().get("AREA_OR_POINT"),
                "nodata_kind": nodata_kind,
                "nodata_value": nodata_number,
                "mask_flags": [flag.name for flag in dataset.mask_flag_enums[index]],
            },
            "window": {
                **selection.model_dump(),
                "transform": list(window_transform)[:6],
                "pixel_spacing_x": transform.a,
                "pixel_spacing_y": abs(transform.e),
                "crs_axis_units": units,
            },
            "conversion": conversion,
            "values": values,
            "quality": {
                "pixel_count": int(raw.size),
                "valid_pixels": int(valid.size),
                "invalid_pixels": int(np.count_nonzero(invalid)),
                "declared_nodata_pixels": int(np.count_nonzero(declared_missing)),
                "gdal_mask_excluded_pixels": int(np.count_nonzero(mask == 0)),
                "raw_nonfinite_pixels": int(np.count_nonzero(~finite)),
                "policy_excluded_pixels": int(np.count_nonzero(policy_missing)),
                "conversion_nonfinite_pixels": int(np.count_nonzero(transformed_nonfinite)),
                "out_of_range_pixels": int(np.count_nonzero(out_of_range)),
                "nodata_marked_valid_by_mask": int(
                    np.count_nonzero(declared_missing & (mask != 0))
                ),
                "note": "Counts can overlap; explicit nodata always overrides a valid GDAL mask.",
            },
            "sample_summary": {
                "minimum": float(np.min(valid)) if valid.size else None,
                "maximum": float(np.max(valid)) if valid.size else None,
                "mean_over_valid_pixels": (
                    float(np.mean(valid / np.max(np.abs(valid))) * np.max(np.abs(valid)))
                    if np.max(np.abs(valid)) != 0
                    else 0.0
                )
                if valid.size and manifest.nature != "categorical_map"
                else None,
            },
            "coverage_status": "partial" if valid.size else "unavailable",
        }


def build_artifact(manifest_path: Path) -> dict[str, Any]:
    if manifest_path.stat().st_size > 100000:
        raise RasterJobError("manifest_budget_exceeded")
    manifest = Manifest.model_validate_json(manifest_path.read_bytes())
    root = manifest_path.parent.resolve()
    path = (root / manifest.path).resolve()
    if not path.is_relative_to(root):
        raise RasterJobError("input_path_refused")
    if path.stat().st_size > MAX_BYTES:
        raise RasterJobError("input_byte_budget_exceeded")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.sha256:
        raise RasterJobError("checksum_mismatch")
    result = _read(content, manifest)
    versions = {
        "adapter": "raster-window-v1",
        "rasterio": rasterio.__version__,
        "gdal": rasterio.__gdal_version__,
        "numpy": np.__version__,
        "pyproj": pyproj.__version__,
        "proj": pyproj.proj_version_str,
        "python": platform.python_version(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "implementation_sha256": hashlib.sha256(
            Path(__file__).read_bytes() + Path(__file__).with_name("grid_job.py").read_bytes()
        ).hexdigest(),
    }
    inputs = {"manifest": manifest.model_dump(mode="json"), "engine_versions": versions}
    result.update(
        schema_version="raster-artifact-v1",
        job_id=hashlib.sha256(canonical_json(inputs)).hexdigest(),
        inputs=inputs,
        source=manifest.provenance.model_dump(mode="json"),
        variable=manifest.variable,
        nature=manifest.nature,
        model_statistic=manifest.model_statistic,
        depth_cm=manifest.depth_cm,
        source_year=manifest.source_year,
        year_evidence_url=manifest.year_evidence_url,
        data_cutoff=manifest.data_cutoff.isoformat() if manifest.data_cutoff else None,
        nominal_source_grid_step_m=manifest.nominal_source_grid_step_m,
        effective_resolution_m=manifest.provenance.effective_resolution_m,
        exclusion_policy=manifest.exclusion.model_dump(mode="json") if manifest.exclusion else None,
        transformations=[
            "Reviewed local standalone GeoTIFF in memory; internal metadata/masks only",
            "Native integer pixel window; no reprojection, interpolation or gap filling",
            "One unit conversion; missing, nonfinite and policy-excluded values remain null",
        ],
        public_layers_added=0,
        scores_added=0,
    )
    return result


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise RasterJobError("arguments_invalid")


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        result = build_artifact(args.manifest)
        created = write_artifact(args.output, canonical_json(result))
    except (
        ValueError,
        OSError,
        TypeError,
        KeyError,
        AttributeError,
        RasterioError,
        pyproj.exceptions.ProjError,
        RecursionError,
    ):
        print(json.dumps({"status": "unavailable", "reason": "raster_job_failed"}))
        return 2
    print(
        json.dumps(
            {
                "job_id": result["job_id"],
                "created": created,
                "coverage_status": result["coverage_status"],
                "quality": result["quality"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
