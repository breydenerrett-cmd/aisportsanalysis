"""GET /card/{date} and GET /card: THE CARD -- today's three to five bets.

Same division of labour as api/opportunities.py: this file fetches inputs
and hands them to pure builders. `src.report.card.card_for_date` does the
assembly, `src.analysis.daily_card` owns the rule and the wording, and
nothing here decides anything a reader sees.

DATE HANDLING: `/card/{date}` validates and builds for that date; `/card`
uses UTC-today, the same rule every other date-defaulting route applies.

This endpoint NEVER returns an empty card silently. When there is nothing
to publish it carries a `reason` naming a fact about the world -- no games
scheduled, all of them started, no prices posted yet -- because those are
the only empty states this surface has. It has no evidence bar to clear and
so cannot report failing to clear one.
"""

from __future__ import annotations

import logging
import os
from datetime import date as date_cls, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from api.games import _build_entries, _record_page_view
from src.analysis import best_bets_card, daily_card, grade
from src.analysis import opportunities as opportunities_mod
from src.analysis import strength
from src.appstate import freshness
from src.appstate import ratelimit
from src.appstate import ufc_public_card
from src.report import card as card_mod

# TWO ROUTERS, ONE PREFIX (2026-10-01). api/app.py mounts `router` behind the
# paid gate and `public_router` behind nothing:
#
#   router         GET /card/{date}, GET /card          PAID  -- tonight's picks.
#   public_router  GET /card/record, GET /card/history  PUBLIC -- the graded
#                  GET /card/accounts                   record, settled days only,
#                                                       and example account
#                                                       balances over it.
#
# The landing page promises "one public page you can open yourself", and the
# record page IS that page; behind the paid gate a stranger who followed the
# proof link met "SIGN IN REQUIRED" and a token box, which is the opposite of
# proof. What stays paid is the product -- the pick for a date that has not
# been settled. `_public_history` below is what makes the public half safe:
# it is the only thing between this unauthenticated route and tonight's card,
# because history()/history_v2() return PUBLISHED-but-unsettled days too.
router = APIRouter()
public_router = APIRouter()
_log = logging.getLogger(__name__)

# Per-IP, per-minute. The two public routes verify the hash chain and fold the
# whole ledger on every call, and nobody legitimately loads a record page
# sixty times a minute; this keeps an open route from being a free way to burn
# the box's one CPU. Keyed on Fly-Client-IP (src.appstate.ratelimit.client_ip).
PUBLIC_RECORD_RATE_LIMIT_PER_MIN = 60
_public_record_limiter = ratelimit.FixedWindowLimiter(
    limit=PUBLIC_RECORD_RATE_LIMIT_PER_MIN, window_s=60.0)
_rate_limit_public_record = ratelimit.limiter_dependency(_public_record_limiter)

# GET /card?sport=nfl had no cache at all: every request re-ran
# nfl_card.card_for_date, which -- when the date is not yet frozen -- pays
# for a live nfl_slate build. Measured cold on staging 2026-09-21: 3.3s.
# Same fix shape as the mma cache directly below: cache the BUILT payload
# per date, TTL-only, same 120s TTL every other date-keyed cache here uses.
# Added so api/warmup.py has a real cache to warm -- see that module's
# docstring for why a warm-up call must go through the same cached path a
# real request does, not call nfl_card.card_for_date directly.
_nfl_card_cache = freshness.SingleFlightTTLCache(ttl_s=120.0, stale_while_revalidate_s=900.0)

# GET /card?sport=mma's LIVE branch (measured on staging 2026-09-21: 2.7s)
# reads `snapshots.read_multibook(sport="mma")` -- the whole multibook
# store, once per request, only to throw most of it away filtering to one
# date -- every time the day's card is not yet FROZEN (`ufc_card.
# card_for_date`'s own `prefer_frozen` check already makes the common case,
# a published card, cheap; this only covers the live-build path). Same
# fix shape as api/odds.py and api/games.py's own caches: cache the BUILT
# payload per date, TTL-only (no fingerprint check -- unlike the multibook
# reader fix, this file has no reason to reimplement store-window logic
# just to save a rebuild), same 120s TTL every other date-keyed cache in
# this project uses. Only the VALUE is reused, never the meta -- this
# route's response shape is unchanged, so no `freshness` key is added.
# A date after the UFC pause cut-off never reaches this cache (2026-10-03,
# see `_build_payload`): it is answered as paused before anything is built.
_mma_card_cache = freshness.SingleFlightTTLCache(ttl_s=120.0, stale_while_revalidate_s=900.0)

# MLB card, LIVE (unpublished) branch only -- see _build_payload. The stale
# window (here and on the NFL/UFC caches above, 2026-09-21) pairs with
# api/warmup.py's 10-minute pass: past the 120 s TTL the last good payload is
# served at once while it rebuilds in the background, so no visitor waits.
_mlb_live_card_cache = freshness.SingleFlightTTLCache(ttl_s=120.0, stale_while_revalidate_s=900.0)

# GET /card/history's page size. Capped, not unlimited -- the record page
# is the public sales pitch, not a data export; a reader who wants the
# whole ledger can read evidence/cards_v1.jsonl directly, which is the
# actual receipt.
DEFAULT_HISTORY_LIMIT = 60
MAX_HISTORY_LIMIT = 200


