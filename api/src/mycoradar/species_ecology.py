"""Offline candidate names and bibliographic host evidence, never ecological scoring."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import parse_qs, urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    model_validator,
)

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9:-]{0,79}$")]
Binomial = Annotated[str, Field(pattern=r"^[A-Z][a-z]+ [a-z][a-z-]+$")]
UsageKey = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,15}$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
MAX_MANIFEST = 512 * 1024
MAX_RESPONSE = 128 * 1024


def explicit_time(value: object) -> str:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Explicit ISO datetime required")
    return value


Timestamp = Annotated[AwareDatetime, BeforeValidator(explicit_time)]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, allow_inf_nan=False
    )


class FileRef(Contract):
    path: Annotated[str, Field(min_length=1, max_length=256)]
    sha256: Digest
    url: HttpUrl
    fetched_at: Timestamp


class Reference(Contract):
    dataset_key: Literal["d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"]
    scope: Literal["gbif_backbone_legacy"]
    license: Literal["CC-BY-4.0"]
    license_url: HttpUrl
    citation: Text
    registry_published_at: Timestamp
    registry_modified_at: Timestamp
    reviewed_at: Timestamp
    matching_service_build_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    index_clb_dataset_key: Annotated[str, Field(pattern=r"^[0-9]+$")]
    index_before_after_equal: Literal[True]
    snapshot_atomic: Literal[False]

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if max(self.registry_published_at, self.registry_modified_at) > self.reviewed_at:
            raise ValueError("Registry dates cannot postdate review")
        return self


class Evidence(Contract):
    id: Identifier
    citation: Text
    url: HttpUrl
    published_year: Annotated[int, Field(strict=True, ge=1, le=9999)]
    consulted_at: Timestamp
    access_basis: Literal["full_text", "abstract"]
    text_license: Literal["CC-BY-4.0", "CC-BY-3.0-NL", "unknown_copyright"]
    document_body_included: Literal[False]
    training_use: Literal["not_admitted"]

    @model_validator(mode="after")
    def publication_known(self) -> Self:
        if self.published_year > self.consulted_at.year:
            raise ValueError("Publication year cannot postdate consultation")
        return self


class Association(Contract):
    host_name: Annotated[str, Field(pattern=r"^[A-Z][a-z]+(?: [a-z][a-z-]+)?$")]
    host_rank: Literal["genus", "species"]
    vegetation_form: Literal["tree", "shrub"]
    evidence_kind: Literal["experimental_synthesis", "field_study_context"]
    source_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=10)]
    source_locator: Text
    concept_alignment: Literal["not_verified"]
    transfer_to_pilot: Literal["unvalidated"]
    exhaustive_host_list: Literal[False]

    @model_validator(mode="after")
    def explicit_rank(self) -> Self:
        if (" " in self.host_name) != (self.host_rank == "species"):
            raise ValueError("Host name and rank disagree")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("Duplicate evidence reference")
        return self


class Threshold(Contract):
    variable: Literal["soil_ph", "elevation_m"]
    unit: Literal["pH", "m"]
    lower: Number | None
    upper: Number | None
    source_ids: tuple[Identifier, ...]
    scoring_enabled: Literal[False]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.unit != {"soil_ph": "pH", "elevation_m": "m"}[self.variable]:
            raise ValueError("Threshold unit mismatch")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("Reversed threshold")
        if (self.lower is not None or self.upper is not None) and not self.source_ids:
            raise ValueError("Configured hypothesis needs evidence")
        return self


class Candidate(Contract):
    id: Identifier
    canonical_name: Binomial
    usage_key: UsageKey
    match: FileRef
    usage: FileRef
    associations: Annotated[tuple[Association, ...], Field(min_length=1, max_length=30)]
    thresholds: Annotated[tuple[Threshold, ...], Field(max_length=10)]
    concept_review_source_ids: tuple[Identifier, ...]
    name_concept: Literal["name_in_reference_not_verified_against_study_material"]
    pilot_admission: Literal["not_admitted"]

    @model_validator(mode="after")
    def unique_settings(self) -> Self:
        if len({t.variable for t in self.thresholds}) != len(self.thresholds):
            raise ValueError("Duplicate threshold variable")
        if len({(a.host_name, a.evidence_kind) for a in self.associations}) != len(
            self.associations
        ):
            raise ValueError("Duplicate association; combine evidence references")
        return self


class Manifest(Contract):
    schema_version: Literal["species-ecology-v1"]
    content_kind: Literal["real_bibliographic_catalog", "synthetic"]
    reference: Reference
    evidence: Annotated[tuple[Evidence, ...], Field(min_length=1, max_length=100)]
    candidates: Annotated[tuple[Candidate, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def references_known(self) -> Self:
        source_ids = {source.id for source in self.evidence}
        if len(source_ids) != len(self.evidence):
            raise ValueError("Duplicate bibliography ID")
        for field in ("id", "canonical_name", "usage_key"):
            if len({getattr(c, field) for c in self.candidates}) != len(self.candidates):
                raise ValueError("Duplicate candidate")
        for candidate in self.candidates:
            references = [a.source_ids for a in candidate.associations]
            references += [t.source_ids for t in candidate.thresholds]
            references.append(candidate.concept_review_source_ids)
            for ids in references:
                if not set(ids) <= source_ids:
                    raise ValueError("Unknown evidence reference")
            if (
                max(candidate.match.fetched_at, candidate.usage.fetched_at)
                > self.reference.reviewed_at
            ):
                raise ValueError("Review cannot predate capture")
        return self


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON key")
        result[key] = value
    return result


def _read(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise ValueError("Ordinary file required")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("File budget exceeded")
    return raw


def _response(ref: FileRef, root: Path) -> dict[str, Any]:
    if Path(ref.path).is_absolute():
        raise ValueError("Relative source path required")
    path = (root / ref.path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Referenced file outside manifest directory")
    raw = _read(path, MAX_RESPONSE)
    if hashlib.sha256(raw).hexdigest() != ref.sha256:
        raise ValueError("Source checksum mismatch")
    value = json.loads(raw, object_pairs_hook=_unique_keys)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _verified_name(candidate: Candidate, reference: Reference, root: Path) -> None:
    expected_query = {
        "scientificName": [candidate.canonical_name],
        "kingdom": ["Fungi"],
        "rank": ["SPECIES"],
    }
    for ref in (candidate.match, candidate.usage):
        url = urlsplit(str(ref.url))
        if (url.scheme, url.hostname, url.port, url.username, url.password, url.fragment) != (
            "https",
            "api.gbif.org",
            None,
            None,
            None,
            "",
        ):
            raise ValueError("GBIF HTTPS source URL required")
    match_url = urlsplit(str(candidate.match.url))
    usage_url = urlsplit(str(candidate.usage.url))
    if (
        match_url.path != "/v2/species/match"
        or parse_qs(match_url.query, keep_blank_values=True) != expected_query
    ):
        raise ValueError("Mismatch between query and candidate")
    if usage_url.path != f"/v1/species/{candidate.usage_key}" or usage_url.query:
        raise ValueError("Mismatch between usage URL and key")
    match = _response(candidate.match, root)
    usage = _response(candidate.usage, root)
    kingdoms = [c.get("name") for c in match["classification"] if c.get("rank") == "KINGDOM"]
    species = [c for c in match["classification"] if c.get("rank") == "SPECIES"]
    if (
        match.get("synonym") is not False
        or match["diagnostics"]["matchType"] != "EXACT"
        or match["usage"]["key"] != candidate.usage_key
        or match["usage"]["canonicalName"] != candidate.canonical_name
        or match["usage"]["rank"] != "SPECIES"
        or match["usage"]["status"] != "ACCEPTED"
        or kingdoms != ["Fungi"]
        or len(species) != 1
        or species[0].get("key") != candidate.usage_key
        or species[0].get("name") != candidate.canonical_name
        or type(usage["key"]) is not int
        or str(usage["key"]) != candidate.usage_key
        or usage["datasetKey"] != reference.dataset_key
        or usage["canonicalName"] != candidate.canonical_name
        or usage["taxonomicStatus"] != "ACCEPTED"
        or usage["rank"] != "SPECIES"
        or usage["kingdom"] != "Fungi"
    ):
        raise ValueError("Unverified name usage; no synonym or fuzzy fallback")


def load_catalog(path: Path) -> tuple[Manifest, str]:
    raw = _read(path, MAX_MANIFEST)
    manifest = Manifest.model_validate(json.loads(raw, object_pairs_hook=_unique_keys))
    for candidate in manifest.candidates:
        _verified_name(candidate, manifest.reference, path.parent)
    return manifest, hashlib.sha256(raw).hexdigest()


def receipt(manifest: Manifest, digest: str) -> dict[str, object]:
    return {
        "schema_version": "species-ecology-receipt-v1",
        "catalog_sha256": digest,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "status": "partial",
        "content_kind": manifest.content_kind,
        "taxonomic_reference": manifest.reference.scope,
        "candidates": [
            {
                "id": c.id,
                "canonical_name": c.canonical_name,
                "reference_usage_key": c.usage_key,
                "name_match": "exact_accepted_species",
                "association_count": len(c.associations),
                "configured_thresholds": sum(
                    t.lower is not None or t.upper is not None for t in c.thresholds
                ),
                "pilot_admission": c.pilot_admission,
                "effective_resolution_m": None,
                "habitat_score": None,
                "fruiting_score": None,
            }
            for c in manifest.candidates
        ],
        "source_count": len(manifest.evidence),
        "publication_allowed": False,
        "scientific_validation": "not_performed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest, digest = load_catalog(args.manifest)
        report = receipt(manifest, digest)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError, RecursionError):
        print('{"error":"species_catalog_invalid"}')
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
