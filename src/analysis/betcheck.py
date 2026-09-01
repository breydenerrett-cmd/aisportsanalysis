"""Bet Check: take a stated bet, hand back an honest verdict object.

WHAT THIS IS
------------
The engine side of the "type a bet, see what we actually know" loop. It does
not add a single new fact about a game. Everything it returns is either a
strict re-parse of the bet string, or a re-partition of findings and market
numbers this codebase already produces (`src.detect.base.Finding.side`,
`src.analysis.prices.snapshot`, `src.analysis.synthesis.EVIDENCE_LABELS`).
See docs/SAAS_APPLICATION_ARCHITECTURE.md section 3: "Finding.side makes the
evidence partition a filter, not new analysis" -- that is the whole design
of `check()` below.

WHAT THIS IS NOT
----------------
Not a predictor. Not a recommendation engine. The record this module is
required to state on every call is unchanged from the rest of the product:
27 pre-registered hypotheses across four families (src/analysis/__init__.py)
have been measured against outcomes and none has survived. A bet's stated
price beating the de-vigged consensus is LINE-SHOPPING VALUE -- a better
execution price -- and is labelled exactly that, never expected value and
never an edge (src/analysis/prices.py:LABEL).

TWO STAGES
----------
`parse(text)` turns a free-text bet into {team, market, price} or a
structured refusal naming exactly what was ambiguous (team / market /
price). It never guesses: an unresolved team, an unsupported market named
explicitly, or a missing/unreadable price all refuse rather than default.

`check(bet, dossier, board=None, findings=None)` takes a parsed bet (or a
raw string, which it parses itself) together with the one game's dossier and
its multi-book board, and returns the structured verdict: the matched game,
findings for and against the stated side (each carrying its sample and its
evidence label -- a finding without both cannot enter the object), price
context against both the de-vigged consensus and the best number on the
board, what-changed events when the dossier carries any, sample-quality
warnings for anything dropped for lacking a sample, and a bottom line that
says support, opposition, or "does not distinguish" -- never a prediction.

THIRD STAGE -- THE CONTRACT
----------------------------
`build_contract(date, away_club, home_club, side, american_price, ...)` is
the paid-beta API's entry point (docs/SAAS_APPLICATION_ARCHITECTURE.md
section 3.4). It takes the STRUCTURED bet the API's request model has
already validated -- a club pair, `side` in {away, home}, an American price
-- rather than a free-text string, and returns a
`src.analysis.contracts.BetCheckContract`: the same fixed skeleton every
other customer surface returns, so an omission is visible rather than
absorbed into a looser dict shape. It does not call `check()` (that
function's job is the free-text loop; this one is the structured one) but it
reuses the same building blocks -- `prices.snapshot` for market context,
`Finding.side` for the for/against partition, `synthesis.sample_size` and
`synthesis.EVIDENCE_LABELS` for the sample-and-label pairing -- because the
underlying facts do not change with the input shape, only their container
does. A missing board, a thin board, or a side with no priceable quote all
come back as an explicit "market context unavailable" statement folded into
`bottom_line` -- never a fabricated price, never a defaulted zero.
"""

from __future__ import annotations

import re

import src.analysis as analysis
from src.analysis import gamepayload
from src.analysis import prices as prices_mod
from src.analysis import relevance as relevance_mod
from src.analysis import synthesis as synthesis_mod
from src.core import odds as odds_math
from src.data import parks
from src.detect import base as detect
from src.pipeline import slate as slate_mod

from src.analysis import contracts as c

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# Only h2h (moneyline) is checked today. Every other market name recognised
# here is refused BY NAME rather than silently coerced into h2h -- a spread
# ticket checked as though it were a moneyline is a wrong answer, not an
# approximation.
SUPPORTED_MARKETS = {
    "moneyline": "h2h",
    "money line": "h2h",
    "money-line": "h2h",
    "ml": "h2h",
    "h2h": "h2h",
}

UNSUPPORTED_MARKETS = {
    "run line": "run line",
    "runline": "run line",
    "rl": "run line",
    "spread": "spread",
    "point spread": "spread",
    "over/under": "total",
    "o/u": "total",
    "total": "total",
    "over": "total",
    "under": "total",
    "first five": "first five innings",
    "first 5": "first five innings",
    "1st five": "first five innings",
    "1st 5": "first five innings",
    "f5": "first five innings",
    "puck line": "puck line",
    "puckline": "puck line",
    "player prop": "player prop",
    "props": "player prop",
    "prop": "player prop",
    "nrfi": "no-run-first-inning",
    "yrfi": "yes-run-first-inning",
}

