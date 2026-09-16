"""DAILY_CARD_BEST_BETS_V2 -- the pure selection rule, registered in
`docs/PREREG_CARD_V2.md`, and the four A1-A4 family arms of registration
section 17.

WHY THIS IS A NEW MODULE, NOT MORE CODE IN `daily_card.py`
------------------------------------------------------------
`daily_card.py` is V1, `DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`, and it
keeps running and keeps its own record while V2 is evaluated beside it
(registration, header). Editing it to grow a second rule would let a change
made for V2 alter what V1 already published, which the registration's
`v1_code_fingerprint` exists specifically to catch. So V2 is new code with
its own file, its own fingerprint window (registration 11.2 covers this
file), and its own frozen constants.

WHY THE RULE LOOKS THE WAY IT DOES
------------------------------------
The short version, argued at length in the registration: the owner asked for
"value x confidence", so the ranking key is a Kelly fraction on a
deliberately marked-down probability (`score`, section 4); a candidate must
clear break-even by a price-scaled margin, not merely clear it
(`required_edge`, section 4.2); and two price-defined classes, MAIN
(-160..-100, where our number and the market's both have to prefer the side)
and PLUS_MONEY (+100..+250, where the market may call the side the
underdog), are graded, floored and capped apart from each other because
nothing in this repo has ever measured our probability below 0.50 and the
class the owner is most enthusiastic about is exactly that one (registration
0.2). None of that is re-derived here; this module only turns the frozen
numbers into gates and a score.

PURE, STDLIB ONLY
------------------
No disk read, no network call, no naked `datetime.now()` -- every "now" this
module needs arrives as an argument, so a test can freeze it and a caller
can replay a past publish run exactly. `select()` takes a `candidates`
sequence of plain dicts already carrying `price`, `market_probability`,
`our_probability` (raw) and the other fields documented on `failed_gates`;
building those from live board/model rows is the report layer's job
(`src.report.card`, out of this module's scope), not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence

from src.analysis import daily_card, prices, propboard
from src.analysis.grade import FRESH_SECONDS
from src.core import odds

# ---------------------------------------------------------------------------
# RuleParams -- every registered constant, in one frozen, comparable shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleParams:
    """One rule's frozen constants (registration section 3, 4 and 17.1).

    A `RuleParams` instance is the whole rule: nothing in `select()` or the
    gates below reads a module-level constant instead of a field on this
    object, so a shadow or variant arm is a complete, testable rule by
    itself, not a rule plus some ambient state. Every field's source is
    named in the registration (section 3's "Where the gate constants come
    from" paragraph, section 4's constants block, or the module named beside
    it); none is fitted or guessed here.
    """

    rule_id: str

    # Price band (registration section 4, G4). BASE_PRICE is not itself a
    # bound; it is the reference price `required_edge` scales from, and it
    # equals `worst_price` here by definition (registration section 4:
    # "leverage 1.0 here").
    worst_price: float = -160.0
    best_price: float = 250.0
    base_price: float = -160.0

    # The score (registration section 4). MARKDOWN is subtracted from our
    # raw probability before any value test or score; BASE_EDGE is the
    # required-edge margin at `base_price`, scaled up with the decimal odds
    # at longer prices (4.2).
    markdown: float = 0.038
    base_edge: float = 0.010

    # Likelihood floors, one pair per price class (registration 0.1, G5, G6).
    # `None` means the floor is not applied -- used only by SHADOW_A, which
    # registration section 10 defines with no likelihood floor at all.
    main_market_floor: Optional[float] = 0.50
    main_our_floor: Optional[float] = 0.50
    plus_market_floor: Optional[float] = 0.20
    plus_our_floor: Optional[float] = 0.30

    # G7, G8, G13 (registration section 3). `None` disables the check, used
    # only by shadows built to isolate one mechanism.
    value_test: bool = True
    disagreement_cap: Optional[float] = 0.10
    no_line_shopping: bool = True

    # G14. `None` removes the sub-cap entirely (registration section 10:
    # SHADOW_A and the *_NOCAP arms).
    plus_money_subcap: Optional[int] = 3

    # G2, G3, G9, G10, G11 inputs, all named repo constants (registration
    # section 3's "Where the gate constants come from").
    game_min_books: int = prices.MIN_BOOKS
    prop_min_books: int = propboard.MIN_BOOKS
    prop_min_season_games: int = daily_card.MIN_SEASON_GAMES_FOR_PRELINEUP
    require_lineup: bool = False
    fresh_seconds: float = FRESH_SECONDS

    # G12 and the floor (registration section 6). `ceiling` counts picks and
    # fills together -- the owner's 2026-09-16 answer, replacing the draft's
    # picks-only ceiling that could publish 13 entries.
    ceiling: int = 10
    floor: int = 3
    fill_to_floor: bool = True

    # Layout only (registration 17.2). Never read by `select()`: a layout
    # choice may reorder how entries are grouped on the page, never which
    # entries are chosen or their within-class order (T9v's invariant).
    interleave_classes: bool = True

    # The superseded draft's ranking key, kept only so SHADOW_E can select
    # it explicitly rather than this module growing a second code path that
    # every other rule silently ignores. "score" everywhere else.
    rank: str = "score"


V2 = RuleParams("DAILY_CARD_BEST_BETS_V2")

# Registration section 10. SHADOW_A drops the likelihood floors, the value
# test and the disagreement cap to show what the price band alone would
# publish -- and it must also drop the plus-money sub-cap, because G14 caps
# the CARD's composition rather than gating our number, and leaving it at 3
# would make A drop some of V2's own plus-money picks and stop being a
# superset of V2 (registration section 10, and the build-plan correction
# logged there on 2026-09-16).
SHADOW_A = replace(
    V2,
    rule_id="DAILY_CARD_BEST_BETS_V2_SHADOW_A_BAND_ONLY",
    main_our_floor=None,
    plus_our_floor=None,
    value_test=False,
    disagreement_cap=None,
    plus_money_subcap=None,
)

# Registration section 10 / question 4: the short end of the price band at
# -150 instead of -160, everything else unchanged.
SHADOW_C = replace(
    V2,
    rule_id="DAILY_CARD_BEST_BETS_V2_SHADOW_C_OTHER_WORST_PRICE",
    worst_price=-150.0,
)

# There is no SHADOW_D. Registration section 10 deregisters it before
# registration; the family's loose arms (A3, A4 below) replace what it was
# for. A `markdown=0.0` parameter set must never be reintroduced under any
# name -- `tests/test_card_v2_shadows.py` asserts this directly.

# Registration section 10: the superseded 2026-09-11 draft rule, kept only
# as a shadow so its record stays comparable. No plus-money class (the
# floors and sub-cap that define it are switched off), no markdown, no
# required edge above bare break-even, and the old price-first ranking key.
SHADOW_E = replace(
    V2,
    rule_id="DAILY_CARD_BEST_BETS_V2_SHADOW_E_LIKELY_FIRST",
    best_price=None,
    markdown=0.0,
    base_edge=0.0,
    plus_market_floor=None,
    plus_our_floor=None,
    main_market_floor=0.50,
    main_our_floor=0.50,
    plus_money_subcap=0,
    rank="longest_price_first",
)

# ---------------------------------------------------------------------------
# The four family arms (registration 17.1), over the two settings the owner
# disputed on 2026-09-16 about 03:10Z: how far our number is marked down
# (V2's registered 0.038/0.010 vs. a loose 0.0090/0.0024 pair that reproduces
# the bar in the registration's 17.1 table) and whether the plus-money
# sub-cap applies. Every field but these two, or the sub-cap and rule_id, is
# identical to V2's -- pinned by
# `tests/test_card_v2_shadows.py::test_arms_differ_from_v2_in_named_fields_only`
# comparing `dataclasses.asdict` field by field, so a future edit can never
# let a fifth field drift silently.
# ---------------------------------------------------------------------------

A1 = V2
A2 = replace(V2, rule_id="DAILY_CARD_BEST_BETS_V2_VAR_STRICT_NOCAP", plus_money_subcap=None)
A3 = replace(V2, rule_id="DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_CAP3", markdown=0.0090, base_edge=0.0024)
A4 = replace(
    V2,
    rule_id="DAILY_CARD_BEST_BETS_V2_VAR_LOOSE_NOCAP",
    markdown=0.0090,
    base_edge=0.0024,
    plus_money_subcap=None,
)

ARMS = {"A1": A1, "A2": A2, "A3": A3, "A4": A4}
PUBLISHED_ARM = "A1"


# ---------------------------------------------------------------------------
# Price class, break-even, the markdown and the score (registration section 4)
# ---------------------------------------------------------------------------


def price_class(price: float) -> Optional[str]:
    """MAIN, PLUS_MONEY, or None (registration G4). One function, used by the
    gates, the record, the ledger row and the page, so no caller can drift
    into its own copy of the band."""
    if -160.0 <= price <= -100.0:
        return "MAIN"
    if 100.0 <= price <= 250.0:
        return "PLUS_MONEY"
    return None


def in_band(price: float, params: RuleParams) -> bool:
    """True when the price falls in the class band `params` allows. Reads
    `params.worst_price` / `params.best_price` rather than the hardcoded
    constants in `price_class`, so a shadow with a different band (SHADOW_C,
    SHADOW_E) is still checked against its own numbers."""
    if params.best_price is None:
        return price <= params.worst_price or price >= 100.0
    return (params.worst_price <= price <= -100.0) or (100.0 <= price <= params.best_price)


def breakeven(price: float) -> Optional[float]:
    """Raw implied probability at `price` -- vig included, exactly as the
    registration's `breakeven(price)` (section 4)."""
    try:
        return odds.american_to_probability(price)
    except odds.OddsError:
        return None


