"""Invented public geometries unless a test explicitly checks the frozen IGN sample."""

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from mycoradar import landcover_job as job
from mycoradar.grid_job import canonical_json, write_artifact
from pydantic import ValidationError
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape


def feature(identifier="synthetic-1", geometry=None, **props):
    return {
        "type": "Feature",
        "geometry": mapping(geometry if geometry is not None else box(-0.02, -0.02, 0.005, 0.005)),
        "properties": {
            "id": identifier,
            "code_tfv": "LA4",
            "tfv": "Synthetic shrubland",
            "tfv_g11": "Synthetic group",
            "essence": "NC",
            "PRIVATE_IGNORED": "PRIVATE_SENTINEL",
            **props,
        },
    }


@pytest.fixture
def manifest(tmp_path):
    data = {"type": "FeatureCollection", "features": [feature()]}
    path = tmp_path / "manifest.json"
    spec = {
        "schema_version": "landcover-manifest-v1",
        "path": "source.geojson.gz",
        "sha256": "0" * 64,
        "entity_sha256": "0" * 64,
        "compression": "gzip",
        "crs": "EPSG:4326",
        "bbox": [-0.01, -0.01, 0.01, 0.01],
        "provenance": {
            "provider": "Synthetic provider",
            "product": "Invented test layer",
            "source_url": "https://example.invalid/landcover",
            "license": "CC0-1.0",
            "license_url": "https://example.invalid/license",
            "attribution": "Synthetic test only",
            "version": "test-1",
            "fetched_at": "2026-01-01T00:00:00Z",
            "source_published_at": None,
            "effective_resolution_m": None,
            "visibility": "public",
        },
        "product_metadata_url": "https://example.invalid/metadata",
    }
    path.write_bytes(canonical_json(spec))
    update_source(path, data)
    return path


def update_source(path, data):
    raw = canonical_json(data)
    packed = gzip.compress(raw, mtime=0)
    spec = json.loads(path.read_bytes())
    (path.parent / spec["path"]).write_bytes(packed)
    spec["sha256"] = hashlib.sha256(packed).hexdigest()
    spec["entity_sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_bytes(canonical_json(spec))


def edit(manifest_path, **changes):
    spec = json.loads(manifest_path.read_bytes())
    spec.update(changes)
    manifest_path.write_bytes(canonical_json(spec))


def test_clip_retains_categories_unknown_year_and_never_infers_zero_forest(manifest):
    a = job.build_artifact(manifest)
    assert a["negative_inference_allowed"] is False and a["grid_mask_status"] == "unavailable"
    assert a["forest_fraction"] is None and a["coverage_status"] == "partial"
    assert a["quality"]["unknown_source_year"] == 1
    p = a["features"][0]["properties"]
    assert p["vegetation_code"] == "LA4" and p["dominant_taxa"] is None
    assert p["source_year"] is None and p["year_status"] == "unavailable"
    assert p["current_ground_cover_verified"] is False and p["effective_resolution_m"] is None
    g = shape(a["features"][0]["geometry"])
    assert isinstance(g, MultiPolygon) and g.is_valid
    assert box(-0.01, -0.01, 0.01, 0.01).buffer(1e-9).covers(g)
    assert "PRIVATE_SENTINEL" not in canonical_json(a).decode()


def test_same_input_and_runtime_produce_identical_bytes_and_non_overwriting_replay(
    manifest, tmp_path
):
    a = canonical_json(job.build_artifact(manifest))
    assert a == canonical_json(job.build_artifact(manifest))
    output = tmp_path / "result.geojson"
    assert write_artifact(output, a) is True
    before = output.stat().st_mtime_ns
    assert write_artifact(output, a) is False and output.stat().st_mtime_ns == before
    with pytest.raises(ValueError):
        write_artifact(output, b"different")
    assert output.read_bytes() == a


def test_holes_and_multipart_geometry_survive_normalization(manifest):
    polygon = Polygon(
        [(-0.005, -0.005), (0.005, -0.005), (0.005, 0.005), (-0.005, 0.005)],
        holes=[[(-0.001, -0.001), (0.001, -0.001), (0.001, 0.001), (-0.001, 0.001)]],
    )
    multi = MultiPolygon([polygon, box(0.006, 0.006, 0.008, 0.008)])
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(geometry=multi)]})
    g = shape(job.build_artifact(manifest)["features"][0]["geometry"])
    assert len(g.geoms) == 2 and sum(len(p.interiors) for p in g.geoms) == 1


