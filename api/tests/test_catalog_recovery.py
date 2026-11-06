"""Recovery drills use the admitted catalogue, with explicitly synthetic faults/clocks."""

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from mycoradar.catalog import DEFAULT_CATALOG, Catalog
from mycoradar.catalog_models import Snapshot
from mycoradar.catalog_recovery import RecoveryError, inspect, read_validated, run, write_new


@pytest.fixture
def digest() -> str:
    return DEFAULT_CATALOG.with_suffix(".sha256").read_text(encoding="ascii").strip()


def invoke(operation: str, path: Path, digest: str, *extra: str) -> tuple[dict[str, Any], int]:
    return run([operation, "--input", str(path), "--sha256", digest, *extra])


def test_real_backup_fault_detection_and_restore(tmp_path: Path, digest: str) -> None:
    backup, broken, restored = (
        tmp_path / name for name in ("backup.json", "broken.json", "new.json")
    )
    report, code = invoke("backup", DEFAULT_CATALOG, digest, "--output", str(backup))
    assert code == 0 and report["integrity"] == "verified"
    assert backup.read_bytes() == DEFAULT_CATALOG.read_bytes()
    broken.write_bytes(backup.read_bytes() + b"corruption")
    error, code = invoke("restore", broken, digest, "--output", str(restored))
    assert code == 1 and error["error"] == "checksum_mismatch"
    assert not restored.exists()
    report, code = invoke("restore", backup, digest, "--output", str(restored))
    assert code == 0 and report["catalog_version"] == digest
    restored_catalog = Catalog(restored, digest)
    assert restored_catalog.snapshot == Catalog(DEFAULT_CATALOG, digest).snapshot
    assert restored_catalog.version == digest
    assert restored_catalog.snapshot is not None
    assert restored_catalog.snapshot.availability.species.status == "unavailable"
    assert not list(tmp_path.glob(".recovery-*"))


@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_never_replace_existing_destination(tmp_path: Path, digest: str, operation: str) -> None:
    destination = tmp_path / "healthy.json"
    previous = b"independent healthy deployment"
    destination.write_bytes(previous)
    report, code = invoke(operation, DEFAULT_CATALOG, digest, "--output", str(destination))
    assert code == 1 and report["error"] == "destination_exists"
    assert destination.read_bytes() == previous
    assert not list(tmp_path.glob(".recovery-*"))


@pytest.mark.parametrize("phase", ["fsync", "link"])
def test_interrupted_write_preserves_destination(tmp_path: Path, digest: str, phase: str) -> None:
    destination = tmp_path / "new.json"
    with patch(f"mycoradar.catalog_recovery.os.{phase}", side_effect=OSError("private detail")):
        report, code = invoke("backup", DEFAULT_CATALOG, digest, "--output", str(destination))
    assert code == 1 and report["error"] == "write_failed"
    assert not destination.exists()
    assert not list(tmp_path.glob(".recovery-*"))
    assert "private detail" not in json.dumps(report)


def test_no_overwrite_when_another_writer_wins(tmp_path: Path) -> None:
    destination = tmp_path / "race.json"

    def competing_link(source: Path, target: Path) -> None:
        target.write_bytes(b"winner")
        raise FileExistsError()

    with patch("mycoradar.catalog_recovery.os.link", side_effect=competing_link):
        with pytest.raises(RecoveryError, match="destination_exists"):
            write_new(destination, b"loser")
    assert destination.read_bytes() == b"winner"
    assert not list(tmp_path.glob(".recovery-*"))


@pytest.mark.parametrize("fault", ["bad_schema", "private_record", "missing_reference"])
def test_checksum_alone_cannot_admit_a_catalogue(tmp_path: Path, fault: str) -> None:
    value = json.loads(DEFAULT_CATALOG.read_bytes())
    if fault == "bad_schema":
        value["schema_version"] = "unknown"
    elif fault == "private_record":
        value["regions"][0]["visibility"] = "private"
    else:
        value["regions"][0]["source_ids"] = ["absent"]
    data = json.dumps(value).encode()
    path, output = tmp_path / "invalid.json", tmp_path / "backup.json"
    path.write_bytes(data)
    report, code = invoke("backup", path, sha256(data).hexdigest(), "--output", str(output))
    assert code == 1 and report["error"] == "invalid_catalogue"
    assert not output.exists()


def test_bounded_read_before_hash(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * 33)
    with patch("mycoradar.catalog_recovery.MAX_BYTES", 32):
        with pytest.raises(RecoveryError, match="size_limit"):
            read_validated(path, "0" * 64)


@pytest.mark.parametrize("digest", ["", "0" * 63, "A" * 64, "../secret"])
def test_invalid_checksum_is_rejected_before_read(tmp_path: Path, digest: str) -> None:
    with pytest.raises(RecoveryError, match="invalid_checksum"):
        read_validated(tmp_path / "does-not-exist", digest)


def test_paths_and_source_payload_never_enter_reports(tmp_path: Path, digest: str) -> None:
    missing = tmp_path / "secret-token-123.json"
    report, code = invoke("verify", missing, digest)
    assert code == 1 and report["error"] == "read_failed"
    success, code = invoke("verify", DEFAULT_CATALOG, digest)
    assert code == 0
    text = json.dumps([report, success])
    for forbidden in (str(tmp_path), "secret-token", "coordinates", "source_url", "FR-13"):
        assert forbidden not in text
    assert success["scientific_validation"] == "not_performed"


