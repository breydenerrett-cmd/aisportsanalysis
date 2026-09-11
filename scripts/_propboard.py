"""The captured player-prop board, assembled once so two probes cannot drift.

WHY THIS EXISTS
---------------
`probe_prop_value.py` asks where our number beats a price.
`prereg_market_vs_model.py` asks which number predicts the outcome better.

They must read the SAME board. If each built its own -- same intent, separate
code -- a quiet divergence in how a two-way pair is de-vigged or which instant
counts as "newest" would make the two disagree, and the disagreement would be
read as a finding about baseball rather than about the instrument. This repo
has chased that ghost five times in two days: a spacing difference in a text
prefilter that matched zero of 1,054 rows, an attribute typo that silently
returned `None`, an ablation arm that was byte-identical to the control and
still printed a verdict.

So the board is built here, once, and both scripts import it.

Read-only. Reads no outcome to decide what goes on the board.

Leading underscore: a helper for `scripts/`, not a public module, and
deliberately not in `src/` -- it reads a capture store, which is pipeline
work, and `src/analysis` stays pure.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import playerprops  # noqa: E402
from src.core import odds as odds_math  # noqa: E402
from src.pipeline import boxscores  # noqa: E402

BOX_STORE = os.path.join("data", "processed", "boxscores_2026.jsonl")
PROP_STORE = os.path.join("data", "processed", "batter_props.jsonl")

# A pair whose two sides sum below this cannot be a real two-way market --
# a book always prices both sides above 100% and that excess is its margin.
# Same floor and same reason as src/analysis/derivative_prices.py's.
MIN_TWO_WAY_BOOKSUM = 0.98

# Below this many books quoting BOTH sides of one player-line, a "consensus"
# is a handful's opinion rather than a market.
#
# TWO, NOT THREE, AND THE REASON IS MEASURED. At three this examined 12% of
# the board and the survivors bunched on whichever date happened to get a
# fuller capture -- 13 of the top 18 findings came from one day. Player-prop
# boards are simply thinner two-way than game boards: only 40% of total-base
# contracts carry three books quoting both sides, and 10% of hits contracts,
# though 56-75% carry two.
#
# Two is a real weakening and it is stated rather than hidden. It is not a
# threshold moved to produce more findings -- it is moved because three was
# selecting on capture depth rather than on anything about the bets.
MIN_BOOKS = 2

# Which box-score column settles each market's over.
OUTCOME_FIELD = {
    "batter_hits": "h",
    "batter_total_bases": "total_bases",
    "batter_home_runs": "hr",
    "batter_runs_scored": "r",
}


def assessable(market) -> bool:
    """BOTH gates, and they ask different questions.

    `publishable` asks whether the MODEL is any good on this market;
    `deviggable` asks whether a fair price EXISTS to measure against. Home
    runs pass the first and fail the second -- no book quotes the under, so a
    "gap" there is measured against a raw price that still contains the
    book's whole margin, which is not value and is not ours.
    """
    return (playerprops.publishable(market or "")
            and playerprops.deviggable(market or ""))


def read_props(path=PROP_STORE):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rows.append(json.loads(raw))
            except ValueError:
                continue
    return rows


def read_batters(path=BOX_STORE):
    """Every batter box-score line, plus a name index sorted by date."""
    box = [r for r in boxscores.read(path) if r.get("type") == "batter"]
    by_name = defaultdict(list)
    for row in box:
        name = row.get("player_name")
        if name:
            by_name[name].append(row)
    for lines in by_name.values():
        lines.sort(key=lambda r: str(r.get("date") or ""))
    return box, by_name


def slot_index():
    """Tonight's batting slot by (date, player name).

    The prop store carries the odds feed's event id and the lineup store
    carries game_pk, so a name-and-date join avoids a mapping that could
    silently match nothing -- and a batter appears once per date, so it is
    unambiguous.

    An empty index is a gap in coverage, not a crash: the posted-lineup store
    covers far fewer games than the price store.
    """
    index = {}
    try:
        from src.pipeline import lineup_store
        for card in (lineup_store.read() or {}).values():
            if not isinstance(card, dict):
                continue
            date = str(card.get("date") or "")
            for side in ("away", "home"):
                for entry in card.get(side) or ():
                    if entry.get("name") and entry.get("order"):
                        index[(date, entry["name"])] = entry["order"]
    except Exception:  # noqa: BLE001 -- no lineups is a gap, not a crash
        return {}
    return index


def build_contracts(props):
    """Group prices into contracts, keeping only each book's newest quote.

    One contract is (date, event, player, market, line). Within it, one price
    per book per side, taken at the newest instant that contract was seen --
    a book that moved its line during the day should be read at where it
    ended, not at an average of where it passed through.
    """
    newest = {}
    for row in props:
        if not assessable(row.get("market")):
            continue
        key = (row.get("game_date"), row.get("event_id"), row.get("player"),
               row.get("market"), str(row.get("line")))
        stamp = row.get("observed_utc") or ""
        if stamp > newest.get(key, ""):
            newest[key] = stamp

    contracts = defaultdict(lambda: defaultdict(dict))
    for row in props:
        if not assessable(row.get("market")):
            continue
        key = (row.get("game_date"), row.get("event_id"), row.get("player"),
               row.get("market"), str(row.get("line")))
        if (row.get("observed_utc") or "") != newest.get(key):
            continue
        side = row.get("side")
        if side in ("Over", "Under") and row.get("book"):
            contracts[key][row["book"]][side] = row.get("price")
    return contracts


def devig(books):
    """De-vig each book's two-way pair; return the fair overs and best price.

    A gap measured against a RAW price partly IS the book's margin, which is
    not value and does not belong to us. Every fair probability returned here
    has had its book's own margin removed first.

    Returns (fair_overs, best_over_american, best_over_decimal, best_book).
    """
    fair_overs, best = [], None
    for book, sides in books.items():
        over, under = sides.get("Over"), sides.get("Under")
        if over is None or under is None:
            continue
        try:
            raw = (odds_math.american_to_probability(over)
                   + odds_math.american_to_probability(under))
            if raw < MIN_TWO_WAY_BOOKSUM:
                continue
            fair_over, _fair_under = odds_math.devig_two_way(over, under)
            decimal = odds_math.american_to_decimal(over)
        except (odds_math.OddsError, TypeError, ValueError,
                ZeroDivisionError):
            continue
        fair_overs.append(fair_over)
        if best is None or decimal > best[1]:
            best = (over, decimal, book)
    if best is None:
        return fair_overs, None, None, None
    return fair_overs, best[0], best[1], best[2]


def resolve(by_name, player, date, market, line):
    """Did the over hit? `None` when nothing settles it.

    ABSENT IS NOT ZERO. A batter with no box-score line for that date did not
    go 0-for-4 -- he may have been scratched, the game may not be ingested,
    the name may not have matched. Returning 0 there would score a
    non-observation as a loss.
    """
    field = OUTCOME_FIELD.get(market)
    if field is None:
        return None
    for row in by_name.get(player, ()):
        if str(row.get("date") or "") == str(date):
            got = row.get(field)
            if got is None:
                return None
            try:
                return 1 if int(got) > line else 0
            except (TypeError, ValueError):
                return None
    return None
