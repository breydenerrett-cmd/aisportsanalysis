"""Jarvis: the owner's pre-game briefing (paper only, built on LINEHOUND's own stores, no outside research).

WHAT IT IS (owner, 2026-10-25, docs/TODO_UNTIL_SUNDAY.md item 4)
----------------------------------------------------------------
Once a day, for the owner (Brey) and the member Jacob: three to five ranked singles and at most two two-leg
parlays, each with the real captured prices, a maximum acceptable price, the probability against break-even,
the reasons, how it could lose and what to avoid, plus the edges that vanished when lines moved. It reads only
what we already store: the multi-book odds boards, the prop boards, the lineups / probables / umpires /
transactions watch files, the weather forecast file and the existing models' stored outputs. A field with no
stored data says "no data"; nothing is looked up, guessed or invented.

THE FOUR RULES THAT SHAPE EVERY LINE OF IT
------------------------------------------
1. NEVER -200 OR WORSE. No pick, no parlay leg, no max acceptable price is ever -200 or worse (owner rulings
   2026-09-20 and 2026-09-22). The ban looks at both the best and the average price.
2. ONE SIDE PER GAME. Singles reuse ``src.hounds.one_side`` (the rule the hounds already live by); a parlay
   never takes two legs from one game, so it can never hold both sides.
3. PREGAME KNOWLEDGE IS FROZEN. A briefing carries an ``as_of`` instant and every reader stops at it: a row
   observed after it, a lineup posted after it, a game already started at it, is not read.
4. PAPER ONLY, NO PROFIT CLAIMS. Every number is an estimate and says so. Anything from a source we have not
   shown to be calibrated is labelled EXPERIMENTAL, which today is every source (``brief.CALIBRATED_SOURCES``).

FILING. Every pick published is filed through ``src.hounds.apprentice.store.add_recommendation`` (source
"jarvis") with the time it was published, so the Apprentice evidence grades can tell a pick that came first
from one found afterwards.

MODULES: ``board`` (as-of boards, no-vig consensus, open versus current), ``context`` (what the watch files and
stored models say about a game), ``brief`` (select, parlay, explain, file, render), CLI ``python -m src.cli
jarvis brief --date YYYY-MM-DD [--as-of ISO]``, API ``api/jarvis.py`` (admin token).
"""
