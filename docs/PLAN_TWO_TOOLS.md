# Two tools: the Analyzer and the Ranker

## Context — the whole story, from nothing

**What we set out to do.** Build software that finds MLB bets worth making, and
that explains itself well enough that a knowledgeable bettor learns something.

**What exists today.** Real infrastructure, all working:

- Four seasons of game results, 2.7 million individual pitches, starting-pitcher
  logs, bullpen usage, posted lineups, ballpark data.
- A paid odds subscription with ~53,000 credits left. We have every price from
  ~18 sportsbooks, several times a day, back to 2023.
- Eleven "detectors" — small programs that each look for one specific thing
  (a lefty-heavy lineup against a pitcher who struggles with lefties, a bullpen
  that pitched three days straight, a team that just flew across the country).
- A dashboard that turns all of it into a readable page, one card per game.
- A daily loop that runs itself: collect prices, build the page, log what it
  would have bet, settle yesterday's games, grade the record.

**The hard part, and why it matters.** A betting system can fool you in a dozen
ways, and almost all of them make it look *better* than it is. So we built the
guardrails first:

- *No peeking.* When testing on 2023 data, the system may only use information
  that existed before that game started. We found and fixed a real leak: the
  stats service we were using silently returned full-season numbers no matter
  what date you asked for. Everything got rebuilt from raw pitch data instead.
- *Decide before you look.* Write down what you are testing and what would
  count as success, then test. Otherwise you test thirty ideas, one works by
  luck, and you convince yourself it was the plan all along.
- *Correct for hunting.* Test enough ideas and some will look great by chance.
  There is standard math for this and we apply it.
- *Publish the losers.* Always.

**What we found.** We ran two full rounds.

*Round one — eleven baseball ideas.* Every one failed. None of them predicted
game outcomes better than the betting market already did.

*Round two — five market ideas.* Different question: forget out-analyzing the
bookmakers, do the bookmakers contradict *themselves*? Published academic work
says betting lines overreact and give some back, and that late prices are
sometimes worse than earlier ones. We tested all five on data we already had.
Cost: zero. Result: all five failed too. One looked spectacular — an 18% return,
odds of 1-in-160 against luck — and then died under the kill-tests we had
committed to in advance: it was essentially one sportsbook, in one season, in a
narrow slice. Without those tests we would be betting real money on noise.

**Why this is not a surprise.** Independent researchers tested 1,547 simple MLB
betting strategies. About 0.45% were profitable at a strict significance
level — which is *the rate you get from pure chance*. The MLB moneyline is one
of the most efficient betting markets in existence. Our two null results agree
with the best evidence available.

**Where that leaves us.** Thirteen ideas, zero edges. That is an honest,
valuable finding: we know what does *not* work, and we know the machinery that
found that out is trustworthy. What we do not have is a way to beat the market.

**So we split into two products**, because they need different standards of
proof and mixing them is how honest tools become dishonest ones:

- **The Analyzer** — deep, readable analysis of any matchup. Its job is to make
  a bettor *better informed*. It does not need a proven edge to be valuable,
  the same way a good scouting report does not need to guarantee wins.
- **The Ranker** — a daily list of the best bets available. Its job is to make
  *money*. It absolutely does need a proven edge, and until one exists it stays
  in the garage.

Brey's decision: **hold the Ranker until something is proven.** So this plan
builds the Analyzer now, builds the evidence machine that could unlock the
Ranker, and specifies the Ranker fully so it can ship the day it is earned.

---

## Part 1 — The realistic route to an actual edge

Ranked by how likely each is to work, given everything we now know.

### 1. Information timing — the strongest remaining candidate

Not "we understand baseball better." Instead: **something happens, and the
market takes time to react.** A star is scratched, a lineup posts, a closer
lands on the injured list, wind shifts at a small park. Books update on a delay
and on smaller markets they update slowly.

This is the one hypothesis that does not require us to be smarter than anyone.
It requires us to be *earlier*.

It also needs three things we did not have until now:
- Dense price sampling — **already running**, every 15 minutes before games.
- Timestamped events — the news layer this plan builds.
- A way to measure "how long did the price take to move after the event" —
  new, and the whole point.

**This is where the next real research family lives.** It is testable forward,
free to collect, and it is what the deferred lineup-release idea was really
about.

### 2. Less efficient markets

The MLB moneyline is the hardest market on earth to beat. It is also the only
one we have tried. Materially softer, in rough order:

- **First-five innings** and alternate lines — fewer bettors, less attention.
- **Player props** — far more markets, far less sharp money on each.
- **KBO and NPB** — Korean and Japanese baseball. Fewer sharps, lower limits,
  slower books, and *identical* analysis machinery to what we have already
  built. Brey has already said all sports eventually.

Nothing here is guaranteed. But hunting in a soft market with mediocre tools
beats hunting in the hardest market with mediocre tools.

### 3. Line shopping — boring, real, available today

Not an edge in the predictive sense, and it is worth more than most claimed
edges. If eighteen books average +100 on a side and one offers +108, taking the
+108 every time is worth roughly 2% on turnover. That is larger than nearly
every "edge" people sell.

It requires no forecast, no model, and no luck. It is pure execution. We already
compute every piece of it. **This is the honest core the Ranker will eventually
be built on**, and it is the reason the Ranker is worth specifying now.

### 4. Standing on other people's work

Concretely, in order of value:

- **Academic literature** — largely mined. It gave us round two. The remaining
  useful papers are about market microstructure, not baseball.
- **Public projection systems** — open-source and public MLB projections
  (Marcel-style baselines, public Statcast-derived models). The test is cheap
  and specific: does any free public projection beat the closing line? Almost
  certainly not — but if one does, that is a finding we get for the price of an
  afternoon, and it is literally using someone else's strategy.
- **What sharp syndicates actually do** — they do not publish. But the shape is
  known and consistent: enormous market coverage, fast execution, tiny edges
  taken thousands of times, aggressive line shopping. Notably that is much
  closer to route 3 than to any clever insight.
- **Public betting percentages** — would unlock a real family of contrarian
  strategies. Still **blocked**: no source we can access provides them, and
  inferring public sentiment from price movement invents the data.

### What we will not do

Build more detectors of the round-one kind. Twenty more "this team travelled
far" ideas will produce the same null, and the evidence for that is now both
external and our own.

---

## Part 2 — The Analyzer

**One sentence:** everything worth knowing about tonight's game, in plain
English, with the sample size attached and the noise called out.

Built on the existing `brief` command and `src/report/dashboard.py`, which
already produce a solid per-game page.

### What makes it worth using

1. **It tells you when your reasoning is wrong.** Already partly built and the
   most distinctive thing here. A bettor sees "he's 7-for-18 against this
   pitcher" and feels informed. The tool says: that is 18 at-bats, it means
   nothing. Yesterday it caught its own version of this — a starter "averaging
   1.00 innings" who had made exactly one start.
2. **Sample size on every claim**, always visible.
3. **Evidence labels** on every claim, so a refuted idea can never be mistaken
   for an open one.
4. **"No play" is a real answer**, and most nights it is the right one.

### Work items

**A1 — News and roster layer** *(free MLB feeds first, web search second)*

New `src/providers/mlb_news.py` + `src/pipeline/news.py`:
- MLB transactions endpoint (free): trades, call-ups, options, releases.
- Injured-list status and roster moves per team.
- Lineup scratches: compare posted lineup against expected regulars.
- Every item timestamped, because a news item without a time cannot be used in
  a backtest and cannot be used to test information timing.

*Why MLB feeds first and web search second:* MLB's own feed is reliable, free,
and — critically — **replayable**, so a claim built on it can be validated the
way everything else here is. Web-search news cannot be replayed honestly, so a
system built on it can never be proven. We just spent two research families
learning what unvalidatable inputs cost. Feeds form the backbone; web search
becomes enrichment on top, for the handful of games already flagged as
interesting, clearly marked as unverifiable colour rather than evidence.

