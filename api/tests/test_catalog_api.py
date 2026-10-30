"""Real IGN display smoke plus explicitly synthetic fixtures for cells/taxa and failures."""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urljoin

import pytest
from fastapi.testclient import TestClient
from mycoradar.catalog import DEFAULT_CATALOG, Catalog
from mycoradar.catalog_api import intersects
from mycoradar.main import app

from scripts.prepare_catalog import build_catalog


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as connection:
        yield connection


def test_real_admitted_regions_have_provenance_but_no_scientific_result(client: TestClient) -> None:
    response = client.get("/v1/regions?country=FR")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert [r["id"] for r in body["items"]] == ["FR-13", "FR-83", "FR-84"]
    assert body["items"][0]["name"] == "Bouches-du-Rhône"
    assert all(r["geometry"]["type"] == "MultiPolygon" for r in body["items"])
    assert "score" not in response.text and "occurrences" not in response.text
    metadata = client.get("/v1/metadata").json()
    assert metadata["catalog_version"] == body["catalog_version"]
    sources = {s["id"]: s for s in metadata["items"]}
    for record in body["items"]:
        for key in record["source_ids"]:
            assert sources[key]["provider"] == "IGN"
            assert sources[key]["license"] == "Etalab-2.0"
            assert sources[key]["source_published_at"] is None
            assert sources[key]["effective_resolution_m"] is None
            assert sources[key]["fetched_at"].startswith("2026-10-29T17:06:20")


def test_frozen_publication_is_reproducible_and_verified() -> None:
    content = build_catalog()
    assert content == DEFAULT_CATALOG.read_bytes()
    assert (
        hashlib.sha256(content).hexdigest()
        == DEFAULT_CATALOG.with_suffix(".sha256").read_text().strip()
    )


def test_version_pinned_pagination_preserves_filters_and_has_no_duplicates(
    client: TestClient,
) -> None:
    url = "/v1/regions?country=FR&limit=1"
    identities = []
    for offset in range(3):
        response = client.get(url)
        page = response.json()
        assert response.status_code == 200
        assert page["pagination"]["offset"] == offset
        assert page["pagination"]["total"] == 3
        identities.append(page["items"][0]["id"])
        next_link = page["pagination"]["next"]
        if offset < 2:
            assert next_link.startswith("?")  # Also works behind the /api reverse proxy.
            assert "country=FR" in next_link and "catalog_version=" in next_link
            url = urljoin(str(response.request.url), next_link)
        else:
            assert next_link is None
    assert identities == ["FR-13", "FR-83", "FR-84"]
    assert client.get("/v1/regions?offset=3").json()["items"] == []


@pytest.mark.parametrize("path", ["regions", "species", "cells", "metadata"])
def test_changed_snapshot_rejects_stale_pagination_version(client: TestClient, path: str) -> None:
    response = client.get(f"/v1/{path}?catalog_version={'0' * 64}&region_id=FR-83")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "catalog_version_conflict"


@pytest.mark.parametrize(
    "query,identities",
    [
        ("country=ES", []),
        ("region_id=FR-83", ["FR-83"]),
        ("bbox=6.5,43.3,6.6,43.4", ["FR-83"]),
        ("bbox=-3,50,-2,51", []),
    ],
)
def test_geographic_filters_are_explicit_envelope_candidates(
    client: TestClient, query: str, identities: list[str]
) -> None:
    body = client.get(f"/v1/regions?{query}").json()
    assert [r["id"] for r in body["items"]] == identities
    assert body["status"] == "partial"  # Empty selection does not prove worldwide coverage.
    assert body["spatial_filter"] == ("envelope_intersects" if "bbox=" in query else None)


def test_envelope_boundary_contact_is_included() -> None:
    assert intersects((0, 0, 1, 1), (1, 1, 2, 2))
    assert not intersects((0, 0, 1, 1), (1.01, 1.01, 2, 2))


