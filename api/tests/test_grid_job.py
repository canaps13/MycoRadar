"""Job contract and publication tests, using clearly synthetic, public polygon fixtures."""

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from mycoradar.grid import GridError
from mycoradar.grid_job import build_artifact, canonical_json, main, write_artifact
from pydantic import ValidationError
from shapely.geometry import box, mapping, shape


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    data = canonical_json(
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:6933"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": {"code": "test"},
                    "geometry": mapping(box(0, 0, 1000, 1000)),
                }
            ],
        }
    )
    (tmp_path / "source.geojson").write_bytes(data)
    definition = {
        "schema_version": "grid-manifest-v1",
        "grid": {"resolutions_m": [1000]},
        "layers": {
            "synthetic": {
                "path": "source.geojson",
                "sha256": hashlib.sha256(data).hexdigest(),
                "crs": "EPSG:6933",
                "provenance": {
                    "provider": "Synthetic fixture",
                    "product": "Not a real boundary",
                    "version": "fixture-1",
                    "source_url": "https://example.invalid/synthetic",
                    "license": "CC0-1.0",
                    "license_url": "https://example.invalid/license",
                    "attribution": "Synthetic test only",
                    "fetched_at": "2026-01-01T00:00:00Z",
                    "source_published_at": None,
                    "visibility": "public",
                },
            }
        },
        "territories": [
            {
                "id": "test:region",
                "name": "Synthetic test",
                "country_code": "NZ",
                "timezone": "Pacific/Auckland",
                "boundary": {"layer": "synthetic"},
                "land": None,
                "forest": None,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical_json(definition))
    return path


def edit(path: Path, mutate: Any) -> None:
    definition = json.loads(path.read_bytes())
    mutate(definition)
    path.write_bytes(canonical_json(definition))


def test_artifact_is_reproducible_and_preserves_provenance_and_unknowns(manifest: Path) -> None:
    first = build_artifact(manifest)
    assert canonical_json(first) == canonical_json(build_artifact(manifest))
    assert (
        first["inputs"]["manifest"]["layers"]["synthetic"]["provenance"]["visibility"] == "public"
    )
    feature = first["features"][0]
    assert shape(feature["geometry"]).geom_type == "MultiPolygon"
    assert shape(feature["geometry"]).is_valid
    properties = feature["properties"]
    assert properties["cell_id"] == "epsg6933-v1:1000:0:0"
    assert properties["coverage_status"] == "unavailable"
    for key in (
        "land_fraction",
        "forest_fraction",
        "display_cell_size_m",
        "effective_resolution_m",
        "location_uncertainty_m",
    ):
        assert properties[key] is None
    assert "score" not in canonical_json(first).decode()
    edit(manifest, lambda d: d["layers"]["synthetic"]["provenance"].update(version="fixture-2"))
    second = build_artifact(manifest)
    assert first["job_id"] != second["job_id"]
    assert properties["cell_id"] == second["features"][0]["properties"]["cell_id"]


def test_known_zero_forest_requires_coverage_and_stable_full_cell(manifest: Path) -> None:
    empty = canonical_json(
        {
            "type": "FeatureCollection",
            "features": [],
            "crs": {"type": "name", "properties": {"name": "EPSG:6933"}},
        }
    )
    (manifest.parent / "empty.geojson").write_bytes(empty)

    def masks(d: dict[str, Any]) -> None:
        layer = deepcopy(d["layers"]["synthetic"])
        layer.update(path="empty.geojson", sha256=hashlib.sha256(empty).hexdigest())
        d["layers"]["empty"] = layer
        d["territories"][0]["land"] = {
            "positive": {"layer": "synthetic"},
            "coverage": {"layer": "synthetic"},
        }
        d["territories"][0]["forest"] = {
            "positive": {"layer": "empty"},
            "coverage": {"layer": "synthetic"},
        }

    edit(manifest, masks)
    properties = build_artifact(manifest)["features"][0]["properties"]
    assert properties["land_fraction"] == 1 and properties["forest_fraction"] == 0
    assert properties["coverage_status"] == "complete"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["layers"]["synthetic"].update(sha256="0" * 64),
        lambda d: d["layers"]["synthetic"].update(path="../outside.geojson"),
        lambda d: d["layers"]["synthetic"].update(crs="EPSG:4326"),
        lambda d: d["territories"][0]["boundary"].update(layer="missing"),
        lambda d: d["territories"][0]["boundary"].update(property="code", value="missing"),
    ],
)
def test_input_mismatch_or_escape_fails_before_publication(manifest: Path, change: Any) -> None:
    edit(manifest, change)
    with pytest.raises(GridError):
        build_artifact(manifest)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["layers"]["synthetic"]["provenance"].update(visibility="private"),
        lambda d: d["layers"]["synthetic"]["provenance"].update(license=""),
        lambda d: d["layers"]["synthetic"]["provenance"].update(license="CC-BY-NC-4.0"),
        lambda d: d["layers"]["synthetic"]["provenance"].pop("source_published_at"),
        lambda d: d["territories"][0].update(timezone="not/a/timezone"),
        lambda d: d["territories"].append(d["territories"][0]),
    ],
)
def test_incomplete_rights_private_inputs_and_bad_configuration_fail(
    manifest: Path, change: Any
) -> None:
    edit(manifest, change)
    with pytest.raises(ValidationError):
        build_artifact(manifest)


