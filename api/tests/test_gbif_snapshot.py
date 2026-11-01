"""Invented responses only; a snapshot never establishes permission to release a location."""

import hashlib
import json
import socket
import sys
from pathlib import Path

import pytest
from mycoradar import gbif_snapshot as snapshot
from mycoradar.gbif_client import GBIFClient, GBIFError
from mycoradar.gbif_import import admit_sample, import_sample
from mycoradar.gbif_job import main
from mycoradar.occurrence_outputs import audit_payload
from mycoradar.occurrence_privacy import PrivacyPolicy
from pydantic import ValidationError
from test_gbif import Provider, request, row


@pytest.fixture
def archive(tmp_path):
    provider = Provider()
    entries = []

    def capture(url, timeout):
        result = provider(url, timeout)
        name = f"response-{len(entries)}.json"
        (tmp_path / name).write_bytes(result.body)
        entries.append(
            {"url": url, "path": name, "sha256": hashlib.sha256(result.body).hexdigest()}
        )
        return result

    import_sample(request(), GBIFClient(capture))
    manifest = tmp_path / "snapshot.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "gbif-snapshot-v1",
                "capture_kind": "synthetic",
                "captured_at": "2026-01-04T00:00:00Z",
                "request": request().model_dump(mode="json"),
                "responses": entries,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def edit(path, **changes):
    data = json.loads(path.read_bytes())
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_replay_is_identical_without_network_or_fake_freshness(archive, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("offline replay attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", no_network)
    first = snapshot.replay_snapshot(archive)
    second = snapshot.replay_snapshot(archive)
    assert first.receipt == second.receipt
    assert first.receipt["fetched_at"] == "2026-01-04T00:00:00+00:00"
    assert first.receipt["raw_records_persisted"] is True
    assert first.receipt["replay"]["network_requests"] == 0
    assert first.receipt["quality"]["received"] == 3
    assert first.receipt["quality"]["normalized"] == 3
    assert first.receipt["coverage_status"] == "partial"
    assert first.receipt["download_doi"] is None
    policy = PrivacyPolicy()
    assert audit_payload(admit_sample(first, policy), policy)["accepted"] == 0
    assert "PRIVATE_" not in json.dumps(first.receipt)


def test_live_and_replay_share_the_same_source_identity(archive):
    live = import_sample(request(), GBIFClient(Provider()))
    replay = snapshot.replay_snapshot(archive)
    assert live.receipt["sample_version"] == replay.receipt["sample_version"]
    assert live._rows == replay._rows


@pytest.mark.parametrize("change", ["reorder", "missing", "extra", "query", "host"])
def test_exact_request_sequence_is_required(archive, change):
    data = json.loads(archive.read_bytes())
    entries = data["responses"]
    if change == "reorder":
        entries[0], entries[1] = entries[1], entries[0]
    elif change == "missing":
        entries.pop()
    elif change == "extra":
        entries.append(entries[-1])
    elif change == "query":
        entries[2]["url"] += "&PRIVATE_SENTINEL=1"
    else:
        entries[0]["url"] = "https://example.invalid/private"
    edit(archive, responses=entries)
    with pytest.raises((GBIFError, ValidationError)):
        snapshot.replay_snapshot(archive)


@pytest.mark.parametrize("change", ["checksum", "traversal", "absolute", "missing", "directory"])
def test_inputs_stay_local_and_are_verified(archive, change):
    data = json.loads(archive.read_bytes())
    ref = data["responses"][0]
    if change == "checksum":
        ref["sha256"] = "0" * 64
    elif change == "traversal":
        ref["path"] = "../PRIVATE_SENTINEL.json"
    elif change == "absolute":
        ref["path"] = str(archive.parent.parent / "PRIVATE_SENTINEL.json")
    elif change == "missing":
        ref["path"] = "PRIVATE_SENTINEL.json"
    else:
        ref["path"] = "."
    edit(archive, responses=data["responses"])
    with pytest.raises((GBIFError, OSError)):
        snapshot.replay_snapshot(archive)


@pytest.mark.parametrize(
    "budget", ["MAX_MANIFEST_BYTES", "MAX_SNAPSHOT_BYTES", "MAX_RESPONSE_BYTES"]
)
def test_byte_budgets_are_enforced(archive, monkeypatch, budget):
    monkeypatch.setattr(snapshot, budget, 10)
    with pytest.raises(GBIFError, match="snapshot_budget_exceeded"):
        snapshot.replay_snapshot(archive)


@pytest.mark.parametrize(
    "changes",
    [
        {"captured_at": "2099-01-01T00:00:00Z"},
        {"captured_at": "2026-01-04"},
        {"captured_at": "2026-01-04T00:00:00"},
        {"capture_kind": "verified_by_gbif"},
        {"responses": []},
        {"private_secret": "PRIVATE_SENTINEL"},
        {"captured_at": None},
    ],
)
def test_manifest_cannot_silently_invent_capture_facts(archive, changes):
    edit(archive, **changes)
    with pytest.raises(ValidationError):
        snapshot.replay_snapshot(archive)


def test_source_metadata_cannot_postdate_the_declared_capture(archive):
    edit(archive, captured_at="2025-12-31T00:00:00Z")
    with pytest.raises(GBIFError, match="snapshot_capture_incoherent"):
        snapshot.replay_snapshot(archive)


def test_replay_keeps_restrictive_duplicates_and_unknown_dates(archive):
    data = json.loads(archive.read_bytes())
    entry = data["responses"][2]
    content = json.dumps(
        {
            "offset": 0,
            "limit": 2,
            "endOfRecords": False,
            "results": [row(1), row(1, license="https://example.invalid/license", eventDate=None)],
        }
    ).encode()
    (archive.parent / entry["path"]).write_bytes(content)
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    edit(archive, responses=data["responses"])
    batch = snapshot.replay_snapshot(archive)
    assert batch.receipt["quality"]["duplicate_identities"] == 1
    assert batch.receipt["quality"]["unusable_records"] == 1
    policy = PrivacyPolicy()
    assert audit_payload(admit_sample(batch, policy), policy)["accepted"] == 0


def test_cli_replays_deterministically_and_never_echoes_private_input(archive, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["gbif-job", "--snapshot", str(archive)])
    assert main() == 0
    first = capsys.readouterr()
    assert main() == 0
    second = capsys.readouterr()
    assert first == second and first.err == ""
    output = json.loads(first.out)
    assert output["admission"]["accepted"] == 0 and "PRIVATE_" not in first.out
    edit(archive, responses=[])
    assert main() == 2
    failed = capsys.readouterr()
    assert failed.err == "" and "PRIVATE_" not in failed.out
    assert json.loads(failed.out)["status"] == "unavailable"


def test_cli_modes_are_exclusive(archive, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["gbif-job", "--request", "PRIVATE_PATH", "--snapshot", str(archive)]
    )
    assert main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "unavailable",
        "error": "arguments_invalid",
    }


