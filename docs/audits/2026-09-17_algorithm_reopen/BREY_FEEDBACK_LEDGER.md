# Brey's feedback, chronologically, in his own words

Written 2026-09-17 as part of the algorithm-reopen audit.

**Why verbatim.** Summarising owner feedback into "wants better algorithms" is
how direction gets lost. Several entries below were acted on incorrectly the
first time precisely because they were paraphrased. Where a quote is recovered
from this session's conversation it is exact; where it is reconstructed from a
commit or doc, that is marked.

**Coverage warning, stated first.** This ledger is built from (a) the session
conversation of 2026-09-15 to 2026-09-17, which is verbatim, and (b) commit
messages and docs that record earlier decisions second-hand. Feedback given
before 2026-09-15 is therefore reconstructed, not recovered, and anything from
a ChatGPT session or a verbal conversation is **UNKNOWN** to this document. A
reader should not treat the early entries as complete.

---

## The through-line

Read in order, Brey has said one thing many ways since at least 2026-09-10:
**the product must find good BETS, and the system keeps finding likely
WINNERS instead.** Almost every correction below is a restatement of that,
and the system kept mistaking it for a threshold-tuning request.

---

## Entries

### 2026-09-10 to 09-14 — reconstructed, not verbatim

| Field | Content |
|---|---|
| FEEDBACK | Direction toward a published daily card: 3-5 MLB picks, frozen before first pitch, graded publicly. Props added 09-12, totals 09-14 ("merge every bet, not just moneylines" — quoted inside `web/js/cardrecord.js`'s own comment). |
| SYSTEM WAS DOING | Building the card and its ledger. |
| CHANGED AFTER | Card V1 shipped and began publishing. Props and totals joined it. |
| IMPLEMENTED? | Yes. |
| CURRENT RELEVANCE | High — this is the live product. |

### 2026-09-15 — "best bets, not best favourites". THE CENTRAL ONE.

| Field | Content |
|---|---|
| FEEDBACK | Verbatim, with five card screenshots: *"I'm not feeling confident that our best picks for the day are showing not only strong confidence but also good value... The goal is to find the best bets for the day, not the best favorites. If the price is -200 or higher, it's typically not going to be a good bet... the 3-10 bets for the day are the best of the best of the best of the best bets. Not only are they -150, -115, +100, or higher, but they wouldn't be any lower than -150 or -160."* |
| SYSTEM WAS DOING | V1 ranking candidates by MARKET confidence, with no price test at all. |
| CHANGED AFTER | Diagnosis written; V2 designed with a price band and a value×probability score. |
| IMPLEMENTED? | **PARTIALLY, and this is the single largest open gap in the project.** V2 is built, tested, calibrated and NOT REGISTERED as of 2026-09-17. V1 still publishes. |
| CURRENT RELEVANCE | Highest. Measured 09-17: 48 of 48 graded picks were favourites, half beyond his stated limit, seven at -200 or worse, worst -230. He was right and the ledger now proves it. |

### 2026-09-15 — underdogs and the value algorithm

| Field | Content |
|---|---|
| FEEDBACK | Verbatim: *"BOOM KEY QUESTION! Theres a lot of times where the underdog actually makes more sense than the favorite and those are the real bangers, vegas doesnt always get the stats right... especially UFC when we get to it there so many underdogs, and same with finding +100 to +250 picks offer really good value"* and *"even confidence of 30-45+ percent if high enough value (+150, +200 etc etc) we need an algorithm of value x confidence / likelihood"*. |
| SYSTEM WAS DOING | Publishing only favourites. |
| CHANGED AFTER | V2's ranking key became `score = p − (1−p)/(d−1)` — a Kelly fraction on the marked-down probability, which IS value × probability as one number — with a required edge that widens with the price. |
| IMPLEMENTED? | Built, not live. |
| CURRENT RELEVANCE | Highest. This is the algorithm he asked for, sitting unregistered. |

### 2026-09-15 — freeze the calibration

| Field | Content |
|---|---|
| FEEDBACK | "Freeze it now" (AskUserQuestion answer), on being told V1's calibration was refit nightly on the sealed window. |
| SYSTEM WAS DOING | Refitting nightly on data overlapping what it was graded against — a leak. |
| CHANGED AFTER | Refit stopped; `docs/CARD_CALIBRATION_FREEZE_2026-09-15.md`. |
| IMPLEMENTED? | **Yes, verified 2026-09-17** by walking every commit touching the file: last refit 21:04Z on 09-15, before the ~22:35Z order; the 09-16 and 09-17 loops left it alone. |
| CURRENT RELEVANCE | High, and under-appreciated: cards published 09-10 to 09-15 ran under the leak. Their results are in question, not just the bad days. |

### 2026-09-15 — try strategies, not bet-sizing tweaks

| Field | Content |
|---|---|
| FEEDBACK | Verbatim: *"Can we try both strategies and see which one is profitable? These are the types of strategies that we should be changing not necessarily just the type of betting strategy like changing these differences are strategy changes."* |
| SYSTEM WAS DOING | Offering threshold and cap choices. |
| CHANGED AFTER | The four-arm variant family (A1-A4) was designed. |
| IMPLEMENTED? | Built 2026-09-17 (`src/analysis/card_variants.py`). Unregistered. |
| CURRENT RELEVANCE | High. Note the tension with the next-but-one entry: he wants to SEE which is winning; the registration refuses a running arm scoreboard. |

### 2026-09-16 — home underdog is not a strategy

| Field | Content |
|---|---|
| FEEDBACK | Verbatim: *"home underdog is a BEYOND IDIOTIC STRATEGY with no research behind it, no strategies that can be back tested will prove, our systems and analysis take into consideration metrics and recent history and stats and matchup and bullpen analysis and bench analysis and all the things a backtest couldn't do"* |
| SYSTEM WAS DOING | Running SR1, a home-underdog price-band family. |
| CHANGED AFTER | SR1 killed on its own evidence (band A −3.51pp 2023; band B sign-flipped +7.77 to −2.14). I partly disagreed at the time — a backtest CAN use matchup and bullpen features where point-in-time values exist; the blocker was 2023/24 data, not method — and said so. |
| IMPLEMENTED? | Yes, killed. The broader lesson took until 2026-09-17 to land as policy (Stage 19's mechanism requirement). |
| CURRENT RELEVANCE | High. His objection was to single-factor strategies with no mechanism, and he was right about that class. |

### 2026-09-16 — the live sniping system, private

| Field | Content |
|---|---|
| FEEDBACK | Verbatim: *"This live bet version is for me and me only I want to have a Claude built system that's watching all live tennis matching and nba games managing a paper account for now simulated trying to snipe obvious bets like Carlos Alcaraz down 1-0... second set ML would be a cake walk... if it's -200 or higher should be considered."* |
| SYSTEM WAS DOING | Nothing live. |
| CHANGED AFTER | `docs/SNIPE_SYSTEM.md` designed; live MLB pipeline rebuilt. |
| IMPLEMENTED? | Partially. The tennis half is now narrowed to MATCH WINNER because API-Tennis was measured and skipped 2026-09-17 — his exact second-set bet has no licensed source. |
| CURRENT RELEVANCE | High, and the substitution is a real loss of the thing he asked for. |

### 2026-09-17 — the record page question that found the real problem

| Field | Content |
|---|---|
| FEEDBACK | *"How did we go from +small units wins to -5 units in the last 2 days? Something is just not correct here."* Earlier the same day, on units and percentages: *"I'm just confused on what your math is and how you're getting there and how you're gonna advertise that to the customers because anybody would look at that."* |
| SYSTEM WAS DOING | Showing game picks at 60.7% and negative units, with no combined figure, and an unlabelled ROI. |
| CHANGED AFTER | ROI relabelled "ROI PER UNIT STAKED", a unit defined, an EVERYTHING TOGETHER panel added (the three true panels never stated their sum; the headline overstated the book by 4.05 points). Then the price analysis that produced `docs/PRICE_BAND_EVIDENCE_2026-09-17.md`. |
| IMPLEMENTED? | Yes. |
| CURRENT RELEVANCE | Highest. His instinct located the central finding, twice. |

### 2026-09-17 — stop asking, take charge

| Field | Content |
|---|---|
| FEEDBACK | Verbatim: *"I need you to take over, take charge, and make the correct choices. I need you to figure out how to test different strategies, not just 'let's bet on the home team every time.' I don't need fucking retarded strategies. I need you to forward test different strategies every day... We're looking for player props. We're looking for things that we can find statistics on, historical data, and make an accurate estimate of what's going to happen using some sort of algorithm that we've come up with. I just don't need to be answering these questions for you. You need to be solving them."* |
| SYSTEM WAS DOING | Putting three registration questions to him. |
| CHANGED AFTER | Questions 12-14 decided by Claude under delegation and recorded as such (`docs/PREREG_CARD_V2.md` §15b). Stage 19 written: mechanism-required proposal gate, props-led, daily forward testing, deaths published. |
| IMPLEMENTED? | Decisions recorded; Stage 19 planned, not built. |
| CURRENT RELEVANCE | Highest — it is the standing operating instruction. |

### 2026-09-17 — the principle, stated plainly

| Field | Content |
|---|---|
| FEEDBACK | Verbatim: *"exactly why we dont just pick the favorites or no underdogs, thats just never gonna be a winning strategy hence why were looking for VALUE and PROBABILITY algorithm"* |
| CURRENT RELEVANCE | This is the project's objective function in one sentence, and it should be treated as such. |

---

## What he has asked for that is NOT built

Ranked by how long it has been outstanding:

1. **V2 live.** Asked 09-15. Built, calibrated, unregistered as of 09-17. Every day it stays unregistered, the card publishes prices he explicitly ruled out.
2. **A view of which strategies are working.** Asked repeatedly. Refused for the card family on multiplicity grounds (a decision I made and must justify); owed via Stage 19's published kills, which are not built.
3. **Player-prop strategies from statistics and history.** Asked 09-17. Stage 19 S4 is a plan, not code.
4. **Live sniping, tennis second-set.** Asked 09-16. Narrowed to match-winner — a substitution, not the thing.
5. **Text/alert delivery.** Mentioned in the snipe design. UNKNOWN whether ever built; not observed this session.
6. **UFC.** Named 09-15 as a later want. Nothing exists.

## Where the system has repeatedly misread him

A pattern worth naming, because it will recur:

- He says something directional and slightly imprecise ("-200 or higher is typically not a good bet").
- The system converts it into a THRESHOLD question and asks him to pick a number.
- He answers the number, but the underlying complaint — *rank by value, not by how sure the market is* — goes unimplemented for days.

The fix is not to ask fewer questions. It is to identify the MECHANISM behind
his objection and change that, then tell him what changed. On 2026-09-17 he
said this explicitly and it should be treated as a standing correction.
