# First Customer Playbook

Working brand: Linehound (temporary, pending trademark/domain clearance —
Brey 2026-09-01, same as every other content doc). `[PRICE]`/`[N]` merge
fields are used exactly where the source docs use them below — they are
pending Brey's decision in `docs/PRICING_OFFER_VALIDATION.md`'s BREY
DECISION BLOCK and must not be filled in before that lands.

This is the one document Brey executes end to end to land the first real,
paying customer this week. It does not repeat the content already drafted
elsewhere — it sequences and links it. Where a number is quoted from another
doc it is cited the same way that doc cites it; every number this document
states outright is either sourced or marked `ASSUMPTION`.

**Vocabulary rules apply absolutely, everywhere in this document and
everything it tells Brey to send**: no plus-sign EV framing, no claim of a
"true" price/line/odds, no "edge" as a customer-facing noun, no guaranteed
outcome, no sure-thing framing, no invented win probability, no self-funding
claim about the subscription cost, no comparing price-improvement dollars to
the subscription price, no naming a book as having "the" best price, and
`late_move` is never described as CLV. Source: `tests/test_customer_language.py`'s
`HARD_BANNED`/`NEGATION_ONLY` lists, extended over this file by
`tests/test_content_language.py` (see EVIDENCE RULES at the bottom).

---

## 1. Day-by-day plan: credentials arrive → first payment

Hour-level from the moment Brey has the one credential
`deploy/DEPLOY_RUNBOOK.md` Step 0 requires (a Fly.io app-scoped deploy
token). Everything before that point is inert — see that runbook's own
framing.

**Day 0 (credential arrives, ~2–3 hours of active work):**
1. Run `deploy/DEPLOY_RUNBOOK.md` Steps 1a–1g: create the Fly app, the
   volume, set `APP_ADMIN_TOKEN`, deploy `deploy/fly.staging.toml`. (~45 min,
   mostly deploy wait time.)
2. Step 2: `bash scripts/smoke_api.sh` against the live staging URL
   (`BASE=https://<app>.fly.dev`). This must go green before anything below
   happens — a red smoke test here is a stop, not a note. (~10 min.)
3. Run `scripts/funnel_smoke.sh` against the same staging config if Stripe
   *test-mode* keys (`sk_test_...`) are already set per Step 1e's optional
   block — this proves checkout → webhook → funnel end to end before a real
   card touches it. If Stripe keys aren't set yet, do this after Step 1e is
   redone with them, still same day. (~15 min.)
4. **Brey does one real test-mode purchase himself — the dry run.** Using
   Stripe test-mode card `4242 4242 4242 4242`, any future expiry/CVC, walk
   the actual customer path: landing → signup → checkout → `GET
   /signup/complete` token → paste token into the app → confirm the app
   loads Today, a Bet Check runs, and `GET /admin/funnel` shows
   `checkout_started`/`checkout_completed` incrementing. This is not the
   smoke script — it's Brey's own eyes on the exact screens a stranger will
   see. Any friction found here (confusing copy, a broken step, a scary
   error) gets fixed before Day 1's outreach, full stop.
5. Wire `scripts/monitor_remote.sh` against the staging URL (Step 3 of the
   runbook) so a break during outreach shows up without Brey refreshing a
   tab.

**Day 1 (first outreach batch, ~1–2 hours):**
1. Finish the beta recruitment target list (§2) — at minimum the first 15–20
   rows.
2. Send the first 5–8 disclosed-builder DMs from
   `docs/ACQUISITION_ASSETS.md` §1 (persona-matched scripts), using the real
   `[PRICE]`/`[N]` values only once Brey has made that decision (§4 below) —
   until then, send with the honest-beta framing and no price mentioned, or
   hold outreach until the price decision lands, whichever Brey prefers.
3. Do NOT batch-post to Reddit/Discord yet — one disclosed post per
   community, staggered (§5), not fired all at once with DMs.

**Day 2–3 (respond, iterate, first conversions):**
1. Answer every DM reply same-day — `docs/ACQUISITION_ASSETS.md`'s own
   posting discipline ("answer every skeptical reply for real") applies to
   DMs too.