# Longest phrase first, so "money line" is not lost to a shorter accidental
# match and "first five" is not lost to a hypothetical shorter alias.
_MARKET_PHRASES = sorted(
    list(SUPPORTED_MARKETS) + list(UNSUPPORTED_MARKETS), key=len, reverse=True)

# American odds: a sign, then 3-5 digits. The sign is required -- an
# unsigned number is exactly the kind of thing this parser must not guess
# the meaning of (a jersey number, an over/under total, a year).
_PRICE_RE = re.compile(r'(?<![\w.-])([+-]\d{3,5})(?!\d)')


def _refuse(reason, ambiguous, raw_input):
    """One shape for every refusal: never a guess, always says what for."""
    return {"ok": False, "refused": True, "reason": reason,
            "ambiguous": ambiguous, "input": raw_input}


def _blank_span(text, span):
    """Replace one regex match with spaces so later passes cannot re-find it
    and cannot have it collapse two tokens together."""
    start, end = span
    return text[:start] + (" " * (end - start)) + text[end:]


def _find_market(text):
    """The first (longest) recognised market phrase in `text`, or (None, None).

    Every phrase is required to sit on a token boundary -- `\\brl\\b`-style --
    so a market word can never be "found" as a stray substring of a team name.
    """
    for phrase in _MARKET_PHRASES:
        pattern = (r'(?<![A-Za-z0-9])' + re.escape(phrase).replace(r'\ ', r'\s+')
                  + r'(?![A-Za-z0-9])')
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match, phrase
    return None, None


def _find_teams(text):
    """{canonical_abbrev: matched phrase} for every team nameable in `text`.

    Two independent routes, both reused rather than reimplemented:
    - every contiguous run of words is tried against
      `slate.team_abbrev_from_name` (the same nickname table the multibook
      boards are matched with), so "Yankees", "New York Yankees" and a
      trailing "the Yankees" all resolve the same way `prices.py` already
      resolves odds-feed club names.
    - every short alphabetic token is tried as a literal abbreviation through
      `parks.canonical_team`, the same alias table `prices.matchup_key` uses,
      so "NYY" and "ATH" resolve exactly as the price boards do.
    """
    tokens = re.findall(r"[A-Za-z']+", text)
    found = {}
    for i in range(len(tokens)):
        for j in range(i + 1, len(tokens) + 1):
            phrase = " ".join(tokens[i:j])
            abbrev = slate_mod.team_abbrev_from_name(phrase)
            if abbrev:
                found.setdefault(parks.canonical_team(abbrev), phrase)
    for token in tokens:
        if 2 <= len(token) <= 4:
            candidate = parks.canonical_team(token)
            if candidate in parks.PARKS:
                found.setdefault(candidate, token)
    return found


def parse(text) -> dict:
    """Strict bet-string parser. Success or a named refusal -- never a guess.

    On success: {"ok": True, "input": text, "team": <abbrev>, "market": "h2h",
    "price": <int>}. On failure: {"ok": False, "refused": True, "reason":
    <str>, "ambiguous": "team" | "market" | "price", "input": text}.
    """
    if not isinstance(text, str) or not text.strip():
        return _refuse("empty bet string", "team", text)
    raw = text

    price_matches = list(_PRICE_RE.finditer(text))
    if not price_matches:
        return _refuse(
            "no American price found (expected something like -125 or +140)",
            "price", raw)
    distinct = {m.group(1) for m in price_matches}
    if len(distinct) > 1:
        return _refuse(
            f"multiple prices found ({', '.join(sorted(distinct))}); state "
            "one price for one bet", "price", raw)
    price_match = price_matches[0]
    try:
        price = int(price_match.group(1))
        odds_math.american_to_decimal(price)
    except (ValueError, odds_math.OddsError) as exc:
        return _refuse(f"{price_match.group(1)!r} is not a usable American "
                       f"price: {exc}", "price", raw)
    working = _blank_span(text, price_match.span())

    market_match, phrase = _find_market(working)
    if market_match is None:
        return _refuse(
            "no market named; Bet Check only checks moneyline bets today -- "
            "say 'ML' or 'moneyline'", "market", raw)
    if phrase in UNSUPPORTED_MARKETS:
        return _refuse(
            f"the {UNSUPPORTED_MARKETS[phrase]} market is not supported yet; "
            "Bet Check only checks moneyline (h2h) bets", "market", raw)
    working = _blank_span(working, market_match.span())

    teams = _find_teams(working)
    if not teams:
        return _refuse(f"could not identify a team in {raw!r}", "team", raw)
    if len(teams) > 1:
        return _refuse(
            f"more than one team named ({', '.join(sorted(teams))}); a bet "
            "names exactly one side", "team", raw)
    team = next(iter(teams))

    return {"ok": True, "input": raw, "team": team,
            "market": SUPPORTED_MARKETS[phrase], "price": price}


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

