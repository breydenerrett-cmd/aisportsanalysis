# Discord community feed (`scripts/discord_feed.py`)

Posts the day's frozen public card plus the public graded record into a
Discord channel via an incoming webhook. Stdlib-only, idempotent, read-only
against the ledger -- see the module docstring in `scripts/discord_feed.py`
for the full design rationale (why picks are rebuilt from frozen fields
instead of a stored sentence, why NFL/UFC differ from MLB, the idempotency
key, why the webhook URL is never logged).

Already wired into `scripts/daily_loop.sh` (right after `card record
(running)`) and `scripts/afternoon_slate.sh` (right after `card publish`),
both gated identically:

```sh
if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then
    python3 scripts/discord_feed.py --sport mlb || echo "ESCALATE: discord feed failed"
fi
```

Unset the env var and both scripts skip the step entirely -- nothing to do
below until you actually want it posting.

## 1. Create the Discord webhook

In the target Discord channel: **Channel Settings -> Integrations ->
Webhooks -> New Webhook**. Copy its URL
(`https://discord.com/api/webhooks/<id>/<token>`). Treat it like a
credential -- anyone with the URL can post to that channel.

## 2. Add the repository secret

GitHub -> repo -> **Settings -> Secrets and variables -> Actions -> New
repository secret**:

- Name: `DISCORD_WEBHOOK_URL`
- Value: the webhook URL from step 1

## 3. Add the YAML on the default branch

**This is the step that is easy to get wrong.** Both `daily-loop.yml` and
`afternoon-slate.yml` say so in their own comments: a scheduled
(`on: schedule`) run always reads the workflow file from the repository's
**default branch**, never from the branch named in `ref:` further down the
file (that `ref:` only controls which branch is *checked out for the code*,
i.e. which copy of `scripts/discord_feed.py` runs). A `DISCORD_WEBHOOK_URL:`
line added only on a feature branch's copy of the YAML will never be read by
the 10:00Z / 15:40Z cron triggers -- only by a manual
`workflow_dispatch` run started from that branch.

So: add the two lines below to **both** files, **on the default branch**
(check `git branch --show-current` after checking out the default branch, or
look at the repo's Settings -> Branches page if unsure which branch that
is -- `daily-loop.yml`'s own comment calls it "an orphan that shares no
history with the working line"). Mirror the same edit onto the working
branch's copy too (`claude/sports-betting-analysis-review-g1o0co` as of this
writing) so a manual `workflow_dispatch` run from that branch also carries
the webhook.

### `.github/workflows/daily-loop.yml`

Existing step (job `daily`):

```yaml
      - name: Run the daily loop
        id: daily_loop
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
          BALLDONTLIE_API_KEY: ${{ secrets.BALLDONTLIE_API_KEY }}
        run: |
          set -o pipefail
          bash scripts/daily_loop.sh 2>&1 | tee -a /tmp/daily_run.out
          exit "${PIPESTATUS[0]}"
```

Add one line to `env:`:

```yaml
      - name: Run the daily loop
        id: daily_loop
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
          BALLDONTLIE_API_KEY: ${{ secrets.BALLDONTLIE_API_KEY }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: |
          set -o pipefail
          bash scripts/daily_loop.sh 2>&1 | tee -a /tmp/daily_run.out
          exit "${PIPESTATUS[0]}"
```

### `.github/workflows/afternoon-slate.yml`

Existing step (job `slate`):

```yaml
      - name: Run the afternoon slate pass
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
        run: |
          set -o pipefail
          bash scripts/afternoon_slate.sh 2>&1 | tee -a /tmp/afternoon_slate.out
          exit "${PIPESTATUS[0]}"
```

Add one line to `env:`:

```yaml
      - name: Run the afternoon slate pass
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: |
          set -o pipefail
          bash scripts/afternoon_slate.sh 2>&1 | tee -a /tmp/afternoon_slate.out
          exit "${PIPESTATUS[0]}"
```

Neither workflow needs any other change -- `data/watch` (the marker file's
directory) is already committed by both scripts' existing `git add` lines.

## 4. First post from this PC (manual, no workflow needed)

Always dry-run first -- it prints the exact JSON payload and posts nothing,
regardless of whether a webhook URL is set:

```powershell
# PowerShell, from the repo root
python scripts\discord_feed.py --sport mlb --date 2026-09-27 --dry-run
```

```sh
# Git Bash
python scripts/discord_feed.py --sport mlb --date 2026-09-27 --dry-run
```

Once that looks right, set the webhook URL for the session and run for
real (omit `--date` to default to today, the same default-date rule
`api/card.py`'s `GET /card` uses):

```powershell
# PowerShell
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/<id>/<token>"
python scripts\discord_feed.py --sport mlb
```

```sh
# Git Bash / the real runners (python3)
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/<id>/<token>"
python3 scripts/discord_feed.py --sport mlb
```

A run prints one of:

- `no published card for <date>` (exit 0) -- nothing published yet, nothing posted.
- `already posted: ...` (exit 0) -- this exact card version was already sent; safe to re-run anytime.
- `posted: mlb <date> (card)` (exit 0) -- sent, and a row was appended to `data/watch/discord_feed_posted.jsonl`.
- `ESCALATE: discord feed ...` (exit 1) -- no webhook configured, or Discord rejected the post. The webhook URL itself never appears in this output or in the marker file (only a sha256 of it, `webhook_hash`).

Other flags: `--sport {mlb,nfl,mma}` (default `mlb`), `--record-only` (post
just the running record, skip the card entirely), `--webhook-url` (instead
of the env var).
