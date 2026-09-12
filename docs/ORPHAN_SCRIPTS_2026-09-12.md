# Seven scripts nothing calls — what they are, and what to do with each

Read for the owner. No code-reading required. Every number below was run or
read today (2026-09-12) and its source is named.

`scripts/reachability_audit.py` checks every script against everything that
actually runs it (workflows, shell scripts, CLI commands). Run today: it
found the same **seven** scripts under `scripts/` that nothing calls
(command: `python scripts/reachability_audit.py`, exit code 1). That is not
new — the prior overnight session already found these seven and said it
wasn't its call to close them out cold (`docs/OVERNIGHT_PLAN_2026-09-12.md`,
lines 138–143). This memo is that follow-up.

---

## Bad news first — two data problems, found while checking these scripts

**1. Live lineup capture has a 3-day gap, and nobody would know without checking.**
The store of tonight's-posted-lineups (who's actually batting where) has games
recorded from 2026-08-24 through 2026-09-08 — and then nothing. No lineups
captured for 09-09, 09-10, or 09-11 (checked by reading the store directly).
One of the seven scripts in this memo, `probe_lineup_slot.py`, says in its own
docstring that whether to depend on posted lineups at all "decides whether the
whole lineup dependency is worth taking on for the projection -- which is a
genuine cost, because lineups post two to four hours before first pitch and a
props card cannot freeze until they do" — so whatever is consuming lineups
live has been running without them for three days. This is worth checking
today, independent of anything else in this memo.

**2. The player-prop history store is thin, and it's quietly breaking a
measurement.** The box-score store used to grade batter performance holds
only 12 days of history (2026-08-30 to 2026-09-10, 3,437 batter rows —
counted directly from the file). Several of the checks below need a batter to
have a real track record before they'll say anything about him, and with only
12 days on file, most batters don't have one yet. This is a "we haven't kept
enough history" problem, not a "today's data hasn't loaded yet" problem — see
script #3 below for exactly how it shows up.

---

## The seven scripts

| Script | What it does | Last touched | Anything import it? | Runs today? | Superseded by something else? |
|---|---|---|---|---|---|
| `_propboard.py` | Shared helper that builds "the list of tonight's prop bets" once, so other scripts don't each build their own and quietly disagree | commit `3a0a6d8`, 2026-09-10 | Yes — three other scripts use it (see below) | Yes, silently (no visible output) | No — it's the shared foundation, not a duplicate |
| `backfill_handedness.py` | One-time catch-up job: fills in which hand every pitcher/batter uses, for players already in the history store | commit `05d1586`, 2026-09-10 | No | Yes, exit 0 | No |
| `prereg_market_vs_model.py` | The pre-committed test of "is our model's number better than the bookmaker's number" | commit `3a0a6d8`, 2026-09-10 | No | Yes, but returns too little data today (see below) | No — this is the one authoritative test, not superseded |
| `probe_information_edge.py` | Tests whether the market price moves *after* we learn something (a lineup posts, a pitcher changes), to see if knowing things early is worth anything | commit `02ff35a`, 2026-09-11 | No | Yes, exit 0 | No |
| `probe_line_shopping.py` | Measures how much money is left on the table by not shopping for the best price across books | commit `ea89786`, 2026-09-10 | No | Yes, exit 0 | Partly — the customer-facing "which book has the better odds" feature it studies is the one the owner already ordered removed (see below) |
| `probe_lineup_slot.py` | Tests whether tonight's batting order position predicts a batter's plate appearances better than his own season average | commit `30f8a28`, 2026-09-10 | No | Crashes today (see below) | No — a different, currently-pending document (`docs/PREREG_SLOT_PROP.md`) asks a different question (does the *market* react to a lineup slot, not whether the slot itself predicts plate appearances) |
| `probe_platoon_split.py` | Tests whether left/right-handed matchups (batter vs. pitcher) should go into the model | commit `05d1586`, 2026-09-10 | No | Yes, exit 0 | No — this is the standing test that any future version of this feature must pass |

---

## `_propboard.py` — keep it, declare it

