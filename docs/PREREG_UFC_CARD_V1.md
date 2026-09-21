# PREREG: UFC_CARD_V1

**Registered:** 2026-09-21, before any UFC pick has been published or graded.
**Rule id:** `UFC_CARD_V1` (`src/analysis/ufc_card.py`, `RULE_ID`).
**Sport:** `mma` (`src/sports/mma.py`; The Odds API sport key
`mma_mixed_martial_arts`).
**Status:** free, public, clearly labelled "being tested, bet at your own
risk" (docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md S5.1). Never
sold. No "proven edge" language anywhere on this card, ever (owner ruling).

This document exists so nobody can quietly pick "the rule that happened to
win" after the fact -- every number below is fixed in code
(`src/analysis/ufc_card.py`) and in this file before UFC Fight Night
2026-09-26, the first card this rule will ever see.

## 1. Market

Moneyline (h2h) only -- the only market The Odds API's
`mma_mixed_martial_arts` key confirms coverage for today. No method-of-
victory, no round totals.

## 2. Minimum books

A bout is evaluated only when **at least 3 books** quote it
(`MIN_BOOKS = 3`). Fewer than that and the bout is never looked at -- not
"found nothing", never evaluated. This is deliberately looser than NFL's
5-book minimum (NFL_CARD_V2): UFC boards in the US carry fewer active
books than NFL boards, and a 5-book floor would leave most bouts on a
12-14-fight card unjudged.

## 3. Consensus, not leave-one-book-out

For each side, the **consensus probability** is the mean, across every
book quoting the bout, of that book's own price with the vig removed by
the **proportional** method (`src.core.odds.devig_two_way(method=
"proportional")`) -- a single method, not NFL_CARD_V2's three-method
agreement rule. UFC boards are thin enough (often exactly 3-4 books) that
removing one book from its own consensus (leave-one-book-out) would swing
the number most on the bout that most needs it to be stable, so this rule
uses the plain, full-board mean instead.

The **average American price** per side is the plain arithmetic mean of
the American prices themselves across the same books. This is the number
the card is graded at (see item 9) -- not the best single book's price.

## 4. Candidate rule

A bout produces **at most one candidate**:

  a. The **consensus favourite** (the side with the higher consensus
     probability) is the candidate if its average price is **better than
     -200** (e.g. -110 through -199 qualify; -200 or worse never does --
     owner ruling, applied here exactly as it is in NFL_CARD_V2); otherwise

  b. **Either side** priced from **+100 to +150** whose consensus
     probability is **at least 0.45** is the candidate.

If the favourite qualifies under (a), that is the bout's candidate and (b)
is never checked for that bout -- one pick per bout, never both a
favourite pick and a dog pick on the same fight.

A bout whose favourite is worse than -200 AND whose underdog is outside
+100 to +150, or inside that range but under 45% consensus, produces no
candidate at all. On a typical UFC card most bouts will fall here -- this
is a deliberately sparse, cautious rule, exactly like NFL_CARD_V2's own
1-candidate-in-100-instants result. **A 12-14-fight card publishing 0-2
picks is the rule working as designed, not a bug**
(docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md S5.1).

## 5. Ranking

Candidates are ranked by **consensus probability**, most confident first.
**The product picks the most CONFIDENT outcomes, not the best price**
(owner ruling) -- this is why ranking is by probability, not by price or
by expected value.

## 6. Cap

At most **5** picks published per card (`MAX_PICKS = 5`), same cap as
NFL_CARD_V2.

## 7. Lock

Each bout locks **90 minutes before ITS OWN commence_time**
(`src/sports/mma.py`'s `lock_lead_hours = 1.5`, applied through
`src.appstate.card_ledger.publish`/`locked_game_ids` exactly as every other
sport's per-game lock works). A UFC card is one long session (several
hours, prelims through main event); locking per bout rather than for the
whole card at once means an early prelim's pick can lock hours before the
main event's does, and a locked pick is carried forward verbatim on every
later publish of that date -- it cannot be edited once locked.

## 8. Fighter changes

If a bout's fighter pair changes after its pick has locked, **the pick is
VOID**. This is enforced at settlement (`src.report.ufc_card.
settle_for_date`), not at selection: a manually-entered result
(`src.pipeline.ufc_results`) is matched to a locked pick by the two
fighters' names, in either order. If the fighters who actually fought are
not the two names the pick locked on, no result is found for that pick,
and it grades VOID through the same "no final score" path any postponed or
unscored game already uses (`src.appstate.card_ledger.grade_pick`).

## 9. Grading price

Each pick is graded at **the average (consensus) American price across
books at lock** -- the same number computed in item 3 and stored on the
pick -- never the best single book's price (owner ruling).

## 10. Results and other void cases

There is no legal, free, bulk source of UFC results to grade against
(docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md S5.2, S5.5) --
`data/historical/ufc_results.jsonl` is filled by a person, via `python -m
src.cli ufc result`, reading a result from a news or broadcast source
(never UFC.com, whose Terms of Use ban both automated AND manual
monitoring). A **draw**, **no contest**, or **cancelled** bout grades every
pick on it **VOID** -- none of those settle a moneyline bet either way,
the same way a push has no equivalent in a two-way moneyline market.

## What this rule does and does not claim

A pick here is a statement that the market's own consensus, once the vig
is removed, rates this fighter as the more likely (or, for a qualifying
dog, a market-underrated) winner -- not a claim of proprietary insight or
a fighter-rating model. UFC_CARD_V1 has no fighter-strength model of its
own (`model_probability` is always `null`); its fair price is the market's
own consensus. Whether prices selected this way win over time is exactly
what the forward, publicly-graded record exists to find out -- and as of
this registration, it has graded zero picks.
