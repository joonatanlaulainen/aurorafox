"""Shared HTTP client with an on-disk, expiry-aware cache.

Both upstream services publish terms that this client is built to honour:

MET Norway requires a User-Agent that identifies the application and gives a
contact address, and asks clients not to re-request data before the ``Expires``
header they send. A run touches ~50 coordinates, so caching is not an
optimisation here, it is a condition of use. Requests are refused outright
rather than sent with a generic agent.

NOAA SWPC publishes no per-file expiry, so its products get a short fixed TTL;
their cadence is 1-5 minutes for the real-time feeds and much slower for the
forecasts.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests

from ..version import __version__

DEFAULT_USER_AGENT = (
    f"aurorafox/{__version__} (+https://github.com/joonatanlaulainen/aurorafox)"
)
USER_AGENT_ENV = "AURORAFOX_USER_AGENT"
CACHE_DIR_ENV = "AURORAFOX_CACHE_DIR"

DEFAULT_TIMEOUT = 20.0
MAX_ATTEMPTS = 3


class SourceError(RuntimeError):
    """A data source could not be read. Callers degrade rather than crash."""


@dataclass(slots=True)
class Response:
    """A fetched payload plus where it came from and how fresh it is."""

    url: str
    text: str
    fetched_at: datetime
    from_cache: bool

    def json(self) -> Any:
        return json.loads(self.text)


def user_agent() -> str:
    return os.environ.get(USER_AGENT_ENV, "").strip() or DEFAULT_USER_AGENT


def cache_dir() -> Path:
    override = os.environ.get(CACHE_DIR_ENV, "").strip()
    base = Path(override) if override else Path.home() / ".cache" / "aurorafox"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return cache_dir() / f"{digest}.json"


def _read_cache(url: str, now: float) -> Response | None:
    path = _cache_path(url)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if record.get("url") != url or record.get("expires_at", 0) <= now:
        return None
    return Response(
        url=url,
        text=record["text"],
        fetched_at=datetime.fromtimestamp(record["fetched_at"], tz=timezone.utc),
        from_cache=True,
    )


def _write_cache(url: str, text: str, fetched_at: float, expires_at: float) -> None:
    record = {
        "url": url,
        "text": text,
        "fetched_at": fetched_at,
        "expires_at": expires_at,
    }
    path = _cache_path(url)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # A cache that cannot be written must not break a run.
        pass


def _expiry_from_headers(headers: Any, now: float, default_ttl: float) -> float:
    """Prefer the server's own ``Expires``; fall back to a caller TTL."""
    raw = headers.get("Expires")
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed is not None:
                expires = parsed.timestamp()
                # Never cache for less than 60s or more than 6h.
                return min(max(expires, now + 60.0), now + 6 * 3600.0)
        except (TypeError, ValueError):
            pass
    return now + default_ttl


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(
            {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
        )
    return _session


def fetch(url: str, *, default_ttl: float = 300.0, use_cache: bool = True) -> Response:
    """GET ``url``, returning cached content when it is still valid.

    Raises :class:`SourceError` after exhausting retries, so a single failing
    endpoint degrades one part of a run instead of aborting it.
    """
    now = time.time()
    if use_cache:
        cached = _read_cache(url, now)
        if cached is not None:
            return cached

    session = _get_session()
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(0.6 * (2**attempt))
        try:
            response = session.get(url, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 429 or 500 <= response.status_code < 600:
            last_error = SourceError(f"{url} returned HTTP {response.status_code}")
            continue
        if response.status_code != 200:
            raise SourceError(f"{url} returned HTTP {response.status_code}")

        fetched_at = time.time()
        if use_cache:
            _write_cache(
                url,
                response.text,
                fetched_at,
                _expiry_from_headers(response.headers, fetched_at, default_ttl),
            )
        return Response(
            url=url,
            text=response.text,
            fetched_at=datetime.fromtimestamp(fetched_at, tz=timezone.utc),
            from_cache=False,
        )

    raise SourceError(f"could not fetch {url}: {last_error}")
