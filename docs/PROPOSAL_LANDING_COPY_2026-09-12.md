# Landing page copy proposal — sections still selling the old product

**v2.** A checker found real errors in the first draft — a wrong ledger count,
an invented quote, an impossible price/probability pairing, and a few others.
This version is corrected against the source files directly, not against the
first draft. Written for the owner. Plain English, bad news first. This is a
proposal, not an edit — `web/landing.html` is untouched.

---

## Bad news first

1. **The record never appears on this page**, and what it actually says is
   messier than "two graded nights." Full numbers below — read that section
   before anything else, because two things in the first draft of this
   document were wrong about it.
2. **Three of the four "every bettor has this story" pain points are about
   watching prices move and lineups post — not about picks.** Only "The
   favourite" (price vs. break-even) matches what the card sells today.
   (`web/landing.html:199-219`; the retirement of price-comparison as a
   customer surface is documented at `web/landing.html:359-362`.)
3. **"In the seventh inning" is a price-movement demo, top to bottom** — a
   lineup scratch, a 17-cent line move, a chart of the move. Nothing in it is
   a pick, a probability, or anything gradeable. (`web/landing.html:365-386`)
4. **"Sample slate" shows the old price-board tile format**, including a
   "Best price" badge — the framing the owner ruled off customer surfaces
   ("that has to stop... nobody... cares," `docs/OVERNIGHT_PLAN_2026-09-12.md`
   lines 211-213, quoted exactly below). It shows no pick, no label
   (STRONG/LEAN/SLIGHT/SPLIT — `web/js/card.js:41-44`), no break-even number.
   (`web/landing.html:280-321`)
5. **"Thirty seconds or thirty minutes" contradicts the page's own evidence
   ladder, and recycles a killed idea's sample size to do it.** Its Quick
   View line says "Moderate historical support over 249 selections." Six
   sections earlier, "Where our research actually sits" says the
   **Historical support** rung is not lit — today sits at **Observation**
   (`web/landing.html:262-273`). And **249** is not a new number: it is the
   exact sample size of the one idea `web/landing.html:241` already describes
   — the one that "reversed direction just below the threshold that defined
   it" and was killed. The Quick View sentence is dressing up a killed idea's
   sample size as live support for a different bet. (`web/landing.html:397`,
   compared against `:241`)
6. **"It gets better the more you use it" sells a bet-tracking feature on the
   reader's *own* bets, not the card** — "your number vs the best," "what
   moved after you fired," "your repeat weak spot." (`web/landing.html:419-441`)
7. **Four of the page's six button links offer a free Bet Check, not a
   preview of the card** (`web/landing.html:57,128,454,570`), and the card is
   the product now. The fifth is `web/landing.html:464`, "Get founding
   access" — the primary button on the founding-beta pricing card — which
   isn't a free preview either, it's the paid path. The sixth is the
   "Check it" button inside the Bet Check demo (`:353`), which also goes to
   signup. (A seventh, "OPEN THE LIVE DEMO" at `:131`, is hidden unless the
   deploy runs as a public demo, which production deliberately does not —
   `deploy/fly.production.toml:53`.) `/card` is paid — gated
   by `require_paid_access` (`api/app.py:84,92`) unless the server runs with
   `APP_PUBLIC_DEMO=1`, the flag that lets the landing hero itself show a real
   game (`web/js/landing-live.js:1-6`). A prospect can try the old product's
   free tool or pay for founding access, but cannot see one pick from the new
   product for free.

---

## The record, plainly — corrected

Source: `evidence/cards_v1.jsonl`, read row by row (18 lines total: 17 rows
with `kind: "card_published"`, 1 row with `kind: "card_settled"`).

