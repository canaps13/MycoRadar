"""Invented environmental supports only; no real station, occurrence or location."""

import json
import socket
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from mycoradar.feature_job import MAX_BYTES, build_artifact, main
from mycoradar.grid_job import canonical_json, write_artifact
from shapely.geometry import box, mapping


def polygon(west: float = 0, east: float = 0.008) -> dict[str, Any]:
    return dict(mapping(box(west, 0, east, 0.004)))


@pytest.fixture
def definition() -> dict[str, Any]:
    return {
        "schema_version": "feature-join-manifest-v1",
        "input_kind": "synthetic",
        "geometry_crs": "EPSG:4326",
        "as_of": "2026-01-03T00:00:00Z",
        "target_at": "2026-01-03T00:00:00Z",
        "cells": [{"cell_id": "test:cell", "display_cell_size_m": 1000, "geometry": polygon()}],
        "layers": [
            {
                "feature_id": "test:continuous",
                "unit": "test-unit",
                "aggregation": "area_weighted_mean",
                "value_kind": "continuous_intensive",
                "temporal_kind": "historical_observation",
                "valid_from": "2026-01-02T00:00:00Z",
                "valid_until": "2026-01-04T00:00:00Z",
                "source_data_cutoff": "2026-01-01T00:00:00Z",
                "source": {
                    "id": "test:source",
                    "provider": "Synthetic fixture",
                    "product": "Invented values, not observations",
                    "version": "test-v1",
                    "source_url": "https://example.invalid/synthetic",
                    "license": "CC0-1.0",
                    "license_url": "https://example.invalid/license",
                    "attribution": "MycoRadar, synthetic test only",
                    "sha256": "a" * 64,
                    "source_published_at": "2026-01-02T00:00:00Z",
                    "fetched_at": "2026-01-02T12:00:00Z",
                    "effective_resolution_m": None,
                    "transformations": [],
                    "visibility": "public",
                },
                "patches": [
                    {"id": "test:left", "value": 2.0, "geometry": polygon(0, 0.002)},
                    {"id": "test:right", "value": 6.0, "geometry": polygon(0.002, 0.008)},
                ],
            }
        ],
    }


def run(tmp_path: Path, definition: dict[str, Any]) -> dict[str, Any]:
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical_json(definition))
    return build_artifact(path)


