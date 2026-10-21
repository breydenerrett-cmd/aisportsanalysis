"""The member "Gematria" base style: a member's hound that picks by the SAME engine and the SAME active rules as the house
Gematria Hound (``src/hounds/gematria``), on the member's own sports, bets a day, stake and name.

WHAT THE MEMBER CHOOSES AND WHAT THEY DO NOT
--------------------------------------------
The member chooses the name, tagline, colour, badge, sports, most bets a day and stake, like any hound. Everything that
decides a pick is NOT theirs to change: the margin, the thresholds, the ciphers, the weights and the price band come from
``config/gematria/active.json``'s rules file, read at pick time by the same ``GematriaRuntime`` the house hound runs. There is
no second copy of the logic here, so the two can never drift: this module only (1) rebuilds the house runner's inputs for a
member's game (a point-in-time ``Context`` and the lock board, through ``pack.base``'s own functions), (2) asks the runtime to
weigh the game, and (3) turns a "bet" verdict into the candidate the user engine writes.

THE SPEC (a version-2 spec with ``style: "gematria"``)
------------------------------------------------------
``validate_spec`` hands a raw spec with that style to ``normalize`` below, which returns the spec's fixed parts:

  sports           the member's, from the dog menu
  rules            ONE canonical rule, derived (never typed): moneyline, either side, the stamped rules' price band, 3 books,
                   no conditions. It exists so every reader that walks ``spec["rules"]`` (the kennel feed, the stats, the
                   sports gate) keeps working; the engine never evaluates it as a rule, ``hound_candidates`` of the generic
                   engine returns nothing for this style (user_engine_v2), and the published sentence says what really runs.
  lock_minutes     the rules' own (60), nothing else is accepted
  gematria         ``{rules_version, rules_hash}`` stamped at creation: which rules the hound was made under. It is part of
                   the spec hash. It must name a rules file this program holds, so a made-up stamp is refused.

WHICH RULES A BET USES. The engine weighs under the ACTIVE rules, exactly as the house hound does, and every bet row carries the
``rules_version`` / ``rules_hash`` it was actually made under (and the evidence block, with both sides' matches). When the
house moves to ``rules_v2`` a member hound made under v1 follows it, and its bet rows say so from that day. The creation
stamp stays in the spec as the record of what the member saw when they made it.

PASSES. The engine's own reasons are kept as counts on the engine report (``gematria_no_history``, ``gematria_small_margin``
...). A sport with no facts or no stored results passes with those reasons; nothing is guessed, and a game is never invented.

FORWARD ONLY, PAPER ONLY. A replay is refused (the house hound refuses one too: ``ai_defs.GEMATRIA_FORWARD_ONLY_MESSAGE``). The
preview (``preview``) is a read-only look at today's board and writes nothing. The kill switch ``GEMATRIA_HOUND=off`` stops
member Gematria hounds exactly as it stops the house hound. Nothing here places or suggests a real bet, and a price of -200 or
worse is vetoed by the decision itself and again by the user engine.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

STYLE = "gematria"
STYLE_LABEL = "Gematria"
HOUSE_HOUND_ID = "gematria"
HOUSE_HOUND_NAME = "Gematria Hound"
HOUSE_HOUND_HREF = "hound.html?id=gematria"
CATEGORY = "numerology"
CANONICAL_LABEL = "Gematria"
MARKET = "moneyline"

PASS_PREFIX = "gematria_"
FORWARD_ONLY_CODE = "gematria_forward_only"
OFF_CODE = "gematria_switched_off"

#: Plain, claim-free copy. The one-paragraph explanation the builder shows, and the short line the quiz card carries.
EXPLAINER = (
    "Gematria reads the numbers in a game. For each team it works out what the numbers in names, cities, mascots, the date "
    "and our stored results would say if that team won: letter values, win and loss counts, streaks, days since the last "
    "win. Every time two of those numbers match, that is one piece of evidence. Your hound backs the side with clearly more "
    "matches, on moneylines only, an hour before the start, and passes when the data is thin, the sides are too close or the "
    "price is -200 or worse. It uses the same rules as the house Gematria Hound, so the two never drift apart. It is a "
    "for-fun style: nothing here claims that numbers predict games, and every pick is paper and graded in public.")
QUIZ_LINE = "Reads the numbers in names, dates and streaks. Bets when they line up."

_STAMP_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,24}$")
_STAMP_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def is_gematria(spec: Mapping) -> bool:
    return isinstance(spec, Mapping) and spec.get("style") == STYLE


def enabled(env: Optional[Mapping] = None) -> bool:
    """The kill switch, shared with the house hound: ``GEMATRIA_HOUND=off`` (also 0, false, no) stops both."""
    from src.hounds.gematria import runtime as gem_rt

    return gem_rt.enabled(env)


# ---------------------------------------------------------------------------
# the rules a hound is stamped with
# ---------------------------------------------------------------------------

_rules_cache: dict = {}


def _rules_file(name: Optional[str] = None):
    from src.hounds.gematria import rules as rules_mod

    fname = name or rules_mod.active_file()
    return fname, rules_mod.config_dir() / fname


def load_rules(name: Optional[str] = None):
    """The parsed rules of one file (the active one by default), cached by file modification time."""
    from src.hounds.gematria import rules as rules_mod

    fname, path = _rules_file(name)
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return rules_mod.load(fname)           # raises RulesError with the reason
    hit = _rules_cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    rules = rules_mod.load(fname)
    _rules_cache[str(path)] = (key, rules)
    return rules


def active_stamp() -> dict:
    """``{rules_version, rules_hash}`` of the rules the house hound runs under today."""
    rules = load_rules()
    return {"rules_version": rules.version, "rules_hash": rules.rules_hash}


def known_rules() -> dict:
    """{(version, hash): Rules} for every rules file on disk (a spec's stamp must be one of them)."""
    from src.hounds.gematria import rules as rules_mod

    out: dict = {}
    folder = rules_mod.config_dir()
    try:
        names = sorted(p.name for p in folder.glob("rules_*.json"))
    except OSError:
        names = []
    for name in names:
        try:
            r = load_rules(name)
        except Exception:  # noqa: BLE001 -- a bad rules file is simply not a known stamp
            continue
        out[(r.version, r.rules_hash)] = r
    return out


def rules_for(stamp: Optional[Mapping]):
    """The Rules a stamp names (the stamped file), or the active ones when the stamp is missing or unknown."""
    if isinstance(stamp, Mapping):
        hit = known_rules().get((stamp.get("rules_version"), stamp.get("rules_hash")))
        if hit is not None:
            return hit
    return load_rules()


# ---------------------------------------------------------------------------
# validation (called by user_spec._validate_v2)
# ---------------------------------------------------------------------------

def canonical_rule(sports: list, rules) -> dict:
    """The one rule a Gematria spec carries. Derived from the stamped rules, never typed."""
    from src.hounds.pack import base

    lo, hi = rules.decision.price_band
    return {"label": CANONICAL_LABEL, "sports": list(sports), "markets": [MARKET], "side": "either",
            "price_min": int(max(base.PRICE_MIN, lo)), "price_max": int(min(base.PRICE_MAX, hi)),
            "line_min": None, "line_max": None, "min_books": int(base.MIN_BOOKS), "when": None}


def normalize(raw: Mapping, errors: dict) -> Optional[dict]:
    """The fixed parts of a Gematria spec, or None with the reasons in ``errors``.

    Returns ``{sports, stamp, rules, rule, lock_minutes}``. ``raw["rules"]`` is accepted on input (so a spec can be POSTed back
    as read) but only to be REPLACED by the canonical rule; a rule carrying conditions or a market other than the
    moneyline is refused, because the engine would not read them and a published rule must be what ran."""
    from src.hounds import user_spec

    stamp_raw = raw.get("gematria")
    stamp = None
    if stamp_raw is None:
        stamp = active_stamp()
    elif (isinstance(stamp_raw, Mapping) and set(stamp_raw) == {"rules_version", "rules_hash"}
          and isinstance(stamp_raw["rules_version"], str) and _STAMP_VERSION_RE.match(stamp_raw["rules_version"])
          and isinstance(stamp_raw["rules_hash"], str) and _STAMP_HASH_RE.match(stamp_raw["rules_hash"])
          and (stamp_raw["rules_version"], stamp_raw["rules_hash"]) in known_rules()):
        stamp = {"rules_version": stamp_raw["rules_version"], "rules_hash": stamp_raw["rules_hash"]}
    else:
        errors["gematria"] = "must name a Gematria rules version this program holds"
    rules_raw = raw.get("rules")
    given_sports: list = []
    if rules_raw not in (None, []):
        if not isinstance(rules_raw, (list, tuple)) or len(rules_raw) != 1 or not isinstance(rules_raw[0], Mapping):
            errors["rules"] = "the Gematria style has one fixed rule; leave it as it is"
        else:
            one = rules_raw[0]
            if one.get("when"):
                errors["rules"] = "the Gematria style takes no extra conditions; its rule is fixed"
            elif any(m != MARKET for m in (one.get("markets") or [MARKET])):
                errors["rules"] = "the Gematria style bets moneylines only"
            else:
                given_sports = one.get("sports") or []
    sports = user_spec.normalize_sports(raw["sports"] if raw.get("sports") is not None else given_sports)
    if sports is None:
        errors["sports"] = user_spec.sports_error_text()
    elif raw.get("sports") is not None and given_sports and user_spec.normalize_sports(given_sports) != sports:
        errors["sports"] = "the Gematria rule covers the hound's sports; change the sports, not the rule"
    markets = raw.get("markets")
    if markets is not None and list(markets if isinstance(markets, (list, tuple)) else [markets]) != [MARKET]:
        errors["markets"] = "the Gematria style bets moneylines only"
    rank = raw.get("rank_by")
    if rank is not None and rank != "earliest_lock":
        errors["rank_by"] = "the Gematria style takes the earliest games first"
    if errors.get("gematria") or errors.get("rules") or sports is None or stamp is None:
        return None
    rules = rules_for(stamp)
    lock = int(rules.decision.lock_minutes)
    given_lock = raw.get("lock_minutes")
    if given_lock is not None and given_lock != lock:
        errors["lock_minutes"] = f"the Gematria style weighs each game {lock} minutes before the start"
        return None
    rule = canonical_rule(sports, rules)
    return {"sports": sports, "stamp": stamp, "rules": [rule], "rule": rule, "lock_minutes": lock}


# ---------------------------------------------------------------------------
# the published rule
# ---------------------------------------------------------------------------

def _price(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


def rule_sentence(spec: Mapping) -> str:
    """The Gematria style's rule in plain English, from the stamped rules and the spec's sports. Pure."""
    from src.hounds import user_spec

    rules = rules_for(spec.get("gematria"))
    d = rules.decision
    lo, hi = spec["rules"][0]["price_min"], spec["rules"][0]["price_max"]
    sports = user_spec.sports_phrase(spec["rules"][0]["sports"])
    return (
        f"{CANONICAL_LABEL}: {sports} moneylines. For each team it works out what the numbers would say if that team won "
        "(the cipher values of names, cities and mascots, the number of the date, how far the game is from a founding "
        "date, and counts from our stored results such as records, streaks and days since a win); each time two of those "
        f"numbers match is one piece of evidence. It backs the side with the larger total only if it leads by at least "
        f"{d.min_margin:g}, both sides had enough stored results to count, and the side's average price is between "
        f"{_price(lo)} and {_price(hi)} (never -200 or worse); otherwise it passes. It runs the house Gematria Hound's "
        f"rules ({rules.version}) and makes no claim that numbers predict games.")


def fixed_text(fixed: Mapping) -> str:
    """The builder's one line of what the style fixes (the page shows it as is): lock, market, price band, rules version."""
    parts = []
    if fixed.get("lock_minutes"):
        parts.append(f"it weighs each game {fixed['lock_minutes']} minutes before the start")
    parts.append("on moneylines only")
    band = fixed.get("price_band")
    if band:
        parts.append(f"at an average price between {_price(band[0])} and {_price(band[1])} (never -200 or worse)")
    if fixed.get("rules_version"):
        parts.append(f"under the house hound's rules {fixed['rules_version']}")
    return "Fixed by the style: " + ", ".join(parts) + ". It passes when the data is thin."


def global_sentences(spec: Mapping) -> list:
    bets, stake = spec["max_bets_per_day"], spec["stake_units"]
    return [
        f"{spec['lock_minutes']} minutes before the start it weighs each game once, from the board as it stood then and "
        "the results stored by then (nothing newer).",
        f"At most {bets} {'bet' if bets == 1 else 'bets'} a day, the earliest games first.",
        f"Each bet is {stake:g} paper unit{'' if stake == 1 else 's'}, graded at the average price.",
    ]


# ---------------------------------------------------------------------------
# weighing a member's games with the house runtime
# ---------------------------------------------------------------------------

def _row_for(row: Mapping, observed: datetime) -> dict:
    return {**row, "market": "h2h", "observed_utc": observed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def make_runtime():
    """The house runtime, ledger-less: the same rules, facts and history source the house hound runs, and no decision log (a
    member's bet row carries the evidence). Tests replace this to run on synthetic facts and results."""
    from src.hounds.gematria import runtime as gem_rt

    return gem_rt.GematriaRuntime(ledger=None)


class Weigher:
    """One engine pass's view of the games: the house runner's inputs for each game, built once, weighed once.

    The boards the user engine holds (``GameBoards``) are turned back into the quotes ``pack.base`` reads, so the
    ``Context`` and the lock board come from ``pack.base.build_context`` / ``lock_board`` themselves: the same functions, on
    the same captured rows, as the house runner. ``runtime`` is injectable for tests; production builds the house
    ``GematriaRuntime`` with no ledger (a member's pass writes no decision log, the bet row carries the evidence)."""

    def __init__(self, games: Mapping, *, runtime=None, root: Optional[str] = None,
                 load_results: Optional[Callable] = None):
        self.games = games
        self._runtime = runtime
        self._root = root
        self._load_results = load_results
        self._stores = None
        self._loaded: set = set()
        self._memo: dict = {}

    @property
    def runtime(self):
        if self._runtime is None:
            self._runtime = make_runtime()
        return self._runtime

    def stores(self):
        from src.hounds.pack import base

        if self._stores is None:
            st = base.Stores(sports=tuple(sorted({g.sport.lower() for g in self.games.values()})) or base.DEFAULT_SPORTS)
            for eid, g in self.games.items():
                quotes = []
                for observed, rows in (g.captures.get("moneyline") or {}).items():
                    for row in rows:
                        q = base.quote_from_row(_row_for(row, observed))
                        if q is not None:
                            quotes.append(q)
                if not quotes:
                    continue
                st.quotes_by_event[eid] = quotes
                st.events[eid] = {"sport": g.sport.lower(), "away_name": g.away_team, "home_name": g.home_team,
                                  "commence": sorted(g._commence_by_obs.items()),
                                  **({"league_title": g.league_title} if g.league_title else {})}
            self._stores = st
        return self._stores

    def _ensure_results(self, sport: str) -> None:
        from src.hounds.pack import base

        if sport not in ("mlb", "nfl") or sport in self._loaded:
            return
        self._loaded.add(sport)
        loader = self._load_results or (lambda st, s: base.load_result_stores(st, root=self._root, mlb=(s == "mlb"),
                                                                              nfl=(s == "nfl")))
        loader(self.stores(), sport)

    def context(self, event_id: str):
        from src.hounds.pack import base

        game = self.games.get(event_id)
        if game is None:
            return None
        self._ensure_results(game.sport.lower())
        return base.build_context(self.stores(), event_id)

    def weigh(self, event_id: str, *, as_of: Optional[datetime] = None):
        """``(ctx, board, Weighed)`` for a game, or None when it has no usable board or start. ``as_of`` is only the
        preview's: a game not yet at its lock is read on the board as it stands (the lock board does not exist yet)."""
        from src.hounds.pack import base

        key = (event_id, as_of)
        if as_of is None and key in self._memo:          # a preview's moving clock is never memoised (it would only grow)
            return self._memo[key]
        ctx = self.context(event_id)
        out = None
        if ctx is not None:
            if as_of is None or as_of >= ctx.lock:
                board = base.lock_board(self.stores(), ctx)
            else:
                board = base.build_board(self.stores().quotes_by_event.get(event_id) or [], at=as_of, start=ctx.start,
                                         sport=ctx.sport)
            out = (ctx, board, self.runtime.weigh(ctx, board))
        if as_of is None:
            self._memo[key] = out
        return out


def _candidate(game, ctx, board, weighed, runtime) -> Optional[dict]:
    """The engine candidate for a "bet" verdict, with the evidence stamped for the bet row."""
    from src.hounds import user_engine as E
    from src.hounds.pack import base

    v = weighed.verdict
    info = base.side_info(board, MARKET, v.side)
    if info is None:
        return None
    price, best = int(info["price_average"]), int(info["price_best"])
    found = game.board_at(MARKET, ctx.lock)
    observed = found[0] if found else ctx.lock
    selection = E._selection_text(game, MARKET, v.side, None)
    n_books = int(info["book_count"])
    rules = runtime.rules
    reason = (f"Gematria: {v.reason}. It backed {selection} at the board average of {E._fmt_price(price)} across {n_books} "
              f"books; the best single price was {E._fmt_price(best)} at {info['book']}. Rules {rules.version}.")
    extra = {"gematria": weighed.block, "rules_version": rules.version, "rules_hash": rules.rules_hash,
             "confidence": v.confidence, "forward_only": True, "style": STYLE, "reason": reason}
    return {"side": v.side, "line": None, "price": price, "best_price": best, "best_book": info["book"],
            "n_books": n_books, "board_observed_utc": E._iso(observed),
            "board_age_minutes": round((ctx.lock - observed).total_seconds() / 60.0, 1), "selection": selection,
            "player": None, "rule_index": 0, "row_extra": extra}


def hound_candidates(hound: Mapping, spec: Mapping, games: Mapping, date: str, *, mode: str,
                     clock: Callable[[], datetime], seen_ids: set, skipped, considered: dict,
                     weigher: Weigher, env: Optional[Mapping] = None) -> list:
    """The candidates of one member Gematria hound on one slate date, in the shape ``user_engine.run`` ranks and writes:
    ``[(sortkey, lock_utc, event_id, market, game, commence, cand, bet_id)]``."""
    from src.hounds import user_engine as E

    if not enabled(env):
        skipped[OFF_CODE] += 1
        return []
    if mode != "live":
        skipped[FORWARD_ONLY_CODE] += 1                  # the house hound is forward only; so is a member's
        return []
    created = E._utc(hound.get("created_at"))
    out = []
    for event_id, game in sorted(games.items()):
        if game.sport not in spec["sports"] or game.commence is None:
            continue
        bet_id = E.bet_id_for(hound["id"], event_id, MARKET)
        if bet_id in seen_ids:
            continue
        now = clock()
        lock_pre = game.commence - timedelta(minutes=spec["lock_minutes"])
        if now >= game.commence:
            skipped["game_started"] += 1
            continue
        if now < lock_pre:
            skipped["not_locked_yet"] += 1
            continue
        if created is not None and created > lock_pre:
            skipped["hound_created_after_lock"] += 1
            continue
        considered.setdefault(hound["id"], set()).add(event_id)
        got = weigher.weigh(event_id)
        if got is None:
            skipped[PASS_PREFIX + "no_context"] += 1
            continue
        ctx, board, weighed = got
        if now >= ctx.start:
            skipped["game_started"] += 1
            continue
        if now < ctx.lock:
            skipped["not_locked_yet"] += 1
            continue
        if not weighed.verdict.is_bet:
            skipped[PASS_PREFIX + weighed.verdict.code] += 1
            continue
        cand = _candidate(game, ctx, board, weighed, weigher.runtime)
        if cand is None:
            skipped[PASS_PREFIX + "no_board"] += 1
            continue
        out.append(((ctx.lock, event_id, 0), ctx.lock, event_id, MARKET, game, ctx.start, cand, bet_id))
    return out


def preview(spec: Mapping, games: Mapping, date: str, now: datetime, *, weigher: Optional[Weigher] = None) -> dict:
    """What this member Gematria spec would bet on this slate, from the boards as they stand at ``now``. Writes nothing.
    Same result shape as ``user_engine_v2.preview`` so the builder's preview panel draws it unchanged."""
    from src.hounds import user_engine as E

    weigher = weigher or Weigher(games)
    skipped: Counter = Counter()
    considered: set = set()
    picks = []
    for event_id, game in sorted(games.items()):
        if game.sport not in spec["sports"] or game.commence is None:
            continue
        if not enabled():
            skipped[OFF_CODE] += 1
            continue
        considered.add(event_id)
        got = weigher.weigh(event_id, as_of=now)
        if got is None:
            skipped[PASS_PREFIX + "no_context"] += 1
            continue
        ctx, board, weighed = got
        if weighed.verdict.is_bet:
            cand = _candidate(game, ctx, board, weighed, weigher.runtime)
            if cand is not None:
                picks.append((ctx.lock, event_id, game, ctx, cand))
                continue
        skipped[PASS_PREFIX + weighed.verdict.code] += 1
    picks.sort(key=lambda p: (p[0], p[1]))
    out = []
    for position, (lock, event_id, game, ctx, cand) in enumerate(picks):
        out.append({
            "event_id": event_id, "sport": game.sport, "market": MARKET, "away_team": game.away_team,
            "home_team": game.home_team, "start_utc": E._iso(ctx.start), "lock_utc": E._iso(lock), "locked": now >= lock,
            "selection": cand["selection"], "side": cand["side"], "line": None, "player": None, "price": cand["price"],
            "best_price": cand["best_price"], "n_books": cand["n_books"], "rule_index": 0,
            "would_bet": position < spec["max_bets_per_day"], "rank": position + 1})
    return {"date": date, "games_considered": len(considered), "games_fit": len(out), "qualifying": len(out),
            "would_bet": min(len(out), spec["max_bets_per_day"]), "max_bets_per_day": spec["max_bets_per_day"],
            "picks": out, "skipped": dict(skipped)}


# ---------------------------------------------------------------------------
# the Evidence fold for a member's hound
# ---------------------------------------------------------------------------

MAX_PICKS = 40


def picks_for(hound_id: str, *, ledger: Optional[str] = None, limit: int = MAX_PICKS) -> dict:
    """The same payload as ``gematria.view.picks_for`` (what ``web/js/hounds-gematria.js`` reads), from the member ledger.

    Streams the ledger and parses only lines naming this hound, so a big shared ledger is never held whole."""
    from src.hounds import NOT_ADVICE, PAPER_ONLY, user_engine, user_settle
    from src.hounds.gematria import EXPERIMENTAL_LINE

    path = Path(user_engine.ledger_path(ledger))
    needle = f'"{hound_id}"'
    bets, grades = [], {}
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if needle not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict) or r.get("hound_id") != hound_id:
                    continue
                if r.get("kind") == user_engine.KIND_BET and isinstance(r.get("gematria"), dict):
                    bets.append(r)
                elif r.get("kind") == user_settle.KIND_GRADED:
                    grades[r.get("bet_id")] = r
    bets.sort(key=lambda r: (str(r.get("commence_time") or ""), str(r.get("event_id") or "")), reverse=True)
    picks = []
    for r in bets[:limit]:
        g = r["gematria"]
        graded = grades.get(r.get("bet_id"))
        picks.append({
            "event_id": r.get("event_id"), "date": r.get("slate_date"), "sport": r.get("sport"),
            "start_utc": r.get("commence_time"), "away": r.get("away_team"), "home": r.get("home_team"),
            "selection": r.get("selection"), "side": r.get("side"), "price": r.get("price_average", r.get("price")),
            "result": graded.get("result") if graded else None,
            "rules_version": g.get("rules_version") or r.get("rules_version"),
            "hound_version": g.get("hound_version"),
            "scores": g.get("scores"), "margin": g.get("margin"), "threshold": g.get("threshold"),
            "comparisons": g.get("comparisons"), "search_space": g.get("search_space"), "matches": g.get("matches"),
            "history": g.get("history"), "evidence": g.get("evidence"),
        })
    return {"hound_id": hound_id, "started": bool(bets), "picks": picks, "copy": EXPERIMENTAL_LINE,
            "paper_only": PAPER_ONLY, "not_advice": NOT_ADVICE}


def is_member_gematria_hound(hound_id: str) -> bool:
    """True for a stored member hound (any version) whose spec has the Gematria style. A missing database answers False."""
    if not isinstance(hound_id, str) or not hound_id:
        return False
    try:
        from src.hounds import user_defs, user_store

        if not user_defs.db_exists():
            return False
        hound = user_store.get_hound(hound_id)
    except Exception:  # noqa: BLE001 -- an unreadable store is "not a member hound", never a 500 on a public route
        return False
    return bool(hound) and is_gematria(hound.get("spec") or {})