def _validate_sport(sport: str) -> None:
    """Validate sport parameter against src.sports.keys()."""
    from src import sports
    valid_sports = sports.keys()
    if sport not in valid_sports:
        raise HTTPException(
            status_code=400,
            detail=f"sport must be one of {valid_sports}, got {sport!r}")


# T5 (docs/CARD_V2_BUILD_PLAN.md). The only two rule ids any card route
# accepts -- there is no third value, and neither string is guessed from
# elsewhere: "v1" is `daily_card.CARD_RULE`'s family, "v2" is
# `best_bets_card.V2.rule_id`'s. `?rule=` defaults to `card_mod.
# ACTIVE_CARD_RULE`, so every existing caller (no `rule` param at all) keeps
# getting exactly what it always has -- V1 -- until `ACTIVE_CARD_RULE`
# itself flips at T13's registration commit.
_VALID_RULES = ("v1", "v2")


def _resolve_rule(rule: Optional[str]) -> str:
    resolved = rule or card_mod.ACTIVE_CARD_RULE
    if resolved not in _VALID_RULES:
        raise HTTPException(
            status_code=400,
            detail=f"rule must be one of {_VALID_RULES}, got {resolved!r}")
    return resolved


def _previous_rule_cohort(sport: str, live_rule: Optional[str]) -> Optional[dict]:
    """The prior rule's reconciled record, read-only (task B1/B2, owner
    instruction: no version gets prominence because its return is better --
    the record route hands the page both the current rule's figures, built
    above exactly as before, AND the rule right before it, so a page never
    has to choose one to show).

    Only populated on the response for the CURRENTLY LIVE rule -- a caller
    that explicitly asked for the retired rule's own record (`?rule=v1` /
    `?rule=NFL_CARD_V1`) is already looking at the oldest rule this sport
    has, which has no predecessor of its own. `live_rule` is the caller's
    resolved rule id (None for MLB's own v1/v2 shorthand, meaning "compare
    to ACTIVE_CARD_RULE inside effective_record"); MMA never has a previous
    rule (a brand-new test, see src.report.ufc_card).

    A read failure here must never break the record this route has always
    served -- `effective_record`'s own cohort builders already contain
    every ledger-read exception; this is one more layer of the same
    honest-absence rule, for the one failure mode entirely outside the
    ledger (an import cycle, a renamed constant): return None, not a 500.
    """
    if sport == "mma":
        return None
    try:
        from src.report import effective_record
        snapshot = effective_record.sport_snapshot(sport)
    except Exception:  # noqa: BLE001
        return None
    current = snapshot.get("current") or {}
    if sport == "nfl" and live_rule not in (None, current.get("rule_id")):
        return None
    return snapshot.get("previous")


def _effective_record_extras(sport: str, live_rule: Optional[str]) -> dict:
    """The fields the MLB-v2 branch of `get_card_record` needs but cannot
    reach by falling through to the shared block below (that branch
    `return`s its payload early -- see the `if sport == "mlb" and
    resolved_rule == "v2":` branch above -- because V2's payload is
    already assembled by hand with its own `rule`/`basis`/`disclaimer`
    keys). Without this, `GET /card/record` for MLB 500s with a
    NameError on every call that resolves to "v2" -- which, since
    `card_mod.ACTIVE_CARD_RULE` flipped to "v2" at CUTOVER_DATE
    (2026-09-23), is now every call with no explicit `?rule=` at all,
    i.e. the record page's default request.

    Mirrors exactly what the non-early-return branch below sets for
    every other sport: chain_ok/chain_detail/rows_checked and
    previous_rule -- read-only, same shape, same honest-absence rule
    (an unreadable chain reports `None`, never a guessed "ok").

    THE CHAIN VERIFIED HERE IS V2's OWN (`card_ledger.CARD_STORE_V2`),
    NOT `verify()`'s bare default. A bare `card_ledger.verify(sport=
    "mlb")` (or `sport=None`) resolves through `store_path`, which is
    V1's file -- exactly the MLB/NFL chain-mismatch bug `_previous_rule_
    cohort`'s sibling code above already had to fix once (see that
    block's own comment, and `docs/` review 2026-09-20). Naming the path
    explicitly is what keeps this from repeating it for V2.
    """
    from src.appstate import card_ledger

    extras: dict = {"sport": sport}
    try:
        chain = card_ledger.verify(path=card_ledger.CARD_STORE_V2)
        extras["chain_ok"] = bool(getattr(chain, "ok", True))
        extras["chain_detail"] = None if extras["chain_ok"] else str(chain)
        extras["rows_checked"] = getattr(chain, "rows_checked", None)
    except Exception:  # noqa: BLE001 -- honest-absence, never a 500
        extras["chain_ok"] = None
        extras["chain_detail"] = None
        extras["rows_checked"] = None
    extras["previous_rule"] = _previous_rule_cohort(sport, live_rule)
    return extras


