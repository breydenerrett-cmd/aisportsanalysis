# data-seed/statcast

This orphan branch holds a **seed copy** of `data/historical/statcast/`
(the Baseball Savant pitch-level Statcast store: `manifest.json` plus
`pitches_*.jsonl.gz` window files, ~45MB), used ONLY to bootstrap a cold
GitHub Actions runner where the `actions/cache` restore missed.

It exists because that store is `.gitignore`'d on the main branch (it is
bulk pitch data derived from a public source, not source code) and has no
cheap incremental rebuild path: `statcast --catchup` can only ever *extend*
an existing manifest, never create one from nothing, and a full `build()`
is a ~45-window season backfill against Baseball Savant that
`scripts/daily_bootstrap.sh` deliberately never triggers on its own. See
`docs/CAPTURE_EXTERNALIZATION.md` ("Daily loop externalization") and
`scripts/daily_bootstrap.sh`'s own header comment on the main branch for
the full rationale.

## How it is used

`scripts/daily_bootstrap.sh`, when it finds no
`data/historical/statcast/manifest.json` on a fresh checkout, fetches this
branch (`git fetch origin data-seed/statcast`, ref overridable via
`AISPORTS_STATCAST_SEED_REF`) and materializes `data/historical/statcast/`
from it before handing off to `statcast --catchup`. This is a data escape
hatch, not part of the normal cache-hit path -- on every day the
`actions/cache` restore succeeds, this branch is never touched.

## How it is refreshed

This is a **manual operation**, run by an operator from a checkout with a
current, healthy `data/historical/statcast/` store -- it is NOT part of the
daily loop and nothing in CI writes to this branch automatically. To
refresh it: from that checkout, in a separate temporary worktree, re-run
the same orphan-branch steps used to create this branch (checkout
`--orphan data-seed/statcast`, remove everything, copy in the current
`data/historical/statcast/`, refresh this README if needed, commit) and
force-push:

```
git push -u origin data-seed/statcast --force
```

Refresh it whenever the store has grown enough that a cold bootstrap
restoring from a stale copy would leave `statcast --catchup` too many days
behind to catch up affordably in one run -- there is no fixed schedule.
