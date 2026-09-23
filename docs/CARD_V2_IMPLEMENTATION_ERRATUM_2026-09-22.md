# DAILY_CARD_BEST_BETS_V2 — implementation erratum, 2026-09-22

**Status: record only. No rule changed, no threshold moved, no published row
replaced, no deployment.** The registration text is not edited by this
document.

## Why this is a separate file and not a row in section 16

Section 16 lists what may be appended to it: a typo that changes no number or
rule; a recorded owner answer with its date; the frozen parameter file's
sha256; the `code_fingerprint` and `v1_code_fingerprint` at the registration
commit; the cutover date; a recorded model restart under 11.2; a recorded
change to the `v1_code_fingerprint` under 11.6; links to the published harm
check and read. Then: **"Anything else is a new rule id."**

An implementation erratum is not on that list. Appending one would itself
breach the restriction it is trying to honour. So the findings live here, the
registration is left as written, and the corrected enumeration — if it is
ever promoted to a published card — takes a **new rule id**, which is what
section 16's own sentence requires.

Everything below was verified at branch
`claude/sports-betting-analysis-review-g1o0co`, HEAD `b525c54e`, with
`git diff` against the registration commit `859176ba` empty for every file
named. Each item says whether it is SOURCE-CODE VERIFIED (read in the code)
or OBSERVED (measured on stored output).

---

## E1 — The moneyline candidate set is one side per game, not both

**SOURCE-CODE VERIFIED.**

Section 2 registers the moneyline row as "Both sides of every game".

`src/report/card_v2.py:191` delegates to
`src/analysis/daily_card.py:build_pick_candidates`, which calls
`_consensus_side` (`daily_card.py:445-456`):

```python
return ("away", pa) if pa > ph else ("home", ph)
```

and appends exactly one candidate for that side. Because a de-vigged board's
two sides sum to one, `max(p_away, p_home) >= 0.50` always. G5's PLUS_MONEY
branch (`best_bets_card.py:376-381`) requires `market_probability < 0.50`.
The two conditions are disjoint, and `G5_MARKET` is not fill-eligible
(`best_bets_card.py:316`), so **the registered PLUS_MONEY class cannot fire
on a game moneyline through this path at any price**.

A near-pick'em favourite can carry a positive American quote, but that is a
different fact from a market underdog, and it does not reach the class
either: G5 refuses it on the market number, and G13 (`best_bets_card.py:409-413`)
refuses it whenever the consensus exceeds the price's break-even.

**OBSERVED.** Across `evidence/cards_v2*.jsonl`: 332 moneyline entries, every
price negative (−105 to −149), minimum `market_probability` 0.5003. Seven
PLUS_MONEY candidates have ever been recorded; all seven are props, all seven
died on G7_VALUE, none was published. Shadow arm A — which disables G6, G7,
G8 and G14 — published zero from 101 PLUS_MONEY candidates, which places the
cause upstream of the gates, in enumeration.

## E2 — Run line and player props also depart from section 2, and are NOT fixed

**SOURCE-CODE VERIFIED. Both remain open.**

* **Run line.** Section 2 registers "Both sides at exactly +1.5 and −1.5".
  The implementation attaches the favoured side's run line as a display
  alternative only (`daily_card.py:571-572`, `_attach_run_line`'s own
  docstring: "as an ALTERNATIVE, never as the pick"), and `card_v2.py:228`
  stamps `"line": None`. No run line is a candidate on either side.