def marked_down(our_probability: float, params: RuleParams) -> float:
    """Our number after `params.markdown`. Every downstream consumer (the
    value test, the score, the figure shown on the card) reads this; G6 and
    G8 read the RAW number instead, because one is the owner's floor on our
    own confidence and the other is a cap on how far our raw number may sit
    from the market's (registration section 4, G6's row)."""
    return max(0.0, our_probability - params.markdown)


def required_edge(price: float, params: RuleParams) -> float:
    """Edge required on top of break-even, growing with the decimal odds:
    expected value per unit is `p*d - 1`, so the same probability error
    costs exactly `d` per point of overstatement (registration section 4,
    4.2)."""
    return params.base_edge * (
        odds.american_to_decimal(price) / odds.american_to_decimal(params.base_price)
    )


def value_need(price: float, params: RuleParams) -> Optional[float]:
    """`breakeven(price) + required_edge(price)` -- the bar the marked-down
    number must clear (G7)."""
    be = breakeven(price)
    if be is None:
        return None
    return be + required_edge(price, params)


def passes_value_test(our_probability: float, price: float, params: RuleParams) -> bool:
    """G7: `marked_down(ours) >= value_need(price)`. `False` whenever the
    price has no break-even (e.g. inside -100..+100, which G4 already
    refuses) or `params.value_test` is switched off for a shadow rule."""
    if not params.value_test:
        return True
    need = value_need(price, params)
    if need is None:
        return False
    return marked_down(our_probability, params) >= need


