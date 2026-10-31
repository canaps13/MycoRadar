"""All records, locations, classifications and sources below are SYNTHETIC fixtures."""

import copy
import io
import json
import logging
import re
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mycoradar.occurrence_outputs import (
    api_payload,
    audit_payload,
    export_zip,
    public_paths,
    tile_geojson,
)
from mycoradar.occurrence_privacy import (
    AdmissionError,
    PrivacyPolicy,
    SourceRule,
    TaxonRule,
    admit_occurrences,
)
from pydantic import ValidationError

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
SENTINEL = "PRIVATE-SYNTHETIC-SENTINEL"
PRIVATE_LONGITUDE = 12.345678901
PRIVATE_LATITUDE = 45.678901234
SINKS = (api_payload, tile_geojson, export_zip, public_paths, audit_payload)


def policy(now: datetime = NOW) -> PrivacyPolicy:
    return PrivacyPolicy(
        version="synthetic-policy-v1",
        review_reference="https://example.invalid/synthetic-review",
        reviewed_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        sources=(
            SourceRule(
                id="synthetic-source",
                version="synthetic-v1",
                license="CC0-1.0",
                attribution="Synthetic test data, no real source admitted",
                citation_url="https://example.invalid/synthetic-source",
                fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
                source_published_at=None,
                public_distribution_authorized=True,
                minimum_uncertainty_m=1000,
            ),
        ),
        taxa=(
            TaxonRule(taxon_id="synthetic-public", country_code="FR", sensitivity="public"),
            TaxonRule(taxon_id="synthetic-sensitive", country_code="FR", sensitivity="sensitive"),
            TaxonRule(taxon_id="synthetic-public", country_code="ES", sensitivity="sensitive"),
        ),
    )


def candidate(**updates: object) -> dict[str, Any]:
    row = {
        "record_id": "synthetic-record",
        "source_id": "synthetic-source",
        "source_version": "synthetic-v1",
        "record_license": "CC0-1.0",
        "taxon_id": "synthetic-public",
        "country_code": "FR",
        "location_visibility": "public",
        "sensitivity": "public",
        "reviewed_for_release": True,
        "coordinate_crs": "EPSG:4326",
        "longitude": 6.2,
        "latitude": 43.4,
        "location_uncertainty_m": 1500,
        "generalized": True,
        "event_date": "2020-01-02",
        "dataGeneralizations": "Rounded by the synthetic source, no real observation",
    }
    row.update(updates)
    return row


def decoded_artifact(value: object) -> str:
    if isinstance(value, bytes):
        with zipfile.ZipFile(io.BytesIO(value)) as archive:
            assert set(archive.namelist()) == {"occurrences.csv", "metadata.json"}
            return "\n".join(archive.read(name).decode() for name in archive.namelist())
    return json.dumps(value, sort_keys=True)


def test_positive_public_generalized_point_is_preserved_on_every_surface() -> None:
    rules = policy()
    publication = admit_occurrences([candidate()], rules, now=NOW)
    assert len(publication.records) == 1
    public = publication.records[0]
    assert (public.longitude, public.latitude, public.location_uncertainty_m) == (6.2, 43.4, 1500)
    assert public.generalized is True
    assert re.fullmatch(r"[a-f0-9]{64}", public.id)
    for sink in SINKS:
        output = decoded_artifact(sink(publication, rules, now=NOW))
        assert "synthetic-record" not in output  # Original record identifiers are never exported.
    api = api_payload(publication, rules, now=NOW)
    assert api["status"] == "partial"
    assert "effective_resolution_m" not in api["items"][0]
    assert api["sources"][0]["license_url"].endswith("/zero/1.0/")
    assert "original" not in decoded_artifact(tile_geojson(publication, rules, now=NOW))


