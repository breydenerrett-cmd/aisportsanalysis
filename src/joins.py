"""A shared, loud check for one join shape: two id-keyed collections that
are supposed to line up on a shared key, joined by looking a left-side id up
in a right-side mapping.

WHY THIS EXISTS (Stage 18 join-integrity audit, 2026-09-16)
-------------------------------------------------------------
The NFL outage (fixed at commit 9a45be1a) was a join that silently dropped
every row: `prices.boards_by_matchup` resolved team names through an
MLB-only abbreviation table for every sport, both sides came back `None`,
an `if not away or not home: continue` guard dropped every row, and the
function returned an empty dict on every NFL date -- no error, just an
empty result a downstream card reported as "no game cleared the bar". A
copy sweep after that fix asked whether the MLB card's own `_game_identity`
vs `gamepayload.game_id()` join had the same shape (see `src/report/card.py`
-- it did not, on real data, but the two constructions used to duplicate
each other rather than share one function, which was itself the risk).

THE DISTINCTION THIS FUNCTION EXISTS TO DRAW
---------------------------------------------
An empty join is not always a bug. If either side legitimately has nothing
in it (no games on the slate, no moneyline rows captured yet), a zero-match
join is the HONEST answer and must stay quiet -- that is the normal state
for most of a slow morning. It is only alarming when BOTH sides are
non-empty and the join still produced nothing: that shape means the two
key constructions have drifted apart, not that the world is quiet.

This function is intentionally tiny and stdlib-only: it does not perform a
join, it only grades the shape of the result the caller already computed
(`matched`, `left`, `right`), so it can sit beside any join without dictating
how that join is built.
"""

from __future__ import annotations

from typing import Sized


def report_join_result(*, name: str, left: Sized, right: Sized,
                       matched: Sized) -> bool:
    """Grade one join's outcome; print an `ESCALATE:` line iff it is alarming.

    `left` / `right` are the two collections that fed the join (anything
    `len()` works on -- a list, dict, or set of keys). `matched` is what the
    join actually produced (again, anything `len()` works on: matched rows,
    matched keys, whatever the caller's join shape returns).

    Returns True iff the join is honest (nothing to escalate) -- either a
    real match, or an empty result explained by an empty input. Returns
    False (having already printed the `ESCALATE:` line) iff both inputs
    were non-empty and the join produced nothing: a code failure wearing an
    honest null's clothes.

    Deliberately prints rather than raises: `scripts/escalations.py` scrapes
    stdout/log lines starting literally `ESCALATE: ` for the existing
    escalations channel, and a raised exception from inside a join would
    take down whichever nightly job called this, which is a worse outcome
    than a silently-wrong card for one bug the escalations channel already
    exists to catch.
    """
    if len(left) == 0 or len(right) == 0:
        return True  # an honest empty: nothing on one side to join at all
    if len(matched) > 0:
        return True  # a real join happened
    print(f"ESCALATE: join '{name}' produced zero matches from "
          f"{len(left)} left rows x {len(right)} right rows -- both sides "
          f"were non-empty, so this is a key-construction mismatch, not an "
          f"honest empty slate.")
    return False
