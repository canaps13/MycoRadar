"""Invented station/forecast/HTTP fixtures only; no provider requests run in CI."""

import base64
import csv
import gzip
import io
import json
import zlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from mycoradar import weather_http, weather_job
from mycoradar.weather import ForecastRequest, MFRequest, read_forecast, read_mf
from mycoradar.weather_http import (
    MAX_BODY,
    MET_ROOT,
    MF_ROOT,
    HTTPResult,
    Snapshot,
    WeatherClient,
    WeatherError,
    _SafeRedirect,
    bounded_gunzip,
    digest,
    valid_url,
)
from pydantic import ValidationError

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
URL = MF_ROOT + "Q_13_latest-2025-2026_RR-T-Vent.csv.gz"
MF = MFRequest(
    url=URL,
    station_id="13000001",
    start_day="2026-01-01",
    end_day="2026-10-30",
    resource_updated_at=NOW - timedelta(days=1),
)
FORECAST = ForecastRequest(
    provider="met-norway",
    public_reference=True,
    reference_id="synthetic-reference",
    latitude="1",
    longitude="2",
)


def mf_row(**changes: str) -> dict[str, str]:
    return {
        "NUM_POSTE": "13000001",
        "LAT": "1",
        "LON": "2",
        "AAAAMMJJ": "20261029",
        "RR": "0.0",
        "QRR": "1",
        "TM": "12.3",
        "QTM": "0",
        "NOM_USUEL": "PRIVATE_IGNORED_SENTINEL",
        **changes,
    }


def mf_snapshot(*rows: dict[str, str]) -> Snapshot:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(mf_row()), delimiter=";")
    writer.writeheader()
    writer.writerows(rows or [mf_row()])
    return Snapshot(URL, gzip.compress(stream.getvalue().encode()), NOW, NOW, {}, "test")


def forecast_document() -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [2, 1, 10]},
        "properties": {
            "meta": {
                "updated_at": "2026-10-31T10:17:00Z",
                "units": {
                    "air_temperature": "celsius",
                    "precipitation_amount": "mm",
                },
            },
            "timeseries": [
                {
                    "time": "2026-10-31T10:00:00Z",
                    "data": {
                        "instant": {"details": {"air_temperature": 12.5}},
                        "next_1_hours": {"details": {"precipitation_amount": 0}},
                        "next_6_hours": {"details": {"precipitation_amount": 42}},
                    },
                },
                {
                    "time": "2026-10-31T16:00:00Z",
                    "data": {
                        "instant": {"details": {"air_temperature": 8}},
                        "next_6_hours": {"details": {"precipitation_amount": 6}},
                    },
                },
                {"time": "2026-10-31T22:00:00Z", "data": {"instant": {"details": {}}}},
            ],
        },
    }


def forecast_snapshot(document: dict | None = None) -> Snapshot:
    return Snapshot(
        FORECAST.url(),
        json.dumps(document or forecast_document()).encode(),
        NOW,
        NOW,
        {"expires": format_datetime(NOW + timedelta(minutes=30))},
        "test",
    )


def test_mf_history_and_recent_are_observations_with_distinct_rainfall_interval() -> None:
    batch = read_mf(mf_snapshot(mf_row(), mf_row(AAAAMMJJ="20260101")), MF, NOW)
    assert batch.receipt["kind_counts"] == {"historical_observation": 2, "recent_observation": 2}
    rain = [r for r in batch.measurements if r.variable == "precipitation"][-1]
    assert rain.value == 0.0 and rain.accumulation_hours == 24
    assert rain.valid_at == "2026-10-29T06:00:00+00:00"
    assert rain.interval_end == "2026-10-30T06:00:00+00:00"
    temperature = batch.measurements[0]
    assert temperature.variable == "air_temperature_daily_mean"
    assert temperature.value == 12.3 and temperature.valid_at is None
    assert all(r.issued_at is None and r.effective_resolution_m is None for r in batch.measurements)
    assert "PRIVATE_IGNORED_SENTINEL" not in json.dumps(batch.receipt)


