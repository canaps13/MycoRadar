"""Opt-in recovery drill on newly created synthetic databases in the local Compose stack."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Protocol

import psycopg
from mycoradar.database import ROOT, required_revision
from mycoradar.settings import Settings
from psycopg import sql
from psycopg.errors import CheckViolation, ForeignKeyViolation

TABLES = (
    "alembic_version",
    "countries",
    "regions",
    "cells",
    "cell_regions",
    "taxa",
    "data_providers",
    "source_datasets",
    "source_versions",
    "prediction_runs",
    "prediction_run_inputs",
    "occurrences",
)
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class DrillError(Exception):
    """Only fixed codes may reach stdout."""


class Descriptor(Protocol):
    def fileno(self) -> int: ...


def validate_environment(settings: Settings) -> None:
    if (
        os.environ.get("MYCORADAR_TEST_DATABASE") != "1"
        or not re.fullmatch(r"mycoradar_test[a-z0-9_]{0,40}", settings.pg_database)
        or settings.pg_host not in ("127.0.0.1", "::1", "localhost")
    ):
        raise DrillError("isolated_test_database_required")


def generated_database(name: str, run_id: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{16}", run_id) or name not in {
        f"mycoradar_test_recovery_{run_id}_{suffix}"
        for suffix in ("source", "restored", "rejected")
    }:
        raise DrillError("database_name_refused")


def connect(settings: Settings, database: str) -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        dbname=database,
        user=settings.pg_user,
        password=settings.pg_password.get_secret_value(),
        connect_timeout=5,
        options="-c statement_timeout=15000 -c lock_timeout=5000",
        autocommit=True,
    )


def checked_process(
    arguments: list[str],
    *,
    stdin: Descriptor | None = None,
    stdout: Descriptor | None = None,
    env: dict[str, str] | None = None,
    expected_conflict: bool = False,
) -> None:
    try:
        result = subprocess.run(
            arguments,
            stdin=stdin.fileno() if stdin is not None else subprocess.DEVNULL,
            stdout=stdout.fileno() if stdout is not None else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            cwd=ROOT,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DrillError("command_unavailable_or_timeout") from exc
    # Warnings must be investigated, never treated as a clean recovery proof.
    if result.returncode != 0 or result.stderr:
        if (
            expected_conflict
            and result.returncode != 0
            and re.search(rb'ERROR:\s+relation "occurrences" already exists', result.stderr)
        ):
            raise DrillError("restore_relation_conflict")
        raise DrillError("command_failed")


def pg_command(tool: str, database: str, user: str) -> list[str]:
    if tool not in ("pg_dump", "pg_restore"):
        raise DrillError("tool_refused")
    return [
        "docker",
        "compose",
        "--env-file",
        ".env.example",
        "exec",
        "-T",
        "db",
        tool,
        "--host=/var/run/postgresql",
        "--port=5432",
        f"--username={user}",
        "--no-password",
        f"--dbname={database}",
        "--no-owner",
        "--no-privileges",
    ]


def archive_bytes(path: Path, expected: str | None = None) -> bytes:
    with path.open("rb") as stream:
        content = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(content) > MAX_ARCHIVE_BYTES or not content.startswith(b"PGDMP"):
        raise DrillError("archive_invalid")
    if expected is not None and hashlib.sha256(content).hexdigest() != expected:
        raise DrillError("archive_checksum_mismatch")
    return content


def restore(
    settings: Settings,
    path: Path,
    expected: str,
    database: str,
    run_id: str,
    *,
    expected_conflict: bool = False,
) -> None:
    generated_database(database, run_id)
    content = archive_bytes(path, expected)
    # Use the very bytes checked, even if the operator file is changed afterwards.
    with tempfile.TemporaryFile() as checked:
        checked.write(content)
        checked.seek(0)
        checked_process(
            pg_command("pg_restore", database, settings.pg_user)
            + ["--single-transaction", "--exit-on-error"],
            stdin=checked,
            expected_conflict=expected_conflict,
        )


def seed(settings: Settings, database: str) -> None:
    env = os.environ.copy()
    env["PGDATABASE"] = database
    # Keep the established migration CLI and capture its normal INFO output privately.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise DrillError("migration_failed")
    statements = (
        "INSERT INTO countries VALUES ('FR', 'Synthetic recovery fixture')",
        """INSERT INTO regions (id,country_code,name,timezone,geometry) VALUES
           ('test:r','FR','Synthetic area','Europe/Paris',
            ST_GeomFromText('MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))',4326))""",
        """INSERT INTO cells (id,grid_system,resolution_m,geometry) VALUES
           ('test:c','synthetic',1000,
            ST_GeomFromText('MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))',4326))""",
        "INSERT INTO cell_regions VALUES ('test:c','test:r')",
        "INSERT INTO taxa (id,scientific_name) VALUES ('test:t','Synthetic taxon')",
        "INSERT INTO data_providers VALUES ('test:p','Synthetic','https://example.invalid/')",
        """INSERT INTO source_datasets (id,provider_id,product,source_url) VALUES
           ('test:d','test:p','Synthetic','https://example.invalid/data')""",
        """INSERT INTO source_versions
           (id,dataset_id,version,source_url,checksum_sha256,fetched_at) VALUES
           ('test:v','test:d','synthetic','https://example.invalid/v',repeat('a',64),
            '2026-01-02T00:00:00Z')""",
        "INSERT INTO prediction_runs (id,model_version) VALUES ('test:run','synthetic-no-score')",
        "INSERT INTO prediction_run_inputs VALUES ('test:run','test:v')",
        """INSERT INTO occurrences (id,taxon_id,source_version_id,source_record_id,geometry)
           VALUES ('test:private','test:t','test:v','synthetic-1',
                   ST_SetSRID(ST_MakePoint(0.5,0.5),4326))""",
        """INSERT INTO occurrences
           (id,taxon_id,source_version_id,source_record_id,geometry,visibility,
            event_start,event_end,location_uncertainty_m) VALUES
           ('test:restricted','test:t','test:v','synthetic-2',
            ST_SetSRID(ST_MakePoint(0.6,0.6),4326),'restricted',
            '2026-01-01','2026-01-31',1500)""",
    )
    with connect(settings, database) as connection, connection.transaction():
        for statement in statements:
            connection.execute(statement)


def fingerprint(settings: Settings, database: str) -> str:
    """Compare all business rows, indexes and constraints without logging their contents."""
    digest = hashlib.sha256()
    with connect(settings, database) as connection:
        for table in TABLES:
            rows = connection.execute(
                sql.SQL(
                    "SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text"
                ).format(sql.Identifier(table))
            ).fetchall()
            digest.update(json.dumps([table, rows]).encode())
        for statement in (
            """SELECT tablename,indexname,indexdef FROM pg_indexes
               WHERE schemaname='public' AND tablename=ANY(%s) ORDER BY tablename,indexname""",
            """SELECT c.relname,k.conname,pg_get_constraintdef(k.oid) FROM pg_constraint k
               JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname,k.conname""",
        ):
            digest.update(
                json.dumps(connection.execute(statement, (list(TABLES),)).fetchall()).encode()
            )
        if connection.execute("SELECT version_num FROM alembic_version").fetchone() != (
            required_revision(),
        ):
            raise DrillError("revision_mismatch")
        if not connection.execute("SELECT postgis_version()").fetchone():
            raise DrillError("postgis_unavailable")
    return digest.hexdigest()


def check_restored_constraints(settings: Settings, database: str) -> None:
    with connect(settings, database) as connection:
        for statement in (
            "UPDATE occurrences SET geometry=ST_SetSRID(geometry,3857)",
            "UPDATE occurrences SET taxon_id='missing'",
            "UPDATE occurrences SET visibility='invented'",
        ):
            try:
                with connection.transaction():
                    connection.execute(statement)
                    raise DrillError("restored_constraint_missing")
            except (CheckViolation, ForeignKeyViolation):
                pass
        private = connection.execute(
            """SELECT visibility,verification_status,event_start,location_uncertainty_m
               FROM occurrences WHERE id='test:private'"""
        ).fetchone()
        if private != ("private", "unverified", None, None):
            raise DrillError("privacy_or_unknowns_changed")


def drill(settings: Settings, run_id: str) -> dict[str, Any]:
    validate_environment(settings)
    names = [
        f"mycoradar_test_recovery_{run_id}_{suffix}"
        for suffix in ("source", "restored", "rejected")
    ]
    for name in names:
        generated_database(name, run_id)
    source, restored, rejected = names
    created: list[str] = []
    with connect(settings, settings.pg_database) as control:
        try:
            for name in names:
                control.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name))
                )
                created.append(name)
            seed(settings, source)
            expected_rows = fingerprint(settings, source)
            with tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "synthetic.dump"
                with archive.open("xb") as stream:
                    checked_process(
                        pg_command("pg_dump", source, settings.pg_user) + ["--format=custom"],
                        stdout=stream,
                    )
                content = archive_bytes(archive)
                digest = hashlib.sha256(content).hexdigest()
                broken = Path(directory) / "corrupt.dump"
                broken.write_bytes(content + b"INJECTED_CORRUPTION")
                try:
                    restore(settings, broken, digest, restored, run_id)
                    raise DrillError("corruption_not_detected")
                except DrillError as exc:
                    if str(exc) != "archive_checksum_mismatch":
                        raise
                with connect(settings, restored) as target:
                    if target.execute(
                        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
                    ).fetchone() != (0,):
                        raise DrillError("corrupt_restore_changed_target")
                restore(settings, archive, digest, restored, run_id)
                if fingerprint(settings, restored) != expected_rows:
                    raise DrillError("restored_data_mismatch")
                check_restored_constraints(settings, restored)
                with connect(settings, rejected) as target:
                    target.execute("CREATE TABLE occurrences (sentinel text)")
                    target.execute("INSERT INTO occurrences VALUES ('independent-existing-data')")
                try:
                    restore(settings, archive, digest, rejected, run_id, expected_conflict=True)
                    raise DrillError("conflicting_restore_not_rejected")
                except DrillError as exc:
                    if str(exc) != "restore_relation_conflict":
                        raise
                with connect(settings, rejected) as target:
                    tables = target.execute(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname='public' ORDER BY tablename"
                    ).fetchall()
                    if tables != [("occurrences",)] or target.execute(
                        "SELECT sentinel FROM occurrences"
                    ).fetchall() != [("independent-existing-data",)]:
                        raise DrillError("failed_restore_not_atomic")
                    if target.execute(
                        "SELECT count(*) FROM pg_extension WHERE extname='postgis'"
                    ).fetchone() != (0,):
                        raise DrillError("failed_restore_not_atomic")
                if fingerprint(settings, source) != expected_rows:
                    raise DrillError("source_changed")
        finally:
            cleanup_failed = False
            for name in reversed(created):
                generated_database(name, run_id)
                try:
                    control.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
                except psycopg.Error:
                    cleanup_failed = True
            if cleanup_failed:
                raise DrillError("cleanup_failed")
    return {
        "event": "postgis_recovery_smoke",
        "status": "ok",
        "run_id": run_id,
        "synthetic_only": True,
        "corruption_detected_before_restore": True,
        "data_indexes_constraints_equal": True,
        "restored_constraints_enforced": True,
        "private_defaults_and_unknowns_preserved": True,
        "failed_restore_rolled_back": True,
        "source_unchanged": True,
        "temporary_databases_removed": True,
        "off_machine_backup_tested": False,
        "production_recovery_tested": False,
    }


def main() -> int:
    run_id = uuid.uuid4().hex[:16]
    try:
        report = drill(Settings(), run_id)
        code = 0
    except Exception as exc:
        allowed = {
            "isolated_test_database_required",
            "database_name_refused",
            "command_failed",
            "command_unavailable_or_timeout",
            "archive_invalid",
            "archive_checksum_mismatch",
            "migration_failed",
            "revision_mismatch",
            "postgis_unavailable",
            "cleanup_failed",
            "corruption_not_detected",
            "corrupt_restore_changed_target",
            "restored_data_mismatch",
            "restored_constraint_missing",
            "privacy_or_unknowns_changed",
            "source_changed",
            "conflicting_restore_not_rejected",
            "failed_restore_not_atomic",
        }
        report = {
            "event": "postgis_recovery_smoke",
            "status": "error",
            "run_id": run_id,
            "error": str(exc)
            if isinstance(exc, DrillError) and str(exc) in allowed
            else "drill_failed",
        }
        code = 1
    print(json.dumps(report, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
