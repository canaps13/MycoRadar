"""Small, read-only GBIF search imports; no database writes or scientific publication."""

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, Final, Literal, TypeGuard
from urllib.parse import urlencode
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mycoradar.gbif_client import BASE_URL, GBIFClient, GBIFError, object_json
from mycoradar.occurrence_privacy import PrivacyPolicy, PublicPublication, admit_occurrences

BACKBONE: Final = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
CRITICAL_ISSUES = frozenset(
    {
        "COORDINATE_INVALID",
        "COORDINATE_OUT_OF_RANGE",
        "COORDINATE_REPROJECTION_FAILED",
        "COORDINATE_REPROJECTION_SUSPICIOUS",
        "COORDINATE_UNCERTAINTY_METERS_INVALID",
        "COUNTRY_COORDINATE_MISMATCH",
        "COUNTRY_MISMATCH",
        "GEODETIC_DATUM_INVALID",
        "TAXON_MATCH_FUZZY",
        "TAXON_MATCH_HIGHERRANK",
        "TAXON_MATCH_AGGREGATE",
        "PRESUMED_SWAPPED_COORDINATE",
        "PRESUMED_NEGATED_LONGITUDE",
        "PRESUMED_NEGATED_LATITUDE",
        "SUSPECTED_SWAPPED_COORDINATE",
        "SUSPECTED_NEGATED_LONGITUDE",
        "SUSPECTED_NEGATED_LATITUDE",
        "ZERO_COORDINATE",
    }
)
REPORTED_ISSUES = CRITICAL_ISSUES | {
    "CONTINENT_DERIVED_FROM_COORDINATES",
    "COUNTRY_DERIVED_FROM_COORDINATES",
    "COORDINATE_REPROJECTED",
    "COORDINATE_ROUNDED",
    "TAXON_ID_NOT_FOUND",
    "FOOTPRINT_WKT_MISMATCH",
    "RECORDED_DATE_INVALID",
    "RECORDED_DATE_MISMATCH",
}
LICENSES = {
    f"{scheme}://creativecommons.org/{path}{suffix}": identifier
    for scheme in ("http", "https")
    for path, identifier in (
        ("licenses/by/4.0/", "CC-BY-4.0"),
        ("publicdomain/zero/1.0/", "CC0-1.0"),
    )
    for suffix in ("", "legalcode")
}


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    dataset_key: UUID
    scientific_name: Annotated[str, Field(pattern=r"^[A-Z][a-z]+ [a-z-]+$", max_length=150)]
    country: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    page_size: Annotated[int, Field(strict=True, ge=1, le=300)] = 20
    max_records: Annotated[int, Field(strict=True, ge=1, le=1000)] = 40
    # This adapter deliberately pins the legacy identifiers, which GBIF still supports.
    checklist_key: Literal["d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"] = BACKBONE


@dataclass(frozen=True)
class ImportBatch:
    receipt: Mapping[str, object]
    _rows: tuple[Mapping[str, object], ...] = field(repr=False)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _date(raw: Mapping[str, object]) -> str | None:
    issues = raw.get("issues", [])
    if not isinstance(issues, list) or any(
        flag in issues for flag in ("RECORDED_DATE_INVALID", "RECORDED_DATE_MISMATCH")
    ):
        return None
    value = raw.get("eventDate")
    # Intervals, timestamps, years and absent values remain unknown; never truncate them.
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    return None


