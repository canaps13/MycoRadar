"""Synthetic taxonomy/evidence contracts; the real curated bundle is tested separately."""

import hashlib
import json
import shutil
import socket
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from mycoradar.species_ecology import MAX_MANIFEST, MAX_RESPONSE, load_catalog, main, receipt


def write_json(path: Path, value: object) -> str:
    raw = (json.dumps(value, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def definition(tmp_path: Path) -> dict[str, Any]:
    match = {
        "usage": {
            "key": "123",
            "canonicalName": "Testus inventus",
            "rank": "SPECIES",
            "status": "ACCEPTED",
        },
        "diagnostics": {"matchType": "EXACT", "confidence": 99},
        "synonym": False,
        "classification": [
            {"rank": "KINGDOM", "name": "Fungi", "key": "5"},
            {"rank": "SPECIES", "name": "Testus inventus", "key": "123"},
        ],
    }
    usage = {
        "key": 123,
        "datasetKey": "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c",
        "canonicalName": "Testus inventus",
        "rank": "SPECIES",
        "taxonomicStatus": "ACCEPTED",
        "kingdom": "Fungi",
    }
    return {
        "schema_version": "species-ecology-v1",
        "content_kind": "synthetic",
        "reference": {
            "dataset_key": usage["datasetKey"],
            "scope": "gbif_backbone_legacy",
            "license": "CC-BY-4.0",
            "license_url": "https://example.invalid/license",
            "citation": "Invented reference fixture, not a real taxonomic assertion",
            "registry_published_at": "2020-01-01T00:00:00Z",
            "registry_modified_at": "2020-01-01T00:00:00Z",
            "reviewed_at": "2020-01-04T00:00:00Z",
            "matching_service_build_sha": "a" * 40,
            "index_clb_dataset_key": "123",
            "index_before_after_equal": True,
            "snapshot_atomic": False,
        },
        "evidence": [
            {
                "id": "test-paper",
                "citation": "Synthetic paper, never published",
                "url": "https://example.invalid/paper",
                "published_year": 2019,
                "consulted_at": "2020-01-03T00:00:00Z",
                "access_basis": "abstract",
                "text_license": "unknown_copyright",
                "document_body_included": False,
                "training_use": "not_admitted",
            }
        ],
        "candidates": [
            {
                "id": "candidate:testus",
                "canonical_name": "Testus inventus",
                "usage_key": "123",
                "match": {
                    "path": "match.json",
                    "sha256": write_json(tmp_path / "match.json", match),
                    "url": "https://api.gbif.org/v2/species/match?scientificName=Testus%20inventus&kingdom=Fungi&rank=SPECIES",
                    "fetched_at": "2020-01-02T00:00:00Z",
                },
                "usage": {
                    "path": "usage.json",
                    "sha256": write_json(tmp_path / "usage.json", usage),
                    "url": "https://api.gbif.org/v1/species/123",
                    "fetched_at": "2020-01-02T00:00:00Z",
                },
                "associations": [
                    {
                        "host_name": "Testus",
                        "host_rank": "genus",
                        "vegetation_form": "shrub",
                        "evidence_kind": "experimental_synthesis",
                        "source_ids": ["test-paper"],
                        "source_locator": "Invented abstract",
                        "concept_alignment": "not_verified",
                        "transfer_to_pilot": "unvalidated",
                        "exhaustive_host_list": False,
                    }
                ],
                "thresholds": [
                    {
                        "variable": "soil_ph",
                        "unit": "pH",
                        "lower": None,
                        "upper": None,
                        "source_ids": [],
                        "scoring_enabled": False,
                    }
                ],
                "concept_review_source_ids": [],
                "name_concept": "name_in_reference_not_verified_against_study_material",
                "pilot_admission": "not_admitted",
            }
        ],
    }


def run(tmp_path: Path, definition: dict[str, Any]) -> dict[str, Any]:
    path = tmp_path / "catalog.json"
    write_json(path, definition)
    catalog, digest = load_catalog(path)
    return receipt(catalog, digest)


def test_candidate_names_and_host_facts_never_activate_scoring(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    report = run(tmp_path, definition)
    assert report["status"] == "partial"
    assert report["content_kind"] == "synthetic"
    assert report["publication_allowed"] is False
    assert report["scientific_validation"] == "not_performed"
    candidate = report["candidates"][0]
    assert candidate["canonical_name"] == "Testus inventus"
    assert candidate["reference_usage_key"] == "123"
    assert candidate["name_match"] == "exact_accepted_species"
    assert candidate["configured_thresholds"] == 0
    assert candidate["pilot_admission"] == "not_admitted"
    assert candidate["effective_resolution_m"] is None
    assert candidate["habitat_score"] is None and candidate["fruiting_score"] is None
    assert "confidence" not in json.dumps(report)


@pytest.mark.parametrize(
    "case",
    [
        "synonym",
        "fuzzy",
        "higher_rank",
        "unaccepted",
        "wrong_name",
        "wrong_key",
        "wrong_kingdom",
        "duplicate_kingdom",
        "class_species",
        "usage_dataset",
        "usage_name",
        "usage_rank",
        "usage_status",
        "usage_kingdom",
        "usage_bool_key",
    ],
)
def test_no_silent_taxonomic_reconciliation(
    tmp_path: Path, definition: dict[str, Any], case: str
) -> None:
    kind = "usage" if case.startswith("usage_") else "match"
    ref = definition["candidates"][0][kind]
    path = tmp_path / ref["path"]
    body = json.loads(path.read_bytes())
    if case == "synonym":
        body["synonym"] = True
    elif case == "fuzzy":
        body["diagnostics"]["matchType"] = "FUZZY"
    elif case == "higher_rank":
        body["usage"]["rank"] = "GENUS"
    elif case == "unaccepted":
        body["usage"]["status"] = "SYNONYM"
    elif case == "wrong_name":
        body["usage"]["canonicalName"] = "Testus alius"
    elif case == "wrong_key":
        body["usage"]["key"] = "124"
    elif case == "wrong_kingdom":
        body["classification"][0]["name"] = "Plantae"
    elif case == "duplicate_kingdom":
        body["classification"].append({"rank": "KINGDOM", "name": "Plantae"})
    elif case == "class_species":
        body["classification"][1]["key"] = "124"
    elif case == "usage_dataset":
        body["datasetKey"] = "another-reference"
    elif case == "usage_name":
        body["canonicalName"] = "Testus alius"
    elif case == "usage_rank":
        body["rank"] = "GENUS"
    elif case == "usage_status":
        body["taxonomicStatus"] = "SYNONYM"
    elif case == "usage_kingdom":
        body["kingdom"] = "Plantae"
    elif case == "usage_bool_key":
        body["key"] = True
    ref["sha256"] = write_json(path, body)
    with pytest.raises(ValueError):
        run(tmp_path, definition)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_candidate",
        "duplicate_paper",
        "unknown_paper",
        "wrong_host_rank",
        "negative_exhaustive",
        "admitted",
        "enabled_score",
        "wrong_unit",
        "reversed_range",
        "no_basis",
        "unknown_variable",
        "duplicate_threshold",
        "duplicate_association",
        "future_publication",
        "future_registry",
        "future_capture",
        "raw_coordinates",
        "old_reference_as_current",
    ],
)
def test_metadata_limits_and_disabled_scientific_use(
    tmp_path: Path, definition: dict[str, Any], case: str
) -> None:
    candidate = definition["candidates"][0]
    threshold = candidate["thresholds"][0]
    if case == "duplicate_candidate":
        definition["candidates"] *= 2
    elif case == "duplicate_paper":
        definition["evidence"] *= 2
    elif case == "unknown_paper":
        candidate["associations"][0]["source_ids"] = ["unknown-paper"]
    elif case == "wrong_host_rank":
        candidate["associations"][0]["host_rank"] = "species"
    elif case == "negative_exhaustive":
        candidate["associations"][0]["exhaustive_host_list"] = True
    elif case == "admitted":
        candidate["pilot_admission"] = "admitted"
    elif case == "enabled_score":
        threshold["scoring_enabled"] = True
    elif case == "wrong_unit":
        threshold["unit"] = "m"
    elif case == "reversed_range":
        threshold.update(lower=7.0, upper=3.0, source_ids=["test-paper"])
    elif case == "no_basis":
        threshold["lower"] = 3.0
    elif case == "unknown_variable":
        threshold["variable"] = "rainfall_mm"
    elif case == "duplicate_threshold":
        candidate["thresholds"] *= 2
    elif case == "duplicate_association":
        candidate["associations"] *= 2
    elif case == "future_publication":
        definition["evidence"][0]["published_year"] = 2021
    elif case == "future_registry":
        definition["reference"]["registry_published_at"] = "2021-01-01T00:00:00Z"
    elif case == "future_capture":
        candidate["match"]["fetched_at"] = "2021-01-01T00:00:00Z"
    elif case == "raw_coordinates":
        candidate["longitude"] = 4.2
    elif case == "old_reference_as_current":
        definition["reference"]["scope"] = "current_col_xr"
    with pytest.raises(ValueError):
        run(tmp_path, definition)


def test_explicit_numeric_hypothesis_is_configurable_but_still_disabled(
    tmp_path: Path, definition: dict[str, Any]
) -> None:
    definition["candidates"][0]["thresholds"][0].update(
        lower=3.0, upper=7.0, source_ids=["test-paper"]
    )
    report = run(tmp_path, definition)
    assert report["candidates"][0]["configured_thresholds"] == 1
    assert report["candidates"][0]["habitat_score"] is None
    assert report["publication_allowed"] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://api.gbif.org/v2/species/match?scientificName=Testus%20inventus&kingdom=Fungi&rank=SPECIES",
        "https://api.gbif.org/v2/species/match?scientificName=Testus%20alius&kingdom=Fungi&rank=SPECIES",
        "https://api.gbif.org/v2/species/match?scientificName=Testus%20inventus&scientificName=Testus%20inventus&kingdom=Fungi&rank=SPECIES",
        "https://example.invalid/v2/species/match",
        "https://private:secret@api.gbif.org/v2/species/match",
    ],
)
def test_source_urls_are_checked_without_calling_them(
    tmp_path: Path, definition: dict[str, Any], url: str
) -> None:
    definition["candidates"][0]["match"]["url"] = url
    with pytest.raises(ValueError):
        run(tmp_path, definition)


