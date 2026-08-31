# Probe design — forward pitcher-strikeout prop LISTING audit

**DESIGN ONLY. Nothing here has been run. No API call was made to write it, no
code was changed, no credit was spent.** This is step 2 of the C1 prerequisite
list in `docs/RESEARCH_V6_CANDIDATES.md` ("a forward prop-listing audit"), and
it is written so Brey can approve or refuse a bounded spend with the numbers in
front of him.

**Written 2026-08-31**, from `docs/RESEARCH_V6_CANDIDATES.md` (C1),
`docs/COLLECTION_POLICY.md`, `src/providers/odds.py`, `src/pipeline/dense.py`
(`_f5_close_pass`), `src/pipeline/rosterwatch.py`.

## The one question

**When do the books that carry pitcher-strikeout props actually LIST them,
relative to the lineup post?**

Not "what is the line", not "is the line good". Listing time, book count, and
whether the listing changes after the lineup exists. C1's slot-2 argument is
that the line is made before its key input exists; that claim is either true in
the timestamps or it is not, and no price is needed to read it.

Three sub-questions, in the order the evidence would arrive:

1. **Coverage.** How many books list `pitcher_strikeouts` per game, and on what
   fraction of games? All that is known today is `COLLECTION_POLICY`'s
   "3–4 books, listing-dependent" from the 24-credit probe.
2. **Listing time.** Is the market listed before the lineup bracket opens?
   Bounded between two of our own polls, rosterwatch's grade-B convention.