* **Player props.** Section 2 registers "Both sides of every `batter_hits`
  and `batter_total_bases` contract". `src/report/props.py:148` keeps only
  `propboard.most_likely`'s side (`propboard.py:96,388`, `LIKELY_FLOOR =
  0.50`), so the contract's other side never reaches V2's gates.

Nothing in the 2026-09-22 correction touches either. A report that says "V2
candidate coverage is complete" after this work is wrong.

## E3 — `code_fingerprint` depends on the checkout, not only on the content

**SOURCE-CODE VERIFIED and OBSERVED.**

`card_ledger.code_fingerprint` hashes each file's raw bytes
(`read_bytes()`). Line endings are part of those bytes. Section 16's recorded
V2 value

```
8a641de0ee76091972d482cc316b47924a474e063334d67056333513ee4d2061
```

reproduces exactly when all seven fingerprinted files are CRLF. This
repository's Windows checkout today holds three of them
(`best_bets_card.py`, `card_v2.py`, `card_v2_frozen_params.json`) as LF with
**byte-identical committed content** — `git diff 859176ba HEAD` over the
fingerprinted paths is empty — and computes
`0a5d8ad7c671c04fadabf904280a9a21ec0b454eb3b59c779d8bea60d158988a` instead.

Consequences, stated plainly:

1. The same code publishes rows stamped with different `code_fingerprint`
   values depending on whether the run happened on Windows or on Linux CI.
2. Registration 11.2's guard — "a change to any fingerprinted file restarts
   the counted sample" — can therefore fire on a checkout difference that
   changed no code. **A false alarm, not a blind spot.** An earlier draft of
   this erratum also claimed a real source change could be masked by an
   offsetting line-ending change; that claim is withdrawn as unsupported.
   sha256 gives no mechanism for one byte difference to cancel another, and
   no such case was constructed or observed. The failure mode is one-way:
   the guard cries wolf, it does not sleep.
3. Any count of "rows carrying the registered fingerprint" is a count of
   rows published from one particular checkout, not of rows built from the
   registered code.

The fix is to normalise line endings before hashing (or to hash git blob ids).
That is a change to a fingerprinted file, so it restarts the sample and is
the owner's call, not this correction's. It is **not** applied here, and the
values recorded in section 16 are **not** reset.
`tests/test_card_v2_candidate_enumeration.py` pins the content instead, over
LF-normalised bytes, so the no-registered-file-changed claim is checkable
without depending on the checkout.

Minimal reproduction, retained and runnable:
`python scripts/fingerprint_diagnostic.py`. It prints each registered file's
line endings and both hashes, recomputes each fingerprint as-checked-out,
all-LF and all-CRLF, and names which convention reproduces the recorded
value. It reports only — it never rewrites a recorded hash. Its current
output is the evidence for this item and for E4.

## E4 — The recorded `v1_code_fingerprint` is not the value at the registration commit

**OBSERVED.**

Section 16 records `v1_code_fingerprint` as
`10f5cac7191ff23d0afcebc1f3566c8e747b9e4286a1eacbbfd8be09bf1c92ee` "at this
commit". That value does not reproduce from `859176ba`'s content under
either line-ending convention. It reproduces exactly (CRLF) when
`src/report/card.py` and `src/appstate/card_ledger.py` are taken from
`859176ba~1` — the two `V1_FINGERPRINT_FILES` members that the registration
commit itself modified. `data/processed/card_calibration.json` is identical
in both revisions and does not discriminate.

So the recorded value pins a **pre-commit** V1 state. It was computed before
those two files' registration-commit edits were applied. This does not change
any V2 number; it means the V1 comparison's pin (section 10, 11.6) currently
identifies a state that was never the registered one, and a genuine future
V1 change could be compared against the wrong baseline.

## E5 — Three published cards exceeded the registered ten-entry ceiling

**OBSERVED and SOURCE-CODE VERIFIED. Reported, not repaired.**

The owner's answer of 2026-09-16 about 00:45Z caps the card at "10 listed
bets in total, picks and fills together", and section 16 records the cost he
accepted: "an eleventh entry that passed every gate is refused a slot rather
than a published fill being withdrawn."

`best_bets_card.select` enforces that correctly within one run
(`best_bets_card.py:554-557`). The **ledger's** ceiling does not:

```python
# card_ledger.py:2100-2106
locked_shown = [e for e in merged if e.get("locked")]
room = max(0, params.ceiling - len(locked_shown))
```

Locked entries are exempt by design ("a lock is a lock"). Entries lock at
their own game's first pitch, and a locked entry is carried forward on every
later publish, so across a day's publishes the locked set grows and the card
grows past the ceiling with it. When every shown entry is locked, `room` is
0, there is nothing unlocked to refuse, and the merged card keeps whatever it
has.

The seven 2026-09-22 publishes of `evidence/cards_v2.jsonl`:

| Published (UTC) | picks | fills | entries listed | ceiling_refused |
|---|---:|---:|---:|---:|
| 14:43:31 | 0 | 3 | 3 | 0 |
| 15:41:59 | 2 | 3 | 5 | 0 |
| 19:14:07 | 2 | 3 | 5 | 0 |
| 20:12:45 | 2 | 4 | 6 | 0 |
| 21:00:25 | 9 | 3 | **12** | 1 |
| 21:31:49 | 10 | 3 | **13** | 0 |
| 22:02:40 | 11 | 3 | **14** | 0 |

`web/js/card.js` renders `payload.all_bets` in its server order and caps
nothing, so the last card listed fourteen entries against a registered
maximum of ten. The `n_picks = 11` in the handoff is not a counting-unit
artifact: it is eleven distinct picks, all props, all locked, on a card whose
stored `params.ceiling` is 10.

Also recorded, because it bears on E1: **every entry on all seven publishes
is a player prop.** `n_plus_money_picks` is 0 on all seven. No game moneyline
has ever been published under V2.

**The correct behaviour, demonstrated on the real sequence.** The breach does
not happen when an entry locks; it happens when an eleventh entry is
*admitted* to a card that already holds ten. An entry never admitted never
locks. `src/appstate/ceiling_admission.py` applies the cap at admission —
carried entries keep their slots, fresh ones fill the room that is left, the
rest are refused a slot and recorded — and `scripts/ceiling_reconciliation.py`
walks the day:

```
published (UTC)                    picks fills locked listed allowed refused
2026-09-22T14:43:31                    0     3      0      3       3       0
2026-09-22T15:41:59                    2     3      2      5       5       0
2026-09-22T19:14:07                    2     3      3      5       5       0
2026-09-22T20:12:45                    2     4      5      6       6       0
2026-09-22T21:00:25                    9     3     12     12      10       3
2026-09-22T21:31:49                   10     3     13     13      10       4
2026-09-22T22:02:40                   11     3     14     14      10       5
```

The cap holds at ten on every run, and **no published entry is removed** —
which is the condition the owner's answer imposed. Nothing is wired into the
publisher; `tests/test_ceiling_admission.py` covers the admission rule.

Applying it changes what the live publisher emits, so it stays out of scope
for a correction approved for shadow evaluation only. It needs the owner's
decision: admit under the cap as above, or amend the registered cap — which,
under section 16, is a new rule id.

---

## What the 2026-09-22 correction does

`src/analysis/card_v2_enum_shadow.py`, a new module in **neither** fingerprint
list. It calls `card_v2._build_game_candidates` unmodified for the favoured
side, adds the opposite side from that side's own quote row, and hands the
combined pool to the unedited `best_bets_card.select`. The favoured side's
candidate dict is the object the registered builder returned; only the added
side carries `enumeration = "moneyline_both_sides_v1"`.

Isolation is a fact about the import graph, not a promise about a flag: no
file under `src/`, `api/` or `scripts/` imports the module, and
`tests/test_card_v2_candidate_enumeration.py` walks those trees and fails if
one ever does. The live publisher, the scheduler and every served route keep
the registered implementation.

**Not approved for promotion.** No activation date is proposed. If the
corrected enumeration is ever published, section 16's own rule applies: it is
a new rule id, with its own registration, its own fingerprint and its own
count, and pre-fix and post-fix records are never pooled into one performance
claim.
