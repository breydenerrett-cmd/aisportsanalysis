"""The Hounds learning loop: champion / challenger, never overwrite.

Pre-registered in ``docs/PREREG_LEARNING_LOOP.md`` (committed before this package existed). The short
version: a coach (a frontier model) may PROPOSE a challenger; the challenger runs in SHADOW on the
same games at the same prices as its champion; and only a pre-set sequential test on the paired
closing-line-value difference, controlled for false discoveries across all challengers, can PROMOTE
it. A model can never promote. The loop is also built to prove whether it is improving at all, and
to switch itself off when it cannot.

Module map (who owns what):

  rules        every number, quoted from the prereg
  sequential   the statistics: clustered paired mean, Student's t, look boundaries, Benjamini-Hochberg
  ledger       Scope (where a scope's three ledgers live), the hash-chained event log, the state fold
  tunables     the knobs a pack hound declares in config/house_pack.json: validate, render, patch
  proposals    the guards a proposal passes, and the proposal that creates a challenger
  shadow       run live challengers on the same boards as their champions (pack and user engines)
  pairing      the paired slots of a challenger and its champion, with their closing-line values
  referee      looks, boundaries, the monthly BH batch, promotion and retirement, lessons
  lessons      the append-only lessons ledger and what a coach is shown from it
  scorecard    the daily system scorecard and the auto-pause
  views        JSON payloads for the routes and pages
  director     the monthly director-review request file
  cli          python -m src.hounds.learning ...

Nothing here places, sizes or suggests a real bet. Paper only. The -200 cap is enforced by the
engines the shadow runner reuses; no setting in this package can move it.
"""

from __future__ import annotations

PREREG = "docs/PREREG_LEARNING_LOOP.md"