def score(our_probability: float, price: float, params: RuleParams) -> Optional[float]:
    """Value times confidence, as a Kelly fraction on the marked-down
    number: the share of a bankroll this confidence at this price would
    justify (registration section 4). RANKING KEY ONLY -- callers must only
    compute it for a candidate that has already passed every gate, so a high
    score never rescues one a gate refused. No fractional multiplier and no
    cap are applied here, and none is registered: neither would change a
    selection or an order, since any positive constant multiple of this key
    gives the same order."""
    d = odds.american_to_decimal(price)
    if d <= 1.0:
        return None
    p = marked_down(our_probability, params)
    return p - (1.0 - p) / (d - 1.0)


# ---------------------------------------------------------------------------
# Gates (registration section 3)
# ---------------------------------------------------------------------------

G1_STARTED = "G1_STARTED"
G2_BOOKS = "G2_BOOKS"
G3_STALE = "G3_STALE"
G4_BAND = "G4_BAND"
G5_MARKET = "G5_MARKET"
G6_FLOOR = "G6_FLOOR"
G7_VALUE = "G7_VALUE"
G8_DISAGREEMENT = "G8_DISAGREEMENT"
G9_UNCALIBRATED = "G9_UNCALIBRATED"
G10_SAMPLE = "G10_SAMPLE"
G13_LINE_SHOPPING = "G13_LINE_SHOPPING"

# Gates a fill is allowed to fail without losing floor eligibility
# (registration section 3, the "A fill" paragraph): fail at least one of
# G3, G7 and nothing else.
_FILL_ALLOWED_FAILURES = frozenset({G3_STALE, G7_VALUE})


