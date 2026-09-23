# Forward shadow enumeration runs — what these artifacts are

Produced by `scripts/shadow_enumeration_run.py`, the single authorised caller
of `src/analysis/card_v2_enum_shadow.py`.

**Nothing in this directory was published.** Every artifact carries
`"shadow_only": true` and `"published": false`. These are offline evaluations
of an unwired enumeration against the live registered one, on the same board
at the same instant. No ledger, card store or customer surface was written by
any of these runs. An entry recorded here is *evaluated output*, never a
published pick, and must not be described as one.

Each artifact preserves, at its own original run timestamp: the board and
every quote with its own `observed_utc`; the complete model inputs per game
with raw **and** calibrated outputs plus a consistency check of the
raw→calibrated arithmetic; the frozen parameter file's sha256 and the full
rule parameter set; both sides' quotes and candidate identities; every gate
result per candidate; and every selection. Artifacts are never edited after
the fact — a correction is a new file, and this README carries the analysis.

---

## 2026-09-23T14:09:51Z — the first complete forward result

The first run on a full board (an earlier 02:50Z run found all 16 games below
the six-book floor and is kept alongside for comparison).

### Counts, labelled by market

The headline "16 → 32 candidates" is **game moneylines only**. The full pools
are larger because both arms also carry the identical prop pool.

| | game moneyline | player prop | raw pool |
|---|---:|---:|---:|
| registered path | 16 (favourite only, one per game) | 64 | **80** |
| corrected path | 32 (both sides of the same 16 games) | 64 | **96** |

The correction adds **16 game-moneyline sides** and changes the prop pool by
nothing. The two arms' prop candidates are the same 64 rows, built by the same
unmodified builder.

### Reconciling the three-entry cards — they share no entry

Both arms produced a three-entry card, and it is a coincidence of the floor,
not a similarity of content.

| | entries | kind | class |
|---|---|---|---|
| registered | 3 | **prop fills** | MAIN, −152 / −160 / −135 |
| corrected | 3 | **game moneyline picks** | PLUS_MONEY, +128 / +154 / +125 |

* **Registered:** the game pool produced zero picks *and* zero fills. The
  floor of three was met **entirely from the prop pool**, as labelled fills —
  entries that did not pass the value test and are shown only to reach the
  floor. So on a full sixteen-game board the live rule put forward no game
  selection at all.
* **Corrected:** the three added moneyline sides that cleared every gate
  became picks, which met the floor on their own, so no fill was drawn.

No entry appears on both cards.

### Gate outcomes for the 16 added sides

| primary reason | count |
|---|---:|
| G7_VALUE | 11 |
| G5_MARKET | 1 |
| G8_DISAGREEMENT | 1 |
| passed every gate | **3** |

`added_sides_missing_model_input: 0` — every added side carried a real frozen
model number, so G6/G7/G8 were decided on actual model output and nothing was
substituted to manufacture a pick. `sides_not_built: []` — every game's
opposite side was buildable. `raw_to_calibrated_all_consistent: true`.

### What this is, and is not, evidence of

**Is:** the candidate-coverage defect was suppressing candidates that pass
every registered gate, on a real forward board rather than a fixture. The
gates were not bypassed — 13 of 16 added sides were refused, 11 of them by
the value test.

**Is not:** evidence of profitability, or a reason to promote the corrected
enumeration publicly. The games had not been played when this ran, the
artifact contains no outcome information, and three selections on one slate
is not a sample. Thresholds stay exactly as registered; they will not be
adjusted in response to how these three settle, in either direction.

### A finding that sets the next task

The 64-candidate prop pool produced **zero picks in both arms** — fills only.
Props are enumerated one side per contract (`src/report/props.py:148` keeps
only `propboard.most_likely`'s side, floor 0.50), which is the same departure
from registration section 2 that this correction just fixed for moneylines.
Every entry on all seven published 2026-09-22 cards was a prop, so that pool
is where the published card actually lives.