def _resolve_nfl_rule(rule: Optional[str]) -> str:
    """`?rule=` for sport=nfl: one of src/report/nfl_card.RULES, default the
    live rule. ADDED 2026-09-20: the NFL ledger holds NFL_CARD_V1 (retired)
    and NFL_CARD_V2 (live) and the record shows one at a time, never the two
    pooled -- so the retired record needs its own address to stay public.
    MLB's "v1"/"v2" are not NFL rule ids and are refused here, not guessed."""
    from src.report import nfl_card as nfl_report
    resolved = (rule or nfl_report.LIVE_RULE).upper()
    if resolved not in nfl_report.RULES:
        raise HTTPException(
            status_code=400,
            detail=f"rule must be one of {nfl_report.RULES} for sport=nfl, got {rule!r}")
    return resolved


def _build_payload(date: str, request: Optional[Request], route: str,
                   sport: str = "mlb", rule: Optional[str] = None) -> dict:
    """The card for one date.

    THE FROZEN CHECK COMES FIRST, AND IT IS WORTH 15 SECONDS A REQUEST.
    ------------------------------------------------------------------
    This function used to run `_build_entries` (a live schedule fetch plus a
    full slate build) and then `build_opportunities` over the result, before
    handing both to `card_mod.card_for_date`.

    But `card_for_date` serves the FROZEN row whenever one exists, and in that
    branch it reads neither argument. `frozen_card` needs one ledger row and
    nothing else. So on every request for a date whose card is published --
    which is every request for today's card, all day, from every visitor --
    the endpoint built a slate and a price board and threw both away.

    Measured on the 512 MB staging container from its own log:

        GET /card/{date}  status=200  latency_ms=15260.3

    Fifteen seconds of a one-CPU machine, per request, for a result already
    sitting on disk. It starved /health past Fly's timeout, Fly pulled the
    machine out of rotation, and visitors got 503s from an app that was alive
    -- see docs/INCIDENT_2026-09-10_SPINNING_SLATE.md.

    Checking first costs one ledger read. The live branch below is unchanged
    and still pays full price, which is correct: a date with no published
    card genuinely has to be built.
    """
    _validate_sport(sport)

    # Tennis: return research-only notice
    if sport == "tennis":
        _record_page_view(request, route, date)
        return {
            "sport": "tennis",
            "reason": "Research only. No tennis picks until results grading is connected."
        }

    # NFL: use nfl_card, cached per date -- see _nfl_card_cache above.
    if sport == "nfl":
        from src.report import nfl_card

        def _rebuild():
            return nfl_card.card_for_date(date, now=datetime.now(timezone.utc))

        payload, _meta = _nfl_card_cache.get(("nfl_card", date), _rebuild)
        _record_page_view(request, route, date, surface="card", sport="nfl")
        return payload

    # UFC/MMA: use ufc_card. Free/public, no different than the other live
    # rules here -- the "free, being tested" framing lives in the payload's
    # own notice/disclaimer text, not in a separate auth gate.
    if sport == "mma":
        # PAUSED AFTER THE CUT-OFF (owner decision 2026-10-03,
        # docs/decisions/UFC_FAVOURITES_PAUSED.md). The favourites rule is no
        # longer public, and the live branch below WOULD serve it: a date with
        # no published row is built from the multibook store on the spot and
        # comes back as provisional picks. So a date after the last public
        # date (config/ufc_public_card.json, read through ufc_public_card)
        # is answered here, before the cache and before anything that reads
        # the store or the ledger, with no picks and the reason. Nothing is
        # built, so there is nothing to cache and no stale entry to serve.
        #
        # A date on or before the cut-off falls through untouched: frozen
        # rows, the live card for a date not yet published, the cache, all
        # exactly as they were. An unreadable config is NOT "no pause": the
        # helper falls back to the owner's own date, so a deploy without
        # config/ still pauses (the image did not copy it when this was
        # written).
        #
        # A plain page_view, not a value action: no product content was
        # served, and `surface` is what makes a request count toward a
        # tester's activation and the per-feature numbers.
        paused = ufc_public_card.paused_card(date)
        if paused is not None:
            _record_page_view(request, route, date)
            return paused

        from src.report import ufc_card

        def _rebuild():
            return ufc_card.card_for_date(date, now=datetime.now(timezone.utc))

        payload, _meta = _mma_card_cache.get(("mma_card", date), _rebuild)
        _record_page_view(request, route, date, surface="card", sport="mma")
        return payload

    resolved_rule = _resolve_rule(rule)

    # MLB, rule v2: the PREVIEW path (T5). Kept entirely separate from the
    # branch below so `rule=None`/`rule="v1"` -- every existing caller --
    # reaches the untouched v1 code and gets the untouched v1 byte shape.
    if resolved_rule == "v2":
        return _build_payload_v2(date, request, route)

    # MLB: existing code path (default)
    now = datetime.now(timezone.utc)

    frozen = card_mod.frozen_card(date)
    if frozen is not None:
        frozen["date"] = date
        frozen["generated_at"] = now.isoformat()
        frozen["model_basis"] = strength.MODEL_BASIS
        # The grade legend rides every card, frozen or live. This branch
        # returns before src/report/card.py's card_for_date (which is where
        # the live path attaches it), so it is attached here too -- a
        # frozen card's picks carry the grade they were frozen with, and the
        # page needs the legend to read it.
        frozen["knowledge_legend"] = list(grade.legend())
        # An honest freshness block for a row that is frozen ON PURPOSE. It
        # describes when this payload was BUILT, which for a frozen card is
        # when it was published -- not how old the prices on it are. The page
        # warns about price age separately (web/js/card.js's
        # `card-stale-prices`), and conflating the two would either cry stale
        # about a card doing exactly what it promised, or hide a genuinely
        # old quote behind a fresh-looking build time.
        published = frozen.get("frozen_at")
        age_s = None
        if published:
            try:
                age_s = (now - datetime.fromisoformat(published)).total_seconds()
            except (TypeError, ValueError):
                age_s = None
        frozen["freshness"] = {
            "served_at": now.isoformat(),
            "built_at": published,
            "age_s": age_s,
            "stale": False,
            "stale_reason": None,
        }
        _record_page_view(request, route, date, surface="card")
        return frozen

    # The LIVE (not yet published) branch is cached per date, like the NFL and
    # UFC cards (2026-09-21). On staging it cost about 3 s on every request,
    # and the day's card is served from here until its first publish. Only
    # this branch is cached: the frozen check above runs first on every
    # request, so a card published a second ago is served immediately.
    def _rebuild_live():
        entries, _notes, meta = _build_entries(date)
        # The moneyline board comes from the SAME builder the price board uses,
        # so the card and the board can never quote different best prices for
        # the same bet on the same page.
        opportunities = opportunities_mod.build_opportunities(
            entries, date=date, now=now)
        built = card_mod.card_for_date(
            entries, opportunities.get("rows") or [], date=date, now=now)
        built["freshness"] = meta
        return built

    payload, _meta = _mlb_live_card_cache.get(("mlb_live_card", date), _rebuild_live)
    _record_page_view(request, route, date, surface="card")
    return payload