def quote_age_seconds(observed_utc: Any, now: Any) -> Optional[float]:
    """Seconds between `observed_utc` and `now`. `None` for a missing or
    unparseable time, which fails G3 (registration section 3, G3's row: "a
    missing or unparseable `observed_utc` fails")."""
    if observed_utc is None or now is None:
        return None
    try:
        return (now - observed_utc).total_seconds()
    except (TypeError, AttributeError):
        return None


def _kind_is_prop(candidate: Mapping[str, Any]) -> bool:
    return candidate.get("kind") == "prop"


def failed_gates(candidate: Mapping[str, Any], *, now: Any, params: RuleParams) -> list:
    """Every gate this candidate fails, in gate-number order. Reads only the
    fields documented here; a caller assembling candidates supplies them.

    Expected fields: `price` (American odds), `market_probability` (raw,
    de-vigged consensus), `our_probability` (raw model/prop-board number),
    `books` (int), `observed_utc`, `has_started` (bool), `calibrated` (bool,
    G9 -- whether the frozen parameter file backs this candidate's number;
    props are not applicable and always pass), `season_games` (props only),
    optional `kind` ("prop" for a player prop, otherwise a game market).
    """
    fails: list = []
    price = candidate.get("price")
    is_prop = _kind_is_prop(candidate)

    if candidate.get("has_started", False):
        fails.append(G1_STARTED)

    min_books = params.prop_min_books if is_prop else params.game_min_books
    books = candidate.get("books")
    if books is None or books < min_books:
        fails.append(G2_BOOKS)

    age = quote_age_seconds(candidate.get("observed_utc"), now)
    if age is None or age > params.fresh_seconds:
        fails.append(G3_STALE)

    if price is None or not in_band(price, params):
        fails.append(G4_BAND)

    pcls = price_class(price) if price is not None else None
    market_p = candidate.get("market_probability")
    our_p = candidate.get("our_probability")

    if pcls == "MAIN":
        floor_market = params.main_market_floor
        if floor_market is not None and not (market_p is not None and market_p > floor_market):
            fails.append(G5_MARKET)
        floor_our = params.main_our_floor
        if floor_our is not None and not (our_p is not None and our_p > floor_our):
            fails.append(G6_FLOOR)
    elif pcls == "PLUS_MONEY":
        floor_market = params.plus_market_floor
        if floor_market is not None and not (
            market_p is not None and floor_market <= market_p < 0.50
        ):
            fails.append(G5_MARKET)
        floor_our = params.plus_our_floor
        if floor_our is not None and not (our_p is not None and our_p >= floor_our):
            fails.append(G6_FLOOR)
    else:
        # G4 already failed; G5 and G6 have no band to test against.
        fails.append(G5_MARKET)
        fails.append(G6_FLOOR)

    if price is not None and our_p is not None:
        if not passes_value_test(our_p, price, params):
            fails.append(G7_VALUE)
    else:
        fails.append(G7_VALUE)

    if params.disagreement_cap is not None:
        if our_p is None or market_p is None or abs(our_p - market_p) > params.disagreement_cap:
            fails.append(G8_DISAGREEMENT)

    if not is_prop:
        if not candidate.get("calibrated", False):
            fails.append(G9_UNCALIBRATED)

    if is_prop:
        season_games = candidate.get("season_games")
        if season_games is None or season_games < params.prop_min_season_games:
            fails.append(G10_SAMPLE)

    if params.no_line_shopping:
        if price is not None:
            be = breakeven(price)
            if be is not None and market_p is not None and market_p > be:
                fails.append(G13_LINE_SHOPPING)

    return fails


def is_fill_eligible(fails: Sequence[str]) -> bool:
    """A fill must pass every gate except (at most) G3 and G7 (registration
    section 3, the "A fill" paragraph)."""
    if not fails:
        return True
    return bool(fails) and set(fails) <= _FILL_ALLOWED_FAILURES


# ---------------------------------------------------------------------------
# Ranking (registration section 5) and close-call ordering (section 6)
# ---------------------------------------------------------------------------


