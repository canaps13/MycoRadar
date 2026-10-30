"""Fail-closed admission of normalized occurrences, before any public serialization.

No provider access, geocoding, rounding, storage of rejected records or HTTP routes.
The rule document is trusted operator configuration, never inferred from input rows.
"""

import hashlib
import hmac
import json
import logging
import secrets
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_RECORDS = 10_000
_PROOF = object()
_SEAL_KEY = secrets.token_bytes(32)  # Process-local capability seal; never stored or transmitted.
_LOGGER = logging.getLogger(__name__)
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")]
Country = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
License = Literal["CC0-1.0", "CC-BY-4.0", "Etalab-2.0"]
PositiveDistance = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]


class AdmissionError(Exception):
    """A fixed code only; never attach validation inputs, paths or raw exceptions."""


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class SourceRule(RuleModel):
    id: Identifier
    version: Identifier
    license: License
    attribution: Annotated[str, Field(min_length=1, max_length=2048)]
    citation_url: HttpUrl
    fetched_at: AwareDatetime
    source_published_at: AwareDatetime | None
    public_distribution_authorized: StrictBool = False
    minimum_uncertainty_m: PositiveDistance | None = None

    @model_validator(mode="after")
    def public_reference(self) -> Self:
        url = self.citation_url
        if url.scheme != "https" or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use a reviewed public HTTPS citation without query or credentials")
        if self.source_published_at and self.source_published_at > self.fetched_at:
            raise ValueError("Publication cannot be later than collection")
        return self


class TaxonRule(RuleModel):
    taxon_id: Identifier
    country_code: Country
    sensitivity: Literal["public", "sensitive", "unknown"] = "unknown"


class PrivacyPolicy(RuleModel):
    schema_version: Literal["occurrence-privacy-v1"] = "occurrence-privacy-v1"
    version: Identifier = "deny-by-default-v1"
    review_reference: HttpUrl | None = None
    reviewed_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    sources: tuple[SourceRule, ...] = ()
    taxa: tuple[TaxonRule, ...] = ()

    @model_validator(mode="after")
    def coherent_rules(self) -> Self:
        if len(self.sources) > 1000 or len(self.taxa) > 10_000:
            raise ValueError("Rule budget exceeded")
        if len({s.id for s in self.sources}) != len(self.sources):
            raise ValueError("Duplicate source rule")
        if len({(t.taxon_id, t.country_code) for t in self.taxa}) != len(self.taxa):
            raise ValueError("Duplicate taxon/country rule")
        if self.reviewed_at and self.expires_at and self.reviewed_at >= self.expires_at:
            raise ValueError("Invalid review interval")
        if self.review_reference:
            url = self.review_reference
            if url.scheme != "https" or url.username or url.password or url.query or url.fragment:
                raise ValueError("Review reference must be public, canonical HTTPS")
        return self

    def active(self, now: datetime) -> bool:
        return bool(
            self.review_reference
            and self.reviewed_at
            and self.expires_at
            and self.reviewed_at <= now < self.expires_at
        )

    def fingerprint(self) -> str:
        # Private implementation detail: never include the rules for rejected taxa in a payload.
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class _Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    record_id: Annotated[str, Field(min_length=1, max_length=1024)]
    source_id: Identifier
    source_version: Identifier
    record_license: str
    taxon_id: Identifier
    country_code: Country
    location_visibility: Literal["public", "private", "unknown"] = "unknown"
    sensitivity: Literal["public", "sensitive", "unknown"] = "unknown"
    reviewed_for_release: StrictBool = False
    coordinate_crs: Literal["EPSG:4326"]
    longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)]
    latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)]
    location_uncertainty_m: PositiveDistance | None
    generalized: StrictBool
    event_date: date | None = None
    informationWithheld: Annotated[str, Field(max_length=4096)] = ""
    dataGeneralizations: Annotated[str, Field(max_length=4096)] = ""

    @field_validator("event_date", mode="before")
    @classmethod
    def date_only(cls, value: object) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, str) and len(value) == 10:
            return date.fromisoformat(value)
        raise ValueError("An explicit calendar date is required")

    def __repr__(self) -> str:
        return "<restricted occurrence candidate>"

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class PublicOccurrence:
    id: str
    source_id: str
    taxon_id: str
    country_code: str
    longitude: float
    latitude: float
    location_uncertainty_m: float | None
    generalized: bool
    event_date: date | None


@dataclass(frozen=True)
class PublicPublication:
    """Ephemeral capability, not a durable cache or a raw-record container."""

    records: tuple[PublicOccurrence, ...]
    sources: tuple[SourceRule, ...]
    policy_version: str
    expires_at: datetime | None
    processed: int
    excluded: tuple[tuple[str, int], ...]
    _policy_fingerprint: str = field(repr=False)
    _proof: object = field(repr=False)
    _seal: str = field(default="", repr=False)