def _build_payload_v2(date: str, request: Optional[Request], route: str) -> dict:
    """The V2 preview payload for one date (T5, `?rule=v2`).

    Serves the FROZEN row when V2 has published one for this date (same
    "check the ledger first" shape `_build_payload`'s v1 branch uses, for
    the identical reason -- see that function's docstring), and builds live
    otherwise. Nothing publishes V2 before T0's registration commit, so in
    practice every request through this path today builds live; the frozen
    branch exists so this route does not need to change again the day T6
    starts writing rows.

    `CardV2Error` (the frozen-parameter file missing or unreadable) is a 503,
    not a 500 and not a quietly empty card: V2 cannot be built at all
    without its own fitted numbers, and that is an operational fact about
    this deployment, not a fact about tonight's board.
    """
    from src.report import card_v2

    now = datetime.now(timezone.utc)

    frozen = card_v2.frozen_card_v2(date)
    if frozen is not None:
        frozen["generated_at"] = now.isoformat()
        _record_page_view(request, route, date, surface="card")
        return frozen

    entries, _notes, meta = _build_entries(date)
    opportunities = opportunities_mod.build_opportunities(
        entries, date=date, now=now)
    try:
        payload = card_v2.card_v2_for_date(
            entries, opportunities.get("rows") or [], date=date, now=now)
    except card_v2.CardV2Error as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    payload["freshness"] = meta
    _record_page_view(request, route, date, surface="card")
    return payload


def _day_is_fully_settled(day: dict) -> bool:
    """True only for a history day with NOTHING left to grade.

    A `card_settled` row can exist while some of its picks are still
    UNRESOLVED (partial settlement: an afternoon game final, an evening game
    not yet played). Such a row's `picks` list names the bets still awaiting
    their game -- tonight's paid picks -- so a day is public only when no pick
    on it is unresolved, by its own counters AND by a scan of the pick lists
    themselves (the counters are derived by `settle`; the lists are what would
    leak). V2's `graded` entries are scanned the same way."""
    from src.appstate import card_ledger

    for counter in ("unresolved", "prop_unresolved", "total_unresolved"):
        if day.get(counter):
            return False
    for key in ("picks", "prop_picks", "total_picks", "graded"):
        for pick in day.get(key) or ():
            if isinstance(pick, dict) and pick.get("result") == card_ledger.RESULT_UNRESOLVED:
                return False
    return True


def _public_history(payload: dict) -> dict:
    """`payload` (a card_ledger.history / history_v2 result) reduced to what an
    unauthenticated reader may see: SETTLED days only.

      * `pending_days` -- published cards with no settlement, i.e. tonight's
        picks with their books and prices -- is emptied. It exists for the
        record page's calendar; the calendar simply shows no future day.
      * a day whose settlement still has an unresolved pick is withheld
        until it resolves (see _day_is_fully_settled).
      * `total_days`/`truncated` are recomputed so a reader is never told
        about days the response hides; `withheld_days` says how many there
        were, and the page need not show it.

    Fail-closed: anything unexpected about the payload's shape leaves `days`
    as the settled-only filter produces it, never as the raw input."""
    out = dict(payload)
    days = list(out.get("days") or [])
    kept = [d for d in days if isinstance(d, dict) and _day_is_fully_settled(d)]
    withheld = len(days) - len(kept)
    out["days"] = kept
    out["pending_days"] = []
    out["withheld_days"] = withheld
    if "total_days" in out and isinstance(out["total_days"], int):
        out["total_days"] = max(out["total_days"] - withheld, len(kept))
    out["truncated"] = bool(out.get("truncated")) and out.get("total_days", 0) > len(kept)
    return out