**Published, by date (from each row's `published_utc`):**

| Date | Published rows | `n_picks` on each |
|---|---|---|
| 2026-09-10 | 1 | 3 |
| 2026-09-11 | 11 | 5, 5, 5, 5, 5, 5, 6, 6, 6, 7, 9 (in publish order through the day) |
| 2026-09-12 | 5 | 5, 5, 5, 5, 5 |

The card was republished many times through 2026-09-11 as more games'
lineups posted, and the pick count grew across those republications, ending
at **9 picks** on the last one that night (row 13). It did not stay in a
3-5 band. `MIN_PICKS = 3` and `MAX_PICKS = 5` are code constants
(`src/analysis/daily_card.py:89-90`), and the `select()` function itself caps
a single call's agreed-picks at `max_picks` (`daily_card.py:631-651`) — so
where does 9 come from? The answer is in `card_ledger.publish()`: every
republication is merged with the previous row's picks rather than replacing
them — the ledger reader's docstring says the newest row is "the full current
composition: locked picks exactly as they were locked, open picks as of the
latest read" (`published_row()`, `src/appstate/card_ledger.py:183-184`), and the merge that does
this carries every already-locked pick forward and only adds to it
(`card_ledger.py:271-319`). `src/report/card.py:563` calls
`daily_card.select(candidates)` with no override, so `max_picks` defaults to
5 and each single call really is bounded at 5 — but 6, 7, and then 9 is what
locked picks accumulating across the day's later republications look like on
top of that per-call cap, not a bypass of it. **No copy may promise "three to
five picks" as a fact regardless** — the daily total isn't bounded that way
in practice, even though each individual `select()` call is.

**Settled:** exactly one row, `kind: "card_settled"`, `date: "2026-09-10"` —
**2 wins, 1 loss, +0.5407 units on 3 bets, ROI +18.023%** (row 2). Neither the
2026-09-11 nor the 2026-09-12 cards have a `card_settled` row as of this
writing (2026-09-12) — the entire 2026-09-11 card, all eleven versions of it,
is still ungraded. So today, honestly: **one graded night, 2-1.** Nothing
published since has a result yet.

**Research:** 36 pre-registered hypotheses read, zero survived — already the
number on the page in three places (`web/landing.html:186, 235, 532`), so no
change needed there.

Any copy below that touches the record says exactly what's in this table and
no more — no "usually," no "our picks win," no implied pick-count promise.
One graded night cannot support any of those, and the standing rule is that
losers publish at the same size as wins, not get rounded off.

---

## Section-by-section

### 1. "Every bettor has this story" — REWRITE

**Why:** Three of four cards are the retired line-shopping/monitoring
product. "The favourite" is the only one actually about a pick mismatch — a
side priced worse than it's actually likely to win, which is the exact
break-even math the card publishes on every pick (`daily_card.py:196`,
`_breakeven_pct`, called from `_bet_sentence` at line 220 and used at line
322). The other three describe problems a price-tracking feature solves, not
problems the card solves. Reframed around the actual gap the card claims to
fill — a checkable record, receipts instead of a screenshot — the section
sets up "why we built this" instead of contradicting the page around it.

No invented statistics about any real or implied competitor appear below —
the first draft of this document put a fabricated "62-38 for the season"
record into a hypothetical tout's mouth, which is exactly the kind of
unsourced number this whole document argues against. Removed.

**Proposed copy:**

```html
<section class="section" aria-label="the problem" data-hook="pain-points">
  <div class="section__head" data-rise>
    <span class="eyebrow eyebrow--money">Every bettor has this story</span>
  </div>
  <h2 class="section__title" data-rise data-delay="60">You've taken a pick from someone who wouldn't show you their record.</h2>
  <div class="story-grid" style="margin-top:32px">
    <div class="story-card panel chamfer" data-rise data-delay="80">
      <div class="story-card__kicker">The favourite</div>
      <div class="story-card__title">Took −180.<br>They win 58% of the time.</div>
      <p class="story-card__body">At −180 you need 64% just to break even. The bet was losing money before the first pitch.</p>
    </div>
    <div class="story-card panel chamfer" data-rise data-delay="140">
      <div class="story-card__kicker">The lock</div>
      <div class="story-card__title">"Trust me, lock of the night."<br>No case. No number.</div>
      <p class="story-card__body">Not how likely it is, not what the price needs — just a name and a confident tone.</p>
    </div>
    <div class="story-card panel chamfer" data-rise data-delay="200">
      <div class="story-card__kicker">The screenshot</div>
      <div class="story-card__title">A win, framed and posted.<br>The losses, never mentioned.</div>
      <p class="story-card__body">Handicappers post the nights they're right. The nights they're wrong quietly disappear from the feed.</p>
    </div>
    <div class="story-card panel chamfer" data-rise data-delay="260">
      <div class="story-card__kicker">The record</div>
      <div class="story-card__title">"Check my record."<br>There's nothing to check it against.</div>
      <p class="story-card__body">A record you're told about isn't a record. A record you can open yourself is.</p>
    </div>
  </div>
</section>
```

---

### 2. "In the seventh inning" — REWRITE (replace the price-movement demo with a real graded pick)

**Why:** This section is a lineup-scratch-and-line-move demo — no pick, no
probability, nothing gradeable. `docs/PRODUCT_DOCTRINE.md` section 1, item 1
is explicit about where the proof belongs: **"The core product is AI sports
picks and betting edge. Provability and auditability are the trust moat —
[...] not a substitute for prediction quality."** That is the opposite
emphasis from making a whole section about price movement — the receipts
support the picks, they aren't the pitch by themselves. The replacement
below uses one real settled pick, quoted from the ledger, not invented: the
Phillies moneyline loss from 2026-09-10 (`evidence/cards_v1.jsonl` row 1, the
`why` array on the Phillies pick, and row 2's settlement fields). This isn't
new disclosure — it's already public on `#/record-card` — it only relocates
one real example to the page that's supposed to be selling honesty.

**Proposed copy:**

```html
<section class="section" aria-label="a graded pick, in full" data-hook="losing-pick-demo">
  <div class="section__head" data-rise>
    <span class="eyebrow eyebrow--money">What the picks actually look like, graded</span>
  </div>
  <h2 class="section__title" data-rise data-delay="60">Here's a pick we got wrong. In full.</h2>
  <div class="demo-panel panel chamfer" style="margin-top:28px" data-rise data-delay="100">
    <div class="demo-block">
      <div class="demo-block__label">Sept 10, 2026 · Astros @ Phillies</div>
      <p class="demo-block__body" style="font-weight:600">Take Phillies to win at −165.</p>
    </div>
    <div class="demo-block">
      <div class="demo-block__label">The case, as published — before first pitch</div>
      <p class="demo-block__body">Phillies score 4.5 runs a game and give up 4.2. Astros score 4.5 and give up 4.8.
        Zack Wheeler starts against Cristian Javier. The market makes Phillies a 61% bet to win; our own numbers
        agree at 56%.</p>
    </div>
    <div class="demo-block watchout chamfer">
      <div class="demo-block__label" style="color:var(--money-label)">What happened</div>
      <p class="watchout__body">Astros 2, Phillies 1. Loss. −1.00 unit. Graded the next morning, exactly as
        published — nothing edited after the fact.</p>
    </div>
  </div>
  <p class="section__lede" style="max-width:none">This is one of the three picks on the one night this record has graded so far: 2 wins, 1 loss.</p>
</section>
```

**Owner call needed — read this before approving:** at −165 the break-even is
62%. Our own number on this pick was 56% — *below* the price's break-even, by
our own math, before first pitch. The card still published it, because the
rule that decides a pick is "does the market and our model agree on the
side," not "does our number clear this price" (`docs/PRODUCT_DOCTRINE.md`
§4's funnel; the disclaimer on every card says the same: "Backing the more
likely side wins most individual bets and still loses money at the vig,"
`evidence/cards_v1.jsonl` row 1, `disclaimer` field). That's a defensible,
even honest, thing to publish — it's the wedge working as designed. But a
reader who just read "the favourite" pain point two sections up ("At −180 you
need 64%... the bet was losing money before the first pitch") will do the
identical subtraction here and may conclude the card knowingly recommended a
bet that was mathematically behind before first pitch. That may still be the
right thing to put on the front page — it is, after all, real and true — but
it should be the owner's call made with that specific reading in front of
them, not something this document quietly assumes.

---

### 3. "Thirty seconds, or thirty minutes" — REWRITE (removes the contradiction, adds no new numbers)

**Why:** The current Quick View sentence claims a "Historical support"
evidence tier the page says elsewhere it hasn't reached, using a sample size
recycled from a killed idea (see Bad news #5 above). The fix below keeps the
Quick/Advanced structure — still a good pattern — but stops putting any
specific probability/price pair into this section at all, for two reasons:

- Every made-up number risks the same failure this document already made
  once: a Quick View reading "Best of 11 books at −110. The market makes this
  side a 61% favourite; our own numbers land at 56%" was in the first draft
  of this section. It doesn't appear anywhere on `web/landing.html` today —
  it was invented for this proposal. It's also arithmetically impossible: a
  market pricing a side at 61% prices it near −156, not −110 (61/(1−61) ×
  100 ≈ 156). And a reader who just read "At −180 you need 64%" two sections
  up would do the same subtraction here (61% likely, 52.4% needed at −110)
  and read it as a positive-expected-value claim — which the card's own
  disclaimer explicitly forbids ("not claims of positive expected value,"
  `evidence/cards_v1.jsonl` row 1). Pairing a real-looking probability with a
  price that was never actually quoted together is the exact mistake to not
  make twice.
- The real, correctly-paired numbers for an actual pick belong to one place
  on the page, not two — they're already used in section 2 above (the
  Phillies pick) and in the existing, unchanged "Before You Fire" Bet Check
  demo (Pirates/Brewers, `web/landing.html:343-352`). Restating a third
  version here either duplicates one of those or requires inventing a fourth
  set of numbers, which is the thing to stop doing.

The Advanced disclosure also drops every field from the retired cross-book
register — `Book spread`, `Books moved`, `Fair price (Pit)` — the same
register the owner named directly (*"this whole 'we do price verification
and see which book has the better odds, dude,' that has to stop. None of
that's important. Nobody fucking cares,"* `docs/OVERNIGHT_PLAN_2026-09-12.md`
lines 211-213, quoted exactly). The first draft of this document cut these
same fields from "Sample slate" and then put them right back here, calling
them "illustrative sample numbers, not an evidence claim" — that was never
the objection. The objection is that they're the retired price-shopping
register, illustrative or not, and the owner's ruling in that document
applies to what the register measures, not to whether the numbers next to it
are real.

**Proposed copy:**

```html
<section class="section" aria-label="thirty seconds or thirty minutes" data-hook="quick-advanced-demo">
  <div class="section__head" data-rise>
    <span class="eyebrow">Thirty seconds, or thirty minutes</span>
  </div>
  <h2 class="section__title" data-rise data-delay="60">Plain English first. The full detail is one tap away.</h2>
  <div class="demo-panel panel chamfer" style="margin-top:28px" data-rise data-delay="100">
    <div class="demo-block" data-hook="quick-view">
      <div class="demo-block__label">Quick view</div>
      <p class="demo-block__body">The pick, how likely it is — by the whole market and by our own numbers — and
        what the price needs to break even. One line, in that order.</p>
    </div>
    <details class="demo-block" data-hook="advanced-view">
      <summary class="demo-block__label" style="cursor:pointer;list-style:none">Advanced ▸ matchup detail, sample size, and the counterargument</summary>
      <div style="margin-top:14px;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px">
        <div><div class="stat-label">IP / start</div><div class="stat-figure">6.1</div></div>
        <div><div class="stat-label">Books quoting</div><div class="stat-figure">11</div></div>
        <div class="not-yet-available chamfer" style="grid-column:1/-1">
          <div class="not-yet-available__head"><span class="not-yet-available__marker chamfer"></span><span class="not-yet-available__label">Not yet available</span></div>
          <div class="not-yet-available__body">Pitch mix and velocity trend — not ingested from a verified source yet, so nothing is
            shown rather than estimated.</div>
        </div>
      </div>
    </details>
  </div>
</section>
```

`Books quoting` is a depth/evidence-tier figure (how many books had a live
price when the pick froze), not a price comparison across them — the
distinction `docs/PRODUCT_DOCTRINE.md` §5.1 itself draws ("evidence
confidence... book depth" ships today; price-shopping across those books does
not).

---

### 4. "Sample slate" — CUT

**Why:** The three-tile rail carries badges reading "Best price," "Changed,"
"Bullpen." "Best price" is the exact framing the owner named and retired
(quoted above). No pick, no label (STRONG/LEAN/SLIGHT/SPLIT —
`web/js/card.js:41-44`), and no probability appears anywhere in this section.
It also duplicates the hero (one live matchup already) and "What you
actually get" (already shows what a card looks like) without adding anything
new. Cutting it shortens the page and removes a contradiction for free,
rather than rebuilding it to show real pick-card tiles — a real design lift
that the doctrine's own card format already does better elsewhere on the
page.

**Proposed copy:** none — delete `web/landing.html:280-321` in full.

---

### 5. "It gets better the more you use it" — REWRITE

**Why:** All three cards describe tracking the *reader's own* betting history
("your number vs the best," "what moved after you fired," "your repeat weak
spot") — a feature for their bets, not ours, sitting directly above pricing
where the pitch should be tightening around the card. It also isn't a live
feature today: `#/mybets` doesn't save anything from Bet Check yet
(`docs/OVERNIGHT_PLAN_2026-09-12.md` Tier 2, "Nothing saves from Bet
Check"), so a personalization story here would be describing something that
doesn't exist yet. Rewritten around the one thing that's actually true and
actually compounds — the ledger getting longer — using only the corrected
numbers from the table above, not the "3-5 picks" / "settled the morning
after" claims the first draft of this document put here, both of which the
ledger itself contradicts today (a published card has carried up to 9 picks,
and the entire 2026-09-11 card is still ungraded as of this writing).

**Proposed copy:**

```html
<section class="section" aria-label="the record compounds" data-hook="paper-trail">
  <div class="section__head" data-rise>
    <span class="eyebrow">It gets better the more nights we're on record</span>
  </div>
  <h2 class="section__title" data-rise data-delay="60">Every card adds to a ledger you can check.</h2>
  <div class="story-grid" style="margin-top:28px">
    <div class="story-card panel chamfer" data-rise data-delay="60">
      <div class="story-card__kicker">Tonight's card</div>
      <p class="story-card__body">A handful of picks, frozen before first pitch and written to a tamper-proof
        chain the moment they're made.</p>
    </div>
    <div class="story-card panel chamfer" data-rise data-delay="120">
      <div class="story-card__kicker">The grade</div>
      <p class="story-card__body">We grade every pick and publish the result — win, loss, or void — and
        nothing on the ledger is edited after. Some nights that grade lands the next morning; some nights
        it's still pending.</p>
    </div>
    <div class="story-card panel chamfer" data-rise data-delay="180">
      <div class="story-card__kicker">The running record</div>
      <p class="story-card__body">Wins and losses sit on the same page, at the same size, starting from the very
        first graded night.</p>
    </div>
  </div>
</section>
```

I swapped "hash-chained record" for "tamper-proof chain" in this new copy —
not a correction to anything already on the page (that phrase, unchanged, is
fine at `web/landing.html:170`), just matching the wording the app's own
record page already uses for the same thing (`web/js/card.js:244`) rather
than adding a third term (`web/js/cardrecord.js:163` uses a fourth,
"TAMPER-EVIDENT LEDGER"). None of this needs to change today; it's a minor
consistency nit, not a rewrite worth doing on its own — noted so it doesn't
get re-introduced by accident later.

---

### 6. FAQ — KEEP, unchanged

**Why:** There are **ten** existing questions, not nine
(`web/landing.html:506-562`: no-guarantee, gambling-advice, predict-winners,
price-improvement, no-edge, data-freshness, sports-covered, cancel,
free-checks, hit-rate) — the first draft of this document miscounted them.
All ten already match the current product: no false "no win probability"
claim, the correct research count, an honest "do you predict who wins"
answer.

The first draft proposed adding an eleventh entry stating the 2-1 record,
inserted directly after `faq-hit-rate`. That question and answer read: *"Why
don't you show a win percentage like other apps do? Because we do not have
one we can stand behind... We will not publish a win probability that has
never been validated"* (`web/landing.html:557-562`). Publishing "two wins,
one loss" in the very next box states a win/loss result immediately under a
question that says the product deliberately withholds exactly that kind of
figure. Even though the two are technically different things — a settled
result from one real night versus a validated predictive win-rate model — a
reader hitting them back to back reads a contradiction, not a distinction.
Given the record is already surfaced honestly in section 2's rewrite above
("one of the three picks on the one night this record has graded so far: 2
wins, 1 loss"), there's no need to also add it to the FAQ, and doing so right
under `faq-hit-rate` is the one place on the page most likely to make it read
badly. **Recommendation: leave the FAQ exactly as it is.**

---

### 7. Closing band — REWRITE (contingent on the CTA answer below)

**Why:** "Before you fire, run it through" is the Bet Check tagline and
already appears once (`web/landing.html:326-328`). As the last thing a reader
sees, it points at checking a bet they already have in mind, not at tonight's
card, which is the product the rest of the page now leads with.

**Proposed copy:**

```html
<section class="closing-band" aria-label="call to action" data-view="cta" data-hook="cta-bottom">
  <div class="closing-band__title">Tonight's card is already up.<br>See what it says.</div>
  <div class="closing-band__cta">
    <a class="btn btn--primary btn--lg" href="index.html#/betcheck" data-hook="cta-signup-bottom">Try 3 Bet Checks free</a>
  </div>
</section>
```

Only the headline changes. The button and its destination are left exactly
as they are — that decision depends on the open question below, not on
wording.

---

## The CTA question: is a free Bet Check still the right first step?

**Asked directly, because it can't be answered by copy alone.**

Four of the page's six button links — nav (`:57`), hero (`:128`), pricing's
free-trial card (`:454`), and the closing band (`:570`) — offer **"Try 3 Bet
Checks free."** Bet Check answers "is the bet I already have in mind any
good." That was the right free trial when the product was line-shopping. It
is not a preview of the card, which is what the hero and "What you actually
get" now lead with. The fifth, and the pricing card's primary button, is
already **"Get founding access"** (`:464`) — the paid path, not a free
preview either; the sixth, the demo panel's "Check it" (`:353`), goes to
signup too. Not one button on the page shows a pick from the card for free.

**The technical constraint, not just a copy one:** `/card` requires payment.
`api/app.py` gates the card router behind `require_paid_access`
(`_authed_paid`, line 84, applied to `card_router` at line 92) for every
request unless the server runs with `APP_PUBLIC_DEMO=1` — the flag that lets
the landing hero itself show a real game (`web/js/landing-live.js:1-6`).
`deploy/fly.production.toml` states plainly that this flag "IS DELIBERATELY
ABSENT, and must stay absent" in production (line 53). So on the real
production deploy, a prospect cannot see one pick from tonight's card without
paying — the free thing they *can* try is a different feature entirely.

I also want to flag, separately, a link I almost put into this document's own
proposed copy and removed: a "see every graded night" link pointing at
`#/record-card` would send a free visitor straight at `GET /card/record` and
`GET /card/history` (`web/js/cardrecord.js:2,474-475`), both mounted under
`card_router` — the same paid gate as `/card` itself
(`api/app.py:92`). That's not a hypothetical trap; it's the same one this
document's "bad news" section already names for the CTA overall, and it
would have been reintroduced by this proposal's own copy in an earlier draft.
The rewritten section 2 above states the record's numbers as plain text
instead, with no link, for exactly this reason. Separately, `GET /meta` (the
research count's live source) is genuinely open with no gate
(`api/app.py:104`) — the two are not "the same way," and no copy on this page
should imply they are.

**Three ways to close the free-trial gap**, none of which I can pick for you:

1. **Keep Bet Check as the free trial**, and stop implying it's a preview of
   the card — reword the CTA copy honestly ("check a bet of your own, free")
   rather than positioning it as step one toward the card. No engineering
   change.
2. **Build a real free preview of the card** — e.g., today's already-graded
   picks, or last night's card, shown without a paywall. Matches the product
   being sold, but it's new engineering, not a copy change, and it changes
   what "3 free Bet Checks" means as a headline offer.
3. **Lead with founding access, which is already the primary paid CTA**
   (`web/landing.html:464`, "Get founding access") — drop the free-trial
   framing from the top of the funnel and lean on the receipts (the record,
   the ledger, the losers published) instead of a free sample to do the
   convincing. This is a framing change to a button already on the page, not
   a new path.

I lean toward (1) as the only one that ships today without new engineering,
with (2) as the stronger fix if it's worth building. This is a funnel
decision, not a wording one, and it's the owner's to make.

---

## Questions only the owner can answer

1. **Section 2's real loss** (the Phillies pick): approve using a real,
   specific loss — real teams, real score, real date — as the front-page
   proof-of-honesty example, knowing that its own numbers (56% vs. a 62%
   break-even at −165) mean the card published a pick that was behind on its
   own math before first pitch? That's true of the product by design, but it
   is a specific, checkable fact a skeptical reader could highlight.
2. **The CTA question above** — which of the three funnel options, if any.
3. **FAQ**: confirmed as no-change. Flag if there's a reason to revisit.
