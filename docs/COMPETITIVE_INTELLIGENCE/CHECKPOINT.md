# Competitive checkpoint — 17 products, 2026-08-31

Synthesis over four research streams. Every figure traces to a segment doc;
where a worker could not verify something, this says so rather than smoothing
it over. Screenshot capture was blocked all session (proxy resets on every
navigation, reproduced against a control site), so **visual and UX claims are
text-sourced and weaker than the pricing and feature claims.**

---

## The one finding that should shape everything

**Across 17 audited products, not one has a third-party-audited record, and not
one makes publishing its own losses a headline promise.**

Every competitor's marketing promises *more* — edge, sharpness, accuracy,
profit. The most transparent product found (PropsBot.ai: timestamped,
closing-line-referenced, user-auditable) is still self-graded. The least
transparent (PropJuice.ai) advertises 75–80% accuracy while its own copy
admits an "initial development phase" with no disclosed sample size.

That is an empty position, and it happens to be the only one this project has
actually earned: 25+ pre-registered hypotheses, every loser published, a
falsification battery that killed our own best-looking candidate.

**But the same finding cuts against us.** It is only a differentiator once it
is true of us *in the customer's view*, not just in `docs/`. Today our honesty
lives in a static HTML page and a pile of markdown. That gap is the work.

---

## Price range

| band | who | what it buys |
|---|---|---|
| under $10 | **nobody found** | — |
| $10–20 | Outlier Premium $19.99, Props.Cash $19.99, LineMate $14.99*, Action PRO week pass $14.99 | single-purpose tools |
| $20–35 | **thickest band** — Rithmm Core $29.99, Outlier Premium+ $29.99, Action PRO $24.99, BetQL tiers from $19.99 | the category default |
| $35–60 | Rithmm Pro $49.99, BetQL Sharp $49.99, PlayerProps.ai $59.99 | all-sport / "AI" tiers |
| $60–100 | only 2 confirmed | thin |
| $100+ | Outlier Pro $79.99 → Betstamp PRO $249 base, up to ~$477 loaded | professional / B2B |

*LineMate's website and its App Store listing show different prices. Unresolved.

Annual: PlayerProps.ai $499.99, Props.Cash $199.99 (promo $119.99), Rithmm
Core $239.99 / Premium $999.99, Action PRO $119.99.

**Your proposed pricing, against the evidence.** ONE SPORT at $29.99/mo lands
*exactly* beside Rithmm Core at $29.99 — which is all-sport. Same price, fewer
sports, is a messaging problem to solve deliberately rather than discover after
launch. ALL SPORTS at $49.99–59.99 sits beside Rithmm Pro, BetQL Sharp and
PlayerProps.ai, and $499/yr is nearly identical to PlayerProps.ai's $499.99.
The bands are crowded; there is no room to win on price and no reason to try.
The sub-$10 band being empty is a real signal — nobody believes this audience
buys cheap tools.

---

## Best in class, by dimension

- **Best product breadth:** OddsJam (though Cloudflare-walled to our research,
  so secondary-sourced and flagged UNVERIFIED throughout). Notably it is not an
  independent startup — its parent was acquired by Gambling.com Group for $80M
  plus an $80M earnout.
- **Best professional workflow:** Betstamp, which has quietly repositioned its
  main brand as a B2B pricing-and-data layer while keeping the free consumer
  tracker alive as a separate product.
- **Best marketing:** Rithmm — it is the only product in the AI segment with a
  real AI-chat feature ("Scout") rather than an AI claim, and its App Store
  reviews show users articulating the value in workflow terms.
- **Most honest methodology:** PropsBot.ai, and it is still self-graded.
- **Most instructive packaging idea:** BetQL prices by *sport count*, which
  none of the preliminary leads mentioned and which is directly relevant to
  your one-sport/all-sport split.

## Worst common weaknesses

1. **Sample size is absent.** Grepping Props.Cash's and LineMate's live
   production JavaScript found **zero** occurrences of "sample size", "small
   sample", "denominator" or "disclaimer". LineMate ships filter categories
   titled **"100% Hit Rates"** gated by a hard-coded **three-game minimum**.
2. **"Edge" and "+EV" are used without disclosure.** None of six sharp/odds
   products discloses, on the page making the claim, that best-price-versus-
   consensus is normally negative once vig is accounted for, or that a
   displayed price is often not takeable at size. Where that disclosure exists
   at all it lives in secondary blog content.
3. **Executability is unaddressed.** RebelBetting is the only one that
   proactively coaches users on handling limits and bans — an implicit
   admission the edge is not durably executable at one book.
4. **No independent verification anywhere.**

## What users actually complain about

From ~1,700 dated App Store reviews across nine products (Reddit was
unreachable behind its anti-bot wall all session — the single biggest evidence
gap in this checkpoint, and where the richest workflow material normally
lives):

- **Billing and cancellation practices** — charged after cancelling, charged
  during "free trials". Dozens of independent reports across OddsJam, Rithmm,
  Pikkit, Action Network, BetQL. This is the loudest complaint in the corpus
  and it is not about product quality at all.
- **"Coin flip"** — a strikingly standardised framing repeated across four
  unrelated products, meaning the picks feel no better than chance.

