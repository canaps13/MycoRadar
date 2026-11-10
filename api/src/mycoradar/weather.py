"""Station observations and model forecasts stay separate; no interpolation or scoring."""

import csv
import io
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal, Self
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mycoradar.weather_http import (
    MET_ROOT,
    MF_ROOT,
    Snapshot,
    WeatherError,
    bounded_gunzip,
    digest,
    http_time,
    timestamp,
    valid_url,
)


class MFRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    url: str
    station_id: Annotated[str, Field(pattern=r"^\d{8}$")]
    start_day: date
    end_day: date
    resource_updated_at: datetime

    @model_validator(mode="after")
    def scope(self) -> Self:
        if not self.url.startswith(MF_ROOT) or not valid_url(self.url):
            raise ValueError("MF file URL required")
        department = self.url.removeprefix(MF_ROOT).split("_")[1]
        # Overseas FU time conventions need their own reviewed adapter; never assume UTC there.
        metropolitan = {f"{n:02d}" for n in range(1, 96)} - {"20"} | {"2A", "2B"}
        if department not in metropolitan or not self.station_id.startswith(
            "20" if department in {"2A", "2B"} else department
        ):
            raise ValueError("metropolitan station/file scope required")
        if (
            self.end_day < self.start_day
            or (self.end_day - self.start_day).days > 1095
            or self.resource_updated_at.tzinfo is None
        ):
            raise ValueError("bounded date range and aware metadata date required")
        return self


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    provider: Literal["met-norway"]
    public_reference: Literal[True]
    reference_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,60}$")]
    latitude: Annotated[str, Field(pattern=r"^-?\d{1,2}(?:\.\d{1,4})?$")]
    longitude: Annotated[str, Field(pattern=r"^-?\d{1,3}(?:\.\d{1,4})?$")]

    def url(self) -> str:
        result = MET_ROOT + "?" + urlencode({"lat": self.latitude, "lon": self.longitude})
        if not valid_url(result):
            raise WeatherError("reference_coordinate_invalid")
        return result


@dataclass(frozen=True)
class Measurement:
    kind: str
    location_id: str
    support: str
    variable: str
    value: float | None
    unit: str
    quality: str
    observed_day: str | None = None
    valid_at: str | None = None
    interval_end: str | None = None
    accumulation_hours: int | None = None
    provider_quality_code: str | None = None
    forecast_updated_at: str | None = None
    issued_at: None = None
    lead_time_hours: None = None
    effective_resolution_m: None = None


@dataclass(frozen=True)
class WeatherBatch:
    receipt: dict[str, object]
    measurements: tuple[Measurement, ...] = field(repr=False)


def _number(
    value: object, lower: float, upper: float, *, allow_text: bool = False
) -> tuple[float | None, str]:
    if value is None or value == "":
        return None, "missing"
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int, float))
        or (isinstance(value, str) and not allow_text)
    ):
        return None, "invalid"
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None, "invalid"
    if not math.isfinite(result) or not lower <= result <= upper:
        return None, "invalid"
    return result, "usable"


def _evaluation(snapshot: Snapshot, now: datetime) -> datetime:
    if (
        now.tzinfo is None
        or snapshot.fetched_at.tzinfo is None
        or snapshot.checked_at.tzinfo is None
        or not snapshot.fetched_at <= snapshot.checked_at <= now
    ):
        raise WeatherError("evaluation_time_invalid")
    return now.astimezone(UTC)


def _receipt(
    snapshot: Snapshot,
    request: BaseModel,
    rows: list[Measurement],
    now: datetime,
    provider: str,
    license_id: str,
    attribution: str,
) -> dict[str, object]:
    now = _evaluation(snapshot, now)
    version = digest(
        json.dumps(
            {
                "adapter": "weather-sample-v1",
                "sha256": digest(snapshot.body),
                "request": request.model_dump(mode="json"),
                "classification_day": now.date().isoformat(),
            },
            sort_keys=True,
        ).encode()
    )
    expires = http_time(snapshot.headers.get("expires"))
    return {
        "schema_version": "weather-sample-v1",
        "adapter_version": "weather-sample-v1",
        "batch_version": version,
        "provider": provider,
        "license": license_id,
        "license_url": (
            "https://github.com/etalab/licence-ouverte/blob/master/LO.md"
            if license_id == "Etalab-2.0"
            else "https://creativecommons.org/licenses/by/4.0/"
        ),
        "attribution": attribution,
        "source": snapshot.provenance(),
        "request": request.model_dump(mode="json"),
        "evaluated_at": now.isoformat(),
        "classification_reference_day": now.date().isoformat(),
        "available_at": snapshot.fetched_at.isoformat(),
        "availability_semantics": "first local retrieval, not historical availability",
        "http_cache_expired": now > expires if expires is not None else None,
        "coverage_status": "partial" if any(r.value is not None for r in rows) else "unavailable",
        "measurement_count": len(rows),
        "usable_measurement_count": sum(r.value is not None for r in rows),
        "kind_counts": dict(sorted(Counter(row.kind for row in rows).items())),
        "kind_status": {
            kind: "partial"
            if any(r.kind == kind and r.value is not None for r in rows)
            else "unavailable"
            for kind in (
                ("historical_observation", "recent_observation")
                if provider == "meteo-france-daily"
                else ("forecast",)
            )
        },
        "quality_counts": dict(sorted(Counter(row.quality for row in rows).items())),
        "effective_resolution_m": None,
        "raw_records_persisted_in_git": False,
        "public_measurements_added": 0,
    }


