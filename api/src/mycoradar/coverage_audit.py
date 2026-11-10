"""Audit local GBIF month facets; never read or publish occurrence rows."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

MAX_MANIFEST = 128 * 1024
MAX_RESPONSE = 100_000
SEASONS = {"winter": (12, 1, 2), "spring": (3, 4, 5), "summer": (6, 7, 8), "autumn": (9, 10, 11)}


class AuditError(ValueError):
    """Fixed diagnostic, without paths, queries or source contents."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise AuditError("coverage_input_invalid")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def explicit_timestamp(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        value,
    ):
        raise ValueError("An explicit ISO capture timestamp with timezone is required")
    return value


class Capture(Contract):
    region_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9:_-]{1,80}$")]
    path: str
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    fetched_at: Annotated[AwareDatetime, BeforeValidator(explicit_timestamp)]
    request_url: str


class Manifest(Contract):
    schema_version: str = Field(pattern="^gbif-month-audit-v1$")
    capture_kind: str = Field(pattern="^(synthetic|operator_supplied)$")
    dataset_key: UUID
    taxon_key: Annotated[int, Field(strict=True, gt=0)]
    checklist_key: UUID
    # This label is an operator declaration, not a new taxonomic admission.
    scientific_name: Annotated[str, Field(min_length=1, max_length=200)]
    captures: Annotated[tuple[Capture, ...], Field(min_length=1, max_length=16)]


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditError("coverage_input_invalid")
        result[key] = value
    return result


def load_json(path: Path, maximum: int) -> tuple[Any, str]:
    if not path.is_file():
        raise AuditError("coverage_input_invalid")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise AuditError("coverage_input_invalid")
    return json.loads(raw, object_pairs_hook=unique_object), hashlib.sha256(raw).hexdigest()


def count(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or not (int(positive) <= value <= 10**12):
        raise AuditError("coverage_input_invalid")
    return value


def month_counts(data: Any) -> tuple[int, dict[int, int]]:
    if (
        not isinstance(data, dict)
        or type(data.get("limit")) is not int
        or data["limit"] != 0
        or type(data.get("offset")) is not int
        or data["offset"] != 0
        or data.get("results") != []
    ):
        raise AuditError("coverage_input_invalid")
    total = count(data.get("count"))
    facets = data.get("facets")
    if not isinstance(facets, list) or len(facets) != 1:
        raise AuditError("coverage_input_invalid")
    facet = facets[0]
    if not isinstance(facet, dict) or facet.get("field") != "MONTH":
        raise AuditError("coverage_input_invalid")
    entries = facet.get("counts")
    if not isinstance(entries, list) or len(entries) > 12:
        raise AuditError("coverage_input_invalid")
    months: dict[int, int] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not re.fullmatch(r"[1-9]|1[0-2]", str(entry.get("name"))):
            raise AuditError("coverage_input_invalid")
        month = int(entry["name"])
        if month in months:
            raise AuditError("coverage_input_invalid")
        months[month] = count(entry.get("count"), positive=True)
    if sum(months.values()) > total:
        raise AuditError("coverage_input_invalid")
    return total, months


def band(number: int) -> str:
    # Coarse disclosure policy, not a proof of anonymity or scientific sufficiency.
    return "0_indexed" if number == 0 else "1_to_4_withheld" if number < 5 else "5_or_more"


def audit(path: Path) -> dict[str, Any]:
    raw, manifest_digest = load_json(path, MAX_MANIFEST)
    manifest = Manifest.model_validate(raw)
    if len({c.region_id for c in manifest.captures}) != len(manifest.captures):
        raise AuditError("coverage_input_invalid")
    regions = []
    for capture in manifest.captures:
        url = urlsplit(capture.request_url)
        query = parse_qs(url.query, keep_blank_values=True)
        expected = {
            "datasetKey": str(manifest.dataset_key),
            "taxonKey": str(manifest.taxon_key),
            "checklistKey": str(manifest.checklist_key),
            "limit": "0",
            "offset": "0",
            "facet": "month",
            "facetLimit": "12",
            "facetMincount": "1",
            "license": "CC_BY_4_0",
        }
        if (
            url.scheme != "https"
            or url.netloc != "api.gbif.org"
            or url.path != "/v1/occurrence/search"
            or url.fragment
            or any(len(values) != 1 for values in query.values())
            or any(query.get(key) != [value] for key, value in expected.items())
            or set(query)
            - (expected.keys() | {"geometry", "country", "hasCoordinate", "hasGeospatialIssue"})
            or not query.get("geometry", [""])[0]
            or capture.fetched_at > datetime.now(UTC)
        ):
            raise AuditError("coverage_input_invalid")
        source = (path.parent / capture.path).resolve()
        if not source.is_relative_to(path.parent.resolve()):
            raise AuditError("coverage_input_invalid")
        data, digest = load_json(source, MAX_RESPONSE)
        if digest != capture.sha256:
            raise AuditError("coverage_input_invalid")
        total, months = month_counts(data)
        regions.append(
            {
                "region_id": capture.region_id,
                "source_sha256": digest,
                "fetched_at": capture.fetched_at.isoformat(),
                "indexed_count_band": band(total),
                "unknown_month_band": band(total - sum(months.values())),
                "seasons": {
                    s: band(sum(months.get(m, 0) for m in values)) for s, values in SEASONS.items()
                },
            }
        )
    return {
        "schema_version": "pilot-coverage-audit-v1",
        "adapter_version": "gbif-month-facets-audit-v1",
        "status": "partial",
        "capture_kind": manifest.capture_kind,
        "manifest_sha256": manifest_digest,
        "dataset_key": str(manifest.dataset_key),
        "declared_taxon": manifest.scientific_name,
        "scientific_status": "blocked",
        "release_review_required": True,
        "selected_pilot_taxon": None,
        "unmeasured": [
            "sampling_effort",
            "coordinate_uncertainty",
            "duplicates",
            "identification_quality",
            "non_detections",
        ],
        "count_semantics": (
            "Indexed rows in declared query scope; not abundance or biological absence. "
            "Scopes may overlap; never sum regions."
        ),
        "disclosure": (
            "Only zero, 1-4 withheld or at least 5; "
            "no exact positive counts, URLs, coordinates or occurrence rows."
        ),
        "rights_review": (
            "Required separately; checksums and query filters are not source signatures."
        ),
        "regions": regions,
    }


def main() -> int:
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("--manifest", type=Path, required=True)
        args = parser.parse_args()
        result = audit(args.manifest)
    except (ValueError, OSError, TypeError, KeyError, RecursionError):
        print(json.dumps({"status": "unavailable", "error": "coverage_input_invalid"}))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