Both are trust failures. Neither is solved by a better model.

## The 10-tab problem, quoted

> "I used to use like 8 different websites to do my research on what to bet on
> and it would take me 1-2 hours and now it takes 2 seconds." — Rithmm review

> "I had to go to other sites to get like head to head match ups and weather
> impact of stadiums." — Rithmm review

> "Instead of having to open a thousand pages on my web browser and having to
> hunt for the stats, Oddsjam has it all in place." — OddsJam review

Only four independent quotes were found, so this is **thin evidence, honestly
labelled**. It points the right way but does not yet carry weight.

---

## Where we win today

- **Sample-size skepticism**, which the two leading prop tools do not do at all
  and one actively sells against.
- **Evidence labels** — a refuted idea cannot render as an open one.
- **Negative evidence and counterargument**, which nothing found offers.
- **Honest price framing** — price improvement kept distinct from EV, with the
  vig-negative reality stated on the page rather than buried.
- **Methodological depth** nobody else has: point-in-time reconstruction, a
  falsification battery, placebo noise ceilings, published nulls.

## Where we lose today

- **There is no product.** No accounts, no auth, no payments, no URL. Static
  HTML on a container's filesystem (see `docs/PRODUCT_ARCHITECTURE_AUDIT.md`).
  Every competitor listed above beats us on this, absolutely.
- **One sport.** Competitors at our proposed price cover all of them.
- **No bet tracking, no sync, no alerts, no community, no mobile.**
- **No props** beyond a capped feasibility probe.
- **No brand, no name.**

Stated plainly: we have the best evidence engine and no product, against
competitors with real products and no evidence.

---

## Top product opportunities, ranked by our ability to win them

1. **Bet Check** — paste "Yankees ML -125", get market context, best price,
   supporting AND contradicting evidence, sample quality, warnings. Nothing
   found does the contradicting half.
2. **Bet Debunker** — challenge the user's own reasoning ("7-for-18 is
   nothing"). Directly attacks the "100% Hit Rates" pattern.
3. **What matters tonight** — 3–5 ranked facts instead of a stat dump. Built.
4. **What changed** — news/lineup/roster timeline with market state before and
   after, answering "has the market already reacted?" Built.
5. **Why did this line move** — event timeline against book response.
6. **Honest price improvement** with the vig explanation on the page.
7. **Matchup decomposition** — lineup versus actual starter profile. Built.
8. **Published track record** with pre-committed selections — the audited
   record nobody has.
9. **Research methodology, visible** — the nulls as a feature, not an
   embarrassment.
10. **Strategy autopsy / noise ceiling** as a user-facing idea eventually:
    "here is why this pattern is probably luck."

Note how many are *built and unexposed*. The bottleneck is not analysis.

## Top 5 differentiators

1. Evidence labels + sample size on every claim, structurally enforced.
2. Contradicting evidence — reasons NOT to bet.
3. Price improvement framed honestly, never as EV.
4. A published, pre-committed, auditable record.
5. Visible methodology, including published failures.

## Pricing recommendation

Do not compete on price; the bands are crowded and the cheap band is empty for
a reason. The defensible position is **$29.99 one-sport / $49.99 all-sport**,
matching the category rather than undercutting it, with the **one-sport tier
justified by depth rather than by being cheaper** — because at $29.99 the
customer is comparing against Rithmm Core's all-sport offer and will notice.
A professional tier is credible later (Betstamp PRO reaches ~$477) but only
with something a professional cannot get elsewhere. Week passes are an
established norm (Action PRO $14.99, PlayerProps.ai $20) and are the cheapest
way to let skeptics test a claim of honesty.

**Do not launch subscription pricing while billing complaints are the loudest
signal in the category.** Trivial cancellation, no dark patterns, and a
visible refund stance would be differentiating on their own.

---

## Names and brand — nothing selected

Finalists only, pending domain recheck, collision and trademark search, App
Store checks, pronunciation, multi-sport fit, and consumer testing:
**Ledgerline**, **Quiet Signal**, **Coverage Grid**. Ruled out with cause:
Marketline (live collision in our exact positioning), Fieldnote (trademarked
notebook brand), Passline (craps term), Fair Line (yacht brand), Deep Slate
(Minecraft block), Vantage, Meridian, Tempo Desk.

**Brand territory finding:** terminal/data-layer language exists in this
category only in B2B products at $200–800/month. No self-serve consumer
product uses that register. The white space is **terminal register at consumer
access** — not "terminal" alone. The restrained-palette half of the hypothesis
is *unconfirmed*, since competitor visuals could not be captured; restraint
should be a positive choice, not framed as contrarian to something unverified.

## What should change in the roadmap

1. The product gap is now the largest unbuilt thing in the project, and it is
   conventional engineering rather than research risk.
2. Ship the honesty **in the product**, not only in `docs/`. Transparency that
   customers cannot see is not a differentiator.
3. Treat billing conduct as a product feature.
4. Prioritise Bet Check and Bet Debunker — highest differentiation per unit of
   work, and both mostly assemble existing pieces.
5. Re-run the Reddit and screenshot research from an unblocked environment;
   both gaps are known and neither is fatal.
