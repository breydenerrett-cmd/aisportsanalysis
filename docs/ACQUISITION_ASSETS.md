# Founding-user acquisition assets — DRAFT

Content only, no visual design. Product has no chosen name; every mention
uses **[WORKING TITLE]** per `docs/COMPETITIVE_INTELLIGENCE/NAMING.md`/
`CHECKPOINT.md`. `[PRICE]` is a merge field standing in for the $19.99/mo
beta price `docs/PRICING_OFFER_VALIDATION.md`'s BREY DECISION BLOCK
recommends — **not yet approved by Brey** — so every price mention below
uses the merge field, never a hardcoded number, and every dollar figure
this document does state outright (research counts, sample sizes) is cited
to its source the same way `docs/CONTENT_LANDING.md` cites its own numbers.

Vocabulary rules from `tests/test_customer_language.py` and
`tests/test_content_language.py` apply absolutely, in the same words
`docs/CONTENT_LANDING.md` states them: no plus-sign EV framing, no claim of
a "true" price, no guaranteed outcome, no invented win probability, no
claim that betting is risk-free or that any pick is a certain winner.
Price improvement is described only as line-shopping value — never as an
edge, never as a wagering-expectancy number.

**No astroturf playbook of any kind appears in this document.** Every
script below is written for Brey (or whoever runs outreach) to post or send
**as themselves, disclosing plainly that they built the product** — never
as a satisfied "customer," a sock puppet, a seeded review, or an
undisclosed affiliate link. Where a channel's own rules require self-promo
disclosure (r/sportsbook, most betting Discords), that disclosure is
written into the script itself, not left to the poster's discretion.

---

## 1. DM / outreach scripts by persona

Personas from `docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md`. Each script
below is honest about the product's current state — a private beta, no
demonstrated betting edge, MLB only — because every persona doc's own
evidence base warns that "picks/predictions perceived as no better than
random" is the #1 or #2 churn driver across nine studied products; leading
with an overclaim to this exact audience would recruit the users most
likely to churn on discovering it's untrue.
<!-- source: docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md (personas 1, 3, 5
churn-reason fields; CUSTOMER_PAIN.md cross-product synthesis) -->

### Persona 1 — Casual serious bettor

*Targets: someone who's posted about Rithmm/BetQL/Action Network, or
described comparison-shopping between a paid picks app and free stats.*