@pytest.mark.parametrize(
    "updates",
    [
        {"location_visibility": "private"},
        {"location_visibility": "unknown"},
        {"reviewed_for_release": False},
        {"reviewed_for_release": "true"},
        {"taxon_id": "synthetic-sensitive"},
        {"taxon_id": "unclassified"},
        {"sensitivity": "sensitive"},
        {"sensitivity": "unknown"},
        {"country_code": "ES"},
        {"country_code": "US"},
        {"source_id": "unclassified-source"},
        {"source_version": "older-v0"},
        {"record_license": "CC-BY-NC-4.0"},
        {"record_license": "unknown"},
        {"informationWithheld": SENTINEL},
        {"generalized": False},
        {"location_uncertainty_m": None},
        {"location_uncertainty_m": 100},
        {"location_uncertainty_m": 0},
        {"location_uncertainty_m": -1},
        {"location_uncertainty_m": float("nan")},
        {"longitude": 181},
        {"latitude": 91},
        {"longitude": float("inf")},
        {"coordinate_crs": "EPSG:3857"},
        {"event_date": 0},
        {"event_date": "private-date"},
        {"event_date": "2020-02-30"},
        {"event_date": "2020-01-02T12:00:00Z"},
        {"unmapped_privacy_flag": SENTINEL},
    ],
)
@pytest.mark.parametrize("sink", SINKS, ids=["api", "tiles", "export", "urls", "audit"])
def test_private_sensitive_unknown_or_inconsistent_data_never_reaches_any_sink(
    updates: dict[str, object], sink: Any, caplog: pytest.LogCaptureFixture
) -> None:
    raw = candidate(record_id=SENTINEL, longitude=PRIVATE_LONGITUDE, latitude=PRIVATE_LATITUDE)
    raw.update(updates)
    rules = policy()
    with caplog.at_level(logging.INFO):
        publication = admit_occurrences([raw], rules, now=NOW)
        output = decoded_artifact(sink(publication, rules, now=NOW))
    assert publication.records == ()
    for forbidden in (
        SENTINEL,
        str(PRIVATE_LONGITUDE),
        str(PRIVATE_LATITUDE),
        "synthetic-sensitive",
    ):
        assert forbidden not in output and forbidden not in caplog.text
        assert forbidden not in repr(publication)
    assert publication.sources == ()  # No metadata discloses the rejected source membership.


@pytest.mark.parametrize(
    "field",
    [
        "location_visibility",
        "sensitivity",
        "reviewed_for_release",
        "generalized",
        "location_uncertainty_m",
        "coordinate_crs",
        "record_license",
    ],
)
def test_missing_release_or_precision_information_is_denied(field: str) -> None:
    raw = candidate()
    del raw[field]
    assert not admit_occurrences([raw], policy(), now=NOW).records


def test_free_text_does_not_reconstruct_the_original_location() -> None:
    raw = candidate(
        dataGeneralizations=f"{SENTINEL} original {PRIVATE_LONGITUDE},{PRIVATE_LATITUDE}"
    )
    rules = policy()
    publication = admit_occurrences([raw], rules, now=NOW)
    assert len(publication.records) == 1
    for sink in SINKS:
        artifact = decoded_artifact(sink(publication, rules, now=NOW))
        assert SENTINEL not in artifact and str(PRIVATE_LONGITUDE) not in artifact
    assert api_payload(publication, rules, now=NOW)["items"][0]["longitude"] == 6.2
    assert raw["dataGeneralizations"].startswith(SENTINEL)  # No mutation of private input.


def test_unknown_uncertainty_stays_unknown_when_explicitly_allowed() -> None:
    rules = policy()
    source = rules.sources[0].model_copy(update={"minimum_uncertainty_m": None})
    rules = rules.model_copy(update={"sources": (source,)})
    raw = candidate(generalized=False, dataGeneralizations="", location_uncertainty_m=None)
    publication = admit_occurrences([raw], rules, now=NOW)
    assert api_payload(publication, rules, now=NOW)["items"][0]["location_uncertainty_m"] is None


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "private_update",
    [
        {"location_visibility": "private"},
        {"longitude": 181},
        {"longitude": 6.21},
        {"location_uncertainty_m": 1700},
    ],
)
def test_restrictive_or_conflicting_duplicates_suppress_the_whole_identity(
    reverse: bool, private_update: dict[str, object]
) -> None:
    records = [candidate(), candidate(**private_update)]
    if reverse:
        records.reverse()
    assert not admit_occurrences(records, policy(), now=NOW).records


