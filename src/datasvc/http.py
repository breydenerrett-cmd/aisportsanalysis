"""One polite HTTP fetcher for every data source.

What it guarantees, whichever sport calls it:

* One request at a time, at least `delay_s` apart. No parallel requests.
* An on-disk cache keyed by the canonical URL, so a re-run never fetches a page it
  already has. Historical pages never expire; `max_age_s` refreshes live ones
  (a scoreboard, an upcoming card).
* A 404 is cached too (an old fight with no statistics stays missing without
  being asked for again) and raised as NotFound.
* Retries with backoff on 429, 5xx and network errors, honouring Retry-After up
  to a minute.
* A hard cap on network requests per run (RequestCapReached), so a bug cannot
  turn into thousands of requests.
* A browser check instead of data (a proof-of-work or CAPTCHA page) raises
  SourceBlocked and is never cached. Nothing here tries to pass one: a source
  that blocks a plain client is a source we do not use.

The opener, sleep and clock are injectable so tests run with no network.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.paths import data_path

DEFAULT_UA = "LineHoundData/1.0 (plain client, one request at a time)"
DEFAULT_CACHE_DIR = data_path("datasvc", "raw")
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_S = 60.0

# Query parameters that change nothing about the payload; dropped from the cache key
# so the same resource reached through a $ref and through a built URL is one entry.
_IGNORED_PARAMS = frozenset({"lang", "region"})
_CHALLENGE_MARKERS = ("checking your browser", "requires javascript", "captcha",
                      "just a moment", "cf-chl", "attention required")


class FetchError(RuntimeError):
    """A request that could not be completed. `status` is the HTTP status or None."""

    def __init__(self, url: str, status: Optional[int], message: str):
        super().__init__(f"{message} ({status}) for {url}")
        self.url = url
        self.status = status


class NotFound(FetchError):
    """The source answered 404 (cached, so it is not asked again)."""


class SourceBlocked(FetchError):
    """The source served a browser check instead of data. Stop; do not work around it."""


class RequestCapReached(FetchError):
    """This run has used its network request budget."""


def canonical_url(url: str) -> str:
    """https, no lang/region parameters, remaining parameters sorted."""
    parts = urllib.parse.urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k not in _IGNORED_PARAMS]
    query.sort()
    return urllib.parse.urlunsplit((scheme, parts.netloc.lower(), parts.path,
                                    urllib.parse.urlencode(query), ""))


def looks_like_challenge(body: bytes) -> bool:
    head = body[:4000].decode("utf-8", "replace").lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PoliteFetcher:
    def __init__(self, *, cache_dir: Optional[Path] = None, delay_s: float = 0.35,
                 max_requests: Optional[int] = None, timeout_s: float = 40.0,
                 retries: int = 3, backoff_s: float = 2.0, user_agent: str = DEFAULT_UA,
                 opener: Optional[Callable] = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, now_iso: Callable[[], str] = _utc_now_iso):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.delay_s = float(delay_s)
        self.max_requests = max_requests
        self.timeout_s = float(timeout_s)
        self.retries = int(retries)
        self.backoff_s = float(backoff_s)
        self.user_agent = user_agent
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._clock = clock
        self._now_iso = now_iso
        self._last_request_at: Optional[float] = None
        self.stats = {"requests": 0, "cache_hits": 0, "bytes": 0, "not_found": 0, "retries": 0}

    # -- cache ---------------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        canon = canonical_url(url)
        host = urllib.parse.urlsplit(canon).netloc or "unknown"
        digest = hashlib.sha1(canon.encode("utf-8")).hexdigest()
        return self.cache_dir / host / digest[:2] / f"{digest}.json"

    def _read_cache(self, url: str, max_age_s: Optional[float]) -> Optional[dict]:
        path = self._cache_path(url)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if max_age_s is not None:
            try:
                fetched = datetime.strptime(envelope["fetched_utc"], "%Y-%m-%dT%H:%M:%SZ")
                age = (datetime.now(timezone.utc).replace(tzinfo=None) - fetched).total_seconds()
            except (KeyError, ValueError):
                return None
            if age > max_age_s:
                return None
        return envelope

    def _write_cache(self, url: str, envelope: dict) -> None:
        path = self._cache_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # -- network -------------------------------------------------------------------

    def _wait_turn(self) -> None:
        if self._last_request_at is not None:
            gap = self._clock() - self._last_request_at
            if gap < self.delay_s:
                self._sleep(self.delay_s - gap)

    def _network(self, url: str) -> dict:
        canon = canonical_url(url)
        attempt = 0
        while True:
            if self.max_requests is not None and self.stats["requests"] >= self.max_requests:
                raise RequestCapReached(canon, None, f"request cap of {self.max_requests} reached")
            self._wait_turn()
            self.stats["requests"] += 1
            request = urllib.request.Request(canon, headers={
                "User-Agent": self.user_agent, "Accept": "application/json, text/html;q=0.8"})
            status, body, ctype, retry_after = None, b"", "", None
            try:
                with self._open(request, timeout=self.timeout_s) as response:
                    status = getattr(response, "status", 200)
                    body = response.read()
                    ctype = (response.headers.get("content-type", "") if response.headers else "")
            except urllib.error.HTTPError as exc:
                status = exc.code
                try:
                    body = exc.read() or b""
                except Exception:  # noqa: BLE001
                    body = b""
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    exc.close()     # an unclosed error response holds its connection open
                except Exception:  # noqa: BLE001
                    pass
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                status, body = None, repr(exc).encode("utf-8")
            finally:
                self._last_request_at = self._clock()
            self.stats["bytes"] += len(body)

            if status == 200:
                if looks_like_challenge(body):
                    raise SourceBlocked(canon, status, "the source served a browser check, not data")
                return {"url": canon, "status": 200, "content_type": ctype,
                        "fetched_utc": self._now_iso(), "body": body.decode("utf-8", "replace")}
            if status == 404:
                self.stats["not_found"] += 1
                return {"url": canon, "status": 404, "content_type": ctype,
                        "fetched_utc": self._now_iso(), "body": ""}
            retryable = status is None or status in RETRY_STATUSES
            if not retryable or attempt >= self.retries:
                raise FetchError(canon, status, "request failed")
            wait = self.backoff_s * (2 ** attempt)
            if retry_after:
                try:
                    wait = max(wait, min(float(retry_after), MAX_RETRY_AFTER_S))
                except ValueError:
                    pass
            self.stats["retries"] += 1
            self._sleep(wait)
            attempt += 1

    # -- public --------------------------------------------------------------------

    def get_text(self, url: str, *, use_cache: bool = True, max_age_s: Optional[float] = None) -> str:
        envelope = self._read_cache(url, max_age_s) if use_cache else None
        if envelope is not None:
            self.stats["cache_hits"] += 1
        else:
            envelope = self._network(url)
            self._write_cache(url, envelope)
        if envelope.get("status") == 404:
            raise NotFound(envelope.get("url", url), 404, "not found")
        return envelope["body"]

    def get_json(self, url: str, *, use_cache: bool = True, max_age_s: Optional[float] = None):
        text = self.get_text(url, use_cache=use_cache, max_age_s=max_age_s)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise FetchError(canonical_url(url), 200, f"response was not JSON: {exc}") from None

    def fetched_utc(self, url: str) -> Optional[str]:
        """When the cached copy of `url` was fetched (None if it is not cached)."""
        envelope = self._read_cache(url, None)
        return envelope.get("fetched_utc") if envelope else None
