"""All transport/data fixtures are invented; live checks are explicit manual sample jobs."""

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from mycoradar.gbif_client import (
    MAX_RESPONSE_BYTES,
    GBIFClient,
    GBIFError,
    HTTPResult,
    _backoff,
)
from mycoradar.gbif_import import ImportRequest, admit_sample, import_sample
from mycoradar.gbif_job import main
from mycoradar.occurrence_outputs import api_payload, audit_payload, tile_geojson
from mycoradar.occurrence_privacy import PrivacyPolicy, SourceRule, TaxonRule
from pydantic import ValidationError

DATASET = "11111111-1111-4111-8111-111111111111"
METADATA = {
    "key": DATASET,
    "title": "Synthetic occurrence fixture",
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "publishingOrganizationKey": DATASET,
    "citation": {"text": "Invented publisher, tests only"},
    "doi": "10.0000/synthetic",
    "modified": "2026-01-02T00:00:00Z",
    "pubDate": "2026-01-01T00:00:00Z",
}
MATCH = {
    "usageKey": 123,
    "rank": "SPECIES",
    "status": "ACCEPTED",
    "matchType": "EXACT",
    "kingdom": "Fungi",
    "canonicalName": "Testus syntheticus",
}


def row(key: int = 1, **changes: object) -> dict[str, object]:
    return {
        "key": key,
        "datasetKey": DATASET,
        "countryCode": "FR",
        "taxonKey": 123,
        "taxonRank": "SPECIES",
        "occurrenceStatus": "PRESENT",
        "issues": [],
        "decimalLongitude": 5.125,
        "decimalLatitude": 43.875,
        "coordinateUncertaintyInMeters": 4321.0,
        "eventDate": "2026-01-03",
        "license": METADATA["license"],
        "dataGeneralizations": "coarsened by producer",
        "recordedBy": "PRIVATE_PERSON_SENTINEL",
        "locality": "PRIVATE_LOCALITY_SENTINEL",
        "verbatimLongitude": 5.123456789,
        **changes,
    }


def request(**changes: object) -> ImportRequest:
    return ImportRequest.model_validate(
        {
            "dataset_key": DATASET,
            "scientific_name": "Testus syntheticus",
            "country": "FR",
            "page_size": 2,
            "max_records": 3,
            **changes,
        }
    )


class Provider:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows if rows is not None else [row(1), row(2), row(3)]
        self.urls: list[str] = []
        self.metadata = dict(METADATA)
        self.match = dict(MATCH)
        self.page_change: Callable[[dict[str, object]], None] = lambda page: None

    def __call__(self, url: str, timeout: float) -> HTTPResult:
        assert 0 < timeout <= 10 and url.startswith("https://api.gbif.org/v1/")
        self.urls.append(url)
        parts = urlsplit(url)
        if parts.path.endswith("species/match"):
            body = self.match
        elif "/dataset/" in parts.path:
            body = self.metadata
        else:
            params = parse_qs(parts.query)
            limit, offset = int(params["limit"][0]), int(params["offset"][0])
            body = {
                "limit": limit,
                "offset": offset,
                "endOfRecords": offset + limit >= len(self.rows),
                "results": self.rows[offset : offset + limit],
            }
            self.page_change(body)
        return HTTPResult(200, json.dumps(body).encode())


def test_paging_mapping_provenance_and_safe_default_admission() -> None:
    provider = Provider()
    batch = import_sample(request(), GBIFClient(provider))
    receipt = batch.receipt
    assert len(receipt["pages"]) == 2
    assert receipt["coverage_status"] == "partial" and receipt["transport_end_of_records"]
    assert receipt["download_doi"] is None and not receipt["raw_records_persisted"]
    assert (
        receipt["source"]["metadata_sha256"]
        == hashlib.sha256(json.dumps(METADATA).encode()).hexdigest()
    )
    assert receipt["quality"]["received"] == 3
    assert receipt["quality"]["record_license_counts"] == {"CC-BY-4.0": 3}
    assert receipt["source"]["metadata_modified_at"] != receipt["source"]["source_published_at"]
    policy = PrivacyPolicy()
    publication = admit_sample(batch, policy)
    audit = audit_payload(publication, policy)
    assert audit["processed"] == 3 and audit["accepted"] == 0
    assert "PRIVATE_" not in json.dumps({"receipt": receipt, "audit": audit})
    normalized = batch._rows[0]
    assert normalized["longitude"] == 5.125 and normalized["location_uncertainty_m"] == 4321
    assert normalized["generalized"] is True and normalized["reviewed_for_release"] is False
    assert not {"recordedBy", "locality", "verbatimLongitude"} & normalized.keys()
    assert "5.123456789" not in repr(batch)