@pytest.mark.parametrize("value", ["", "NaN", "inf", "-1", "4000", "PRIVATE_VALUE"])
def test_missing_or_invalid_rain_never_becomes_zero(value: str) -> None:
    batch = read_mf(mf_snapshot(mf_row(RR=value)), MF, NOW)
    assert next(r for r in batch.measurements if r.variable == "precipitation").value is None


@pytest.mark.parametrize("code", ["2", "9", "", "unknown"])
def test_mf_unadmitted_quality_is_retained_and_value_withheld(code: str) -> None:
    row = next(
        r
        for r in read_mf(mf_snapshot(mf_row(QRR=code)), MF, NOW).measurements
        if r.variable == "precipitation"
    )
    assert row.value is None and row.provider_quality_code == code
    assert row.quality == "provider_quality_not_admitted"


def test_identical_mf_duplicates_are_counted_and_conflicting_copies_fail() -> None:
    batch = read_mf(mf_snapshot(mf_row(), mf_row()), MF, NOW)
    assert len(batch.measurements) == 2 and batch.receipt["duplicate_rows"] == 1
    with pytest.raises(WeatherError, match="observation_duplicate_conflict"):
        read_mf(mf_snapshot(mf_row(), mf_row(RR="2")), MF, NOW)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"AAAAMMJJ": "20260230"}, "observation_day_invalid"),
        ({"AAAAMMJJ": "20261031"}, "observation_day_incomplete"),
        ({"LAT": "nan"}, "station_coordinate_invalid"),
    ],
)
def test_mf_invalid_dates_and_coordinates_are_rejected(changes: dict, code: str) -> None:
    request = MF.model_copy(update={"end_day": NOW.date()})
    with pytest.raises(WeatherError, match=code):
        read_mf(mf_snapshot(mf_row(**changes)), request, NOW)


def test_rain_interval_not_complete_at_midnight_is_withheld() -> None:
    early = NOW.replace(hour=3)
    snapshot = replace(mf_snapshot(mf_row(AAAAMMJJ="20261030")), fetched_at=early, checked_at=early)
    rain = next(
        r for r in read_mf(snapshot, MF, early).measurements if r.variable == "precipitation"
    )
    assert rain.value is None and rain.quality == "interval_incomplete"


def test_missing_station_does_not_claim_complete_coverage() -> None:
    batch = read_mf(mf_snapshot(mf_row(NUM_POSTE="13000002")), MF, NOW)
    assert batch.receipt["coverage_status"] == "unavailable"
    assert batch.receipt["selected_days"] == 0


def test_forecast_update_is_not_issue_time_and_periods_are_not_added() -> None:
    batch = read_forecast(forecast_snapshot(), FORECAST, NOW)
    assert batch.receipt["issued_at"] is None and batch.receipt["lead_time_hours"] is None
    assert batch.receipt["forecast_updated_at"] == "2026-10-31T10:17:00+00:00"
    assert all(row.kind == "forecast" for row in batch.measurements)
    rain = [r for r in batch.measurements if r.variable == "precipitation"]
    assert [r.value for r in rain] == [0, 6, None]
    assert [r.accumulation_hours for r in rain] == [1, 6, None]
    assert rain[1].interval_end == "2026-10-31T22:00:00+00:00"
    assert batch.receipt["effective_resolution_m"] is None


@pytest.mark.parametrize("value", [True, "12", float("nan"), float("inf"), 10**400, {}])
def test_forecast_invalid_numeric_values_are_unknown(value: object) -> None:
    document = forecast_document()
    document["properties"]["timeseries"][0]["data"]["instant"]["details"]["air_temperature"] = value
    assert read_forecast(forecast_snapshot(document), FORECAST, NOW).measurements[0].value is None


