"""Verify real HTTP conditional requests on the API and frontend proxy."""

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def check_endpoint(base: str) -> None:
    url = base.rstrip("/") + "/v1/regions?country=FR&limit=1"
    with urlopen(url, timeout=10) as response:
        assert response.status == 200
        tag = response.headers["ETag"]
        assert tag and tag.startswith('W/"')
        assert response.headers["Cache-Control"] == "private, no-cache"
        body = json.load(response)
        assert body["items"][0]["id"] == "FR-13"
        assert body["items"][0]["geometry"]["type"] == "MultiPolygon"
    try:
        with urlopen(Request(url, headers={"If-None-Match": tag}), timeout=10):
            raise AssertionError("Expected 304")
    except HTTPError as response:
        assert response.code == 304 and response.read() == b""
        assert response.headers["ETag"] == tag
        assert response.headers["Cache-Control"] == "private, no-cache"
    for query, expected in (
        ("limit=0", 422),
        ("catalog_version=" + "0" * 64, 409),
        ("region_id=not-found", 404),
    ):
        try:
            with urlopen(
                Request(base + "/v1/regions?" + query, headers={"If-None-Match": "*"}), timeout=10
            ):
                raise AssertionError("Expected typed error")
        except HTTPError as response:
            assert response.code == expected
            assert response.headers["Cache-Control"] == "no-store" and not response.headers["ETag"]
            assert "error" in json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:18000")
    parser.add_argument("--web-url", default="http://127.0.0.1:15173")
    args = parser.parse_args()
    check_endpoint(args.api_url.rstrip("/"))
    check_endpoint(args.web_url.rstrip("/") + "/api")
    print(
        json.dumps(
            {
                "scope": "real_catalogue_cache_smoke",
                "surfaces": ["API", "web_proxy"],
                "conditional_304_verified": True,
                "errors_remain_no_store": True,
                "shared_cdn_cache_enabled": False,
            }
        )
    )


if __name__ == "__main__":
    main()