2. Check `GET /admin/funnel` daily (§7) — watch `signup_started` →
   `checkout_started` conversion specifically; a big drop there before any
   real traffic volume is a checkout-flow bug, not a messaging problem.
3. Post the first social item (§5 sequence, post 1 of the X thread or the
   subreddit post — not both same day).
4. Every new paying customer gets the personal-touch checklist (§6)
   immediately, not batched.

**Day 4–5 (second wave, watch retention signals):**
1. Second outreach batch (next 5–8 DMs) once Day 1's batch has had time to
   reply or go quiet (2–3 days is reasonable before considering a DM a
   non-response).
2. Continue the social sequence (§5).
3. Day-3 check-in emails (`docs/RETENTION_EMAILS.md` §2) start firing
   automatically for anyone who redeemed an invite/token and hasn't run a
   Bet Check or saved a bet — confirm this is actually wired (see §6's
   "SENDER INFRASTRUCTURE: NOT BUILT" caveat below) or send it by hand.

**Success checkpoint for the week:** see §7's definition, not a specific day
— this plan does not promise the first payment lands by a specific hour,
because no acquisition-rate data exists yet (see §2's numbers section).

---

## 2. Beta recruitment list methodology

No scraping, no automation, no bots — every contact below is Brey (or
whoever runs outreach) reading a real post/thread and replying or DMing as
themselves, disclosing authorship, per `docs/ACQUISITION_ASSETS.md`'s
standing rule ("no astroturf playbook of any kind").

### Where the personas actually are

From `docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md`'s own acquisition-channel
fields (most are `[INFERENCE]` or `UNKNOWN` — flagged as such there, and
flagged again here rather than dressed up as confirmed):

| Persona | Where (source) | Confidence |
|---|---|---|
| 1 — Casual serious bettor | r/sportsbook, r/sportsbetting (App Store search/word of mouth also named, but not a place to *find* people) | `[INFERENCE]` |
| 3 — Prop-heavy bettor | Prop-betting content on X/Twitter, Props.Cash/LineMate's own user base described as including "content creators" | `[INFERENCE]` |
| 5 — Sharp-leaning bettor | Discord/forum communities around OddsJam, Unabated, RebelBetting (their own education/community framing) | `[INFERENCE]` — PERSONAS.md notes Reddit (where this group "most visibly organizes") was unreachable in that research |
| 6 — Content creator | Betting-adjacent X accounts, prop-content creators | `[INFERENCE]` |
| 7 — New bettor wanting guidance | "how do I get started" threads/posts; PlayerProps.ai's Discord (19,000+ members) is the one *evidenced* community for this persona | `[EVIDENCE]` for the PlayerProps.ai community existing; `[INFERENCE]` that our target bettors are reachable there without being an undisclosed competitor pitch inside someone else's community |

No acquisition-channel evidence exists at all for personas 2, 4, 8
(`PERSONAS.md`'s own cross-persona note) — do not improvise a channel for
them this week.

**Specific communities to check current posting rules for before using**
(names only — `docs/ACQUISITION_ASSETS.md`'s own open item flags that no
community's current self-promo rule was verified in that research):
r/sportsbook, r/sportsbetting (general, persona 1); r/dfsports (persona 3,
props-adjacent); betting-tool Discords with a `#self-promo` channel
(OddsJam/Unabated/RebelBetting-adjacent communities, persona 5) — check each
server's own rules, not assumed from another server. Every one of these
requires verifying the current rule at post time; communities change theirs.

### Disclosure rules (transparent-builder framing only)

Exactly `docs/ACQUISITION_ASSETS.md`'s standing rule, restated as the
operational checklist:
- Post/DM as Brey's real identity (or whoever's), never a sock puppet or
  "satisfied customer" framing.
- State "I built this" / "this is my product, not a review" in the first
  sentence a stranger reads, not buried below the pitch.
- Where a community's rule requires explicit self-promo disclosure, that
  disclosure is written into the post text itself — see
  `docs/ACQUISITION_ASSETS.md` §2's exact wording.
- No incentivized upvotes/replies, no cross-posting identical text across
  communities, no coordinated "show support" asks.
- Answer every skeptical reply for real, including the ones that land.

### Target list template

Track outreach in a simple table (spreadsheet or plain markdown — no tool
recommendation here, use whatever Brey already has open):

| source | persona fit | contact route | status |
|---|---|---|---|
| e.g. "r/sportsbook thread, [url], posted [date]" | 1 / 3 / 5 / 6 / 7 (pick one — see PERSONAS.md) | DM / disclosed post reply / Discord DM | not contacted / DM sent / replied / invited / declined / converted |

Populate the first 15–20 rows by reading real threads/posts matching the
persona signals PERSONAS.md and `docs/COMPETITIVE_INTELLIGENCE/CUSTOMER_PAIN.md`
describe (e.g. persona 1: someone comparing a paid picks app to ESPN;
persona 3: someone discussing rolling-window hit rates) — not by searching
for "MLB betting" broadly, which will not surface persona-matched people.

### Realistic first-week numbers (cited, or marked assumption)

- **No acquisition-rate or conversion-rate evidence exists for this
  product** — `docs/PRICING_OFFER_VALIDATION.md` §3c states this directly:
  "no user-volume or unit-economics model exists yet," and sets its own
  beta-cohort checkpoint (N=50 paying users or 8 weeks) as an explicit
  `ASSUMPTION`, not an evidenced minimum.
- **Realistic first-week target: `ASSUMPTION` — 15–20 disclosed outreach
  contacts, 1–3 replies with real interest, 0–2 conversions to a paying
  customer in week one.** This range is not derived from any measured
  conversion rate for this product or channel (none exists); it is a
  conservative, unhedged guess sized so a single "no" from a stranger this
  week is informative, not a failure signal — consistent with
  `docs/PRICING_OFFER_VALIDATION.md` §3c's own framing for why $19.99 is
  priced to make a "no" cheap and honest to read.
- Do not treat a slow first week as evidence the product doesn't work —
  `docs/PRICING_OFFER_VALIDATION.md`'s decision rule (§3c) only kicks in at
  N=50 or 8 weeks; a handful of days of outreach is far short of that
  threshold either way.

---

## 3. Demo flow script (3 minutes)

**Setup:** pick a real MLB game from today's actual slate (whatever `GET
/today` returns live) — never a hypothetical or made-up matchup. Have the
app open to Today before starting.

**0:00–0:30 — Today.** "This is today's MLB slate, pulled fresh — one row
per game, and if a market isn't priced yet for a game, it says so instead of
guessing." Point at the timestamp on a price. (Source:
`docs/CONTENT_LANDING.md` §2 "Today.")

**0:30–2:00 — Bet Check, real example.** Open a real game, pick a real side
someone might actually consider. Run Bet Check with a real quoted price.
Walk through, on-screen, exactly this and nothing more:
- The best price currently quoted for that side.
- The market-implied consensus shown *separately* — say the words "this is
  not a prediction, it's the market's own implied number, de-vigged."
- If a second book is quoted at a better number for the same bet, show the
  price-improvement framing verbatim from
  `docs/CONTENT_LANDING.md` §4's calculator callout: "if this bet wins, the
  better price pays more; if it loses, both lose the same stake — the
  difference is $0." Never skip the losing branch.
- Point at the honest case-for/case-against text, including saying out loud
  if it shows "no significant counterargument found" — that's a real
  product state, not a placeholder.

**2:00–2:45 — the honesty story.** "We ran 25 pre-registered research ideas
against real MLB games — 35 counting every registered detector variant.
Zero survived our own falsification tests. One looked real at first —
+8.49pp over 249 selections — until we ran the checks we'd committed to in
advance and it fell apart. We published that too." (Source:
`docs/CONTENT_LANDING.md` §3, cited there to `docs/RESEARCH_CATALOGUE.md`.)
Point out the `recommendation` field is permanently empty — "that's a rule,
not a gap we're filling later."

**2:45–3:00 — close.** "MLB only, private beta. No predictions, no picks —
just real prices, the real consensus, and an honest record of what we've
tried and killed." Offer the invite.

### Vocabulary rules for the live demo (what NOT to say)

Say the price-improvement framing exactly as scripted above, both branches,
same weight. Never say: "edge," "this is a good bet," "you should take
this," any guaranteed outcome, a claim of a "true" price or line, any
self-funding claim about the subscription, or "CLV" for a late-move
observation — and never name a specific book as having "the" best price
(63–79% of observed instants are ties across books — `docs/CONTENT_LANDING.md`
§4 small print). If a prospect asks "so
what should I bet," use the canned answer from
`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §5 verbatim: "This tool doesn't make
picks or recommendations — it's built to show you the support and the
counterargument for a bet you're already looking at, so you can decide with
the full picture. The decision's always yours."

### Objection handling

From `docs/COMPETITIVE_INTELLIGENCE/CUSTOMER_PAIN.md`'s evidenced cross-
product churn/skepticism themes:

**"Isn't this just another tout service?"**
> No — a tout sells you a pick. This has no pick to sell: the
> `recommendation` field is permanently empty, by design, because there's no
> validated prediction model behind it. What you get instead is the actual
> price, the market's own implied number, and an honest case for and against
> whatever you're already considering — including saying plainly when there
> isn't a real counterargument to show you.
<!-- source: docs/API_CONTRACTS.md ("recommendation" permanently null);
docs/CONTENT_LANDING.md §3 -->

**"Do you promise a result, or that this will work?"**
> No — nothing here is guaranteed, and I'd be lying if I said otherwise. We tested 25 research ideas (35
> counting every variant) against real games and zero survived our own
> falsification tests — that's published, not hidden. Nothing here promises
> a result or a win probability; that's a permanent rule in the product, not
> something we haven't gotten to yet.
<!-- source: docs/RESEARCH_CATALOGUE.md; docs/CONTENT_LANDING.md §3 -->

**"Why would I trust a tool built by someone with zero winning ideas so
far?"** — use `docs/ACQUISITION_ASSETS.md` §2's exact framing: "you're
trusting the process (published nulls, pre-registered tests), not a track
record, because there isn't one yet."

**"Every picks app I've used is no better than a coin flip"** (the single
most standardized complaint phrase across the corpus — Rithmm, Outlier,
BetQL, PlayerProps.ai, per `CUSTOMER_PAIN.md` §4): agree with them, don't
argue. "That's exactly why this doesn't make picks. If it did, you'd be
right to distrust it the same way — nothing here has cleared the bar we'd
need to clear before shipping a prediction."

---

## 4. Positioning one-liners + free-month vs. founding-price

One-liners (from `docs/PRICING_OFFER_VALIDATION.md` §1's founding-member
framing and `docs/ACQUISITION_ASSETS.md` §3's one-pager copy):

- "[PRICE]/mo, locked for as long as your subscription stays active — even
  after the public price moves to $29.99/mo."
- "One tier, everything included — no ladder to climb, because there's
  nothing to segment by yet."
- "This isn't a discount to make an overpriced product look cheap. It's
  priced for what it actually is right now: an unproven, single-sport beta,
  asked of real strangers for the first time."
- "Cancel anytime, one click, no retention flow. Billed in error? Full
  refund within 7 days, no questions asked."

**Recommendation: offer the founding price ([PRICE]/mo locked), not a free
month, to every beta prospect this week.** Justification:
`docs/PRICING_OFFER_VALIDATION.md` §3c's own decision framework needs a
*real charge* to generate a willingness-to-pay signal — a free month
generates usage data but not the signal that actually matters this week
(would a stranger pay). §1 of that same doc states the founding-member lock
is deliberately "a real price lock... not a vague founding-member badge,"
and a free month undercuts exactly the "genuinely below the $20-35/mo band,
earned by being early" framing §2 relies on. Reserve a free month, if ever,
for a specific person Brey wants product feedback from more than revenue
signal from (e.g. a content creator persona whose feedback is worth more
than $19.99) — not as the default offer.

This recommendation depends on Brey's price decision actually landing
(`docs/PRICING_OFFER_VALIDATION.md`'s BREY DECISION BLOCK, option (a) is
that doc's own recommendation: $19.99/mo, $239/yr, founding-member lock) —
until it does, `[PRICE]`/`[N]` stay merge fields, not real numbers, in every
outreach script.

---

## 5. Social launch sequence (X + one subreddit)

Ordered, referencing `docs/ACQUISITION_ASSETS.md`'s gated copy verbatim — no
new claims invented here.

1. **Day 1 or 2: X thread, post 1 only** — the hook post from
   `docs/ACQUISITION_ASSETS.md` §4, item 1 ("We ran 25 pre-registered
   betting research ideas against real MLB games... Zero survived"). Post as
   a real account, disclosing authorship in the first post.
2. **Same day, later, or next day: X thread, remaining posts 2–10** — the
   full thread from §4, posted as a continuation, not spread across separate
   days (a thread reads as abandoned if it stalls partway).
3. **1–2 days after the thread: one disclosed subreddit post** — the honest
   pitch from `docs/ACQUISITION_ASSETS.md` §2, posted to whichever single
   subreddit (r/sportsbook or r/sportsbetting) currently permits a disclosed-
   builder self-promo post per its own rules (verify at post time — not
   pre-verified by this doc or `ACQUISITION_ASSETS.md`'s own open item).
   **One community, once** — no cross-posting the identical text.
4. **Ongoing, as replies come in:** answer every reply on both the thread and
   the subreddit post for real, per `ACQUISITION_ASSETS.md`'s posting
   discipline — this matters more to the pitch's credibility than posting
   volume does.
5. **Do not** post the founding-member one-pager (§3 of `ACQUISITION_ASSETS.md`)
   as a standalone social post this week — it's for DM follow-up once
   someone's already expressed interest, not a cold post (its own framing
   assumes the reader already wants in).

No bot amplification, no purchased engagement, no coordinated reply-network
boosting, no incentivized upvotes — `ACQUISITION_ASSETS.md`'s standing rule,
restated because it applies to every item above.

---

## 6. Feedback/onboarding sequence for customers 1–10

**Personal-touch checklist, per new paying customer, immediately (not
batched):**
1. Mint the invite/token by hand (`POST /admin/invites`,
   `docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §1) and send it personally — no
   automated invite-email sender exists yet (`ONBOARDING_SUPPORT_PLAYBOOK.md`
   §1's own flagged gap), so this is a real, individual email from Brey,
   using the token-paste copy that doc specifies.
2. Watch `GET /onboarding` for that user over the next few days — the four
   tracked steps (`token_redeemed`, `first_today_view`, `first_bet_check`,
   `first_saved_bet`) tell you exactly where they are, not a guess
   (`ONBOARDING_SUPPORT_PLAYBOOK.md` §2).
3. If they stall before `first_bet_check`/`first_saved_bet`, that's what the
   day-3 email is for (below) — don't manually nudge before day 3 unless
   they've reached out first.

**Day-3 email:** fires per `docs/RETENTION_EMAILS.md` §2's exact trigger
condition — 3 days after `token_redeemed`, only if `first_bet_check` and
`first_saved_bet` are both still incomplete, sent once. **Caveat:**
`docs/RETENTION_EMAILS.md` §1 flags "SENDER INFRASTRUCTURE: NOT BUILT" as a
Brey decision — if no automated sender exists yet by the time customer 1
hits day 3, send that exact copy by hand rather than skip it; the trigger
condition (check `GET /onboarding` for that user) is checkable manually for
a customer count this small.

**Feedback questions** — use `docs/PRICING_OFFER_VALIDATION.md` §3a's 5
required + 2 optional questions verbatim, timed per that doc's own guidance
(after at least 2 weeks of access and one billing cycle if converted from
free to paid — not day 3, which is onboarding-recovery timing, not
validation-survey timing). Do not shorten or lengthen that survey —
§3a's own note: "low-effort surveys get honest, higher-response answers from
a beta cohort this small."

**How feedback lands:**
- Support replies (`POST /support`) land in `GET /admin/support` — triage
  per `ONBOARDING_SUPPORT_PLAYBOOK.md` §3's P0/P1/P2 table (data-wrong and
  billing jump the queue ahead of arrival order).
- Behavioral willingness signals — `bet_check_run` frequency, `bet_saved` as
  a stickiness proxy, cohort retention — are already wired in
  `src/appstate/events.py` per `docs/PRICING_OFFER_VALIDATION.md` §3b;
  report them only as cohort-wide aggregates (median weekly count, % with
  ≥1 in the last 7 days), never a per-user leaderboard, per that section's
  explicit privacy rule.
- Survey answers (§3a) are the *stated* signal; `bet_check_run`/retention are
  the *behavioral* signal — report disagreement between them rather than
  resolving it by picking one (§3b's own instruction).

---

## 7. First-customer definition of success + funnel metrics to watch

**Definition of success for this week:** one real person, previously
unknown to Brey, completes a real Stripe charge (test-mode dry run in §1
does not count — it must be a stranger's own card) and reaches
`first_bet_check` in `GET /onboarding` within their first few days. A
completed charge with no product usage at all is a weaker signal — it says
"the pitch worked," not "the product works for them" — so both parts matter,
not payment alone.

**Metrics to watch on `GET /admin/funnel`** (`api/funnel.py`):

| Step | What a good early sign looks like | What a bad sign looks like |
|---|---|---|
| `landing_view` → `signup_started` | Some non-zero conversion at all — even one real visitor starting signup this week is meaningful for a cold-start funnel | Zero `signup_started` despite outreach sent — messaging or landing-page friction, not a volume problem |
| `signup_started` → `checkout_started` | Most people who start signup reach checkout | A big drop here specifically flags a signup-form or copy problem, distinguishable from a pricing objection (which would show up later, at checkout → completed) |
| `checkout_started` → `checkout_completed` | Any completion at $19.99 this week, from a stranger | Repeated `checkout_started` with no completions — likely a pricing objection or a checkout bug; check `scripts/funnel_smoke.sh` still passes before assuming it's pricing |
| `checkout_completed` → `invite_redeemed` | Should be ~100% — this is just "did they use the token they were just given" | Any gap here is very likely a friction/support issue (lost token, confusing paste-in-token flow), not a customer-motivation issue |
| `invite_redeemed` → `bet_check_run` (first occurrence) | Reaching this = a real activated user, not just a payment | A customer who pays but never reaches this is the specific case the day-3 email exists for |
| `bet_check_run` → `bet_saved` (first occurrence) | A stickiness signal, not a requirement for "success" this week | Absence isn't itself a failure signal this early — `PRICING_OFFER_VALIDATION.md` §3b treats `bet_saved` as a longer-horizon stickiness proxy, not a week-one milestone |

Each step renders as `0`, never omitted, when nothing happened yet — a
funnel with real zeros in it is more honest than a hidden row (`api/funnel.py`'s
own docstring: "a step with zero events renders as count 0... real
information for a beta this early, not a hole in the data").
`conversion_pct_from_previous` is `None`, never a fabricated percentage,
whenever the previous step's count is itself zero — do not read a `None`
conversion cell as "0%."

**A one-week window is far short of any real signal threshold** —
`docs/PRICING_OFFER_VALIDATION.md` §3c's own decision rule doesn't trigger
until N=50 paying users or 8 weeks. Nothing in this section should be read
as "if X isn't true by Friday, the product doesn't work" — it's a set of
things to watch, not a pass/fail gate this early.

---

## Test coverage for this document

`tests/test_content_language.py` is extended to scan this file for the same
banned/negation-only vocabulary it already applies to `CONTENT_LANDING.md`,
`RETENTION_EMAILS.md`, and `ACQUISITION_ASSETS.md` — see that file's
`FIRST_CUSTOMER_PLAYBOOK_FILE` addition.

## Open items for Brey (not resolved by this doc)

- `[PRICE]`/`[N]` are pending the BREY DECISION BLOCK in
  `docs/PRICING_OFFER_VALIDATION.md` — do not fill either into a sent
  outreach message before that decision lands.
- Which specific subreddits/Discords currently permit a disclosed-builder
  post, and their exact rules, is not verified here or in
  `ACQUISITION_ASSETS.md` — verify at post time.
- No automated invite-email or day-3-email sender exists
  (`RETENTION_EMAILS.md` §1's flagged Brey decision) — §6 above assumes
  manual sending is the fallback for a customer count this small; revisit if
  volume exceeds what manual sending can keep up with.
- Product name (`LINEHOUND`) is a working placeholder pending trademark/
  domain clearance — every mention here needs the same global find/replace
  every other content doc already carries as an open item.