def _mark_postseason(payload: dict) -> dict:
    """Each V2 entry gains `postseason: true/false`, decided the way the
    counted record decides it (src.report.effective_record: the results
    store, plus the ledger's own evidence -- a game frozen with a non-"R"
    type, or a card dated inside this season's postseason calendar).

    The page cannot work this out itself. A prop entry freezes
    `game_type: "R"` unconditionally, so the record page tagged the two
    moneyline fills of 2026-09-30 "postseason, not counted" and left the three
    prop fills on the very same games looking like regular-season entries.
    Copies the days and entries it marks; the ledger rows are not touched. Any
    failure leaves the payload exactly as it came."""
    try:
        from src.report import effective_record as er
        days = payload.get("days") or []
        pks = er._postseason_game_pks() | (
            er._ledger_postseason_pks({"days": days}) - er._regular_game_pks(_results_store()))
        marked = []
        for day in days:
            entries = [dict(e, postseason=er._is_postseason_entry(e, pks))
                       for e in (day.get("graded") or [])]
            marked.append(dict(day, graded=entries))
        return dict(payload, days=marked)
    except Exception:  # noqa: BLE001 -- a tag is never worth a 500 on the proof page
        return payload


def _results_store() -> dict:
    try:
        from src.pipeline import history as history_mod
        return history_mod.read_results()
    except Exception:  # noqa: BLE001
        return {}


# DECLARED BEFORE /card/{date}, because FastAPI matches routes in
# declaration order and "record" would otherwise be captured as a date and
# rejected by _validate_date as a 400. (Now also on a different router:
# app.py mounts `public_router` first, for the same reason.)
# THE TWO PUBLIC ROUTES ARE BUILT ONCE PER LEDGER STATE (2026-10-01).
#
# Both fold the whole ledger and verify its hash chain: about 0.15 s for the
# first rule and 0.9 s for the current one on a development machine, several
# times that on the one-CPU box. The landing page now calls /card/history for
# its sample card, so every visitor would have paid that. The answer only
# changes when a ledger changes, so it is kept under the same key GET /meta
# uses (api.meta._ledger_signature: the size and modification time of every
# file the record is read from) plus the request's own arguments. A
# settlement is picked up on the next request; nothing is served from a stale
# ledger. Page views are still recorded on every request, outside the cache.
_PUBLIC_MEMO: dict = {}
_PUBLIC_MEMO_LOCK = __import__("threading").Lock()
_PUBLIC_MEMO_MAX = 256


def _memo_public(kind: str, args: tuple, build):
    from api import meta as meta_api
    state = meta_api._ledger_signature()
    key = (kind, args)
    with _PUBLIC_MEMO_LOCK:
        if _PUBLIC_MEMO.get("state") != state:
            _PUBLIC_MEMO.clear()
            _PUBLIC_MEMO["state"] = state
        hit = _PUBLIC_MEMO.get(key)
    if hit is not None:
        return hit
    value = build()           # a 400 raised here is never cached
    with _PUBLIC_MEMO_LOCK:
        if _PUBLIC_MEMO.get("state") == state and len(_PUBLIC_MEMO) <= _PUBLIC_MEMO_MAX:
            _PUBLIC_MEMO[key] = value
    return value


def reset_public_cache_for_tests() -> None:
    with _PUBLIC_MEMO_LOCK:
        _PUBLIC_MEMO.clear()


@public_router.get("/card/record", dependencies=[Depends(_rate_limit_public_record)])
def get_card_record(request: Request = None, sport: str = "mlb",
                    rule: Optional[str] = None) -> dict:
    """GET /card/record: `_card_record_uncached`, once per ledger state."""
    payload = _memo_public("record", (sport, rule),
                           lambda: _card_record_uncached(None, sport, rule))
    _record_page_view(request, "card_record", None)
    return payload


@public_router.get("/card/history", dependencies=[Depends(_rate_limit_public_record)])
def get_card_history(request: Request = None, limit: int = DEFAULT_HISTORY_LIMIT,
                     sport: str = "mlb", rule: Optional[str] = None) -> dict:
    """GET /card/history: `_card_history_uncached`, once per ledger state."""
    payload = _memo_public("history", (limit, sport, rule),
                           lambda: _card_history_uncached(None, limit, sport, rule))
    _record_page_view(request, "card_history", None)
    return payload


