"""Private, offline quality audit; no cleaned records or publication capability are returned."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Never, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from mycoradar.occurrence_privacy import Identifier, SourceRule

MAX_BYTES = 8 * 1024 * 1024
Identity = tuple[str, str, str]


class QualityError(ValueError):
    """Fixed diagnostics only; never attach an input row or a filesystem error."""


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class AuditSource(SourceRule):
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Observation(Model):
    record_id: Identifier
    source_id: Identifier
    source_version: Identifier
    record_license: Annotated[str, Field(min_length=1, max_length=128)]
    occurrence_status: Literal["present"]
    taxon_id: Identifier
    taxon_match: Literal["exact_accepted", "synonym", "ambiguous", "unresolved"]
    country_code: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    coordinate_crs: Literal["EPSG:4326"]
    longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)] | None
    latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)] | None
    location_uncertainty_m: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)] | None
    generalized: StrictBool
    location_visibility: Literal["public", "private", "unknown"]
    sensitivity: Literal["public", "sensitive", "unknown"]
    event_start: date | None
    event_end: date | None

    @field_validator("event_start", "event_end", mode="before")
    @classmethod
    def calendar_date(cls, value: object) -> date | None:
        if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
            return value
        if isinstance(value, str) and len(value) == 10:
            return date.fromisoformat(value)
        raise ValueError("Explicit calendar date required")

    @model_validator(mode="after")
    def coherent_pairs(self) -> Self:
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("Incomplete coordinates")
        if (self.event_start is None) != (self.event_end is None):
            raise ValueError("Incomplete interval")
        if self.event_start and self.event_end and self.event_start > self.event_end:
            raise ValueError("Reversed interval")
        return self

    def __repr__(self) -> str:
        return "<private quality observation>"

    def __str__(self) -> str:
        return self.__repr__()


class Batch(Model):
    schema_version: Literal["occurrence-quality-v1"]
    capture_kind: Literal["synthetic", "operator_supplied"]
    captured_at: AwareDatetime
    observation_semantics: Literal["presence_only"]
    sources: Annotated[tuple[AuditSource, ...], Field(max_length=100)]
    records: Annotated[tuple[dict[str, Any], ...], Field(max_length=10_000)]

    @model_validator(mode="after")
    def coherent_sources(self) -> Self:
        if len({(source.id, source.version) for source in self.sources}) != len(self.sources):
            raise ValueError("Duplicate source version")
        if any(source.fetched_at > self.captured_at for source in self.sources):
            raise ValueError("Source collected after declared capture")
        return self


def identity(raw: dict[str, Any]) -> Identity | None:
    source, version, record = (raw.get(key) for key in ("source_id", "source_version", "record_id"))
    if (
        isinstance(source, str)
        and isinstance(version, str)
        and isinstance(record, str)
        and all(0 < len(value) <= 160 for value in (source, version, record))
    ):
        return source, version, record
    return None


def audit(batch: Batch) -> dict[str, Any]:
    groups: dict[Identity, list[Observation | None]] = defaultdict(list)
    invalid_rows = unidentified = 0
    for raw in batch.records:
        key = identity(raw)
        try:
            row = Observation.model_validate(raw)
        except ValidationError:
            row = None
            invalid_rows += 1
        if key is None:
            unidentified += 1
        else:
            groups[key].append(row)
    representatives = []
    invalid_groups = conflicts = rejected_rows = duplicate_rows = 0
    for rows in groups.values():
        valid = [row for row in rows if row is not None]
        if len(valid) != len(rows):
            invalid_groups += 1
            rejected_rows += len(rows)
        elif len({row.model_dump_json() for row in valid}) != 1:
            conflicts += 1
            rejected_rows += len(rows)
        else:
            representatives.append(valid[0])
            duplicate_rows += len(rows) - 1
    flags: Counter[str] = Counter()
    months: Counter[str] = Counter()
    uncertainty: Counter[str] = Counter()
    coincident: Counter[tuple[object, ...]] = Counter()
    sources = {(source.id, source.version): source for source in batch.sources}
    for row in representatives:
        source = sources.get((row.source_id, row.source_version))
        if source is None:
            flags["source_reference_unknown"] += 1
        elif row.record_license != source.license:
            flags["record_license_mismatch"] += 1
        if row.taxon_match != "exact_accepted":
            flags["taxon_mapping_not_exact_accepted"] += 1
        if row.location_visibility != "public":
            flags["location_not_public"] += 1
        if row.sensitivity != "public":
            flags["sensitivity_not_public"] += 1
        if row.longitude is None:
            flags["coordinates_unknown"] += 1
        if row.generalized:
            flags["generalized"] += 1
            if row.location_uncertainty_m is None:
                flags["generalized_uncertainty_unknown"] += 1
        distance = row.location_uncertainty_m
        bucket = (
            "unknown"
            if distance is None
            else "up_to_100_m"
            if distance <= 100
            else "over_100_to_1000_m"
            if distance <= 1000
            else "over_1000_m"
        )
        uncertainty[bucket] += 1
        if row.event_start is None:
            flags["event_date_unknown"] += 1
        elif row.event_end and row.event_end > batch.captured_at.astimezone(UTC).date():
            flags["event_after_declared_capture"] += 1
        elif row.event_start != row.event_end:
            flags["event_date_interval"] += 1
        else:
            months[f"{row.event_start.month:02d}"] += 1
            if row.longitude is not None and not row.generalized:
                coincident[(row.taxon_id, row.longitude, row.latitude, row.event_start)] += 1
    return {
        "schema_version": "occurrence-quality-report-v1",
        "status": "partial" if representatives else "unavailable",
        "report_visibility": "private",
        "capture_kind": batch.capture_kind,
        "captured_at": batch.captured_at.astimezone(UTC).isoformat(),
        "capture_time_basis": "operator_declared_not_verified",
        "source_checksums_verified": False,
        "source_publication_date_unknown_count": sum(
            source.source_published_at is None for source in batch.sources
        ),
        "taxon_mapping_basis": "operator_declared_not_verified",
        "country_location_check": "not_performed",
        "input_rows": len(batch.records),
        "invalid_rows": invalid_rows,
        "unidentified_rows": unidentified,
        "invalid_identity_groups": invalid_groups,
        "conflicting_identity_groups": conflicts,
        "rejected_identity_rows": rejected_rows,
        "identical_duplicate_rows": duplicate_rows,
        "representative_rows_for_audit_only": len(representatives),
        "quality_flags": dict(sorted(flags.items())),
        "uncertainty_buckets": {
            key: uncertainty[key]
            for key in ("unknown", "up_to_100_m", "over_100_to_1000_m", "over_1000_m")
        },
        "calendar_day_month_counts": {
            f"{month:02d}": months[f"{month:02d}"] for month in range(1, 13)
        },
        "coincident_event_candidate_groups": sum(count > 1 for count in coincident.values()),
        "coincident_event_candidate_rows": sum(count for count in coincident.values() if count > 1),
        "coincident_events_automatically_merged": False,
        "sampling_effort": "unknown",
        "spatial_bias_assessment": "not_performed",
        "absence_evidence": "unavailable",
        "scientific_admission": "not_performed",
        "publication_allowed": False,
        "records_emitted": 0,
    }


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise QualityError("invalid_input")
        result[key] = value
    return result


def reject_constant(value: str) -> Never:
    raise QualityError("invalid_input")


def read_audit(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise QualityError("input_budget_exceeded")
        value = json.loads(content, object_pairs_hook=unique_object, parse_constant=reject_constant)
        result = audit(Batch.model_validate(value))
        return {**result, "input_sha256": hashlib.sha256(content).hexdigest()}
    except QualityError:
        raise
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise QualityError("invalid_input") from exc


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise QualityError("invalid_arguments")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--input", type=Path, required=True)
        result = read_audit(parser.parse_args(argv).input)
        code = 0
    except QualityError as exc:
        allowed = {"invalid_input", "invalid_arguments", "input_budget_exceeded"}
        result = {
            "status": "unavailable",
            "error": str(exc) if str(exc) in allowed else "audit_failed",
            "publication_allowed": False,
        }
        code = 2
    print(json.dumps(result, allow_nan=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