def rank_key(c: Mapping[str, Any]):
    """Descending score, then ascending raw disagreement, then descending
    books, then ascending first pitch, then alphabetical sentence
    (registration section 5). Sort with this key and `reverse=False` on the
    tuple below -- the sign flips are baked into the tuple, not the call."""
    return (
        -c["score"],
        abs(c.get("our_probability", 0.0) - c.get("market_probability", 0.0)),
        -(c.get("books") or 0),
        c.get("first_pitch") or "",
        c.get("bet_sentence") or "",
    )


def close_call_key(c: Mapping[str, Any], fails: Sequence[str]):
    """Fewest failed checks, then ascending shortfall against `value_need`,
    then descending score, then books, first pitch, sentence (registration
    section 6). Score breaks the tie a stale board collapses onto: when every
    candidate fails only G3, shortfall is zero for all of them, and without
    the score term the order would fall through to a tie-break with no
    bearing on the bet."""
    price = c.get("price")
    params = c["__params__"]
    need = value_need(price, params) if price is not None else None
    our_p = c.get("our_probability")
    if need is None or our_p is None:
        shortfall = float("inf")
    else:
        shortfall = max(0.0, need - marked_down(our_p, params))
    return (
        len(fails),
        shortfall,
        -(c.get("score") or 0.0),
        -(c.get("books") or 0),
        c.get("first_pitch") or "",
        c.get("bet_sentence") or "",
    )


# ---------------------------------------------------------------------------
# select() -- the whole rule, one candidate pool at a time
# ---------------------------------------------------------------------------


def _game_key(c: Mapping[str, Any]) -> Any:
    """G11's dedup identity: one entry per game (both markets) or per
    player, never mixed across price classes."""
    return c.get("player_id") or c.get("game_id")


