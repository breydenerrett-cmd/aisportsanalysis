"""Assemble one slate's player-prop board from the stores on disk.

Same division of labour as src/report/card.py: this file reads, and
`src.analysis.propboard` decides. Nothing here chooses what is shown or in
what order -- it loads three stores, hands them over, and shapes the result
for transport.

WHAT IT READS
-------------
- `src.pipeline.batter_props.read_processed()` -- the prop quotes. 17,149
  rows across six markets as of 2026-09-11, captured from the odds feed.
- `src.pipeline.boxscores` -- every batter's game log, which is the only
  input the model gets. Filtered to STRICTLY BEFORE the slate date inside
  `propboard`, never here.
- `src.pipeline.lineup_store` -- tonight's batting order when it has posted,
  because slot is the most valuable input on this board: leadoff is 4.467
  expected plate appearances against 3.461 batting ninth, roughly 29% more
  chances. Absent, the model falls back to the batter's season average and
  says so in `expected_pa_source`.

WHAT IT IS NOT
--------------
Not a pick list. `propboard`'s module docstring carries the measurement that
forbids ranking this by the price gap; this layer preserves that ordering and
adds nothing to it.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from src.analysis import playerprops, propboard
from src.paths import processed_path
from src.pipeline import batter_props, boxscores, lineup_store

BOX_STORE = processed_path("boxscores_2026.jsonl")

# How many contracts a caller gets by default. The board runs to a few
# hundred on a full slate and no reader wants that; a caller that genuinely
# does asks for it.
DEFAULT_LIMIT = 40
MAX_LIMIT = 200


def _batter_rows(path=BOX_STORE) -> list:
    return [row for row in boxscores.read(path) if row.get("type") == "batter"]


def _by_name(rows: Sequence[Mapping]) -> dict:
    """{player_name: [game logs, oldest first]}.

    Keyed by NAME because that is the only identifier the prop feed and the
    box score share -- the feed carries no player id. A name that does not
    match is dropped by `propboard` as "no prior box score", counted, and
    reported; it is never resolved by guessing.
    """
    out: dict = {}
    for row in rows:
        name = row.get("player_name")
        if name:
            out.setdefault(name, []).append(row)
    for lines in out.values():
        lines.sort(key=lambda r: str(r.get("date") or ""))
    return out


def _slots_for(date: str) -> dict:
    """{player_name: batting slot} from tonight's posted lineups, or {}.

    A lineup that has not posted yet is not an error and not a gap worth
    reporting to a reader -- it is simply early. The board still prices,
    using each batter's season average, and says which estimate it used.
    """
    try:
        stored = lineup_store.read() or {}
    except Exception:  # noqa: BLE001 -- a missing lineup must not kill the board
        return {}
    slots: dict = {}
    for _game_pk, entry in (stored or {}).items():
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("date") or "")[:10] != date:
            continue
        for side in ("away", "home"):
            for index, batter in enumerate(entry.get(side) or [], start=1):
                if not isinstance(batter, Mapping):
                    continue
                name = batter.get("name")
                # The store carries an explicit `order`; position in the
                # list is only the fallback. They agree today, and a card
                # that ever arrives out of order would otherwise hand every
                # batter the wrong slot silently -- and slot is the single
                # input this board is most sensitive to.
                try:
                    slot = int(batter.get("order") or index)
                except (TypeError, ValueError):
                    slot = index
                if name and 1 <= slot <= 9:
                    slots[name] = slot
    return slots


def board_for_date(date: str, *, limit: Optional[int] = DEFAULT_LIMIT,
                   prop_rows: Optional[Sequence[Mapping]] = None,
                   batter_rows: Optional[Sequence[Mapping]] = None,
                   slots: Optional[Mapping] = None) -> dict:
    """One slate's priced prop board, most likely first.

    Every store is injectable so a test can exercise this without the real
    disk deciding whether it passes -- the defect `a-test-that-reads-the-disk`
    exists to prevent.
    """
    rows = (list(prop_rows) if prop_rows is not None
            else batter_props.read_processed())
    batters = list(batter_rows) if batter_rows is not None else _batter_rows()
    by_name = _by_name(batters)

    # League rates come from every batter-game BEFORE this slate. Measured,
    # never assumed: offence drifts year to year.
    history = [row for row in batters
               if str(row.get("date") or "")[:10] < date]
    if not history:
        return {"date": date, "contracts": [], "counts": {},
                "reason": "no batter history before this date"}

    league = playerprops.league_rates(history)
    built = propboard.build(
        rows, date=date, batters_by_name=by_name, league=league,
        slots_by_player=(slots if slots is not None else _slots_for(date)))

    likely = propboard.most_likely(built["contracts"])
    capped = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    counts = propboard.summarise(built)

    payload = {
        "date": date,
        "contracts": [_public(c) for c in likely[:capped]],
        "counts": counts,
        "reason": None,
    }
    if not likely:
        payload["reason"] = (
            "no prop prices posted for this slate yet"
            if not built["contracts"]
            else "nothing on this board is more likely than not")
    return payload


def _public(contract: Mapping) -> dict:
    """One contract, shaped for transport and rounded for reading.

    `probability` and `breakeven` are both kept because they answer the two
    different questions a reader has, in that order, and neither is useful
    without the other: a bet can win three nights in four and still be poor
    value, which is most of this board.
    """
    return {
        "player": contract.get("player"),
        "market": contract.get("market"),
        "line": contract.get("line"),
        "side": contract.get("side"),
        "probability": round(float(contract.get("probability") or 0.0), 4),
        # None stays None: a one-sided market (home runs) has no fair price,
        # and rounding its absence to 0.0 would print "the market makes it
        # 0%", which is a number nobody quoted.
        "market_probability": (
            None if contract.get("market_probability") is None
            else round(float(contract["market_probability"]), 4)),
        "market_probability_absent": contract.get("market_probability_absent"),
        "breakeven": round(float(contract.get("breakeven") or 0.0), 4),
        "gap_vs_breakeven": round(
            float(contract.get("gap_vs_breakeven") or 0.0), 4),
        "price": contract.get("price"),
        "book": contract.get("book"),
        "expected_pa": contract.get("expected_pa"),
        "expected_pa_source": contract.get("expected_pa_source"),
        "batting_slot": contract.get("batting_slot"),
    }
