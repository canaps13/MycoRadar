"""Offline image smoke using invented HTTP responses and a temporary operator cache."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from mycoradar.weather_http import MF_ROOT, HTTPResult, WeatherClient


def main() -> None:
    start = datetime(2000, 1, 1, tzinfo=UTC)
    calls: list[Mapping[str, str]] = []

    def transport(url: str, headers: Mapping[str, str]) -> HTTPResult:
        calls.append(dict(headers))
        if len(calls) == 1:
            return HTTPResult(200, b"invented image smoke only", {"ETag": 'W/"synthetic-v1"'})
        if len(calls) == 2 and headers.get("If-None-Match") == 'W/"synthetic-v1"':
            return HTTPResult(304, b"")
        raise RuntimeError("Unexpected weather smoke request")

    url = MF_ROOT + "Q_13_latest-2025-2026_RR-T-Vent.csv.gz"
    with TemporaryDirectory() as folder:
        cache = Path(folder)
        first = WeatherClient(cache, transport=transport, now=lambda: start).get(url)
        later = start + timedelta(hours=2)
        checked = WeatherClient(cache, transport=transport, now=lambda: later).get(url)
        cached = WeatherClient(cache, transport=transport, now=lambda: later).get(url)
        if (
            len(calls) != 2
            or first.body != checked.body
            or checked.body != cached.body
            or checked.fetched_at != start
            or cached.fetched_at != start
            or checked.checked_at != later
            or checked.cache_state != "revalidated"
            or cached.cache_state != "local_cache"
        ):
            raise RuntimeError("Weather cache invariant failed")
    print(
        "Weather ETag cache verified: two transports, stable first collection, "
        "persisted revalidation."
    )


if __name__ == "__main__":
    main()