def test_search_is_a_bounded_sample_and_versions_are_reproducible() -> None:
    first = import_sample(request(max_records=1), GBIFClient(Provider()))
    second = import_sample(request(max_records=1), GBIFClient(Provider()))
    assert not first.receipt["transport_end_of_records"]
    assert first.receipt["sample_version"] == second.receipt["sample_version"]
    changed = import_sample(request(max_records=1), GBIFClient(Provider([row(1, eventDate=None)])))
    assert first.receipt["sample_version"] != changed.receipt["sample_version"]


def test_even_active_policy_does_not_turn_api_visibility_into_location_permission() -> None:
    batch = import_sample(
        request(),
        GBIFClient(Provider([row(1), row(1), row(1, informationWithheld="PRIVATE_WITHHELD")])),
    )
    now = datetime.now(UTC)
    policy = PrivacyPolicy(
        review_reference="https://example.invalid/review",
        reviewed_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        sources=(
            SourceRule(
                id=f"gbif:{DATASET}",
                version=batch.receipt["source"]["metadata_sha256"],
                license="CC-BY-4.0",
                attribution="Synthetic",
                citation_url="https://example.invalid/cite",
                fetched_at=now,
                source_published_at=None,
                public_distribution_authorized=True,
            ),
        ),
        taxa=(TaxonRule(taxon_id="gbif-backbone:123", country_code="FR", sensitivity="public"),),
    )
    publication = admit_sample(batch, policy)
    assert not publication.records
    assert batch.receipt["quality"]["duplicate_identities"] == 2
    assert "conflicting_identity" in audit_payload(publication, policy)["reasons"]
    payloads = json.dumps([api_payload(publication, policy), tile_geojson(publication, policy)])
    assert "PRIVATE_" not in payloads and "5.125" not in payloads


@pytest.mark.parametrize(
    "change",
    [
        {"matchType": "FUZZY"},
        {"rank": "GENUS"},
        {"status": "SYNONYM"},
        {"canonicalName": "Other species"},
        {"kingdom": "Plantae"},
        {"usageKey": True},
    ],
)
def test_ambiguous_or_incompatible_taxonomy_is_not_used(change: dict[str, object]) -> None:
    provider = Provider()
    provider.match.update(change)
    with pytest.raises(GBIFError, match="taxon_mapping_unverified"):
        import_sample(request(), GBIFClient(provider))
    assert len(provider.urls) == 1


@pytest.mark.parametrize(
    "license_url",
    [None, "CC-BY-NC-4.0", "https://creativecommons.org/licenses/by-nc/4.0/", "unknown"],
)
def test_unverified_dataset_rights_stop_before_reading_occurrences(license_url: object) -> None:
    provider = Provider()
    provider.metadata["license"] = license_url
    with pytest.raises(GBIFError, match="dataset_rights_unverified"):
        import_sample(request(), GBIFClient(provider))
    assert not any("occurrence/search" in url for url in provider.urls)


@pytest.mark.parametrize(
    "changes",
    [
        {"datasetKey": "OTHER"},
        {"countryCode": "GB"},
    ],
)
def test_wrong_scope_aborts_the_whole_batch(changes: dict[str, object]) -> None:
    with pytest.raises(GBIFError, match="record_scope_mismatch"):
        import_sample(request(), GBIFClient(Provider([row(1), row(2, **changes)])))


@pytest.mark.parametrize(
    "value",
    ["2026", "2026-01", "2026-02-30", "2026-01-01/2026-01-03", "2026-01-03T23:00:00Z", 0, None],
)
def test_date_precision_is_not_invented(value: object) -> None:
    batch = import_sample(request(), GBIFClient(Provider([row(1, eventDate=value)])))
    assert batch._rows[0]["event_date"] is None


