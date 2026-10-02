# UFC results: where an automatic grade can come from (2026-10-02)

Seven UFC picks were graded by hand on 2026-10-01 (5-1, 1 void, n=6 staked:
far too few to mean anything). Hand grading from two sources is an audited
stopgap. This is what was found when looking for an automatic source,
without spending anything or using any key.

| Source | Names the winner | Cancelled / no contest / draw | Cost | Status |
|---|---|---|---|---|
| The Odds API (already paid) | No | No | n/a | Its sports table has no scores for MMA. Not usable. Read on the provider's own page. |
| BALLDONTLIE MMA, fights endpoint | Yes (`winner`, method, round) | `canceled` is a documented status; how a draw or no contest is encoded is NOT documented | Free tier has events and fighters only, no fights. "ALL-STAR" tier, about $9.99 a month for this one sport | Provider written from the documentation; never run against the live service. Prices come from a summary of the pricing page and must be confirmed on the page before buying. |
| TheSportsDB | Not confirmed | Not confirmed | Free key or $9 a month | Could not confirm it carries UFC results. |
| Wikipedia | In prose and tables | In prose | Free | Allowed by licence; parsing is fragile. Kept as a manual source. |
| Sherdog, Tapology | Yes | Yes | Free to read | Terms not confirmed for automated reading. Manual only. |
| UFC.com | | | | Never: its terms ban automated and manual collection. |

## What is built

`python -m src.cli ufc autograde --date YYYY-MM-DD [--dry-run]`: published
fight (both names and the date, from the ledger) -> provider result ->
winner / draw / no contest / cancelled (including "a fighter was replaced, so
the published pairing never happened") -> the same grade the manual path
gives, with the provider, its fight id, the fetch time and its raw status
stored on the row. A partial or ambiguous name match grades nothing and is
listed for a person. A bout that already has a row is skipped, so a manual
entry is never buried, and a later manual row still overrides an automatic
one. Replaying the seven hand-graded picks through it gives the identical
result.

Without a key it prints BLOCKED and does nothing. Manual entry
(`ufc result`) works as before.

## Decision for Brey

1. First check the BALLDONTLIE account's billing page. It was on an
   all-access trial in mid-September. If it is being billed, either the MMA
   endpoint already works with the existing key (then nothing new to buy) or
   there is a charge to cancel.
2. If there is no active plan: the MMA tier at about $10 a month would
   replace hand grading. With one UFC card every week or two and seven picks
   so far, hand grading costs about ten minutes an event. Recommendation:
   do not buy it yet; keep grading by hand until UFC picks matter to a
   paying customer.
