# First-Customer / Growth Package

Working brand: LINEHOUND (temporary, pending trademark/domain clearance).
Commercial facts per `design/linehound-v1/HANDOFF_README.md` (frozen design)
and this task's own INPUTS: **$19.99/mo, Founding Access, cancel anytime; 3
free Bet Checks TOTAL, lifetime (not per day); MLB only.** These are treated
as settled, not merge fields — `docs/PRICING_OFFER_VALIDATION.md`'s BREY
DECISION BLOCK option (a) is what the design already shipped.

This doc does not repeat `docs/FIRST_CUSTOMER_PLAYBOOK.md`,
`docs/ACQUISITION_ASSETS.md`, `docs/CONTENT_LANDING.md`, or
`docs/PRICING_OFFER_VALIDATION.md` — it sequences a week of solo-founder
execution on top of them and adds the pieces those docs don't cover (channel
prioritization, a 10-minute demo script, message variants by warmth, a
content backlog, a referral concept, and objection responses). Every number
stated outright below is cited to its source or marked `ASSUMPTION`.
Vocabulary rules are identical to every other content doc in this repo (see
"Vocabulary rules" note at the bottom) — no EV/edge language for price
improvement, no claim of a "true" price or line, no win probabilities, no guaranteed wins, no
implying picks exist.

---

## 1. Founding-beta acquisition plan — this week, solo founder

