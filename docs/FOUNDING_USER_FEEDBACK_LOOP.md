# Founding-user survey + days 1–7 feedback loop

Two things this doc adds that don't exist elsewhere yet: a short, early
check-in survey for founding users (customers 1–10), and the concrete
day-by-day watch plan for a customer's first week. Both build on, and do
not duplicate, the longer pricing-validation survey already drafted in
`docs/PRICING_OFFER_VALIDATION.md` §3a — that survey is timed *later*
(after 2 weeks + one billing cycle) and answers a different question
(willingness to pay at $19.99). This doc's survey is timed *earlier* (after
the 3rd session) and answers a narrower one: what would we actually change
based on how a founding user is really using it, this week.

Vocabulary rules apply absolutely (`tests/test_customer_language.py` /
`tests/test_content_language.py`): no plus-sign EV, no "true" price/line, no
"edge" as a customer noun, no guaranteed outcome, no invented win
probability, `late_move` never called "CLV."

---

## 1. Founding-user survey (max 7 questions, after the 3rd session)

**Trigger:** the user's 3rd product session — not day-count. A "session" is
a distinct visit that includes at least a `PAGE_VIEW` on `/today` or a
`BET_CHECK_RUN`, per the same events `src/appstate/onboarding.py` and
`src/appstate/events.py` already record; do not send it after 3 calendar
days if the user has only opened the app once. Sending it before someone
has real usage to reflect on produces noise, not signal — the whole point
of tying it to session count instead of days.

**Why this doesn't reuse §3a's survey outright:** §3a is deliberately timed
for a pricing/willingness-to-pay decision that needs a full billing cycle to
mean anything. Waiting that long to hear "the case-against text on Bet
Check confused me" or "I didn't notice the price-improvement framing" from
a founding user is too slow for a two-person team that could fix it this
week. This survey exists to catch *that* kind of signal early; §3a still
runs later for the pricing decision specifically — a user may see both.

**The 7 questions:**

1. **First real reaction:** "What was your first reaction the first time
   you ran a Bet Check?" (open text) — the rawest signal available, asked
   before it fades.
2. **Confusion check:** "Was anything on the Bet Check screen confusing, or
   did you trust every number you saw?" (open text) — direct probe for a
   copy or trust-framing bug, not a satisfaction score.
3. **Comparison anchor:** "What are you using instead of, or alongside,
   this right now?" (open text) — same "10-tab problem" probe
   `docs/PRICING_OFFER_VALIDATION.md` §3a uses, asked at week one instead of
   week three.
4. **What would you change, first thing:** "If you could change one thing
   about it this week, what would it be?" (open text) — the question this
   survey is actually built around; answers here should map directly to a
   real backlog item, not get filed away.
5. **Did you notice the honesty framing:** "Did you notice anything in the
   app about research we've tried that didn't work?" (yes/no + optional
   open text) — checks whether the published-nulls framing is actually
   landing, not just present.
6. **Stall check:** "Is there anything you tried to do that didn't work the
   way you expected?" (open text, optional) — a second, softer pass at bug
   surfacing beyond what support tickets alone catch.
7. **(Optional) Would you tell a friend:** "Would you tell a friend who bets
   MLB about this? Why or why not?" (open text, optional) — a lightweight
   qualitative read, not a formal NPS instrument (no 0–10 score — a beta
   cohort this small doesn't need one, and a number here risks reading as a
   fabricated confidence metric this product's own vocabulary rules
   disallow elsewhere).

**How it's sent:** by hand (email), same interim-manual pattern every other
customer-facing send in this beta uses until a sender is chosen
(`docs/RETENTION_EMAILS.md`'s "SENDER INFRASTRUCTURE: NOT BUILT" gap
applies here too — this is not a new gap, just another thing waiting on
that same decision).

