"""Invented partition metadata: hashes, times and thresholds have no scientific meaning."""

import hashlib
import json
import socket
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from mycoradar.evaluation_protocol import GROUPS, MAX_BYTES, Plan, audit_file, main


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def definition() -> dict[str, Any]:
    rows = []
    for i in range(4):
        day = f"202{3 if i < 2 else 4}-{1 if i % 2 == 0 else 2:02d}-01"
        row = {
            "record_sha256": digest(f"invented-record-{i}"),
            "split": "development" if i < 2 else "test",
            "inner_fold": i if i < 2 else None,
            "time_block_sha256": digest(f"invented-month-{day[:7]}"),
            "event_start": f"{day}T00:00:00Z",
            "event_end": f"{day}T01:00:00Z",
            "prediction_at": f"{day}T00:00:00Z",
            "feature_data_cutoff": "2022-12-31T00:00:00Z",
            "feature_available_at": "2022-12-31T12:00:00Z",
            "label_available_at": f"{day}T02:00:00Z",
            "nearest_development_distance_m": 2000.0 if i >= 2 else None,
        }
        for group in GROUPS:
            row[group] = digest(f"invented-{group}-{i}")
        rows.append(row)
    return {
        "schema_version": "evaluation-plan-v1",
        "input_kind": "synthetic",
        "observation_basis": "presence_only",
        "state": "frozen",
        "frozen_at": "2025-01-01T00:00:00Z",
        "model_selection_started_at": "2025-01-02T00:00:00Z",
        "test_labels_accessed_at": None,
        "pilot_admission_sha256": digest("invented-admission-not-real"),
        "source_manifest_sha256": digest("invented-source-not-real"),
        "taxon_scope_sha256": digest("invented-taxon-not-real"),
        "territory_scope_sha256": digest("invented-territory-not-real"),
        "sampling_bias_review_sha256": digest("invented-bias-review-not-real"),
        "background_scope_sha256": digest("invented-background-not-real"),
        "baseline_configs_sha256": digest("invented-baselines-not-real"),
        "metric_definition_sha256": digest("invented-metric-not-real"),
        "split_construction_sha256": digest("invented-split-design-not-real"),
        "baselines": ["seasonality", "simple_habitat", "simple_weather"],
        "spatial_design": {
            "autocorrelation_range_m": 500.0,
            "minimum_separation_m": 1000.0,
            "justification_sha256": digest("invented-spatial-review-not-real"),
        },
        "decision_rule": {
            "primary_metric": "presence_capture_at_area_fraction",
            "area_fraction": 0.1,
            "minimum_capture_gain": 0.05,
            "minimum_development_blocks": 2,
            "minimum_test_blocks": 2,
            "minimum_test_time_blocks": 2,
            "uncertainty": "blocked_bootstrap",
            "require_gain_lower_bound": True,
            "require_equal_coverage": True,
            "justification_sha256": digest("invented-threshold-review-not-real"),
        },
        "assignments": rows,
    }


def run(tmp_path: Path, definition: dict[str, Any]) -> dict[str, Any]:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(definition, allow_nan=False), encoding="utf-8")
    return audit_file(path)