def test_candidate_budget_is_global_across_territories(manifest: Path) -> None:
    def extend(d: dict[str, Any]) -> None:
        d["grid"]["max_candidates"] = 1
        second = deepcopy(d["territories"][0])
        second["id"] = "test:second"
        d["territories"].append(second)

    edit(manifest, extend)
    with pytest.raises(GridError, match="budget"):
        build_artifact(manifest)


def test_atomic_no_overwrite_and_idempotent_publication(tmp_path: Path) -> None:
    output = tmp_path / "grid.geojson"
    assert write_artifact(output, b"first\n")
    before = output.stat().st_mtime_ns
    assert not write_artifact(output, b"first\n")
    assert output.stat().st_mtime_ns == before
    with pytest.raises(GridError, match="different content"):
        write_artifact(output, b"second\n")
    assert output.read_bytes() == b"first\n"
    assert list(tmp_path.iterdir()) == [output]


def test_failed_atomic_publication_leaves_no_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any) -> None:
        raise OSError("Synthetic disk failure")

    monkeypatch.setattr("mycoradar.grid_job.os.link", fail)
    with pytest.raises(OSError):
        write_artifact(tmp_path / "output.geojson", b"data")
    assert list(tmp_path.iterdir()) == []


def test_cli_can_be_replayed_without_rewriting(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = manifest.parent / "artifact.geojson"
    monkeypatch.setattr(
        "sys.argv", ["grid_job", "--manifest", str(manifest), "--output", str(output)]
    )
    assert main() == 0
    before = output.read_bytes()
    assert main() == 0 and output.read_bytes() == before


def test_pilot_reference_is_real_versioned_and_never_claims_missing_masks(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2] / "data/territories/provence"
    shutil.copyfile(
        root / "ign-adminexpress-source.geojson", tmp_path / "ign-adminexpress-source.geojson"
    )
    definition = json.loads((root / "manifest.json").read_bytes())
    definition["grid"]["resolutions_m"] = [10000]  # Small offline CI smoke on the real extract.
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical_json(definition))
    artifact = build_artifact(path)
    assert {f["properties"]["region_id"] for f in artifact["features"]} == {
        "FR-13",
        "FR-83",
        "FR-84",
    }
    assert all(f["properties"]["coverage_status"] == "unavailable" for f in artifact["features"])
    assert all(f["properties"]["forest_fraction"] is None for f in artifact["features"])
    source = artifact["inputs"]["manifest"]["layers"]["ign-boundaries"]["provenance"]
    assert source["provider"] == "IGN" and source["source_published_at"] is None
