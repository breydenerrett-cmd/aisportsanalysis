# Odds Data Credential — Purchase Brief

## Provider
The Odds API (the-odds-api.com), v4. Already implemented as the sole odds
provider in `src/providers/odds.py:1-46` (`ENV_KEY = "ODDS_API_KEY"`, host
`https://api.the-odds-api.com/v4`, `src/providers/odds.py:40,45`).

## Plan
Recommended: **"20K"** — $30/month, 20,000 credits/month, per
`PRICING_TIERS` in `src/providers/odds.py:237-243` and
`scripts/validate_odds_key.sh:181-188`.

## Current monthly price
Repo table and live pricing page agree, no drift found:
- free: $0 / 500 credits
- 20K: $30 / 20,000 credits
- 100K: $59 / 100,000 credits
- 5M: $119 / 5,000,000 credits
- 15M: $249 / 15,000,000 credits

Source: `src/providers/odds.py:237-243` (repo table); confirmed live via
WebFetch of the-odds-api.com pricing page and WebSearch of third-party
pricing roundups (OddsPapi, SimplyCodes, SharpAPI), all citing identical
figures as of Sept 2026 — see Sources below. **No drift.**

## Quota
1 credit per market per region on the live odds endpoint; historical
endpoints cost 10x (`src/providers/odds.py:35-36` comment block,
`HISTORICAL_CREDIT_MULTIPLIER = 10` at `src/providers/odds.py:35`).
The `/v4/sports` list call used by `scripts/validate_odds_key.sh` costs
0 credits (`scripts/validate_odds_key.sh:44-47`).

## Estimated monthly usage
From `scripts/validate_odds_key.sh:128-188` (repo's own worked estimate,
derived from `src/pipeline/dense.py` constants):
- Dense capture: ~132 credits/day (3 markets × 1 region × 4 captures/hr ×
  11-hr slate; `dense.py:26-31`, `scripts/validate_odds_key.sh:132-142`)
- F5 close pass: ~15-16 credits/day typical, up to ~32/day worst case
  (`scripts/validate_odds_key.sh:144-151`)
- **Steady state: ~148 credits/day typical (~4,440/month), ~164/day worst
  case (~4,920/month)** (`scripts/validate_odds_key.sh:166-171`)
- Plus a one-time, capped 400-credit prop-listing audit
  (`src/pipeline/prop_listing.py`, `docs/PROBE_PROP_LISTING.md`,
  `scripts/validate_odds_key.sh:153-160`)

Free tier (500/month) is exhausted in ~3.4 days at this cadence
(`scripts/validate_odds_key.sh:174-179`). 20K plan (20,000 credits) covers
this with ~4x headroom.

**Important operational note, not in the original ask but load-bearing:**
the repo's git history shows regular "Forward capture NN:NNZ" commits
(e.g. `bac461f`, `83986f7`, `6176518` — hourly, ongoing as of Sept 1 2026)
and `data/processed/odds_multibook.jsonl` contains rows with
`observed_utc` timestamps from Sept 1 2026 — i.e., **a live ODDS_API_KEY
is already active somewhere and already consuming credits today**, even
though it is not present as a GitHub Actions secret
(`.github/workflows/deploy-staging.yml` only references `FLY_API_TOKEN`,
no `ODDS_API_KEY`). This means the "buy or wait" decision may already be
moot for the current key/period — verify with Brey whether a key is
already purchased and on which tier before treating this as a fresh
purchase decision.

## On quota exhaustion
Confirmed via WebSearch of the-odds-api.com's own guides
(`the-odds-api.com/guide/rate-limit.html`,
`the-odds-api.com/manage/faqs.html`): **hard cutoff, no overage
billing.** When `x-requests-remaining` hits zero, further calls return
429 until the plan resets at the start of the next billing month. There
is no automatic overage charge and no throttle-then-bill behavior — the
feed simply stops serving live odds until reset or upgrade. Upgrading
mid-period is supported on the same key with no code change.

## Features this enables
Grep of `api/` and `src/analysis/` shows every customer-facing surface
that reads odds pulls from `src/analysis/prices.py`'s `boards_by_matchup`
(`src/analysis/prices.py:220-282`), which reads captured rows from
`src/pipeline/snapshots.py`, which are populated ONLY when
`ODDS_API_KEY`-backed captures run (`dense.py`, `forward_capture.sh`):
- `GET /odds/{date}` and `/odds/{date}/{away}/{home}` — full market
  board, best price, consensus, spread, staleness (`api/odds.py:64-80`)