def test_valid_structure_is_never_scientific_validation_or_permission(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    report = run(tmp_path, definition)
    assert report["structural_status"] == "passed"
    assert report["blockers"] == []
    assert report["counts"] == {
        "development": 2,
        "test": 2,
        "inner_folds": 2,
        "development_blocks": 2,
        "test_blocks": 2,
        "test_time_blocks": 2,
    }
    assert report["scientific_validation"] == "not_performed"
    assert report["publication_allowed"] is False
    assert report["model_training_authorized"] is False
    assert report["probability_evaluation_supported"] is False
    definition["input_kind"] = "private_operator_manifest"
    assert run(tmp_path, definition)["publication_allowed"] is False


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("destination", [1, 2])
def test_dependencies_cannot_cross_inner_folds_or_holdout(
    tmp_path: Path, definition: dict[str, Any], group: str, destination: int
) -> None:
    definition["assignments"][destination][group] = definition["assignments"][0][group]
    assert "dependency_group_crosses_partitions" in run(tmp_path, definition)["blockers"]


def test_repeated_group_in_same_development_fold_is_allowed(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    row = deepcopy(definition["assignments"][0])
    row["record_sha256"] = digest("invented-repeat")
    definition["assignments"].append(row)
    report = run(tmp_path, definition)
    assert report["structural_status"] == "passed"
    assert report["counts"]["development"] == 3
    assert report["counts"]["development_blocks"] == 2


@pytest.mark.parametrize(
    "case,reason",
    [
        ("chronology", "chronological_holdout_overlap"),
        ("freeze", "freeze_after_model_selection"),
        ("draft", "protocol_not_frozen"),
        ("no_freeze", "protocol_not_frozen"),
        ("accessed", "test_labels_already_accessed"),
        ("prediction", "prediction_after_event_start"),
        ("future_feature", "feature_information_leakage"),
        ("cutoff_after_capture", "feature_information_leakage"),
        ("unknown_feature", "feature_availability_unknown"),
        ("unknown_label", "label_availability_unknown"),
        ("premature_label", "label_before_observation_end"),
        ("late_development_label", "development_label_unavailable_at_fit"),
        ("test_cv", "test_in_inner_cv"),
        ("missing_fold", "development_fold_missing"),
        ("single_fold", "inner_cv_needs_multiple_folds"),
        ("no_test", "partition_missing"),
        ("duplicate", "duplicate_record"),
        ("time_block", "time_block_crosses_holdout"),
        ("unknown_time_block", "time_block_unknown"),
        ("unknown_group", "dependency_group_unknown"),
        ("unknown_distance", "test_separation_unknown"),
        ("short_distance", "test_within_spatial_buffer"),
        ("short_buffer", "spatial_separation_below_declared_range"),
        ("unknown_range", "spatial_design_unjustified"),
        ("unjustified_spatial", "spatial_design_unjustified"),
        ("no_evidence", "admission_or_design_evidence_missing"),
        ("no_threshold", "decision_thresholds_unjustified"),
        ("unjustified_threshold", "decision_thresholds_unjustified"),
        ("few_blocks", "declared_sample_threshold_not_met"),
        ("few_times", "declared_sample_threshold_not_met"),
        ("no_baseline", "baselines_incomplete"),
        ("duplicate_baseline", "baselines_incomplete"),
    ],
)
def test_each_safety_gate(
    tmp_path: Path, definition: dict[str, Any], case: str, reason: str
) -> None:
    row = definition["assignments"][0]
    test = definition["assignments"][2]
    if case == "chronology":
        row.update(event_start="2024-01-01T00:00:00Z", event_end="2024-01-01T00:00:01Z")
    elif case == "freeze":
        definition["frozen_at"] = "2025-01-03T00:00:00Z"
    elif case == "draft":
        definition["state"] = "draft"
    elif case == "no_freeze":
        definition["frozen_at"] = None
    elif case == "accessed":
        definition["test_labels_accessed_at"] = "2024-12-01T00:00:00Z"
    elif case == "prediction":
        row["prediction_at"] = row["event_end"]
    elif case == "future_feature":
        row["feature_available_at"] = row["event_end"]
    elif case == "cutoff_after_capture":
        row["feature_data_cutoff"] = row["event_start"]
    elif case == "unknown_feature":
        row["feature_available_at"] = None
    elif case == "unknown_label":
        row["label_available_at"] = None
    elif case == "premature_label":
        row["label_available_at"] = row["event_start"]
    elif case == "late_development_label":
        row["label_available_at"] = "2025-01-03T00:00:00Z"
    elif case == "test_cv":
        test["inner_fold"] = 0
    elif case == "missing_fold":
        row["inner_fold"] = None
    elif case == "single_fold":
        definition["assignments"][1]["inner_fold"] = 0
    elif case == "no_test":
        definition["assignments"] = definition["assignments"][:2]
    elif case == "duplicate":
        test["record_sha256"] = row["record_sha256"]
    elif case == "time_block":
        test["time_block_sha256"] = row["time_block_sha256"]
    elif case == "unknown_time_block":
        test["time_block_sha256"] = None
    elif case == "unknown_group":
        row[GROUPS[0]] = None
    elif case == "unknown_distance":
        test["nearest_development_distance_m"] = None
    elif case == "short_distance":
        test["nearest_development_distance_m"] = 999.99
    elif case == "short_buffer":
        definition["spatial_design"]["minimum_separation_m"] = 499.0
    elif case == "unknown_range":
        definition["spatial_design"]["autocorrelation_range_m"] = None
    elif case == "unjustified_spatial":
        definition["spatial_design"]["justification_sha256"] = None
    elif case == "no_evidence":
        definition["pilot_admission_sha256"] = None
    elif case == "no_threshold":
        definition["decision_rule"]["minimum_capture_gain"] = None
    elif case == "unjustified_threshold":
        definition["decision_rule"]["justification_sha256"] = None
    elif case == "few_blocks":
        definition["decision_rule"]["minimum_test_blocks"] = 3
    elif case == "few_times":
        definition["decision_rule"]["minimum_test_time_blocks"] = 3
    elif case == "no_baseline":
        definition["baselines"].pop()
    elif case == "duplicate_baseline":
        definition["baselines"][0] = definition["baselines"][1]
    report = run(tmp_path, definition)
    assert report["structural_status"] == "blocked"
    assert reason in report["blockers"]


def test_timezone_equivalent_boundaries_and_half_open_chronology(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    row = definition["assignments"][0]
    row["feature_available_at"] = "2023-01-01T01:00:00+01:00"
    definition["assignments"][1]["event_end"] = "2024-01-01T01:00:00+01:00"
    definition["assignments"][1]["label_available_at"] = "2024-01-01T02:00:00+01:00"
    assert run(tmp_path, definition)["structural_status"] == "passed"


@pytest.mark.parametrize(
    "case",
    [
        "coordinates",
        "label",
        "naive_time",
        "invalid_interval",
        "probability_metric",
        "unsafe_rule",
        "true_absence",
        "raw_identity",
        "bool_distance",
        "string_count",
        "too_many",
    ],
)
def test_unsupported_contract_is_rejected(
    tmp_path: Path, definition: dict[str, Any], case: str
) -> None:
    row = definition["assignments"][0]
    if case == "coordinates":
        row["longitude"] = 4.2
    elif case == "label":
        row["target_value"] = 1
    elif case == "naive_time":
        row["prediction_at"] = "2023-01-01T00:00:00"
    elif case == "invalid_interval":
        row["event_end"] = row["event_start"]
    elif case == "probability_metric":
        definition["decision_rule"]["primary_metric"] = "brier_score"
    elif case == "unsafe_rule":
        definition["decision_rule"]["require_equal_coverage"] = False
    elif case == "true_absence":
        definition["observation_basis"] = "true_absence"
    elif case == "raw_identity":
        row["record_sha256"] = "PRIVATE_SENTINEL"
    elif case == "bool_distance":
        row["nearest_development_distance_m"] = True
    elif case == "string_count":
        definition["decision_rule"]["minimum_test_blocks"] = "2"
    elif case == "too_many":
        definition["assignments"] *= 2501
    with pytest.raises(ValueError):
        run(tmp_path, definition)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_distances_rejected(tmp_path: Path, definition: dict[str, Any], bad: str) -> None:
    raw = json.dumps(definition).replace("2000.0", bad)
    path = tmp_path / "manifest.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        audit_file(path)


def test_stdout_is_aggregate_deterministic_without_network_or_writes(
    tmp_path: Path,
    definition: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    modified = path.stat().st_mtime_ns
    monkeypatch.setattr(sys, "argv", ["audit", "--manifest", str(path)])

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("No network or output file allowed")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    assert main() == 0
    first = capsys.readouterr().out
    assert main() == 0
    assert capsys.readouterr().out == first
    assert path.stat().st_mtime_ns == modified
    for row in definition["assignments"]:
        assert row["record_sha256"] not in first
        for name in GROUPS:
            assert row[name] not in first
    assert "2023-01-01" not in first
    assert json.loads(first)["publication_allowed"] is False


def test_cli_invalid_input_is_fixed_and_blocks_have_exit_two(
    tmp_path: Path,
    definition: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "PRIVATE_SENTINEL.json"
    path.write_text('{"private":"PRIVATE_SENTINEL"}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["audit", "--manifest", str(path)])
    assert main() == 2
    assert capsys.readouterr().out == '{"error":"evaluation_manifest_invalid"}\n'
    definition["state"] = "draft"
    path.write_text(json.dumps(definition), encoding="utf-8")
    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["blockers"] == ["protocol_not_frozen"]
    path.write_bytes(b" " * (MAX_BYTES + 1))
    assert main() == 2
    assert capsys.readouterr().out == '{"error":"evaluation_manifest_invalid"}\n'


def test_unknown_design_values_remain_unknown(tmp_path: Path, definition: dict[str, Any]) -> None:
    for name in ("autocorrelation_range_m", "minimum_separation_m", "justification_sha256"):
        definition["spatial_design"][name] = None
    for name in (
        "area_fraction",
        "minimum_capture_gain",
        "minimum_development_blocks",
        "minimum_test_blocks",
        "minimum_test_time_blocks",
        "justification_sha256",
    ):
        definition["decision_rule"][name] = None
    assert Plan.model_validate(definition).spatial_design.minimum_separation_m is None
    blockers = run(tmp_path, definition)["blockers"]
    assert "decision_thresholds_unjustified" in blockers
    assert "spatial_design_unjustified" in blockers


@pytest.mark.parametrize("scope", ["root", "assignment"])
def test_ambiguous_repeated_json_keys_rejected(
    tmp_path: Path, definition: dict[str, Any], scope: str
) -> None:
    raw = json.dumps(definition)
    if scope == "root":
        raw = raw.replace('"state": "frozen"', '"state":"draft","state":"frozen"')
    else:
        raw = raw.replace('"split": "development"', '"split":"test","split":"development"', 1)
    path = tmp_path / "manifest.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="Repeated JSON key"):
        audit_file(path)


def test_embedded_examples_are_only_technical_and_pilot_stays_blocked() -> None:
    root = Path(__file__).resolve().parents[2] / "data" / "evaluation"
    valid = audit_file(root / "synthetic.json")
    assert valid["structural_status"] == "passed"
    assert valid["input_kind"] == "synthetic" and valid["publication_allowed"] is False
    assert audit_file(root / "synthetic-leakage.json")["structural_status"] == "blocked"
    pilot = audit_file(root / "pilot-plan.json")
    assert pilot["structural_status"] == "blocked"
    assert pilot["counts"] == {
        "development": 0,
        "test": 0,
        "inner_folds": 0,
        "development_blocks": 0,
        "test_blocks": 0,
        "test_time_blocks": 0,
    }