@pytest.mark.parametrize("case", ["escape", "absolute", "corrupt", "oversize", "duplicate_key"])
def test_source_file_integrity(tmp_path: Path, definition: dict[str, Any], case: str) -> None:
    ref = definition["candidates"][0]["match"]
    if case == "escape":
        ref["path"] = "../PRIVATE_SENTINEL.json"
    elif case == "absolute":
        ref["path"] = str(tmp_path / "match.json")
    elif case == "corrupt":
        (tmp_path / "match.json").write_bytes(b"{}")
    elif case == "oversize":
        (tmp_path / "match.json").write_bytes(b" " * (MAX_RESPONSE + 1))
    elif case == "duplicate_key":
        path = tmp_path / "match.json"
        raw = path.read_bytes().replace(b'"synonym": false', b'"synonym":true,"synonym":false')
        path.write_bytes(raw)
        ref["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        run(tmp_path, definition)


@pytest.mark.parametrize("value", [1700000000, "2020-01-01", "2020-01-01T00:00:00"])
def test_explicit_capture_time(tmp_path: Path, definition: dict[str, Any], value: object) -> None:
    definition["candidates"][0]["match"]["fetched_at"] = value
    with pytest.raises(ValueError):
        run(tmp_path, definition)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_thresholds(tmp_path: Path, definition: dict[str, Any], bad: str) -> None:
    raw = json.dumps(definition).replace('"lower": null', '"lower":' + bad)
    path = tmp_path / "catalog.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        load_catalog(path)


def test_cli_is_reproducible_offline_and_errors_reveal_no_source_details(
    tmp_path: Path,
    definition: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(tmp_path, definition)
    path = tmp_path / "catalog.json"
    modified = path.stat().st_mtime_ns
    monkeypatch.setattr(sys, "argv", ["catalog", "--manifest", str(path)])

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Network forbidden")

    monkeypatch.setattr(socket, "socket", forbidden)
    assert main() == 0
    first = capsys.readouterr().out
    assert main() == 0
    assert capsys.readouterr().out == first
    assert path.stat().st_mtime_ns == modified
    second = deepcopy(definition["candidates"][0])
    second.update(id="candidate:late", canonical_name="Fictus falsus", usage_key="124")
    second["match"].update(
        path="PRIVATE_SENTINEL.json",
        url="https://api.gbif.org/v2/species/match?scientificName=Fictus%20falsus&kingdom=Fungi&rank=SPECIES",
    )
    second["usage"]["url"] = "https://api.gbif.org/v1/species/124"
    definition["candidates"].append(second)
    write_json(path, definition)
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == '{"error":"species_catalog_invalid"}\n'
    assert captured.err == ""
    path.write_bytes(b" " * (MAX_MANIFEST + 1))
    assert main() == 2
    assert capsys.readouterr().out == '{"error":"species_catalog_invalid"}\n'


def test_real_curated_bundle_is_read_without_network_and_preserves_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "data" / "species", tmp_path / "species")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("The real fixture is offline, never refresh GBIF in tests")

    monkeypatch.setattr(socket, "socket", forbidden)
    catalog, digest = load_catalog(tmp_path / "species" / "catalog.json")
    report = receipt(catalog, digest)
    assert len(catalog.candidates) == 4 and len(catalog.evidence) == 4
    assert sum(len(c.associations) for c in catalog.candidates) == 5
    assert {c.canonical_name for c in catalog.candidates} == {
        "Lactarius sanguifluus",
        "Boletus aereus",
        "Boletus edulis",
        "Cantharellus cibarius",
    }
    for candidate in catalog.candidates:
        assert all(t.lower is None and t.upper is None for t in candidate.thresholds)
        assert candidate.pilot_admission == "not_admitted"
        for association in candidate.associations:
            assert association.concept_alignment == "not_verified"
            assert association.transfer_to_pilot == "unvalidated"
            assert association.exhaustive_host_list is False
    boletes = [c for c in catalog.candidates if c.canonical_name.startswith("Boletus ")]
    assert all(c.associations[0].host_name == "Cistus" for c in boletes)
    assert all(c.associations[0].host_rank == "genus" for c in boletes)
    assert all(c.associations[0].vegetation_form == "shrub" for c in boletes)
    assert report["publication_allowed"] is False
