"""BALLDONTLIE MMA as a `ufc_autograde` result provider.

STATUS: BUILT FROM DOCUMENTATION, NEVER RUN AGAINST THE LIVE API.
The response shapes below come from https://mma.balldontlie.io (read
2026-10-01): `GET /mma/v1/events?date=YYYY-MM-DD` and
`GET /mma/v1/fights?event_ids[]=ID` with fight fields `fighter1`, `fighter2`,
`winner` (fighter object or null), `result_method`, `result_round`, `status`
and `status_state` (one of scheduled, in_progress, final, postponed,
canceled, delayed, suspended, abandoned, unknown).

ACCESS: the Fights endpoint needs the ALL-STAR tier or above for MMA
($9.99/mo per sport at time of reading); the free tier is events and
fighters only (no fights, so no winner). Without a key with that
entitlement every call here raises `ProviderError` naming the blocker.
Paid tiers do not carry across sports -- the tennis ALL-ACCESS trial that
ended 2026-09-17 is gone.

DOCUMENTATION GAPS, handled by failing safe (the bout is left unresolved for
a human, never guessed):
  * How a DRAW or NO CONTEST fight is encoded is not documented. A final
    fight with `winner` null is read as a draw / no contest ONLY when
    `result_method` contains "draw" or "no contest"; otherwise outcome is
    None and the autograder leaves it unresolved.
  * How a fight-level cancellation or a replaced fighter is encoded is not
    documented. `status_state == "canceled"` on a fight is read as
    cancelled; a replacement shows up as the published pair being absent
    from the event's fights (handled in `ufc_autograde.resolve_bout`).
  * Array query parameters are sent as `event_ids[]` (BALLDONTLIE's
    documented array style for its other sports).

SECURITY: reuses `src.providers.balldontlie.Client`, which never logs or
echoes the key. Nothing here reads the key itself.
"""

from __future__ import annotations

import json
from datetime import date as date_cls, datetime, timedelta
from typing import Callable, Optional

from src.pipeline import ufc_results
from src.pipeline.ufc_autograde import (
    STATUS_CANCELLED, STATUS_FINAL, STATUS_PENDING, ProviderError, ProviderFight,
    UfcResultsProvider)
from src.providers import balldontlie as bdl

PROVIDER_NAME = "balldontlie"
EVENTS_PATH = "/mma/v1/events"
FIGHTS_PATH = "/mma/v1/fights"


def _name(fighter) -> str:
    return str((fighter or {}).get("name") or "").strip()


def _status(fight: dict) -> str:
    state = str(fight.get("status_state") or "").strip().lower()
    if state == "final":
        return STATUS_FINAL
    if state in ("canceled", "cancelled"):
        return STATUS_CANCELLED
    return STATUS_PENDING


def parse_fight(fight: dict, *, fetched_utc: str) -> ProviderFight:
    """One documented fight object -> ProviderFight (pure)."""
    status = _status(fight)
    winner = _name(fight.get("winner")) or None
    method = str(fight.get("result_method") or "").strip().lower()
    outcome: Optional[str] = None
    if status == STATUS_FINAL:
        if winner:
            outcome = ufc_results.OUTCOME_WIN
        elif "no contest" in method or method == "nc":
            outcome = ufc_results.OUTCOME_NO_CONTEST
        elif "draw" in method:
            outcome = ufc_results.OUTCOME_DRAW
    event = fight.get("event") or {}
    raw = f"{fight.get('status')}/{fight.get('status_state')}"
    if fight.get("result_method"):
        raw += f" method={fight.get('result_method')}"
    return ProviderFight(
        provider=PROVIDER_NAME, event_id=str(event.get("id", "")),
        fight_id=str(fight.get("id", "")),
        fighter1=_name(fight.get("fighter1")), fighter2=_name(fight.get("fighter2")),
        status=status, raw_status=raw, outcome=outcome, winner=winner,
        fetched_utc=fetched_utc)


class BallDontLieMmaProvider(UfcResultsProvider):
    name = PROVIDER_NAME

    def __init__(self, client: bdl.Client):
        self._client = client

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "BallDontLieMmaProvider":
        try:
            client = bdl.client_from_env(
                env, config=bdl.ClientConfig(
                    rate_per_minute=50, max_429_wait_seconds=120, max_429_attempts=5))
        except bdl.BallDontLieError as exc:
            raise ProviderError(
                f"{exc}; BALLDONTLIE MMA needs a key with the ALL-STAR MMA "
                "tier (fights endpoint)") from None
        return cls(client)

    def _event_ids(self, date: str) -> list:
        wanted = {date, (date_cls.fromisoformat(date) - timedelta(days=1)).isoformat()}
        ids = []
        for day in sorted(wanted):
            for page in self._client.pages(EVENTS_PATH, {"date": day}):
                for event in page.get("data") or ():
                    # Re-checked client-side: an event is wanted only if its
                    # own date is the card date or the day before (a late
                    # main card crosses the UTC date line).
                    if str(event.get("date") or "")[:10] in wanted and event.get("id") is not None:
                        ids.append(event["id"])
        return sorted(set(ids))

    def fetch_fights(self, date: str, *, now: datetime) -> list:
        fetched = now.isoformat()
        try:
            ids = self._event_ids(date)
            out = []
            if ids:
                for page in self._client.pages(FIGHTS_PATH, {"event_ids[]": ids}):
                    for fight in page.get("data") or ():
                        if (fight.get("event") or {}).get("id") in ids:
                            out.append(parse_fight(fight, fetched_utc=fetched))
            return out
        except bdl.BallDontLieHTTPError as exc:
            if exc.status in (401, 403):
                raise ProviderError(
                    f"BALLDONTLIE returned HTTP {exc.status}: the key is missing or "
                    "not entitled to MMA fights (ALL-STAR MMA tier needed)") from None
            raise ProviderError(str(exc)) from None
        except bdl.BallDontLieError as exc:
            raise ProviderError(str(exc)) from None


def fixture_transport(payload: dict) -> Callable:
    """A transport for `bdl.Client` that serves a saved payload
    {"events": {...documented events response...},
     "fights": {...documented fights response...}} -- offline dry runs and
    tests. Everything not events/fights is a 404."""
    def transport(path: str, params: dict, headers: dict) -> tuple:
        if path == EVENTS_PATH:
            return 200, json.dumps(payload.get("events") or {"data": []}).encode()
        if path == FIGHTS_PATH:
            return 200, json.dumps(payload.get("fights") or {"data": []}).encode()
        return 404, b""
    return transport


def provider_from_fixture(path: str) -> BallDontLieMmaProvider:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    client = bdl.Client("fixture-key", transport=fixture_transport(payload),
                        sleep=lambda _s: None,
                        config=bdl.ClientConfig(rate_per_minute=100000))
    return BallDontLieMmaProvider(client)