> Hey — saw your post about [tool/complaint]. I'm building something in the
> same space, wanted to be upfront that I'm the one who made it, not a
> random recommendation.
>
> It's [WORKING TITLE] — MLB only right now, private beta. It doesn't
> predict winners or give you a pick; it shows you the actual quoted price,
> the market-implied consensus across books, and what changed since you
> last looked, plus the honest case for and against a bet you're
> considering. We've tested [N] betting ideas against real games and
> published every one that failed, which so far is all of them — that's
> intentional, not something to be talked around.
<!-- source: docs/RESEARCH_CATALOGUE.md (25 at detector/spec level, 35 at
registered-hypothesis level; "the commonly-cited '27' double-counts one
family") -->
>
> No pressure either way — if a "no predictions, here's the record"
> product isn't what you're looking for, totally fair. If you want to try
> it, I can send an invite.

### Persona 3 — Prop-heavy bettor

*Targets: someone discussing rolling-window hit rates, Props.Cash, or
LineMate.*

> Hey — I noticed [tool] doesn't flag when a hit-rate stat is on a really
> small sample. I'm building [WORKING TITLE] partly because of exactly
> that gap: every claim we show carries the sample size it's built on, and
> a small sample gets labeled "we cannot tell" instead of a headline
> number that looks confident but isn't.
<!-- source: docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md persona 3 pain
field (Props.Cash/LineMate have "zero sample-size warning... at the code
level"); docs/RESEARCH_CATALOGUE.md ("we cannot tell" as a distinct
verdict) -->
>
> I'm the one who built it — full disclosure, not a neutral recommendation.
> MLB only, private beta, free to try if you want a look. No pitch beyond
> that.

### Persona 5 — Sharp-leaning bettor

*Targets: someone discussing cross-book price comparison, OddsJam,
Unabated, or getting limited by books.*

> Hey — you clearly already think in terms of comparing prices across
> books, so I'll be straight about what this is and isn't. I built
> [WORKING TITLE]; it shows a price-improvement board (best quoted price
> vs. the de-vigged market consensus, across books) but it does NOT claim
> an edge, doesn't do CLV framing, and isn't built for the volume/sharp
> tooling you're probably already running (no API, no steam alerts). If
> that's genuinely not useful to you, no hard feelings — just didn't want
> to oversell it to someone who'd see through it immediately.
<!-- source: docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md persona 5 (tools
used: OddsJam/Unabated/RebelBetting; "does not map cleanly to either of
our two proposed consumer tiers") -->

### Persona 6 — Content creator

*Targets: someone building betting-adjacent content who's mentioned
wanting citable, defensible numbers.*

> Hey — following your [content type], and thought of you because of a
> specific thing: I built [WORKING TITLE] to show its work — actual quoted
> prices, market-implied consensus, timestamped, plus a published record
> of every research idea we tested and killed. If you ever want a
> citable, checkable number instead of a vibe for something you're
> writing, happy to give you a look — I'm the builder, not a neutral
> recommender, and this is a beta, not a finished product.
<!-- source: docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md persona 6 (pain:
"needs defensible, citable numbers rather than vibes... to protect their
own credibility") -->

### Persona 7 — New bettor wanting guidance

*Targets: someone asking "how do I get started" or expressing distrust of
black-box picks apps.*

> Hey — saw you asking about getting started. One honest note before
> anything else: [WORKING TITLE] (which I built) doesn't teach betting
> strategy or give picks — it's a checking tool, not a coach. It shows you
> the price, the consensus, and what changed for a bet you're already
> considering, with no recommendation attached (that field is
> intentionally empty — there's no validated prediction model behind this
> product).
<!-- source: docs/API_CONTRACTS.md ("recommendation" permanently null);
docs/COMPETITIVE_INTELLIGENCE/PERSONAS.md persona 7 (wants "to be taught
'how to think,'" not handed picks) -->
>
> If that's not what you need right now, PlayerProps.ai's community/
> education angle (mentioned a lot by people in your spot) might be a
> better first stop than this. If a checking tool for later is useful,
> happy to send an invite.

---

## 2. Reddit / Discord honest pitch (transparent "I built this" only)

For subreddits/Discords where self-promotion requires explicit disclosure
(r/sportsbook, r/sportsbetting, most betting Discords' `#self-promo`
channels) — check each community's specific rule before posting; this
script assumes a "disclosed builder post" is the permitted format, not a
comment or DM masquerading as organic discussion.

> **I built a sports-betting checking tool. Full disclosure: this is my
> product, not a review.**
>
> I've spent [TIME PERIOD] running actual research against real MLB games
> — 25 distinct ideas at the detector level (35 counting every registered
> variant), everything from bullpen workload to cross-book price
> dispersion. **Zero of them survived our own falsification tests.** I'm
> not saying that to be self-deprecating — it's the actual result, and
> it's published in full, including the one idea that looked real at first
> (a cross-book dispersion signal, +8.49pp over 249 selections) until we
> ran the pre-committed checks and it fell apart on replication.
<!-- source: docs/RESEARCH_CATALOGUE.md (25/35 count; F1 cross-book
dispersion result and its failure mode); docs/CONTENT_LANDING.md §3
("the honesty story") -->
>
> So [WORKING TITLE] doesn't predict winners or hand you a pick. What it
> does: shows the actual price you'd get, the de-vigged market-implied
> consensus separately, what changed on a game since this morning, and —
> for any bet you're checking — the honest case for and against that side,
> including saying plainly when there's no real counterargument to show
> you.
>
> It's MLB-only, private beta, [PRICE]/mo (or free if you're one of the
> first beta invites — happy to hand a few out here if there's interest).
> Genuinely looking for people who'll tell me what's wrong with it, not
> just people who want a picks app — this isn't that.
>
> Happy to answer anything, including "why would I trust a tool built by
> someone with zero winning ideas so far" — that's a completely fair
> question and the honest answer is: you're trusting the process
> (published nulls, pre-registered tests) not a track record, because
> there isn't one yet.

**Posting discipline:**
- One post per community, no cross-posting the identical text to farm
  reach — a repeated identical post reads as spam regardless of honesty.
- No incentivized upvotes/comments, no asking friends to "show support" —
  the entire pitch's credibility rests on the research-honesty framing;
  manufactured engagement directly undermines it.
- Answer every skeptical reply for real, including ones that land — a
  disclosed-builder post that stops responding once the questions get hard
  reads worse than not posting at all.

---

## 3. Founding-member offer one-pager

Per `docs/PRICING_OFFER_VALIDATION.md` §1's founding-member framing —
"honest, concrete, and checkable — a real price lock, not a vague 'founding
member' badge." `[PRICE]` merge field throughout; N (cohort size) also
pending Brey's decision (same BREY DECISION BLOCK) and shown as `[N]`
below.

---

**[WORKING TITLE] — Founding Member**

You're one of the first [N] paying beta subscribers. Here's exactly what
that means:

- **[PRICE]/mo, locked for as long as your subscription stays active** —
  even after the public price moves to $29.99/mo at general launch. If you
  cancel and resubscribe later, the price active at that time applies; the
  lock only holds for a subscription that stays continuously active.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 ("the first N paid-beta
subscribers get $19.99/mo... locked for as long as they stay subscribed,
even after the public price moves to $29.99/mo"; lock condition stated
verbatim) -->
- **Annual option: $239/yr at this rate** (effective [PRICE]/mo) — two
  months free compared to paying monthly at the same rate, stated exactly:
  12 × $29.99 = $359.88/yr at the eventual public monthly rate; $239/yr is
  about a 33.6% discount against that number, not against today's beta
  rate.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 (discount math shown in
full: "(359.88 − 239) / 359.88 ≈ 33.6%") -->
- **Full feature set, no tier ladder** — the evidence ladder, the
  price-improvement board, What Changed, Bet Check, and saved bets are all
  included; nothing is gated behind a higher tier because there is no
  higher consumer tier today.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 ("one tier, one price, no
feature ladder, for PAID BETA") -->
- **Cancel anytime, one click, no retention flow.** Your access continues
  through the end of the period you already paid for; you won't be charged
  again. If you're billed by mistake, email us within 7 days for a full
  refund, no questions asked.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 (refund/cancel policy
draft, verbatim terms) -->

**What this is not:** a discount to make an overpriced product look
cheap, or a "limited spots" countdown. [PRICE]/mo is genuinely below the
$20–35/mo band our direct competitors occupy, because this is an unproven,
single-sport, beta product being asked of real strangers for the first
time — the discount is earned by being early, not manufactured by pretend
scarcity.
<!-- source: docs/PRICING_OFFER_VALIDATION.md §2 ("a deliberate beta
discount below the $20–35 band... not a permanent competitive position") -->

**No countdown timer accompanies this offer, and none should be added to
any rendering of it** — `docs/PRICING_OFFER_VALIDATION.md` §1 and §4
explicitly rule out urgency/scarcity framing for this exact offer.

[Get started at [PRICE]/mo → APP_LINK]

---

## 4. X/thread outline — the honesty-story angle

Mirrors `docs/CONTENT_LANDING.md` §3's "honesty story" content, restructured
for a thread format (short, numbered posts, one idea per post).

1. **Hook:** We ran 25 pre-registered betting research ideas against real
   MLB games (35 counting every registered variant). Zero survived our own
   falsification tests. Here's what that actually looked like. 🧵
<!-- source: docs/RESEARCH_CATALOGUE.md -->
2. One idea — betting against a book that sat far off the market pack —
   looked real at first: +8.49 percentage points over 249 selections,
   statistically significant.
<!-- source: docs/RESEARCH_CATALOGUE.md (F1 cross-book dispersion) -->
3. Then we ran the checks we'd pre-committed to before ever looking at the
   result: did it hold up season over season? Did it come from one book or
   many? Did the effect reverse just past the threshold that defined it?
4. It failed all three. The effect came almost entirely from one
   sportsbook, didn't replicate season-over-season, and reversed direction
   right at the boundary of its own definition. We killed it — and
   published the writeup instead of quietly shelving it.
<!-- source: docs/RESEARCH_CATALOGUE.md (F1's specific failure modes) -->
5. That's the pattern across all 25/35 ideas: bullpen workload, platoon
   matchups, fading recent line moves, cross-book dispersion — tested the
   same rigorous way, none of them cleared the bar.
6. So [WORKING TITLE] doesn't predict winners. There's a `recommendation`
   field in the product and it's permanently, deliberately empty — not a
   gap we're filling later, a rule, until something actually clears our
   own bar.
<!-- source: docs/API_CONTRACTS.md ("recommendation" permanently null) -->
7. What it does instead: shows you the actual quoted price, the
   market-implied consensus (de-vigged, never called "true"), what changed
   recently, and — when you're checking a specific bet — the honest case
   for and against it, including saying plainly when there's no real
   counterargument.
<!-- source: docs/CONTENT_LANDING.md §2 -->
8. Price improvement — finding the better of two quoted prices for the
   same bet — is real and we show the arithmetic: if the bet wins, the
   better price pays more; if it loses, both cost the same. No prediction
   involved, just two numbers compared honestly.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md (two-branch framing,
required); docs/CONTENT_LANDING.md §4 -->
9. It's MLB only, private beta, [PRICE]/mo for the first [N] subscribers,
   locked for as long as you stay subscribed. Full record of every failed
   idea is in-product if you want to read it yourself rather than take our
   word for it.
10. If "we published our own losses instead of hiding them" is a product
    you'd want to try, beta invites are open: [APP_LINK]. This product
    never guarantees an outcome and does not hand you a predicted winner —
    if picks or a promised result are what you're looking for, this
    genuinely isn't the right tool; we haven't found anything that clears
    our own bar yet, and we're not going to pretend otherwise to sell a
    subscription.
<!-- source: docs/CONTENT_LANDING.md §3 ("What this product will not do") -->

**Thread discipline:** post as a real account disclosing authorship in
post 1 ("I built this" or equivalent), not an anonymous or brand-only
account implying third-party coverage. No bot amplification, no purchased
engagement, no coordinated reply-network boosting.

---

## Open items for Brey (not resolved by this doc)

- Product name unresolved — every `[WORKING TITLE]` needs a global
  find/replace once locked, same open item every content doc in this repo
  carries.
- `[PRICE]` and `[N]` (founding-cohort size) are pending
  `docs/PRICING_OFFER_VALIDATION.md`'s BREY DECISION BLOCK — do not fill
  either in before that decision lands, including in a rendered/sent
  version of the one-pager or thread.
- Which specific subreddits/Discords permit a disclosed-builder self-promo
  post, and their exact posting rules, is not researched here — verify
  each community's current rules before posting; they change and vary by
  community.
- No acquisition-channel evidence exists for personas 2, 4, and 8
  (`PERSONAS.md`'s own cross-persona notes flag this) — no outreach script
  is written for them here; do not improvise one without the same
  evidence-citation discipline the four scripted personas above follow.