def test_overlap_is_reported_without_choosing_a_winning_vegetation_type(manifest):
    update_source(
        manifest,
        {"type": "FeatureCollection", "features": [feature(), feature("other", code_tfv="FF31")]},
    )
    a = job.build_artifact(manifest)
    assert len(a["features"]) == 2 and set(a["quality"]["vegetation_counts"]) == {"LA4", "FF31"}
    assert a["quality"]["overlap_area_m2"] > 0
    assert a["quality"]["summed_mapped_area_m2"] > a["quality"]["union_mapped_area_m2"]


def test_exact_duplicate_ids_deduplicate_but_conflicts_fail(manifest):
    f = feature()
    update_source(manifest, {"type": "FeatureCollection", "features": [f, deepcopy(f)]})
    assert job.build_artifact(manifest)["quality"]["duplicate_identities"] == 1
    update_source(
        manifest, {"type": "FeatureCollection", "features": [f, feature(code_tfv="other")]}
    )
    with pytest.raises(job.LandcoverError, match="duplicate_identity_conflict"):
        job.build_artifact(manifest)


def test_invalid_geometry_requires_explicit_repair_and_records_it(manifest):
    bowtie = Polygon(
        [(-0.005, -0.005), (0.005, 0.005), (0.005, -0.005), (-0.005, 0.005), (-0.005, -0.005)]
    )
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(geometry=bowtie)]})
    with pytest.raises(job.LandcoverError, match="explicit_repair"):
        job.build_artifact(manifest)
    edit(manifest, repair_invalid=True)
    a = job.build_artifact(manifest)
    assert a["quality"]["repaired_geometries"] == 1
    assert a["features"][0]["properties"]["geometry_repaired"] is True
    assert shape(a["features"][0]["geometry"]).is_valid


def test_repair_cannot_turn_a_collapsed_polygon_into_a_mapped_surface(manifest):
    polygon = Polygon([(0, 0), (0.001, 0.001), (0.002, 0.002), (0, 0)])
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(geometry=polygon)]})
    edit(manifest, repair_invalid=True)
    with pytest.raises(job.LandcoverError, match="repair_has_no_area"):
        job.build_artifact(manifest)


def test_repair_reports_discarded_zero_area_spike(manifest):
    polygon = Polygon(
        [
            (0, 0),
            (0.005, 0),
            (0.005, 0.005),
            (0.0025, 0.005),
            (0.0025, 0.008),
            (0.0025, 0.005),
            (0, 0.005),
            (0, 0),
        ]
    )
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(geometry=polygon)]})
    edit(manifest, repair_invalid=True)
    a = job.build_artifact(manifest)
    assert a["quality"]["non_polygon_parts_removed"] == 1


def test_outside_and_empty_selection_are_unavailable_not_nonforest(manifest):
    update_source(
        manifest,
        {"type": "FeatureCollection", "features": [feature(geometry=box(0.02, 0.02, 0.03, 0.03))]},
    )
    a = job.build_artifact(manifest)
    assert a["quality"]["outside_or_boundary_only"] == 1
    assert a["coverage_status"] == "unavailable" and a["forest_fraction"] is None
    update_source(manifest, {"type": "FeatureCollection", "features": []})
    assert job.build_artifact(manifest)["coverage_status"] == "unavailable"


