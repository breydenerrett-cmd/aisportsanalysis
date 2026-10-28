# Decision: how to run the live tennis paper test (it is OFF until you start it)

For Brey. The test you asked for on 2026-10-28 is built and pre-registered
(`docs/PREREG_LIVE_TENNIS.md`, rule `LIVE_TENNIS_V1`). It is **off**: with the switch
unset it makes no request, spends no credit and writes nothing. This memo is the one
thing it needs from you: where it should run, and the one setting that turns it on.

## The short version

- **Recommended if the PC really stays on: run it there.** Nothing in GitHub or the app
  changes. One command in a terminal that stays open, plus **one thing only you can do:
  this PC has no `.env` and no Odds API key today** (`capture --plan` prints
  `odds API key configured: NO`), so the key has to be put in a local `.env` first. Cost
  when running: about 120 Odds API credits on a typical tennis day, never more than 200
  (hard cap), never more than 4,000 a month, out of the 100,000 you already pay for. No
  new subscription.
- **If you would rather not put the key on this PC: Option B below.** The key already
  lives in GitHub's secrets (`live-window.yml` uses it), so B needs no secret handling,
  only the workflow file and a daily dispatch.
- **Not recommended: the app's background loops or a GitHub scheduled job.** Reasons
  below; the exact workflow file is in this memo anyway, in case you want it.
- **Expect a boring answer.** The test was registered expecting the model to LOSE to the
  books' later price by about the vig (2.8 points). A pass would be a surprise and would
  only earn a second, independent test. It cannot tell you whether courtsiding (seeing
  the score before the book) works, because our feeds are late by construction.

## Option A (recommended): the PC

Run this in PowerShell, from the repo, and leave the window open (it sleeps 5 minutes
when nothing is live or due, polls every minute while a match is on or about to start,
and stops itself on 2027-01-31):

```powershell
cd C:\Users\KC\Desktop\wt_ship
$env:LIVE_TENNIS_TEST = "on"
python -m src.cli research live-tennis capture --loop
```

Before the first run, create `C:\Users\KC\Desktop\wt_ship\.env` (copy `.env.example`; a
file named `.env` is gitignored) and fill the one line `ODDS_API_KEY=` with the key from
your Odds API account page, <https://the-odds-api.com/account/>. Every command reads it
from there and nothing prints or logs it. If the switch is on and the key is missing, the
command exits with an error before making any request. To turn it off: close the window, or unset the variable. To look at
what it would do without spending anything: `python -m src.cli research live-tennis
capture --plan` (makes no request at all).

Where the evidence lands, and the one chore:

| File | What | Tracked by git |
|---|---|---|
| `evidence/live_tennis_v1.jsonl` | every decision point, bet, reference, no-reference and outcome; hash-chained, append-only | yes |
| `data/research/live_tennis/snapshots.jsonl` | every paid board, verbatim | yes (not ignored) |
| `data/research/live_tennis/heartbeat.jsonl` | one row per tick, so downtime is counted | yes (not ignored) |
| `data/live/credit_log_live.jsonl` | this test's own credit rows (band `live_odds`, caller `live_tennis.capture`) | as today |

The chore: every day or two, commit and push those three files so the evidence is not
only on one disk (`git add evidence/live_tennis_v1.jsonl data/research/live_tennis`,
commit, push). Nothing automatic does this for the PC. If the PC is off, ticks are simply
missing and the heartbeat file shows it; the report counts them. Sleep and updates
matter: set the PC to never sleep while it runs (`powercfg /change standby-timeout-ac 0`),
as `docs/SNIPE_SYSTEM.md` section 2.1 says for the same reason.

Every few days: `python -m src.cli research live-tennis grade` (free; writes references
and outcomes) and `python -m src.cli research live-tennis report` (counts always; no
effect statistic until 300 bets with a reference from 150 matches).

## Why not the app's in-process loops

The existing loops (`live_feed`, `live_settle`) run inside the Fly app. This test's
ledger has to be committed evidence. The app cannot append to git-tracked `evidence/`
(it is baked into the image, `src/hounds/live_settle.py` says so for the house pack), the
volume is not reachable from git, and production redeploys the working-branch head about
hourly, so a ledger written under the app is either lost on a redeploy or stranded on a
disk the research CLI cannot read. Hooking it there would produce a test whose evidence
cannot be audited. So no hook was added to `api/app.py`, and `src/sports/live_feed.py` was
not touched.

## Option B (only if the PC cannot stay on): a dispatched GitHub run

GitHub's own `schedule` events fire a small fraction of the time
(`scripts/capture_tick.ps1` documents 4 of ~96 on 2026-09-07) and a set start is visible
at 0-0 for only a few minutes, so a cron is the wrong tool. A **dispatched** run that loops
for up to 330 minutes, like `live-window.yml`, works. It would be dispatched by you or by
the PC watchdog (`gh workflow run live-tennis.yml`), once a day around the first match
(about 08:00 UTC covers Europe through the US evening in two dispatches).

Create `.github/workflows/live-tennis.yml` on the default branch
(`claude/cowork-session-migration-tn3sx2`): open
<https://github.com/breydenerrett-cmd/aisportsanalysis/new/claude/cowork-session-migration-tn3sx2?filename=.github/workflows/live-tennis.yml>
and press **Commit changes** after pasting:

```yaml
name: live-tennis
run-name: "live-tennis"

"on":
  workflow_dispatch:
    inputs:
      max_minutes:
        description: "Maximum minutes to run"
        required: false
        default: "330"
        type: string

permissions:
  contents: write

concurrency:
  group: live-tennis
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 350
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Run the live tennis paper test
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
          LIVE_TENNIS_TEST: ${{ vars.LIVE_TENNIS_TEST }}
        run: |
          python3 -m src.cli research live-tennis capture --loop --max-minutes "${{ inputs.max_minutes }}" &
          PID=$!
          push() {
            git add evidence/live_tennis_v1.jsonl data/research/live_tennis
            git -c user.name="live-tennis" -c user.email="live-tennis@users.noreply.github.com" \
              commit -q -m "live tennis paper test: evidence $(date -u +%Y-%m-%dT%H:%MZ)" || return 0
            git pull --rebase -q && git push -q
          }
          while kill -0 "$PID" 2>/dev/null; do sleep 300; push; done
          push
```

and turn it on by creating the repository variable `LIVE_TENNIS_TEST` = `on` at
<https://github.com/breydenerrett-cmd/aisportsanalysis/settings/variables/actions>
(button **New repository variable**). With the variable unset the run starts, prints that
the test is OFF and exits. The Odds API key it needs is the `ODDS_API_KEY` secret that
`live-window.yml` already uses.

Caveats if you pick B: the credit log the guard reads on a fresh runner is the committed
one, so the daily cap is only as accurate as the last push; a dispatch that crosses
midnight UTC is fine (the cap is by UTC day); and two runs at once are prevented by the
`concurrency` group, not by the test.

## What I did and did not do

- Did: built the capture, model, ledger, guard, CLI and tests under `src/research/live_tennis/`
  and `tests/test_live_tennis_*.py`; wired the CLI (`research live-tennis ...`) in
  `src/cli.py`; this memo.
- Did not: edit any workflow YAML, `scripts/*.sh`, `api/app.py`, `src/capture/budget.py` or
  any other worker's file. The credit rows use the existing `live_odds` band and are
  counted against the existing 300-a-day shared live-odds cap, so on a day when MLB or NFL
  live capture also runs, this test can only use what that cap leaves.
- Not turned on. Nothing runs until you do Option A or B.
