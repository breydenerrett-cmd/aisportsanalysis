"""The Ranker shell: the page that refuses to rank until an edge is earned.

THE TWO ENGINES
---------------
Engine 1 is price improvement -- the best number on the board versus the
de-vigged consensus (src/analysis/prices.py). It is honest today and it is
ALL this page shows.

Engine 2 is predicted value. It requires a demonstrated edge, and none
exists: twenty-four pre-registered hypotheses across three research
families, zero survivors. ENGINE2 below is therefore None, and the page
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

from src.analysis import prices as prices_mod

# The predictive engine. None means: no demonstrated edge exists. See the
# module docstring for what changing this requires.
ENGINE2 = None

BANNER = (
    "No predictive edge exists. Twenty-four pre-registered hypotheses across "
    "three research families have been tested; none survived. Everything "
    "below is PRICE IMPROVEMENT -- where the best available price beats the "
    "market's own consensus. That is a better execution price on a wager "
    "that this page is NOT telling you to place. Nothing here is a "
    "recommendation.")


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
        cells = "".join(
            '<tr>'
            f'<td>{_esc(r["away"])} @ {_esc(r["home"])}</td>'
            f'<td>{_esc(r["team"])} ({_esc(r["side"])})</td>'
            f'<td class="mono">{_esc(_signed(r["best_price"]))} '
            f'({_esc(r["best_book"] or "?")})</td>'
            f'<td class="mono">{(r["consensus_probability"] or 0):.1%}</td>'
            f'<td class="mono">{(r["improvement_points"] or 0):+.4f}</td>'
            f'<td class="mono">{(r["improvement_return_pct"] or 0):+.2f}%</td>'
            f'<td class="mono">{_esc(r["books"] or "?")}</td>'
            '</tr>'
            for r in listed)
        body.append(
            '<table><tr><th>game</th><th>priced side</th>'
            '<th>best available</th><th>consensus</th>'
            '<th>improvement (prob pts)</th><th>improvement (return)</th>'
            '<th>books</th></tr>' + cells + '</table>')
    body.append(f'<p class="label">{_esc(prices_mod.LABEL)}.</p>')
    return ('<section class="ranker"><h2>Price board</h2>'
            + "".join(body) + '</section>')


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