def read_mf(snapshot: Snapshot, request: MFRequest, now: datetime) -> WeatherBatch:
    now = _evaluation(snapshot, now)
    if snapshot.url != request.url or request.resource_updated_at > snapshot.fetched_at:
        raise WeatherError("source_metadata_mismatch")
    try:
        text = bounded_gunzip(snapshot.body, 32 * 1024 * 1024).decode("utf-8-sig")
    except UnicodeError:
        raise WeatherError("csv_encoding_invalid") from None
    reader = csv.DictReader(io.StringIO(text), delimiter=";", strict=True)
    required = {"NUM_POSTE", "AAAAMMJJ", "LAT", "LON", "RR", "QRR", "TM", "QTM"}
    try:
        fields = reader.fieldnames
    except csv.Error:
        raise WeatherError("csv_schema_invalid") from None
    if fields is None or len(fields) != len(set(fields)) or not required.issubset(fields):
        raise WeatherError("csv_schema_invalid")
    selected: dict[str, tuple[str, ...]] = {}
    rows: list[Measurement] = []
    scanned = duplicates = 0
    try:
        for record in reader:
            scanned += 1
            if scanned > 200000:
                raise WeatherError("row_budget_exceeded")
            if None in record or any(value is None for value in record.values()):
                raise WeatherError("csv_schema_invalid")
            if record["NUM_POSTE"] != request.station_id:
                continue
            if not re.fullmatch(r"\d{8}", record["AAAAMMJJ"]):
                raise WeatherError("observation_day_invalid")
            try:
                day = datetime.strptime(record["AAAAMMJJ"], "%Y%m%d").date()
            except ValueError:
                raise WeatherError("observation_day_invalid") from None
            if not request.start_day <= day <= request.end_day:
                continue
            if day >= now.date():
                raise WeatherError("observation_day_incomplete")
            if any(
                _number(record[key], low, high, allow_text=True)[0] is None
                for key, low, high in (("LAT", -90, 90), ("LON", -180, 180))
            ):
                raise WeatherError("station_coordinate_invalid")
            values = tuple(record[key] for key in sorted(required))
            if day.isoformat() in selected:
                if selected[day.isoformat()] != values:
                    raise WeatherError("observation_duplicate_conflict")
                duplicates += 1
                continue
            selected[day.isoformat()] = values
            kind = (
                "recent_observation" if (now.date() - day).days <= 7 else "historical_observation"
            )
            for column, variable, unit, low, high in (
                ("RR", "precipitation", "mm", 0, 3000),
                ("TM", "air_temperature_daily_mean", "celsius", -100, 70),
            ):
                value, quality = _number(record[column], low, high, allow_text=True)
                code = record["Q" + column]
                if code not in {"0", "1"}:
                    value, quality = None, "provider_quality_not_admitted"
                start = datetime.combine(day, time(6), UTC) if column == "RR" else None
                end = start + timedelta(days=1) if start else None
                if end is not None and end > now:
                    value, quality = None, "interval_incomplete"
                rows.append(
                    Measurement(
                        kind,
                        "mf-station:" + request.station_id,
                        "station",
                        variable,
                        value,
                        unit,
                        quality,
                        observed_day=day.isoformat(),
                        valid_at=start.isoformat() if start else None,
                        interval_end=end.isoformat() if end else None,
                        accumulation_hours=24 if start else None,
                        provider_quality_code=code,
                    )
                )
    except csv.Error:
        raise WeatherError("csv_invalid") from None
    rows.sort(key=lambda row: (row.observed_day or "", row.variable))
    receipt = _receipt(
        snapshot,
        request,
        rows,
        now,
        "meteo-france-daily",
        "Etalab-2.0",
        "Meteo-France - daily climatological observations; source URL and resource update retained",
    )
    receipt.update(
        scanned_rows=scanned,
        selected_days=len(selected),
        duplicate_rows=duplicates,
        missing_days=(request.end_day - request.start_day).days + 1 - len(selected),
        source_resource_updated_at=request.resource_updated_at.isoformat(),
        observed_day_min=min(selected) if selected else None,
        observed_day_max=max(selected) if selected else None,
        recency_rule="last seven calendar days relative to evaluated_at, not a freshness guarantee",
        rainfall_interval="06:00 UTC J to 06:00 UTC J+1; assigned to J; metropolitan only",
        daily_temperature_interval="daily mean of hourly temperatures; exact bounds not asserted",
        transformation="RR/TM decimal units unchanged; quality 0/1 only; no spatial interpolation",
        catalog_url="https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes",
        fully_usable_day_count=sum(
            count == 2
            for count in Counter(row.observed_day for row in rows if row.value is not None).values()
        ),
    )
    return WeatherBatch(receipt, tuple(rows))