def test_area_weighting_not_arithmetic_mean_and_unknown_resolution(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    artifact = run(tmp_path, definition)
    row = artifact["features"][0]
    assert row["value"] == pytest.approx(5)
    assert row["status"] == "available"
    assert row["usable_area_fraction"] == 1
    assert row["effective_resolution_m"] is None
    assert row["display_cell_size_m"] == 1000
    assert row["location_uncertainty_m"] is None
    assert artifact["status"] == "partial"
    assert artifact["admitted_for_scientific_use"] is False
    assert artifact["input_kind"] == "synthetic"
    assert artifact["sources"][0]["license"] == "CC0-1.0"
    assert "score" not in canonical_json(artifact).decode()


@pytest.mark.parametrize("field", ["source_published_at", "fetched_at", "source_data_cutoff"])
def test_each_future_timestamp_withholds_values(
    tmp_path: Path, definition: dict[str, Any], field: str
) -> None:
    layer = definition["layers"][0]
    if field == "source_data_cutoff":
        layer[field] = "2026-01-04T00:00:00Z"
        layer["source"]["fetched_at"] = "2026-01-04T12:00:00Z"
    else:
        layer["source"][field] = "2026-01-04T00:00:00Z"
        if field == "source_published_at":
            layer["source"]["fetched_at"] = "2026-01-04T12:00:00Z"
    row = run(tmp_path, definition)["features"][0]
    assert row["value"] is None
    assert row["reason"] == "source_not_available_as_of"
    assert row["contributing_patch_ids"] == []


@pytest.mark.parametrize("field", ["source_published_at", "source_data_cutoff"])
def test_unknown_source_age_cannot_be_replaced_by_capture_time(
    tmp_path: Path, definition: dict[str, Any], field: str
) -> None:
    layer = definition["layers"][0]
    (layer if field == "source_data_cutoff" else layer["source"])[field] = None
    row = run(tmp_path, definition)["features"][0]
    assert row["value"] is None
    assert row["reason"] == "source_time_unknown"


@pytest.mark.parametrize("target", ["2026-01-01T23:59:59Z", "2026-01-04T00:00:00Z"])
def test_half_open_validity_interval(
    tmp_path: Path, definition: dict[str, Any], target: str
) -> None:
    definition["as_of"] = "2025-12-31T00:00:00Z"
    layer = definition["layers"][0]
    layer["source_data_cutoff"] = "2025-12-29T00:00:00Z"
    layer["source"]["source_published_at"] = "2025-12-30T00:00:00Z"
    layer["source"]["fetched_at"] = "2025-12-30T00:00:00Z"
    definition["target_at"] = target
    assert run(tmp_path, definition)["features"][0]["reason"] == "outside_validity_interval"


def test_source_resolution_is_not_the_join_resolution(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    definition["layers"][0]["source"]["effective_resolution_m"] = 250.0
    row = run(tmp_path, definition)["features"][0]
    assert row["source_effective_resolution_m"] == 250
    assert row["effective_resolution_m"] is None
    assert row["display_cell_size_m"] == 1000


def test_equal_instant_with_offset_is_not_future(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    definition["layers"][0]["source"]["fetched_at"] = "2026-01-03T01:00:00+01:00"
    assert run(tmp_path, definition)["features"][0]["value"] == pytest.approx(5)


@pytest.mark.parametrize("case", ["gap", "missing", "empty", "overlap", "null_overlap"])
def test_no_renormalization_over_missing_area_and_no_double_counting(
    tmp_path: Path, definition: dict[str, Any], case: str
) -> None:
    patches = definition["layers"][0]["patches"]
    if case == "gap":
        patches[1]["geometry"] = polygon(0.004, 0.008)
    elif case == "missing":
        patches[1]["value"] = None
    elif case == "empty":
        patches.clear()
    else:
        patches[1]["geometry"] = polygon(0.001, 0.008)
        if case == "null_overlap":
            patches[0]["value"] = None
    row = run(tmp_path, definition)["features"][0]
    assert row["value"] is None
    assert row["status"] == "unavailable"
    assert row["contributing_patch_ids"] == []
    assert row["reason"] == (
        "overlapping_supports" if "overlap" in case else "incomplete_usable_coverage"
    )
    if case == "missing":
        assert row["usable_area_fraction"] == pytest.approx(0.25)


def test_zero_is_not_missing_and_boundary_contact_is_not_area(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    layer = definition["layers"][0]
    layer["patches"] = [
        {"id": "test:full", "value": 0.0, "geometry": polygon()},
        {"id": "test:edge", "value": 999.0, "geometry": polygon(0.008, 0.01)},
    ]
    row = run(tmp_path, definition)["features"][0]
    assert row["value"] == 0
    assert row["contributing_patch_ids"] == ["test:full"]


def test_holes_are_missing_not_zero(tmp_path: Path, definition: dict[str, Any]) -> None:
    geometry = polygon()
    geometry["coordinates"] = [geometry["coordinates"][0], polygon(0.002, 0.004)["coordinates"][0]]
    # Interior hole must not touch the outer boundary.
    geometry["coordinates"][1] = [
        [0.002, 0.001],
        [0.004, 0.001],
        [0.004, 0.003],
        [0.002, 0.003],
        [0.002, 0.001],
    ]
    definition["layers"][0]["patches"] = [{"id": "test:hole", "value": 1.0, "geometry": geometry}]
    row = run(tmp_path, definition)["features"][0]
    assert row["value"] is None
    assert row["usable_area_fraction"] < 1


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_cell",
        "duplicate_feature",
        "duplicate_patch",
        "forecast",
        "categorical",
        "private",
        "extra",
        "future_cutoff",
        "naive_time",
        "reversed_validity",
        "publication_after_capture",
        "unknown_crs",
        "bool_value",
        "string_value",
        "bool_coordinate",
        "string_coordinate",
        "unclosed",
        "invalid_geometry",
        "too_large",
    ],
)
def test_invalid_or_unsupported_inputs_fail_entire_job(
    tmp_path: Path, definition: dict[str, Any], case: str
) -> None:
    layer = definition["layers"][0]
    if case == "duplicate_cell":
        definition["cells"] *= 2
    elif case == "duplicate_feature":
        definition["layers"] *= 2
    elif case == "duplicate_patch":
        layer["patches"] *= 2
    elif case == "forecast":
        layer["temporal_kind"] = "forecast"
    elif case == "categorical":
        layer["value_kind"] = "categorical"
    elif case == "private":
        layer["source"]["visibility"] = "private"
    elif case == "extra":
        layer["occurrence_coordinates"] = [42, 3]
    elif case == "future_cutoff":
        definition["as_of"] = "2026-01-04T00:00:00Z"
    elif case == "naive_time":
        definition["as_of"] = "2026-01-03T00:00:00"
    elif case == "reversed_validity":
        layer["valid_until"] = layer["valid_from"]
    elif case == "publication_after_capture":
        layer["source"]["source_published_at"] = "2026-01-03T00:00:00Z"
    elif case == "unknown_crs":
        definition["geometry_crs"] = "unknown"
    elif case.endswith("_value"):
        layer["patches"][0]["value"] = True if case == "bool_value" else "2"
    elif case.endswith("_coordinate"):
        geometry = json.loads(json.dumps(polygon()))
        geometry["coordinates"][0][0][0] = True if case == "bool_coordinate" else "0"
        definition["cells"][0]["geometry"] = geometry
    elif case == "unclosed":
        geometry = json.loads(json.dumps(polygon()))
        geometry["coordinates"][0][-1] = [0.001, 0.001]
        definition["cells"][0]["geometry"] = geometry
    elif case == "invalid_geometry":
        definition["cells"][0]["geometry"] = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [0.01, 0.01], [0, 0.01], [0.01, 0], [0, 0]]],
        }
    elif case == "too_large":
        definition["cells"][0]["geometry"] = polygon(0, 100)
    with pytest.raises(ValueError):
        run(tmp_path, definition)