def _finite_number(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _metadata(content: bytes, dataset_key: str) -> dict[str, object]:
    raw = object_json(content)
    license_id = LICENSES.get(str(raw.get("license")))
    citation = raw.get("citation")
    if (
        raw.get("key") != dataset_key
        or raw.get("rights") not in (None, "")
        or license_id is None
        or not isinstance(citation, dict)
        or not isinstance(citation.get("text"), str)
        or not citation["text"].strip()
        or len(citation["text"]) > 2048
        or not isinstance(raw.get("title"), str)
        or not isinstance(raw.get("publishingOrganizationKey"), str)
    ):
        raise GBIFError("dataset_rights_unverified")
    for metadata_field in ("modified", "pubDate"):
        value = raw.get(metadata_field)
        if value is not None:
            try:
                if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
                    raise ValueError
            except ValueError:
                raise GBIFError("dataset_rights_unverified") from None
    doi = raw.get("doi")
    if doi is not None and (
        not isinstance(doi, str) or not re.fullmatch(r"10\.[0-9]{4,9}/[-._;()/:A-Za-z0-9]+", doi)
    ):
        raise GBIFError("dataset_rights_unverified")
    # No contacts, personal names from records, descriptions or arbitrary URLs are retained.
    return {
        "dataset_key": dataset_key,
        "source_url": BASE_URL + "dataset/" + dataset_key,
        "title": raw["title"],
        "license": license_id,
        "license_url": raw["license"],
        "citation": citation["text"],
        "doi": raw.get("doi"),
        "publisher_key": raw["publishingOrganizationKey"],
        "metadata_modified_at": raw.get("modified"),
        "source_published_at": raw.get("pubDate"),
    }


def _normalize(
    raw: Mapping[str, object], request: ImportRequest, taxon_key: int, source_version: str
) -> dict[str, object]:
    key = raw.get("key")
    if type(key) is not int or key <= 0:
        return {}
    if (
        raw.get("datasetKey") != str(request.dataset_key)
        or raw.get("countryCode") != request.country
    ):
        raise GBIFError("record_scope_mismatch")
    identity: dict[str, object] = {
        "record_id": str(key),
        "source_id": f"gbif:{request.dataset_key}",
        "source_version": source_version,
    }
    # Invalid/restrictive copies keep their identity so they suppress an otherwise public duplicate.
    accepted_key = raw.get("acceptedTaxonKey", raw.get("taxonKey"))
    issues = raw.get("issues", [])
    if (
        type(accepted_key) is not int
        or accepted_key != taxon_key
        or raw.get("taxonRank") != "SPECIES"
        or raw.get("occurrenceStatus") != "PRESENT"
        or not isinstance(issues, list)
        or any(not isinstance(issue, str) for issue in issues)
        or any(issue in CRITICAL_ISSUES for issue in issues)
    ):
        return identity
    longitude, latitude = raw.get("decimalLongitude"), raw.get("decimalLatitude")
    uncertainty = raw.get("coordinateUncertaintyInMeters")
    record_license = LICENSES.get(str(raw.get("license")))
    if (
        not _finite_number(longitude)
        or not _finite_number(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
        or (longitude == 0 and latitude == 0)
        or record_license is None
        or (uncertainty is not None and (not _finite_number(uncertainty) or uncertainty <= 0))
        or any(
            raw.get(field) is not None and not isinstance(raw.get(field), str)
            for field in ("informationWithheld", "dataGeneralizations")
        )
    ):
        return identity
    generalized = bool(raw.get("dataGeneralizations"))
    if generalized and uncertainty is None:
        return identity
    return {
        **identity,
        "record_license": record_license,
        "taxon_id": f"gbif-backbone:{taxon_key}",
        "country_code": request.country,
        "coordinate_crs": "EPSG:4326",
        "longitude": longitude,
        "latitude": latitude,
        "location_uncertainty_m": uncertainty,
        "event_date": _date(raw),
        "generalized": generalized,
        "informationWithheld": raw.get("informationWithheld") or "",
        "dataGeneralizations": raw.get("dataGeneralizations") or "",
        # Being reachable through GBIF is not evidence of a location release review.
        "location_visibility": "unknown",
        "sensitivity": "unknown",
        "reviewed_for_release": False,
    }


def import_sample(request: ImportRequest, client: GBIFClient) -> ImportBatch:
    match_bytes = client.get(
        "species/match",
        {
            "name": request.scientific_name,
            "kingdom": "Fungi",
            "strict": "true",
        },
    )
    match = object_json(match_bytes)
    taxon_key = match.get("usageKey")
    if (
        type(taxon_key) is not int
        or taxon_key <= 0
        or match.get("rank") != "SPECIES"
        or match.get("canonicalName") != request.scientific_name
        or match.get("matchType") != "EXACT"
        or match.get("status") != "ACCEPTED"
        or match.get("kingdom") != "Fungi"
    ):
        raise GBIFError("taxon_mapping_unverified")
    metadata_bytes = client.get(f"dataset/{request.dataset_key}")
    metadata = _metadata(metadata_bytes, str(request.dataset_key))
    source_version = _digest(metadata_bytes)
    rows: list[Mapping[str, object]] = []
    pages: list[dict[str, object]] = []
    issue_counts: Counter[str] = Counter()
    offset = 0
    ended = False
    while len(rows) < request.max_records:
        limit = min(request.page_size, request.max_records - len(rows))
        parameters: dict[str, str | int] = {
            "datasetKey": str(request.dataset_key),
            "taxonKey": taxon_key,
            "checklistKey": request.checklist_key,
            "country": request.country,
            "hasCoordinate": "true",
            "offset": offset,
            "limit": limit,
        }
        content = client.get("occurrence/search", parameters)
        page = object_json(content)
        results = page.get("results")
        if (
            type(page.get("offset")) is not int
            or page.get("offset") != offset
            or type(page.get("limit")) is not int
            or page.get("limit") != limit
            or type(page.get("endOfRecords")) is not bool
            or not isinstance(results, list)
            or len(results) > limit
            or any(not isinstance(row, dict) for row in results)
            or (not page["endOfRecords"] and len(results) != limit)
        ):
            raise GBIFError("pagination_invalid")
        pages.append(
            {
                "offset": offset,
                "limit": limit,
                "sha256": _digest(content),
                "request_url": BASE_URL + "occurrence/search?" + urlencode(parameters),
            }
        )
        for raw in results:
            flags = raw.get("issues", [])
            if isinstance(flags, list):
                for flag in flags:
                    issue_counts[
                        flag if isinstance(flag, str) and flag in REPORTED_ISSUES else "OTHER_FLAGS"
                    ] += 1
        rows.extend(_normalize(row, request, taxon_key, source_version) for row in results)
        offset += len(results)
        ended = page["endOfRecords"] is True
        if ended:
            break
    # Verify the registry did not change during the job. This is not an atomic occurrence index.
    if (
        _metadata(client.get(f"dataset/{request.dataset_key}"), str(request.dataset_key))
        != metadata
    ):
        raise GBIFError("dataset_changed")
    fetched_at = datetime.now(UTC).isoformat()
    identities = [row["record_id"] for row in rows if "record_id" in row]
    quality = {
        "received": len(rows),
        "unique_identities": len(set(identities)),
        "duplicate_identities": len(identities) - len(set(identities)),
        "normalized": sum("record_license" in row for row in rows),
        "unusable_records": sum("record_license" not in row for row in rows),
        "unknown_calendar_dates": sum(
            row.get("event_date") is None for row in rows if "record_license" in row
        ),
        "unknown_coordinate_uncertainty": sum(
            row.get("location_uncertainty_m") is None for row in rows if "record_license" in row
        ),
        "generalized": sum(row.get("generalized") is True for row in rows),
        "provider_issue_counts": dict(sorted(issue_counts.items())),
    }
    provenance = {
        "schema_version": "gbif-sample-v1",
        "adapter_version": "gbif-search-v1",
        "request": request.model_dump(mode="json"),
        "fetched_at": fetched_at,
        "taxonomy": {
            "checklist_key": BACKBONE,
            "taxon_key": taxon_key,
            "canonical_name": request.scientific_name,
            "match_sha256": _digest(match_bytes),
            "status": "legacy_backbone_compatibility_not_current_COL",
        },
        "source": {**metadata, "metadata_sha256": source_version},
        "pages": pages,
        "transport_end_of_records": ended,
        "coverage_status": "partial",
        "download_doi": None,
        "raw_records_persisted": False,
        "quality": quality,
        "transformations": [
            "GBIF interpreted WGS84 only",
            "strict species mapping",
            "exact calendar dates only; others unknown",
            "no coordinate changes",
            "personal/free-text fields discarded",
            "location release unknown; MR-048 admission required",
        ],
    }
    # Stable receipt identity excludes the time of this execution, but includes all input hashes.
    provenance["sample_version"] = _digest(
        json.dumps(
            {
                "request": provenance["request"],
                "adapter_version": provenance["adapter_version"],
                "source_version": source_version,
                "match_sha256": _digest(match_bytes),
                "pages": pages,
            },
            sort_keys=True,
        ).encode()
    )
    return ImportBatch(provenance, tuple(rows))


def admit_sample(batch: ImportBatch, policy: PrivacyPolicy) -> PublicPublication:
    """No implicit permissions: GBIF reachability and dataset licence cannot approve a location."""
    return admit_occurrences(batch._rows, policy)
