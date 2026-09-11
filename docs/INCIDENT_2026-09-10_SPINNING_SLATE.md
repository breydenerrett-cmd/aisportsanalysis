# Incident: the slate pages spun forever, and every check was green

**2026-09-10, ~9pm ET.** Reported by Brey, from his phone, with screenshots:

> Both pages show loading slate and they just sit there and spin and circle
> for many many many minutes... if there's anybody that has any excitement
> about what we're doing and then gets to these pages and the slates aren't
> loading there's literally no point.

Two screenshots: `#/today` showing **LOADING TONIGHT'S BOARD** and `#/games`
showing **LOADING THE SLATE**, both with the skeleton animating.

---

## What was actually wrong

Four defects, none of which failed a test, and each of which hid the next.

### 1. The cache made the CUSTOMER pay for the rebuild

`api/games.py` caches one date's slate entries for **120 seconds**. On expiry
the cache made the **requesting thread** run the rebuild.

That rebuild takes about **3s on a developer laptop and 20–45s on the 512 MB
staging container** — the deploy's own health check got a 200 inside its 45s
budget while a browser gave up at 20s. Against a 120s TTL, roughly every
other visitor arrived just after an expiry and waited out the whole rebuild
behind an animating skeleton.

**This was the spinner.** Not an outage, not an error — a cache whose expiry
policy handed the bill to whoever happened to arrive next.

### 2. No API call could ever time out

`web/js/api.js` called `fetch()` with no `AbortController` and no timeout.

A 503 was never the problem: that rejects at once, and `dom.js`'s
`renderError` already says *"We could not reach the board"* and distinguishes
it from an honest empty night. The silent case is a server holding the socket
open and never writing a response. The promise never settled, `renderError`
was never reached, and the skeleton animated indefinitely.

### 3. The deploy check never touched the endpoint that was broken

It exercised `/card`, `/card/record`, `/opportunities` and `/today` — and
stopped. `/games/{date}`, `/changed/{date}` and `/odds/{date}` were never
called, so a completely dead Games page shipped as a **green deploy, twice
that day**.

The rule the omission broke: *a deploy check must touch every route a
customer's first screen calls.* `#/today` alone fires four.

### 4. Staging ships an image with no historical data

`deploy-staging.yml` restores the daily-loop cache and reports
`Cache not found for input keys: daily-loop-data-` on **every** run, while
45 MiB caches with exactly that prefix are written every thirty minutes.

The caches sit on the **orphan default branch**. A run on the working branch
sees **zero** of them (`gh api .../actions/caches?ref=<working branch>` →
`total_count: 0`): an orphan shares no history with the working branch, so
the working branch never inherits its cache scope. Matching the `path` list
to daily-loop's save step was necessary — GitHub hashes that list into the
cache version — and was **not sufficient**.

**This is real and it is NOT what caused the spinner.** That was assumed
first and then measured: building the same slate with every `data/historical/`
store absent takes **1.07s against 1.09s** with them all present. Missing data
degrades what the page can *say*; it does not make it slow.

---

## Fixes

| # | Fix | Where |
|---|---|---|
| 1 | **Stale-while-revalidate.** Past the TTL, serve the last good slate instantly (flagged stale, with a reason) and rebuild on a background thread. Only the first caller after a cold start waits. Bounded at 10 minutes. | `src/appstate/freshness.py`, `api/games.py`, `api/today.py` |
| 2 | **20-second timeout on every API call**, covering the body read as well as the headers, raising with a null status so it lands on the network branch. | `web/js/api.js` |
| 3 | **`/games`, `/changed`, `/odds` added to the deploy check**, plus `flyctl logs` captured on failure. | `.github/workflows/deploy-staging.yml` |
| 4 | Path list matched to daily-loop's save step; a **loud warning** when the image ships without data. | `.github/workflows/deploy-staging.yml` |

Tests: `tests/test_stale_while_revalidate.py` (11), `tests/test_request_timeout.py`
(10). The timeout tests were run against the committed pre-fix `api.js` and
**all 7 enforcement tests failed**, so they catch the original bug rather than
describing the new code.

The stale-while-revalidate test asserts **timing**, not a flag: against a
builder that sleeps 2s, the stale read must return in under 0.5s. A test that
only checked `stale: true` would pass on a cache that still blocked.

---

## Still open

- **Why `/games/{date}` takes 20–45s on Fly and 3s locally.** Stale-while-
  revalidate means customers no longer pay it, but the cost is still there and
  the first visitor after each deploy still meets it. Candidates not yet
  separated: cold module imports, `mlb.fetch_games` latency from `iad`, and
  the shared vCPU. The new `flyctl logs` step should narrow it.
- **The cache never restores.** The durable fix is publishing the stores as a
  workflow **artifact** (repo-scoped) rather than a cache (branch-scoped).
  That requires editing `daily-loop.yml` **on the default branch**, since cron
  workflows run from there — not something the working branch can do to
  itself.
- **Warming the cache at startup** would close the remaining cold-start gap.
  Deliberately not done in the same change: it touches app boot on a container
  that had been falling over, and the fix above should be verified alone first.

## The pattern, again

Every one of the four was silent. No test went red, no function was wrong, the
deploy was green, and the only signal that any of it was broken was a customer
saying the page would not load.

That is the seventh instance in three days of *code that is correct, tested,
committed, and that nothing exercises.* `scripts/reachability_audit.py` was
built for this class and does not yet walk the deploy check's route list
against what the frontend actually calls — which is precisely the gap that let
#3 through.
