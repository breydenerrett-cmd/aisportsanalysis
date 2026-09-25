# Prop pool reconciliation, 2026-09-23 — exact identity sets, not a subtraction

Source artifact: `evidence/shadow_enumeration/2026-09-23_20260923T170144Z_moneyline-props.json`
(the 163000Z run earlier the same evening carries the identical two counts,
144 and 234, and reconciles the same way — 170144Z is used here as the later
of the two). Produced by `src.analysis.card_v2_enum_shadow.reconcile_identity_sets`
run directly against that artifact's own `registered_path.prop_candidate_rows`
(144 rows) and `corrected_path.prop_candidate_rows` (234 rows), identity
`(player, market, line, side)` — D1b's own default, unchanged.

## The claim being checked

Brey reported the prop pool "went 144 -> 234" and, separately, "117 added
Under sides". `234 - 144 = 90`, so a single subtraction cannot be both
numbers at once — that arithmetic fact is what this task asked to resolve:
state the real relationship, or show the earlier framing was wrong.

## The exact reconciliation

```
n_before = 144   n_after = 234
n_added   = 117
n_removed = 27
n_unchanged = 117
duplicate identities: 0 before, 0 after
```

Both checks that must hold for an exact set reconciliation hold here:
`n_unchanged + n_added == n_after` (117 + 117 = 234) and
`n_unchanged + n_removed == n_before` (117 + 27 = 144).

**"117 added" is correct as a count. It is not a count of Under sides.**
Of the 117 added identities, 82 are `Under` and 35 are `Over`:

| | Over | Under | total |
|---|---:|---:|---:|
| added | 35 | 82 | 117 |
| removed | 0 | 27 | 27 |
| unchanged | 117 | 0 | 117 |

(The 117 `unchanged` identities are all `Over` because the registered board
keeps `propboard.most_likely` — probability > 0.50 — and every one of these
117 contracts' `Over` side was the more-likely one; see below for why they
read as "unchanged" rather than "added" even though the corrected board
rebuilds every contract from scratch.)

## Why 27 identities were REMOVED — a scope difference, not a bug in this fix

Every one of the 27 removed identities is `batter_runs_scored, Under`.
Cross-tabulated by market, the two pools are:

```
registered (144): batter_hits 67, batter_total_bases 50, batter_runs_scored 27
corrected  (234): batter_hits 134, batter_total_bases 100
```

`67 + 50 = 117` and `134 = 2 * 67`, `100 = 2 * 50` — **exactly** doubled.
That is the correction working as designed: `both_sides_prop_board`'s own
docstring states it applies `daily_card.PROP_MARKETS = ("batter_hits",
"batter_total_bases")` because "section 2 registers two markets" and the
corrected board must not widen the registered set.

The registered board is where the widening already was, not this fix.
`props.board_for_date` (the LIVE path `card_v2._build_prop_candidates` calls
when no `prop_board` override is given) does **not** filter to
`PROP_MARKETS` — it returns whatever `propboard.build` priced, capped by
`most_likely` and a display limit, with no market restriction
(`src/report/props.py:119-154`). So the registered 144-row pool already
contained 27 `batter_runs_scored` contracts that section 2 never registered
at all. The corrected arm, which explicitly scopes itself to the two
registered markets, was never going to carry them, so they disappear from
the corrected side of the reconciliation — not because a side was dropped by
the both-sides correction, but because they were out of the registered
market's scope on both sides of the comparison and only the registered
LIVE path's own filter gap let them into the "before" count in the first
place.

This is a **separate, pre-existing departure from registration section 2**
(an unregistered third market reaching the registered V2 candidate pool) —
worth a line in a future audit, but it is not this task's correction to make
and no file in this lane's write area was touched to produce this finding;
it is read directly off the two pools' own `market` fields.

## The real relationship

```
234 = 2 x (67 + 50) = 2 x 117
```

The two REGISTERED markets (`batter_hits`, `batter_total_bases`) contained
117 contracts in the registered pool. Both-sides enumeration keeps each
contract's original (`most_likely`) side untouched — that is the 117
`unchanged` — and builds exactly one new side per contract — that is the 117
`added`. 117 == 117 here because every registered-market contract has
*exactly* two sides and the correction adds *exactly* the one the live path
was dropping; it is not a coincidence between two unrelated counts, it is
the same 117 contracts counted twice, once on each side of the mirror.

Net growth is `2 x 117 - 144 = 90`, which resolves against the 27 removed
`batter_runs_scored` rows exactly: `117 added - 27 removed = 90 net`, which
is `234 - 144`. All three framings — "144 -> 234", "117 added", "90 net
growth" — are simultaneously true once the 27 removed identities are stated
separately. Describing the 117 additions as "Under sides" was the part that
did not hold: 35 of them are `Over`.

## Primary gate-rejection counts (D1b, exclusive — one bucket per candidate)

Computed with `primary_gate_rejection_counts` over each pool's own recorded
`gate_primary_reason` (the corrected arm's real `gate_census`, from the same
artifact):

```
registered (n=144): {'G3_STALE': 144}
corrected  (n=234): {'G3_STALE': 234}
added-only (n=117): {'G3_STALE': 117}
```

Every candidate in both pools failed G3 (stale quote) as its PRIMARY
reason — this capture's props were all too old by the time `select` ran, so
neither pool produced a single prop pick on this run (both arms' cards were
filled from elsewhere or left short). That is a real, reportable result
about this one capture's freshness, not a defect in the reconciliation
method, and it is consistent with the module's own stance that zero picks
from a widened pool is a valid outcome — nothing here was tuned to
manufacture a pick.

## What this does not show

This is one artifact from one evening. It says how the 144 -> 234 change
partitions, and it says the registered pool already exceeded its own
registration by 27 rows before this correction touched anything — it says
nothing about any other date's prop board, and nothing about whether the 90
net additional candidates would ever have produced a different card, since
every candidate in this particular capture failed G3 regardless of
enumeration.
