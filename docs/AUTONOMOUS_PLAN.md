# Autonomous work plan — macro scale

**Written 27 Aug 2026**, after the clearest statement yet of what the tool is for.

## The reframe this plan is built on

The scanner outputs a **verdict**: flagged, or no play. That was right for "find obvious
mismatches" and it is too narrow for what was actually described:

> There's just so many different things that we should be aware of — this analysis tool
> should help digging into everything, it should be all in one, and it should tell
> degenerate gamblers who already know a lot about sports things that they're not even
> thinking about.

That is not a pick. It is a **briefing**. The unit of value is a *fact the reader did
not already have*, and the audience is explicitly someone who already knows a lot — so
the bar is not "true", it is **"true and not already in your head."**

Three consequences that shape everything below:

1. **The product is a per-game dossier, not a verdict.** The scanner becomes one voice
   in it rather than the whole output.
2. **A fact only earns space if it is surprising.** "The Dodgers are good" is true and
   worthless. Every fact needs a baseline to be measured against, or it is filler.
3. **A quiet day still produces a briefing.** "Nothing actionable, but here are three
   things you would not have known" is a good day's output.

## Architecture: detectors and a surprise ranker

The all-in-one goal is only tractable if the system is **many small independent parts**
rather than one growing model. So:

**A detector** looks at one narrow thing and either stays silent or emits one fact:

    {  claim:      one plain sentence
       value:      the number
       baseline:   what is normal, from the data
       sample:     how much it rests on
       surprise:   how far from normal, in noise units
       confidence: gated by sample size, never asserted   }

**The ranker** sorts a game's facts by surprise and shows the top few. A detector that
cannot state its baseline does not ship — without one there is no way to tell a finding
from a description.

**The sample gate is the whole product.** The most-quoted stat in betting is
batter-versus-pitcher history, and a live check today returned **2 at-bats**. A tool
that prints "he's 0-for-2 against this guy" is worse than useless. A tool that prints
"the 4-for-8 you are about to see is 8 at-bats and means nothing" is telling a
knowledgeable bettor something they are not thinking about. **Both directions count as
facts**, and the second is the harder and more valuable one.

## Track A — Foundation

The detector framework, the dossier assembler, the surprise ranker, and the sample-gate
policy. Nothing else can be built until a detector has a shape to conform to. Existing
scanner signals get rewritten as detectors so there is exactly one mechanism.

## Track B — Data acquisition

Each is verified as reachable and free unless noted.

| Source | Gives us | Status |
|---|---|---|
| Batter vs pitcher (`vsPlayer`) | Head-to-head history, and its sample size | Verified working |
| Home/away splits (`statSplits`) | Per-player home/road performance | Verified working — Judge is .996 OPS home, .834 away |
| Starting lineups (`hydrate=lineups`) | Who is actually playing, not just the roster | Verified working |
| Travel | Distance, time zones, road-trip length — derived from the schedule and park coordinates already stored | Buildable now |
| Bullpen usage | Who threw yesterday and the day before, and who is unavailable | Buildable from game logs |
| Umpire assignments | Strike-zone tendencies | Needs checking |
| Historical odds | Everything in `docs/RESEARCH_PLAN.md` Tier 2 | **Paid — see below** |
| Bet % / handle % | What the public is on, and therefore where the sharps are not | **Not available from any source we have** |

On that last row, honestly: The Odds API does not carry bet percentages, and the sites
that do are paid or need scraping. But **reverse line movement is partly inferable from
what we already collect** — a line moving *against* the side the price implies is public
money getting faded, and nine books of snapshots can see that without buying anything.
That is the honest version of "what the sharps are doing" and it is free.

## Track C — Detector families

Ordered by how much a knowledgeable reader would not already know.

1. **Sample-size debunkers.** Flag the small-sample stats a bettor is about to be shown
   elsewhere and say how thin they are. Cheapest to build, and possibly the highest
   value per line of code in the whole project.
2. **Split divergence.** A hitter or pitcher whose home/road, day/night, or handedness
   split is far enough from his own overall line to matter — measured against his own
   baseline, not the league's.
3. **Matchup history**, with the gate attached to every number.
4. **Fatigue and travel.** Third city in five days, a coast-to-coast flight, a bullpen
   that threw 4 innings yesterday.
5. **Lineup quality.** The gap the scanner currently cannot see, because it only knows
   pitchers and run differential.
6. **Streak and regression.** A team scoring far above its underlying rates is a fact
   about luck, not about quality — and it is the sort of thing that feels like
   information and usually is not.
7. **Park and weather interaction.** Weather is already collected and completely unused.

## Track D — Market intelligence

Distinct from the above: these are facts about the *price*, not the game.

- Store all nine books per snapshot instead of one. Currently discarding eight of nine
  quotes of data that cannot be recovered. **Highest-decay item in the project.**
- Line movement per book, and the disagreement between books.
- Reverse line movement detection, per above.
- Best available price at any moment — arithmetic, not prediction, and it applies to
  every bet from every strategy.

## Track E — Live

Game-state polling, and divergence detection against the pre-game priors: *"statistics
that just don't align with previous history."* Sequenced last, because a divergence
detector needs established priors to diverge from, and Tracks B and C are what produce
them.

## Track F — Validation, running continuously underneath

Flags keep logging and grading forward. Every new detector is pre-registered before it
runs. At roughly one flag a day, the 200 decided calls needed for a verdict is most of a
season, and no work in Tracks A–E shortens that clock.

## Hard stops for autonomous work

Carried forward unchanged, and they are not negotiable by me mid-run:

- No spending money. The subscription decision is yours.
- No bets, and no code capable of placing one.
- No tuning a threshold against results already seen.
- No re-evaluating the burned 2025 test split.
- No claiming an edge, ever, without forward evidence.
- Never fabricate a value. A blank field is correct; a guessed one is corruption.

## The purchase decision, corrected

I previously called this "$59 one time". That was wrong: it is **$59/month recurring**.
You can subscribe, pull the backfill, and cancel — but it is a subscription.

Measured credit costs for the backfill (10× multiplier on all historical requests):

| Backfill | Credits | Fits |
|---|---|---|
| 3 seasons, full-game ml+spread+total, closing only | 16,740 | $30 plan |
| 3 seasons, same, open **and** close | 33,480 | $59 plan |
| 1 season, first-five ml + total | 48,600 | $59 plan |
| 3 seasons, first-five ml + total | 145,800 | **Too big for $59** |

First-five is billed **per game** rather than per slate, which is why it dominates.

**Recommendation: one month of the $59 / 100K plan, then cancel.** In that month, pull
3 seasons of full-game prices at open and close (33,480) plus one season of first-five
(48,600) — 82,080 credits, comfortably inside 100K. The $30 plan cannot touch first-five
at all, which is the market that was named.