# EXAMPLE ACCOUNTS (2026-10-03). `GET /card/accounts` answers "what would a
# bankroll be today if it had bet every published pick since 2026-09-22",
# per sport and for all sports, for the few accounts in
# config/example_accounts.json. The arithmetic is src/appstate/
# example_accounts.py (pure); this block only gathers its inputs.
#
# IT READS NOTHING THE RECORD PAGE HAS NOT ALREADY READ. Production has
# OOM'd on whole-store reads, so the three records and the three histories
# come from the very memo entries GET /card/record and GET /card/history fill
# for the record page: the same keys ("record", (sport, None)) and
# ("history", (60, sport, None)), so a visitor who opens the page costs the
# box one build of each, not two. The one exception is a day that is only
# partly settled: the public history withholds it (it would list tonight's
# unplayed picks), yet the record counts its finished picks, so the two would
# differ by that day. Only then is the sport's settled rows read once more,
# and only their results and units are used, never a pick's name.
#
# Memoised per ledger state like the other public routes, plus the config
# file's own size and time, so editing an account is picked up. An answer that
# fails to reconcile IS cached (it is a fact about the ledger state); an
# unexpected exception is not, and the visitor gets the one-sentence answer.
ACCOUNTS_HISTORY_LIMIT = 60          # what web/js/cardrecord.js asks for


def _accounts_config_signature() -> tuple:
    from src.appstate import example_accounts
    try:
        stat = os.stat(example_accounts.CONFIG_PATH)
        return (stat.st_size, stat.st_mtime_ns)
    except OSError as exc:
        return (type(exc).__name__,)


def _accounts_unfiltered_days(ledger_sport: str) -> list:
    """Every settled day of one sport, partly settled ones included, exactly
    as the record counts them. Used only while a day is partly settled."""
    from src.appstate import card_ledger
    if ledger_sport == "mlb":
        days = card_ledger.history_v2(limit=None)["days"]
        return _mark_postseason({"days": days})["days"]
    if ledger_sport == "nfl":
        return card_ledger.history(limit=None, sport="nfl", rule=_resolve_nfl_rule(None))["days"]
    return card_ledger.history(limit=None, sport=ledger_sport)["days"]


def _accounts_days(ledger_sport: str) -> list:
    from src.appstate import example_accounts
    limit = ACCOUNTS_HISTORY_LIMIT
    history = _memo_public("history", (limit, ledger_sport, None),
                           lambda: _card_history_uncached(None, limit, ledger_sport, None))
    if history.get("truncated"):
        limit = MAX_HISTORY_LIMIT
        history = _memo_public("history", (limit, ledger_sport, None),
                               lambda: _card_history_uncached(None, limit, ledger_sport, None))
        if history.get("truncated"):
            raise example_accounts.AccountsError(
                "The record has more days than this page follows, so nothing is shown.")
    if history.get("withheld_days"):
        return _accounts_unfiltered_days(ledger_sport)
    return history.get("days") or []


def _accounts_sources() -> dict:
    from src.appstate import example_accounts as ea
    sources = {}
    for view, ledger_sport in ea.LEDGER_SPORT.items():
        record = _memo_public("record", (ledger_sport, None),
                              lambda s=ledger_sport: _card_record_uncached(None, s, None))
        if record.get("chain_ok") is not True:
            raise ea.AccountsError(
                f"The {ea.VIEW_LABEL[view]} record does not pass its tamper check right now, "
                "so nothing is shown.")
        if view == "mlb" and record.get("rule") != "v2":
            raise ea.AccountsError("The MLB record is not on the current rule, so nothing is shown.")
        days = _accounts_days(ledger_sport)
        if view == "mlb":
            rows, waiting = ea.rows_from_v2_days(days, view)
        else:
            rows, waiting = ea.rows_from_v1_days(days, view)
        sources[view] = {"rows": rows, "waiting": waiting,
                         "reference": ea.reference_from_record(view, record)}
    return sources


def _accounts_pending() -> list:
    """Published picks still waiting on their games, as a count per sport and
    never a name: the figure /meta already publishes (effective_record's
    `pending_count`), read from /meta's own per-ledger-state memo."""
    from src.appstate import example_accounts as ea
    try:
        from api import meta as meta_api
        sports = (meta_api._record_parts().get("effective_record") or {}).get("sports") or {}
    except Exception:  # noqa: BLE001 -- no count is better than a wrong one
        return []
    pending = []
    for view, ledger_sport in ea.LEDGER_SPORT.items():
        count = ((sports.get(ledger_sport) or {}).get("current") or {}).get("pending_count")
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            pending.append({"sport": view, "picks": count})
    return pending


def _accounts_uncached() -> dict:
    from src.appstate import example_accounts as ea
    try:
        config = ea.load_config()
        payload = ea.build_payload(config, _accounts_sources(), pending=_accounts_pending())
    except ea.AccountsError as exc:
        payload = ea.unavailable(str(exc))
    if not payload.get("available"):
        _log.warning("example accounts unavailable: %s %s", payload.get("reason"),
                     {k: v.get("problems") for k, v in (payload.get("reconciled") or {}).items()
                      if not v.get("ok")})
    return payload


@public_router.get("/card/accounts", dependencies=[Depends(_rate_limit_public_record)])
def get_card_accounts() -> dict:
    """GET /card/accounts: what a bankroll would be today had it bet every
    published pick since the start date, or `{"available": false, ...}` when
    the numbers do not reconcile with the published record. Public, no token,
    settled days only, and nothing about any user."""
    from src.appstate import example_accounts as ea
    try:
        return _memo_public("accounts", (_accounts_config_signature(),), _accounts_uncached)
    except Exception:  # noqa: BLE001 -- the public page never gets a 500 for this
        _log.exception("example accounts failed unexpectedly")
        return ea.unavailable("The record could not be read right now, so nothing is shown.")


