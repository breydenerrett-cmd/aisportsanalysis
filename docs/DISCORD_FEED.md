# Discord community feed (`scripts/discord_feed.py`)

Posts the day's frozen public card plus the public graded record into one or
more Discord channels via incoming webhooks -- one webhook per paying
community server. Stdlib-only, idempotent per webhook, read-only against the
ledger. See the module docstring in `scripts/discord_feed.py` for the design
rationale (why picks are rebuilt from frozen fields instead of a stored
sentence, why NFL/UFC differ from MLB, the idempotency key, why a webhook URL
is never logged).

Sports: `--sport mlb` (default), `--sport nfl`, `--sport mma`. NFL reads the
frozen NFL card exactly as `GET /card?sport=nfl` does for a published date
(`src/report/nfl_card.py`); if no NFL card is published for the date the run
prints `no published card for <date>`, posts nothing and exits 0 -- that is
normal on a non-game day, not an error.

## Webhook configuration

A run delivers to every webhook it finds in:

| Source | Holds |
|---|---|
| `DISCORD_WEBHOOK_URL` | one URL (the original variable, still works) |
| `DISCORD_WEBHOOK_URLS` | many URLs, separated by commas and/or newlines |
| `--webhook-url` | one URL on the command line |

All three are merged into one list. Whitespace and empty items are ignored
and duplicates are collapsed, so a URL listed twice is posted to once.

`scripts/daily_loop.sh` and `scripts/afternoon_slate.sh` call the feed only
when a webhook variable is set. They need the gate to open on either
variable and an NFL line next to the MLB one:

```sh
if [ -n "${DISCORD_WEBHOOK_URL:-}${DISCORD_WEBHOOK_URLS:-}" ]; then
    python3 scripts/discord_feed.py --sport mlb || echo "ESCALATE: discord feed failed"
    python3 scripts/discord_feed.py --sport nfl || echo "ESCALATE: discord feed failed"
fi
```

Both workflow files must also pass the new secret through (see section 3).

## What is posted, and what never is

- Only the frozen published card -- never a live build.
- Nothing priced at -200 or shorter. Such an entry is dropped from the post;
  a card whose every entry is that short prints `nothing to post for ...` and
  posts nothing.
- Fills appear under their own **Fills** heading, never mixed into **Picks**.
- Props read as `Devers over 0.5 hits at +120` (side and market in plain
  words), taken from the frozen row.
- The footer is the feed's own beta disclaimer. The words edge, profit, lock,
  guarantee, sharp, winning and "Bet Check" never appear; the only exception
  is the sentence "No edge is claimed." A payload that contains one of those
  words is refused (`ESCALATE: ... banned wording`) rather than posted. Today
  that refuses UFC cards, whose stored basis text says "at lock".

## 1. Add a customer server

1. The customer creates the webhook in their own server: **Channel Settings
   -> Integrations -> Webhooks -> New Webhook**, picks the channel, copies the
   URL (`https://discord.com/api/webhooks/<id>/<token>`).
2. They send that URL to the owner **privately** (direct message or email to
   the owner only). Never paste it in a public channel, an issue, a commit, a
   chat with a bot or a log. Anyone holding the URL can post to that channel.
3. The owner appends it to the repository secret `DISCORD_WEBHOOK_URLS`
   (GitHub -> repo -> **Settings -> Secrets and variables -> Actions**,
   edit the secret): one URL per line, or comma-separated. Paste the whole
   existing value plus the new line -- editing a secret replaces it.
4. Nothing else. The next run posts the current card to the new server (its
   own marker is empty, so it gets today's card even if others already have
   it) and every later run keeps it in step.

## 2. Remove a server (cancellation, deleted webhook)

Delete that URL from `DISCORD_WEBHOOK_URLS` (edit the secret and save the
remaining lines). That is the whole removal; nothing else references it. The
customer should also delete the webhook in their server's settings, which
makes the old URL dead. The marker file keeps only a hash of the URL, so
nothing to scrub there.

## 3. Add the secrets to the workflows (default branch)