def _side_for_team(dossier, team) -> str:
    """AWAY, HOME, or None -- team is compared canonically, the same way the
    price boards are matched to a game (prices.matchup_key)."""
    away, home = dossier.teams
    away_c = parks.canonical_team(away or "")
    home_c = parks.canonical_team(home or "")
    team_c = parks.canonical_team(team)
    if team_c == away_c:
        return detect.AWAY
    if team_c == home_c:
        return detect.HOME
    return None


def _board_quotes(board):
    if isinstance(board, dict):
        return board.get("quotes") or []
    if isinstance(board, list):
        return board
    return []


def _fmt_price(price):
    return f"+{price}" if isinstance(price, int) and price > 0 else str(price)


def _market_context(price, side, board) -> dict:
    """De-vigged consensus and best available for `side`, and where the
    stated price sits against each -- PRICE CONTEXT, never EV.

    Reuses `prices.snapshot` unchanged: the only new arithmetic here is
    comparing the stated price's raw implied probability against the same
    de-vigged consensus `snapshot` already computes, which is exactly the
    comparison `snapshot` itself makes for `improvement_points` -- not the
    model-probability-vs-market comparison `core.odds.edge` exists to guard.
    """
    quotes = _board_quotes(board)
    if not quotes:
        return {"available": False,
                "reason": "no multi-book board provided for this game",
                "label": prices_mod.LABEL}
    snapshot = prices_mod.snapshot(quotes)
    if "skipped" in snapshot:
        return {"available": False, "reason": snapshot["skipped"],
                "label": prices_mod.LABEL}
    detail = (snapshot.get("sides") or {}).get(side) or {}
    consensus = detail.get("consensus_probability")
    if detail.get("skipped") or consensus is None:
        return {"available": False,
                "reason": detail.get("skipped")
                or "no priceable consensus for this side",
                "label": prices_mod.LABEL}

    try:
        stated_decimal = odds_math.american_to_decimal(price)
        stated_implied = odds_math.american_to_probability(price)
    except odds_math.OddsError:
        stated_decimal = stated_implied = None

    beats_consensus = None
    stated_vs_consensus_points = None
    if stated_implied is not None:
        stated_vs_consensus_points = round(consensus - stated_implied, 5)
        beats_consensus = stated_vs_consensus_points > 0

    best_price = detail.get("best_price")
    beats_best_available = None
    if stated_decimal is not None and best_price is not None:
        try:
            beats_best_available = (
                stated_decimal > odds_math.american_to_decimal(best_price))
        except odds_math.OddsError:
            pass

    note = None
    if beats_consensus is True:
        note = (f"the stated price {_fmt_price(price)} beats the de-vigged "
               f"consensus by {stated_vs_consensus_points * 100:.2f} "
               "probability points -- that is line-shopping value, not "
               "expected value and not a prediction.")
    elif beats_consensus is False:
        note = (f"the stated price {_fmt_price(price)} does not beat the "
               "de-vigged consensus; this is price context, never expected "
               "value.")

    return {
        "available": True,
        "side": side,
        "books": (snapshot.get("dispersion") or {}).get("books"),
        "consensus_probability": consensus,
        "best_available": {"book": detail.get("best_book"), "price": best_price},
        "stated_price": price,
        "stated_vs_consensus_points": stated_vs_consensus_points,
        "beats_consensus": beats_consensus,
        "beats_best_available": beats_best_available,
        "label": prices_mod.LABEL,
        "note": note,
    }


