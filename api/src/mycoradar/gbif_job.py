"""Read a bounded public GBIF sample in memory; emit only a provenance/aggregate receipt."""

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from pydantic import ValidationError

from mycoradar.gbif_client import GBIFClient, GBIFError
from mycoradar.gbif_import import ImportRequest, admit_sample, import_sample
from mycoradar.occurrence_outputs import audit_payload
from mycoradar.occurrence_privacy import AdmissionError, PrivacyPolicy


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise GBIFError("arguments_invalid")


def main() -> int:
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("--request", type=Path, required=True)
        args = parser.parse_args()
        with args.request.open("rb") as stream:
            content = stream.read(65537)
        if len(content) > 65536:
            raise GBIFError("request_file_budget_exceeded")
        request = ImportRequest.model_validate_json(content)
        batch = import_sample(request, GBIFClient())
        # This command has no publication switch. Scientific/location admission is a separate gate.
        policy = PrivacyPolicy()
        publication = admit_sample(batch, policy)
        result = {
            "status": "partial",
            "receipt": batch.receipt,
            "admission": audit_payload(publication, policy),
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n")
        return 0
    except GBIFError as error:
        allowed = {
            "arguments_invalid",
            "request_file_budget_exceeded",
            "invalid_service_path",
            "response_budget_exceeded",
            "request_budget_exceeded",
            "provider_unreachable",
            "provider_backoff_required",
            "provider_http_error",
            "provider_json_invalid",
            "dataset_rights_unverified",
            "taxon_mapping_unverified",
            "record_scope_mismatch",
            "pagination_invalid",
            "dataset_changed",
        }
        code = str(error) if str(error) in allowed else "import_failed"
    except (OSError, UnicodeError, ValidationError, AdmissionError):
        code = "request_or_admission_invalid"
    sys.stdout.write(json.dumps({"status": "unavailable", "error": code}) + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
