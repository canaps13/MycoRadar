"""Read-only smoke checks against the real local stack (no simulated predictions)."""

import argparse
import json
from urllib.request import urlopen


def check_stack(api_url: str, web_url: str) -> None:
    expected_health = {"status": "ok", "service": "mycoradar-api"}
    for url, expected in [
        (f"{api_url}/health", expected_health),
        (f"{api_url}/ready", {"status": "ok", "database": "ready"}),
        (f"{web_url}/api/health", expected_health),
        (f"{web_url}/api/ready", {"status": "ok", "database": "ready"}),
    ]:
        with urlopen(url, timeout=10) as response:
            if response.status != 200 or json.load(response) != expected:
                raise RuntimeError("Unexpected API or proxy response")
    with urlopen(web_url, timeout=10) as response:
        if response.status != 200 or "MycoRadar" not in response.read().decode("utf-8"):
            raise RuntimeError("MycoRadar page unavailable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:18000")
    parser.add_argument("--web-url", default="http://127.0.0.1:15173")
    args = parser.parse_args()
    check_stack(args.api_url.rstrip("/"), args.web_url.rstrip("/"))
    print("Local stack verified: HTTP, PostGIS readiness, schema, web and proxy.")


if __name__ == "__main__":
    main()