@pytest.mark.parametrize(
    "path,reason",
    [
        ("/v1/species?region_id=FR-83", "no_admitted_taxonomy_published"),
        ("/v1/cells?region_id=FR-83", "no_grid_publication_admitted"),
    ],
)
def test_absent_taxonomy_or_grid_is_not_silent_empty_success(
    client: TestClient, path: str, reason: str
) -> None:
    body = client.get(path).json()
    assert body["status"] == "unavailable" and body["reason"] == reason
    assert body["items"] == [] and body["pagination"]["total"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=1.5",
        "offset=-1",
        "offset=50001",
        "country=fr",
        "bbox=1,2,3",
        "bbox=NaN,1,2,3",
        "bbox=-1,1,inf,3",
        "bbox=4,43,3,44",
        "bbox=170,-1,-170,1",
        "bbox=-181,0,-179,1",
        "bbox=0,91,1,92",
        "bbox=0,0,10,10",
        "bbox=0,0,0,1",
        "bbox=0,1,1,0",
        "limit=1&limit=2",
        "unknown=secret-value",
        "catalog_version=wrong",
        "region_id=../../private",
    ],
)
def test_invalid_or_unbounded_queries_have_documented_safe_errors(
    client: TestClient, query: str
) -> None:
    response = client.get(f"/v1/regions?{query}")
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "unavailable" and body["error"]["code"] == "invalid_query"
    assert response.headers["cache-control"] == "no-store"
    assert "secret-value" not in response.text and "private" not in response.text


@pytest.mark.parametrize("path", ["regions", "species", "cells"])
def test_unknown_region_is_a_typed_404(client: TestClient, path: str) -> None:
    response = client.get(f"/v1/{path}?region_id=missing-region")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "region_not_found"


@pytest.mark.parametrize(
    "path",
    [
        "/v1/cells",
        "/v1/species?bbox=1,1,2,2",
        "/v1/metadata?country=FR",
    ],
)
def test_unsupported_filter_combinations_are_rejected(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 422


def synthetic_publication() -> dict:  # type: ignore[type-arg]
    """Invented test records; never the application's default publication."""
    snapshot = json.loads(DEFAULT_CATALOG.read_bytes())
    source_id = snapshot["metadata"][0]["id"]
    snapshot["species"] = [
        {
            "id": "synthetic-taxon",
            "scientific_name": "Testus syntheticus",
            "region_ids": ["FR-83"],
            "sensitive": False,
            "source_ids": [source_id],
            "visibility": "public",
        }
    ]
    snapshot["cells"] = [
        {
            "id": "synthetic-cell",
            "region_ids": ["FR-83", "FR-13"],
            "source_ids": [source_id],
            "visibility": "public",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[6, 43], [6.01, 43], [6.01, 43.01], [6, 43.01], [6, 43]]],
            },
            "display_cell_size_m": 1000,
            "effective_resolution_m": None,
            "habitat_status": "unavailable",
            "fruiting_status": "unavailable",
        }
    ]
    for kind in ("species", "cells"):
        snapshot["availability"][kind] = {"status": "partial", "reason": "synthetic_test_only"}
    return snapshot


def install_fixture(client: TestClient, tmp_path: Path, snapshot: dict) -> None:  # type: ignore[type-arg]
    path = tmp_path / "synthetic-catalog.json"
    content = json.dumps(snapshot).encode()
    path.write_bytes(content)
    client.app.state.catalog = Catalog(path, hashlib.sha256(content).hexdigest())


