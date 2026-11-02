"""Bounded local bytes and immutable private artifacts, without geographic dependencies."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_bytes(path: Path, maximum: int) -> bytes:
    if not path.is_file():
        raise OSError("ordinary_file_required")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("input_budget_exceeded")
    return data


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value: str) -> Any:
    raise ValueError("nonfinite_json")


def parse_object(data: bytes) -> dict[str, Any]:
    value = json.loads(data, object_pairs_hook=_object, parse_constant=_constant)
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return value


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode()


def write_immutable(path: Path, data: bytes) -> bool:
    """An identical retry preserves bytes/mtime; never replace a different artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            if read_bytes(path, len(data)) != data:
                raise ValueError("immutable_artifact_conflict") from None
            return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