Sequencing rationale: disclosed 1:1 outreach first (highest trust, lowest
reach, fastest signal on messaging), then one staggered social post per
channel (medium trust, medium reach), never a paid channel this week (see
§8 — most paid gambling-adjacent ad channels require certification/review
Brey hasn't started).

**Day 0** — infra check per `FIRST_CUSTOMER_PLAYBOOK.md` §1 (smoke test,
funnel smoke, Brey's own test-mode dry run). Do not start outreach until
this is green — sending strangers to a broken checkout burns the only
first impression each of them gets.

**Day 1 (~1–2 hrs):**
1. Build the first 15–20 rows of the prospect list (§2 below).
2. Send 5–8 disclosed DMs (persona-matched scripts, `ACQUISITION_ASSETS.md`
   §1, real $19.99 price now that it's settled).
3. Do not post to Reddit/Discord/X yet — one disclosed post per community,
   staggered, not fired same day as DMs (`FIRST_CUSTOMER_PLAYBOOK.md` §1).

**Day 2:**
1. Answer every DM reply same-day.
2. Check `GET /admin/funnel` — watch `signup_started` → `checkout_started`
   specifically.
3. Post X thread, item 1 only (the hook post, §5 below / `ACQUISITION_ASSETS.md`
   §4 item 1).

**Day 3:**
1. Post the rest of the X thread (items 2–10), same thread, not spread
   across more days — a stalled thread reads as abandoned.
2. Continue answering replies.
3. Every new paying customer gets the personal-touch checklist
   (`FIRST_CUSTOMER_PLAYBOOK.md` §6) immediately.

**Day 4:**
1. One disclosed subreddit post (r/sportsbook or r/sportsbetting, whichever
   currently permits a disclosed builder post — verify at post time).
2. Second DM batch (next 5–8 prospects).

**Day 5:**
1. Answer replies on both the thread and the subreddit post.
2. Day-3 check-in email for anyone who redeemed an invite and hasn't run a
   Bet Check or saved a bet (`RETENTION_EMAILS.md` §2) — send by hand if the
   automated sender isn't built yet (flagged gap, same doc §1).
3. Review the week: funnel numbers (§7 of `FIRST_CUSTOMER_PLAYBOOK.md`),
   which outreach messages got real replies vs. silence, which objections
   came up (§7 below) and whether the scripted responses actually landed.

**Order of channels, and why:** disclosed DM > staggered single-community
post > standing content backlog (§5) as ongoing background, never front-
loaded. Reasoning: a DM is reversible if the messaging is off (fix it before
the next one); a public post is not — it's read by everyone who sees it,
including people who never reply. Get the DM messaging right on 5–8 people
before it's public.

**Realistic numbers**: same `ASSUMPTION` as `FIRST_CUSTOMER_PLAYBOOK.md` §2 —
15–20 disclosed contacts, 1–3 real-interest replies, 0–2 conversions in week
one. No acquisition-rate evidence exists for this product or channel; do not
read a quiet week as proof the product doesn't work (that decision rule
doesn't trigger until N=50 or 8 weeks, `PRICING_OFFER_VALIDATION.md` §3c).

---

## 2. First 25–50 prospect methodology

**No scraping, no automation, no bots.** Every row is a real post/thread
Brey reads, then a disclosed reply or DM sent as himself. This is the same
standing rule `ACQUISITION_ASSETS.md` states ("no astroturf playbook of any
kind") — repeated here because it governs how the list gets built, not just
how it gets messaged.

### Where to look (real, named venues)

From `docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md`'s own acquisition-channel
fields — most are `[INFERENCE]`, flagged as such there and here, not
dressed up as confirmed:

| Persona | Venue | Confidence | What to look for there |
|---|---|---|---|
| 1 — Casual serious bettor | r/sportsbook, r/sportsbetting | `[INFERENCE]` | A post comparing a paid picks app (Rithmm, BetQL, Action Network) unfavorably to free stats, or asking "is X worth it" |
| 3 — Prop-heavy bettor | r/dfsports; prop-betting X accounts; Props.Cash/LineMate's own visible user base | `[INFERENCE]` | Someone discussing a rolling-window hit-rate stat, or complaining a tracker doesn't flag small samples |
| 5 — Sharp-leaning bettor | Discord/forum communities built around OddsJam, Unabated, RebelBetting (their own education/community framing) | `[INFERENCE]` — Reddit was unreachable for this persona in the underlying research | Cross-book price comparison talk, complaints about being limited by books |
| 6 — Content creator | Betting-adjacent X accounts, prop-content creators | `[INFERENCE]` | Someone who's said they need a citable, checkable number rather than a vibe |
| 7 — New bettor wanting guidance | "how do I get started" threads; PlayerProps.ai's Discord (19,000+ members, the one *evidenced* community here) | `[EVIDENCE]` the community exists; `[INFERENCE]` our target users are reachable there without reading as an undisclosed competitor pitch | Explicit distrust of black-box picks apps |

No acquisition-channel evidence exists for personas 2, 4, 8
(`PERSONAS.md`'s own cross-persona note) — do not improvise a venue for
them; leave those rows for later, once real evidence exists.

**Verify each community's current self-promo rule before posting or DMing
into it** — none of this research pre-verified current rules
(`ACQUISITION_ASSETS.md`'s own flagged open item); rules change and vary by
server/subreddit.

### Qualification criteria (what makes a row worth adding)

A prospect qualifies if the real post/comment shows at least one of:
- Actively comparing paid picks/stats tools, or asking whether one is
  "worth it" (persona 1 signal).
- Discussing a specific hit-rate or rolling-window stat, or complaining a
  tool doesn't show sample size (persona 3 signal).
- Discussing cross-book price comparison, arbitrage-adjacent behavior, or
  getting limited by a book (persona 5 signal).
- Explicitly asking for citable/checkable numbers for content they're
  producing (persona 6 signal).
- Explicitly distrusting black-box picks or asking "how do I even start"
  (persona 7 signal).

Do **not** add a row just because someone said "MLB" or "betting" broadly —
that's not persona-matched and won't convert at a rate worth the outreach
time (`FIRST_CUSTOMER_PLAYBOOK.md` §2 makes the same point).

### Tracking sheet structure

One row per prospect, plain spreadsheet or markdown table — whatever Brey
already has open, no new tool needed:

| Column | Purpose |
|---|---|
| `source` | The actual post/thread, e.g. "r/sportsbook thread, [url], posted [date]" |
| `persona` | 1 / 3 / 5 / 6 / 7 — pick one, per `PERSONAS.md` |
| `qualifying_signal` | One line: what they actually said that matched a criterion above |
| `contact_route` | DM / disclosed reply / Discord DM |
| `date_contacted` | |
| `status` | not contacted / DM sent / replied / invited / declined / converted |
| `objection_raised` | If any — feeds §7 below; leave blank if none yet |
| `notes` | Anything worth remembering before the next touch |

Target: 15–20 rows before Day 1 outreach starts, growing to 25–50 across
the week as replies generate more leads (e.g., someone in a Discord thread
who reacts to the disclosed post becomes a new row, not just the original
poster).

---

## 3. Founder-led demo script — 10 minutes

Same demo the design was built around
(`design/linehound-v1/HANDOFF_README.md`: Gameday, Bet Check, price board),
extended from `FIRST_CUSTOMER_PLAYBOOK.md` §3's 3-minute version into a full
10-minute walkthrough for a live 1:1 call or screen-share, not a cold post.
**Setup:** pick a real MLB game from today's actual slate — never a
hypothetical matchup.

**0:00–1:00 — Landing.** Show the landing page. Say what the product is in
one sentence before anything else: "This checks a bet you're already
looking at — the actual price, the market's own implied number, and an
honest case for and against it. It doesn't predict winners and it doesn't
sell picks." State the free offer plainly: 3 free Bet Checks, total,
lifetime — not per day, not a trial that auto-charges.

**1:00–2:30 — Free Bet Check, live.** Have the prospect name a real bet
they'd actually consider today (or pick one together from the slate). Run
it live as one of their 3 free checks. Show:
- The best price currently quoted for that side.
- The market-implied consensus shown *separately* — say the words "this is
  not a prediction, it's the market's own implied number, de-vigged" —
  never a claim of a "true" price or line, never a "market's true-read"
  style phrasing.
- If a second book beats it, the two-branch framing verbatim: "if this bet
  wins, the better price pays more; if it loses, both lose the same stake —
  the difference is $0." Never skip the losing branch.
- The case-for/case-against text, including saying out loud if it shows "no
  significant counterargument found" — a real product state, not a gap.

**2:30–4:30 — Gameday.** Walk today's slate view: one row per game, price
age shown honestly, "unavailable" instead of a guessed number when a market
isn't priced yet. Point at a timestamp. This is where the prospect sees the
product handles *every* game today, not a cherry-picked example.

**4:30–6:00 — Price board.** Show the full board — quoted prices across
books for the slate, timestamped. Say the small-print rule out loud if it
comes up naturally: "we don't name one book as having the best price — most
of the time more than one book ties for it, so naming one would be
arbitrary." Never call the price-improvement number an edge or an EV.

**6:00–8:00 — The honesty pitch.** "We pre-registered 25 research ideas
against real MLB games — 35 counting every registered detector variant.
Zero survived our own falsification tests. One looked real at first — a
cross-book price-dispersion signal, +8.49 percentage points over 249
selections — until we ran the checks we'd committed to in advance, and it
fell apart: it came almost entirely from one book, didn't replicate season
over season, and reversed right at its own threshold. We killed it and
published the writeup instead of quietly shelving it." (Source:
`docs/RESEARCH_CATALOGUE.md`.) Point at the `recommendation` field being
permanently empty: "that's a rule, not a gap we're filling later — there's
no validated prediction model behind this product."

**8:00–9:00 — the moment they ask "so what do I bet?"** This will come up —
treat it as the actual pitch, not a gap to talk around. Use the canned
answer verbatim (`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §5): "This tool
doesn't make picks or recommendations — it's built to show you the support
and the counterargument for a bet you're already looking at, so you can
decide with the full picture. The decision's always yours." If they push
further: "If picks or a promised result are what you're looking for, this
genuinely isn't the right tool yet — we haven't found anything that clears
our own bar, and we're not going to pretend otherwise to sell a
subscription." (`CONTENT_LANDING.md` §3.)

**9:00–10:00 — the Founding Access ask.** "$19.99/mo, Founding Access,
locked for as long as your subscription stays active — even after the
public price moves. Cancel anytime, one click, no retention flow. You've
already used a free Bet Check — if this is useful for the bets you're
already making, I'd love to have you as one of the first beta subscribers,
and I want your honest feedback more than your money right now." Offer the
signup link. No urgency framing, no countdown, no "only N spots left."

### Vocabulary rules for the live demo

Never say: "edge," "this is a good bet," "you should take this," any
guaranteed outcome, a claim of a "true" price or line, any self-funding
claim about the subscription, "CLV" for a late-move observation, or name a
specific book as having "the" best price.

---

## 4. Outreach messages — DM/short-form and email, 3 variants each

All six messages offer the 3 free Bet Checks; none begs, none uses urgency
language, all disclose authorship in the first sentence a stranger reads.
Vocabulary rules apply identically to every message below.

### DM / short-form (X DM, Reddit DM, Discord DM)

**Cold** (persona-matched stranger, no prior interaction):

> Hey — saw your post about [tool/complaint]. Building something in the
> same space and want to be upfront I'm the one who made it, not a random
> recommendation. It's LINEHOUND — MLB only, private beta. No predictions,
> no picks — it checks a bet you're already considering: the actual price,
> the market's implied consensus, and an honest case for/against. 3 free
> Bet Checks, no card needed, if you want to see it on a real bet today. No
> pressure either way.

**Warm** (someone Brey has actually interacted with in a community — reacted
to their comment, replied in the same thread earlier):

> Hey, following up from [thread/context] — I'm the one building
> LINEHOUND, the MLB price-check tool I mentioned. Since you were
> already talking about [specific thing they said], figured you'd want a
> straight answer rather than a pitch: it doesn't predict winners, it shows
> you the actual price and the honest counterargument for a bet you're
> checking. 3 free Bet Checks, lifetime, no card — try it on tonight's slate
> if you want, and tell me what's wrong with it.

**Referral** (someone referred by an existing beta user — name the referrer
only with that user's permission):

> Hey — [existing user] mentioned you might find this useful, so I wanted to
> reach out directly rather than have them forward a link. I built
> LINEHOUND — MLB price-check tool, no predictions, no picks, just the
> actual price, the market's implied consensus, and an honest case for and
> against a bet you're already looking at. 3 free Bet Checks, no card. Happy
> to answer anything, including why [existing user] is still using it after
> a few weeks if that's useful context.

### Email

**Cold** (found via a public post, no prior contact):

> Subject: Built a price-check tool, not another picks app
>
> Hi [name],
>
> Saw your [post/comment] about [tool/complaint] and wanted to reach out
> directly — I'm the person building LINEHOUND, not a marketer for it.
>
> It's an MLB-only checking tool, private beta: you give it a bet you're
> already considering, and it shows the actual quoted price, the market's
> implied consensus (de-vigged, never called "true"), and an honest case
> for and against — including saying plainly when there's no real
> counterargument to show you. It doesn't predict winners; the
> recommendation field is permanently empty by design.
>
> 3 free Bet Checks, lifetime, no card required. If it's useful for how you
> already bet, [PRICE — currently $19.99/mo] gets Founding Access, locked
> for as long as you stay subscribed. If not, no hard feelings — just
> didn't want to cold-email you and pretend to be anything other than the
> builder asking for a look.
>
> [link]
>
> — Brey

**Warm** (a community member who's engaged with Brey's content or replies
before):

> Subject: The MLB price-check tool from [community] — free look
>
> Hi [name],
>
> You've replied a couple times in [community] when I've mentioned
> LINEHOUND, so figured a direct note beats another public post.
>
> Quick recap since you already know the shape of it: MLB-only, no picks,
> shows the actual price, the market's implied consensus, and an honest
> case for/against a bet you're checking. 3 free Bet Checks if you haven't
> used them yet.
>
> Would genuinely value your read on it, especially anywhere it's wrong or
> confusing — that matters more to me right now than a subscription.
>
> [link]
>
> — Brey

**Referral** (introduced by an existing user):

> Subject: [existing user] thought you'd want to see this
>
> Hi [name],
>
> [Existing user] mentioned you might be interested in LINEHOUND — the
> MLB price-check tool I built. Rather than have them forward a link, I
> wanted to introduce it myself and be straight about what it is: no
> predictions, no picks, just the actual price, the market's implied
> consensus, and an honest case for/against a bet you're checking.
>
> 3 free Bet Checks, lifetime, no card. Happy to answer anything about it,
> including how [existing user] has been using it.
>
> [link]
>
> — Brey

---

## 5. Social/content backlog — 15 post ideas

Each idea is grounded in something the product actually shows today —
real captured price spreads, published research nulls, and sample-size
skepticism — not an invented statistic or engagement number. No idea
implies a pick, an edge, or a win probability.

1. (X) The hook thread: "We ran 25 pre-registered betting research ideas
   against real MLB games (35 counting every variant). Zero survived." —
   full 10-post thread already drafted, `ACQUISITION_ASSETS.md` §4.
2. (X) One post, screenshot of a real game's price board from today's
   slate, captioned with the timestamp and "every price here is exactly
   what we observed, nothing smoothed."
3. (Reddit, r/sportsbook) The disclosed builder pitch, `ACQUISITION_ASSETS.md`
   §2, once per community, staggered from the X thread.
4. (X) A single post on the F1 "cross-book dispersion" research writeup:
   +8.49pp over 249 selections looked real, then failed replication —
   walked as its own mini-story, not folded into the big thread.
5. (X) Screenshot of the two-branch price-improvement calculator on a real
   quoted pair, captioned with both branches shown, win and lose, same
   weight — never a single dollar figure alone.
6. (X) A post about the empty `recommendation` field itself: "There's a
   field in our API called `recommendation`. It's permanently null. Here's
   why that's a rule, not a bug."
7. (X) A post quoting the exact tie-rate small print: "On 63–79% of moments
   we've observed, more than one book was tied for the best price — that's
   why we never name 'the' best book."
8. (X) A short post on what "we cannot tell" means as a distinct verdict
   from a tested null — using a real small-sample example from the research
   catalogue, sample size stated plainly.
9. (Reddit, r/dfsports) A disclosed post aimed at persona 3 (prop-heavy
   bettors), leading with the sample-size-transparency gap in existing
   tracking tools, per `ACQUISITION_ASSETS.md` §1 persona 3 script.
10. (X) A "what changed since this morning" screenshot for a real slate —
    lineup/scratch changes, timestamped, captioned "we don't make you
    re-read a stale page."
11. (X) A post responding directly to the most common complaint in the
    space: "Every picks app is a coin flip" — agree with it, explain why
    that's exactly why this product doesn't make picks.
12. (X) A short post walking through what a "de-vigged" number actually
    means and why it's called market-implied consensus, never "true" odds.
13. (X) A post on the beta's Founding Access terms stated plainly: $19.99/mo
    locked for as long as the subscription stays active, no countdown, no
    "spots left" framing — the honesty pitch extended to pricing itself.
14. (X, reply-only) Reserve capacity to answer every skeptical reply on
    items 1–13 for real, including the ones that land — this is listed as
    its own backlog item because it takes as much time as posting and
    matters more to credibility (`ACQUISITION_ASSETS.md`'s posting
    discipline).
15. (X) A post on the 3-free-Bet-Checks offer itself, stated exactly as it
    is — lifetime total, not per day, not an auto-charging trial — framed as
    "here's the actual terms, in one sentence, because the fine print
    shouldn't be where the surprise is."

Posting discipline for all 15: one post per community, no cross-posting
identical text, no bot amplification or purchased engagement, no
incentivized replies/upvotes (`ACQUISITION_ASSETS.md` standing rule).

---

## 6. Referral concept

**Beta-appropriate mechanic (draft, not yet implemented):** an existing
paying beta subscriber who refers a friend who converts to a paying
subscriber gets an extra benefit — either (a) one additional month at the
locked Founding Access price before their next charge, or (b) their own
price lock extended/reconfirmed at $19.99/mo (functionally a no-op if
they're already locked, so (a) is the more concrete option). The referred
friend gets the same public offer everyone gets (3 free Bet Checks, then
$19.99/mo Founding Access) — do not create a "referred users pay less"
tier; that fragments the one-tier pricing decision `PRICING_OFFER_VALIDATION.md`
§1 already made deliberately.

**Why this shape, not a cash referral bounty:** a free-month credit is
denominated in the product itself (an extra month of something the referrer
already values), not cash — this keeps it inside the "no self-funding
claim," "never compare price-improvement dollars to the subscription"
vocabulary discipline that already governs every other customer-facing
number in this product. A cash bounty would also raise a separate set of
questions (1099 reporting at volume, whether a cash-for-referral scheme in
a gambling-adjacent product reads differently to a platform's ToS team than
a product-credit one) that a free-month credit avoids at this scale.

**Flag for review, not asserted as fine:**
- No legal/ToS review of this mechanic has been done. Referral programs in
  a gambling-*adjacent* (not gambling) product sit in a genuinely gray area
  this research didn't clear — `docs/LEGAL_COMPLIANCE_RESEARCH.md` §1
  documents that the product's own classification as an information service
  (not a gambling operator) rests on an inference from secondary sources,
  not a citable holding; a referral incentive doesn't change that
  classification analysis, but it's a new customer-facing mechanic that
  hasn't been checked against it either.
- Check Stripe's own terms on issuing account credits/free periods before
  implementing — this is a billing-mechanics question, not just a legal
  one, and `PRICING_OFFER_VALIDATION.md` §1's "no retention dark pattern"
  standing rule extends naturally to "no confusing credit mechanic" too.
- Do not launch this mechanic this week. It requires product/billing work
  this task's boundaries exclude (no `web/`/`api/` changes) and a legal
  pass this doc cannot substitute for. Treat this section as a concept for
  Brey to evaluate, not a shipped feature.
- No engagement or conversion numbers are invented for this mechanic —
  there is no beta cohort large enough yet to have referral data.

---

## 7. Conversion objections + responses

The first four are lifted verbatim or near-verbatim from
`FIRST_CUSTOMER_PLAYBOOK.md` §3 and `ACQUISITION_ASSETS.md` (cited there);
the remaining six extend to objections those docs don't cover directly
(price-for-one-sport, legality, "why should I trust a solo founder," data
freshness, "why not use free odds sites," and "what happens if I cancel").

**1. "Isn't this just another tout service?"**
> No — a tout sells you a pick. This has no pick to sell: the
> `recommendation` field is permanently empty, by design, because there's no
> validated prediction model behind it. What you get instead is the actual
> price, the market's own implied number, and an honest case for and
> against whatever you're already considering.

**2. "Do you promise a result, or that this will work?"**
> No — nothing here is guaranteed. We tested 25 research ideas (35 counting
> every variant) against real games and zero survived our own falsification
> tests — published, not hidden. That's a permanent rule in the product,
> not something we haven't gotten to yet.

**3. "Why would I trust a tool built by someone with zero winning ideas so
far?"**
> You're trusting the process — published nulls, pre-registered tests — not
> a track record, because there isn't one yet.

**4. "Every picks app I've used is no better than a coin flip."**
> Agree with them, don't argue: "That's exactly why this doesn't make
> picks. If it did, you'd be right to distrust it the same way — nothing
> here has cleared the bar we'd need to clear before shipping a
> prediction."

**5. "$20 a month for MLB only? Why not wait for multi-sport?"**
> Fair — this is MLB-only today because that's where the research and data
> pipeline actually exist; I'm not going to claim coverage I don't have.
> $19.99/mo is a below-market beta price specifically because it's
> single-sport and unproven — the comparable tools with more sports charge
> $25–35/mo. If MLB isn't your main sport, this genuinely isn't for you yet.

**6. "Why pay for this when odds are free everywhere?"**
> The prices themselves are free, that's true — books post them publicly.
> What this does is put them side by side with the market's own implied
> consensus and a timestamp, and check a specific bet you're already
> considering against both, instead of you opening ten tabs to do it
> yourself. If ten tabs is fine for you, you don't need this.

**7. "No picks, no predictions — so what am I actually paying for?"**
> The checking, not a prediction: the actual price, the market's implied
> number shown separately, what changed since you last looked, and an
> honest case for/against a bet you're already leaning toward. If what
> you're looking for is something to tell you who's going to win, this
> isn't it — we haven't found anything that clears our own bar for that.

**8. "Is this legal in my state / legal at all?"**
> This product doesn't take bets or handle any wagered money — it's an
> information tool, and you place any actual bet with your own licensed
> sportsbook, subject to your own state's rules on sports wagering. I'm not
> a lawyer and this isn't legal advice; if you're not sure sports betting
> itself is legal where you are, that's a question for your state's
> gambling regulator, not for me. [This response reflects the product's own
> classification analysis in `docs/LEGAL_COMPLIANCE_RESEARCH.md` §1 — an
> inference from secondary sources, not a legal holding — and is offered as
> an honest founder answer, not as legal advice to the prospect. Any
> stronger legal claim than this needs counsel sign-off first, per that
> doc's own framing.]

**9. "How do I know your prices/data are actually fresh?"**
> Every price on the board carries the exact timestamp of when we last
> observed it, and its age is shown, not hidden. If there's no market
> currently priced for a game, it says "unavailable" instead of guessing —
> that's a rule, not an edge case we forgot to handle.

**10. "What happens if I cancel, or if I get charged by mistake?"**
> Cancel anytime, one click, no retention flow, no "are you sure" loop.
> Your access runs through the period you already paid for. If you're
> billed in error, email within 7 days for a full refund, no questions
> asked. (Source: `docs/PRICING_OFFER_VALIDATION.md` §1's refund/cancel
> draft.)

---

## 8. Compliant acquisition channels — restrictions + organic-first posture

**Organic-first, this week, is the whole plan** — disclosed DM, disclosed
community posts, and the founder's own content backlog (§5). No paid ad
spend is in this week's plan.

**Channel-by-channel restriction notes** (from
`docs/LEGAL_COMPLIANCE_RESEARCH.md` §, cited inline — none of this is
independently re-verified beyond what that doc already found, and none of
it is legal advice):

- **Reddit ads:** gambling-adjacent ad categories carry restrictions on
  most ad platforms generally; this product's own research doesn't resolve
  whether a no-wagering information tool needs certification or falls
  outside scope — do not run Reddit ads this week regardless; organic
  disclosed posts (§1, §5) are the only Reddit presence planned.
- **X ads:** X's Feb 2026 policy update banned gambling products/services,
  explicitly including sports betting, from *paid partnerships*
  (influencer/affiliate/ambassador deals) entirely; standard paid gambling
  ads remain "Restricted Content" requiring preauthorization
  (`LEGAL_COMPLIANCE_RESEARCH.md` §, X row). Organic posting (no paid boost,
  no paid partnership) is unaffected by this and is what §5's backlog uses.
- **Google Ads:** the Gambling and Games policy now requires certification
  for gambling-related ad categories, expanded through multiple 2026
  updates; whether a pure information/price-comparison product with no
  affiliate sportsbook links falls under "gambling-promoting content"
  requiring certification was not conclusively resolved in that research
  pass (`LEGAL_COMPLIANCE_RESEARCH.md` §, Google Ads row) — do not run
  Google Ads this week; if ever considered, read the live policy directly
  and do a test submission first, per that doc's own recommendation.
- **App stores:** not applicable — the product has no native app today.
- **Discord:** no platform-wide ad restriction researched here, but every
  server's own `#self-promo` rule governs, and none was pre-verified — check
  at post time, same discipline as Reddit.

**21+ and responsible-gambling framing, in every outreach message and post
this week:** the product doesn't take bets, but every outreach touchpoint
should read as aimed at adults already engaged in legal sports wagering,
not as recruiting anyone into betting who wasn't already there. Concretely:
- Never target or word a message toward anyone who reads as underage.
- Never frame the product as a way to bet more, bet bigger, or start
  betting if the prospect doesn't already — the honest pitch (checking a
  bet you're already considering) is inherently aimed at existing bettors,
  not at converting non-bettors.
- Where a channel or state context makes it natural (e.g. a state-legality
  objection, §7 item 8), the 21+/legal-wagering-in-your-state framing
  belongs in the actual reply, not as boilerplate stapled onto every
  message — over-inserting it into casual DMs reads as legal-cover theater
  rather than genuine care.

---

## Vocabulary rules

Same rules as every other content doc in this repo, applied to every
message, script, and post above: no plus-sign EV framing, no "true
claim of a "true" price/line or the market's true-read phrasing (say
MARKET-IMPLIED CONSENSUS instead), no "edge"
affirmed as a thing the customer has or gets, no win probability, no
guaranteed outcome, no self-funding claim about the subscription cost, no
comparing price-improvement dollars to the subscription price, no naming a
book as having "the" best price, `late_move` is never called CLV, and no
implying picks or recommendations exist (Ranker gated while Engine 2 is
None). Source: `tests/test_customer_language.py`'s `HARD_BANNED`/
`NEGATION_ONLY` lists. This file is new and is not yet added to
`tests/test_content_language.py`'s scanned-file list (this task's
boundaries exclude editing `tests/`) — vocabulary discipline here is
self-applied, matching the enforced rules exactly rather than relying on
the scanner to catch a slip.

No metrics, follower counts, or testimonials are fabricated anywhere in
this document — every quantitative claim traces to a cited source doc
above, or is explicitly marked `ASSUMPTION`.

---

## Open items for Brey (not resolved by this doc)

- Founding-cohort size (N) for the "first N subscribers" framing is not set
  anywhere in the source docs (`PRICING_OFFER_VALIDATION.md`'s BREY
  DECISION BLOCK covers price, not N explicitly) — this doc doesn't invent
  one; state N when Brey decides it, before using "first N" language in any
  live outreach.
- The referral mechanic (§6) is a concept only — needs legal/ToS review and
  actual product/billing implementation before use; not shippable from this
  task's boundaries.
- Which specific subreddits/Discords currently permit a disclosed-builder
  post, and their exact rules, is not verified here — verify at post time,
  same open item every other doc in this repo already carries.
- Product name (`LINEHOUND`) is a working placeholder pending trademark/
  domain clearance — every mention here needs the same find/replace every
  other content doc already flags.