def test_published_test_cells_are_unique_and_not_effective_resolution_or_presence(
    client: TestClient, tmp_path: Path
) -> None:
    install_fixture(client, tmp_path, synthetic_publication())
    cells = client.get("/v1/cells?country=FR&bbox=6,43,6.02,43.02").json()
    assert cells["pagination"]["total"] == 1  # A border cell associated with two regions is unique.
    item = cells["items"][0]
    assert item["effective_resolution_m"] is None and item["display_cell_size_m"] == 1000
    assert item["habitat_status"] == item["fruiting_status"] == "unavailable"
    assert client.get("/v1/cells?bbox=0,0,1,1").json()["items"] == []
    assert len(client.get("/v1/species?region_id=FR-83").json()["items"]) == 1
    assert client.get("/v1/species?region_id=FR-84").json()["items"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "private",
        "sensitive",
        "unknown_source",
        "unknown_region",
        "duplicate_id",
        "unclosed_ring",
        "invalid_longitude",
        "unknown_timezone",
        "unavailable_with_records",
        "naive_date",
        "occurrences",
    ],
)
def test_invalid_publications_fail_closed_without_leaking_private_inputs(
    client: TestClient, tmp_path: Path, mutation: str
) -> None:
    snapshot = synthetic_publication()
    if mutation == "private":
        snapshot["cells"][0]["visibility"] = "private"
    if mutation == "sensitive":
        snapshot["species"][0]["sensitive"] = True
    if mutation == "unknown_source":
        snapshot["cells"][0]["source_ids"] = ["private-source"]
    if mutation == "unknown_region":
        snapshot["cells"][0]["region_ids"] = ["private-region"]
    if mutation == "duplicate_id":
        snapshot["cells"].append(snapshot["cells"][0])
    if mutation == "unclosed_ring":
        snapshot["cells"][0]["geometry"]["coordinates"][0].pop()
    if mutation == "invalid_longitude":
        snapshot["cells"][0]["geometry"]["coordinates"][0][1][0] = 181
    if mutation == "unknown_timezone":
        snapshot["regions"][0]["timezone"] = "private-timezone"
    if mutation == "unavailable_with_records":
        snapshot["availability"]["cells"]["status"] = "unavailable"
    if mutation == "naive_date":
        snapshot["metadata"][0]["fetched_at"] = "2026-10-29T17:06:20"
    if mutation == "occurrences":
        snapshot["occurrences"] = [{"private_coords": [6.001, 43.002]}]
    install_fixture(client, tmp_path, snapshot)
    for path in ("regions", "species", "metadata", "cells?region_id=FR-83"):
        response = client.get(f"/v1/{path}")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "catalog_unavailable"
        assert "private" not in response.text and str(tmp_path) not in response.text
    assert client.get("/health").json()["status"] == "ok"


def test_missing_malformed_or_tampered_artifact_is_not_served(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    assert Catalog(path, "0" * 64).snapshot is None
    path.write_bytes(b"not JSON")
    assert Catalog(path, hashlib.sha256(path.read_bytes()).hexdigest()).snapshot is None
    path.write_bytes(DEFAULT_CATALOG.read_bytes())
    assert Catalog(path, "0" * 64).snapshot is None
    assert Catalog(path, "").snapshot is None


def test_loaded_catalog_does_not_reload_or_read_files_during_requests(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Request-time catalogue I/O")

    monkeypatch.setattr(Path, "open", forbidden)
    assert client.get("/v1/regions").status_code == 200
    assert client.get("/v1/metadata").status_code == 200


def test_openapi_has_concrete_pages_query_bounds_and_typed_failures(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    for name in ("regions", "species", "cells", "metadata"):
        operation = document["paths"][f"/v1/{name}"]["get"]
        assert set(operation["responses"]) >= {"200", "404", "409", "422", "503"}
        query = {p["name"]: p["schema"] for p in operation["parameters"]}
        assert query["limit"]["maximum"] == 100
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("ErrorResponse")


def test_corrupt_checksum_sidecar_does_not_kill_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog.json"
    path.write_bytes(DEFAULT_CATALOG.read_bytes())
    path.with_suffix(".sha256").write_bytes(b"\xff\xfe")
    monkeypatch.setattr("mycoradar.main.DEFAULT_CATALOG", path)
    with TestClient(app) as connection:
        assert connection.get("/health").status_code == 200
        assert connection.get("/v1/regions").status_code == 503