def test_replay_is_atomic_without_overwrite_and_versioned(
    tmp_path: Path, definition: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Network access forbidden")

    monkeypatch.setattr(socket, "socket", forbidden)
    first = run(tmp_path, definition)
    assert canonical_json(first) == canonical_json(run(tmp_path, definition))
    output = tmp_path / "result.json"
    assert write_artifact(output, canonical_json(first)) is True
    modified = output.stat().st_mtime_ns
    assert write_artifact(output, canonical_json(first)) is False
    assert output.stat().st_mtime_ns == modified
    definition["as_of"] = "2026-01-02T12:00:00Z"
    second = run(tmp_path, definition)
    assert first["job_id"] != second["job_id"]
    with pytest.raises(ValueError):
        write_artifact(output, canonical_json(second))
    assert output.read_bytes() == canonical_json(first)


def test_cli_failure_has_no_private_details_and_preserves_output(
    tmp_path: Path,
    definition: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    definition["layers"][0]["unexpected_private_field"] = "PRIVATE_SENTINEL"
    path = tmp_path / "private-location.json"
    path.write_bytes(canonical_json(definition))
    output = tmp_path / "output.json"
    output.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["job", "--manifest", str(path), "--output", str(output)])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == '{"error":"feature_job_failed"}\n'
    assert captured.err == ""
    assert output.read_text(encoding="utf-8") == "existing"


def test_cli_replay_and_input_byte_budget(
    tmp_path: Path,
    definition: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(tmp_path, definition)
    output = tmp_path / "output.json"
    monkeypatch.setattr(
        sys, "argv", ["job", "--manifest", str(tmp_path / "manifest.json"), "--output", str(output)]
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["created"] is True
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["created"] is False
    path = tmp_path / "manifest.json"
    path.write_bytes(b" " * (MAX_BYTES + 1))
    assert main() == 2
    assert json.loads(capsys.readouterr().out) == {"error": "feature_job_failed"}


def test_pair_budget(tmp_path: Path, definition: dict[str, Any]) -> None:
    definition["cells"] = [
        dict(definition["cells"][0], cell_id=f"test:cell-{i}") for i in range(101)
    ]
    layer = definition["layers"][0]
    layer["patches"] = [dict(layer["patches"][0], id=f"test:patch-{i}") for i in range(1000)]
    with pytest.raises(ValueError, match="Join work budget"):
        run(tmp_path, definition)


def test_overlap_budget(
    tmp_path: Path, definition: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import mycoradar.feature_job as job

    monkeypatch.setattr(job, "MAX_PAIRS", 5)
    definition["layers"][0]["patches"] = [
        {"id": f"test:p-{i}", "value": 2.0, "geometry": polygon(i * 0.002, (i + 1) * 0.002)}
        for i in range(3)
    ]
    with pytest.raises(ValueError, match="Overlap work budget"):
        run(tmp_path, definition)


def test_unsupported_licence(tmp_path: Path, definition: dict[str, Any]) -> None:
    definition["layers"][0]["source"]["license"] = "unknown"
    with pytest.raises(ValueError, match="supported open licence"):
        run(tmp_path, definition)


def test_data_after_capture_is_incoherent(tmp_path: Path, definition: dict[str, Any]) -> None:
    definition["layers"][0]["source_data_cutoff"] = "2026-01-02T13:00:00Z"
    with pytest.raises(ValueError, match="Data cutoff cannot postdate acquisition"):
        run(tmp_path, definition)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_values(tmp_path: Path, definition: dict[str, Any], bad: str) -> None:
    raw = canonical_json(definition).decode().replace('"value":2.0', '"value":' + bad)
    path = tmp_path / "manifest.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        build_artifact(path)


def test_tiny_positive_overlap_is_not_rounded_away(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    definition["layers"][0]["patches"][1]["geometry"] = polygon(0.002 - 1e-14, 0.008)
    assert run(tmp_path, definition)["features"][0]["reason"] == "overlapping_supports"


def test_ineligible_invalid_geometry_is_still_rejected(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    definition["layers"][0]["source_data_cutoff"] = None
    definition["layers"][0]["patches"][0]["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.01, 0.01], [0, 0.01], [0.01, 0], [0, 0]]],
    }
    with pytest.raises(ValueError):
        run(tmp_path, definition)


def test_layer_order_does_not_change_values(tmp_path: Path, definition: dict[str, Any]) -> None:
    second = deepcopy(definition["layers"][0])
    second["feature_id"] = "test:another"
    definition["layers"].append(second)
    first = run(tmp_path, definition)
    definition["layers"].reverse()
    other = run(tmp_path, definition)
    assert first["features"] == other["features"]
    # Input bytes are intentionally part of identity, even for a mere reordering.
    assert first["job_id"] != other["job_id"]


TIME_PATHS = [
    ("as_of",),
    ("target_at",),
    ("layers", 0, "valid_from"),
    ("layers", 0, "valid_until"),
    ("layers", 0, "source_data_cutoff"),
    ("layers", 0, "source", "fetched_at"),
    ("layers", 0, "source", "source_published_at"),
]


@pytest.mark.parametrize("path", TIME_PATHS)
@pytest.mark.parametrize("representation", ["integer", "float", "epoch_string", "space"])
def test_dates_require_explicit_strings_even_when_epoch_would_be_equivalent(
    tmp_path, definition, path, representation
):
    parent = definition
    for key in path[:-1]:
        parent = parent[key]
    value = parent[path[-1]]
    epoch = int(datetime.fromisoformat(value).timestamp())
    parent[path[-1]] = {
        "integer": epoch,
        "float": float(epoch),
        "epoch_string": str(epoch),
        "space": value.replace("T", " "),
    }[representation]
    with pytest.raises(ValueError):
        run(tmp_path, definition)


def test_all_explicit_offsets_preserve_the_same_join_instants(tmp_path, definition):
    for path in TIME_PATHS:
        parent = definition
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = (
            datetime.fromisoformat(parent[path[-1]])
            .astimezone(timezone(timedelta(hours=5, minutes=30)))
            .isoformat()
        )
    assert run(tmp_path, definition)["features"][0]["value"] == pytest.approx(5)


def test_epoch_source_date_never_publishes_partial_artifact(
    tmp_path, definition, monkeypatch, capsys
):
    source = definition["layers"][0]["source"]
    source["fetched_at"] = int(datetime.fromisoformat(source["fetched_at"]).timestamp())
    path = tmp_path / "PRIVATE_MANIFEST.json"
    path.write_bytes(canonical_json(definition))
    output = tmp_path / "output.json"
    monkeypatch.setattr(
        sys, "argv", ["feature-job", "--manifest", str(path), "--output", str(output)]
    )
    assert main() == 2 and not output.exists()
    captured = capsys.readouterr()
    assert captured.err == "" and json.loads(captured.out) == {"error": "feature_job_failed"}
    assert "PRIVATE_MANIFEST" not in captured.out