_NO_EDGE_DISCLAIMER = (
    f"No predictive edge is claimed here: {analysis.HYPOTHESES_TESTED} "
    f"pre-registered hypotheses across {analysis.HYPOTHESIS_FAMILIES_WORD} "
    "families have been measured against outcomes and none has survived. "
    "Price context above is line-shopping value, never expected value.")


def _bottom_line(supporting, opposing) -> dict:
    """Honest, never a recommendation: supports, opposes, or does not
    distinguish -- always with the no-edge record attached."""
    if not supporting and not opposing:
        return {"verdict": "does_not_distinguish",
                "headline": ("The evidence gathered for this game does not "
                            "distinguish for or against this bet."),
                "disclaimer": _NO_EDGE_DISCLAIMER}
    if len(supporting) > len(opposing):
        headline = (f"{len(supporting)} finding(s) point toward this side, "
                   f"against {len(opposing)} pointing away.")
        verdict = "supports"
    elif len(opposing) > len(supporting):
        headline = (f"{len(opposing)} finding(s) point away from this side, "
                   f"against {len(supporting)} pointing toward it.")
        verdict = "opposes"
    else:
        headline = (f"{len(supporting)} finding(s) point each way; the "
                   "evidence does not distinguish for or against this bet.")
        verdict = "does_not_distinguish"
    return {"verdict": verdict, "headline": headline,
            "disclaimer": _NO_EDGE_DISCLAIMER}


def check(bet, dossier, board=None, findings=None) -> dict:
    """The verdict object for one stated bet against one game's dossier.

    `bet` is a bet string, or an already-`parse`d dict -- a parse failure
    (from either) is returned unchanged rather than raising. `board` is the
    multi-book board for this game (a {"quotes": [...]} dict, e.g.
    `dossier.get("multibook_board")`, or a bare list of quotes); omit it and
    market context is honestly reported unavailable rather than guessed.
    `findings` defaults to running every registered detector over `dossier`
    (`detect.run_all`); pass it explicitly to reuse findings already computed
    for the same dossier so a slate does not run every detector twice.
    """
    parsed = bet if isinstance(bet, dict) else parse(bet)
    if not parsed.get("ok"):
        return parsed

    side = _side_for_team(dossier, parsed["team"])
    if side is None:
        away, home = dossier.teams
        return _refuse(
            f"{parsed['team']} does not name either side of this game "
            f"({away} at {home}); this bet is not on this game's slate",
            "team", parsed.get("input"))
    opposite = detect.HOME if side == detect.AWAY else detect.AWAY

    if findings is None:
        findings = detect.run_all(dossier)

    supporting, opposing, warnings = [], [], []
    for finding in findings or []:
        # CONTEXT is deliberately excluded: it is "shown but never ranked"
        # (detect.base.rank) -- true and relevant, but not evidence for or
        # against a side, and promoting it here would manufacture a lean out
        # of background the reader already assumes.
        if getattr(finding, "kind", None) == detect.CONTEXT:
            continue
        if finding.side not in (side, opposite):
            continue
        # A claim without both a sample and an evidence label cannot enter
        # this object -- the pairing is structural, not a rendering choice.
        if finding.sample is None or finding.surprise is None:
            warnings.append({
                "detector": finding.detector, "claim": finding.claim,
                "reason": ("no sample size attached" if finding.sample is None
                           else "surprise not expressible on a comparable "
                           "scale, so it cannot be weighed against the rest")})
            continue
        label, meaning = synthesis_mod.EVIDENCE_LABELS.get(
            finding.evidence, (finding.evidence, ""))
        entry = {
            "detector": finding.detector,
            "kind": finding.kind,
            "claim": finding.claim,
            "side": finding.side,
            "sample": finding.sample,
            "sample_n": synthesis_mod.sample_size(finding.sample),
            "surprise": finding.surprise,
            "evidence": finding.evidence,
            "evidence_label": label,
            "evidence_meaning": meaning,
        }
        (supporting if finding.side == side else opposing).append(entry)

    return {
        "ok": True,
        "input": parsed.get("input"),
        "bet": {"team": parsed["team"], "market": parsed["market"],
               "price": parsed["price"]},
        "game": dict(dossier.game),
        "side": side,
        "supporting": supporting,
        "opposing": opposing,
        "sample_quality_warnings": warnings,
        "market_context": _market_context(parsed["price"], side, board),
        "what_changed": dossier.get("what_changed"),
        "bottom_line": _bottom_line(supporting, opposing),
    }


