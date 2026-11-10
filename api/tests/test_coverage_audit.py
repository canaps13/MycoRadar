"""Invented aggregate responses; never provider observations or a pilot admission."""

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest
from mycoradar.coverage_audit import audit


@pytest.fixture
def capture(tmp_path):
    data = {
        "limit": 0,
        "offset": 0,
        "count": 15,
        "results": [],
        "facets": [
            {
                "field": "MONTH",
                "counts": [
                    {"name": "12", "count": 3},
                    {"name": "1", "count": 4},
                    {"name": "7", "count": 2},
                    {"name": "10", "count": 5},
                ],
            }
        ],
    }
    dataset = "00000000-0000-4000-8000-000000000001"
    checklist = "00000000-0000-4000-8000-000000000002"
    parameters = dict(
        datasetKey=dataset,
        taxonKey="1",
        checklistKey=checklist,
        limit="0",
        offset="0",
        facet="month",
        facetLimit="12",
        facetMincount="1",
        license="CC_BY_4_0",
        geometry="POLYGON((0 0,1 0,1 1,0 1,0 0))",
    )
    manifest = {
        "schema_version": "gbif-month-audit-v1",
        "capture_kind": "synthetic",
        "dataset_key": dataset,
        "checklist_key": checklist,
        "taxon_key": 1,
        "scientific_name": "Synthetic test taxon",
        "captures": [
            {
                "region_id": "synthetic-region",
                "path": "month.json",
                "sha256": "0" * 64,
                "fetched_at": "2000-01-01T00:00:00Z",
                "request_url": "https://api.gbif.org/v1/occurrence/search?" + urlencode(parameters),
            }
        ],
    }

    def write():
        raw = json.dumps(data).encode()
        (tmp_path / "month.json").write_bytes(raw)
        manifest["captures"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest))
        return path

    return data, manifest, write


def test_audit_is_offline_reproducible_suppresses_small_counts_and_never_admits_pilot(
    capture, monkeypatch
):
    _, _, write = capture
    path = write()

    def no_network(*args, **kwargs):
        pytest.fail("Offline audit attempted network access")

    monkeypatch.setattr(socket, "socket", no_network)
    result = audit(path)
    assert result == audit(path)
    assert result["capture_kind"] == "synthetic"
    assert result["scientific_status"] == "blocked" and result["selected_pilot_taxon"] is None
    region = result["regions"][0]
    assert region["seasons"] == {
        "winter": "5_or_more",
        "spring": "0_indexed",
        "summer": "1_to_4_withheld",
        "autumn": "5_or_more",
    }
    assert region["unknown_month_band"] == "1_to_4_withheld"
    assert "request_url" not in json.dumps(result)
    assert "geometry" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        {"results": [{"decimalLatitude": 1, "secret": "PRIVATE"}]},
        {"limit": 1},
        {"offset": 1},
        {"count": True},
        {"count": -1},
        {"count": 13},
        {"facets": []},
        {"facets": [{"field": "YEAR", "counts": []}]},
        {"facets": [{"field": "MONTH", "counts": [{"name": "13", "count": 1}]}]},
        {"facets": [{"field": "MONTH", "counts": [{"name": "1", "count": True}]}]},
        {"facets": [{"field": "MONTH", "counts": [{"name": "1", "count": 1}] * 2}]},
    ],
)
def test_incoherent_or_row_bearing_responses_are_rejected(capture, change):
    data, _, write = capture
    data.update(change)
    with pytest.raises(ValueError):
        audit(write())


@pytest.mark.parametrize("suffix", ["&limit=0", "&facetOffset=1", "&unexpected=PRIVATE"])
def test_truncated_or_ambiguous_facet_queries_are_rejected(capture, suffix):
    _, manifest, write = capture
    manifest["captures"][0]["request_url"] += suffix
    with pytest.raises(ValueError):
        audit(write())


