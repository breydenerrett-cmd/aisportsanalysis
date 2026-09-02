# Launch-day checklist (morning-of, private beta)

For the morning outreach actually starts, or the morning a fresh deploy
goes out before outreach — not a general deploy runbook (that's
`deploy/DEPLOY_RUNBOOK.md`) and not the multi-day plan (that's
`docs/FIRST_CUSTOMER_PLAYBOOK.md` §1). This is the short list to run once,
same morning, before the first stranger sees a link.

Run top to bottom. A red item is a stop, not a note — do not send outreach
or a demo link with a red item unresolved.

## 1. Staging green

- [ ] `bash scripts/smoke_api.sh` against the live staging URL
      (`BASE=https://linehound-staging.fly.dev`) — green, not "green last
      time I checked." <!-- source: docs/FIRST_CUSTOMER_PLAYBOOK.md §1 -->
- [ ] `GET /health` returns `status: "ok"` with an empty `reasons` array —
      paste the raw response if anything looks off; it never carries a
      token, email, or row body, so it's safe to paste anywhere
      (`docs/API_CONTRACTS.md`'s `/health` section).
- [ ] `GET /meta` returns the expected `version` (not stale from a prior
      deploy) and the current beta `disclaimer` string.

## 2. Funnel smoke (paid path specifically)

- [ ] `bash scripts/funnel_smoke.sh` against staging, with real Stripe
      *test-mode* keys configured — proves signup → checkout → webhook →
      activation token end to end before a real card touches it.
      <!-- source: docs/FIRST_CUSTOMER_PLAYBOOK.md §1 step 3 -->
- [ ] `GET /admin/funnel` shows the funnel steps rendering (even at 0 —
      a step with zero events renders as `0`, never omitted;
      `docs/FIRST_CUSTOMER_PLAYBOOK.md` §7). Confirm the endpoint itself
      answers before relying on it all day.
- [ ] If it's been a while since Brey's own test-mode dry run (§1 step 4 of
      `FIRST_CUSTOMER_PLAYBOOK.md`) — landing → signup → checkout → token →
      Today → Bet Check — re-run it once this morning if anything shipped
      since the last dry run. Any friction found gets fixed before
      outreach goes out, full stop.

## 3. Capture fresh (real data on the slate, not stale)

- [ ] Confirm today's MLB slate actually has games (`GET /today` /
      `GET /games/{date}` for today's date) — a launch morning with a
      genuinely empty slate (all-star break, off day) is a real thing to
      know before promising a live demo.
- [ ] Confirm the forward-evidence/odds capture for today is fresh —
      `odds_meta.age_seconds` / `staleness.age_seconds` on a real game
      should read as a normal capture interval, not hours-stale or `null`
      across the board. A `null` `age_seconds` means no market at all for
      that game (`docs/API_CONTRACTS.md` vocabulary rules) — distinguish
      "no market yet this morning" (normal, early) from "capture is
      broken" (not normal by mid-morning).
- [ ] Pick the one real game the demo script (`docs/FIRST_CUSTOMER_PLAYBOOK.md`
      §3) will use, and confirm it has a priced market before committing to
      it — never fall back to a hypothetical matchup if the picked game's
      market isn't up yet; pick a different one that is.

## 4. Support inbox watched

- [ ] `GET /admin/support?status=open` — start the day at zero backlog, or
      know exactly what's already open before new messages start arriving
      from outreach.
- [ ] Confirm someone (Brey) is actually watching it today — no ticketing
      system exists (`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §3), so "watched"
      means a person checking the endpoint, not a notification firing on
      its own.
- [x] `scripts/monitor_remote.sh` wired against the staging URL so an outage
      during outreach surfaces without refreshing a tab
      (`docs/FIRST_CUSTOMER_PLAYBOOK.md` §1 step 5). **WIRED**: running as
      an hourly routine against staging, live since 2026-09-01.

## 5. Rollback path

- [ ] Confirm the previous known-good Fly release/image is identifiable
      (`fly releases` or equivalent) before deploying anything new today —
      a launch-day deploy should never be the first time anyone checks
      whether rollback is possible.
- [ ] If today's launch follows a fresh deploy: re-run item 1 (staging
      green) and item 2 (funnel smoke) AFTER the deploy, not just before —
      a deploy that looked fine pre-flight and broke something is exactly
      what these two checks exist to catch before a stranger hits it.
- [ ] Know the one command to roll back before you need it (do not look it
      up for the first time during an incident) — see
      `deploy/DEPLOY_RUNBOOK.md` for the current mechanism; this checklist
      does not duplicate Fly's own rollback docs.

## 6. Vocabulary / honesty pass on anything going out today

- [ ] Any outreach copy, demo script deviation, or canned response written
      fresh this morning gets a quick scan against the banned/negation-only
      lists (`tests/test_customer_language.py`, `tests/test_content_language.py`)
      before it's sent to a stranger — no "edge," no "true" price, no
      guaranteed outcome, no invented win probability, `late_move` is never
      "CLV." A launch-day rush is exactly when a banned phrase slips in.

---

**If any item above is red and cannot be fixed same-morning:** delay
outreach, not the fix — do not send a first-impression link to a stranger
against a known-broken funnel or a stale slate. `docs/FIRST_CUSTOMER_PLAYBOOK.md`
§1's own framing: a red smoke test "is a stop, not a note."
