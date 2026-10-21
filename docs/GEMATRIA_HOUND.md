# The Gematria Hound

Owner ruling (Brey, 2026-10-21): build a real, functioning house hound that researches upcoming matchups with numerology,
ranks selections, publishes paper picks through the existing hound system and is graded publicly like every other hound.
Make it functional first, then improve its selection rules. Do not label claims of predictive superiority as established
without evidence, and do not use that uncertainty as a reason not to build it.

## What it is

`gematria` (category `numerology`), a house hound that shares the AI hounds' config (`config/ai_hounds.json`, family
`gematria`), ledger (`ai_hounds_v1.jsonl` beside the app database), sports gate (the whole dog menu) and runner
(`src/hounds/ai_runner.py`). It asks no model and costs nothing. Moneyline only, paper only, forward only.

Copy, everywhere: "Experimental numerology hound. Paper picks, graded in public like every hound." No claim of predictive power.

## How it decides

For a game it builds two worlds, "home wins" and "away wins". A pool of numbers is the same in both worlds (cipher values of
names, the state's order of statehood, numbers of the date, spans from founding or admission dates, game and meeting numbers);
the counts a result would produce exist only in one world (win and loss totals, streaks, days and weeks since the last win or
loss, head-to-head, an NFL coach's record with the club). Every equality between a world's counts and the pool, or between two
of its counts, or a prime-index or triangular link, or a count of 33 or 47, is one typed evidence item with a weight from
`config/gematria/rules_v1.json`. A count that several other numbers equal is flagged as the HEADLINE (the posts lead with one)
and outweighs a loose match. A side's score is the sum of its world's weights; the other side's matches are the posts' warning
bullets. The total number of comparisons tried is logged beside every score.

It picks the higher side only when the margin is at least `min_margin`, both worlds had enough stored results to count
(`min_milestones_per_side`), the two searches were of similar size (`max_search_imbalance`), and the side's average price at the
lock is inside the band (never -200 or worse; the other side is never taken instead). Otherwise it passes and logs why.
Confidence 1..5 comes from the margin, less one when the other side's case is nearly as strong. At most `max_picks_per_day`
(default 3), taken in lock order like every hound's cap, because ranking against games that have not locked would use boards that
do not exist yet.

## No post-lock information

Lock = 60 minutes before the start. The board is `base.lock_board`; history is cut at lock minus six hours
(`history.FINISH_LAG`); the runner refuses a forward bet at or after the start. A pass that only lacks a board yet is not logged,
so a later pass in the same window can decide; every other decision is logged once and never revisited.

## Where the numbers come from

* `config/gematria/team_facts.json`, built by `scripts/build_gematria_facts.py`: ESPN team endpoints and Wikipedia infoboxes,
  a source URL on every fact. A fact that could not be read is absent. The hound never fetches.
* Results: the MLB and NFL stores through the pack Context; the ESPN store for the NBA, NHL, college football and the EPL; nothing
  for other sports (the hound passes `no_history`).
* The MLB sealed window (2026-01-01..2026-08-27) is never read.

## Improving the rules

A rules file is frozen the moment a pick is made under it. A change is a new `rules_vN.json` with a new `hound_version`, and one
line in `config/gematria/active.json`. Every bet row carries `rules_version`, `rules_hash` and the integer `hound_version`
(the lineage page reads it). Past picks are never edited.

## Switches

`GEMATRIA_HOUND=off` removes the hound from every pass; the default in code is on. The API process's loop starts when
`AI_HOUNDS=on` or `GEMATRIA_HOUND=on` is set explicitly, so production toggling is the owner's call.

## The research folder

`research/rabbitszn/`: `METHOD.md` (how the poster builds a pick), `ledger.csv` (every documented pick, with results and
sources), `claims.csv` (every checkable numerology claim and whether the arithmetic holds), `replay.py` (the engine run
point-in-time over the documented games; in-sample diagnostics only).