@pytest.mark.parametrize(
    "change,code",
    [
        ("unit", "forecast_unit_mismatch"),
        ("geometry", "forecast_scope_mismatch"),
        ("time", "timestamp_invalid"),
        ("order", "forecast_order_invalid"),
        ("future_update", "forecast_update_in_future"),
    ],
)
def test_forecast_schema_conflicts_cannot_silently_map(change: str, code: str) -> None:
    document = forecast_document()
    if change == "unit":
        document["properties"]["meta"]["units"]["air_temperature"] = "kelvin"
    elif change == "geometry":
        document["geometry"]["coordinates"][0] = 3
    elif change == "time":
        document["properties"]["timeseries"][0]["time"] = "2026-10-31T10:00:00"
    elif change == "order":
        document["properties"]["timeseries"].reverse()
    else:
        document["properties"]["meta"]["updated_at"] = "2026-11-01T00:00:00Z"
    with pytest.raises(WeatherError, match=code):
        read_forecast(forecast_snapshot(document), FORECAST, NOW)


def test_same_content_and_classification_day_have_stable_version() -> None:
    a = read_forecast(forecast_snapshot(), FORECAST, NOW)
    b = read_forecast(
        replace(forecast_snapshot(), checked_at=NOW + timedelta(hours=1)),
        FORECAST,
        NOW + timedelta(hours=1),
    )
    assert a.receipt["batch_version"] == b.receipt["batch_version"]
    assert a.receipt["available_at"] == b.receipt["available_at"]
    assert b.receipt["http_cache_expired"] is True


class QueueTransport:
    def __init__(self, *results: HTTPResult) -> None:
        self.results = list(results)
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HTTPResult:
        self.requests.append((url, dict(headers)))
        return self.results.pop(0)


def test_persistent_cache_honors_expires_across_client_instances(tmp_path: Path) -> None:
    queue = QueueTransport(
        HTTPResult(200, b"body", {"Expires": format_datetime(NOW + timedelta(hours=3))})
    )
    first = WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    second = WeatherClient(tmp_path, transport=queue, now=lambda: NOW + timedelta(hours=2)).get(URL)
    assert first.body == second.body and second.cache_state == "local_cache"
    assert len(queue.requests) == 1
    assert queue.requests[0][1]["User-Agent"].startswith("MycoRadar/")
    assert queue.requests[0][1]["Accept-Encoding"] == "gzip, deflate"


def test_304_revalidates_exact_last_modified_without_renewing_first_availability(
    tmp_path: Path,
) -> None:
    modified = format_datetime(NOW - timedelta(days=1))
    queue = QueueTransport(
        HTTPResult(200, b"original", {"Last-Modified": modified}), HTTPResult(304, b"")
    )
    first = WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    later = NOW + timedelta(hours=2)
    second = WeatherClient(tmp_path, transport=queue, now=lambda: later).get(URL)
    assert second.fetched_at == first.fetched_at and second.checked_at == later
    assert second.body == b"original" and second.cache_state == "revalidated"
    assert queue.requests[1][1]["If-Modified-Since"] == modified


@pytest.mark.parametrize(
    "retry", ["7200", format_datetime(NOW + timedelta(hours=2)), "bad-deadline"]
)
def test_429_cooldown_survives_restarts_and_no_early_retry(tmp_path: Path, retry: str) -> None:
    queue = QueueTransport(HTTPResult(429, b"PRIVATE_ERROR", {"Retry-After": retry}))
    with pytest.raises(WeatherError, match="provider_throttled"):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    with pytest.raises(WeatherError, match="provider_cooldown"):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW + timedelta(minutes=90)).get(URL)
    assert len(queue.requests) == 1
    assert "PRIVATE_ERROR" not in next(tmp_path.glob("*.json")).read_text()