@pytest.mark.parametrize("failure", ["late_checksum", "extra_response", "invalid_json"])
def test_late_failure_never_emits_a_partial_receipt(archive, monkeypatch, capsys, failure):
    data = json.loads(archive.read_bytes())
    if failure == "extra_response":
        data["responses"].append(data["responses"][-1])
    else:
        entry = data["responses"][-1]
        content = b"PRIVATE_SENTINEL: invalid JSON"
        (archive.parent / entry["path"]).write_bytes(content)
        if failure == "invalid_json":
            entry["sha256"] = hashlib.sha256(content).hexdigest()
    edit(archive, responses=data["responses"])
    monkeypatch.setattr(sys, "argv", ["gbif-job", "--snapshot", str(archive)])
    assert main() == 2
    output = capsys.readouterr()
    assert output.err == "" and "PRIVATE_" not in output.out
    result = json.loads(output.out)
    assert result["status"] == "unavailable" and "receipt" not in result


def test_frozen_packaging_fixture_is_explicitly_synthetic_and_not_publishable():
    path = Path(__file__).resolve().parents[2] / "data/gbif/offline-synthetic/snapshot.json"
    batch = snapshot.replay_snapshot(path)
    assert batch.receipt["replay"]["capture_kind"] == "synthetic"
    assert batch.receipt["quality"]["received"] == 3
    policy = PrivacyPolicy()
    assert audit_payload(admit_sample(batch, policy), policy)["accepted"] == 0


@pytest.mark.parametrize("failure", [ValueError, RuntimeError])
def test_filesystem_resolution_diagnostics_remain_private(archive, monkeypatch, capsys, failure):
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        if path.name == "response-0.json":
            raise failure("PRIVATE_SENTINEL")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(sys, "argv", ["gbif-job", "--snapshot", str(archive)])
    assert main() == 2
    output = capsys.readouterr()
    assert output.err == "" and "PRIVATE_" not in output.out
    assert json.loads(output.out)["error"] == "snapshot_input_invalid"
