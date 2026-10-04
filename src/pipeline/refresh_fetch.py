"""The one place the display refresh's upstream requests are counted, reused,
retried and stopped (2026-10-04).

WHY A LAYER AT THE SEAM
-----------------------
Every MLB request the refresh makes goes through `src.providers.mlb._get_json`
(schedule, boxscore, game log, standings, splits, handedness), the transactions
feed through `src.providers.mlb_news._get_json`, and the Savant arsenal CSV
through `src.providers.statcast.fetch_arsenal`. Those three functions are the
wire; the pipelines above them never touch it. So one wrapper around them,
installed for the length of a refresh, gives every step the same behaviour
without editing any of them:

  COUNT     every call and every real `urlopen` attempt, by endpoint class and
            by outcome, so "how many requests did one refresh make" is a number
            read off the run's own report, not an estimate.
  REUSE     an identical schedule or standings URL asked twice in one run is
            answered from memory (the probe, the results step and the pitcher
            step all ask for today's schedule; the pitcher and splits steps
            both ask for the same probables). Nothing larger is held. A response that can never change again -- a schedule
            day whose games are all final or cancelled, and the boxscore of a
            game the schedule has shown final -- is also kept on disk, keyed by
            the canonical URL as `src.datasvc.http.PoliteFetcher` does, so a
            restart, a second consumer on the same disk or a rerun does not ask
            again. A game log is never kept on disk: it changes with every start.
  RETRY     boundedly. 429 and 5xx are retried at most `MAX_RETRIES` times with
            a short capped backoff (Retry-After honoured up to
            `MAX_RETRY_AFTER_S`). A transport failure is not retried here: the
            provider's own call already retries a timeout or reset once. 401 and 403 are NEVER retried:
            the first one halts the whole run, and every later call fails
            instantly with no request. So does a run of consecutive hard
            failures. A 404 and a malformed body are not retried either.
  CLASSIFY  every call lands in exactly one outcome, so a refresh's own report
            can tell the four things apart that a bare "N failed" cannot:
                ok            the source answered with data
                ok_empty      the source answered and had nothing (a pitcher
                              with no starts, a date with no table), and
                not_found     the source says the thing does not exist (404):
                              both are MISSING SOURCE DATA, not a failure
                cache_memo / cache_disk   not asked again (REUSED)
                auth_denied / rate_limited / http_error /
                transport_error / invalid / halted    a FAILED fetch
            (whether the data that arrived was NEW, a CORRECTION or UNCHANGED
            is decided later, against the committed copy: see
            `display_refresh._row_diff`.)

NOTHING HERE WRITES A STORE. The disk cache lives under `<data>/raw/` (git
ignored, reproducible), holds only immutable provider answers, and a corrupt or
unwritable cache is a miss, never an error.

`sleep`, `clock` and the urlopen counter are injectable, so a test never sleeps
and never touches the network.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from src.datasvc.http import canonical_url
from src.providers import mlb, mlb_news, statcast

MAX_RETRIES = 2                      # so at most 3 attempts per call
BACKOFF_S = 1.0                      # 1 s, then 2 s
MAX_RETRY_AFTER_S = 30.0
CONSECUTIVE_FAILURE_LIMIT = 6        # this many hard failures in a row halts the run
RATE_LIMIT_LIMIT = 3                 # ... or this many calls that stayed 429 after retries
IMMUTABLE_TTL_S = 7 * 24 * 3600.0    # a final answer is trusted this long (stat corrections)
# Only these are kept in memory within a run. They are the answers several steps
# ask for again (today's and tomorrow's schedule is read by the probe, the
# results, bullpen, pitcher and splits steps) and they are small. A boxscore or a
# game log is asked for once per run, and holding 290 boxscores (tens of MB) to
# answer a question nobody repeats would cost the 1 GB machine for nothing.
MEMO_CLASSES = frozenset({"schedule", "standings"})
AUTH_STATUSES = frozenset({401, 403})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
FINAL_CODES = frozenset({"F", "O"})
SETTLED_CODES = FINAL_CODES | frozenset({"D", "C", "T", "U"})  # final, or will not be played

OUTCOMES_REUSED = ("cache_memo", "cache_disk")
OUTCOMES_FAILED = ("auth_denied", "rate_limited", "http_error",
                   "transport_error", "invalid", "halted")


def endpoint_class(path: str, params: Optional[dict] = None) -> str:
    """A short name for what one request is, for the per-class counts."""
    path = str(path).strip("/")
    params = params or {}
    if path == "schedule":
        return "schedule"
    if path.startswith("game/") and path.endswith("/boxscore"):
        return "boxscore"
    if path.startswith("people/") and path.endswith("/stats"):
        return {"gameLog": "pitcher_game_log", "statSplits": "pitcher_splits",
                "vsPlayer": "matchup"}.get(str(params.get("stats")), "player_stats")
    if path == "people":
        return "handedness"
    if path == "standings":
        return "standings"
    if path == "transactions":
        return "transactions"
    return path.split("/")[0] or "other"


def _is_empty(cls: str, payload) -> bool:
    """True when the source answered with a well-formed nothing."""
    if not isinstance(payload, dict):
        return not payload
    if cls == "schedule":
        return not any((d or {}).get("games") for d in payload.get("dates") or [])
    if cls in ("pitcher_game_log", "pitcher_splits", "matchup", "player_stats"):
        return not any((b or {}).get("splits") for b in payload.get("stats") or [])
    if cls == "standings":
        return not payload.get("records")
    if cls == "boxscore":
        return not payload.get("teams")
    if cls == "transactions":
        return not payload.get("transactions")
    if cls == "handedness":
        return not payload.get("people")
    return False


def _status_of(exc: BaseException) -> Optional[int]:
    """The HTTP status behind a provider error, or None for a transport error.
    `mlb._get_json` raises `MLBError(...) from HTTPError`; the news and Savant
    seams drop the cause and keep "HTTP 403" in the message."""
    cause = exc.__cause__
    code = getattr(cause, "code", None)
    if isinstance(code, int):
        return code
    found = re.search(r"\bHTTP (\d{3})\b", str(exc))
    return int(found.group(1)) if found else None


def _retry_after(exc: BaseException) -> Optional[float]:
    headers = getattr(exc.__cause__, "headers", None)
    try:
        raw = headers.get("Retry-After") if headers else None
        return min(float(raw), MAX_RETRY_AFTER_S) if raw else None
    except (TypeError, ValueError):
        return None


class FetchLayer:
    """See the module docstring. One instance per refresh."""

    def __init__(self, *, cache_dir: Optional[Path] = None, memo: bool = True,
                 retries: int = MAX_RETRIES, backoff_s: float = BACKOFF_S,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time,
                 immutable_ttl_s: float = IMMUTABLE_TTL_S):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.use_memo = bool(memo)
        self.retries = max(int(retries), 0)
        self.backoff_s = float(backoff_s)
        self._sleep, self._clock = sleep, clock
        self.immutable_ttl_s = float(immutable_ttl_s)
        self.entries: list = []
        self.wire_attempts = 0
        self.halted: Optional[str] = None
        self._memo: dict = {}
        self._final_pks: set = set()
        self._streak = 0
        self._rate_limited = 0

    # -- installation -------------------------------------------------------

    @contextlib.contextmanager
    def install(self):
        """Wrap the three network seams for the length of the `with` block, and
        count every real `urlopen`. Everything is restored on exit, whatever
        happens inside."""
        saved = (mlb._get_json, mlb_news._get_json, statcast.fetch_arsenal,
                 urllib.request.urlopen)
        real_get, news_get, arsenal, real_urlopen = saved

        def counting_urlopen(*args, **kwargs):
            self.wire_attempts += 1
            return real_urlopen(*args, **kwargs)

        def mlb_call(path, params=None, timeout=None):
            return self._call("mlb", real_get, mlb.MLBError, path, params,
                              lambda: real_get(path, params, timeout=timeout))

        def news_call(path, params, timeout=mlb_news.DEFAULT_TIMEOUT):
            return self._call("mlb_news", news_get, mlb_news.NewsError, path, params,
                              lambda: news_get(path, params, timeout=timeout),
                              host=mlb_news.API_HOST)

        def arsenal_call(season, side=statcast.PITCHER, min_pitches=statcast.MIN_PITCHES,
                         timeout=statcast.DEFAULT_TIMEOUT):
            return self._call("savant", arsenal, statcast.StatcastError,
                              "leaderboard/pitch-arsenal-stats",
                              {"year": season, "type": side, "min": min_pitches},
                              lambda: arsenal(season, side=side, min_pitches=min_pitches,
                                              timeout=timeout),
                              host=statcast.HOST, cls="savant_arsenal")

        urllib.request.urlopen = counting_urlopen
        mlb._get_json, mlb_news._get_json, statcast.fetch_arsenal = mlb_call, news_call, arsenal_call
        try:
            yield self
        finally:
            (mlb._get_json, mlb_news._get_json, statcast.fetch_arsenal,
             urllib.request.urlopen) = saved

    # -- the call -----------------------------------------------------------

    def _call(self, source, _original, error_cls, path, params, invoke, *,
              host: Optional[str] = None, cls: Optional[str] = None):
        params = params or {}
        cls = cls or endpoint_class(path, params)
        key = canonical_url(f"{host or mlb.API_HOST}/{str(path).lstrip('/')}"
                            + (f"?{urllib.parse.urlencode(sorted((str(k), str(v)) for k, v in params.items()))}"
                               if params else ""))
        entry = {"source": source, "class": cls, "key": key, "outcome": None,
                 "status": None, "attempts": 0}
        self.entries.append(entry)

        if self.halted:
            entry["outcome"] = "halted"
            raise error_cls(f"refresh halted, no request made: {self.halted}")

        memoable = self.use_memo and cls in MEMO_CLASSES
        if memoable and key in self._memo:
            entry["outcome"] = "cache_memo"
            return copy.deepcopy(self._memo[key])
        stored = self._disk_get(key)
        if stored is not None:
            entry["outcome"] = "cache_disk"
            self._remember(key, cls, stored)
            return copy.deepcopy(stored)

        attempt = 0
        while True:
            attempt += 1
            entry["attempts"] = attempt
            try:
                payload = invoke()
            except error_cls as exc:
                status = _status_of(exc)
                entry["status"] = status
                if status in AUTH_STATUSES:
                    entry["outcome"] = "auth_denied"
                    self.halted = (f"authentication denied (HTTP {status}) by {source}; "
                                   f"stopped with no retry")
                    raise
                # Only an HTTP status that means "try again" is retried here.
                # A transport failure is not: `mlb._get_json` already retries a
                # timeout or reset once itself, and stacking a second policy on
                # top of it multiplies the wait on an API that is simply down.
                if status in RETRY_STATUSES and attempt <= self.retries:
                    self._sleep(_retry_after(exc) or self.backoff_s * (2 ** (attempt - 1)))
                    continue
                if status == 404:
                    entry["outcome"] = "not_found"
                elif status == 429:
                    entry["outcome"] = "rate_limited"
                    self._rate_limited += 1
                elif status is None and "invalid JSON" in str(exc):
                    entry["outcome"] = "invalid"
                elif status is None:
                    entry["outcome"] = "transport_error"
                else:
                    entry["outcome"] = "http_error"
                if entry["outcome"] in ("rate_limited", "transport_error", "http_error"):
                    self._streak += 1
                    if self._rate_limited >= RATE_LIMIT_LIMIT:
                        self.halted = f"rate limited by {source} {self._rate_limited} times; stopped"
                    elif self._streak >= CONSECUTIVE_FAILURE_LIMIT:
                        self.halted = f"{self._streak} consecutive failed requests to {source}; stopped"
                raise
            self._streak = 0
            entry["outcome"] = "ok_empty" if _is_empty(cls, payload) else "ok"
            self._remember(key, cls, payload)
            self._disk_put(key, cls, payload)
            return payload

    # -- reuse --------------------------------------------------------------

    def _remember(self, key, cls, payload) -> None:
        if self.use_memo and cls in MEMO_CLASSES:
            self._memo[key] = copy.deepcopy(payload)
        if cls == "schedule" and isinstance(payload, dict):
            for day in payload.get("dates") or []:
                for game in (day or {}).get("games") or []:
                    code = ((game or {}).get("status") or {}).get("codedGameState")
                    if code in FINAL_CODES and game.get("gamePk") is not None:
                        self._final_pks.add(int(game["gamePk"]))

    def _immutable(self, key, cls, payload) -> bool:
        if cls == "schedule" and isinstance(payload, dict):
            games = [g for d in payload.get("dates") or [] for g in (d or {}).get("games") or []]
            return bool(games) and all(
                ((g.get("status") or {}).get("codedGameState") in SETTLED_CODES) for g in games)
        if cls == "boxscore":
            found = re.search(r"/game/(\d+)/boxscore", key)
            return bool(found) and int(found.group(1)) in self._final_pks and not _is_empty(cls, payload)
        return False

    def _path(self, key: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.cache_dir / digest[:2] / f"{digest}.json"

    def _disk_get(self, key: str):
        path = self._path(key)
        if path is None:
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if envelope.get("url") != key:
                return None
            if self._clock() - float(envelope["fetched"]) > self.immutable_ttl_s:
                return None
            payload = envelope["payload"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if "/boxscore" in key:
            # The schedule that showed this game final is how a boxscore earns
            # its place on disk; a cached boxscore with no such memory this run
            # is still a final game's (it was only ever written for one).
            found = re.search(r"/game/(\d+)/boxscore", key)
            if found:
                self._final_pks.add(int(found.group(1)))
        elif "/schedule" in key and isinstance(payload, dict):
            for day in payload.get("dates") or []:
                for game in (day or {}).get("games") or []:
                    if ((game or {}).get("status") or {}).get("codedGameState") in FINAL_CODES \
                            and game.get("gamePk") is not None:
                        self._final_pks.add(int(game["gamePk"]))
        return payload

    def _disk_put(self, key, cls, payload) -> None:
        path = self._path(key)
        if path is None or not self._immutable(key, cls, payload):
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"url": key, "fetched": self._clock(), "payload": payload},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except (OSError, TypeError, ValueError):
            pass  # an unwritable cache is a miss next time, never an error

    # -- reporting ----------------------------------------------------------

    def mark(self) -> int:
        """A position in the call log, for a per-step delta."""
        return len(self.entries)

    def summary(self, since: int = 0) -> dict:
        """What the calls since `since` did. `network_calls` went to the wire
        layer (retries are in `retries`); `wire_attempts` is the number of real
        `urlopen` calls over the whole life of the layer (it includes the
        provider's own one retry on a timeout), so it is only reported at the
        run level (`since == 0`)."""
        window = self.entries[since:]
        by_class: dict = {}
        outcomes: dict = {}
        network = reused = failed = retries = 0
        network_keys: dict = {}
        for e in window:
            slot = by_class.setdefault(e["class"], {"network": 0, "reused": 0, "failed": 0})
            outcomes[e["outcome"]] = outcomes.get(e["outcome"], 0) + 1
            if e["outcome"] in OUTCOMES_REUSED:
                reused += 1
                slot["reused"] += 1
            elif e["outcome"] == "halted":
                failed += 1
                slot["failed"] += 1
            else:
                network += 1
                slot["network"] += 1
                retries += max(e["attempts"] - 1, 0)
                network_keys[e["key"]] = network_keys.get(e["key"], 0) + 1
                if e["outcome"] in OUTCOMES_FAILED:
                    failed += 1
                    slot["failed"] += 1
        out = {"calls": len(window), "network_calls": network, "reused": reused,
               "failed": failed, "retries": retries,
               "requests_made": network + retries,
               "same_url_twice_on_network": sum(1 for n in network_keys.values() if n > 1),
               "by_class": by_class, "outcomes": outcomes,
               "missing_source_data": outcomes.get("ok_empty", 0) + outcomes.get("not_found", 0)}
        if since == 0:
            out["wire_attempts"] = self.wire_attempts
            out["halted"] = self.halted
        return out