def synthetic_snapshot(*, source_age: int | None = 3600, fetched_age: int = 60) -> Snapshot:
    value = json.loads(DEFAULT_CATALOG.read_bytes())
    now = datetime(2030, 1, 1, tzinfo=UTC)
    value["published_at"] = (now - timedelta(seconds=10)).isoformat()
    for source in value["metadata"]:
        source["fetched_at"] = (now - timedelta(seconds=fetched_age)).isoformat()
        source["source_published_at"] = (
            (now - timedelta(seconds=source_age)).isoformat() if source_age is not None else None
        )
    return Snapshot.model_validate(value)


def test_source_age_does_not_become_collection_or_publication_age() -> None:
    report = inspect(synthetic_snapshot(), datetime(2030, 1, 1, tzinfo=UTC), 3600)
    assert report["catalogue_publication_age_seconds"] == 10
    assert report["oldest_known_source_age_seconds"] == 3600
    assert report["oldest_fetch_age_seconds"] == 60
    assert report["alerts"] == []
    stale = inspect(synthetic_snapshot(), datetime(2030, 1, 1, tzinfo=UTC), 3599)
    assert stale["alerts"] == ["source_age_exceeded"]


def test_unknown_source_date_stays_unknown() -> None:
    report = inspect(synthetic_snapshot(source_age=None), datetime(2030, 1, 1, tzinfo=UTC), 3600)
    assert report["oldest_known_source_age_seconds"] is None
    assert report["source_date_unknown_count"] == report["source_count"]
    assert report["oldest_fetch_age_seconds"] == 60
    assert report["alerts"] == ["source_date_unknown"]


def test_clock_regression_is_alerted_without_clamping_to_fresh() -> None:
    report = inspect(synthetic_snapshot(), datetime(2029, 1, 1, tzinfo=UTC), 3600)
    for key in (
        "catalogue_publication_age_seconds",
        "oldest_known_source_age_seconds",
        "oldest_fetch_age_seconds",
    ):
        assert report[key] is None
    assert report["alerts"] == ["clock_inconsistent"]


def test_missing_sources_are_not_fresh() -> None:
    value = synthetic_snapshot().model_dump(mode="json")
    for name in ("regions", "species", "cells", "metadata"):
        value[name] = []
        value["availability"][name] = {"status": "unavailable", "reason": "test only"}
    report = inspect(Snapshot.model_validate(value), datetime(2030, 1, 1, tzinfo=UTC), 3600)
    assert report["oldest_known_source_age_seconds"] is None
    assert report["alerts"] == ["sources_unavailable"]


@pytest.mark.parametrize("limit", [0, -1])
def test_invalid_age_policy(limit: int) -> None:
    with pytest.raises(RecoveryError, match="invalid_age_policy"):
        inspect(synthetic_snapshot(), datetime(2030, 1, 1, tzinfo=UTC), limit)


def test_timezone_is_required_and_equivalent_instants_agree() -> None:
    snapshot = synthetic_snapshot()
    with pytest.raises(RecoveryError, match="invalid_clock"):
        inspect(snapshot, datetime(2030, 1, 1))
    assert inspect(snapshot, datetime.fromisoformat("2030-01-01T01:00:00+01:00")) == inspect(
        snapshot, datetime(2030, 1, 1, tzinfo=UTC)
    )


def test_audit_reports_unknown_real_source_dates_without_fabricating(digest: str) -> None:
    report, code = invoke("audit", DEFAULT_CATALOG, digest, "--max-source-age-seconds", "86400")
    assert code == 2 and report["status"] == "attention"
    assert "source_date_unknown" in report["metrics"]["alerts"]
    assert report["integrity"] == "verified"


def test_audit_healthy_and_invalid_policy_exit_codes(tmp_path: Path) -> None:
    value = json.loads(DEFAULT_CATALOG.read_bytes())
    now = datetime.now(UTC)
    value["published_at"] = (now - timedelta(seconds=10)).isoformat()
    for source in value["metadata"]:
        source["fetched_at"] = (now - timedelta(seconds=60)).isoformat()
        source["source_published_at"] = (now - timedelta(seconds=3600)).isoformat()
    content = json.dumps(value).encode()
    path = tmp_path / "synthetic-dated.json"
    path.write_bytes(content)
    digest = sha256(content).hexdigest()
    report, code = invoke("audit", path, digest, "--max-source-age-seconds", "86400")
    assert code == 0 and report["status"] == "ok" and not report["metrics"]["alerts"]
    report, code = invoke("audit", path, digest, "--max-source-age-seconds", "0")
    assert code == 1 and report["error"] == "invalid_age_policy"


def test_parser_errors_are_redacted() -> None:
    report, code = run(["audit", "--secret-token-123"])
    assert code == 1 and report["error"] == "invalid_arguments"
    assert "secret" not in json.dumps(report)


def test_directory_input_is_rejected(tmp_path: Path, digest: str) -> None:
    report, code = invoke("verify", tmp_path, digest)
    assert code == 1 and report["error"] == "not_regular_file"
