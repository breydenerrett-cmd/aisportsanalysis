# Landing-page & product content package — DRAFT

Working brand: Linehound (temporary, pending trademark/domain clearance —
Brey 2026-09-01).

Content only, no HTML/visual design — a separate Claude Design session owns
aesthetics. Every quantitative claim is cited inline as `<!-- source: FILE -->`.
The product has not cleared a final legal/trademark name; every mention
uses **LINEHOUND** as the working brand per Brey's 2026-09-01 decision
(supersedes the open finalist list in
`docs/COMPETITIVE_INTELLIGENCE/NAMING.md` / `CHECKPOINT.md` — none of those
names is cleared, and none should be treated as decided).

This draft avoids tout vocabulary entirely: no plus-sign EV framing, no
claim of a "true" price, no guaranteed outcome, no invented win
probability, no claim that betting is risk-free, and no claim of beating
the sportsbooks. Price improvement is described only as line-shopping
value — never as an edge, never as a wagering-expectancy number — and
never reduced to a single dollars-per-month figure without both branches
shown. `late_move` is never described as being the same thing as CLV. The
enforced list lives in `tests/test_customer_language.py` and
`tests/test_content_language.py`.

---

## 1. Hero variants (3) — DRAFT

All three are HYPOTHESES per Brey's direction: honest capability statements
to test, not a settled brand identity. Positioning is evidential
transparency — what the product shows you and what it admits it doesn't
know — not a promise of winning.

### Hero A — "Show your work"
- **Headline:** Every claim, checkable.
- **Subhead:** LINEHOUND shows you the actual price, the actual market
  consensus, and what changed since this morning — for one bet you're about
  to make. No hidden math, no promised outcome.
- **Primary CTA:** Check a bet

### Hero B — "What we don't know, out loud"
- **Headline:** We publish our losses too.
<!-- source: docs/RESEARCH_CATALOGUE.md -->
- **Subhead:** Four pre-registered research families, dozens of tested
  ideas, zero that beat the market. We'll tell you exactly which ones we
  ruled out — and why that's the point.
- **Primary CTA:** See the research record

### Hero C — "Line shopping, made checkable"
- **Headline:** Find the better price. See the arithmetic.
- **Subhead:** LINEHOUND compares the price you'd take against the
  best one on the board right now, and shows you what that's actually worth
  — win or lose — before you place the bet.
- **Primary CTA:** Try the price check

---

## 2. How it works — DRAFT

Copy describes only what the product does today, per
`docs/API_CONTRACTS.md`.

### Today
Open the app and see today's slate — one entry per game, pulled fresh for
the current date. Each game shows whether a market is currently priced for
it and how old that price is; if there's no board yet, we say so instead of
guessing.
<!-- source: docs/API_CONTRACTS.md (GET /today) -->

