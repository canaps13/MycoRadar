"""Conditional requests against the real admitted catalogue, plus synthetic version changes."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from mycoradar.catalog import DEFAULT_CATALOG, Catalog
from mycoradar.http_cache import CACHE_POLICY, not_modified
from mycoradar.main import app

TAG = '"' + "a" * 64 + '"'


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, False),
        ("", False),
        ("*", True),
        (" \t* \t", True),
        (TAG, True),
        ("W/" + TAG, True),
        ('"other", W/' + TAG, True),
        ('"other,tag", ' + TAG, True),
        ('"other,tag", W/' + TAG + "\t", True),
        ('"*"', False),
        ('"other"', False),
        ("w/" + TAG, False),
        (TAG.upper(), False),
        (TAG + ",", False),
        ("*," + TAG, False),
        ('"unclosed,' + TAG, False),
        (TAG + " invalid", False),
        (",".join([TAG] * 33), False),
        ('"' + "a" * 4096 + '"', False),
    ],
)
def test_bounded_entity_tag_lists_and_weak_comparison(header, expected):
    assert not_modified(header, "W/" + TAG) is expected


@pytest.mark.parametrize(
    "path", ["/v1/regions", "/v1/metadata", "/v1/species", "/v1/cells?region_id=FR-83"]
)
def test_real_route_revalidation_is_bodyless_without_claiming_data_freshness(path):
    with TestClient(app) as client:
        first = client.get(path)
        assert first.status_code == 200
        tag = first.headers["etag"]
        assert tag == f'W/"{hashlib.sha256(first.content).hexdigest()}"'
        assert first.headers["cache-control"] == CACHE_POLICY
        second = client.get(path, headers={"If-None-Match": tag})
        assert second.status_code == 304 and second.content == b""
        assert second.headers["etag"] == tag
        assert second.headers["cache-control"] == CACHE_POLICY
        assert "content-type" not in second.headers and "last-modified" not in second.headers
        assert first.json()["published_at"] == "2026-10-30T07:20:45Z"


def test_changed_filters_and_pagination_do_not_reuse_a_different_representation():
    with TestClient(app) as client:
        original = client.get("/v1/regions?limit=1&offset=0")
        tag = original.headers["etag"]
        for query in ("limit=1&offset=1", "region_id=FR-83", "country=ES"):
            changed = client.get("/v1/regions?" + query, headers={"If-None-Match": tag})
            assert changed.status_code == 200 and changed.headers["etag"] != tag


@pytest.mark.parametrize(
    "query,status",
    [
        ("limit=0", 422),
        ("extra=PRIVATE", 422),
        ("region_id=not-found", 404),
        ("catalog_version=" + "0" * 64, 409),
        ("bbox=nan,43,6,44", 422),
    ],
)
def test_preconditions_never_bypass_query_or_version_errors(query, status):
    with TestClient(app) as client:
        response = client.get("/v1/regions?" + query, headers={"If-None-Match": "*"})
        assert response.status_code == status
        assert response.headers["cache-control"] == "no-store"
        assert "etag" not in response.headers
        assert "PRIVATE" not in response.text


def test_backend_unavailable_is_503_even_with_a_previously_valid_tag():
    with TestClient(app) as client:
        tag = client.get("/v1/regions").headers["etag"]
        app.state.catalog = None
        response = client.get("/v1/regions", headers={"If-None-Match": tag})
        assert (
            response.status_code == 503
            and response.json()["error"]["code"] == "catalog_unavailable"
        )
        assert response.headers["cache-control"] == "no-store" and "etag" not in response.headers


def test_new_catalogue_version_invalidates_tag_without_changing_source_age(tmp_path):
    with TestClient(app) as client:
        first = client.get("/v1/metadata")
        data = json.loads(DEFAULT_CATALOG.read_bytes())
        # A synthetic publication timestamp, not an update of the IGN observations/source.
        data["published_at"] = "2026-11-02T00:00:00Z"
        path = tmp_path / "changed.json"
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        app.state.catalog = Catalog(path, hashlib.sha256(raw).hexdigest())
        second = client.get("/v1/metadata", headers={"If-None-Match": first.headers["etag"]})
        assert second.status_code == 200 and second.headers["etag"] != first.headers["etag"]
        assert second.json()["items"] == first.json()["items"]
        assert second.json()["items"][0]["source_published_at"] is None
        assert second.json()["items"][0]["effective_resolution_m"] is None


def test_client_clock_is_not_used_as_source_freshness():
    with TestClient(app) as client:
        original = client.get("/v1/metadata")
        response = client.get(
            "/v1/metadata",
            headers={
                "If-None-Match": '"different"',
                "If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT",
            },
        )
        assert response.status_code == 200 and response.content == original.content
        assert response.headers["etag"] == original.headers["etag"]


def test_repeated_headers_and_malformed_or_oversized_lists_are_safe():
    with TestClient(app) as client:
        tag = client.get("/v1/regions").headers["etag"]
        assert (
            client.get(
                "/v1/regions", headers=[("If-None-Match", '"other"'), ("If-None-Match", tag)]
            ).status_code
            == 304
        )
        for header in (tag + ",invalid", '"' + "a" * 4096 + '"', ",".join([tag] * 33)):
            assert client.get("/v1/regions", headers={"If-None-Match": header}).status_code == 200


def test_cache_contract_is_documented_but_does_not_apply_to_liveness():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        for route in ("regions", "metadata", "species", "cells"):
            operation = schema["paths"][f"/v1/{route}"]["get"]
            assert any(
                p["name"] == "If-None-Match" and p["in"] == "header"
                for p in operation["parameters"]
            )
            assert "ETag" in operation["responses"]["200"]["headers"]
            assert "content" not in operation["responses"]["304"]
        response = client.get("/health", headers={"If-None-Match": "*"})
        assert response.status_code == 200 and "etag" not in response.headers
