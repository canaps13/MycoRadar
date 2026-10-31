"""Bounded offline weather retrieval with persistent cache and provider cooldowns."""

import base64
import gzip
import hashlib
import io
import json
import os
import re
import tempfile
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BODY = 8 * 1024 * 1024
MF_ROOT = "https://meteofrance.s3.sbg.io.cloud.ovh.net/data/synchro_ftp/BASE/QUOT/"
MET_ROOT = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
USER_AGENT = "MycoRadar/0.1 (+https://github.com/canaps13/MycoRadar)"


class WeatherError(Exception):
    """Fixed diagnostic codes only; no arguments, coordinates or provider documents."""


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise WeatherError("timestamp_invalid")
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except ValueError:
        raise WeatherError("timestamp_invalid") from None


def http_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        result = parsedate_to_datetime(value)
        return result.astimezone(UTC) if result.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def bounded_gunzip(body: bytes, limit: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            value = stream.read(limit + 1)
    except (OSError, EOFError, zlib.error):
        raise WeatherError("gzip_invalid") from None
    if len(value) > limit:
        raise WeatherError("decoded_budget_exceeded")
    return value


def bounded_inflate(body: bytes, limit: int) -> bytes:
    try:
        decoder = zlib.decompressobj()
        value = decoder.decompress(body, limit + 1)
        if len(value) > limit or decoder.unconsumed_tail:
            raise WeatherError("decoded_budget_exceeded")
        if not decoder.eof or decoder.unused_data:
            raise WeatherError("deflate_invalid")
        return value
    except zlib.error:
        raise WeatherError("deflate_invalid") from None


def valid_url(url: str) -> bool:
    if re.fullmatch(
        re.escape(MF_ROOT)
        + r"Q_(?:\d{2,3}|2[AB])_(?:latest-\d{4}-\d{4}|previous-\d{4}-\d{4}|avant-1949)"
        + r"_RR-T-Vent\.csv\.gz",
        url,
    ):
        return True
    parts = urlsplit(url)
    if url.split("?", 1)[0] != MET_ROOT or parts.fragment:
        return False
    query = parse_qs(parts.query, keep_blank_values=True)
    if set(query) != {"lat", "lon"}:
        return False
    for key, bound in (("lat", 90), ("lon", 180)):
        values = query[key]
        if len(values) != 1 or not re.fullmatch(r"-?\d{1,3}(?:\.\d{1,4})?", values[0]):
            return False
        if not -bound <= float(values[0]) <= bound:
            return False
    return True


@dataclass(frozen=True, repr=False)
class HTTPResult:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def __call__(self, url: str, headers: Mapping[str, str]) -> HTTPResult: ...


class _SafeRedirect(HTTPRedirectHandler):
    max_redirections = 2
    max_repeats = 1

    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> Request | None:
        if not valid_url(newurl) or urlsplit(req.full_url).netloc != urlsplit(newurl).netloc:
            raise WeatherError("redirect_refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def fetch(url: str, headers: Mapping[str, str]) -> HTTPResult:
    try:
        request = Request(url, headers=dict(headers))
        with build_opener(_SafeRedirect()).open(request, timeout=15) as response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise WeatherError("response_budget_exceeded")
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding == "gzip":
                body = bounded_gunzip(body, MAX_BODY)
            elif encoding == "deflate":
                body = bounded_inflate(body, MAX_BODY)
            elif encoding != "identity":
                raise WeatherError("encoding_unsupported")
            return HTTPResult(
                response.status,
                body,
                {**dict(response.headers), "X-MycoRadar-Effective-URL": response.geturl()},
            )
    except HTTPError as error:
        return HTTPResult(error.code, b"", dict(error.headers))
    except (URLError, OSError, TimeoutError):
        raise WeatherError("provider_unreachable") from None


@dataclass(frozen=True)
class Snapshot:
    url: str
    body: bytes = field(repr=False)
    fetched_at: datetime
    checked_at: datetime
    headers: Mapping[str, str]
    cache_state: str

    def provenance(self) -> dict[str, object]:
        return {
            "url": self.url,
            "effective_url": self.headers.get("x-mycoradar-effective-url"),
            "sha256": digest(self.body),
            "fetched_at": self.fetched_at.isoformat(),
            "checked_at": self.checked_at.isoformat(),
            "http_last_modified": self.headers.get("last-modified"),
            "http_expires": self.headers.get("expires"),
            "cache_state": self.cache_state,
            "hash_representation": "HTTP entity bytes after Content-Encoding decoding",
        }


class WeatherClient:
    def __init__(
        self,
        cache_dir: Path,
        *,
        transport: Transport = fetch,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.cache_dir, self.transport, self.now = cache_dir, transport, now
        self.remaining = 8

    def get(self, url: str) -> Snapshot:
        if not valid_url(url):
            raise WeatherError("source_url_refused")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        lock = self.cache_dir / ".weather-lock"
        try:
            lock.mkdir()
        except FileExistsError:
            raise WeatherError("cache_busy") from None
        try:
            return self._get(url)
        finally:
            lock.rmdir()

    def _get(self, url: str) -> Snapshot:
        now = self.now()
        if now.tzinfo is None:
            raise WeatherError("timestamp_invalid")
        path = self.cache_dir / (digest(url.encode()) + ".json")
        cache: dict[str, object] = {}
        body = b""
        if path.exists():
            try:
                if path.stat().st_size > 2 * MAX_BODY:
                    raise ValueError
                cache = json.loads(path.read_bytes())
                if not isinstance(cache, dict) or cache.get("url") != url:
                    raise ValueError
                body = base64.b64decode(str(cache.get("body", "")), validate=True)
                if len(body) > MAX_BODY or digest(body) != cache["sha256"]:
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError, RecursionError):
                raise WeatherError("cache_invalid") from None
            if now < timestamp(cache.get("not_before")):
                if cache.get("last_error"):
                    raise WeatherError("provider_cooldown")
                if cache.get("requires_revalidation"):
                    raise WeatherError("provider_revalidation_required")
                return self._snapshot(url, body, cache, "local_cache")
        if self.remaining <= 0:
            raise WeatherError("request_budget_exceeded")
        self.remaining -= 1
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
        previous_headers = cache.get("headers", {})
        if not isinstance(previous_headers, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in previous_headers.items()
        ):
            raise WeatherError("cache_invalid")
        modified = previous_headers.get("last-modified")
        modified_time = http_time(modified) if isinstance(modified, str) else None
        if (
            body
            and isinstance(modified, str)
            and modified_time is not None
            and modified_time <= now
        ):
            headers["If-Modified-Since"] = modified
        error_code: str | None = None
        try:
            result = self.transport(url, headers)
        except WeatherError as error:
            result = HTTPResult(0, b"")
            error_code = (
                str(error)
                if str(error)
                in {
                    "provider_unreachable",
                    "redirect_refused",
                    "response_budget_exceeded",
                    "decoded_budget_exceeded",
                    "gzip_invalid",
                    "deflate_invalid",
                    "encoding_unsupported",
                }
                else "provider_unreachable"
            )
        completed = self.now()
        if completed.tzinfo is None or completed < now:
            raise WeatherError("timestamp_invalid")
        now = completed
        response_headers = {key.lower(): value for key, value in result.headers.items()}
        safe_headers = {
            key: value
            for key, value in response_headers.items()
            if key
            in {
                "last-modified",
                "expires",
                "cache-control",
                "content-type",
                "x-mycoradar-effective-url",
            }
        }
        not_before = now + timedelta(hours=1)  # Project limit, not an invented provider quota.
        expires = http_time(safe_headers.get("expires"))
        if expires:
            not_before = max(not_before, expires)
        directives = response_headers.get(
            "cache-control",
            previous_headers.get("cache-control", "") if result.status == 304 else "",
        ).lower()
        max_age = re.search(r'(?:^|,)\s*max-age\s*=\s*"?(\d+)"?(?:\s*,|\s*$)', directives)
        if max_age:
            try:
                not_before = max(not_before, now + timedelta(seconds=int(max_age[1])))
            except (ValueError, OverflowError):
                not_before = datetime.max.replace(tzinfo=UTC)
        if len(result.body) > MAX_BODY:
            error_code = "response_budget_exceeded"
        elif result.status == 200:
            same_version = body == result.body and "fetched_at" in cache
            body = result.body
            if not same_version:
                cache["fetched_at"] = now.isoformat()
            cache["headers"] = safe_headers
        elif result.status == 304 and body and "If-Modified-Since" in headers:
            cache["headers"] = {**previous_headers, **safe_headers}
        else:
            error_code = error_code or "provider_http_error"
            retry = response_headers.get("retry-after")
            if retry is not None:
                try:
                    until = (
                        now + timedelta(seconds=int(retry))
                        if retry.isascii() and retry.isdigit()
                        else http_time(retry)
                    )
                    if until is None:
                        raise ValueError
                    not_before = max(not_before, until)
                except (ValueError, OverflowError):
                    # An unreadable server deadline requires operator review, never an early retry.
                    not_before = datetime.max.replace(tzinfo=UTC)
            if result.status == 429:
                error_code = "provider_throttled"
        cache.update(
            url=url,
            body=base64.b64encode(body).decode("ascii"),
            sha256=digest(body),
            checked_at=now.isoformat(),
            not_before=not_before.isoformat(),
            last_error=error_code,
            requires_revalidation="no-cache" in directives,
        )
        state = "revalidated" if result.status == 304 else "downloaded"
        transient = self._snapshot(url, body, cache, state) if not error_code else None
        if "no-store" in directives:
            # Operational cooldown only; no response body or response headers on disk.
            cache.update(
                body="", sha256=digest(b""), headers={}, last_error="cache_storage_forbidden"
            )
        with tempfile.NamedTemporaryFile(dir=self.cache_dir, delete=False) as file:
            temporary = Path(file.name)
            file.write(json.dumps(cache, sort_keys=True).encode())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        if error_code:
            raise WeatherError(error_code)
        if "no-store" in directives and transient is not None:
            return transient
        return self._snapshot(url, body, cache, state)

    @staticmethod
    def _snapshot(url: str, body: bytes, cache: dict[str, object], state: str) -> Snapshot:
        headers = cache.get("headers")
        if not isinstance(headers, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
        ):
            raise WeatherError("cache_invalid")
        return Snapshot(
            url,
            body,
            timestamp(cache.get("fetched_at")),
            timestamp(cache.get("checked_at")),
            headers,
            state,
        )