def test_source_year_requires_evidence_and_does_not_come_from_production_period(manifest):
    edit(manifest, product_production_period=[2007, 2018])
    assert job.build_artifact(manifest)["features"][0]["properties"]["source_year"] is None
    edit(manifest, source_year=2010)
    with pytest.raises(ValidationError):
        job.build_artifact(manifest)
    edit(manifest, year_meaning="reference", year_evidence_url="https://example.invalid/year")
    assert job.build_artifact(manifest)["features"][0]["properties"]["source_year"] == 2010


@pytest.mark.parametrize("value", [True, "2020-01-01", "unknown", 2027, 0, 2020.5])
def test_invalid_feature_year_does_not_get_truncated_or_guessed(manifest, value):
    spec = json.loads(manifest.read_bytes())
    spec["properties"] = {"source_year": "year"}
    spec["year_meaning"] = "acquisition"
    spec["year_evidence_url"] = "https://example.invalid/year"
    manifest.write_bytes(canonical_json(spec))
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(year=value)]})
    with pytest.raises(job.LandcoverError, match="source_year_invalid"):
        job.build_artifact(manifest)


def test_feature_year_conflict_is_rejected(manifest):
    edit(
        manifest,
        source_year=2020,
        year_meaning="reference",
        year_evidence_url="https://example.invalid/year",
        properties={"source_year": "year"},
    )
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(year=2021)]})
    with pytest.raises(job.LandcoverError, match="source_year_conflict"):
        job.build_artifact(manifest)


@pytest.mark.parametrize("crs", ["urn:ogc:def:crs:CRS::84", "CRS:84", "EPSG:4326"])
def test_reviewed_geojson_crs84_aliases_preserve_longitude_latitude(manifest, crs):
    update_source(
        manifest,
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": crs}},
            "features": [feature()],
        },
    )
    assert len(job.build_artifact(manifest)["features"]) == 1


def test_projected_input_needs_matching_crs_and_transforms_instead_of_relabelling(manifest):
    data = {"type": "FeatureCollection", "features": [feature(geometry=box(-500, -500, 500, 500))]}
    edit(manifest, crs="EPSG:6933")
    update_source(manifest, data)
    with pytest.raises(job.LandcoverError, match="crs_declaration_missing"):
        job.build_artifact(manifest)
    data["crs"] = {"type": "name", "properties": {"name": "EPSG:6933"}}
    update_source(manifest, data)
    g = shape(job.build_artifact(manifest)["features"][0]["geometry"])
    assert g.bounds[2] < 0.01 and g.bounds[3] < 0.01
    data["crs"]["properties"]["name"] = "EPSG:4326"
    update_source(manifest, data)
    with pytest.raises(job.LandcoverError, match="crs_mismatch"):
        job.build_artifact(manifest)


@pytest.mark.parametrize(
    "field,value", [("numberMatched", 2), ("numberReturned", True), ("totalFeatures", "unknown")]
)
def test_truncated_or_unverifiable_service_counts_fail_closed(manifest, field, value):
    update_source(manifest, {"type": "FeatureCollection", "features": [feature()], field: value})
    with pytest.raises(job.LandcoverError, match="selection_truncated"):
        job.build_artifact(manifest)


def test_input_checksums_and_path_containment_are_enforced(manifest):
    edit(manifest, entity_sha256="0" * 64)
    with pytest.raises(job.LandcoverError, match="entity_checksum"):
        job.build_artifact(manifest)
    edit(manifest, sha256="0" * 64)
    with pytest.raises(job.LandcoverError, match="input_checksum"):
        job.build_artifact(manifest)
    edit(manifest, path="../outside.geojson")
    with pytest.raises(job.LandcoverError, match="input_path_refused"):
        job.build_artifact(manifest)


