"""Privacy rule boundaries; every configuration and row is synthetic."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mycoradar.occurrence_privacy import PrivacyPolicy, SourceRule, TaxonRule, admit_occurrences
from pydantic import ValidationError


def test_no_rule_document_is_an_active_default() -> None:
    assert not PrivacyPolicy().active(datetime.now(UTC))


def test_shipped_configuration_denies_every_source_and_taxon() -> None:
    path = Path(__file__).resolve().parents[2] / "data/privacy/deny-by-default.json"
    rules = PrivacyPolicy.model_validate_json(path.read_bytes())
    assert rules == PrivacyPolicy() and not rules.active(datetime.now(UTC))


@pytest.mark.parametrize("field", ["review_reference", "reviewed_at", "expires_at"])
def test_missing_policy_review_fields_are_not_active(field: str) -> None:
    instant = datetime(2026, 10, 30, tzinfo=UTC)
    data = {
        "review_reference": "https://example.invalid/synthetic-review",
        "reviewed_at": instant - timedelta(days=1),
        "expires_at": instant + timedelta(days=1),
    }
    data.pop(field)
    assert not PrivacyPolicy.model_validate(data).active(instant)


@pytest.mark.parametrize("before_review", [False, True])
def test_policy_interval_boundaries(before_review: bool) -> None:
    instant = datetime(2026, 10, 30, tzinfo=UTC)
    rules = PrivacyPolicy(
        review_reference="https://example.invalid/synthetic-review",
        reviewed_at=instant,
        expires_at=instant + timedelta(days=1),
    )
    assert rules.active(instant)
    outside = instant - timedelta(microseconds=1) if before_review else rules.expires_at
    assert not rules.active(outside)


@pytest.mark.parametrize("license_id", ["CC-BY-NC-4.0", "unknown", "CC-BY-3.0"])
def test_source_license_requires_explicit_supported_admission(license_id: str) -> None:
    with pytest.raises(ValidationError):
        SourceRule.model_validate(
            {
                "id": "synthetic",
                "version": "v1",
                "license": license_id,
                "attribution": "Synthetic fixture",
                "citation_url": "https://example.invalid/source",
                "fetched_at": "2026-10-20T00:00:00Z",
                "source_published_at": None,
            }
        )


def test_source_and_country_taxon_rules_cannot_be_ambiguous() -> None:
    rule = TaxonRule(taxon_id="synthetic", country_code="FR", sensitivity="public")
    with pytest.raises(ValidationError):
        PrivacyPolicy(taxa=(rule, rule))


def test_empty_input_is_not_inferred_presence_or_absence() -> None:
    result = admit_occurrences([], PrivacyPolicy())
    assert result.records == () and result.processed == 0