def select(
    candidates: Sequence[Mapping[str, Any]],
    *,
    now: Any,
    params: RuleParams,
    prior: Optional[Mapping[str, Any]] = None,
) -> dict:
    """The whole rule on one candidate pool at one publish run.

    Order of operations is fixed by registration section 5 and pinned by
    `tests/test_card_v2_order_of_operations.py`: gates on each candidate
    alone; score on the survivors; rank; G11 dedup in rank order; G14 (drop
    the lowest-scored plus-money picks beyond `plus_money_subcap`); G12 (cut
    to `ceiling`); then fills to `floor` from the close-call order.
    Applying G14 before G11 would drop a plus-money pick dedup was about to
    remove anyway and waste a slot -- the specific mistake this ordering
    exists to prevent.
    """
    prior = prior or {}
    prior_shown = [e for e in prior.get("all_bets", []) if not e.get("withdrawn")]

    passed: list = []
    close_calls: list = []

    for raw in candidates:
        c = dict(raw)
        c["__params__"] = params
        fails = failed_gates(c, now=now, params=params)
        price = c.get("price")
        our_p = c.get("our_probability")
        c["price_class"] = price_class(price) if price is not None else None
        c["score"] = (
            score(our_p, price, params)
            if (price is not None and our_p is not None and not fails)
            else None
        )
        c["failed_gates"] = fails
        if not fails:
            passed.append(c)
        elif is_fill_eligible(fails):
            close_calls.append(c)
        # else: neither a pick nor a fill (registration section 6).

    passed.sort(key=rank_key)

    # G11: one entry per game or player, higher score kept, in rank order.
    seen_keys: set = set()
    deduped: list = []
    for c in passed:
        key = _game_key(c)
        if key is not None and key in seen_keys:
            continue
        if key is not None:
            seen_keys.add(key)
        deduped.append(c)

    # G14: drop the lowest-scored plus-money picks beyond the sub-cap.
    plus_money_dropped_by_subcap: list = []
    if params.plus_money_subcap is not None:
        kept: list = []
        plus_count = 0
        for c in deduped:
            if c["price_class"] == "PLUS_MONEY":
                if plus_count >= params.plus_money_subcap:
                    plus_money_dropped_by_subcap.append(c)
                    continue
                plus_count += 1
            kept.append(c)
        deduped = kept

    # G12: cut to the ceiling, counting picks and fills together. Fills are
    # not chosen yet, so the picks are cut first and the remaining room is
    # what fills may use.
    ceiling_refused: list = []
    if len(deduped) > params.ceiling:
        ceiling_refused = deduped[params.ceiling :]
        deduped = deduped[: params.ceiling]

    n_picks = len(deduped)

    # Floor: fill from the close-call order while shown entries (this run's
    # picks plus prior shown entries not being replaced) number fewer than
    # `floor`, up to 3 fills on one run, never exceeding `ceiling` overall.
    fills: list = []
    if params.fill_to_floor:
        picked_keys = {_game_key(c) for c in deduped if _game_key(c) is not None}
        prior_count = len(
            [e for e in prior_shown if _game_key(e) not in picked_keys]
        )
        shown_count = n_picks + prior_count
        room = max(0, params.ceiling - n_picks - prior_count)
        close_calls.sort(key=lambda c: close_call_key(c, c["failed_gates"]))
        used_keys: set = set(picked_keys)
        for c in close_calls:
            if shown_count >= params.floor or len(fills) >= params.floor:
                break
            if room <= 0:
                break
            key = _game_key(c)
            if key is not None and key in used_keys:
                continue
            if key is not None:
                used_keys.add(key)
            fills.append(c)
            shown_count += 1
            room -= 1

    n_plus_money_picks = sum(1 for c in deduped if c["price_class"] == "PLUS_MONEY")

    prop_picks = [c for c in deduped if _kind_is_prop(c)]
    game_picks = [c for c in deduped if not _kind_is_prop(c)]

    close_calls_not_shown = [c for c in close_calls if c not in fills]

    for c in deduped:
        c["entry_class"] = "pick"
    for c in fills:
        c["entry_class"] = "fill"

    all_bets = deduped + fills

    return {
        "rule": params.rule_id,
        "params": params,
        "picks": game_picks,
        "prop_picks": prop_picks,
        "fills": fills,
        "close_calls_not_shown": close_calls_not_shown,
        "withdrawn": [],
        "all_bets": all_bets,
        "n_picks": n_picks,
        "n_fills": len(fills),
        "n_plus_money_picks": n_plus_money_picks,
        "plus_money_dropped_by_subcap": plus_money_dropped_by_subcap,
        "ceiling_refused": ceiling_refused,
        "stale_board": None,
        "basis": BASIS,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Copy (registration section 13). Only the strings this module owns as a
# rule -- not a renderer; `src.report.card` assembles the page.
# ---------------------------------------------------------------------------

BASIS = (
    "A specific bet, at a named price and a named book, published before "
    "first pitch, frozen, and graded in public whether it wins or loses."
)

DISCLAIMER = (
    "This claims no edge, no positive expected return and no guarantee. "
    "Our own number has not been shown to beat the market's."
)


def format_triplet(market: float, needs: float, ours: float) -> tuple:
    """Whole percents rounded half up; if two of the three would print the
    same text at that precision, all three get one more decimal digit
    (registration section 13, `format_triplet`)."""

    def fmt(x: float, digits: int) -> str:
        pct = x * 100.0
        # Round-half-up, not banker's rounding, so 0.5 always rounds away
        # from the lower percent.
        scaled = pct * (10 ** digits)
        rounded = int(scaled + 0.5) if scaled >= 0 else -int(-scaled + 0.5)
        return f"{rounded / (10 ** digits):.{digits}f}%"

    for digits in (0, 1, 2):
        texts = (fmt(market, digits), fmt(needs, digits), fmt(ours, digits))
        if len(set(texts)) == len(texts):
            return texts
    return (fmt(market, 2), fmt(needs, 2), fmt(ours, 2))


def bet_sentence(pick: Mapping[str, Any]) -> str:
    """C2's opening line. Begins with 'Take' only when `pick['take']` is
    true; a locked pick whose newest read fails renders without a verb
    (`no_take_sentence` below) instead."""
    sentence = pick.get("bet_sentence") or ""
    if pick.get("take", True):
        return f"Take {sentence}" if sentence and not sentence.lower().startswith("take") else sentence
    return sentence


def why_sentences(pick: Mapping[str, Any]) -> tuple:
    """C2's two 'why' lines. `why[1]` has exactly one form now that G13
    removes the line-shopping alternative (registration section 13)."""
    market, needs, ours = format_triplet(
        pick.get("market_probability", 0.0),
        value_need(pick.get("price"), pick["__params__"]) or 0.0,
        marked_down(pick.get("our_probability", 0.0), pick["__params__"]),
    )
    why0 = f"Market: {market} · Needs: {needs} · Our number: {ours}"
    why1 = (
        "Our own number has not been shown to beat the market's, so it is "
        f"marked down by {pick['__params__'].markdown * 100:.1f} points before it may clear a price."
    )
    return (why0, why1)


def no_take_sentence(pick: Mapping[str, Any]) -> str:
    """C2b: a locked pick whose fresh read fails renders without a verb."""
    return pick.get("bet_sentence") or ""


def fill_sentence(entry: Mapping[str, Any], fails: Sequence[str]) -> str:
    """C6's entry line: names every check the fill failed."""
    names = ", ".join(fails) if fails else "no check"
    sentence = entry.get("bet_sentence") or ""
    return f"{sentence} (failed: {names})" if sentence else f"(failed: {names})"


def fill_note() -> str:
    """C12: the same line on every fill."""
    return (
        "This one did not pass every check, so it is not a pick. It is "
        "listed because the card shows three bets on a day when three "
        "clear the first checks, and it is graded on the record apart "
        "from the picks."
    )


def plus_money_note(entry_class: str) -> str:
    """C14, corrected 2026-09-16: no clause here may state or imply that our
    number makes the side more likely than not -- the struck clause
    contradicted the shown number on the design board's own illustration
    (registration section 13, C14)."""
    subject = "pick" if entry_class == "pick" else "bet"
    lead = "This is a plus-money pick" if entry_class == "pick" else "This is a plus-money bet"
    return (
        f"{lead}: the market makes this side the underdog, and our number, "
        "after it is marked down, is still above what the price needs. "
        f"Picks like this are kept on their own record, apart from the "
        "rest, so a bad run here cannot hide inside the other picks and a "
        "good run there cannot cover for one here. There is no record for "
        f"this kind of {subject} yet."
    )


def no_lineup_note() -> str:
    """C15: mandatory on every prop with no posted lineup, pick or fill."""
    return (
        "No lineup is posted yet for this game. Plate appearances are "
        "priced off this batter's season average, not his spot in today's "
        "order."
    )


def short_card_sentence(n: int) -> str:
    """C13: used whenever the board offers fewer than `floor` entries."""
    return (
        f"Today {n} bets are listed. Before a bet is listed at all, its "
        "game has to be unstarted, enough books have to be quoting the "
        "price, the price has to be between -160 and +250, and the "
        "market's own number has to be no higher than what that price "
        f"needs. Today the board had {n} of those."
    )


def stale_sentence(n: int, age_seconds: float) -> str:
    """First of C5's stale-board sentences."""
    return f"{n} bets are shown from a board last checked {int(age_seconds)} seconds ago."


def class_stopped_sentence(price_class_name: str) -> str:
    """C9b: one class stopped by a FAIL, UNDERPOWERED or HARM_STOP result,
    the other class's picks unchanged."""
    label = "plus-money bets" if price_class_name == "PLUS_MONEY" else "main-band bets"
    return (
        f"The {label} below are still listed, but they are no longer "
        "picks. A check on the first graded ones did not come out well "
        "enough for us to keep saying take them. The rest of the picks "
        "are unchanged."
    )


def harm_stop_sentence(arms: Sequence[str], price_class_name: Optional[str] = None) -> str:
    """C11: the closing-price form, the hit-rate form, the plus-money
    hit-rate form, or the combined form, chosen by which harm-check arm (or
    arms) fired (registration section 13, C11)."""
    closing = "closing_price" in arms
    hit_rate = "hit_rate" in arms
    if closing and hit_rate:
        return (
            "These bets pass our checks, but checks on the first graded "
            "ones found they were getting worse prices than the market "
            "settled at, and that picks where our number was well above "
            "the market's won less often than their prices needed, so we "
            "no longer say take them. They are not picks."
        )
    if closing:
        return (
            "These bets pass our checks, but a check on the first graded "
            "ones found they were getting worse prices than the market "
            "settled at, so we no longer say take them. They are not picks."
        )
    if hit_rate and price_class_name == "PLUS_MONEY":
        return (
            "These bets pass our checks, but a check on the first graded "
            "plus-money picks found they won less often than their prices "
            "needed, so we no longer say take them. They are not picks. "
            "The other picks are unchanged."
        )
    return (
        "These bets pass our checks, but a check on the first graded "
        "picks where our number was well above the market's found they "
        "won less often than their prices needed, so we no longer say "
        "take them. They are not picks."
    )
