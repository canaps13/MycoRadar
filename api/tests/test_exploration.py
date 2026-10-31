"""Real pilot geometries and explicitly synthetic taxon/configuration fixtures."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mycoradar.catalog import DEFAULT_CATALOG, Catalog
from mycoradar.exploration import CONTEXT_PATH, ExplorerBundle
from mycoradar.main import app

from scripts.prepare_catalog import main as prepare_main


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as connection:
        yield connection


def test_real_explorer_is_partial_with_separate_unavailable_layers(client: TestClient) -> None:
    response = client.get("/v1/exploration?region_id=FR-83&valid_at=2026-11-01")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial" and data["requested_date"] == "2026-11-01"
    assert data["selected_region_id"] == "FR-83" and data["selected_taxon_id"] is None
    assert [r["id"] for r in data["regions"]] == ["FR-13", "FR-83", "FR-84"]
    assert all(r["geometry"]["type"] == "MultiPolygon" for r in data["regions"])
    assert data["species"] == [] and data["species_state"]["status"] == "unavailable"
    for layer in ("habitat", "fruiting"):
        assert data[layer]["status"] == "unavailable" and data[layer]["score"] is None
        assert data[layer]["computed_at"] is None and data[layer]["effective_resolution_m"] is None
    assert data["source_age_days"] is None
    assert data["sources"][0]["provider"] == "IGN"
    assert data["sources"][0]["source_published_at"] is None
    assert data["sources"][0]["fetched_at"].startswith("2026-10-29T17:06:20")
    assert "probability" not in response.text


@pytest.mark.parametrize(
    "query,status,code",
    [
        ("region_id=missing", 404, "region_not_found"),
        ("taxon_id=not-admitted", 404, "taxon_not_admitted"),
        (f"catalog_version={'0' * 64}", 409, "catalog_version_conflict"),
        ("valid_at=0", 422, "invalid_query"),
        ("valid_at=2026-02-30", 422, "invalid_query"),
        ("valid_at=2026-01-01T00:00:00Z", 422, "invalid_query"),
        ("valid_at=1899-01-01", 422, "invalid_query"),
        ("valid_at=2101-01-01", 422, "invalid_query"),
        ("region_id=FR-13&region_id=FR-83", 422, "invalid_query"),
        ("private_location=sentinel", 422, "invalid_query"),
    ],
)
def test_explorer_typed_errors(client: TestClient, query: str, status: int, code: str) -> None:
    response = client.get(f"/v1/exploration?{query}")
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert "sentinel" not in response.text


def test_default_day_uses_the_territory_calendar(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 10, 30, 23, 30, tzinfo=UTC)

    monkeypatch.setattr("mycoradar.exploration.datetime", Clock)
    assert client.get("/v1/exploration?region_id=FR-83").json()["requested_date"] == "2026-10-31"


def test_missing_context_or_catalog_fails_closed_without_breaking_health(
    client: TestClient,
) -> None:
    app.state.explorer = None
    assert client.get("/v1/exploration").status_code == 503
    assert client.get("/health").status_code == 200
    app.state.catalog = None
    assert client.get("/v1/exploration").json()["error"]["code"] == "catalog_unavailable"


def test_one_synthetic_admitted_taxon_can_be_selected_without_fabricating_results(
    client: TestClient, tmp_path: Path
) -> None:
    data = json.loads(DEFAULT_CATALOG.read_bytes())
    source = {
        **data["metadata"][0],
        "id": "synthetic-taxonomy",
        "provider": "Synthetic fixture",
        "product": "Invented taxonomy for tests only",
        "source_url": "https://example.invalid/fixture",
    }
    data["metadata"].append(source)
    data["species"] = [
        {
            "id": "synthetic-taxon",
            "scientific_name": "Testus syntheticus",
            "region_ids": ["FR-83"],
            "visibility": "public",
            "sensitive": False,
            "source_ids": [source["id"]],
        }
    ]
    data["availability"]["species"] = {"status": "partial", "reason": "synthetic_test_only"}
    path = tmp_path / "catalog.json"
    content = json.dumps(data).encode()
    path.write_bytes(content)
    catalog = Catalog(path, hashlib.sha256(content).hexdigest())
    context = json.loads(CONTEXT_PATH.read_bytes())
    context["species_ids"] = ["synthetic-taxon"]
    path = tmp_path / "context.json"
    content = json.dumps(context).encode()
    path.write_bytes(content)
    path.with_suffix(".sha256").write_text(hashlib.sha256(content).hexdigest())
    app.state.catalog = catalog
    app.state.explorer = ExplorerBundle(catalog, path)
    result = client.get(
        "/v1/exploration?region_id=FR-83&taxon_id=synthetic-taxon&valid_at=2026-10-01"
    )
    assert result.status_code == 200
    body = result.json()
    assert body["species"][0]["scientific_name"] == "Testus syntheticus"
    assert body["selected_taxon_id"] == "synthetic-taxon"
    assert body["habitat"]["score"] is None and body["fruiting"]["score"] is None
    assert client.get("/v1/exploration?region_id=FR-84&taxon_id=synthetic-taxon").status_code == 404


def test_bundle_check_works_without_repository_or_geo_modules(tmp_path: Path) -> None:
    source = DEFAULT_CATALOG.parent.parent
    package = tmp_path / "mycoradar"
    package.mkdir()
    for name in (
        "__init__.py",
        "catalog.py",
        "catalog_models.py",
        "catalog_api.py",
        "exploration.py",
    ):
        shutil.copyfile(source / name, package / name)
    shutil.copytree(source / "data", package / "data")
    code = (
        "from mycoradar.exploration import check_bundle; check_bundle(); import sys; "
        "assert not {'numpy','shapely','pyproj'} & sys.modules.keys()"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "Explorer bundle verified" in result.stdout


def test_explorer_context_is_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prepare_catalog.py", "--check"])
    prepare_main()


def test_context_tampering_is_not_silently_served(tmp_path: Path) -> None:
    catalog = Catalog(DEFAULT_CATALOG, DEFAULT_CATALOG.with_suffix(".sha256").read_text().strip())
    path = tmp_path / "context.json"
    path.write_bytes(CONTEXT_PATH.read_bytes())
    path.with_suffix(".sha256").write_text("0" * 64)
    assert ExplorerBundle(catalog, path).context is None


def test_explorer_requests_do_not_read_disk(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Request-time file read")

    monkeypatch.setattr(Path, "open", fail)
    assert client.get("/v1/exploration?valid_at=2026-10-30").status_code == 200


def test_openapi_explorer_contract_is_concrete(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/v1/exploration"]["get"]
    assert {"200", "404", "409", "422", "503"} <= set(operation["responses"])