# ---------------------------------------------------------------------------
# build_contract(): the structured, paid-beta path -> BetCheckContract
# ---------------------------------------------------------------------------

def _claim_from_finding(finding) -> c.Claim:
    """One Finding as a customer Claim.

    A claim only carries `value` when it can also carry a positive
    `sample_n` and a non-empty `sample_unit` -- Rule S, enforced by the
    dataclass itself (Claim.__post_init__). `sample_unit` is the finding's
    own sample string verbatim ("8 hitters, 340 plate appearances") rather
    than a short unit word: that string IS the sample line the product
    promises, not a label for one.
    """
    sample_n = synthesis_mod.sample_size(finding.sample)
    quantitative = bool(finding.sample) and finding.value is not None \
        and sample_n is not None and sample_n > 0
    return c.Claim(
        statement=finding.claim,
        value=finding.value if quantitative else None,
        sample_n=sample_n if quantitative else None,
        sample_unit=finding.sample if quantitative else None,
        evidence_label=finding.evidence,
    )


def _cents_delta(stated_price, market_price):
    """The stated price minus the market's best price, in American-odds
    "cents" -- the sportsbook convention of comparing two same-side lines
    directly (e.g. -110 vs -105 is 5 cents). Mixed-sign prices are not
    directly comparable this way (the scale is not linear across the
    +100/-100 boundary), so this returns None rather than a misleading raw
    subtraction; `beats_consensus`-style probability comparisons already
    cover that case in `_market_facts`.
    """
    if stated_price is None or market_price is None:
        return None
    if (stated_price > 0) != (market_price > 0):
        return None
    return stated_price - market_price


def _market_facts(side, american_price, board) -> dict:
    """Best available price, market-implied consensus, price improvement and
    whether the stated price BEATS the consensus -- or an explicit
    unavailable reason. Never a default: a missing board, a thin board, or a
    side with no priceable quote all come back with every price field None
    and a stated reason, exactly the "never fabricate" rule §4.11 states for
    a board without its capture instant.
    """
    quotes = _board_quotes(board)
    observed_utc = board.get("observed_utc") if isinstance(board, dict) else None
    unavailable = dict(best_available_price=None, market_consensus=None,
                       your_price_beats_consensus=None, price_improvement=None,
                       cents_delta=None)

    if not quotes:
        return dict(unavailable, reason="no multi-book board provided for this game")

    snapshot = prices_mod.snapshot(quotes)
    if "skipped" in snapshot:
        return dict(unavailable, reason=snapshot["skipped"])
    if not observed_utc:
        return dict(unavailable, reason=("the board carries no capture instant; "
                                         "a board without one is not a board"))

    detail = (snapshot.get("sides") or {}).get(side) or {}
    consensus_probability = detail.get("consensus_probability")
    if detail.get("skipped") or consensus_probability is None:
        return dict(unavailable, reason=(detail.get("skipped")
                                         or "no priceable consensus for this side"))

    best_price = c.QuotedPrice(book=detail.get("best_book"),
                               american_price=detail.get("best_price"),
                               observed_utc=observed_utc)
    consensus = c.MarketImpliedConsensus(
        implied_probability=consensus_probability,
        books=(snapshot.get("dispersion") or {}).get("books"),
        observed_utc=observed_utc)
    improvement = c.PriceImprovement(
        best=best_price, consensus=consensus,
        improvement_points=detail.get("improvement_points"),
        improvement_return_pct=detail.get("improvement_return_pct"))

    # "Beats" is decided in DECIMAL odds, the same arithmetic _cents_delta
    # and the price-direction regression (test_betcheck_price_direction.py)
    # already anchor on: the higher of two decimal payouts is the better
    # price. The consensus is stated as an implied probability, so its
    # equivalent decimal payout is 1 / implied_probability -- consensus
    # probability is validated in (0, 1) by MarketImpliedConsensus before
    # this ever runs, so the division is safe.
    try:
        stated_decimal = odds_math.american_to_decimal(american_price)
        consensus_decimal = 1.0 / consensus_probability
    except odds_math.OddsError:
        stated_decimal = None
    your_price_beats_consensus = (
        stated_decimal > consensus_decimal if stated_decimal is not None
        else None)

    return dict(best_available_price=best_price, market_consensus=consensus,
               your_price_beats_consensus=your_price_beats_consensus,
               price_improvement=improvement,
               cents_delta=_cents_delta(american_price, detail.get("best_price")),
               reason=None)


