# Linehound Community Feed: one-page offer (draft, revised 2026-10-01)

Status: DRAFT for Brey's sign-off. Price and guarantee are recommendations.
Nothing here claims an edge; the product is the public grading, not a win
rate. The deliverable is `scripts/discord_feed.py` (posts the nightly card
and the public record into a Discord channel through a webhook) plus the
web record page.

## Who it is for

Gaming, FiveM and creator Discord servers whose members already bet on
sports and argue about picks in chat. The owner wants a daily, credible
post that is not a tout screenshot, and something members come back for.

## Problem

Every pick page a community sees is a highlight reel: winners posted after
the fact, losers deleted, records nobody can check. Members get burned,
the server owner gets blamed, and the channel dies.

## Promise

A nightly card posted in your server before first pitch, and the record
graded in public the next morning, losses included. Every pick is written
to a hash-chained public ledger before the game, so nothing can be edited
or quietly removed. Members can open the record page themselves and see
every night since the rule went live: wins, losses, pushes, voids, units.

What the feed posts, in your channel, automatically:
- The card for tonight (MLB now; NFL on game days), each pick with the
  price and the market's own number next to ours.
- The public record for the current rule and the retired rule, shown
  apart, counted exactly as registered (regular season only; postseason
  picks are shown but not counted).
- The plain disclaimer on every post: analysis only, bet at your own risk,
  no pick is a prediction of profit.

What it does not do: promise wins, hide losses, or place bets.

What a server should expect to see, said before they pay: the rule is
strict, so some nights the card is all labelled fills (entries shown to
round the card out, never counted in the record), and in the NFL the
counted picks have run at about one a week. The feed never posts an entry
priced at -200 or shorter. In October the content is the MLB postseason
nightly and NFL game days; after the World Series it is NFL only.

## Timeline

- Day 0: you create a webhook in the channel you choose and send the URL
  (or we set it up on a call in five minutes).
- Day 0, same night: the first card posts before first pitch; the first
  graded record posts the next morning.
- Every day after: automatic. If the feed misses a night, you see the
  gap in the ledger too.

## Price (recommendation)

- 7 days free in one channel of the server. Nothing is charged and no card
  is taken for the free week; billing starts only if the owner says yes.
- Founding community price after that: $149/month per server, month to
  month, cancel any time. Locked for as long as the server stays subscribed.
- Public community price after the first six servers: $249/month.
- No per-member fees. Members who want the full site get the consumer
  plan ($19.99/month beta, `docs/PRICING_OFFER_VALIDATION.md`) with a
  server-specific code, not included in this price.

Why $149: it covers the product's entire monthly data and hosting cost with
the first sale, sits well under what a server owner pays for one sponsored
post, and is low enough to decide on a DM without a call.

## Guarantee (recommendation)

Delivery, not results: if the feed posts fewer than 90% of scheduled cards
in a calendar month, that month is free. No refund is tied to wins or units,
because nobody can promise those, and we say so on the page.

## The DM

The scripts Brey sends, by hand, are in `docs/sales/scripts.md` (three
variants, two follow-ups). That file is the only copy; do not paste an older
DM from this page's history.

## Objections and honest answers

- "Do you win?" The record page shows every night since the rule went
  live, wins and losses, counted the way it was registered. Read it before
  you pay. We do not claim an edge.
- "Is this a tout?" No. Picks are published before the game, hash-chained,
  and never edited. The losers stay on the page.
- "What if there are no games?" Off-days post nothing; the record page
  still shows the count.
- "Can members bet through it?" No. Analysis only.

## Owner steps before the first sale

1. Approve the price, the free week and the guarantee above (or change them
   here).
2. Create the demo server and add the Discord webhook secret
   (`docs/DISCORD_FEED.md`).
3. Take the first payment by a Stripe payment link for the $149 product
   (a link is fine here: a community has no site login to unlock, unlike
   the $19.99 plan, which must go through the site's own checkout).
