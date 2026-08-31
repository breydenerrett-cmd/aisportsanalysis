"""Price improvement: the best number on the board versus the consensus.

WHAT THIS IS
------------
Given one instant's multi-book quotes for a game, this module reports, per
side: the best available American price and who quotes it, the de-vigged
consensus across the board, the improvement of the best price over the
consensus expressed both in implied-probability points and as a percentage
of return, and how dispersed the books are. That is Engine 1 of the Ranker
design and the Analyzer's market section, in library form.

WHAT THIS IS NOT — READ BEFORE REUSING
--------------------------------------
Price improvement is LINE-SHOPPING VALUE: a better execution price on a bet
whose worth is a separate, unanswered question. It is not positive expected
value, not a predictive edge, not guaranteed profit, and not "real money
regardless of who wins" — that phrasing was retired deliberately
(docs/PLAN_TWO_TOOLS.md). A price only counts at all if it was actually
quoted when shown, which is exactly what the observation timestamp records
and all it records. Every dict this module returns carries a `label` field
saying so, and the dashboard renders that label; removing it is a product
decision nobody gets to make silently.
"""

from __future__ import annotations

from src.core import odds as odds_math

# A consensus over fewer books is that handful's opinion, not a market's.
# Same floor as everywhere else in the system.
MIN_BOOKS = 6

LABEL = ("price improvement / line-shopping value -- a better execution "
         "price, not expected value and not a prediction")

# Said whenever no side on a board beats the de-vigged consensus, which on a
# normally-priced board is every side. Without it a column of negatives reads
# as a verdict on the night instead of as the definition of the two numbers
# being subtracted. This used to live in the renderer (twice -- dashboard.py
# and ranker.py each kept their own copy of the sign logic), which meant a
# reader could see the two pages disagree about whether a board had anything
# positive on it. `snapshot()` computes the sign itself now, once, and every
# renderer just displays what it is handed.
NO_IMPROVEMENT_NOTE = (
    "No side here beats the de-vigged consensus, and that is the usual case "
    "rather than a bad board: the best available price still carries the "
    "book's vig while the consensus it is measured against has had the vig "
    "removed, so the difference is normally negative by roughly the hold. A "
    "positive number is the exception worth noticing; these are not.")

# Where a board came from, carried on the board itself. A finding or a table
# that describes a board has to be able to name the store and the instant it
# read, because "11 books" means nothing without them.
SOURCE = "multi-book capture store"


def format_probability_points(value) -> str:
    """A probability DIFFERENCE, formatted in win-probability POINTS, or "--".

    The store keeps these as fractions (0.019). Rendering the fraction under a
    heading that says "points" understates it a hundredfold and puts it on a
    different scale from every detector sentence on the same page, which all
    say "N points of win probability". Two decimals is the honest resolution:
    the inputs are American prices, and a third digit is arithmetic noise.

    dashboard.py and ranker.py each used to keep their own copy of this
    conversion; one number formatted two ways in two places is exactly the
    class of drift this module exists to prevent, so both now call this one.
    """
    return "--" if value is None else f"{value * 100:+.2f}"


def _decimal(price):
    try:
        return odds_math.american_to_decimal(price)
    except odds_math.OddsError:
        return None


def snapshot(quotes) -> dict:
    """The price-improvement picture for ONE instant's quotes.

    quotes: [{book, away_price, home_price}, ...] — one row per book, all
    observed at the same capture moment (the caller slices by time; mixing
    instants here would compare a stale best against a fresh consensus,
    manufacturing improvement out of latency).

    Returns {"skipped": reason} below the book floor — thin boards produce
    stories, not numbers.
    """
    fairs, priced = [], []
    for quote in quotes or []:
        away, home = quote.get("away_price"), quote.get("home_price")
        try:
            fair_away, fair_home = odds_math.devig_two_way(away, home)
        except odds_math.OddsError:
            continue
        fairs.append((fair_away, fair_home))
        priced.append((quote.get("book"), away, home, fair_away, fair_home))
    if len(priced) < MIN_BOOKS:
        return {"skipped": (f"{len(priced)} books quoted; below the "
                            f"{MIN_BOOKS}-book floor a consensus means "
                            "nothing")}

    n = len(priced)
    consensus_away = sum(f[0] for f in fairs) / n
    consensus_home = sum(f[1] for f in fairs) / n

    sides = {}
    for side, price_index, consensus in (("away", 1, consensus_away),
                                         ("home", 2, consensus_home)):
        best_book, best_price, best_decimal = None, None, None
        for entry in priced:
            decimal = _decimal(entry[price_index])
            if decimal is None:
                continue
            if best_decimal is None or decimal > best_decimal:
                best_book, best_price, best_decimal = (
                    entry[0], entry[price_index], decimal)
        if best_decimal is None:
            sides[side] = {"skipped": "no priceable quote on this side"}
            continue
        # Improvement in implied-probability points: what the best price
        # implies (with no vig adjustment -- it is the price you would
        # actually take) versus what the de-vigged board thinks. Negative
        # improvement is reported as-is: on a heavily vigged board the best
        # available price can still imply MORE than the fair consensus.
        implied_best = 1.0 / best_decimal
        consensus_decimal = 1.0 / consensus
        sides[side] = {
            "best_book": best_book,
            "best_price": best_price,
            "consensus_probability": round(consensus, 5),
            "improvement_points": round(consensus - implied_best, 5),
            "improvement_return_pct": round(
                (best_decimal / consensus_decimal - 1.0) * 100.0, 3),
        }

    dispersion = {
        "books": n,
        # Range of de-vigged home probabilities across the board: how much
        # the books disagree, which is context for how much shopping matters.
        "home_probability_range": round(
            max(f[1] for f in fairs) - min(f[1] for f in fairs), 5),
    }
    # A derived boolean the renderer used to compute for itself -- does ANY
    # side here beat the de-vigged consensus? -- plus the note that explains
    # the answer when it is no. Computing it here means a page can never
    # print "no improvement" for a board that actually has one, or vice
    # versa, because there is exactly one place that decides.
    any_positive = any(
        detail.get("improvement_points") is not None
        and detail["improvement_points"] > 0
        for detail in sides.values())
    return {"sides": sides, "dispersion": dispersion, "label": LABEL,
            "any_positive": any_positive,
            "note": None if any_positive else NO_IMPROVEMENT_NOTE}


