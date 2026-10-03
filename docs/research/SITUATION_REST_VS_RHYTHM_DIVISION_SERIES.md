# Rest versus rhythm in the Division Series

**Status: PRE-REGISTRATION, written and committed before any Game 1 result, series result or score
for the series in the sample was read. The results section at the bottom is empty until the run.**

This is the first factor test of the situation layer (`docs/SITUATION_LAYER_PLAN.md`: "each factor
family is also tested on past seasons before it carries weight"). It is a research note, not a card
rule: it changes no pick, gate or published result, and nothing in it is an edge.

## 1. The idea, and what is being asked

The idea (the owner's, from a conversation about playoff picks, "momentum over rest"): in the
playoffs a club that has played recently is sharper than one that has sat for days. In the Division
Series the two cases sit side by side. A club with a **bye** did not play the Wild Card round; its
opponent came through it. So:

> In a Division Series between a bye club and a club that played the Wild Card round, does the bye
> club do worse than its regular-season strength and home field predict (rhythm beats rest), better
> (rest helps), or the same?

- **H0 (null).** The bye club wins Game 1 and the series at the rates its regular-season record and
  home field predict.
- **H1 (rhythm beats rest).** It wins fewer than predicted.
- **H2 (rest helps).** It wins more than predicted.

The test is **two-sided**: it does not assume the owner's direction. The primary measure is the
**series result**; Game 1 (the bye club's first game back, where rest against rhythm should show most)
is reported beside it.

## 2. The sample, fixed before the outcomes

Every Division Series in the data from **2015 to 2025** (the window the brief set; 2012 to 2014 are not
used and are not added later). Two sources, the same shape:

| Seasons | Source |
|---|---|
| 2023 to 2025 | the results store (`data/historical/mlb_results.csv`, which starts 2023-03-30) |
| 2015 to 2022 | MLB's free Stats API, into a **display-only** store (`data/research/postseason_history/`, `src/situation/postseason_history.py`), never a training population |

The Stats API was also fetched for 2023 to 2025 as a check on the parser: all **131** postseason games
match the results store on date, clubs, round and both scores (zero differences). The standings'
regular-season records equal the results store's regular-season games for 86 of 90 club-seasons; the
other four (LAD and SD in 2024, LAD and CHC in 2025) differ by exactly two games, because the
results store starts after the opening series in Seoul (2024) and Tokyo (2025). The standings are the
authority and are what the test uses.

**Who counts as "bye" and "played".** A club that appears in no Wild Card game of that season had a
bye, but only when the whole Wild Card round is in the data and decided; otherwise it is unknown and
the series is left out and listed. A club that appears in a Wild Card game played.

Counted from team names, rounds and dates alone (no score, winner or series result was used, printed
or looked at), the 44 Division Series of 2015 to 2025 are:

| Season | Division Series | Bye v played (in the test) | Bye v bye | Played v played |
|---|---|---|---|---|
| 2015 | 4 | 2 | 2 | 0 |
| 2016 | 4 | 2 | 2 | 0 |
| 2017 | 4 | 2 | 2 | 0 |
| 2018 | 4 | 2 | 2 | 0 |
| 2019 | 4 | 2 | 2 | 0 |
| 2020 | 4 | 0 | 0 | 4 |
| 2021 | 4 | 2 | 2 | 0 |
| 2022 | 4 | 4 | 0 | 0 |
| 2023 | 4 | 4 | 0 | 0 |
| 2024 | 4 | 4 | 0 | 0 |
| 2025 | 4 | 4 | 0 | 0 |
| **Total** | **44** | **28** | **12** | **4** |

Before 2022 a single Wild Card game left the other two division winners in each league rested
against each other (bye v bye: no contrast, left out); 2020 had no byes at all (every club played the
Wild Card round: left out); from 2022 both Division Series in a league pit a bye club against a
Wild Card winner. **The sample is 28 series.** In all 28 the bye club hosted Game 1.

## 3. The yardstick, fixed before the outcomes

What would the standings and home field predict? For each series (`src/situation/rest_vs_rhythm.py`):

1. **Strength.** Each club's regular-season win rate that year (the standings).
2. **Neutral chance** the bye club beats the other: log5, `(a - ab) / (a + b - 2ab)`.
3. **Home edge**, applied to the odds: two equal clubs give the home club **0.53**
   (`HOME_FIELD_WIN_RATE`). That is the regular-season home win rate of the seasons the results store
   holds, 2023 to 2025 (.521, .522 and .543 over 7,285 games, .529 together), rounded. The earlier
   regular seasons are not in the data here and were not measured. One number for every game of every
   season, so that no season picks its own yardstick. (A first draft of this note said 0.54 and called
   it the recent seasons' round figure. It was checked against the store before any outcome was read,
   did not match, and was changed. This paragraph is the only place the constant was revised.)
4. **Game 1:** the bye club's chance as the home club.
5. **Series:** the chance of winning first to three with the series' own home pattern (the club that
   hosted Game 1 hosts games 1, 2 and 5), computed exactly.

Observed minus expected bye-club wins, summed over the 28 series, is the measured effect. Significance
is the **exact two-sided Poisson-binomial** test (twice the smaller tail, capped at one), at
**p < 0.05**. Nothing is fitted; nothing here has a free parameter except the 0.53.

**One sensitivity, declared now.** A record is a noisy measure of strength, and the clubs with byes
are the ones with the best records, so an unshrunk record overstates their edge and biases the
yardstick against them (a result that says "the bye clubs underperformed" is partly a result about
that overstatement). The sensitivity run pulls both clubs' win rates **one third of the way back to
.500** before predicting. The third is an assumption, labelled as one; the primary result does not
use it. If the two disagree about significance, both are reported and the primary stands as the
answer to the question asked.

## 4. What the sample can and cannot see

Computed from the records and the schedule only (still no outcome):

| | Expected bye-club wins | Standard deviation | Swing that reaches p < .05 |
|---|---|---|---|
| Game 1 | 16.4 of 28 (58.4%) | 2.6 wins | about 18 points |
| Series | 17.1 of 28 (61.2%) | 2.6 wins | about 18 points |
| Sensitivity, Game 1 | 15.8 of 28 (56.6%) | 2.6 wins | about 18 points |
| Sensitivity, series | 16.2 of 28 (57.8%) | 2.6 wins | about 18 points |

The bye clubs averaged a .615 regular-season win rate and their opponents .562. **Only a swing of
about eighteen points in the bye club's series win probability could reach p = 0.05 with 28 series.**
A null therefore means "this sample could not see an effect of ordinary size", never "rest does not
matter". An effect of a few points is far below what 28 series can detect, and **this test cannot
confirm or refute the owner's idea at that size**. What it can do is catch a large effect, and it is
the only test the history allows: there are no more Division Series to add.

## 5. The decision rule, fixed before the outcomes

- **p < .05 on the series result:** reported as a finding in the direction it points, with the
  sample size and the sensitivity beside it. It would be written into the analyst's guidance by name
  (and then watched forward, in arm B's ledger, which is the real test).
- **Anything else:** reported as a **null**, in those words, with the swing the sample could have
  seen. Nothing in the prompt names rest or rhythm as an effect (the prompt says how to weigh the
  situation, not what it does); a null adds no claim and removes none. "Bye or played" stays in the
  record as a fact the analyst can see.
- No second look, no subgroup, no new yardstick after the numbers. A different cut (a sweep against a
  three-game Wild Card series, a particular round, a particular year) would be a new hypothesis with
  its own registration, not a rescue of this one.

## 6. What is not available, said plainly

- **The market's price.** For each Game 1 the report has a column for the market's price. Our closing
  moneylines exist for **2026 only**, so no series in 2015 to 2025 has one and the column reads
  "none" in all 28 rows. The first Division Series that can carry a price is 2026's, which has not
  been played. The test cannot say whether the market already priced rest or rhythm; that needs
  prices, and is the question the forward ledgers (arm A against arm B) can eventually answer.
- Lineups, injuries and who actually started are not in the data. The starters in the store are the
  starters the schedule listed.
- **Threats to a clean reading:** regular-season record is a coarse measure of playoff strength (the
  bye club's best starters pitch Games 1 and 2, the other club's were used in the Wild Card round,
  which is itself a mechanism for "rest" that this test does not separate from rhythm); the
  yardstick treats games as independent; the home edge is one number for all seasons; 28 series is
  thirty-odd draws of a coin.

## 7. What was known before the data was opened

Stated so it can be discounted. The builder of this test had a general, unchecked impression that bye
clubs have not dominated recent Division Series, which is part of why a null was expected and why the
design reports the size of effect the sample could see. No series in the sample was looked up, and
the display store's games were fetched and checked for agreement with the results store without
printing a score.

## 8. How to reproduce

```
python3 -m src.cli situation ingest-postseasons --start 2015 --end 2025   # polite, cached; writes data/research/postseason_history/
python3 -m src.cli situation rest-vs-rhythm                               # the table and the test
python3 -m src.cli situation rest-vs-rhythm --json                        # everything, machine readable
python3 -m unittest tests.test_situation_rest_vs_rhythm tests.test_situation_history
```

`tests/test_situation_rest_vs_rhythm.py` rebuilds the pairing, the yardstick (against independent
hand and brute-force arithmetic), the test and the verdict wording from a small fixture world, with no
disk and no network.

## 9. Result

*(Added after the run, 2026-10-03. Everything above was committed first, as `5be98154`; the one change
to it since is this section.)*

**A null result.** Across 28 Division Series with one club on a bye, the bye club won Game 1 more
often than the standings and home field predict and the series less often. Neither difference is
close to the bar, and a sample this size could only have seen a swing of about 18 points.

| | Bye club won | Expected from record and home field | Excess | Two-sided p |
|---|---|---|---|---|
| Game 1 | 19 of 28 (67.9%) | 16.4 (58.4%) | +2.6 wins (+9.4 points) | 0.41 |
| **Series** (primary) | **15 of 28 (53.6%)** | **17.1 (61.2%)** | **-2.1 wins (-7.6 points)** | **0.52** |
| Sensitivity, Game 1 | 19 of 28 | 15.8 (56.6%) | +3.2 wins | 0.31 |
| Sensitivity, series | 15 of 28 | 16.2 (57.8%) | -1.2 wins | 0.79 |

By the rule in section 5 the primary result (p = 0.52) is a null and is reported as one. The sensitivity
run agrees with it on significance in both measures (it moves the series excess toward zero, as a
shrunk yardstick should).

**What it says, in plain words.**

- If rest cost the bye club its rhythm, Game 1, the bye club's first game back, is where it should
  show. It shows the opposite: the bye clubs won Game 1 in 19 of 28, about 2.6 wins more than
  expected. The standard deviation of that count is 2.6 wins, so this is one standard deviation, the
  kind of gap chance produces about two times in five.
- The series result leans the other way: 2.1 wins fewer than expected, which is under one standard
  deviation (2.6 wins). The two measures point in opposite directions, which is what noise does.
- Nothing here supports "momentum over rest" and nothing refutes it. **A swing of about 18 points a
  series would have been needed to reach p = 0.05; an effect of a few points, the size a real one
  would more plausibly have, is invisible at 28 series.** The null is "this sample could not see an
  effect of ordinary size", not "rest does not matter".

**The series, as played** (expected figures are the yardstick's, from the clubs' records and the home
pattern; the price column is the closing moneyline, which this test could not have):

| Season | Bye club | Played the Wild Card | Game 1 | Series | Expected G1 | Expected series | Price |
|---|---|---|---|---|---|---|---|
| 2015 | STL | CHC (won its Wild Card game) | bye club won 4-0 at home | bye club lost 1-3 | 0.549 | 0.547 | none |
| 2015 | KC | HOU (won its Wild Card game) | bye club lost 2-5 at home | bye club won 3-2 | 0.586 | 0.615 | none |
| 2016 | CHC | SF (won its Wild Card game) | bye club won 1-0 at home | bye club won 3-1 | 0.633 | 0.701 | none |
| 2016 | TEX | TOR (won its Wild Card game) | bye club lost 1-10 at home | bye club lost 0-3 | 0.567 | 0.581 | none |
| 2017 | LAD | ARI (won its Wild Card game) | bye club won 9-5 at home | bye club won 3-0 | 0.600 | 0.641 | none |
| 2017 | CLE | NYY (won its Wild Card game) | bye club won 4-0 at home | bye club lost 2-3 | 0.599 | 0.640 | none |
| 2018 | BOS | NYY (won its Wild Card game) | bye club won 5-4 at home | bye club won 3-1 | 0.583 | 0.610 | none |
| 2018 | MIL | COL (won its Wild Card game) | bye club won 3-2 at home | bye club won 3-0 | 0.561 | 0.570 | none |
| 2019 | HOU | TB (won its Wild Card game) | bye club won 6-2 at home | bye club won 3-2 | 0.601 | 0.644 | none |
| 2019 | LAD | WSH (won its Wild Card game) | bye club won 6-0 at home | bye club lost 2-3 | 0.613 | 0.665 | none |
| 2021 | TB | BOS (won its Wild Card game) | bye club won 5-0 at home | bye club lost 1-3 | 0.581 | 0.606 | none |
| 2021 | SF | LAD (won its Wild Card game) | bye club won 4-0 at home | bye club lost 2-3 | 0.537 | 0.524 | none |
| 2022 | ATL | PHI (won the Wild Card Series 2-0) | bye club lost 6-7 at home | bye club lost 1-3 | 0.617 | 0.672 | none |
| 2022 | NYY | CLE (won the Wild Card Series 2-0) | bye club won 4-1 at home | bye club won 3-2 | 0.574 | 0.594 | none |
| 2022 | HOU | SEA (won the Wild Card Series 2-0) | bye club won 8-7 at home | bye club won 3-0 | 0.631 | 0.696 | none |
| 2022 | LAD | SD (won the Wild Card Series 2-1) | bye club won 5-3 at home | bye club lost 1-3 | 0.668 | 0.759 | none |
| 2023 | LAD | ARI (won the Wild Card Series 2-0) | bye club lost 2-11 at home | bye club lost 0-3 | 0.628 | 0.692 | none |
| 2023 | ATL | PHI (won the Wild Card Series 2-0) | bye club lost 0-3 at home | bye club lost 1-3 | 0.618 | 0.674 | none |
| 2023 | BAL | TEX (won the Wild Card Series 2-0) | bye club lost 2-3 at home | bye club lost 0-3 | 0.599 | 0.640 | none |
| 2023 | HOU | MIN (won the Wild Card Series 2-0) | bye club won 6-4 at home | bye club won 3-1 | 0.549 | 0.546 | none |
| 2024 | CLE | DET (won the Wild Card Series 2-0) | bye club won 7-0 at home | bye club won 3-2 | 0.571 | 0.587 | none |
| 2024 | NYY | KC (won the Wild Card Series 2-0) | bye club won 6-5 at home | bye club won 3-1 | 0.579 | 0.604 | none |
| 2024 | LAD | SD (won the Wild Card Series 2-0) | bye club won 7-5 at home | bye club won 3-2 | 0.562 | 0.571 | none |
| 2024 | PHI | NYM (won the Wild Card Series 2-1) | bye club lost 2-6 at home | bye club lost 1-3 | 0.567 | 0.581 | none |
| 2025 | MIL | CHC (won the Wild Card Series 2-1) | bye club won 9-3 at home | bye club won 3-2 | 0.561 | 0.570 | none |
| 2025 | SEA | DET (won the Wild Card Series 2-1) | bye club lost 2-3 at home | bye club won 3-2 | 0.549 | 0.546 | none |
| 2025 | PHI | LAD (won the Wild Card Series 2-0) | bye club lost 3-5 at home | bye club lost 1-3 | 0.549 | 0.547 | none |
| 2025 | TOR | NYY (won the Wild Card Series 2-1) | bye club won 10-1 at home | bye club won 3-1 | 0.530 | 0.511 | none |

**Left out (16 of the 44):** the 12 bye-against-bye series of 2015 to 2019 and 2021, and the four
2020 series where every club had played the Wild Card round. No series was left out for an open
result, an incomplete Wild Card round or a missing record.

**The price.** As registered, no series has a closing price (our closing moneylines exist for 2026
only), so every Price cell reads "none". One related fact, found while checking: the historical odds
archive (`data/archive/historical/odds_history/`, three snapshots a day) reaches early October in
2023 to 2025 and holds a pre-game moneyline for all twelve Game 1s of those years: within about six
hours of first pitch for the eight of 2024 and 2025, and about two days before for the four of
2023, whose snapshots stop on October 5. A snapshot is not a closing line and it was not joined here;
it is what a later test would use to ask whether the price already held the standings. Twelve games
could not answer that either.

**What follows for the layer.** Nothing is added to or removed from the prompt: it says how to weigh
the situation, not what the situation does. "Bye or played" stays in the situation record as a fact
(`rest_and_rhythm.previous_round`) the analyst can see and cite, with the sample it rests on. The
real test of whether the analyst does better for seeing it is the side-by-side (arm A without the
situation layer, arm B with it, `docs/SITUATION_LAYER.md`), which can start with the 2026 Division
Series if the owner turns the switch on.

**Checks on the run.** The 131 postseason games of 2023 to 2025 the Stats API returned are identical to
the results store's (date, clubs, round, both scores). The pairing, the yardstick (against independent
hand and brute-force arithmetic), the exact test and the verdict rule are in
`tests/test_situation_rest_vs_rhythm.py`, and the store's ingest in `tests/test_situation_history.py`;
both run on fixtures with no disk and no network.