def test_identical_duplicates_collapse_and_replays_are_deterministic() -> None:
    raw = candidate()
    original = copy.deepcopy(raw)
    rules = policy()
    one = admit_occurrences([raw, raw], rules, now=NOW)
    two = admit_occurrences([raw, raw], rules, now=NOW)
    assert len(one.records) == 1 and raw == original
    assert export_zip(one, rules, now=NOW) == export_zip(two, rules, now=NOW)


@pytest.mark.parametrize("sink", SINKS[:-1], ids=["api", "tiles", "export", "urls"])
def test_unreviewed_default_and_expired_policies_never_publish(sink: Any) -> None:
    default = PrivacyPolicy()
    publication = admit_occurrences([candidate()], default, now=NOW)
    assert not publication.records
    with pytest.raises(AdmissionError, match="policy_unavailable"):
        sink(publication, default, now=NOW)
    rules = policy()
    publication = admit_occurrences([candidate()], rules, now=NOW)
    with pytest.raises(AdmissionError, match="policy_unavailable"):
        sink(publication, rules, now=rules.expires_at)
    assert audit_payload(publication, rules, now=rules.expires_at)["accepted"] == 1


@pytest.mark.parametrize("sink", SINKS, ids=["api", "tiles", "export", "urls", "audit"])
def test_cached_publication_is_refused_after_revocation_even_without_version_bump(
    sink: Any,
) -> None:
    rules = policy()
    publication = admit_occurrences([candidate()], rules, now=NOW)
    revoked = rules.model_copy(update={"taxa": ()})
    assert revoked.version == rules.version
    with pytest.raises(AdmissionError, match="policy_changed"):
        sink(publication, revoked, now=NOW)


@pytest.mark.parametrize("sink", SINKS, ids=["api", "tiles", "export", "urls", "audit"])
def test_every_sink_refuses_raw_or_forged_capabilities(sink: Any) -> None:
    rules = policy()
    with pytest.raises(AdmissionError, match="admission_required"):
        sink(candidate(record_id=SENTINEL), rules, now=NOW)
    good = admit_occurrences([candidate()], rules, now=NOW)
    forged = replace(good, _proof=object())
    with pytest.raises(AdmissionError, match="admission_required"):
        sink(forged, rules, now=NOW)
    changed = replace(good, records=(replace(good.records[0], longitude=PRIVATE_LONGITUDE),))
    with pytest.raises(AdmissionError, match="admission_required"):
        sink(changed, rules, now=NOW)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/dataset",
        "https://private:secret@example.invalid/dataset",
        f"https://example.invalid/?coordinates={PRIVATE_LONGITUDE}",
        f"https://example.invalid/#{SENTINEL}",
    ],
)
def test_source_citation_cannot_transport_credentials_or_coordinate_queries(url: str) -> None:
    data = policy().sources[0].model_dump()
    data["citation_url"] = url
    with pytest.raises(ValidationError):
        SourceRule.model_validate(data)


def test_source_authorization_is_required_independently_of_record_flags() -> None:
    rules = policy()
    source = rules.sources[0].model_copy(update={"public_distribution_authorized": False})
    rules = rules.model_copy(update={"sources": (source,)})
    assert not admit_occurrences([candidate()], rules, now=NOW).records


def test_no_partial_publication_when_the_input_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("mycoradar.occurrence_privacy.MAX_RECORDS", 1)
    with pytest.raises(AdmissionError, match="record_budget_exceeded"):
        admit_occurrences([candidate(), candidate(record_id=SENTINEL)], policy(), now=NOW)


def test_real_http_response_uses_the_checked_api_projection() -> None:
    application = FastAPI()
    rules = policy()
    raw = [
        candidate(),
        candidate(
            record_id=SENTINEL,
            location_visibility="private",
            longitude=PRIVATE_LONGITUDE,
            latitude=PRIVATE_LATITUDE,
        ),
    ]

    @application.get("/test-public-occurrences")
    def endpoint() -> dict[str, object]:
        return api_payload(admit_occurrences(raw, rules, now=NOW), rules, now=NOW)

    response = TestClient(application).get("/test-public-occurrences")
    assert response.status_code == 200 and len(response.json()["items"]) == 1
    assert SENTINEL not in response.text and str(PRIVATE_LONGITUDE) not in response.text