@pytest.mark.parametrize(
    "flag",
    [
        "CONTINENT_DERIVED_FROM_COORDINATES",
        "COUNTRY_DERIVED_FROM_COORDINATES",
        "COORDINATE_REPROJECTED",
        "COORDINATE_ROUNDED",
    ],
)
def test_successful_coordinate_interpretation_is_preserved_without_guessing_precision(
    flag: str,
) -> None:
    batch = import_sample(request(), GBIFClient(Provider([row(1, issues=[flag])])))
    assert batch.receipt["quality"]["normalized"] == 1
    assert batch._rows[0]["longitude"] == 5.125
    assert batch.receipt["quality"]["provider_issue_counts"] == {flag: 1}


def test_unrecognized_issue_text_is_not_reflected_in_a_receipt() -> None:
    batch = import_sample(request(), GBIFClient(Provider([row(1, issues=["PRIVATE_ISSUE_TEXT"])])))
    assert "PRIVATE_ISSUE_TEXT" not in json.dumps(batch.receipt)
    assert batch.receipt["quality"]["provider_issue_counts"] == {"OTHER_FLAGS": 1}


@pytest.mark.parametrize("longitude", [True, "5.1", float("nan"), float("inf"), 10**1000])
def test_non_finite_or_non_numeric_coordinates_are_unusable(longitude: object) -> None:
    batch = import_sample(request(), GBIFClient(Provider([row(1, decimalLongitude=longitude)])))
    assert batch.receipt["quality"]["unusable_records"] == 1


def test_retry_exhaustion_is_finite_and_invalid_json_is_not_echoed() -> None:
    calls: list[str] = []
    waits: list[float] = []

    def unavailable(url: str, timeout: float) -> HTTPResult:
        calls.append(url)
        raise GBIFError("provider_unreachable")

    with pytest.raises(GBIFError, match="provider_unreachable"):
        GBIFClient(unavailable, sleep=waits.append).get("species/match")
    assert len(calls) == 3 and waits == [1.0, 2.0]
    for body in (b"PRIVATE_RESPONSE", b"[]", b"null"):
        with pytest.raises(GBIFError, match="^provider_json_invalid$"):
            import_sample(
                request(), GBIFClient(lambda url, timeout, body=body: HTTPResult(200, body))
            )


def test_a_date_flag_prevents_false_precision_and_extra_rights_block_the_dataset() -> None:
    batch = import_sample(
        request(), GBIFClient(Provider([row(1, issues=["RECORDED_DATE_MISMATCH"])]))
    )
    assert batch._rows[0]["event_date"] is None
    provider = Provider()
    provider.metadata["rights"] = "PRIVATE_RESTRICTION"
    with pytest.raises(GBIFError, match="dataset_rights_unverified"):
        import_sample(request(), GBIFClient(provider))


@pytest.mark.parametrize(
    "changes",
    [
        {"license": "https://creativecommons.org/licenses/by-nc/4.0/"},
        {"decimalLongitude": "5.125"},
        {"coordinateUncertaintyInMeters": 0},
        {"issues": ["COUNTRY_COORDINATE_MISMATCH"]},
        {"taxonKey": 999},
        {"informationWithheld": "PRIVATE_WITHHELD"},
        {"occurrenceStatus": "ABSENT"},
    ],
)
def test_restrictive_or_invalid_duplicate_keeps_its_identity(changes: dict[str, object]) -> None:
    batch = import_sample(request(), GBIFClient(Provider([row(1), row(1, **changes)])))
    assert batch._rows[0]["record_id"] == batch._rows[1]["record_id"]
    assert not admit_sample(batch, PrivacyPolicy()).records


@pytest.mark.parametrize(
    "change",
    [
        {"offset": False},
        {"offset": 20},
        {"limit": 300},
        {"results": []},
        {"results": ["PRIVATE"]},
        {"endOfRecords": "true"},
    ],
)
def test_invalid_pagination_never_produces_a_partial_batch(change: dict[str, object]) -> None:
    provider = Provider()
    provider.page_change = lambda page: page.update(change)
    with pytest.raises(GBIFError, match="pagination_invalid"):
        import_sample(request(), GBIFClient(provider))