Three other scripts build on this one so they can't quietly disagree about
what "tonight's bets" means: `prereg_market_vs_model.py`,
`probe_line_shopping.py`, and `probe_prop_value.py` (source: `git grep`
across `scripts/`). `probe_prop_value.py` is already on the approved-exception
list in the audit (`scripts/reachability_audit.py`, line 414), with the
reason that it's read by hand, not on a schedule. This file has no visible
output of its own — it just supplies the other three — so the audit will
never see anything call it directly by name. **Recommendation: add it to the
audit's approved-exceptions list with the reason "supplies the three declared
readers; has no output of its own to be called for."** Nothing is lost either
way — it already works and is already used.

## `backfill_handedness.py` — a one-time fix, already done, keep declared

This script exists because almost no pitcher in the history store had a
recorded throwing hand — only 1 of 286 flagged starters did
(`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`, line 134). Running it today:
914 people are in the box-score store (451 batters, 478 pitchers), 1,281 are
already on file from before, and **0 are missing** — so it fetched nothing
and needed to fetch nothing. It costs no odds-purchasing budget; it only
calls the free MLB league API. **It is a fix-once job, not a recurring one —
run it again only after a large batch of new players shows up with no
handedness recorded.** Recommend declaring it in the audit with that reason.

## `prereg_market_vs_model.py` — the correct verdict is UNDETERMINED, and this file is a standing gate, not a closed question

**Correction to an earlier draft of this memo:** this script's answer is
**UNDETERMINED**, not "no finding." The actual recorded result
(`docs/PREREG_MARKET_VS_MODEL.md`, lines 170–180, run 2026-09-10 on 1,107
bets): *"The interval spans zero... Neither [our model] nor [the market] is
supported."* ("No finding, both directions" is the verdict of a *different*
pre-committed test — `docs/PREREG_UNDER_SIDE.md`, read by a different,
already-declared script, `probe_prop_value.py` — and the two got mixed up
because the same commit, `3a0a6d8`, touched `docs/PREREG_UNDER_SIDE.md` and
`scripts/prereg_market_vs_model.py` — the other question's script, not its
document — on the same day. `docs/PREREG_MARKET_VS_MODEL.md` itself was
written two commits earlier, in `ad006cd`.)

More importantly: this script is not a question that's been answered and
closed. It's the **standing scale** the whole project uses to check whether
any new idea (a handedness matchup, park effects, weather, recent form)
actually helps. The document says so directly: *"adding an input is only
progress if it moves this paired difference, and that measurement now exists
and is re-runnable"* (`docs/PREREG_MARKET_VS_MODEL.md`, lines 136 and
253–256; the same statement appears in
`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`, lines 166–168). The handedness-
matchup script below says the same thing about itself in its own closing
line: any feature built from it "must be measured against the pre-registered
bar" here "before it counts as progress."

**Running it today returns too little data to answer anything: only 81
qualifying bets, versus 200 needed (the script itself refuses below 200 and
exits with an error code for that reason — confirmed at
`scripts/prereg_market_vs_model.py`, lines 176–179). Two days ago
(commit `ad006cd`, 2026-09-10) the same script scored 1,107.** Why the
collapse — see the next section; it's the same root cause as the next
script's failure.

**Recommendation: add it to the audit's approved-exceptions list, with the
reason "this is the project's standing bar for judging every future model
change; it is run by hand each time an input is added, not on a fixed
schedule, because running it on a schedule would invite reading a partial
answer before enough bets have accumulated."**

## `probe_lineup_slot.py` and the 81-vs-1,107 collapse — one root cause, not two separate problems

This script crashes today with a small, unrelated code bug (confirmed:
`ValueError: min() iterable argument is empty`, at
`scripts/probe_lineup_slot.py`, line 204, exit code 1) — but the crash is not
the real story. It crashes because it found **zero comparable batters** to
work with in the first place. That "zero," and the collapse from 1,107 to 81
qualifying bets in the script above, are **the same problem showing up in two
places**, not two separate issues:

- The model refuses to price a batter's prop unless he has at least 40
  plate appearances of history on file (`src/analysis/playerprops.py`, line
  103). With only 12 days of box-score history in the store today (see "Bad
  news first," above), most batters simply haven't accumulated 40 plate
  appearances yet — batters below that floor account for **1,308 of the
  2,760 skipped bets** in today's run of `prereg_market_vs_model.py`
  (measured directly by running its own data-collection step: 1,308 below the
  history floor, 1,194 with too few books quoting a price, 151 with no prior
  games at all, 107 with no result recorded yet). A stale
  box-score feed — data not having caught up to today's games — would look
  completely different: it would show up as "no result recorded for this
  game," which today accounts for only 107 of those skips. This is a
  **missing-history problem, not a lagging-feed problem**, and fixing "why
  hasn't the feed caught up" would not fix it.
- The same 12-day store is why `probe_lineup_slot.py` finds nothing: only 61
  of 450 batters on file have even 11 games of history (counted the same way
  as the 3,437 batter rows above, `scripts/_propboard.py`'s own batter
  reader), so its own requirement of 10+ prior games almost never clears. Its
  batter-game count
  also dropped — 2,465 today versus 3,417 two days ago on the identical code
  (commit `30f8a28`, 2026-09-10) — confirming the store, not the script, is
  what changed.

**A number this script's own comment relies on is already going stale, and
that's worth one line rather than silence:** the comment in
`src/analysis/playerprops.py` (lines 122–124) that justifies using tonight's
batting slot at all cites "3,417 batter-games" and "18.6% never move at all."
Run today, the same measurement now reads 2,465 batter-games and 24.5% never
move. That comment already flags itself as a number with an expiry date
("registered in `scripts/calibration_drift_audit.py` -- a threshold
calibrated against a population is a claim with an expiry date," lines
140–142) — it just hasn't been refreshed since the store shrank.

**Recommendation: fix the crash (cheap — it's a one-line guard against an
empty result) as routine cleanup, but the crash is not the priority. The
priority is deciding whether to backfill more box-score history so these
checks (and the live model itself) have enough of a track record on
batters to work at all.** Whether `probe_lineup_slot.py` itself gets a
declared-manual entry or gets deleted can wait until that's decided — it's
answering a real, already-settled question (tonight's slot beats a batter's
own average by 13%, still the number the live model uses) and adds nothing
further once that's on record.

## `probe_platoon_split.py` — the direction is right, the size is not proven

Run today (exit 0): comparing each batter against his own history (the only
version of this test that's trustworthy — see below), left-handed batters
gain **+0.39** points of hit rate against right-handed pitching, and
right-handed batters lose **0.82** points against right-handed pitching. That
is the *correct direction* for a real platoon effect. But every one of those
numbers sits within roughly one margin-of-error of zero (se 0.67 and 0.55) —
so **the direction test passes; the size is not established.** This matches
the project's own written status: `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`
titles this section "ATTEMPTED, NO FEATURE" (line 131), calls it "Blocked on
a data gap" (line 154), and lists "Platoon, second attempt" as still pending
(line 174). Nothing here should be read as "the platoon effect is real" —
only as "the sign came out the way real baseball says it should, which rules
out one kind of error, not all of them."

There's a second reason a simpler, cruder version of this same test (using
only who *started* the game, rather than who was actually pitching each
at-bat) gives the wrong answer entirely: it shows left- **and** right-handed
batters both hitting lefties better, which can't both be true. That happens
because teams bench their worst-matchup left-handed hitters against
left-handed pitching, so the ones who do get in the game are a
better-than-average subset — comparing across different groups of players
gets credited to the matchup by mistake. Comparing each batter only against
himself removes that mistake, which is why that's the only one of the two
versions worth reading.

**Recommendation: declare it in the audit, but for the correct reason.** The
earlier draft of this memo said "declare it because it already gave its
answer" — that's wrong, and contradicts the script's own closing line, which
says a feature from this must still be measured against the standing bar
above before it counts as progress. **The right reason is: this is run by
hand only when an input is about to be added or re-attempted (the project's
own next-step list, `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`, line 174,
already has "platoon, second attempt" queued) — not on a fixed schedule,
because the answer only changes when there's new history to feed it.**

## `probe_line_shopping.py` — the arithmetic works; the underlying feature is the one the owner already ordered removed

Run today (exit 0, 1,227 qualifying bets): the average bookmaker charges
**6.79 points** of built-in margin on a two-sided player-prop bet; taking the
best available price instead of an average price recovers about **16%** of
that (+1.11 points, 95% confidence range +1.05 to +1.18). Player props cost
1.9x what the same arithmetic costs on game-level bets, and are quoted by a
fifth as many books (`docs/PROP_MARKET_ECONOMICS.md`;
`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`, lines 108–113). The script also
checks whether the best price is usually the "informed" one moving ahead of
bad news — on this one week of data that check is inconclusive (not enough
history to call it either way).

This is where the finding runs into a decision the owner has already made.
Quoting the owner exactly, from a prior working session
(`docs/OVERNIGHT_PLAN_2026-09-12.md`, lines 211–213): *"this whole 'we do
price verification and see which book has the better odds, dude,' that has
to stop. None of that's important. Nobody fucking cares."* That instruction
was about the customer-facing feature that shows users which book has the
better price — and as of today that feature is still live and is still the
dominant content of the page it appears on (same document, section 1.1). This
script is the research tool behind that idea, not the feature itself, and it
produces no customer-facing text — but if the feature is coming out, this
script's future is tied to that decision, not to the number it produces.

**Recommendation: hold the declare-or-delete decision on this one until the
owner's price-comparison feature is actually removed from the product** (a
separate, already-ordered task, not something this memo is asking for). Once
that's done, this script becomes a pure research tool with no live consumer,
and can be declared manual with the reason "measures the size of a bookmaker's
margin for research; the customer-facing version of this idea was
deliberately removed."

