# Bankroll lock, Hockey Nerd empty preview, quiz insight — plan, 2026-11-05

Owner rulings (Brey, 2026-11-05):
- Starting bankroll is **$2,500 for every hound, not editable**. ROI in units and % is what matters.
  Members change only the per-hound **stake (bet size), unit size and bets per day**.
- While building a hound, every answer shows **what that choice would have done over the last 1, 3 and 7 days**.
- Every quiz question has **"Help me choose"** (a sensible labelled default) and **Skip**.
- Before a hound is kept, the builder **analyses its choices** and says plainly what it will do and where it will
  be dumb (sport/personality mismatch, a rule that never fires, too few books, a sport we do not post the market for).
- The "Hockey Nerd" build (NHL moneylines +100..+250, 5+ books) said "passes today. Nothing on the board fits its
  rule" on a night the board held 16 NHL games. HOCKEYCHIEF's /right-now at 21:31Z also returned candidates [],
  closest [], games_considered 16. That is a defect until shown otherwise.

## Phase 1 — Bankroll ($2,500, locked)
Files: `src/hounds/unit_size.py`, `src/hounds/bankroll.py`, `src/hounds/kennels.py`, `api/` unit-size routes,
`web/js/unitsize.js`, kennel cards (`web/js/kennel.js`), account page, `tests/test_unit_size.py`.
- Today: viewer sizing, fixed mode = 100 units × unit_usd, so a $250 unit shows a $25,000 start on every hound.
  Brey saw $33,532 and $23,953 and read it as a glitch.
- Change: start is a constant 2500 (`START_USD`). Remove the start/unit-size choice from the account UI and the
  write route (keep the table; ignore stored values on read, log once). Unit = start / 100 = $25 flat.
  Per-hound stake_units, bets/day stay where they are (Rules tab). Kennel card: Record, **Units**, **Return %**,
  Bankroll ($2,500 → current). Return % = units / 100.
- Copy: "Every hound starts with the same $2,500 paper bankroll. 1 unit = $25." Update `bankroll_rules` on /hounds.
- Tests: card and /hounds payload pin 2500/25; a stored viewer sizing no longer changes any number; mobile
  overflow test on the kennel card.

## Phase 2 — Hockey Nerd empty preview (defect)
Files: `src/hounds/user_engine_v2.py` (preview, build_slate), `api/hounds_create.py` builder_preview,
`api/hounds_interact.py` right-now, `src/hounds/quiz/compose.py`.
- Reproduce with a fixture: an NHL slate of 16 games, both sides priced, 8–11 books, several dogs between +100
  and +250, now = 90 min before the earliest lock. Spec: NHL moneyline either side, price 100..250, min_books 5,
  lock 120, max 3/day. Expect picks > 0 and `closest` non-empty when 0.
- Suspects, in order: (a) the newest-board read for an unlocked game drops games whose latest capture is older than
  a freshness cap; (b) the quiz's "generic" fit for Stats Nerd on NHL raises min_books above what NHL carries or
  adds a `when` that cannot evaluate (fit.fit_rule with `set_fields`); (c) the slate's sport key ("nhl" vs
  "icehockey_nhl" vs "NHL") mismatches the rule's sports list; (d) `closest: []` — near-miss computation skipped.
- Evidence to read first: `/hounds/u-591ac5e2a8/right-now` at 21:31Z (candidates [], closest [], next_look
  Carolina@NYI locks_in 0, starts_in 158); DRAKEO recorded NHL bets 11-04 with 11 books; the builder screenshot
  copy (compose.py:294 warning fired, so the generic fit ran).
- Done when the fixture fails on current code, passes after the fix, and `skipped` carries a plain reason for every
  game left out of a preview.

## Phase 3 — Quiz impact meter (1 / 3 / 7 days)
Files: `web/js/hounds-quiz.js` (or the quiz module), `api/hounds_create.py` (backtest endpoint), new
`web/js/quiz-impact.js`, `src/hounds/quiz/compose.py`.
- After each answer, compose the spec-so-far and call the backtest endpoint for 1, 3 and 7 days (debounced 600 ms,
  cancel stale). Show one line per window: "Last 7 days: 14 bets, 8-6, +2.1u". With zero bets: "would not have bet".
- The impact of THIS answer: show the delta vs the spec before the answer ("this choice: +3 bets, +0.8u over 7 days").
- Cache per spec hash; rate limit shared with preview. Mobile first.

## Phase 4 — Help me choose + Skip
- Every question gets "Help me choose" (picks the default the house pack would pick for the sports already chosen,
  labelled "chosen for you") and "Skip" (leaves the field at its default, labelled). The reveal lists which answers
  were chosen for the member.

## Phase 5 — Pre-build check ("will this hound be dumb?")
Files: new `src/hounds/quiz/insight.py`, reveal page.
- Deterministic checks, each a sentence + a fix button: personality that reads data the sport does not have
  (Stats Nerd on NHL); market not posted for a sport; a rule that fired 0 times in 7 days of boards; min_books
  above the sport's typical count; price band that excludes every side of the sport (e.g. +100..+250 totals);
  catchphrase blanked by a reserved word (say which word, offer to edit); cap lower than the slate ever offers.
- Shown before Keep as "What this hound will do" + "Watch out" lists. Keep stays enabled; nothing blocks.

## Workers
Sonnet builders, own worktree each, one phase per builder; Haiku runs the changed-file test gate; Fable reviews and
does the live check after the hourly deploy. Commit this file before spawning (worktrees read the object store).