def test_feature_vertex_and_area_budgets_are_checked(manifest, monkeypatch):
    update_source(
        manifest,
        {"type": "FeatureCollection", "features": [feature() for _ in range(job.MAX_FEATURES + 1)]},
    )
    with pytest.raises(job.LandcoverError, match="feature_budget"):
        job.build_artifact(manifest)
    update_source(manifest, {"type": "FeatureCollection", "features": [feature()]})
    monkeypatch.setattr(job, "MAX_VERTICES", 4)
    with pytest.raises(job.LandcoverError, match="vertex_budget"):
        job.build_artifact(manifest)
    edit(manifest, bbox=[0, 0, 1, 1])
    with pytest.raises(job.LandcoverError, match="aoi_budget"):
        job.build_artifact(manifest)


def test_compressed_bomb_is_bounded_before_geometry_allocation(manifest, monkeypatch):
    update_source(
        manifest, {"type": "FeatureCollection", "features": [feature(ignored="x" * 10000)]}
    )
    monkeypatch.setattr(job, "MAX_BYTES", 1000)
    with pytest.raises(job.LandcoverError, match="decoded_budget"):
        job.build_artifact(manifest)


def test_properties_are_normalized_and_arbitrary_controls_are_rejected(manifest):
    update_source(
        manifest, {"type": "FeatureCollection", "features": [feature(tfv="Pin d\x92Alep")]}
    )
    a = job.build_artifact(manifest)
    assert a["features"][0]["properties"]["vegetation_label"] == "Pin d’Alep"
    assert a["quality"]["legacy_punctuation_transcoded"] == 1
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(tfv="bad\nlabel")]})
    with pytest.raises(job.LandcoverError, match="property_control_character"):
        job.build_artifact(manifest)


def test_three_dimensions_are_not_silently_dropped(manifest):
    polygon = Polygon([(0, 0, 1), (0.005, 0, 1), (0.005, 0.005, 1), (0, 0, 1)])
    update_source(manifest, {"type": "FeatureCollection", "features": [feature(geometry=polygon)]})
    with pytest.raises(job.LandcoverError, match="two_dimensions"):
        job.build_artifact(manifest)


def test_cli_publishes_atomically_and_failures_never_echo_documents(manifest, tmp_path, capsys):
    output = tmp_path / "result.geojson"
    argv = ["--manifest", str(manifest), "--output", str(output)]
    assert job.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["created"] is True
    assert job.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["created"] is False
    manifest.write_text('{"private":"PRIVATE_SENTINEL"}')
    assert job.main(argv) == 2
    result = capsys.readouterr()
    assert "PRIVATE_SENTINEL" not in result.out + result.err
    assert json.loads(result.out)["status"] == "unavailable"


def test_frozen_real_ign_extract_has_valid_clipped_categories_and_unknown_years():
    path = Path(__file__).resolve().parents[2] / "data/landcover/bdforet-sample/manifest.json"
    a = job.build_artifact(path)
    assert a["quality"]["received"] == 48 and a["quality"]["output"] == 45
    assert a["quality"]["repaired_geometries"] == 0
    assert a["quality"]["unknown_source_year"] == 45
    assert a["quality"]["vegetation_counts"]["LA4"] == 5
    assert all(shape(f["geometry"]).is_valid for f in a["features"])


@pytest.mark.parametrize("coordinate", [True, "0.005", float("nan"), float("inf")])
def test_non_numeric_and_nonfinite_coordinates_are_rejected_before_projection(manifest, coordinate):
    f = feature()
    # Mapping tuples become JSON lists as in the actual source format.
    f = json.loads(json.dumps(f))
    f["geometry"]["coordinates"][0][0][0] = coordinate
    raw = json.dumps({"type": "FeatureCollection", "features": [f]}, allow_nan=True).encode()
    packed = gzip.compress(raw, mtime=0)
    (manifest.parent / "source.geojson.gz").write_bytes(packed)
    edit(
        manifest,
        sha256=hashlib.sha256(packed).hexdigest(),
        entity_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(job.LandcoverError, match="coordinates_invalid"):
        job.build_artifact(manifest)
