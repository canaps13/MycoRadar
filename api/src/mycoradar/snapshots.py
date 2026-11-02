"""Incremental private snapshot staging with immutable objects and an atomic head."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mycoradar.artifact_io import canonical, parse_object, read_bytes, write_immutable

MAX_MANIFEST, MAX_PAYLOAD = 262144, 1048576
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,79}$")]


class Conflict(ValueError):
    pass


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class InputVersion(Contract):
    source_id: Id
    sha256: Digest


class Entry(Contract):
    region_id: Id
    taxon_id: Id
    valid_at: str
    layer: Literal["habitat", "fruiting"]
    model_version: Id
    input_versions: Annotated[tuple[InputVersion, ...], Field(min_length=1, max_length=16)]
    sha256: Digest

    @field_validator("valid_at")
    @classmethod
    def timestamp(cls, value: str) -> str:
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
        ):
            raise ValueError("explicit_timestamp_required")
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()

    @field_validator("input_versions")
    @classmethod
    def inputs(cls, value: tuple[InputVersion, ...]) -> tuple[InputVersion, ...]:
        if len({v.source_id for v in value}) != len(value):
            raise ValueError("duplicate_input_version")
        return tuple(sorted(value, key=lambda v: v.source_id))

    def key(self) -> str:
        return hashlib.sha256(
            canonical([self.region_id, self.taxon_id, self.valid_at, self.layer])
        ).hexdigest()


class Update(Entry):
    path: Annotated[str, Field(min_length=1, max_length=2048)]


class Batch(Contract):
    schema_version: Literal["snapshot-batch-v1"]
    updates: Annotated[tuple[Update, ...], Field(min_length=1, max_length=32)]


class Snapshot(Contract):
    schema_version: Literal["private-snapshot-v1"] = "private-snapshot-v1"
    entries: Annotated[dict[Digest, Entry], Field(max_length=128)]
    publication_allowed: Literal[False] = False
    scientific_validation: Literal["not_performed"] = "not_performed"
    computed_at: None = None
    data_cutoff: None = None
    effective_resolution_m: None = None


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("store_path_invalid")
        return path

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(
            self._path(".publication-lock.sqlite"), timeout=5, isolation_level=None
        )
        try:
            db.execute("BEGIN IMMEDIATE")
            revision = db.execute("PRAGMA user_version").fetchone()[0]
            if revision == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("foreign_lock_database")
                db.execute("PRAGMA user_version=1")
            elif revision != 1:
                raise ValueError("unsupported_lock_schema")
            yield
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def head(self) -> str | None:
        path = self._path("current.json")
        if not path.exists():
            return None
        data = parse_object(read_bytes(path, 256))
        if (
            set(data) != {"run_id"}
            or not isinstance(data["run_id"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", data["run_id"])
        ):
            raise ValueError("invalid_snapshot_pointer")
        return str(data["run_id"])

    def read(self, run_id: str | None = None) -> Snapshot | None:
        selected = run_id if run_id is not None else self.head()
        if selected is None:
            return None
        if not re.fullmatch(r"[a-f0-9]{64}", selected):
            raise ValueError("invalid_run_id")
        raw = read_bytes(self._path(f"runs/{selected}.json"), MAX_MANIFEST)
        if hashlib.sha256(raw).hexdigest() != selected:
            raise ValueError("snapshot_checksum_mismatch")
        snapshot = Snapshot.model_validate(parse_object(raw))
        for key, entry in snapshot.entries.items():
            if key != entry.key():
                raise ValueError("target_identity_mismatch")
            payload = read_bytes(self._path(f"objects/{entry.sha256}.json"), MAX_PAYLOAD)
            if hashlib.sha256(payload).hexdigest() != entry.sha256:
                raise ValueError("payload_checksum_mismatch")
            parse_object(payload)
        return snapshot

    def _point(self, run_id: str) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(canonical({"run_id": run_id}))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path("current.json"))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def publish(self, batch_path: Path, *, expected: str | None) -> dict[str, object]:
        batch = Batch.model_validate(parse_object(read_bytes(batch_path, MAX_MANIFEST)))
        if len({update.key() for update in batch.updates}) != len(batch.updates):
            raise ValueError("duplicate_target")
        prepared = []
        for update in batch.updates:
            path = (batch_path.parent / update.path).resolve()
            if not path.is_relative_to(batch_path.parent.resolve()):
                raise ValueError("input_path_invalid")
            data = read_bytes(path, MAX_PAYLOAD)
            if hashlib.sha256(data).hexdigest() != update.sha256:
                raise ValueError("input_checksum_mismatch")
            parse_object(data)
            entry = Entry.model_validate(update.model_dump(exclude={"path"}))
            prepared.append((entry, data))
        with self._lock():
            previous = self.head()
            if previous != expected:
                raise Conflict("snapshot_head_conflict")
            old = self.read(previous) if previous else None
            entries = dict(old.entries) if old else {}
            changed = 0
            for entry, _data in prepared:
                prior = entries.get(entry.key())
                if (
                    prior is not None
                    and prior.model_version == entry.model_version
                    and prior.input_versions == entry.input_versions
                    and prior.sha256 != entry.sha256
                ):
                    raise ValueError("changed_payload_without_new_dependencies")
                changed += prior != entry
                entries[entry.key()] = entry
            snapshot = Snapshot(entries=entries)
            raw = canonical(snapshot.model_dump(mode="json"))
            if len(raw) > MAX_MANIFEST:
                raise ValueError("snapshot_budget_exceeded")
            run_id = hashlib.sha256(raw).hexdigest()
            if previous == run_id:
                return {"run_id": run_id, "changed_targets": 0, "created": False}
            for entry, data in prepared:
                write_immutable(self._path(f"objects/{entry.sha256}.json"), data)
            write_immutable(self._path(f"runs/{run_id}.json"), raw)
            self._point(run_id)
            return {"run_id": run_id, "changed_targets": changed, "created": True}

    def rollback(self, run_id: str, *, expected: str) -> None:
        with self._lock():
            if self.head() != expected:
                raise Conflict("snapshot_head_conflict")
            self.read(run_id)  # Refuse an incomplete or corrupted rollback target.
            if run_id != expected:
                self._point(run_id)


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError("arguments_invalid")


def main() -> int:
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--store", type=Path, required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--batch", type=Path)
        mode.add_argument("--rollback")
        parser.add_argument("--expected-run")
        args = parser.parse_args()
        store = Store(args.store)
        if args.batch:
            result = store.publish(args.batch, expected=args.expected_run)
        else:
            if args.expected_run is None:
                raise ValueError("rollback_head_required")
            store.rollback(args.rollback, expected=args.expected_run)
            result = {"run_id": args.rollback, "rolled_back": True}
        print(
            json.dumps(
                {**result, "publication_allowed": False, "scientific_validation": "not_performed"},
                sort_keys=True,
            )
        )
        return 0
    except Conflict:
        error = "snapshot_head_conflict"
    except (ValueError, OSError, sqlite3.Error, RecursionError):
        error = "snapshot_input_or_state_invalid"
    print(json.dumps({"status": "unavailable", "error": error}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
