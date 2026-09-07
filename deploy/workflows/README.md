# Workflows staged here, not yet registered

A GitHub workflow file can only be created or changed by a credential
carrying the `workflow` OAuth scope. The token this checkout pushes with, and
the `gh` CLI token beside it, both carry `repo` but not `workflow`:

```
Token scopes: 'gist', 'read:org', 'repo'
```

So a push that touches `.github/workflows/**` is refused by the server:

```
refusing to allow an OAuth App to create or update workflow
`.github/workflows/afternoon-slate.yml` without `workflow` scope
```

Anything in this directory is a finished workflow that is waiting on that one
permission. It is kept in git rather than left on one machine so it cannot be
lost, and so the person with the right credential can register it in one
step.

## afternoon-slate.yml — registering it

This is the F-1 fix (see `docs/DEMO_SHIP_CHECKLIST.md`): a second slate pass
at 21:10Z so the sixteen genome systems, which all require a posted lineup,
can actually decide. Until it is registered they refuse `NO_LINEUP` every
day and the slate carries only null baselines and market references.

The script it runs (`scripts/afternoon_slate.sh`) is already committed and
needs no special permission.

From a shell with a `workflow`-scoped credential:

```bash
gh auth refresh -s workflow          # once, grants the scope
git mv deploy/workflows/afternoon-slate.yml .github/workflows/
git commit -m "Register the afternoon slate workflow"
git push
```

Then register it on the DEFAULT branch as well, because GitHub only fires
`schedule` events from the default branch and this repository's default
branch is an orphan that shares no history with the working line — the same
step `forward-capture.yml` (25816b8) and `daily-loop.yml` (2b63f0d) each
needed:

```bash
git worktree add ../aisports-default claude/cowork-session-migration-tn3sx2
cp .github/workflows/afternoon-slate.yml ../aisports-default/.github/workflows/
cd ../aisports-default && git add .github/workflows/afternoon-slate.yml \
  && git commit -m "Register afternoon-slate on the default branch" && git push
```

The workflow itself checks out the working branch explicitly, so it does not
matter that the default branch has none of the code.

Verify with one manual run before trusting the cron:

```bash
gh workflow run afternoon-slate.yml -R breydenerrett-cmd/aisportsanalysis \
  --ref claude/cowork-session-migration-tn3sx2
```

A good run prints `decisions recorded for <date> by class:` including a
`FORWARD_TEST` count. If that count is still zero the genomes refused again,
and the per-game reason is in the log above it (the adapter logs its refusal
since b88b48b).