@pytest.mark.parametrize("status", [401, 403, 500, 503, 203, 304])
def test_failed_or_deprecated_provider_is_not_retried_immediately(
    tmp_path: Path, status: int
) -> None:
    queue = QueueTransport(HTTPResult(status, b"PRIVATE_ERROR"))
    with pytest.raises(WeatherError, match="provider_http_error"):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    with pytest.raises(WeatherError, match="provider_cooldown"):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    assert len(queue.requests) == 1


def test_failed_refresh_does_not_return_old_body_as_success(tmp_path: Path) -> None:
    queue = QueueTransport(HTTPResult(200, b"old"), HTTPResult(503, b""))
    WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    with pytest.raises(WeatherError):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW + timedelta(hours=2)).get(URL)
    with pytest.raises(WeatherError, match="provider_cooldown"):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW + timedelta(hours=2)).get(URL)


def test_cache_corruption_and_concurrent_job_fail_without_network(tmp_path: Path) -> None:
    queue = QueueTransport()
    path = tmp_path / (digest(URL.encode()) + ".json")
    path.write_text(
        json.dumps({"url": URL, "body": base64.b64encode(b"x").decode(), "sha256": "bad"})
    )
    with pytest.raises(WeatherError, match="cache_invalid"):
        WeatherClient(tmp_path, transport=queue).get(URL)
    (tmp_path / ".weather-lock").mkdir()
    with pytest.raises(WeatherError, match="cache_busy"):
        WeatherClient(tmp_path, transport=queue).get(URL)
    assert queue.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://api.met.no/weatherapi/locationforecast/2.0/compact?lat=1&lon=2",
        MET_ROOT + "?lat=91&lon=2",
        MET_ROOT + "?lat=1.12345&lon=2",
        MET_ROOT + "?lat=1&lon=2&private=sentinel",
        MET_ROOT + "?lat=1&lat=2&lon=2",
        "https://localhost/private",
        MF_ROOT + "../private.csv.gz",
    ],
)
def test_non_allowlisted_requests_never_reach_transport(tmp_path: Path, url: str) -> None:
    queue = QueueTransport()
    assert not valid_url(url)
    with pytest.raises(WeatherError, match="source_url_refused"):
        WeatherClient(tmp_path, transport=queue).get(url)
    assert queue.requests == []


def test_redirect_cannot_leave_https_provider_allowlist() -> None:
    with pytest.raises(WeatherError, match="redirect_refused"):
        _SafeRedirect().redirect_request(
            Request(URL), None, 302, "", {}, "http://localhost/private"
        )


def test_gzip_and_response_budgets_are_enforced(tmp_path: Path) -> None:
    with pytest.raises(WeatherError, match="decoded_budget_exceeded"):
        bounded_gunzip(gzip.compress(b"x" * 100), 10)
    with pytest.raises(WeatherError, match="gzip_invalid"):
        bounded_gunzip(b"not a gzip", 10)
    queue = QueueTransport(HTTPResult(200, b"x" * (MAX_BODY + 1)))
    with pytest.raises(WeatherError, match="response_budget_exceeded"):
        WeatherClient(tmp_path, transport=queue).get(URL)


def test_request_disallows_overseas_utc_assumption_and_private_reference() -> None:
    with pytest.raises(ValidationError):
        MFRequest.model_validate(
            {
                **MF.model_dump(),
                "url": MF_ROOT + "Q_971_latest-2025-2026_RR-T-Vent.csv.gz",
                "station_id": "97100001",
            }
        )
    with pytest.raises(ValidationError):
        ForecastRequest.model_validate({**FORECAST.model_dump(), "public_reference": False})


