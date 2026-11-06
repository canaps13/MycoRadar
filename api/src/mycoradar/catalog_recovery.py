"""Offline recovery of the admitted public catalogue; no database or network access."""

import argparse
import json
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Never

from pydantic import ValidationError

from mycoradar.catalog import MAX_BYTES
from mycoradar.catalog_models import Snapshot


class RecoveryError(Exception):
    """Static diagnostic code only: never render paths, input or validation details."""


def read_validated(path: Path, expected_sha256: str) -> tuple[bytes, Snapshot]:
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise RecoveryError("invalid_checksum")
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RecoveryError("not_regular_file")
        with path.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise RecoveryError("read_failed") from exc
    if len(content) > MAX_BYTES:
        raise RecoveryError("size_limit")
    if sha256(content).hexdigest() != expected_sha256:
        raise RecoveryError("checksum_mismatch")
    try:
        snapshot = Snapshot.model_validate_json(content)
    except ValidationError as exc:
        raise RecoveryError("invalid_catalogue") from exc
    return content, snapshot


def write_new(path: Path, content: bytes) -> None:
    """Publish a complete file exclusively; existing files and symlinks are never replaced."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".recovery-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-filesystem hard link is atomic and refuses every existing destination.
        os.link(temporary, path)
    except FileExistsError as exc:
        raise RecoveryError("destination_exists") from exc
    except OSError as exc:
        raise RecoveryError("write_failed") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def inspect(
    snapshot: Snapshot, now: datetime, max_source_age_seconds: int | None = None
) -> dict[str, Any]:
    """Aggregate ages without exposing source URLs, names, coordinates or paths."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise RecoveryError("invalid_clock")
    if max_source_age_seconds is not None and max_source_age_seconds <= 0:
        raise RecoveryError("invalid_age_policy")
    alerts: set[str] = set()

    def age(date: datetime) -> float | None:
        seconds = (now - date).total_seconds()
        if seconds < 0:
            alerts.add("clock_inconsistent")
            return None
        return seconds

    publication_age = age(snapshot.published_at)
    source_ages = [age(s.source_published_at) for s in snapshot.metadata if s.source_published_at]
    known_source_ages = [value for value in source_ages if value is not None]
    fetch_ages = [age(s.fetched_at) for s in snapshot.metadata]
    known_fetch_ages = [value for value in fetch_ages if value is not None]
    unknown_dates = sum(s.source_published_at is None for s in snapshot.metadata)
    if not snapshot.metadata:
        alerts.add("sources_unavailable")
    if unknown_dates:
        alerts.add("source_date_unknown")
    if max_source_age_seconds is not None and any(
        value > max_source_age_seconds for value in known_source_ages
    ):
        alerts.add("source_age_exceeded")
    states = {
        name: getattr(snapshot.availability, name).status
        for name in ("regions", "species", "cells", "metadata")
    }
    return {
        "checked_at": now.astimezone(UTC).isoformat(),
        "catalogue_publication_age_seconds": publication_age,
        "oldest_known_source_age_seconds": max(known_source_ages, default=None),
        "oldest_fetch_age_seconds": max(known_fetch_ages, default=None),
        "source_count": len(snapshot.metadata),
        "source_date_unknown_count": unknown_dates,
        "source_age_limit_seconds": max_source_age_seconds,
        "coverage": states,
        "alerts": sorted(alerts),
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise RecoveryError("invalid_arguments")


def run(argv: list[str] | None = None) -> tuple[dict[str, Any], int]:
    operation = "unknown"
    try:
        parser = SafeParser(description=__doc__)
        commands = parser.add_subparsers(dest="operation", required=True)
        for name in ("backup", "verify", "restore", "audit"):
            command = commands.add_parser(name)
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--sha256", required=True)
            if name in ("backup", "restore"):
                command.add_argument("--output", type=Path, required=True)
            if name == "audit":
                command.add_argument("--max-source-age-seconds", type=int, required=True)
        args = parser.parse_args(argv)
        operation = args.operation
        content, snapshot = read_validated(args.input, args.sha256)
        metrics = inspect(
            snapshot, datetime.now(UTC), getattr(args, "max_source_age_seconds", None)
        )
        if operation in ("backup", "restore"):
            write_new(args.output, content)
        attention = operation == "audit" and bool(metrics["alerts"])
        return {
            "event": "catalogue_recovery",
            "operation": operation,
            "status": "attention" if attention else "ok",
            "integrity": "verified",
            "catalog_version": args.sha256,
            "bytes": len(content),
            "metrics": metrics,
            "scientific_validation": "not_performed",
        }, 2 if attention else 0
    except RecoveryError as exc:
        return {
            "event": "catalogue_recovery",
            "operation": operation,
            "status": "error",
            "integrity": "unavailable",
            "error": str(exc),
        }, 1
    except OSError:
        # Includes cleanup failures; no exception text is emitted.
        return {
            "event": "catalogue_recovery",
            "operation": operation,
            "status": "error",
            "integrity": "unavailable",
            "error": "filesystem_failed",
        }, 1


def main() -> None:
    report, code = run()
    print(json.dumps(report, allow_nan=False, sort_keys=True))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
