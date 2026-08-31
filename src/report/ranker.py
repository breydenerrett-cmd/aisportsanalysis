"""The Ranker shell: the page that refuses to rank until an edge is earned.

THE TWO ENGINES
---------------
Engine 1 is price improvement -- the best number on the board versus the
de-vigged consensus (src/analysis/prices.py). It is honest today and it is
ALL this page shows.

Engine 2 is predicted value. It requires a demonstrated edge, and none
exists: see src.analysis.HYPOTHESES_TESTED pre-registered hypotheses across
HYPOTHESIS_FAMILIES research families, zero survivors -- the count lives
there so no two surfaces can disagree about it, which they did (this banner
said twenty-four while the briefing header said thirteen and its game cards
said 27). ENGINE2 below is therefore None, and the page
says so in its banner. It stays None until every unlock condition in
docs/PLAN_TWO_TOOLS.md is met -- pre-registered discovery pass, the
falsification battery, 300+ forward selections, and Brey's sign-off --
at which point changing it is a deliberate, reviewed act.

tests/test_ranker.py pins all of this structurally: while ENGINE2 is None
the page contains no bet recommendation, no pick, no unit size, and no
"edge" language. The gate cannot be removed by accident, only by a visible
diff that fails a test until the evidence exists.
"""

from __future__ import annotations

import html

import src.analysis as analysis
from src.analysis import prices as prices_mod

# The predictive engine. None means: no demonstrated edge exists. See the
# module docstring for what changing this requires.
ENGINE2 = None

# The banner used to assert that everything below is "where the best available
# price beats the market's own consensus". On a normally-vigged board that is
# false for every row: the best available price still carries vig while the
# consensus it is measured against has had the vig removed, so the difference
# is negative by roughly the hold. A real board was rendered with twenty-four
# rows, all negative, under a sentence saying each one beat the consensus --
# and sorted best-first, so the top row read as the day's best opportunity. The
# banner now describes the subtraction instead of promising its sign.
BANNER = (
    "No predictive edge exists. "
    f"{analysis.HYPOTHESES_TESTED_WORD} pre-registered hypotheses across "
    f"{analysis.HYPOTHESIS_FAMILIES_WORD} research families have been tested; "
    "none survived. Everything below is PRICE IMPROVEMENT -- the best "
    "available price measured against the market's own de-vigged consensus. "
    "That comparison is normally NEGATIVE, because the price you can actually "
    "take still carries the book's vig and the consensus does not; a positive "
    "row is the exception, not the rule, and this board is sorted best-first "
    "whether or not anything on it is positive. Even a positive row is only a "
    "better execution price on a wager that this page is NOT telling you to "
    "place. Nothing here is a recommendation.")

# Printed above the table whenever no row clears zero, so the sign of the
# column is never left for the reader to interpret on their own.
ALL_NEGATIVE_NOTE = (
    "Not one side on today's board beats the de-vigged consensus. The rows "
    "below are ranked least-bad first; none of them is a price improvement.")

SOME_POSITIVE_NOTE = (
    "Rows above the zero line beat the de-vigged consensus; rows below it do "
    "not, and are shown rather than hidden so the board is the whole board.")


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def rows(price_index) -> list:
    """The day's price-improvement list, best improvement first.

    price_index: prices.by_matchup() output. Only sides with a computed
    improvement appear; thin boards stay off the list entirely rather than
    padding it with noise.
    """
    out = []
    for (away, home, date), section in (price_index or {}).items():
        if section.get("skipped"):
            continue
        for side, detail in (section.get("sides") or {}).items():
            if detail.get("skipped"):
                continue
            out.append({
                "date": date, "away": away, "home": home, "side": side,
                "team": away if side == "away" else home,
                "best_book": detail.get("best_book"),
                "best_price": detail.get("best_price"),
                "consensus_probability": detail.get("consensus_probability"),
                "improvement_points": detail.get("improvement_points"),
                "improvement_return_pct": detail.get("improvement_return_pct"),
                "books": (section.get("dispersion") or {}).get("books"),
            })
    out.sort(key=lambda r: -(r.get("improvement_points") or 0.0))
    return out


def render(price_index=None) -> str:
    """The Ranker page. While ENGINE2 is None it ranks prices, never bets."""
    assert ENGINE2 is None or _engine2_unlocked(), (
        "ENGINE2 is set but the unlock conditions module does not exist; "
        "see the module docstring")
    listed = rows(prices_mod.by_matchup() if price_index is None
                  else price_index)
    body = []
    body.append(f'<p class="banner">{_esc(BANNER)}</p>')
    if not listed:
        body.append('<p class="gap">No multi-book board is thick enough to '
                    'measure right now; the list is empty rather than '
                    'padded.</p>')
    else:
        positive = [r for r in listed
                    if (r.get("improvement_points") or 0) > 0]
        body.append(f'<p class="gap">{_esc(ALL_NEGATIVE_NOTE)}</p>'
                    if not positive else
                    f'<p class="gap">{_esc(SOME_POSITIVE_NOTE)}</p>')
        cells = "".join(
            f'<tr class="{"better" if (r.get("improvement_points") or 0) > 0 else "worse"}">'
            f'<td>{_esc(r["away"])} @ {_esc(r["home"])}</td>'
            f'<td>{_esc(r["team"])} ({_esc(r["side"])})</td>'
            f'<td class="mono">{_esc(_signed(r["best_price"]))} '
            f'({_esc(r["best_book"] or "?")})</td>'
            f'<td class="mono">{_prob_pct(r["consensus_probability"])}</td>'
            f'<td class="mono">{_prob_points(r["improvement_points"])}</td>'
            f'<td class="mono">{_return_pct(r["improvement_return_pct"])}</td>'
            f'<td class="mono">{_esc(r["books"] or "?")}</td>'
            f'<td>{"beats consensus" if (r.get("improvement_points") or 0) > 0 else "worse than consensus"}</td>'
            '</tr>'
            for r in listed)
        body.append(
            '<table><tr><th>game</th><th>priced side</th>'
            '<th>best available</th><th>consensus (de-vigged)</th>'
            '<th>improvement (win-prob points)</th>'
            '<th>improvement (return)</th>'
            '<th>books</th><th>vs consensus</th></tr>' + cells + '</table>')
    body.append(f'<p class="label">{_esc(prices_mod.LABEL)}.</p>')
    return ('<section class="ranker"><h2>Price board</h2>'
            + "".join(body) + '</section>')


def _prob_pct(value) -> str:
    """A probability, or "--". A missing value is never rendered as 0.0%."""
    return "--" if value is None else f"{value:.1%}"


# The conversion, and its docstring, live in prices.py: this page and
# dashboard.py used to each keep an independent copy (§2.2 of the SaaS
# audit), which is exactly the kind of drift -- one number, two renderings --
# this project keeps tripping on.
_prob_points = prices_mod.format_probability_points


def _return_pct(value) -> str:
    return "--" if value is None else f"{value:+.2f}%"


def _signed(price):
    if isinstance(price, int) and price > 0:
        return f"+{price}"
    return price


def _engine2_unlocked() -> bool:
    """False until the unlock evidence exists as reviewable modules.

    Deliberately unimplemented: implementing it IS the deliberate act the
    docstring demands, and it starts with evidence, not with code.
    """
    return False