- `GET /today` — per-game market section + odds-age metadata
  (`api/today.py:1-60`, `_odds_age_seconds`/`_odds_meta`)
- `api/betcheck.py` / `src/analysis/betcheck.py` — price-improvement
  claims, "your price beats consensus" checks (`betcheck.py:496-561`,
  `_market_facts`, `price_improvement`)

Without fresh captures, all three still respond (no 500s) but every
`market`/`price_improvement` section is either absent or serves whatever
was last captured, with `staleness`/`age_seconds` climbing and
`has_market: False` once no board exists at all
(`api/today.py:_odds_meta`, `src/analysis/oddspayload.py:186-220`
`_staleness`).

## What works without it
The system fails safe by design (`src/providers/odds.py:1-27` docstring):
without a key, every odds call returns an explicit "not configured"
result rather than raising or fabricating a price
(`SETUP_MESSAGE`/`NotConfigured` at `src/providers/odds.py:98-111`).
Schedule (`/games`), health, auth, billing, and admin endpoints are
entirely independent of odds. The captured historical data already on
disk (`data/processed/odds_multibook.jsonl`, 5,962 rows;
`odds_snapshots.jsonl`, 2,607 rows) continues to serve `/today` and
`/odds` with visible, honest staleness labels — it does not silently go
stale without saying so.

## Does private beta require it
No, not strictly on day one, given the staleness contract. The product's
own design goal — stated directly in `api/today.py`'s module docstring
("Staleness has to be visible starting at the first endpoint... or 'the
odds are old' becomes a fact only the dashboard knows") — is built to
degrade honestly: every payload that touches odds carries `observed_utc`
and `age_seconds`, and `has_market: False` when there's nothing at all.
A beta could launch on the captured-data path with visible staleness and
be truthful to users. That said: this is a live-odds/price-improvement
product; a beta running on data that is hours-to-days stale materially
undercuts the core value prop (price-improvement claims, betcheck) even
if it's not lying about it. Practically, this is a product-judgment call
about what beta users tolerate, not a technical requirement — and per the
note above, a key already appears to be active and paying for itself in
committed capture history, which weakens the "wait" case further.

## Alternatives & tradeoffs
- **SharpAPI** — free tier ~17,280 req/day (12/min), no card required;
  far more generous free quota than The Odds API's 500/month. Would
  require rewriting `src/providers/odds.py`'s request/response shape
  entirely (provider-specific parsing, market naming, credit model) —
  not a drop-in swap.
- **OddsPapi** — developer-first, 350+ books incl. sharp/crypto books,
  transparent per-request pricing, free tier "includes everything."
  Same rewrite cost as above; unverified production maturity vs.
  The Odds API's established track record in this repo's own capture
  history.
- **SportsGameOdds** — US-focused, 80+ books incl. Pinnacle, object-based
  billing $99-$499/mo — pricier than The Odds API's 20K tier for
  comparable volume; not obviously cheaper.
- **Big Balls Sports Data** — bundles odds+scores+lineups+stats, free
  tier 1,000-2,000 req/day; interesting for future feature surface but
  same full-rewrite cost.
- All alternatives were surveyed via third-party 2026 pricing roundups
  (OddsPapi blog, SharpAPI, SimplyCodes), not each provider's own docs
  directly — treat exact current numbers as directional, not verified to
  provider-primary-source rigor like The Odds API's numbers above.
- Switching cost is the deciding factor regardless of price: any
  alternative requires touching `src/providers/odds.py` (provider-locked
  request building, response parsing, credit accounting) plus its three
  test files (`tests/test_providers_odds.py`, `test_core_odds.py`,
  `test_api_odds.py`), which is real engineering time against a working
  integration.

## Recommendation
**BUY NOW** (or confirm the apparently-already-active key and move it
onto the 20K plan). The estimated steady-state usage (~4,440-4,920
credits/month) fits the $30/month 20K tier with ~4x headroom, quota
exhaustion is a clean, billing-safe 429 rather than a surprise charge,
and switching providers would cost real engineering time against a
working, tested integration for marginal-to-worse pricing. The one
open item before spending anything further is operational, not
financial: git history shows hourly captures already running today
against what must be a live key not tracked in CI secrets, so the
immediate action is confirming with Brey which key/tier is currently
active before assuming this is a fresh purchase decision.