**This is the step that is easy to get wrong.** Both `daily-loop.yml` and
`afternoon-slate.yml` say so in their own comments: a scheduled
(`on: schedule`) run always reads the workflow file from the repository's
**default branch**, never from the branch named in `ref:` further down the
file (that `ref:` only controls which branch is *checked out for the code*,
i.e. which copy of `scripts/discord_feed.py` runs). An env line added only on
a feature branch's copy of the YAML will never be read by the 10:00Z / 15:40Z
cron triggers -- only by a manual `workflow_dispatch` run from that branch.

So add the lines below to **both** files, **on the default branch**, and
mirror the edit onto the working branch's copy
(`claude/sports-betting-analysis-review-g1o0co` as of this writing) so a
manual `workflow_dispatch` run from that branch also carries them.

### `.github/workflows/daily-loop.yml`, step "Run the daily loop"

```yaml
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
          BALLDONTLIE_API_KEY: ${{ secrets.BALLDONTLIE_API_KEY }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          DISCORD_WEBHOOK_URLS: ${{ secrets.DISCORD_WEBHOOK_URLS }}
```

### `.github/workflows/afternoon-slate.yml`, step "Run the afternoon slate pass"

```yaml
        env:
          ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
          DISCORD_WEBHOOK_URLS: ${{ secrets.DISCORD_WEBHOOK_URLS }}
```

A secret that does not exist expands to an empty string, so keeping the
`DISCORD_WEBHOOK_URL` line costs nothing. `data/watch` (the marker file's
directory) is already committed by both scripts' existing `git add` lines.

## 4. Failure behaviour

Each webhook is handled on its own:

- **Already posted** (its own marker for this sport, date and card version
  exists): skipped, nothing sent.
- **Posted OK**: a marker row is appended for that webhook only.
- **Failed** (network error, HTTP 404 because the customer deleted the
  webhook, HTTP 429 rate limit, anything else): no marker is written for it,
  the other webhooks are unaffected, and the next run retries only the ones
  that failed. A 404 keeps failing every run until the dead URL is removed
  from the secret -- that is the signal to do so.

Exit code: **0** when every webhook is posted-or-already-posted, non-zero
otherwise. Each failed webhook prints one line:

```
ESCALATE: discord feed post failed for mlb 2026-10-04 [webhook 3fa91c07]: HTTP 404 (Not Found)
```

The bracketed id is the first 8 hex characters of the sha256 of the URL. To
find which customer it is, hash each URL in the secret the same way:

```sh
python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:8])" "<url>"
```

A webhook URL never appears in output, logs, the marker file or error text.
(Discord/urllib error text that quotes a URL is scrubbed, and unexpected
exceptions are reported by class name only.)

Other lines a run can print: `no published card for <date>` (exit 0),
`nothing to post for <sport> <date>: ...` (exit 0),
`already posted: ... [webhook xxxxxxxx]` (exit 0),
`posted: <sport> <date> (card) [webhook xxxxxxxx]` (exit 0), and
`ESCALATE: discord feed for ... has no webhook URL configured` (exit 1).

## 5. First post from this PC (manual, no workflow needed)

Always dry-run first -- it prints the exact JSON payload and posts nothing,
regardless of whether a webhook is set:

```powershell
# PowerShell, from the repo root
python scripts\discord_feed.py --sport mlb --dry-run
python scripts\discord_feed.py --sport nfl --date 2026-09-27 --dry-run
```

```sh
# Git Bash
python scripts/discord_feed.py --sport mlb --dry-run
```

Then set the webhook(s) for the session and run for real (omit `--date` to
default to today):

```powershell
# PowerShell
$env:DISCORD_WEBHOOK_URLS = "https://discord.com/api/webhooks/<id>/<token>,https://discord.com/api/webhooks/<id2>/<token2>"
python scripts\discord_feed.py --sport mlb
```

```sh
# Git Bash / the real runners (python3)
export DISCORD_WEBHOOK_URLS="https://discord.com/api/webhooks/<id>/<token>
https://discord.com/api/webhooks/<id2>/<token2>"
python3 scripts/discord_feed.py --sport mlb
```

Other flags: `--record-only` (post just the running record, skip the card),
`--webhook-url` (one more URL, merged with the environment variables).