def _seal(publication: PublicPublication) -> str:
    content = {
        "records": [asdict(record) for record in publication.records],
        "sources": [source.model_dump(mode="json") for source in publication.sources],
        "policy_version": publication.policy_version,
        "expires_at": publication.expires_at,
        "policy_fingerprint": publication._policy_fingerprint,
        "processed": publication.processed,
        "excluded": publication.excluded,
    }
    serialized = json.dumps(content, sort_keys=True, default=str).encode()
    return hmac.new(_SEAL_KEY, serialized, hashlib.sha256).hexdigest()


def _identity(raw: Mapping[str, object]) -> str | None:
    values = [raw.get(key) for key in ("source_id", "source_version", "record_id")]
    if not all(isinstance(value, str) and 0 < len(value) <= 1024 for value in values):
        return None
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()


def _reason(record: _Candidate, source: SourceRule | None, taxon: TaxonRule | None) -> str | None:
    if record.location_visibility != "public" or not record.reviewed_for_release:
        return "location_not_authorized"
    if record.sensitivity != "public" or taxon is None or taxon.sensitivity != "public":
        return "taxon_not_authorized"
    if source is None or not source.public_distribution_authorized:
        return "source_not_authorized"
    if record.source_version != source.version or record.record_license != source.license:
        return "source_rights_mismatch"
    if record.informationWithheld.strip():
        return "provider_withheld"
    if record.dataGeneralizations.strip() and not record.generalized:
        return "generalization_inconsistent"
    distance = record.location_uncertainty_m
    if record.generalized and distance is None:
        return "generalization_uncertainty_unknown"
    minimum = source.minimum_uncertainty_m
    if minimum is not None and (distance is None or distance < minimum):
        return "location_too_precise"
    return None


def admit_occurrences(
    records: Iterable[Mapping[str, object]],
    policy: PrivacyPolicy,
    *,
    now: datetime | None = None,
) -> PublicPublication:
    """Normalized inputs only; conflicting/restricted duplicates suppress the whole identity."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise AdmissionError("invalid_clock")
    active = policy.active(instant)
    sources = {s.id: s for s in policy.sources}
    taxa = {(t.taxon_id, t.country_code): t for t in policy.taxa}
    approved: dict[str, PublicOccurrence | None] = {}
    reasons: Counter[str] = Counter()
    processed = 0
    for raw in records:
        processed += 1
        if processed > MAX_RECORDS:
            raise AdmissionError("record_budget_exceeded")
        identity = _identity(raw)
        public = None
        reason: str | None
        if not active:
            reason = "policy_unavailable"
        else:
            try:
                record = _Candidate.model_validate(raw)
                reason = _reason(
                    record,
                    sources.get(record.source_id),
                    taxa.get((record.taxon_id, record.country_code)),
                )
                if reason is None and identity:
                    public = PublicOccurrence(
                        id=identity,
                        source_id=record.source_id,
                        taxon_id=record.taxon_id,
                        country_code=record.country_code,
                        longitude=record.longitude,
                        latitude=record.latitude,
                        location_uncertainty_m=record.location_uncertainty_m,
                        generalized=record.generalized,
                        event_date=record.event_date,
                    )
            except ValidationError:
                reason = "invalid_record"
        if reason:
            reasons[reason] += 1
        if identity:
            if identity in approved:
                previous = approved[identity]
                if previous != public or previous is None:
                    approved[identity] = None
                    reasons["conflicting_identity"] += 1
                else:
                    reasons["duplicate_identity"] += 1
            else:
                approved[identity] = public
    released = tuple(sorted((r for r in approved.values() if r is not None), key=lambda r: r.id))
    used_sources = {r.source_id for r in released}
    publication = PublicPublication(
        records=released,
        sources=tuple(s for s in policy.sources if s.id in used_sources),
        policy_version=policy.version,
        expires_at=policy.expires_at,
        processed=processed,
        excluded=tuple(sorted(reasons.items())),
        _policy_fingerprint=policy.fingerprint(),
        _proof=_PROOF,
    )
    publication = replace(publication, _seal=_seal(publication))
    _LOGGER.info(
        "occurrence_admission processed=%d accepted=%d excluded=%d",
        processed,
        len(released),
        processed - len(released),
    )
    return publication


def check_publication(
    publication: PublicPublication,
    policy: PrivacyPolicy,
    *,
    now: datetime | None = None,
    audit_only: bool = False,
) -> None:
    """Recheck at every sink/cache read, including revocation with an unchanged version label."""
    if not isinstance(publication, PublicPublication) or publication._proof is not _PROOF:
        raise AdmissionError("admission_required")
    try:
        intact = hmac.compare_digest(publication._seal, _seal(publication))
    except (TypeError, ValueError, AttributeError):
        intact = False
    if not intact:
        raise AdmissionError("admission_required")
    if publication._policy_fingerprint != policy.fingerprint():
        raise AdmissionError("policy_changed")
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise AdmissionError("invalid_clock")
    if not audit_only and not policy.active(instant):
        raise AdmissionError("policy_unavailable")