def _evidence_status(claims) -> "str | None":
    """The single highest customer-evidence label across every surviving
    claim, or None when there are none to grade -- never a fabricated
    default badge."""
    if not claims:
        return None
    best = max(claims, key=lambda k: c.customer_evidence(k.evidence_label).tier)
    return c.customer_evidence(best.evidence_label).label


def _historical_support(support_claims) -> "str | None":
    """Weak/Moderate/Strong from the best evidence tier backing the stated
    side, or None with no supporting claims at all -- the contract only
    accepts those three words or None (BetCheckContract.__post_init__)."""
    if not support_claims:
        return None
    top_tier = max(c.customer_evidence(k.evidence_label).tier
                   for k in support_claims)
    if top_tier >= 4:
        return "Strong"
    if top_tier >= 3:
        return "Moderate"
    return "Weak"


def _bottom_line_text(support_n, counter_n, market) -> str:
    """One sentence on the count split, one on price (or its absence), then
    the permanent no-edge record -- composed from parts, never a single
    hand-written verdict string."""
    if support_n == 0 and counter_n == 0:
        lead = ("The evidence gathered for this game does not distinguish "
                "for or against this bet.")
    elif support_n > counter_n:
        lead = (f"{support_n} finding(s) point toward this side, against "
               f"{counter_n} pointing away.")
    elif counter_n > support_n:
        lead = (f"{counter_n} finding(s) point away from this side, against "
               f"{support_n} pointing toward it.")
    else:
        lead = (f"{support_n} finding(s) point each way; the evidence does "
               "not distinguish for or against this bet.")

    if market["reason"] is not None:
        price_clause = f" Market context is unavailable: {market['reason']}."
    else:
        cents = market["cents_delta"]
        best = market["best_available_price"]
        if cents is None or best is None:
            price_clause = (" The stated price sits against a de-vigged "
                            "consensus below -- line-shopping value, not a "
                            "prediction.")
        # DIRECTION, stated once so it cannot be re-derived wrong: for two
        # same-sign American prices on the same side, a HIGHER number is the
        # better price for the bettor (-105 risks less than -110 to win the
        # same; +150 pays more than +140). `cents_delta` is stated minus
        # best, so cents > 0 means the stated price BEATS the best number on
        # our board -- it does not mean it is worse than it.
        elif cents > 0:
            unit = "cent" if cents == 1 else "cents"
            price_clause = (f" The stated price is {cents} {unit} better than "
                           f"the best available {_fmt_price(best.american_price)} "
                           "-- line-shopping value, not a prediction.")
        elif cents < 0:
            unit = "cent" if abs(cents) == 1 else "cents"
            price_clause = (f" The stated price is {abs(cents)} {unit} worse "
                           f"than the best available "
                           f"{_fmt_price(best.american_price)} -- "
                           "line-shopping value, not a prediction.")
        else:
            price_clause = (" The stated price matches the best available "
                            "price on the board.")

    return lead + price_clause + " " + _NO_EDGE_DISCLAIMER


def _change_item(event: dict) -> "c.ChangeItem | None":
    """One roster-change event as a customer ChangeItem, or None when it has
    no headline -- a blank headline is not a fabricated one."""
    headline = event.get("headline") or event.get("summary")
    if not headline:
        return None
    tier = event.get("tier")
    if tier not in (relevance_mod.HIGH, relevance_mod.MEDIUM,
                    relevance_mod.LOW, relevance_mod.UNKNOWN):
        tier = relevance_mod.UNKNOWN
    return c.ChangeItem(seen_utc=event.get("seen_utc") or "",
                        category=event.get("category") or event.get("class")
                                 or "roster",
                        headline=headline, tier=tier,
                        game_id=event.get("game_id"))


