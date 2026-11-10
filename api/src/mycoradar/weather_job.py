"""Read bounded weather samples outside HTTP; emit aggregate provenance only."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Never, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from mycoradar.weather import ForecastRequest, MFRequest, read_forecast, read_mf
from mycoradar.weather_http import WeatherClient, WeatherError


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    mf: MFRequest | None = None
    forecast: ForecastRequest | None = None

    @model_validator(mode="after")
    def not_empty(self) -> Self:
        if self.mf is None and self.forecast is None:
            raise ValueError("at least one explicit provider required")
        return self


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise WeatherError("arguments_invalid")


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        with args.request.open("rb") as stream:
            content = stream.read(64 * 1024 + 1)
        if len(content) > 64 * 1024:
            raise WeatherError("request_budget_exceeded")
        request = JobRequest.model_validate_json(content)
        client = WeatherClient(args.cache_dir)
        now = datetime.now(UTC)
        output: dict[str, object] = {"schema_version": "weather-job-v1", "status": "partial"}
        available = 0
        for name, selection in (("observations", request.mf), ("forecast", request.forecast)):
            if selection is None:
                output[name] = {"status": "unavailable", "reason": "provider_not_selected"}
                continue
            try:
                url = selection.url if isinstance(selection, MFRequest) else selection.url()
                snapshot = client.get(url)
                # Evaluation happens after the fetch; never backdate first availability.
                now = datetime.now(UTC)
                batch = (
                    read_mf(snapshot, selection, now)
                    if isinstance(selection, MFRequest)
                    else read_forecast(snapshot, selection, now)
                )
                output[name] = batch.receipt
                available += batch.receipt["coverage_status"] != "unavailable"
            except WeatherError as error:
                output[name] = {"status": "unavailable", "reason": str(error)}
        if available == 0:
            output["status"] = "unavailable"
        print(json.dumps(output, ensure_ascii=True, sort_keys=True))
        return 0 if available else 2
    except (OSError, ValueError, ValidationError, WeatherError):
        print(json.dumps({"status": "unavailable", "reason": "weather_request_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