## `probe_information_edge.py` — the two things being compared aren't comparable yet, so read nothing from the numbers below that line

Run today (exit 0): information events (a lineup posting, a pitcher change,
etc.) happen a median of **2.9 hours** before first pitch; the comparison
group used as a "nothing happened" baseline sits at a median of **6.9 hours**
before first pitch. The script's own check for this catches it and says so
directly: *"-> STILL NOT MATCHED. Read nothing below this line."* That
instruction should be followed — the headline number below it (prices move
more after real news than after nothing) is not trustworthy yet, because the
two groups being compared aren't happening at the same time of day relative
to the game.

The script's own suggested next step is a different, harder question it
hasn't attempted: not just *whether* the price moves after news, but *which
way* it moves — only the second is something a bettor could actually use
(`docs/INFORMATION_EDGE_FIRST_LOOK.md`, lines 79–90).

**Recommendation: declare it manual, with the reason "reads a moving research
question with no fixed criterion yet; the comparison groups don't line up
today and the script says so — rerun by hand as more history accumulates,
and don't schedule it until the direction-of-movement test above exists."**

---

## What this memo found that nobody asked it to look for

- The 3-day gap in captured lineups (2026-09-09 through 09-11) — see "Bad
  news first."
- A number embedded in `src/analysis/playerprops.py`'s comments (the "how
  much do batters move" table) is quietly out of date against the current,
  smaller history store. Not urgent, but it's a "measured constant" the
  project's own convention says should be checked periodically, and this is
  that check.

---

## Questions only the owner can answer

1. **The lineup capture gap (09-09 to 09-11):** is anything currently reading
   or publishing live picks that depends on posted lineups? If so, is it
   silently running without them right now?
2. **History backfill:** is it worth spending budget to pull more than 12
   days of past box scores, so batters build up the 40-plate-appearance
   history the model requires? Without that, several of these checks (and
   possibly the live model) will keep returning too little to say anything.
3. **The price-comparison feature:** you already said to remove the
   "which book has the better odds" feature from the product
   (`docs/OVERNIGHT_PLAN_2026-09-12.md`) — it's still live as of today. Is
   that still the plan, and is it scheduled?
4. **Platoon matchups:** given the direction is right but the size isn't
   proven yet, do you want to wait for more history before trying this
   again, or is there a faster way to get more plate-appearance-level data?

*This memo makes no claim about edge, value, or expected profit anywhere
above, proposes no changes to the card's ranking or pick count, and does not
reopen cross-book price comparison as a customer-facing idea — all standing
rules.*