3. **Repricing (C1's Falsifier 1).** Does the book's `last_update` for that
   market move after the lineup posts? If it moves on most games, the
   information IS consumed and C1's slot 2 is empty. **This is the falsifier
   the probe exists to fire, and it can fire without a registration.**

---

## 1. Endpoint, market key, and exact credit cost

### What is knowable offline

| Fact | Source | Confidence |
|---|---|---|
| Per-event odds is the only endpoint serving non-featured markets; billed **markets × regions PER EVENT** | `src/providers/odds.py` L54–72, measured live (2 markets = 2 credits) | measured |
| `/events` index is **free** | `odds.list_events` docstring; used every dense close pass | measured |
| "The per-event **markets** endpoint is a **1-credit coverage scanner**" | `docs/COLLECTION_POLICY.md` L21, from the 24-credit probe | measured, but not by us in code |
| Pitcher strikeouts: **3–4 books, listing-dependent**; prop history from ~May 2023 | `docs/COLLECTION_POLICY.md` L19–20 | measured once, no detail retained |
| Every response carries `x-requests-last` / `-remaining` / `-used` | `odds._get_json_with_usage` | measured |

### What is NOT knowable offline — stated plainly

`src/providers/odds.py` has **no props support at all**: `SUPPORTED_MARKETS` is
the three featured markets plus the three first-five keys, and
`_validate_markets` **rejects** anything else — `tests/test_providers_odds.py`
L96 and L215 pin that rejection using the literal string `player_props`. So the
repo contains **no measured cost for a player-prop fetch and no confirmed market
key**. The market key this probe assumes is `pitcher_strikeouts`; that is an
assumption from the API's documented MLB prop keys, not a repo fact.

Two candidate endpoints, and they cost the same:

- **`/v4/sports/baseball_mlb/events/{id}/markets`** — returns which market keys
  each bookmaker lists for that event, no prices. `COLLECTION_POLICY` prices it
  at 1 credit. Answers coverage + listing, but carries **no `last_update`**, so
  it cannot answer sub-question 3.
- **`/v4/sports/baseball_mlb/events/{id}/odds?markets=pitcher_strikeouts`** —
  1 market × 1 region = **1 credit expected**, and returns `last_update` per
  book per market, which is exactly the repricing evidence. Same price, strictly
  more information.

**Design choice: use the per-event ODDS endpoint with the single market
`pitcher_strikeouts`.** Same expected credit, and it is the only one of the two
that can fire Falsifier 1.

### The single cheapest verification call (do this FIRST, before anything else)

One call, on one event, on one game-day:

```
GET /v4/sports/baseball_mlb/events/{id}/odds
    ?markets=pitcher_strikeouts&regions=us&oddsFormat=american
```

made through `_get_json_with_usage` and reading **`x-requests-last`**, which is
the API's own statement of what that request billed. That single response
settles all four unknowns at once: (a) whether the market key is valid (422 if
not), (b) the exact billed cost, (c) which books list it, (d) whether
`last_update` is present per book.

**Cost of verification: 1 credit** (0 if it 422s — a rejected request bills
nothing, per the `MarketsUnavailableAtDate` docstring, though that is documented
for the historical 422 and should not be assumed for a live one).

**Gate:** if `x-requests-last` comes back > 1, the whole budget below multiplies
by that factor and the probe **stops and re-reports** rather than proceeding at
an unapproved rate. This is the only pre-approved call in this document.

---

## 2. Sampling plan

### Shape

Rides the existing hourly scheduler (the same trigger dense uses), as a separate
low-priority pass that runs **after** baseline/close capture and yields to it.
Free `list_events` gives ids; one 1-credit fetch per sampled event per slot.

**Sample: 3 games per game-day.** Chosen deterministically from the slate — sort
the day's events by `commence_time`, take the earliest, the median, and the
latest first pitch. Deterministic selection is not a nicety: a hand-picked
sample of "games likely to have props" would manufacture the coverage number the
probe exists to measure.

**Poll slots: 6 per game, anchored to first pitch**, executed at the first
scheduled run at or after each offset:

| Slot | Offset | What it is for |
|---|---|---|
| S1 | T−12h | Is it listed the night before / early morning? Bounds the early edge. |
| S2 | T−8h | |
| S3 | T−6h | Straddles the typical lineup post (MLB lineups land ~3–5h out). |
| S4 | T−4h | |
| S5 | T−2h | Post-lineup on essentially every game. |
| S6 | T−30m | Close. Did `last_update` move after the lineup? |

**6 slots × 3 games = 18 credits/game-day.** Inside the ≤20/day target.

Absence must be recorded, or the audit proves nothing: a slot that fetched
successfully and found no `pitcher_strikeouts` from any book writes a **marker
row**. This is rosterwatch's rule, and rosterwatch's docstring explains exactly
why — without markers, "we looked and it was not there" is indistinguishable
from "we never looked", and every bracket widens into uselessness. A slot that
**failed** writes an error row and no marker; the bracket then widens honestly.

### Left-censoring, and the one permitted adaptation

If the market is already listed at S1, the listing time is only bounded as
"before T−12h" — left-censored. That still answers C1 directionally (listed well
before any lineup exists), but it does not bound the posting time. **If ≥50% of
listed games are left-censored at S1 after the first 5 game-days, shift the
slot grid one step earlier (S1 → T−20h, S2 → T−14h, rest unchanged).** Same 6
slots, same 18 credits/day, no new spend. Any such shift is recorded in the
store as a `schedule_version` field on every row so the two regimes are never
silently pooled.

---

## 3. What gets recorded

Append-only JSONL at **`data/processed/prop_listing.jsonl`**, written with the
`_ends_ragged` guard `_f5_close_pass` uses (a run killed mid-write must not weld
the next row onto a fragment). Never rewritten, never cleaned, never
de-duplicated in place.

**No prices.** Listing alone answers the question, and the point/price fields
are deliberately excluded from the default row so this probe cannot quietly
become a prop-price collection under a research label. `point` is the one
borderline field — it arrives at zero extra credit and would sharpen Falsifier
1 — so it is listed below as OPTIONAL, **off unless Brey turns it on**.

Listing row — one per book per pitcher per slot:

```json
{"observed_utc":"2026-09-02T18:00:11Z","schedule_version":1,"slot":"T-6h",
 "event_id":"a1b2...","commence_time":"2026-09-03T00:05:00Z",
 "home_team":"...","away_team":"...","market":"pitcher_strikeouts",
 "book":"draftkings","listed":true,"book_last_update":"2026-09-02T17:41:03Z",
 "player":"Pitcher Name","credits_last":1}
```

Marker row — one per event per slot that fetched successfully:

```json
{"observed_utc":"2026-09-02T12:00:07Z","schedule_version":1,"slot":"T-12h",
 "event_id":"a1b2...","commence_time":"2026-09-03T00:05:00Z",
 "poll":true,"books_listing":0,"credits_last":1}
```

Error row — a fetch that failed; never fatal, never silently dropped:

```json
{"observed_utc":"...","slot":"T-4h","event_id":"...","error":"odds API returned HTTP 500"}
```

`credits_last` on every row is `x-requests-last` from that response, so the
store audits its own spend rather than trusting this document's arithmetic.

**Join to lineups:** none is written into this store. The comparison is made at
read time against `rosterwatch.events()` `lineup_posted` brackets, matched
event→`game_pk` by date and team names. Keeping the join out of the capture
path means a bad join can be redone; a bad capture cannot.

**Derived answer, computed at read time only:**
per game, `first_slot_listed` (or `left_censored`), the `lineup_posted` bracket
[last poll without, first poll with], the sign of their comparison, and whether
any book's `book_last_update` advanced after the bracket's closing end.

---

## 4. How long before it can answer

Adopt V3's floor rather than inventing one: **30 admissible games** — a game is
admissible when it has both a resolvable listing state and a grade-B
`lineup_posted` bracket from rosterwatch.

At 3 games/day, with the coverage rate unknown (this is what we are measuring):

| Fraction of sampled games yielding an admissible bracket | Game-days to 30 | Credits |
|---|---|---|
| 100% | 10 | 180 |
| ~60% (planning assumption) | 17 | ~306 |
| ~40% | 25 | 450 → hits the cap below |

**Plan on ~3 weeks of game-days, ~18 credits/day, ~340 credits total.**
**Hard cap: 400 credits cumulative**, then stop and report whatever the store
holds, including "underpowered, N = 21". A missed window is gone and a thin
result is a result; neither is a reason to extend the spend silently.

Note what a small N buys here. This is a **descriptive timing audit**, not a
hypothesis test — it needs enough games to say "listed before the lineup on
most games" or "repriced after the lineup on most games", not enough to survive
a BH-FDR battery. Nothing from this store enters a registration; it decides
whether a registration is worth writing.

---

## 5. Abort criteria

Stated before the first credit is spent, in the order they would fire.

- **A0 — cost verification.** `x-requests-last` > 1 on the verification call:
  stop, report the true rate, do not start the grid. (Spend: 1 credit.)
- **A1 — no coverage.** After **5 game-days** (≤90 credits), if fewer than half
  of sampled games ever show ≥1 book listing `pitcher_strikeouts` at any slot:
  stop. C1 dies on coverage without a registration, which is the cheapest
  possible death and a good outcome.
- **A2 — Falsifier 1 fires.** If, on ≥80% of admissible games, at least one
  book's `book_last_update` for the market advances after the `lineup_posted`
  bracket closes: stop early. The information IS consumed, C1's slot 2 is
  empty, and further spending buys precision on a dead candidate.
- **A3 — instrument failure.** >30% of scheduled slots missing or erroring over
  any 7-day window: stop and report the miss rate. Listing times cannot be
  bounded by polls that did not happen, and inferring them would be fabrication.
- **A4 — budget.** Cumulative 400 credits: stop.
- **A5 — envelope and floor.** This pass is the LOWEST priority layer in
  `COLLECTION_POLICY`'s order of protection. If a day's projected total would
  exceed ~132, this pass is skipped first, before any market is dropped from
  baseline or the grid thins. Balance below 5,200 (floor 5,000 + one day's
  probe): skip. `"skipped: credit floor"` stops everything and reports — never
  worked around.
- **A6 — V3 preempts.** If V3's `lineup_posted` class reaches its floor and
  reports books reacting inside the capture-spacing floor, C1's best argument is
  already damaged; pause this probe and re-decide rather than finish out of
  momentum.

---

## 6. Authorization

**Arithmetic: fits.** 18 credits/game-day against an approved ~132/day envelope,
with `COLLECTION_POLICY` recording that actual spend "has run far below the
envelope". ~340 credits total against a 53,083 balance and a 5,000 floor.

**Policy: does NOT fit without a word from Brey.** `COLLECTION_POLICY` L43–45
is explicit that props "are NOT collected yet: they are options, priced and
documented here, **to be switched on when a registered hypothesis needs them**".
C1 is not registered — by design, since this probe is a prerequisite for
deciding whether to register it. So this is not new *money* outside the
envelope, it is a **new collection layer the policy currently forbids**, and it
needs a one-line policy amendment plus Brey's go, not a silent start.

Recommended amendment text, if approved:

> **PROP LISTING PROBE (bounded, time-limited):** `pitcher_strikeouts` listing
> state only, 3 games/day × 6 slots = 18 credits/day, hard cap 400 credits,
> abort criteria in `docs/PROBE_PROP_LISTING.md`. No prices stored. Lowest
> priority layer; skipped first when a day approaches the envelope. Expires at
> the cap or at any abort trigger, whichever comes first.

Nothing in this document authorizes a **historical** prop pull. That remains a
HARD APPROVAL GATE (`RESEARCH_V6_CANDIDATES.md` C1 §3), untouched here.

## 7. What this probe still cannot tell you

Stated so no one reads more out of the result than it holds.

- **Limits.** C1's Falsifier 4. Not observable from this API at any price. A
  clean listing-time result is a measurement, never a tradeable edge.
- **Whether the prop close is soft.** Nothing here measures prop accuracy. The
  asymmetry C1 leans on — every prior death was against the h2h close, and the
  prop close has never been measured — is untouched by this probe.
- **Whether the book's `last_update` means what we want.** It is the API's
  statement of when it last saw a change from that book, not the book's own
  posting clock. A book that re-serves an unchanged line may or may not advance
  it. **This is the biggest interpretive risk in the design**, and the reason
  A2's threshold is 80% rather than a hair-trigger.