**A2 — Matchup depth** *(Jacob's unit-vs-weakness idea)*

The decomposition, finally: this lineup's specific hitters against this
pitcher's specific pitches, aggregated with counts shown. Handedness
interaction. Bullpen handedness against the batters likely to bat late. All the
underlying data exists in the rebuilt pitch store; this is presentation and
aggregation, not new collection.

**A3 — Narrative quality pass**

Rewrite finding text to read like a sharp friend talking, not a stat dump.
Every claim keeps its number and its sample.

**A4 — Any-matchup mode**

Today the tool analyses tonight's slate. Extend to arbitrary matchups:
`analyze --home BOS --away NYY` for any historical or hypothetical pairing.

**A5 — Report polish**

Print/share view, per-game permalinks, a season-long "what this tool told you"
archive.

---

## Part 3 — The Ranker (specified now, gated on evidence)

**One sentence:** the day's bets ordered by how much value each one carries.

**Status: GATED.** Per Brey's decision it does not publish a bet list until
something is proven. This section defines exactly what "proven" means so the
gate is a fact rather than a judgement call.

### The two engines, deliberately separate

**Engine 1 — Price value.** No forecast required. Compare the best available
price on each side against the de-vigged consensus of all books. When one book
is meaningfully better than the market's own average, that gap is real money
regardless of who wins.

This is honest today. Most of it already exists in `_fair()` in
`src/model/selections.py` and the `stale_book` detector.

**Engine 2 — Predicted value.** Requires an edge. We do not have one. Empty
until we do.

The Ranker's output is Engine 1 × Engine 2. With Engine 2 empty, it ranks
nothing — which is correct and is why it stays gated.

### What unlocks it

All four, no exceptions:
1. A pre-registered hypothesis clears significance *and* effect-size gates on
   discovery data.
2. It survives the falsification battery — dose-response, per-book split,
   per-season split, subgroup checks. (Round two's candidate died here.)
3. It holds on forward data it was never fitted to, over 300+ selections.
4. Brey signs off on freezing the decision policy.

### Built in the meantime (no edge claimed)

**B1 — Price engine as a library.** Best-available-vs-consensus, per game, per
market, with the fair price and the gap. Used by the Analyzer immediately to
show "the best number on the board right now."

**B2 — Forward ledger hardening.** Already running. This is the record that
eventually satisfies unlock condition 3.

**B3 — The Ranker page, empty and honest.** Ships showing exactly what it is:
the price-value list, plus a plain statement that no predictive edge exists yet
and therefore nothing here is a recommendation to bet.

---

## Part 4 — How the two tools connect

Separate products, one shared spine.

```
        shared data + detectors + price engine
                       |
        +--------------+--------------+
        |                             |
   ANALYZER                       RANKER
   depth, per matchup             breadth, per day
   ships now                      gated on evidence
   "understand this game"         "where is the value"
```

- The Analyzer explains **one game deeply**. The Ranker scans **every game
  shallowly**. Same underlying facts, opposite shape.
- The Ranker's price engine feeds the Analyzer's market section today.
- The Analyzer is where a Ranker entry gets justified: click a ranked bet, land
  on that game's full report.
- **They never share an evidence standard.** The Analyzer may show an unproven
  observation clearly labelled. The Ranker may not rank on one. That asymmetry
  is the whole reason they are two tools.

---

## Part 5 — Autonomous work order, next few days

Sequenced so nothing blocks on a decision from Brey.

**Day 1 — News layer (A1)**
MLB transactions + IL + roster provider, timestamped store, historical backfill
for 2023–24, tests. Surface in the Analyzer as a "what changed" section.

**Day 2 — Research Family V3 pre-registration: information timing**
The strongest remaining candidate. Pre-register before looking, as always.
Measure: after a roster/lineup event, how long until books move, and how far?
Uses the dense snapshot grid now running plus Day 1's timestamps. Free.

**Day 3 — Matchup depth (A2) + price engine (B1)**
The decomposition Jacob asked for, and the honest price-value library.

**Day 4 — Public projection benchmark**
Cheap, specific test of route 4: does any free public projection system beat
the closing line? Report either way.

**Day 5 — Narrative pass (A3), any-matchup mode (A4), Ranker shell (B3)**

**Continuous throughout:** daily loop, dense snapshots, forward ledger, credit
discipline, everything committed and pushed, `docs/OVERNIGHT_RUN.md` current.

**Standing rules, unchanged:** no real-money betting and no bet-placement code;
never fabricate a value; never leak future information; 2025 is tuning-only
forever; the sealed 2026 set stays sealed without explicit approval; losers
always published; nothing labelled proven without the evidence.

---

## Verification

- `python3 -m unittest discover -s tests -q` green at every commit (1,059 now).
- News layer: point-in-time test — inject a transaction dated after a game,
  assert it never appears in that game's analysis.
- Price engine: hand-checked against known odds, and the de-vig must sum to 1.
- Analyzer: `python3 -m src.cli brief --date <today>` opens from `file://`,
  no server, zero script tags.
- Ranker shell: asserts it publishes no bet recommendation while Engine 2 is
  empty — a test, so the gate cannot be removed by accident.
- `artifacts/demo_latest.html` stays untouched.
