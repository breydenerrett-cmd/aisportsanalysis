# Your Novak bets, live "comeback" plays, and my limits (2026-10-28)

Plain answer first: congrats on the win. But one win can't show that a bet type makes money, and the numbers we already
have on "back the favourite when they fall behind early" are losing so far. There is one real pricing slip in your
screenshots, and that's the part worth learning from.

## Your Novak bets

**The straight bets (-120, -137) after he lost set 1, 4-6.** The standard tennis math treats each set as a coin flip
weighted by how much better the player is. If Novak was about -300 before the match (75%), losing set 1 drops him to
about 45%, a fair price near +120. You got -120 (55%), so you paid about full price and won. -120 is only a fair price
if he was about -500 before the match. I don't have his real pre-match price. The tennis history study below checks
whether real favourites come back more often than this math says.

**The parlay (Over 2.5 sets + Novak wins, +136).** It was placed one minute after a -120 straight bet on Novak. If set 1
was already over, both legs were the same thing: Novak can only win from there by going to 3 sets. So DraftKings paid
+136 for an outcome it priced at -120 a minute earlier. On $200 that's $472 back instead of $367. With Novak at 45%,
+136 is a good bet and -120 is not. That's a pricing slip by the book, not a prediction. It's the only clear edge in
these screenshots.
Rule of thumb: when one leg makes the other certain, compare the parlay to the straight bet. Books do limit accounts
that keep hitting these.

## What we already know (recorded paper tests, rules written down before any bet)

| Live rule | Sport | Bets | W-L | Units |
|---|---|---|---|---|
| Favourite trailing after 3 innings | MLB | 10 | 4-6 | -1.6 |
| Starting pitcher pulled early | MLB | 86 | 31-55 | -8.4 |
| Favourite trailing at halftime | NFL | 0 | (written down, not recording yet) | |
| Favourite loses set 1 | Tennis | 0 | (built today, needs the Odds API key on this PC) | |

Both MLB samples are too small to be sure either way, but nothing in them points to an edge.

## My limits, honestly

1. **The books see the score before we do.** Their feeds come from the venue. Ours arrive seconds to a minute later.
   Anything that's just "react to the score", they have usually priced already.
2. **Live prices carry a bigger house cut** than pre-game, so a live bet has to be more wrong-priced to pay off long-run.
3. **Our odds feed has no same-game parlay prices and few live props**, so I can't scan for slips like the one above.
   You can, on the app.
4. **Props for every game in every sport** would burn the month's 100,000 Odds API credits in days, because each game
   and each prop market costs credits. We can do props for the games a hound actually bets.
5. **Small samples.** 46 hounds have 378 graded bets in all, and most hounds have under 30. That's too few to tell
   skill from luck.
6. **Me.** I can't watch games or see your sportsbook, and I can be confidently wrong. A fact-check once found 61 of 129
   claims in my own report wrong. That's why every idea goes through a recorded paper test before anyone trusts it.
7. **None of our pre-game tests found that our models beat the market.** The steady losses are mostly the house cut.

## Where more edge could come from (most real first)

1. **Book pricing slips** like the parlay. No model is needed, just consistency. Do it by eye live, for now.
2. **A comeback price table.** From free match history (tennis first: every pro match's set scores and pre-match
   odds): when a favourite at price X loses set 1, how often do they win? That turns into the live price worth
   taking. The tennis paper test then checks real live prices against it. Next: the same for MLB, NBA and NFL from
   free game histories.
3. **Old live prices.** The Odds API keeps price snapshots every 5 minutes going back to 2022. That should include
   games in progress, and I'll confirm it with one cheap request. That would let us test "favourite falls behind
   early" on thousands of past games instead of waiting months. It costs credits, and unused credits are lost at
   month end, so it's a good use of them.
4. **Shopping prices for your own bets.** The same bet often differs between books. Taking the best one is the most
   reliable gain there is.
5. **Deep reviews of every past bet** (news, injuries, analysts' takes) show which kinds of bets keep losing for
   reasons a rule could catch. They're being built now and turn on with your OK.

## Needed from you

- Odds API key on this PC (step 4 in `docs/owner/YOUR_STEPS_2026-10-28.md`): starts the tennis test.
- Yes to downloading the free tennis history: builds the comeback table.
- Yes to $25 once: deep reviews of every past bet and every hound.