def _card_record_uncached(request: Request = None, sport: str = "mlb",
                          rule: Optional[str] = None) -> dict:
    """The card's public record: every settled day, pooled.

    Pooling is correct here and is not the pooling mistake this repo warns
    about elsewhere. The card is ONE system with ONE rule, so its picks are
    one population; the warning is about pooling different systems, where a
    control and a forward test average into a number describing neither.
    That is still true within V2's own record (`rule=v2`, `sport=mlb` only)
    -- what changes is that V2 has TWO price classes and a fills population,
    reported apart from each other and never summed into one figure a
    reader could mistake for the rule's own result (registration R5).

    For sport=nfl, `rule` is an NFL rule id instead (src/report/nfl_card.
    RULES, default the live one) -- see `_resolve_nfl_rule`.

    The chain is verified on every request and reported. A published record
    whose hash chain is broken is not a record, and the page showing it has
    to be able to say so rather than keep printing the totals.
    """
    from src.appstate import card_ledger

    _validate_sport(sport)
    # NFL's ledger holds two rules since 2026-09-20; the page shows one at a
    # time (default the live one, src/report/nfl_card.LIVE_RULE; `?rule=`
    # names the retired one), never the two pooled.
    nfl_rule = _resolve_nfl_rule(rule) if sport == "nfl" else None
    resolved_rule = None if sport == "nfl" else _resolve_rule(rule)

    if sport == "mlb" and resolved_rule == "v2":
        payload = card_ledger.record_v2()
        payload["rule"] = "v2"
        payload["basis"] = best_bets_card.BASIS
        payload["disclaimer"] = best_bets_card.DISCLAIMER
        payload.update(_effective_record_extras("mlb", None))
        # POSTSEASON, GRADED BUT NOT COUNTED (owner ruling, registration
        # 11.1; docs/PREREG_CARD_V2.md lines 1087-1089 and 3203-3205).
        # `effective_record`'s V2 cohort already keeps the counted and
        # postseason slices apart (read once here, rather than re-deriving
        # a second split of the same graded entries by hand) -- see that
        # module's own `_v2_cohort`/`_postseason_game_pks`.
        from src.report import effective_record
        current_cohort = effective_record.sport_snapshot("mlb").get("current") or {}
        payload["postseason"] = current_cohort.get("postseason")
        payload["counted_scope"] = current_cohort.get("counted_scope")
        # FLAT ALIASES (found during task B1's verification pass,
        # 2026-09-25; not introduced by it; extended 2026-09-28 for the
        # postseason split above). Three separate readers of this exact
        # route -- web/js/card.js's recordLine (the strip under tonight's
        # picks), web/js/recordstrip.js's renderCardRecordStrip (the
        # picks-page strip) and web/js/cardrecord.js's detail page -- all
        # read `rec.wins`/`rec.losses`/`rec.n_staked`/`rec.days`/
        # `rec.profit_units`/`rec.win_rate`/`rec.roi_pct` at the TOP level.
        # That was true for V1's `record()`, which has always returned that
        # shape flat. `record_v2()` never did -- it reports main-band,
        # plus-money and fills apart under `main`/`plus_money`/`fills`/
        # `combined` on purpose (R5: never pooled into one misleading
        # figure) -- so every one of those three readers silently read
        # `undefined` for `n_staked`/`days` the moment `ACTIVE_CARD_RULE`
        # became "v2" (CUTOVER_DATE 2026-09-23) and this became the
        # DEFAULT response for `GET /card/record` with no `?rule=` at all.
        # `recordLine`'s own `!rec.n_staked` guard then rendered "Nothing
        # graded yet" -- FALSE; MLB's real V2 record right now is 14-15,
        # -4.73u over 3 nights -- exactly the kind of confident-but-wrong
        # claim this product exists to never make.
        #
        # THESE ALIASES NOW READ THE COUNTED FIGURE (regular season only),
        # not `combined` -- `combined` still pools postseason in (main-band
        # + plus-money PICKS, fills excluded), unchanged, exactly as
        # `record_v2()` returns it, so a caller reading the nested shape
        # directly sees no change; only what the FLAT top-level keys alias
        # to has moved, from `combined` to `effective_record`'s counted V2
        # headline -- the same population `src.report.effective_record`'s
        # cohort now reports for the identical "never let a postseason
        # pick inflate the public record" reason (see that module's
        # `counted_scope`). On today's ledger, with no postseason picks
        # graded yet, the two are numerically identical.
        for _key in ("days", "wins", "losses", "pushes", "voids",
                    "n_staked", "profit_units", "win_rate", "roi_pct"):
            payload[_key] = current_cohort.get(_key)
        _record_page_view(request, "card_record", None)
        return payload

    if sport == "nfl":
        from src.report import nfl_card as nfl_report
    payload = card_ledger.record(sport=sport, rule=nfl_rule)
    # THE CHAIN OF THE LEDGER THIS RECORD WAS READ FROM (review,
    # 2026-09-20). A bare `verify()` walks MLB's file, so the NFL record
    # page said "338 entries so far ... That chain verifies right now" off
    # MLB's ledger (the NFL file had 9 rows), and a tampered NFL file still
    # read as verified. MLB keeps `verify()` exactly as before.
    chain = card_ledger.verify(sport=None if sport == "mlb" else sport)
    payload["chain_ok"] = bool(getattr(chain, "ok", True))
    payload["chain_detail"] = None if payload["chain_ok"] else str(chain)
    payload["rows_checked"] = getattr(chain, "rows_checked", None)
    # THE SAME WORDS THE CARD ITSELF SHOWS, sourced from the one constant
    # both surfaces read -- never a second hand-written sentence on the
    # record page that could quietly drift from daily_card.CARD_DISCLAIMER
    # and end up contradicting it.
    if sport == "mlb":
        payload["disclaimer"] = daily_card.CARD_DISCLAIMER
        payload["basis"] = daily_card.CARD_BASIS
        # This branch only serves V1's OWN record (either ACTIVE_CARD_RULE
        # is still "v1", or the caller explicitly asked for the retired
        # rule via ?rule=v1) -- V1 was the first rule this product ever
        # published under, so it has no rule before it.
        payload["previous_rule"] = None
    elif sport == "nfl":
        payload["sport"] = "nfl"
        payload["rule"] = nfl_rule
        payload["live_rule"] = nfl_report.LIVE_RULE
        payload["notice"] = nfl_report.NOTICE
        payload["previous_rule"] = _previous_rule_cohort("nfl", nfl_rule)
    elif sport == "mma":
        from src.report import ufc_card as ufc_report
        payload["sport"] = "mma"
        payload["rule"] = ufc_report.RULE_ID
        payload["notice"] = ufc_report.NOTICE
        payload["basis"] = ufc_report.ufc_rule.CARD_BASIS
        payload["disclaimer"] = ufc_report.ufc_rule.CARD_DISCLAIMER
        # UFC_CARD_V1 is the only rule UFC has ever published under (see
        # src.report.ufc_card's module docstring) -- never a previous one.
        payload["previous_rule"] = None
    _record_page_view(request, "card_record", None)
    return payload


