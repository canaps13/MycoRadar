"""Offline admission of normalized NDJSON; only checked public artifacts go to stdout."""

import argparse
import json
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import NoReturn

from mycoradar.occurrence_outputs import (
    api_payload,
    audit_payload,
    export_zip,
    public_paths,
    tile_geojson,
)
from mycoradar.occurrence_privacy import AdmissionError, PrivacyPolicy, admit_occurrences
from pydantic import ValidationError

MAX_LINE_BYTES = 64 * 1024
MAX_POLICY_BYTES = 1024 * 1024


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's normal diagnostic echoes unrecognized (potentially private) arguments.
        raise AdmissionError("arguments_invalid")


def read_records(path: Path) -> Iterator[Mapping[str, object]]:
    with path.open("rb") as stream:
        while line := stream.readline(MAX_LINE_BYTES + 1):
            if len(line) > MAX_LINE_BYTES:
                raise AdmissionError("input_budget_exceeded")
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError
            except (ValueError, UnicodeError):
                raise AdmissionError("input_invalid") from None
            yield record


def main() -> int:
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--policy", type=Path, required=True)
        parser.add_argument("--input", type=Path, required=True)
        parser.add_argument(
            "--format", choices=("api", "tiles", "export", "urls", "audit"), default="api"
        )
        args = parser.parse_args()
        with args.policy.open("rb") as stream:
            content = stream.read(MAX_POLICY_BYTES + 1)
        if len(content) > MAX_POLICY_BYTES:
            raise AdmissionError("policy_budget_exceeded")
        policy = PrivacyPolicy.model_validate_json(content)
        publication = admit_occurrences(read_records(args.input), policy)
        if args.format == "export":
            sys.stdout.buffer.write(export_zip(publication, policy))
        else:
            render = {
                "api": api_payload,
                "tiles": tile_geojson,
                "urls": public_paths,
                "audit": audit_payload,
            }[args.format]
            sys.stdout.write(
                json.dumps(render(publication, policy), ensure_ascii=False, sort_keys=True) + "\n"
            )
        return 0
    except AdmissionError as error:
        allowed = {
            "arguments_invalid",
            "input_budget_exceeded",
            "input_invalid",
            "policy_budget_exceeded",
            "policy_unavailable",
            "record_budget_exceeded",
            "policy_changed",
            "admission_required",
            "invalid_clock",
        }
        code = str(error) if str(error) in allowed else "admission_failed"
    except (OSError, UnicodeError, ValidationError):
        code = "policy_or_input_invalid"
    sys.stdout.write(json.dumps({"status": "unavailable", "error": code}) + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