def test_dataset_metadata_change_aborts_after_pages() -> None:
    provider = Provider()

    def mutate(page: dict[str, object]) -> None:
        provider.metadata["modified"] = "2026-01-04T00:00:00Z"

    provider.page_change = mutate
    with pytest.raises(GBIFError, match="dataset_changed"):
        import_sample(request(), GBIFClient(provider))


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_errors_are_retried_with_bounded_backoff(status: int) -> None:
    attempts = iter([HTTPResult(status, b"PRIVATE", "2"), HTTPResult(200, b"{}")])
    waits: list[float] = []
    client = GBIFClient(lambda url, timeout: next(attempts), sleep=waits.append)
    assert client.get("species/match") == b"{}" and waits == [2.0]


@pytest.mark.parametrize("status", [301, 401, 403, 404])
def test_permanent_errors_and_redirects_do_not_retry_or_echo_body(status: int) -> None:
    calls: list[str] = []

    def transport(url: str, timeout: float) -> HTTPResult:
        calls.append(url)
        return HTTPResult(status, b"PRIVATE_ERROR_SECRET")

    with pytest.raises(GBIFError, match="^provider_http_error$"):
        GBIFClient(transport).get("species/match")
    assert len(calls) == 1


def test_long_retry_after_timeout_and_response_limits_are_explicit() -> None:
    with pytest.raises(GBIFError, match="provider_backoff_required"):
        GBIFClient(lambda url, timeout: HTTPResult(429, b"", "60")).get("species/match")
    with pytest.raises(GBIFError, match="response_budget_exceeded"):
        GBIFClient(lambda url, timeout: HTTPResult(200, b"x" * (MAX_RESPONSE_BYTES + 1))).get(
            "species/match"
        )
    now = datetime(2026, 10, 30, tzinfo=UTC)
    assert _backoff("Fri, 30 Oct 2026 00:00:02 GMT", 0, now) == 2
    clock = iter([0.0, 181.0])
    with pytest.raises(GBIFError, match="request_budget_exceeded"):
        GBIFClient(monotonic=lambda: next(clock)).get("species/match")


@pytest.mark.parametrize(
    "changes",
    [
        {"page_size": 301},
        {"max_records": 1001},
        {"dataset_key": "PRIVATE_URL"},
        {"country": "../"},
        {"page_size": True},
        {"scientific_name": "PRIVATE\nINJECTED"},
        {"base_url": "https://example.invalid"},
    ],
)
def test_request_constraints(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**changes)


def test_cli_outputs_only_receipt_and_audit_after_a_complete_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "request.json"
    path.write_text(request().model_dump_json())
    monkeypatch.setattr(sys, "argv", ["gbif-job", "--request", str(path)])
    monkeypatch.setattr("mycoradar.gbif_job.GBIFClient", lambda: GBIFClient(Provider()))
    assert main() == 0
    captured = capsys.readouterr()
    assert captured.err == "" and "PRIVATE_" not in captured.out
    assert json.loads(captured.out)["admission"]["accepted"] == 0
    assert len(list(tmp_path.iterdir())) == 1


def test_cli_failure_after_a_page_does_not_emit_any_record_or_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "request.json"
    path.write_text(request().model_dump_json())
    provider = Provider()

    def fail(url: str, timeout: float) -> HTTPResult:
        if "offset=2" in url:
            return HTTPResult(403, b"PRIVATE_PROVIDER_ERROR")
        return provider(url, timeout)

    monkeypatch.setattr(sys, "argv", ["gbif-job", "--request", str(path)])
    monkeypatch.setattr("mycoradar.gbif_job.GBIFClient", lambda: GBIFClient(fail))
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.err == "" and json.loads(captured.out) == {
        "status": "unavailable",
        "error": "provider_http_error",
    }


def test_invalid_cli_arguments_are_not_echoed() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mycoradar.gbif_job", "--PRIVATE_SECRET"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert result.returncode == 2 and result.stderr == ""
    assert "PRIVATE_SECRET" not in result.stdout