**How answers get used:** every answer to question 4 gets read against the
current backlog before the week is out — not batched into a quarterly
review. Question 2/5/6 answers that reveal a real confusion or bug route
through the bug-intake triage in
`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §7, same as a support ticket would.
Do not treat a single founding user's answer as a mandate to change
anything — a cohort of 1–10 people is a set of individual signals, not a
statistically meaningful preference, and should be reported as such if
escalated (name the respondent count, never imply consensus from n=1).

---

## 2. Days 1–7 watch plan (per new paying customer)

Builds directly on the events already wired
(`src/appstate/onboarding.py`'s four steps, `src/appstate/events.py`,
`GET /admin/funnel`) — no new instrumentation, just a schedule for looking
at what already exists.

| Day | What to check | What "on track" looks like | What's a risk signal |
|---|---|---|---|
| 0 (signup/activation day) | `GET /onboarding` for this user: `token_redeemed` | Fires within minutes of the token being sent/redeemed | Token sent, `token_redeemed` still false after a few hours — likely a lost/undelivered token; see `docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §1b's failure table |
| 0–1 | `first_today_view` | Fires same day as `token_redeemed` | A redeemed token with no `/today` view within a day — worth a check-in, not yet an email (too early for the day-3 trigger) |
| 1–3 | `first_bet_check` | Fires within the first couple of sessions | Still incomplete by day 3 — this is exactly the day-3 email's trigger condition (`docs/RETENTION_EMAILS.md` §2); let that email do the nudge, don't manually reach out first unless they've already contacted support |
| 3 | Day-3 email fires (or is sent by hand — see the sender-infrastructure gap) | Sent once, only if `first_bet_check` AND `first_saved_bet` are both still incomplete | N/A — this is the intervention itself, not a signal to interpret |
| 3–7 | `first_saved_bet` | Fires at some point this week for an engaged user | Never fires — treated as a stickiness signal to watch, not a week-one failure (`docs/FIRST_CUSTOMER_PLAYBOOK.md` §7's own framing: `bet_saved` is a longer-horizon proxy, not a week-one milestone) |
| Ongoing | `GET /admin/support` for this user's messages | Quiet, or resolved same-day per the P0/P1/P2 SLAs | Any P0 (data-wrong, billing, security) from a founding user in week one — treat as urgent regardless of how small the cohort is; a bad first week from customer #1 is disproportionately costly to the product's reputation with everyone who hears about it next |
| Session 3 | Founding-user survey (§1 above) | Sent once real usage exists to reflect on | N/A — trigger, not a signal |

**Activation, defined for this doc's purposes:** reaching `first_bet_check`
within the first few days — this matches `docs/FIRST_CUSTOMER_PLAYBOOK.md`
§7's own "definition of success" (a completed charge with no product usage
is a weaker signal than one that reaches a real Bet Check). A customer who
pays and never runs one by day 7 is not yet a churn case, but is the
specific profile the day-3 email and this watch plan exist to catch before
it becomes one.

**Churn risk, defined for this doc's purposes:** paid, `token_redeemed` but
no `first_bet_check` by day 7 (day-3 email already fired and didn't move
them), or any unresolved P0/P1 support message older than its SLA window
(`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §3). Neither condition alone proves
someone will cancel — both are the honest, checkable signals available at
this cohort size, reported as what they are (a risk flag) rather than a
prediction.

**What this section will not do:** treat a quiet week from a single
customer as evidence of anything at cohort scale.
`docs/FIRST_CUSTOMER_PLAYBOOK.md` §7's own caution applies here without
modification — a one-week window, or a cohort under `docs/PRICING_OFFER_VALIDATION.md`
§3c's N=50 threshold, is not a signal that generalizes; it's a thing to
watch and respond to for that one person.

---

## Open items for Brey (not resolved by this doc)

- Sender infrastructure for the survey email is the same unresolved
  decision `docs/RETENTION_EMAILS.md` flags — this doc's survey is sent by
  hand until that lands.
- This survey and §3a's pricing-validation survey will overlap in content
  for any user who reaches both triggers (session 3, then 2 weeks +
  billing cycle) — that overlap is intentional (different questions, same
  person) and should not be collapsed into one send; keep them separate so
  the early one stays fast and the later one stays rigorous.