def build_contract(date, away_club, home_club, side, american_price, *,
                   board=None, findings=None, what_changed=None,
                   game_pk=None, game_number=None, venue=None,
                   start_time_utc=None) -> c.BetCheckContract:
    """The Bet Check API's whole engine step: a structured bet in, a
    `BetCheckContract` out.

    `date`/`away_club`/`home_club` identify the game (clubs are run through
    `parks.canonical_team`, the same alias table the price boards use, so
    "ATH" and "OAK" name the same game here that they do everywhere else).
    `side` is `"away"` or `"home"` -- the API layer has already resolved the
    caller's team name to a side before this is called, so there is no
    parsing or guessing left to do here. `american_price` is the caller's
    stated price for that side.

    `board` is the game's multi-book board -- a `{"quotes": [...],
    "observed_utc": ...}` dict (`dossier.get("multibook_board")`, or
    `src.analysis.prices.boards_by_matchup()[...]`), or a bare list of
    quotes (in which case there is no capture instant and market context is
    reported unavailable rather than guessed). `findings` is the list of
    `Finding`s already computed for this game (`detect.run_all(dossier)`,
    or whatever a caller already has); passing it in avoids recomputing
    detectors this function has no dossier to run them against.
    `what_changed` is an optional list of raw roster-event dicts.

    NO MODEL WIN PROBABILITY is computed, read, or threaded through here --
    the market context is priced entirely from the board
    (`prices.snapshot`), never from the uncalibrated model.
    """
    if side not in (detect.AWAY, detect.HOME):
        raise ValueError(f"side must be 'away' or 'home', got {side!r}")

    away = parks.canonical_team(away_club or "")
    home = parks.canonical_team(home_club or "")
    # canonical_team passes an unrecognised token straight through rather
    # than raising, so an unknown club must be checked against the park
    # table explicitly -- the same check _find_teams uses above -- or a
    # typo'd club would silently become "the game against itself" instead
    # of a refusal.
    if away not in parks.PARKS or home not in parks.PARKS:
        raise ValueError(
            "away_club and home_club must each name a known MLB club")
    team = away if side == detect.AWAY else home
    opposite_side = detect.HOME if side == detect.AWAY else detect.AWAY

    game_ref = c.GameRef(
        game_id=gamepayload.game_id({"away_team": away, "home_team": home,
                                     "date": date, "game_number": game_number,
                                     "game_pk": game_pk}),
        away=away, home=home, date=date, start_time_utc=start_time_utc,
        venue=venue)

    query = c.BetQuery(raw=f"{team} h2h {_fmt_price(american_price)}",
                       parsed=True, team=team, side=side, market="h2h",
                       price=american_price)

    support_claims, counter_claims = [], []
    strongest_claim = weakest_claim = None
    strongest_surprise = weakest_surprise = None
    for finding in findings or []:
        # CONTEXT findings are shown but never ranked (detect.base.rank) --
        # true and relevant, not evidence for or against a side. Same
        # exclusion `check()` makes above.
        if getattr(finding, "kind", None) == detect.CONTEXT:
            continue
        if finding.side not in (side, opposite_side):
            continue
        claim_obj = _claim_from_finding(finding)
        if finding.side == side:
            support_claims.append(claim_obj)
            if finding.surprise is not None and (
                    strongest_surprise is None
                    or finding.surprise > strongest_surprise):
                strongest_claim, strongest_surprise = finding.claim, finding.surprise
        else:
            counter_claims.append(claim_obj)
            if finding.surprise is not None and (
                    weakest_surprise is None
                    or finding.surprise > weakest_surprise):
                weakest_claim, weakest_surprise = finding.claim, finding.surprise

    market = _market_facts(side, american_price, board)
    changes = tuple(item for item in
                    (_change_item(ev) for ev in (what_changed or []))
                    if item is not None)

    return c.BetCheckContract(
        query=query,
        game=game_ref,
        thesis_support=tuple(support_claims),
        counterargument=tuple(counter_claims),
        best_available_price=market["best_available_price"],
        market_consensus=market["market_consensus"],
        your_price_beats_consensus=market["your_price_beats_consensus"],
        what_changed=changes,
        strongest_reason=strongest_claim,
        weakest_reason=weakest_claim,
        historical_support=_historical_support(support_claims),
        evidence_status=_evidence_status(support_claims + counter_claims),
        bottom_line=_bottom_line_text(len(support_claims), len(counter_claims),
                                      market),
        price_improvement=market["price_improvement"],
    )