def test_cli_is_aggregate_only_and_missing_provider_is_explicit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    class FakeClock:
        @staticmethod
        def now(tz):
            return NOW

    class FakeClient:
        def __init__(self, cache):
            pass

        def get(self, url):
            return mf_snapshot()

    monkeypatch.setattr(weather_job, "WeatherClient", FakeClient)
    monkeypatch.setattr(weather_job, "datetime", FakeClock)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"mf": MF.model_dump(mode="json")}))
    assert weather_job.main(["--request", str(request), "--cache-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["forecast"] == {"status": "unavailable", "reason": "provider_not_selected"}
    assert result["observations"]["measurement_count"] == 2
    assert "PRIVATE_IGNORED_SENTINEL" not in output and '"measurements"' not in output


def test_cli_malformed_request_never_echoes_input(tmp_path: Path, capsys) -> None:
    path = tmp_path / "request.json"
    path.write_text('{"private": "PRIVATE_SENTINEL"}')
    assert weather_job.main(["--request", str(path), "--cache-dir", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert "PRIVATE_SENTINEL" not in output and "unavailable" in output


def test_all_missing_observations_and_expired_forecast_do_not_claim_availability() -> None:
    observations = read_mf(mf_snapshot(mf_row(RR="", TM="")), MF, NOW)
    assert observations.receipt["coverage_status"] == "unavailable"
    assert observations.receipt["usable_measurement_count"] == 0
    forecast = read_forecast(forecast_snapshot(), FORECAST, NOW + timedelta(days=1))
    assert forecast.receipt["future_step_count"] == 0
    assert forecast.receipt["coverage_status"] == "unavailable"
    assert forecast.receipt["http_cache_expired"] is True


@pytest.mark.parametrize("control", ['max-age="7200"', "public, max-age=7200"])
def test_cache_control_max_age_is_a_minimum_wait(tmp_path: Path, control: str) -> None:
    queue = QueueTransport(HTTPResult(200, b"data", {"Cache-Control": control}))
    WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    WeatherClient(tmp_path, transport=queue, now=lambda: NOW + timedelta(minutes=90)).get(URL)
    assert len(queue.requests) == 1


def test_no_store_does_not_save_response_body_or_headers(tmp_path: Path) -> None:
    queue = QueueTransport(HTTPResult(200, b"PRIVATE_NO_STORE", {"Cache-Control": "no-store"}))
    snapshot = WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    assert snapshot.body == b"PRIVATE_NO_STORE"
    stored = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert stored["body"] == "" and stored["headers"] == {}
    with pytest.raises(WeatherError, match="provider_cooldown"):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)


def test_no_cache_requires_revalidation_and_survives_304_without_repeated_directive(
    tmp_path: Path,
) -> None:
    queue = QueueTransport(
        HTTPResult(
            200, b"data", {"Cache-Control": "no-cache", "Last-Modified": format_datetime(NOW)}
        ),
        HTTPResult(304, b""),
    )
    WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    with pytest.raises(WeatherError, match="provider_revalidation_required"):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    later = NOW + timedelta(hours=2)
    assert WeatherClient(tmp_path, transport=queue, now=lambda: later).get(URL).body == b"data"
    with pytest.raises(WeatherError, match="provider_revalidation_required"):
        WeatherClient(tmp_path, transport=queue, now=lambda: later).get(URL)
    assert len(queue.requests) == 2


def test_recovery_after_429_uses_a_single_new_attempt_after_deadline(tmp_path: Path) -> None:
    queue = QueueTransport(
        HTTPResult(429, b"", {"Retry-After": "7200"}), HTTPResult(200, b"recovered")
    )
    with pytest.raises(WeatherError):
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    assert (
        WeatherClient(tmp_path, transport=queue, now=lambda: NOW + timedelta(hours=3)).get(URL).body
        == b"recovered"
    )
    assert len(queue.requests) == 2


def test_fetch_completion_not_start_defines_first_availability(tmp_path: Path) -> None:
    clock = iter([NOW, NOW + timedelta(seconds=5)])
    queue = QueueTransport(HTTPResult(200, b"data"))
    snapshot = WeatherClient(tmp_path, transport=queue, now=lambda: next(clock)).get(URL)
    assert snapshot.fetched_at == NOW + timedelta(seconds=5)


def test_future_last_modified_is_not_sent_to_provider(tmp_path: Path) -> None:
    queue = QueueTransport(
        HTTPResult(200, b"data", {"Last-Modified": format_datetime(NOW + timedelta(days=1))}),
        HTTPResult(200, b"updated"),
    )
    WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    WeatherClient(tmp_path, transport=queue, now=lambda: NOW + timedelta(hours=2)).get(URL)
    assert "If-Modified-Since" not in queue.requests[1][1]


def test_job_request_budget_and_bad_csv_headers_fail_closed(tmp_path: Path) -> None:
    client = WeatherClient(tmp_path, transport=QueueTransport())
    client.remaining = 0
    with pytest.raises(WeatherError, match="request_budget_exceeded"):
        client.get(URL)
    malformed = replace(mf_snapshot(), body=gzip.compress(b'"unfinished header'))
    with pytest.raises(WeatherError, match="csv_schema_invalid"):
        read_mf(malformed, MF, NOW)


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "identity"])
def test_real_fetch_path_decodes_supported_encodings_and_records_final_url(
    monkeypatch, encoding
) -> None:
    plain = b'{"synthetic":true}'
    encoded = (
        gzip.compress(plain)
        if encoding == "gzip"
        else zlib.compress(plain)
        if encoding == "deflate"
        else plain
    )

    class Response:
        status = 200
        headers = {"Content-Encoding": encoding}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return encoded[:limit]

        def geturl(self):
            return URL

    class Opener:
        def open(self, request, timeout):
            assert request.get_header("User-agent").startswith("MycoRadar/")
            assert timeout == 15
            return Response()

    monkeypatch.setattr(weather_http, "build_opener", lambda *args: Opener())
    result = weather_http.fetch(URL, {"User-Agent": weather_http.USER_AGENT})
    assert result.body == plain and result.headers["X-MycoRadar-Effective-URL"] == URL


def test_fetch_never_reads_an_error_document(monkeypatch) -> None:
    class Opener:
        def open(self, request, timeout):
            raise HTTPError(URL, 403, "PRIVATE_ERROR_SENTINEL", {"Retry-After": "3600"}, None)

    monkeypatch.setattr(weather_http, "build_opener", lambda *args: Opener())
    result = weather_http.fetch(URL, {})
    assert result.status == 403 and result.body == b""


def test_deflate_budget_and_invalid_stream_are_bounded() -> None:
    with pytest.raises(WeatherError, match="decoded_budget_exceeded"):
        weather_http.bounded_inflate(zlib.compress(b"x" * 100), 10)
    with pytest.raises(WeatherError, match="deflate_invalid"):
        weather_http.bounded_inflate(b"bad stream", 10)


def test_observation_calendar_uses_utc_even_for_an_offset_evaluation_clock() -> None:
    local = datetime(2026, 11, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    request = MF.model_copy(update={"end_day": local.astimezone(UTC).date()})
    with pytest.raises(WeatherError, match="observation_day_incomplete"):
        read_mf(mf_snapshot(mf_row(AAAAMMJJ="20261031")), request, local)


def test_naive_evaluation_time_fails_with_a_fixed_diagnostic() -> None:
    with pytest.raises(WeatherError, match="evaluation_time_invalid"):
        read_forecast(forecast_snapshot(), FORECAST, NOW.replace(tzinfo=None))


def test_identical_200_response_does_not_make_an_old_version_new(tmp_path: Path) -> None:
    queue = QueueTransport(HTTPResult(200, b"same"), HTTPResult(200, b"same"))
    first = WeatherClient(tmp_path, transport=queue, now=lambda: NOW).get(URL)
    later = NOW + timedelta(hours=2)
    second = WeatherClient(tmp_path, transport=queue, now=lambda: later).get(URL)
    assert second.fetched_at == first.fetched_at
    assert second.checked_at == later and digest(second.body) == digest(first.body)
