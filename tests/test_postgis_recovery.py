"""Guard tests only; real dump/restore is a separate opt-in Compose exercise."""

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mycoradar.settings import Settings

from scripts import check_postgis_recovery as recovery

RUN_ID = "a" * 16
SOURCE = f"mycoradar_test_recovery_{RUN_ID}_source"
RESTORED = f"mycoradar_test_recovery_{RUN_ID}_restored"


@pytest.mark.parametrize(
    ("optin", "host", "database"),
    [
        (None, "127.0.0.1", "mycoradar_test_ci"),
        ("0", "127.0.0.1", "mycoradar_test_ci"),
        ("1", "remote.example", "mycoradar_test_ci"),
        ("1", "127.0.0.1", "mycoradar"),
        ("1", "127.0.0.1", "mycoradar_test; DROP DATABASE x"),
        ("1", "127.0.0.1", "postgres"),
    ],
)
def test_refuse_before_connection_or_process(
    monkeypatch: pytest.MonkeyPatch,
    optin: str | None,
    host: str,
    database: str,
) -> None:
    if optin is None:
        monkeypatch.delenv("MYCORADAR_TEST_DATABASE", raising=False)
    else:
        monkeypatch.setenv("MYCORADAR_TEST_DATABASE", optin)
    settings = Settings(_env_file=None, pg_host=host, pg_database=database)
    with (
        patch.object(recovery, "connect") as connect,
        patch.object(recovery, "checked_process") as run,
    ):
        with pytest.raises(recovery.DrillError, match="isolated_test_database_required"):
            recovery.drill(settings, RUN_ID)
        connect.assert_not_called()
        run.assert_not_called()


@pytest.mark.parametrize("name", ["postgres", "mycoradar_test_ci", SOURCE + "_other", "../source"])
def test_only_this_run_can_be_removed(name: str) -> None:
    with pytest.raises(recovery.DrillError, match="database_name_refused"):
        recovery.generated_database(name, RUN_ID)


def test_failure_cleans_only_databases_created_by_this_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCORADAR_TEST_DATABASE", "1")
    settings = Settings(_env_file=None, pg_database="mycoradar_test_ci")
    control = MagicMock()
    control.__enter__.return_value = control
    with (
        patch.object(recovery, "connect", return_value=control),
        patch.object(recovery, "seed", side_effect=recovery.DrillError("migration_failed")),
    ):
        with pytest.raises(recovery.DrillError, match="migration_failed"):
            recovery.drill(settings, RUN_ID)
    queries = [str(call.args[0]) for call in control.execute.call_args_list]
    assert len(queries) == 6
    assert all("CREATE DATABASE" in query for query in queries[:3])
    assert all("DROP DATABASE" in query for query in queries[3:])
    assert all(RUN_ID in query and "mycoradar_test_ci" not in query for query in queries)
    assert all("FORCE" not in query and "CASCADE" not in query for query in queries)


def test_existing_database_collision_is_not_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCORADAR_TEST_DATABASE", "1")
    settings = Settings(_env_file=None, pg_database="mycoradar_test_ci")
    control = MagicMock()
    control.__enter__.return_value = control
    control.execute.side_effect = recovery.psycopg.errors.DuplicateDatabase()
    with patch.object(recovery, "connect", return_value=control):
        with pytest.raises(recovery.psycopg.errors.DuplicateDatabase):
            recovery.drill(settings, RUN_ID)
    assert control.execute.call_count == 1
    assert "DROP" not in str(control.execute.call_args)


def test_cleanup_failure_cannot_report_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCORADAR_TEST_DATABASE", "1")
    settings = Settings(_env_file=None, pg_database="mycoradar_test_ci")
    control = MagicMock()
    control.__enter__.return_value = control
    control.execute.side_effect = [None, None, None] + [recovery.psycopg.Error()] * 3
    with (
        patch.object(recovery, "connect", return_value=control),
        patch.object(recovery, "seed", side_effect=recovery.DrillError("migration_failed")),
    ):
        with pytest.raises(recovery.DrillError, match="cleanup_failed"):
            recovery.drill(settings, RUN_ID)
    assert control.execute.call_count == 6


def test_corrupt_archive_stops_before_postgres(tmp_path: Path) -> None:
    path = tmp_path / "broken.dump"
    path.write_bytes(b"PGDMPcorruption")
    settings = Settings(_env_file=None)
    with patch.object(recovery, "checked_process") as run:
        with pytest.raises(recovery.DrillError, match="archive_checksum_mismatch"):
            recovery.restore(settings, path, "0" * 64, RESTORED, RUN_ID)
        run.assert_not_called()


def test_restore_feeds_the_verified_bytes_not_a_reopened_input(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.dump"
    content = b"PGDMPsynthetic-unit-fixture-not-a-real-dump"
    path.write_bytes(content)

    def check(arguments: list[str], **kwargs: object) -> None:
        path.write_bytes(b"changed after verification")
        stream = kwargs["stdin"]
        assert stream.read() == content  # type: ignore[attr-defined]
        assert "--single-transaction" in arguments and "--exit-on-error" in arguments
        assert "--clean" not in arguments and "--create" not in arguments

    with patch.object(recovery, "checked_process", side_effect=check):
        recovery.restore(
            Settings(_env_file=None), path, hashlib.sha256(content).hexdigest(), RESTORED, RUN_ID
        )


@pytest.mark.parametrize("content", [b"", b"NOT_PGDMP", b"PGDMP" + b"x" * 32])
def test_archive_format_and_size_are_bounded(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "invalid.dump"
    path.write_bytes(content)
    with patch.object(recovery, "MAX_ARCHIVE_BYTES", 32):
        with pytest.raises(recovery.DrillError, match="archive_invalid"):
            recovery.archive_bytes(path)


def test_unrelated_tool_failure_does_not_prove_rollback() -> None:
    with patch.object(
        recovery.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            [], 1, stderr=b"password authentication failed; private detail"
        ),
    ):
        with pytest.raises(recovery.DrillError, match="^command_failed$"):
            recovery.checked_process(["pg_restore"], expected_conflict=True)
    with patch.object(
        recovery.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            [], 1, stderr=b'pg_restore: error: ERROR:  relation "occurrences" already exists'
        ),
    ):
        with pytest.raises(recovery.DrillError, match="^restore_relation_conflict$"):
            recovery.checked_process(["pg_restore"], expected_conflict=True)


@pytest.mark.parametrize(
    "error", [OSError("secret path"), subprocess.TimeoutExpired("private", 120)]
)
def test_tool_start_and_timeout_are_redacted(error: Exception) -> None:
    with patch.object(recovery.subprocess, "run", side_effect=error):
        with pytest.raises(recovery.DrillError, match="^command_unavailable_or_timeout$"):
            recovery.checked_process(["docker"])


def test_success_with_warning_is_not_a_clean_proof() -> None:
    with patch.object(
        recovery.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            [], 0, stderr=b"WARNING: inspect this private content"
        ),
    ):
        with pytest.raises(recovery.DrillError, match="^command_failed$"):
            recovery.checked_process(["pg_dump"])


def test_main_never_logs_connection_or_dump_details(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(
        recovery, "drill", side_effect=RuntimeError("postgres://secret:password@private")
    ):
        assert recovery.main() == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["error"] == "drill_failed" and output.err == ""
    assert "secret" not in output.out and "password" not in output.out
