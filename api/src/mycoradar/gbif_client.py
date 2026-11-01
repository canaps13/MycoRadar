"""Bounded GET-only GBIF transport for offline jobs; errors never contain provider data."""

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://api.gbif.org/v1/"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class GBIFError(Exception):
    """Fixed diagnostic code only, without URLs, arguments or response bodies."""


@dataclass(frozen=True, repr=False)
class HTTPResult:
    status: int
    body: bytes
    retry_after: str | None = None


class Transport(Protocol):
    def __call__(self, url: str, timeout: float) -> HTTPResult: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def fetch(url: str, timeout: float) -> HTTPResult:
    request = Request(
        url,
        headers={
            "User-Agent": "MycoRadar/0.1 (+https://github.com/canaps13/MycoRadar)",
            "Accept": "application/json",
        },
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise GBIFError("response_budget_exceeded")
            return HTTPResult(response.status, body)
    except HTTPError as error:
        # Never read or echo an error document (it may reflect a private upstream value).
        return HTTPResult(error.code, b"", error.headers.get("Retry-After"))
    except (URLError, OSError, TimeoutError):
        raise GBIFError("provider_unreachable") from None


def _backoff(value: str | None, attempt: int, now: datetime) -> float:
    if value is None:
        return float(2**attempt)
    try:
        delay = (
            float(value)
            if value.isascii() and value.isdigit()
            else (parsedate_to_datetime(value) - now).total_seconds()
        )
    except (ValueError, TypeError, OverflowError):
        raise GBIFError("provider_backoff_required") from None
    # Do not retry earlier than requested, nor block this sample job for a long interval.
    if not 0 <= delay <= 10:
        raise GBIFError("provider_backoff_required")
    return delay


class GBIFClient:
    def __init__(
        self,
        transport: Transport = fetch,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport, self._sleep, self._clock = transport, sleep, monotonic
        self._deadline = monotonic() + 180
        self._remaining_requests = 80

    def get(self, path: str, params: Mapping[str, str | int] | None = None) -> bytes:
        # Callers only build these paths from validated UUIDs and fixed service names.
        if path not in {"species/match", "occurrence/search"} and not (
            path.startswith("dataset/")
            and len(path) == 44
            and all(c in "0123456789abcdef-" for c in path[8:])
        ):
            raise GBIFError("invalid_service_path")
        url = BASE_URL + path + ("?" + urlencode(params) if params else "")
        for attempt in range(3):
            remaining = self._deadline - self._clock()
            if remaining <= 0 or self._remaining_requests <= 0:
                raise GBIFError("request_budget_exceeded")
            self._remaining_requests -= 1
            try:
                result = self._transport(url, min(10.0, remaining))
            except GBIFError as error:
                if str(error) != "provider_unreachable" or attempt == 2:
                    raise
                result = HTTPResult(503, b"")
            if len(result.body) > MAX_RESPONSE_BYTES:
                raise GBIFError("response_budget_exceeded")
            if result.status == 200:
                return result.body
            if result.status not in {429, 500, 502, 503, 504} or attempt == 2:
                raise GBIFError("provider_http_error")
            delay = _backoff(result.retry_after, attempt, datetime.now(UTC))
            if delay >= self._deadline - self._clock():
                raise GBIFError("request_budget_exceeded")
            self._sleep(delay)
        raise GBIFError("provider_http_error")


def object_json(content: bytes) -> dict[str, object]:
    try:
        value = json.loads(content)
    except (ValueError, UnicodeError, RecursionError):
        raise GBIFError("provider_json_invalid") from None
    if not isinstance(value, dict):
        raise GBIFError("provider_json_invalid")
    return cast(dict[str, object], value)