def latest_instant(quotes) -> list:
    """The most recent capture instant's quotes, one row per book.

    Multibook rows accumulate across captures; the board a reader should see
    is the newest complete one. Rows share an instant when they share an
    observed timestamp; per book, the newest row wins.
    """
    if not quotes:
        return []
    newest = max(q.get("ts") or "" for q in quotes)
    by_book = {}
    for quote in quotes:
        if (quote.get("ts") or "") == newest and quote.get("book"):
            by_book[quote["book"]] = quote
    return list(by_book.values())


def for_game(away_team=None, home_team=None, date=None, rows=None) -> dict:
    """The price-improvement section for one game, from the multibook store."""
    from src.pipeline import snapshots

    quotes = snapshots.multibook_quotes(away_team=away_team,
                                        home_team=home_team, date=date,
                                        rows=rows)
    if not quotes:
        return {"skipped": "no multi-book observations recorded for this game"}
    board = latest_instant(quotes)
    result = snapshot(board)
    if "skipped" not in result:
        result["observed_utc"] = board[0].get("ts")
    return result


def matchup_key(away, home, date) -> tuple:
    """The key a board is filed under, and the only key to look one up by.

    Canonical abbreviations, because the same franchise is spelled differently
    by different sources: the MLB schedule (and so the briefing) says ATH and
    AZ where the odds feed's club names resolve to OAK and ARI. Comparing raw
    abbreviations dropped exactly those two clubs' boards -- on 2026-08-31 the
    Athletics and Diamondbacks cards reported no multi-book board while the
    store held eleven books apiece. src/pipeline/slate.py carries the same fix
    for the same reason; this is that lesson applied to the price stores.
    """
    from src.data import parks

    return (parks.canonical_team(away or ""),
            parks.canonical_team(home or ""), date)


def boards_by_matchup(rows=None) -> dict:
    """{(away_abbrev, home_abbrev, date): board} for the multibook store.

    A board is {"quotes": [...], "observed_utc": ts, "source": SOURCE}: ONE
    capture instant, one row per book, exactly the list `snapshot` summarises.

    THIS FUNCTION IS THE POINT. A game card used to describe its board twice
    from two different stores -- the stale_book detector counted the per-game
    snapshot's `all_books`, the price table counted this store -- so the same
    market rendered as "11 books" in one line and "10 books" two inches below
    (docs/OVERNIGHT_RUN.md, 2026-08-31, write-up #4). Both surfaces now read
    the board this function returns, so the counts cannot disagree: they are
    the same list. Anything else that wants to describe a game's board reads
    it here too rather than re-deriving one.

    The multibook store speaks the odds API's full club names; the briefing
    speaks abbreviations. The translation happens here, once, so the
    briefing can look a game up by the key it already has. Rows that name a
    club the translator does not recognise are dropped -- an unmatchable row
    can only ever mislabel a game.

    The date is MLB's OFFICIAL (Eastern) date, via snapshots.official_date,
    not the leading ten characters of the UTC commence time. Slicing UTC
    filed every West Coast game -- a 20:41 ET first pitch is 00:41 UTC the
    next day -- under tomorrow's key, where the briefing (which keys by the
    official date, like everything else in this project) never looked. Those
    games silently showed no board at all while the detector, reading the
    other store, happily reported eleven books.
    """
    from src.pipeline import slate as slate_mod
    from src.pipeline import snapshots

    source = snapshots.read_multibook() if rows is None else rows
    grouped = {}
    for row in source:
        away = slate_mod.team_abbrev_from_name(row.get("away_team") or "")
        home = slate_mod.team_abbrev_from_name(row.get("home_team") or "")
        date = snapshots.official_date(row.get("commence_time"))
        if not away or not home or not date:
            continue
        grouped.setdefault(matchup_key(away, home, date), []).append(row)
    boards = {}
    for key, group in grouped.items():
        quotes = [{"ts": r.get("observed_utc"), "book": r.get("book"),
                   "away_price": r.get("away_price"),
                   "home_price": r.get("home_price")} for r in group]
        board = latest_instant(quotes)
        if not board:
            continue
        boards[key] = {"quotes": board, "observed_utc": board[0].get("ts"),
                       "source": SOURCE}
    return boards


def by_matchup(rows=None, boards=None) -> dict:
    """{(away_abbrev, home_abbrev, date): improvement section} for a store.

    Summarises the boards from `boards_by_matchup`. Callers that also need
    the raw boards (the briefing does -- the stale_book detector reads them)
    build them once and pass them in, so a slate reads the store once and
    every surface describes the identical board.
    """
    source = boards_by_matchup(rows) if boards is None else boards
    out = {}
    for key, board in source.items():
        section = snapshot(board.get("quotes") or [])
        if "skipped" not in section:
            section["observed_utc"] = board.get("observed_utc")
        out[key] = section
    return out
