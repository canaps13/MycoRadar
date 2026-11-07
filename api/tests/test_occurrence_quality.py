"""Only invented data; neither scientific admission nor real observation coverage is tested."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from mycoradar import occurrence_quality as quality

FIXTURE = Path(__file__).resolve().parents[2] / "data/quality/synthetic/batch.json"


@pytest.fixture
def batch() -> dict[str, Any]:
    return json.loads(FIXTURE.read_bytes())  # type: ignore[no-any-return]


def single(batch: dict[str, Any], **changes: object) -> dict[str, Any]:
    batch["records"] = [{**batch["records"][0], **changes}]
    return batch


def audited(batch: dict[str, Any]) -> dict[str, Any]:
    return quality.audit(quality.Batch.model_validate(batch))


def test_synthetic_end_to_end_counts_and_conservation(batch: dict[str, Any]) -> None:
    result = quality.read_audit(FIXTURE)
    assert result["input_rows"] == 7
    assert result["representative_rows_for_audit_only"] == 3
    assert result["identical_duplicate_rows"] == 1
    assert result["conflicting_identity_groups"] == 1
    assert result["invalid_rows"] == result["invalid_identity_groups"] == 1
    assert result["rejected_identity_rows"] == 3
    assert result["coincident_event_candidate_groups"] == 1
    assert result["coincident_event_candidate_rows"] == 2
    assert result["calendar_day_month_counts"]["10"] == 2
    assert result["quality_flags"]["event_date_interval"] == 1
    assert result["quality_flags"]["generalized_uncertainty_unknown"] == 1
    assert result["input_sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert result["input_rows"] == sum(
        result[key]
        for key in (
            "unidentified_rows",
            "rejected_identity_rows",
            "identical_duplicate_rows",
            "representative_rows_for_audit_only",
        )
    )
    assert audited(batch)["publication_allowed"] is False


def test_order_and_repetition_do_not_create_representatives(batch: dict[str, Any]) -> None:
    expected = audited(batch)
    batch["records"].reverse()
    assert audited(batch) == expected
    batch["records"] = batch["records"][2:] + batch["records"][:2]
    assert audited(batch) == expected
    batch["records"] *= 2
    doubled = audited(batch)
    assert doubled["representative_rows_for_audit_only"] == 3
    assert doubled["coincident_event_candidate_rows"] == 2
    assert doubled["calendar_day_month_counts"] == expected["calendar_day_month_counts"]


@pytest.mark.parametrize(
    "change",
    [
        {"longitude": 0.6},
        {"record_license": "unverified"},
        {"location_visibility": "unknown"},
        {"sensitivity": "sensitive"},
        {"event_end": "2020-10-03"},
        {"taxon_match": "ambiguous"},
    ],
)
def test_conflicting_identity_is_wholly_quarantined(
    batch: dict[str, Any], change: dict[str, Any]
) -> None:
    row = copy.deepcopy(batch["records"][0])
    batch["records"] = [row, {**row, **change}, row]
    result = audited(batch)
    assert result["representative_rows_for_audit_only"] == 0
    assert result["rejected_identity_rows"] == 3
    assert result["conflicting_identity_groups"] == 1
    assert result["status"] == "unavailable"


@pytest.mark.parametrize(
    "change",
    [
        {"latitude": None},
        {"latitude": 91.0},
        {"longitude": float("inf")},
        {"longitude": True},
        {"coordinate_crs": "EPSG:3857"},
        {"location_uncertainty_m": 0.0},
        {"location_uncertainty_m": -1.0},
        {"location_uncertainty_m": float("nan")},
        {"generalized": "false"},
        {"event_start": "2020-10-02T12:00:00Z"},
        {"event_end": None},
        {"event_end": "2020-01-01"},
        {"occurrence_status": "absent"},
        {"observer_name": "private person"},
    ],
)
def test_invalid_copy_blocks_its_valid_identity(
    batch: dict[str, Any], change: dict[str, Any]
) -> None:
    row = copy.deepcopy(batch["records"][0])
    batch["records"] = [row, {**row, **change}]
    result = audited(batch)
    assert result["invalid_rows"] == 1
    assert result["invalid_identity_groups"] == 1
    assert result["rejected_identity_rows"] == 2
    assert result["representative_rows_for_audit_only"] == 0


def test_unknown_identity_is_counted_without_guessing(batch: dict[str, Any]) -> None:
    single(batch, record_id=None)
    result = audited(batch)
    assert result["unidentified_rows"] == result["invalid_rows"] == 1
    assert result["representative_rows_for_audit_only"] == 0


def test_missing_precision_and_dates_are_not_invented(batch: dict[str, Any]) -> None:
    single(batch, longitude=None, latitude=None, event_start=None, event_end=None)
    result = audited(batch)
    assert result["uncertainty_buckets"]["unknown"] == 1
    assert result["quality_flags"]["coordinates_unknown"] == 1
    assert result["quality_flags"]["event_date_unknown"] == 1
    assert not any(result["calendar_day_month_counts"].values())
    assert result["sampling_effort"] == "unknown"
    assert result["absence_evidence"] == "unavailable"


@pytest.mark.parametrize("generalized", [True, False])
def test_coincidence_is_only_a_candidate_and_excludes_generalized_centres(
    batch: dict[str, Any],
    generalized: bool,
) -> None:
    row = {**batch["records"][0], "generalized": generalized}
    batch["records"] = [row, {**row, "record_id": "different-record"}]
    result = audited(batch)
    assert result["representative_rows_for_audit_only"] == 2
    assert result["coincident_event_candidate_groups"] == (0 if generalized else 1)
    assert result["coincident_events_automatically_merged"] is False


def test_nearby_events_are_not_merged_by_an_invented_distance(batch: dict[str, Any]) -> None:
    row = batch["records"][0]
    batch["records"] = [row, {**row, "record_id": "nearby", "longitude": 0.50000001}]
    assert audited(batch)["coincident_event_candidate_groups"] == 0


def test_future_events_do_not_supply_coverage(batch: dict[str, Any]) -> None:
    single(batch, event_start="2027-01-01", event_end="2027-01-01")
    result = audited(batch)
    assert result["quality_flags"]["event_after_declared_capture"] == 1
    assert not any(result["calendar_day_month_counts"].values())


def test_equivalent_capture_instants_use_the_same_utc_day(batch: dict[str, Any]) -> None:
    single(batch, event_start="2026-01-03", event_end="2026-01-03")
    expected = audited(batch)
    batch["captured_at"] = "2026-01-02T19:00:00-05:00"
    assert audited(batch) == expected


@pytest.mark.parametrize(
    ("distance", "bucket"),
    [
        (None, "unknown"),
        (100.0, "up_to_100_m"),
        (100.1, "over_100_to_1000_m"),
        (1000.0, "over_100_to_1000_m"),
        (1000.1, "over_1000_m"),
    ],
)
def test_uncertainty_bins_are_descriptive_only(
    batch: dict[str, Any],
    distance: float | None,
    bucket: str,
) -> None:
    single(batch, location_uncertainty_m=distance)
    result = audited(batch)
    assert result["uncertainty_buckets"][bucket] == 1
    assert result["scientific_admission"] == "not_performed"
    assert result["publication_allowed"] is False


def test_source_and_taxon_claims_are_not_verified(batch: dict[str, Any]) -> None:
    single(batch, source_version="unregistered", taxon_match="synonym")
    result = audited(batch)
    assert result["quality_flags"]["source_reference_unknown"] == 1
    assert result["quality_flags"]["taxon_mapping_not_exact_accepted"] == 1
    assert result["source_checksums_verified"] is False
    assert result["source_publication_date_unknown_count"] == 1


def test_license_mismatch_is_reported(batch: dict[str, Any]) -> None:
    single(batch, record_license="unsupported")
    assert audited(batch)["quality_flags"]["record_license_mismatch"] == 1


def test_report_never_emits_identifiers_or_coordinates_or_publication(
    batch: dict[str, Any],
) -> None:
    single(batch, record_id="private-marker", longitude=3.123456789, latitude=4.987654321)
    batch["sources"][0]["public_distribution_authorized"] = True
    result = audited(batch)
    rendered = json.dumps(result)
    for value in (
        "private-marker",
        "3.123456789",
        "4.987654321",
        "synthetic:taxon",
        "synthetic:source",
        "example.invalid",
        "Entirely invented",
    ):
        assert value not in rendered
    assert result["report_visibility"] == "private"
    assert result["records_emitted"] == 0 and result["publication_allowed"] is False
    assert result["spatial_bias_assessment"] == "not_performed"


@pytest.mark.parametrize(
    "change", ["future_source", "duplicate_source", "wrong_hash", "absence_mode"]
)
def test_incoherent_manifest_fails_wholly(
    batch: dict[str, Any], change: str, tmp_path: Path
) -> None:
    if change == "future_source":
        batch["sources"][0]["fetched_at"] = "2027-01-01T00:00:00Z"
    elif change == "duplicate_source":
        batch["sources"].append(batch["sources"][0])
    elif change == "wrong_hash":
        batch["sources"][0]["sha256"] = "not-a-hash"
    else:
        batch["observation_semantics"] = "absence"
    path = tmp_path / "private.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    with pytest.raises(quality.QualityError, match="^invalid_input$"):
        quality.read_audit(path)


@pytest.mark.parametrize(
    "content", [b'{"schema_version":1,"schema_version":2}', b"NaN", b"{", b"\xff"]
)
def test_invalid_json_is_not_partially_audited(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "private.json"
    path.write_bytes(content)
    with pytest.raises(quality.QualityError, match="^invalid_input$"):
        quality.read_audit(path)


def test_input_budgets(batch: dict[str, Any], tmp_path: Path) -> None:
    with patch.object(quality, "MAX_BYTES", 4):
        with pytest.raises(quality.QualityError, match="input_budget_exceeded"):
            quality.read_audit(FIXTURE)
    batch["records"] = [batch["records"][0]] * 10_001
    with pytest.raises(quality.ValidationError):
        quality.Batch.model_validate(batch)


def test_empty_batch_stays_unavailable(batch: dict[str, Any]) -> None:
    batch["records"] = []
    result = audited(batch)
    assert result["status"] == "unavailable" and result["sampling_effort"] == "unknown"
    assert result["absence_evidence"] == "unavailable"


def test_cli_is_deterministic_and_errors_are_redacted(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert quality.main(["--input", str(FIXTURE)]) == 0
    first = capsys.readouterr().out
    assert quality.main(["--input", str(FIXTURE)]) == 0
    assert capsys.readouterr().out == first
    assert quality.main(["--input", str(tmp_path / "secret-marker")]) == 2
    output = capsys.readouterr()
    assert output.err == "" and "secret-marker" not in output.out
    assert json.loads(output.out)["error"] == "invalid_input"
    assert quality.main(["--secret-marker"]) == 2
    output = capsys.readouterr()
    assert output.err == "" and "secret-marker" not in output.out
