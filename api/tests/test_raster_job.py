"""Invented GeoTIFFs, plus one explicitly labelled frozen real SoilGrids WCS capture."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from mycoradar import raster_job as job
from mycoradar.grid_job import canonical_json, write_artifact
from pydantic import ValidationError
from rasterio.io import MemoryFile


def write_source(
    manifest,
    array=None,
    *,
    nodata=-9999,
    crs="EPSG:6933",
    transform=None,
    mask=None,
    scale=1.0,
    offset=0.0,
    unit="m",
):
    values = np.array([[0, 10], [-9999, 20]], dtype="int16") if array is None else array
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=values.shape[1],
            height=values.shape[0],
            count=1,
            dtype=values.dtype,
            crs=crs,
            transform=transform or Affine(10, 0, 0, 0, -10, 20),
            nodata=nodata,
        ) as ds:
            ds.write(values, 1)
            ds.scales = (scale,)
            ds.offsets = (offset,)
            if unit is not None:
                ds.set_band_unit(1, unit)
            if mask is not None:
                ds.write_mask(mask)
        content = memory.read()
    spec = json.loads(manifest.read_bytes())
    (manifest.parent / spec["path"]).write_bytes(content)
    spec["sha256"] = hashlib.sha256(content).hexdigest()
    manifest.write_bytes(canonical_json(spec))


def edit(manifest, **changes):
    spec = json.loads(manifest.read_bytes())
    spec.update(changes)
    manifest.write_bytes(canonical_json(spec))


@pytest.fixture
def manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_bytes(
        canonical_json(
            {
                "schema_version": "raster-manifest-v1",
                "path": "source.tif",
                "sha256": "0" * 64,
                "crs": "EPSG:6933",
                "window": {"row": 0, "column": 0, "height": 2, "width": 2},
                "provenance": {
                    "provider": "Synthetic provider",
                    "product": "Invented terrain raster",
                    "source_url": "https://example.invalid/terrain",
                    "license": "CC0-1.0",
                    "license_url": "https://example.invalid/license",
                    "attribution": "Synthetic test only",
                    "version": "test-1",
                    "fetched_at": "2026-01-01T00:00:00Z",
                    "source_published_at": None,
                    "effective_resolution_m": None,
                    "visibility": "public",
                },
                "variable": "elevation",
                "nature": "synthetic",
                "conversion": {
                    "mode": "embedded",
                    "output_unit": "m",
                    "evidence_url": "https://example.invalid/unit",
                },
            }
        )
    )
    write_source(path)
    return path


def test_zero_elevation_is_data_and_explicit_nodata_remains_null(manifest):
    a = job.build_artifact(manifest)
    assert a["values"] == [[0, 10], [None, 20]]
    assert a["quality"]["valid_pixels"] == 3 and a["quality"]["declared_nodata_pixels"] == 1
    assert a["source_year"] is None and a["effective_resolution_m"] is None
    assert a["window"]["pixel_spacing_x"] == 10 and a["window"]["crs_axis_units"] == [
        "metre",
        "metre",
    ]
    assert a["coverage_status"] == "partial" and a["scores_added"] == 0


def test_internal_mask_cannot_resurrect_an_explicit_nodata_value(manifest):
    write_source(manifest, mask=np.array([[255, 0], [255, 255]], dtype="uint8"))
    a = job.build_artifact(manifest)
    assert a["values"] == [[0, None], [None, 20]]
    assert a["quality"]["gdal_mask_excluded_pixels"] == 1
    assert a["quality"]["nodata_marked_valid_by_mask"] == 1


def test_operator_exclusion_is_separate_from_confirmed_nodata(manifest):
    write_source(manifest, nodata=None)
    edit(
        manifest,
        exclusion={
            "raw_values": [0],
            "reason": "Ambiguous zero, review required",
            "policy_url": "https://example.invalid/policy",
        },
    )
    a = job.build_artifact(manifest)
    assert a["values"][0][0] is None
    assert a["source_raster"]["nodata_kind"] == "not_declared"
    assert (
        a["quality"]["declared_nodata_pixels"] == 0 and a["quality"]["policy_excluded_pixels"] == 1
    )


@pytest.mark.parametrize("mode", ["embedded", "explicit"])
def test_scale_and_offset_are_applied_once(manifest, mode):
    write_source(manifest, scale=0.1, offset=1, unit="m")
    conversion = {"mode": mode, "output_unit": "m", "evidence_url": "https://example.invalid/unit"}
    if mode == "explicit":
        conversion.update(scale=0.1, offset=1)
    edit(manifest, conversion=conversion)
    assert job.build_artifact(manifest)["values"] == [[1, 2], [None, 3]]


def test_explicit_scale_can_fill_absent_embedded_scaling_but_not_conflict(manifest):
    edit(
        manifest,
        conversion={
            "mode": "explicit",
            "scale": 0.1,
            "offset": 0,
            "output_unit": "m",
            "evidence_url": "https://example.invalid/unit",
        },
    )
    assert job.build_artifact(manifest)["values"] == [[0, 1], [None, 2]]
    write_source(manifest, scale=0.01)
    with pytest.raises(job.RasterJobError, match="double_scaling_conflict"):
        job.build_artifact(manifest)


def test_known_band_unit_cannot_be_silently_relabelled(manifest):
    write_source(manifest, unit="kelvin")
    with pytest.raises(job.RasterJobError, match="file_unit_conflict"):
        job.build_artifact(manifest)


def test_missing_nonfinite_and_overflowed_values_do_not_become_zero(manifest):
    array = np.array([[np.nan, np.inf], [1e308, -1e308]], dtype="float64")
    write_source(manifest, array, nodata=np.nan, scale=10)
    a = job.build_artifact(manifest)
    assert a["values"] == [[None, None], [None, None]]
    assert a["coverage_status"] == "unavailable" and a["sample_summary"]["minimum"] is None
    assert a["source_raster"]["nodata_kind"] == "nan"
    assert a["quality"]["raw_nonfinite_pixels"] == 2
    canonical_json(a)


def test_summary_mean_is_finite_for_large_but_finite_values(manifest):
    write_source(manifest, np.full((2, 2), 1e308, dtype="float64"), nodata=None)
    a = job.build_artifact(manifest)
    assert np.isfinite(a["sample_summary"]["mean_over_valid_pixels"])
    assert a["quality"]["valid_pixels"] == 4


def test_range_exclusion_is_reported_without_clamping(manifest):
    edit(manifest, valid_range=[0, 15])
    a = job.build_artifact(manifest)
    assert a["values"] == [[0, 10], [None, None]]
    assert a["quality"]["out_of_range_pixels"] == 2  # includes the separately declared -9999.


def test_window_preserves_native_grid_and_never_pads_outside_extent(manifest):
    edit(manifest, window={"row": 0, "column": 1, "height": 2, "width": 1})
    a = job.build_artifact(manifest)
    assert a["values"] == [[10], [20]] and a["window"]["transform"][2] == 10
    edit(manifest, window={"row": 1, "column": 1, "height": 2, "width": 2})
    with pytest.raises(job.RasterJobError, match="window_outside_dataset"):
        job.build_artifact(manifest)


def test_geographic_grid_step_is_not_metres_or_effective_resolution(manifest):
    write_source(manifest, crs="EPSG:4326", transform=Affine(0.01, 0, 5, 0, -0.01, 44))
    edit(manifest, crs="EPSG:4326", nominal_source_grid_step_m=250)
    a = job.build_artifact(manifest)
    assert a["window"]["crs_axis_units"] == ["degree", "degree"]
    assert a["window"]["pixel_spacing_x"] == 0.01 and a["effective_resolution_m"] is None


@pytest.mark.parametrize("kind", ["missing", "mismatch", "rotated"])
def test_ambiguous_georeferencing_is_refused(manifest, kind):
    if kind == "missing":
        write_source(manifest, crs=None)
        code = "crs_missing"
    elif kind == "mismatch":
        edit(manifest, crs="EPSG:3857")
        code = "crs_mismatch"
    else:
        write_source(manifest, transform=Affine(10, 1, 0, 1, -10, 20))
        code = "north_up_affine_required"
    with pytest.raises(job.RasterJobError, match=code):
        job.build_artifact(manifest)


def test_band_and_window_budgets_are_explicit(manifest):
    edit(manifest, band=2)
    with pytest.raises(job.RasterJobError, match="band_outside_dataset"):
        job.build_artifact(manifest)
    edit(manifest, band=1, window={"row": 0, "column": 0, "height": 1000, "width": 1000})
    with pytest.raises(ValidationError):
        job.build_artifact(manifest)


def test_large_compressed_blocks_are_rejected_before_read(manifest, monkeypatch):
    monkeypatch.setattr(job, "MAX_BLOCK_PIXELS", 1)
    with pytest.raises(job.RasterJobError, match="decompression_block_budget"):
        job.build_artifact(manifest)


def test_path_containment_and_hash_are_enforced(manifest):
    edit(manifest, sha256="0" * 64)
    with pytest.raises(job.RasterJobError, match="checksum"):
        job.build_artifact(manifest)
    edit(manifest, path="../private.tif")
    with pytest.raises(job.RasterJobError, match="input_path_refused"):
        job.build_artifact(manifest)


def test_vrt_is_not_allowed_to_reference_external_files(manifest):
    content = (
        b'<VRTDataset rasterXSize="2" rasterYSize="2">'
        b'<VRTRasterBand dataType="Int16" band="1"><SimpleSource>'
        b"<SourceFilename>/etc/passwd</SourceFilename>"
        b"</SimpleSource></VRTRasterBand></VRTDataset>"
    )
    (manifest.parent / "source.tif").write_bytes(content)
    edit(manifest, sha256=hashlib.sha256(content).hexdigest())
    with pytest.raises(rasterio.errors.RasterioError):
        job.build_artifact(manifest)


def test_memory_reader_ignores_unreviewed_external_mask_sidecars(manifest):
    first = job.build_artifact(manifest)["values"]
    (manifest.parent / "source.tif.msk").write_bytes(b"PRIVATE_INVALID_SIDECAR")
    (manifest.parent / "source.tif.aux.xml").write_text("<invalid>PRIVATE_SENTINEL</invalid>")
    assert job.build_artifact(manifest)["values"] == first


def test_categorical_values_cannot_be_scaled_or_averaged(manifest):
    edit(manifest, nature="categorical_map")
    a = job.build_artifact(manifest)
    assert a["sample_summary"]["mean_over_valid_pixels"] is None
    write_source(manifest, scale=0.1)
    with pytest.raises(job.RasterJobError, match="categorical_scaling"):
        job.build_artifact(manifest)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_year": 2027, "year_evidence_url": "https://example.invalid/year"},
        {"source_year": 2020},
        {"data_cutoff": "2026-01-02T00:00:00Z"},
        {"nature": "soil_prediction"},
        {"depth_cm": [5, 0]},
    ],
)
def test_scientific_metadata_cannot_be_invented_or_backdated(manifest, changes):
    edit(manifest, **changes)
    with pytest.raises(ValidationError):
        job.build_artifact(manifest)


def test_output_is_deterministic_and_not_overwritten_on_replay(manifest, tmp_path):
    a = canonical_json(job.build_artifact(manifest))
    assert a == canonical_json(job.build_artifact(manifest))
    output = tmp_path / "result.json"
    assert write_artifact(output, a) is True
    before = output.stat().st_mtime_ns
    assert write_artifact(output, a) is False and before == output.stat().st_mtime_ns
    with pytest.raises(ValueError):
        write_artifact(output, b"other")


def test_cli_failure_does_not_echo_private_paths_or_documents(manifest, tmp_path, capsys):
    argv = ["--manifest", str(manifest), "--output", str(tmp_path / "result.json")]
    assert job.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["created"] is True
    manifest.write_text('{"private":"PRIVATE_SENTINEL"}')
    assert job.main(argv) == 2
    text = capsys.readouterr()
    assert "PRIVATE_SENTINEL" not in text.out + text.err
    assert json.loads(text.out)["status"] == "unavailable"


def test_frozen_real_soilgrids_capture_keeps_undocumented_zeros_ambiguous():
    path = Path(__file__).resolve().parents[2] / "data/rasters/soilgrids-sample/manifest.json"
    a = job.build_artifact(path)
    assert a["quality"]["pixel_count"] == 64 and a["quality"]["valid_pixels"] == 56
    assert (
        a["quality"]["policy_excluded_pixels"] == 8 and a["quality"]["declared_nodata_pixels"] == 0
    )
    assert a["source_raster"]["nodata_kind"] == "not_declared"
    assert (
        a["nature"] == "soil_prediction"
        and a["model_statistic"] == "mean"
        and a["depth_cm"] == (0, 5)
    )
    assert a["source_year"] is None and a["data_cutoff"] is None
    assert a["nominal_source_grid_step_m"] == 250 and a["effective_resolution_m"] is None
