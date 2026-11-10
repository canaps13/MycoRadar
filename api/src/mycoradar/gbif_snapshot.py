"""Replay operator-supplied GBIF responses locally; never fetch or publish records."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mycoradar.gbif_client import MAX_RESPONSE_BYTES, GBIFClient, GBIFError, HTTPResult
from mycoradar.gbif_import import ImportBatch, ImportRequest, import_sample

MAX_MANIFEST_BYTES = 128 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


class ResponseRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    url: Annotated[str, Field(pattern=r"^https://api\.gbif\.org/v1/", max_length=2048)]
    path: Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00]+$")]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: Literal["gbif-snapshot-v1"]
    capture_kind: Literal["synthetic", "operator_supplied"]
    captured_at: AwareDatetime
    request: ImportRequest
    responses: Annotated[tuple[ResponseRef, ...], Field(min_length=3, max_length=80)]

    @model_validator(mode="after")
    def not_from_future(self) -> Self:
        if self.captured_at > datetime.now(UTC):
            raise ValueError("capture time cannot be in the future")
        return self


def _read(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise GBIFError("snapshot_input_invalid")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise GBIFError("snapshot_budget_exceeded")
    return content


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        raise GBIFError("snapshot_input_invalid") from None


class SnapshotTransport:
    """One successful body per expected GET, in exact order, with a total byte cap."""

    def __init__(self, path: Path) -> None:
        content = _read(path, MAX_MANIFEST_BYTES)
        self.manifest = SnapshotManifest.model_validate_json(content)
        self.manifest_sha256 = hashlib.sha256(content).hexdigest()
        self._root = _resolve(path.parent)
        self._index = 0
        self._remaining_bytes = MAX_SNAPSHOT_BYTES

    def __call__(self, url: str, timeout: float) -> HTTPResult:
        if self._index >= len(self.manifest.responses):
            raise GBIFError("snapshot_sequence_mismatch")
        entry = self.manifest.responses[self._index]
        if entry.url != url:
            raise GBIFError("snapshot_sequence_mismatch")
        path = _resolve(self._root / entry.path)
        if not path.is_relative_to(self._root):
            raise GBIFError("snapshot_input_invalid")
        content = _read(path, min(MAX_RESPONSE_BYTES, self._remaining_bytes))
        if hashlib.sha256(content).hexdigest() != entry.sha256:
            raise GBIFError("snapshot_checksum_mismatch")
        self._remaining_bytes -= len(content)
        self._index += 1
        return HTTPResult(200, content)

    def finish(self) -> None:
        if self._index != len(self.manifest.responses):
            raise GBIFError("snapshot_sequence_mismatch")


def replay_snapshot(path: Path) -> ImportBatch:
    transport = SnapshotTransport(path)
    manifest = transport.manifest
    batch = import_sample(manifest.request, GBIFClient(transport))
    transport.finish()
    source = batch.receipt["source"]
    assert isinstance(source, dict)
    for field in ("metadata_modified_at", "source_published_at"):
        value = source[field]
        if isinstance(value, str) and datetime.fromisoformat(value) > manifest.captured_at:
            raise GBIFError("snapshot_capture_incoherent")
    # A replay is not a new source capture. Preserve the declared capture, not today's clock.
    receipt = {
        **batch.receipt,
        "fetched_at": manifest.captured_at.isoformat(),
        "raw_records_persisted": True,
        "replay": {
            "schema_version": manifest.schema_version,
            "manifest_sha256": transport.manifest_sha256,
            "capture_kind": manifest.capture_kind,
            "capture_time_basis": "operator_declared_not_independently_verified",
            "network_requests": 0,
            "raw_records_written_by_replay": False,
        },
    }
    return ImportBatch(receipt, batch._rows)
