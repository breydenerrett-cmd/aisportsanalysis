# Decision needed: which answer does Today give first?

**Bad news:** the app gives two different answers to "what do I bet tonight"
on the same screen. On both nights we can check, those two answers didn't
just disagree on the side of a bet — they named a different top game.

## What's on the page

The card (3–5 bets, ranked by market confidence — count and order are yours
to change) loads first. Tonight's Picks ("the slip" — ranked by how many
independent groups of systems agree, not a headcount) sits right below. Our
own rulebook (`docs/PRODUCT_DOCTRINE.md` §5) still says the slip should be
#1; never updated after the card shipped. Below both, the hero block (the
big headline panel) is chosen by yet another rule — biggest price gap vs.
fair value, the "cheapest price" framing you told us to retire —
undisclosed on screen.

## What I checked on disk

Two nights have both a real card and a slip that published something:
09-10 (our only settled night) and 09-11.

- **09-10:** slip's only pick — Pirates at White Sox, home side — wasn't on
  the card at all. Card's #1 was Yankees -1.5.
- **09-11:** slip published 6 picks; 4 named a card game — 3 same side, 1
  opposite (card had the Guardians, slip had the Twins, un-flagged). Slip's
  #1 (Brewers) was a different game than the card's #1 (Dodgers).
- **Both** nights: slip's #1 ≠ card's #1 — a different game, not a side.

**Records, kept separate, never added together:**
Card: one settled night, 2-1, up 0.54 "units" (a unit = a dollar staked at
even amounts) on 3 risked, +18%. One night is not a track record.
A group of research systems on paper — not the slip — has 299 settled bets:
150-140-9, +9.2 units on 290 risked, about +3%, barely above a coin flip.
That's the research group's number, not the slip's.
The slip itself has tagged only 7 bets "published" ever — too few for any
record. I'm not filling that gap with the 299.

**Tonight's hero:** 12 games priced tonight, 11 with enough books to compute
a fair line, and not one best price beats it — so the gap rule finds nothing
and the hero falls back to the earliest first pitch. The stored schedule
says that is Mets at Yankees, 1:35 pm ET (the page re-fetches the schedule
live, so a game missing from the stored map could in principle come
earlier). Either way it is not the price-gap rule tonight, and the page
doesn't say so.

## Options

| # | Option | Trade-off |
|---|---|---|
| **Slip placement** | | |
| A1 | Card leads; slip moved to the performance page, labelled research | Matches the code today; slip's 7-bet history is too thin to lead with |
| A2 | Remove the slip from Today | Simplest; loses a feed some customers may want |
| A3 | Keep both; add a line when they disagree | Keeps both; someone must build and maintain that line — needed now |
| **Hero pick** | | |
| B1 | Card's #1 game | Matches what you told us to lead with |
| B2 | Earliest first pitch | Already tonight's default, by accident not design |
| B3 | Keep price-gap rule, labelled on screen | Cheapest fix; still the retired framing, now disclosed |

## My recommendation (mine, not a fact)

**A1 + B1.** The card is what you told us to sell; the slip has 7 bets of
history, too thin to lead a page with — its record belongs on the
performance page. The hero should show the card's #1 pick.

## The decision

Slip: leads / removed / stays-with-a-note? Hero: card's #1 / earliest first
pitch / price-gap (labelled)?