def test_zero_index_rows_are_distinct_from_missing_months(capture):
    data, _, write = capture
    data["count"] = 0
    data["facets"][0]["counts"] = []
    result = audit(write())["regions"][0]
    assert result["unknown_month_band"] == "0_indexed"
    assert set(result["seasons"].values()) == {"0_indexed"}
    data["count"] = 7
    assert audit(write())["regions"][0]["unknown_month_band"] == "5_or_more"


@pytest.mark.parametrize(
    "field,value", [("path", "../private.json"), ("fetched_at", "2200-01-01T00:00:00Z")]
)
def test_uncontained_paths_and_future_captures_are_refused(capture, field, value):
    _, manifest, write = capture
    manifest["captures"][0][field] = value
    with pytest.raises(ValueError):
        audit(write())


def test_checksum_mismatch_and_duplicate_json_keys_are_refused(capture):
    _, _, write = capture
    path = write()
    (path.parent / "month.json").write_text('{"secret":"PRIVATE"}')
    with pytest.raises(ValueError):
        audit(path)
    path.write_text('{"schema_version":1,"schema_version":2}')
    with pytest.raises(ValueError):
        audit(path)


def test_cli_failure_has_no_paths_or_partial_receipt(capture):
    data, _, write = capture
    data["results"] = [{"secret": "PRIVATE"}]
    path = write()
    result = subprocess.run(
        [sys.executable, "-m", "mycoradar.coverage_audit", "--manifest", str(path)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
    )
    assert result.returncode == 2 and result.stderr == ""
    assert json.loads(result.stdout) == {"status": "unavailable", "error": "coverage_input_invalid"}
    assert "PRIVATE" not in result.stdout and str(path) not in result.stdout


def test_shipped_synthetic_capture_reproduces_expected_receipt():
    folder = Path(__file__).resolve().parents[2] / "data/coverage-audit/synthetic"
    assert audit(folder / "manifest.json") == json.loads((folder / "expected.json").read_bytes())


@pytest.mark.parametrize("target,size", [("manifest.json", 131073), ("month.json", 100001)])
def test_local_input_budgets_are_enforced(capture, target, size):
    _, _, write = capture
    path = write()
    (path.parent / target).write_bytes(b" " * size)
    with pytest.raises(ValueError):
        audit(path)


def test_duplicate_scopes_are_not_counted_twice(capture):
    _, manifest, write = capture
    manifest["captures"].append(dict(manifest["captures"][0]))
    with pytest.raises(ValueError):
        audit(write())


@pytest.mark.parametrize(
    "value",
    [
        0,
        946684800,
        946684800.5,
        "946684800",
        True,
        None,
        "2000-01-01",
        "2000-01-01T00:00:00",
        "2000-01-01 00:00:00Z",
    ],
)
def test_capture_date_is_never_coerced_from_epoch_or_implicit_timezone(capture, value):
    _, manifest, write = capture
    manifest["captures"][0]["fetched_at"] = value
    with pytest.raises(ValueError):
        audit(write())


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2000-01-01T00:00:00Z", "2000-01-01T00:00:00+00:00"),
        ("2000-01-01T01:00:00.123456+01:00", "2000-01-01T01:00:00.123456+01:00"),
    ],
)
def test_explicit_capture_timestamps_keep_their_declared_offset(capture, value, expected):
    _, manifest, write = capture
    manifest["captures"][0]["fetched_at"] = value
    assert audit(write())["regions"][0]["fetched_at"] == expected


def test_cli_refuses_epoch_capture_without_inventing_a_receipt(capture):
    _, manifest, write = capture
    manifest["captures"][0]["fetched_at"] = 946684800
    result = subprocess.run(
        [sys.executable, "-m", "mycoradar.coverage_audit", "--manifest", str(write())],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert result.returncode == 2 and result.stderr == ""
    assert json.loads(result.stdout) == {"status": "unavailable", "error": "coverage_input_invalid"}