### Game
Tap into any game for a quick view and a full dossier: team and venue
identity, the market-implied consensus for each side (a fraction derived
from de-vigged prices, not a prediction we're making), and the supporting
detail behind it. When there isn't enough market to form a consensus, that's
shown as "unavailable," not silently dropped.
<!-- source: docs/API_CONTRACTS.md (GET /game/{date}/{away}/{home}) -->

### Bet Check
Tell us the game, the side, and the price you'd take. We check it against
the best price currently quoted, show the market-implied consensus
separately, and lay out the supporting case and the honest counterargument
for that side — including a line that says plainly when we found no
significant counterargument. We never fill in a recommendation: that field
is permanently empty until a validated prediction engine exists, which it
does not today.
<!-- source: docs/API_CONTRACTS.md (POST /betcheck; `recommendation` permanently null) -->

### Odds
Browse the full market board for the slate — every game's quoted prices
across books, the widest spread on the board, and how often books disagree
on who's favored. Every price is timestamped with when we last observed it.
<!-- source: docs/API_CONTRACTS.md (GET /odds/{date}) -->

### What Changed
A running note of what moved since a stated point in time (e.g. "since this
morning") for the whole slate — lineup posts, scratches, roster moves — so
you're not re-reading a stale page.
<!-- source: docs/API_CONTRACTS.md (GET /changed/{date}) -->

---

## 3. The honesty story — DRAFT

**Headline:** We ran the numbers. Most ideas don't survive contact with
real games. We tell you which ones didn't, instead of quietly shelving them.

**Body:**

Between 2023 and 2024, we pre-registered four separate research families
against MLB moneyline betting — a total of 25 distinct ideas at the
detector/mechanism level (35 counting every registered detector-by-market
combination) — everything from bullpen workload and platoon matchups to
market-structure effects like fading recent price moves and cross-book
price dispersion.
<!-- source: docs/RESEARCH_CATALOGUE.md ("Counting the families" — 25 at detector/spec level, 35 at registered-hypothesis level; the commonly-cited "27" double-counts one family and should not be repeated) -->

**Zero of them survived our own falsification tests.**
<!-- source: docs/RESEARCH_CATALOGUE.md ("Running score... zero survivors") -->

One idea — betting against a book that sat far off the pack — looked like a
real signal at first: a positive, statistically significant effect over 249
selections. Then we ran the checks we'd committed to in advance: the effect
came almost entirely from one sportsbook, didn't hold up season over season,
and reversed direction just below the threshold that defined it. We killed
it, and we kept the record.
<!-- source: docs/RESEARCH_CATALOGUE.md (F1 "cross-book dispersion" — 249 selections, +8.49pp headline, killed by dose-response inversion, single-book concentration, no season replication) -->

**What that means for you:**
- We don't ship a "prediction" because one candidate idea looked good in a
  backtest. Every idea here failed a pre-committed replication test before
  it could reach the product.
- Nothing in LINEHOUND claims a win probability, a predicted winner,
  or a bet recommendation. That's not a feature we haven't built yet — it's
  a rule: the underlying model is uncalibrated, and no payload in the
  product emits a win-probability field.
<!-- source: docs/API_CONTRACTS.md (vocabulary rules: "No win probability... permanent product rule, not a gap to fill in later") -->
- What we do give you — the actual quoted prices, the market-implied
  consensus, and what changed recently — is real, checkable, and never
  dressed up as more than it is.

**What this product will not do:** tell you who is going to win, promise a
result, or dress up a quoted price as more than a price. We will never
call that price an edge, and we will not promise an outcome. If that is
what you are looking for, we are not the right tool — we have not found
anything that clears our own bar yet, and we are not going to pretend
otherwise to sell a subscription.

---

## 4. Price-improvement explainer — DRAFT

Per the approved calculator spec in `docs/PRICING_CALCULATOR_REVIEW.md`.
This is descriptive copy for the page around the calculator component — the
component's own on-screen wording is fixed by that review and reproduced
verbatim in the callout below; this section may not paraphrase it.

**Section headline:** What line shopping is actually worth

**Intro copy:**
The same bet is often quoted at different prices by different books. Taking
the better one costs you nothing if the bet loses, and pays you more if it
wins. That's the entire idea — no prediction, no probability, just the
arithmetic of two prices on the same bet.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md ("the one unconditional claim is dominance") -->

**Two-branch framing (must always appear together, same size, same
prominence):**
- If the bet wins: the better price pays more.
- If the bet loses: both prices lose the same stake. The difference is $0.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md (§2a, §3 "Hard wording constraints" #2) -->

**Breakeven framing:** A better price also lowers the win rate you need to
break even — e.g. at −110 you need 52.4% of these bets to win to break even;
at −105 you need only 51.2%. This is pure price arithmetic; no assumed win
rate goes into it.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md (§2b "Breakeven-probability shift") -->

**Calculator callout copy (verbatim from the approved spec; substitute
bracketed values only):**

> If a bet at [odds_b] wins, it pays [$delta_per_win] more than the same bet
> at [odds_a]. If it loses, both lose the same [stake]. Over [bets] winning
> bets, that's [$delta_per_month] — paid only on the bets that win.
>
> The better price also lowers your bar: at [odds_a] you break even winning
> [breakeven_a_pct]% of the time; at [odds_b], [breakeven_b_pct]%.
>
> No prediction involved — this is the arithmetic of two prices on the same
> bet. Prices are as quoted at the moment we observed them; whether a book
> accepts your stake is up to the book. Finding the better number is what
> LINEHOUND does.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md ("Approved specification" §3 output copy) -->

**Small print (must render inline, never a tooltip or footnote link):**
We never name which book had the best price on this page — on 63–79% of
observed instants, more than one book was tied for it, so naming one would
be arbitrary. And a quoted price is what we observed, not a guarantee that
book will take your exact bet at your exact size.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md (§1.3 tie rate 62.7%/78.6%; §2d takeability qualifier; §3 hard constraint #3) -->

**What this section will not do:** show a single self-funding dollar
figure, compare the subscription price to the calculator's output in copy,
name a book, or show the de-vigged market consensus as a bettable price.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md (§3 hard constraints #1, #4, #6) -->

---

## 5. FAQ — DRAFT

**No guaranteed wins — is that really true?**
Yes. Nothing in LINEHOUND guarantees an outcome or a profit, for any
user or any bet. You are responsible for your own wagering decisions,
including whether to bet at all.
<!-- source: src/analysis/disclaimers.py (BETA_DISCLAIMER) -->

**Is this gambling advice?**
No. We show you prices, market-implied consensus, and what changed — not a
recommendation. The product's own "recommendation" field is intentionally
and permanently empty; it isn't a coming-soon feature, it's a rule until a
prediction engine actually clears our own validation bar.
<!-- source: docs/API_CONTRACTS.md ("recommendation" permanently null; Ranker Engine 2 gate) -->

**Do you predict who wins?**
No. We do not publish a win probability or a predicted winner anywhere in
the product. The model behind our research is uncalibrated, and that is a
permanent rule, not a gap we are planning to fill.
<!-- source: docs/API_CONTRACTS.md (vocabulary rules: "No win probability") -->

**What's a "price improvement," then?**
It's the better of two quoted prices for the same bet — line shopping, not
a prediction. See "What line shopping is actually worth" above.

**No edge found yet — what does that mean?**
Exactly what it says: we have not found a betting edge, and we say so
directly. We've pre-registered and tested 25
distinct research ideas (35 counting every registered variant) against real
MLB games from 2023–2024. None of them survived our falsification tests.
We publish the losers, including the one that looked promising until we
checked it properly.
<!-- source: docs/RESEARCH_CATALOGUE.md -->

**How fresh is the data?**
Every price and consensus figure carries the timestamp of when we last
observed it, and we show its age rather than hiding it. If there's no
market currently priced for a game, we say that plainly instead of showing
a stale or fabricated number.
<!-- source: docs/API_CONTRACTS.md (odds_meta.observed_utc / age_seconds; "never a fabricated 0") -->

**Which sportsbooks do you cover?**
Coverage varies by market: our head-to-head moneyline board draws from
multiple books (we don't name a fixed count publicly, since it varies by
game and moment), and we tell you how many books contributed to a given
consensus figure rather than asserting a blanket number.
<!-- source: docs/API_CONTRACTS.md (market_consensus.books; consensus_unavailable_reason) -->

**Which sports do you cover?**
MLB only, today. That's where our research and data pipeline are built out;
other sports are not currently supported.
<!-- source: docs/COMMERCIAL_READINESS.md (data-coverage bar: MLB); docs/RESEARCH_CATALOGUE.md (all research is MLB h2h moneyline) -->

**Is this in beta?**
Yes. The product carries a visible beta notice: it's an information and
research product, and it does not guarantee outcomes; the notice itself is
pending final legal review before any public paid launch.
<!-- source: src/analysis/disclaimers.py (DISCLAIMER_ID = "beta-v1"; requires_final_legal_review=True) -->

**Can I cancel anytime?**
Yes — cancellation is designed to be one click, with no retention flow or
dark patterns, and the policy will be written and shown to you before you
ever pay.
<!-- source: docs/COMMERCIAL_READINESS.md (standing rule 4: "trivial cancellation... no dark patterns"; written policy required before first paid charge) -->

**Will I be charged after I cancel?**
No — that is treated as a stop-ship-severity failure internally, never as
an acceptable exception.
<!-- source: docs/COMMERCIAL_READINESS.md ("charged after cancelling" report should be treated as a stop-ship-severity issue) -->

**What does it cost?**
Pricing is being finalized before paid launch; today's product is free,
invite-based beta. When pricing locks, we'll show you a page that leads
with exactly what you get for the price, not a comparison to what you might
win.
<!-- source: docs/COMMERCIAL_READINESS.md (Stage 3 "closed beta remains free"; pricing-lock decision item: one-sport tier under consideration, not yet locked publicly; "visible, honest 'here's what you get for the price' page") -->

**Why don't you show a "hit rate" or win percentage like other apps do?**
Because we do not have one we can stand behind. Our own research found
zero surviving betting ideas against real games. We will not publish a win
probability that has never been validated — doing so would be exactly the
kind of unearned confidence this product is built to avoid.
<!-- source: docs/RESEARCH_CATALOGUE.md; docs/API_CONTRACTS.md (no win-probability field) -->

**What happens to an idea that doesn't work?**
It gets a permanent, published record — including the sample size, the
effect, and why it failed — rather than quietly disappearing. A small
sample that can't support a conclusion is labeled "we cannot tell," which
is different from, and reported differently from, a tested null.
<!-- source: docs/RESEARCH_CATALOGUE.md ("We cannot tell" is a distinct verdict... N8, B2, B3) -->

---

## 6. Beta invite email + waitlist confirmation — DRAFT

### Beta invite email

**Subject:** You're in — LINEHOUND beta access

Hi [first name],

You're invited into the LINEHOUND beta.

Here's what that actually means: this is an early, free, invite-only
product. It shows you today's game prices, the market-implied consensus
across books, and a price check for any bet you're considering — with the
supporting case and the honest counterargument laid out next to each other.

A few things worth knowing up front:
- We never predict winners or publish a win probability. That is a
  deliberate rule, not a feature we have not gotten to yet.
<!-- source: docs/API_CONTRACTS.md (no win-probability field, permanent rule) -->
- We've tested dozens of betting ideas against real games and published
  every one that failed — which so far is all of them. You can read the
  full record.
<!-- source: docs/RESEARCH_CATALOGUE.md -->
- This is beta software with a visible disclaimer: no guaranteed outcomes,
  and you're responsible for your own wagering decisions.
<!-- source: src/analysis/disclaimers.py -->

[Get started button → app link]

Tell us what's confusing, what's missing, and what you don't trust. That
feedback shapes what we build next.

— The LINEHOUND team

### Waitlist confirmation email

**Subject:** You're on the list for LINEHOUND

Hi [first name],

You're on the waitlist. We'll email you the moment a beta spot opens up —
no action needed from you right now.

While you wait, here's what LINEHOUND is, plainly: a tool that shows
you real prices, real market consensus, and what changed recently for a
game or a bet you're checking. It does not predict outcomes, and it does
not promise you'll win. What it gives you is checkable — the actual
numbers, not a black-box score.

We'll be in touch as soon as there's a spot.

— The LINEHOUND team

---

## 7. Social / one-liner bank (10) — DRAFT

Vocabulary-safe: none of the enforced banned phrases (see the note at the
top of this document) appear in any of these.

1. Every claim, checkable. No hidden math.
2. We published our losses. All 25 of them, so far.
<!-- source: docs/RESEARCH_CATALOGUE.md -->
3. We don't predict winners. We show you the price, the consensus, and what
   changed.
4. Line shopping, with the arithmetic shown, not hidden.
5. No win probability. No fabricated confidence. That's a rule, not a gap.
<!-- source: docs/API_CONTRACTS.md -->
6. Tested dozens of betting ideas. Zero survived our own falsification
   tests — and we'll tell you exactly which ones failed and why.
<!-- source: docs/RESEARCH_CATALOGUE.md -->
7. If a bet wins, the better price pays more. If it loses, both cost you
   the same. That's the whole pitch on price improvement.
<!-- source: docs/PRICING_CALCULATOR_REVIEW.md -->
8. We say "unavailable" when we don't have a real market. We don't fake a
   number to fill the space.
<!-- source: docs/API_CONTRACTS.md -->
9. A recommendation field that's permanently empty, on purpose.
<!-- source: docs/API_CONTRACTS.md -->
10. Beta, clearly labeled. No guaranteed outcomes. Your call, every time.
<!-- source: src/analysis/disclaimers.py -->

---

## Open items for Brey / counsel (not resolved by this doc)

- Product name is unresolved (three finalists, none cleared) — every
  placeholder here needs a global find/replace once locked.
- Final legal disclaimer copy is pending counsel review; the FAQ and email
  drafts above quote the *temporary* beta disclaimer, not final copy.
- Public book-count claims in the FAQ deliberately avoid citing an exact
  number of books, since coverage varies by market and moment and no fixed
  public figure is established in the source docs.
- The subscription price ($29.99/mo one-sport per `COMMERCIAL_READINESS.md`)
  is a decision item, not yet locked; the "What does it cost?" FAQ answer is
  written to avoid stating an unlocked number.