# ALSO DECLARED BEFORE /card/{date}, for the identical reason /card/record
# is above: "history" would otherwise be matched as a date and 400 out of
# _validate_date. See that route's comment and tests/test_api_card.py.
def _card_history_uncached(request: Request = None, limit: int = DEFAULT_HISTORY_LIMIT,
                           sport: str = "mlb", rule: Optional[str] = None) -> dict:
    """Every settled day, newest first -- the day-by-day detail behind
    /card/record's pooled totals: each day's picks, results, prices, books
    and profit, plus that day's published row_hash.

    `limit` is validated here rather than left to FastAPI's own coercion --
    same reasoning as api/daily.py's get_daily_index: a direct function
    call (this codebase's own test style) never runs FastAPI's
    request-parsing layer at all, so an out-of-range value has to be
    caught by hand to be caught the same way in both call paths.
    """
    from src.appstate import card_ledger

    _validate_sport(sport)
    nfl_rule = _resolve_nfl_rule(rule) if sport == "nfl" else None
    resolved_rule = None if sport == "nfl" else _resolve_rule(rule)

    if limit < 1 or limit > MAX_HISTORY_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"limit must be between 1 and {MAX_HISTORY_LIMIT} (got {limit!r})")

    if sport == "mlb" and resolved_rule == "v2":
        payload = _mark_postseason(_public_history(card_ledger.history_v2(limit=limit)))
        _record_page_view(request, "card_history", None)
        return payload

    if sport == "nfl":
        from src.report import nfl_card as nfl_report
        # One rule's days only, published AND settled: card_ledger.history
        # leaves another rule's dates out of `pending_days` too, so a V1 date
        # never shows on the V2 calendar as PENDING (review, 2026-09-20).
        payload = card_ledger.history(limit=limit, sport=sport, rule=nfl_rule)
        payload["sport"] = "nfl"
        payload["rule"] = nfl_rule
        payload["live_rule"] = nfl_report.LIVE_RULE
        payload["notice"] = nfl_report.NOTICE
    elif sport == "mma":
        from src.report import ufc_card as ufc_report
        payload = card_ledger.history(limit=limit, sport=sport)
        payload["sport"] = "mma"
        payload["rule"] = ufc_report.RULE_ID
        payload["notice"] = ufc_report.NOTICE
    else:
        payload = card_ledger.history(limit=limit, sport=sport)
    payload = _public_history(payload)
    _record_page_view(request, "card_history", None)
    return payload


@router.get("/card/{date}")
def get_card_for_date(date: str, request: Request = None,
                      sport: str = "mlb", rule: Optional[str] = None) -> dict:
    return _build_payload(date, request, "card", sport=sport, rule=rule)


@router.get("/card")
def get_card_today(request: Request = None, sport: str = "mlb",
                   rule: Optional[str] = None) -> dict:
    return _build_payload(date_cls.today().isoformat(), request, "card",
                         sport=sport, rule=rule)