def read_forecast(snapshot: Snapshot, request: ForecastRequest, now: datetime) -> WeatherBatch:
    now = _evaluation(snapshot, now)
    if snapshot.url != request.url():
        raise WeatherError("forecast_scope_mismatch")
    try:
        raw = json.loads(snapshot.body)
        coordinates = raw["geometry"]["coordinates"]
        if (
            raw.get("type") != "Feature"
            or raw["geometry"].get("type") != "Point"
            or not isinstance(coordinates, list)
            or len(coordinates) not in {2, 3}
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in coordinates)
            or not all(math.isfinite(v) for v in coordinates)
            or abs(coordinates[0] - float(request.longitude)) > 0.0001
            or abs(coordinates[1] - float(request.latitude)) > 0.0001
        ):
            raise WeatherError("forecast_scope_mismatch")
        meta = raw["properties"]["meta"]
        if (
            meta["units"]["air_temperature"] != "celsius"
            or meta["units"]["precipitation_amount"] != "mm"
        ):
            raise WeatherError("forecast_unit_mismatch")
        updated = timestamp(meta["updated_at"])
        if updated > snapshot.fetched_at:
            raise WeatherError("forecast_update_in_future")
        series = raw["properties"]["timeseries"]
        if not isinstance(series, list) or len(series) > 500:
            raise WeatherError("forecast_series_invalid")
        rows: list[Measurement] = []
        previous: datetime | None = None
        for step in series:
            valid = timestamp(step["time"])
            if previous is not None and valid <= previous:
                raise WeatherError("forecast_order_invalid")
            previous = valid
            data = step["data"]
            temperature = data.get("instant", {}).get("details", {}).get("air_temperature")
            value, quality = _number(temperature, -100, 70)
            rows.append(
                Measurement(
                    "forecast",
                    request.reference_id,
                    "model_point",
                    "air_temperature",
                    value,
                    "celsius",
                    quality,
                    valid_at=valid.isoformat(),
                    forecast_updated_at=updated.isoformat(),
                )
            )
            hours = next((h for h in (1, 6) if f"next_{h}_hours" in data), None)
            precipitation = (
                data[f"next_{hours}_hours"].get("details", {}).get("precipitation_amount")
                if hours
                else None
            )
            value, quality = _number(precipitation, 0, 3000)
            rows.append(
                Measurement(
                    "forecast",
                    request.reference_id,
                    "model_point",
                    "precipitation",
                    value,
                    "mm",
                    quality,
                    valid_at=valid.isoformat(),
                    interval_end=(valid + timedelta(hours=hours)).isoformat() if hours else None,
                    accumulation_hours=hours,
                    forecast_updated_at=updated.isoformat(),
                )
            )
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        OverflowError,
        RecursionError,
    ):
        raise WeatherError("forecast_schema_invalid") from None
    receipt = _receipt(
        snapshot,
        request,
        rows,
        now,
        "met-norway-locationforecast",
        "CC-BY-4.0",
        "Data from MET Norway; normalized temperature and precipitation, no icons",
    )
    receipt.update(
        forecast_updated_at=updated.isoformat(),
        issued_at=None,
        lead_time_hours=None,
        issue_time_semantics="product update is not model issuance; backtesting not admitted",
        valid_at_min=series[0]["time"] if series else None,
        valid_at_max=series[-1]["time"] if series else None,
        nominal_model_resolution_m=None,
        source_model_resolution_note="regional models; per-record resolution not supplied",
        transformation="instant temperature; next 1h else 6h rain; no summation/disaggregation",
        normalized_content_sha256=digest(
            json.dumps([asdict(row) for row in rows], sort_keys=True).encode()
        ),
    )
    receipt["future_step_count"] = sum(timestamp(step["time"]) > now for step in series)
    if not any(
        row.value is not None and row.valid_at is not None and timestamp(row.valid_at) > now
        for row in rows
    ):
        receipt["coverage_status"] = "unavailable"
        receipt["kind_status"] = {"forecast": "unavailable"}
    return WeatherBatch(receipt, tuple(rows))
