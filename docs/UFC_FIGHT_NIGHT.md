# UFC fight night: a written read of every fight on the next card

Built 2026-10-03. The owner paused the UFC favourites card the same day
([`docs/decisions/UFC_FAVOURITES_PAUSED.md`](decisions/UFC_FAVOURITES_PAUSED.md)) and
asked what the page should do instead:

> "Which fighter is fighting what fighter? What are their weaknesses? What are their strengths?
> Any data or history or historical matches or momentum? Are we doing actual work here?"

The UFC page now shows the next card bout by bout. Each bout has both fighters, their records,
the price, a written read (the biggest difference in the fight, each fighter's strengths and
weaknesses, how each could win, the history between them, what the price says, what would change
the read and what could not be used) and a collapsible fact sheet. It sits **under** the
"picks are paused" notice, which is kept exactly as it was.

It is a description. It is not a prediction, not advice, not a pick, and not a claim that any price
is wrong. It publishes no probability of its own (the only probabilities on screen are the
market's, with the bookmaker's margin taken out and labelled as the market's). It changes no card,
ledger, record or pause rule, and it does not touch any fingerprinted file. We have not tested
whether figures like these beat UFC prices, and the read says so in every market view.

## Where it lives

| Piece | File |
| --- | --- |
| The read (pure, stdlib; one fact sheet in, one read out) | `src/analysis/ufc_read.py` |
| The route: `GET /ufc/fight-night` and `/ufc/fight-night/{event_id}` | `api/ufc_fights.py`, mounted in `api/app.py` |
| The page: one panel per bout | `web/js/ufcfights.js`, called from `web/js/main.js` under `renderCard` |
| Styles (`.uf-` rules, 390px safe) | `web/css/ufcfights.css`, linked in `web/index.html` |
| The facts it reads | the data layer: `src/datasvc/ufc/matchup.py`, [`docs/datasvc/UFC_FEATURES.md`](datasvc/UFC_FEATURES.md) |
| Tests | `tests/test_ufc_read.py`, `tests/test_ufc_read_golden.py`, `tests/test_api_ufc_fights.py`, `tests/test_web_ufc_fight_night.py` |
| Golden fixture and its regeneration | `tests/fixtures/ufc_read_golden.json`, `scripts/regen_ufc_read_fixtures.py`, `tests/_ufc_real_fixture_store.py` |

## The route

```
GET /ufc/fight-night                  the next UFC card
GET /ufc/fight-night/{event_id}       any event in the store, by id
        ?sheet=full (default)         the data layer's whole fact sheet per bout
        ?sheet=compact                what the page draws from it (about a third of the size)
```

**Sign-in.** The same gate as `/data/v1`: the router depends on `require_paid_access` itself and is
not in `api/app.py`'s `_authed_paid` group, so `APP_PUBLIC_DEMO=1` cannot open it (tested in a
subprocess with the variable set: 401). A signed-out reader of the page gets the shared sign-in gate
under the paused notice, not a blank.

**Which event is "next".** The rule of `GET /data/v1/ufc/upcoming`: status `scheduled` or
`in_progress` and started no more than 36 hours ago, soonest first. Dana White's Contender Series
is a development show whose fighters have no UFC fights on file, so it is never the default (it is
picked only when nothing else is upcoming), and it is listed in `other_events` and can be opened by
id. The match is on the event name containing "contender series"; it is one line
(`is_development_show`) if the owner wants a different rule.

**Response.**

```
{
  "event":  {event_id, name, short_name, date_utc, status, bout_count, development_show} | null,
  "bouts":  [ one per bout, main event first (match number ascending), see below ],
  "missing_bout_ids": [...],         bouts the event lists that the bouts file does not hold
  "reason": null | "No UFC event is scheduled in our data right now." | "This event has no bouts on file yet.",
  "data_updated_utc": newest fetched_utc among the event, its bouts and their prices (or among every event
                      when there is none); null when there is no data at all,
  "other_events": [ {event_id, name, short_name, date_utc, status, bout_count, development_show}, ... ],
  "label":  "A written description of this fight built only from the figures on this page. ...",
  "generated_utc": stamped per request
}

bout = {
  bout_id, match_number, card_segment, date_utc, weight_class, scheduled_rounds, status, title_bout,
  fighter_a / fighter_b: {fighter_id, name, nickname, record: {wins, losses, draws} | null, stance, weight_class},
  result:  null | {outcome: decided|draw|no_contest, winner_id, winner_name, method, method_words, detail, end_round, end_time_s},
  odds:    null | the data layer's compact odds (open and current moneyline, current rounds line; no method market),
  sheet:   the matchup fact sheet (full or compact) | null,
  read:    the written read | null,
  unavailable: null | "plain reason the sheet or read could not be built"
}
```

**No event** is a 200 with `event: null`, the reason and `data_updated_utc`, so the page can say when the
data was last updated and link the UFC record. An unknown id is a 404; an unreadable dataset is a 503 with a plain
message (no path, no traceback) and is remembered for that store version, exactly as `/data/v1` does.

**Fail soft.** A bout whose sheet cannot be built (a fighter not named yet, no start time, a bug) is still
listed with its fighters and the reason in `unavailable`, and the rest of the card is served. An exception's text
never reaches the client; it is logged with an `error_id`. A cancelled or postponed bout is listed and not read.
One exception: an unreadable dataset is the whole card's problem and is a 503, not fourteen bouts that "could not be
built" behind a 200.

**Loaded once.** Production has run out of memory from whole-store reads per request, so this route reuses the
data API's one store holder (`api.datasvc.holder`: one `UfcStore` per process, swapped only when a dataset file's
modification time or size changes) and builds each event's payload once per store version under the store's lock
(`store.view`). A request after that costs a `stat()` of the six dataset files and a shallow copy. Nothing that
varies with the clock is baked into the cached payload: the read is built without a "now" (so it never says "these
prices are N hours old"), and `generated_utc` is stamped per request. Tested: each dataset is read once across many
requests, six concurrent first requests read each file once, and a changed file is picked up on the next request.
On the real data a whole card (14 bouts, every dataset loaded cold) builds in about 0.16 s and a repeat in 0.03 s.

**Size.** A full payload for a 14-bout card is about 700 KB of JSON, the compact one (which the page asks for) about
475 KB, 34 KB a bout, most of it the read's evidence entries. The read's evidence paths point into the full sheet; a
client holding the compact one reads each entry's label and value.

**Bouts that are not upcoming any more.** `matchup()` finds only a bout whose status is `scheduled`. So for a finished
or in-progress bout (tonight's card, once it is under way, or a card opened by id after it ended) the route builds the
sheet as of that bout's own start and attaches the bout and its prices with the data layer's own public helpers
(`bout_summary`, `bout_odds`). The read therefore always describes the fight going in, never the result: the fight itself
is never one of its "previous meetings", and the read says "This bout is listed as final. The read describes the fight
going in and does not use how it turned out." A finished bout's result is printed beside it as a plain fact.

## The read

`build_read(sheet, now=None)` takes one `matchup()` sheet and returns:

```
headline          the single biggest difference in the fight, one sentence, or "no single difference ..." (a valid read)
headline_trait    which rule made it
notices           no booked bout; the bout is already under way or over
data_depth        how much is on file for each fighter, and one verdict: thin | fair | solid
a, b              per fighter: strengths[], weaknesses[], paths_to_victory[], context[]
context           stance, and how often each fighter's fights have gone to the scorecards
history           previous meetings, shared opponents with the result of each fighter against them
market_view       the margin-free chances, line movement, rounds line, method split, whether the facts point the
                  same way, and the plain statement that the price is more likely right when inputs are thin
what_would_change_it   up to three things
missing           every absent, thin or failed input, in plain words
```

Every strength, weakness and route is `{trait|route, family, size, sentence, sample, sample_level, thin, down_weighted,
caveat, evidence[], weight}`. `evidence` entries are `{path, label, value}`: `path` is a dotted path into the sheet,
`value` is read from that path (never typed), and a number the read worked out itself (a net strike rate) is flagged
`derived` and its path points at a field it came from. `tests/test_ufc_read.py` resolves every path of every read it
produces against its sheet and compares the value.

One deliberate difference from the brief's wording: lists of "edges" are called strengths, weaknesses and routes. The
product's language tripwire (`tests/test_customer_language.py`) forbids the word as a customer noun, and this module's
strings are inside its scan.

### Names

Full names everywhere. A last name is not reliable: ESPN lists some fighters family name first (the main event's Wang
Cong, whom the card calls Wang), names carry particles (Dos Anjos) and suffixes, and two fighters can share one (two
Silvas). A wrong short name on a fighter is worse than a longer sentence. No gendered pronoun appears in any sentence.

### Samples: thin is the normal case, and it is said out loud

UFC fighters fight two or three times a year, so a store that starts in 2024 holds a handful of fights for most of
them (on the first backfill: a median of two; only 16 of 863 fighters had five fights with a recorded method). Every
figure carries its own sample (fights and fight minutes, from the sheet), and the read uses three levels:

| Level | Rates, accuracies, defences, control | Shares of results (finishing, record, fight length, schedule) | Takedown defence also needs |
| --- | --- | --- | --- |
| thin | under 3 fights or under 30 fight minutes | under 5 fights | under 10 attempts against the fighter |
| fair | 3 fights and 30 minutes | 5 to 9 fights | 10 attempts |
| solid | 6 fights and 60 minutes | 10 fights | 20 attempts |

The thin floors are the data layer's own (`MIN_FIGHTS_TIMED`, `MIN_MINUTES_TIMED`, `MIN_FIGHTS_RESULTS`,
`HARD_TO_TAKE_DOWN_MIN_ATTEMPTS`), imported, so the two can never drift (a test asserts it). Solid is twice the floor.

A thin item is **shown and labelled**: a THIN SAMPLE chip in the warning tone, its sample (fights and minutes) in the
sentence and in a chip, and a caveat sentence under it, never behind a toggle. It is down-weighted: ranking multiplies
the size (slight 1, moderate 2, large 3) by 0.3 for thin, 0.6 for fair, 1.0 for solid, so a large gap on thin data
(0.9) ranks below a moderate gap on fair data (1.2).

**Display floors.** Below these a figure is not shown at all, thin or not, because one fight is an anecdote and
"finishes fights, 1 of 1" reads as a trait when it is a single result: a rate needs 2 fights, a share of results needs
3. The record and the last fights are still printed as plain context, and the missing list says the figures were held
back and from how many fights. (The first draft of this module did show them; running it on the real Rosas v Barcelos
fixtures produced four "moderate" weaknesses for the winner of a main event from one fight, which is why.)

### The rules, thresholds and reasons

Every threshold is a design choice made before looking at any result, never tuned against results, and none is a betting
claim. Where the data layer already has a bar (a style label), the read uses the same number. Sizes below are for the gap
between the two fighters unless a rule is about one fighter. The "typical" figures are descriptive percentiles of the
first backfill (2024 to 2026), looked at to place round numbers sensibly, not against outcomes.

| Rule (trait) | What it compares | slight / moderate / large | Reason |
| --- | --- | --- | --- |
| `striking_net` | net significant strikes a minute (landed minus absorbed), the gap between the two fighters' nets | 1.5 / 3.0 / 5.0 | Middle half of fighters land 2.7 to 4.7 a minute and absorb 2.8 to 4.7; four rates over about 50 minutes carry noise near 0.6 a minute, so the first bar is over twice it |
| `striking_accuracy` | landed / attempted | 0.06 / 0.10 / 0.15 | Middle half 0.43 to 0.53; with a couple of hundred strikes behind each, noise in a gap is about 0.05, so the first bar sits above it (it was 0.04 in the first draft, which put an accuracy line on 8 of the 14 bouts of the real card; it is on 5 now) |
| `striking_defence` | share of strikes thrown at the fighter that miss | 0.06 / 0.10 / 0.14 | Middle half 0.49 to 0.58, same noise |
| `takedown_open` | the attacker lands at least 1.5 takedowns per 15 minutes and the defender has stopped 65% or fewer of at least 5 attempts | 1 point, plus 1 if the attacker lands 2.5 or more, plus 1 if the defender stops 50% or fewer | 65% is the bottom third of fighters; a route needs real offence and a leaky defence, and either extra makes it clearer |
| `takedown_closed` | the same attacker meets a defender who has stopped 80% or more | slight; moderate at 90% with an attacker landing 2.5 or more | 80% is the data layer's `hard_to_take_down` bar |
| `control` | share of fight time in control | 0.10 / 0.20 / 0.30 | Middle half 0.06 to 0.25 |
| `knockdown_power` | knockdowns scored per 15 minutes | 0.75 / 1.25 / 2.0 | 0.75 is the data layer's `knockout_threat` bar |
| `chin` | knockdowns suffered per 15 minutes, or two or more losses by KO or TKO with three or more fights on file | 0.75 / 1.25 / 2.0; the count alone is slight | The same bar from the other side |
| `finisher` | share of fights ending in a finishing win | 0.60 / 0.75 / 0.90 | 0.60 is the data layer's `finisher` bar |
| `finished_often` | share of fights ending in a finishing loss | 0.30 / 0.45 / 0.60 | 0.30 is the data layer's `vulnerable_to_finish` bar |
| `submission_threat` | submission attempts per 15 minutes | 1.0 / 1.75 / 2.5 | 1.0 is the data layer's `submission_threat` bar |
| `been_submitted` | losses by submission, with three or more fights on file | 2 / 3 / 4 | Counts, not a rate, because the sample is small |
| `fight_length` | gap in average fight time, five-round bouts only; a weakness only when the shorter average is under 10 minutes | 240 / 420 / 600 seconds | Only a five-round bout tests the late rounds; a short average can also mean quick finishes, and the caveat says so |
| `long_layoff` | days since the last fight on file | 365 / 545 / 730 | Worded "has not fought in the UFC for N months", because the store holds UFC fights only |
| `age` | gap in years, read only when the older fighter is 34 or more | 4 / 7 / 10 | The median gap between two fighters in a bout is 3.6 years and 4 or more is common (46% of bouts), so a gap alone is not a finding; it is read when the older fighter is in the age group where it can matter. The effect of age on the fight is not measured and the caveat says so |
| `reach`, `height` | gap in inches, as listed on the fighter record | reach 3.0 / 4.5 / 6.0, height 3 / 4 / 6 | Over the 1,667 bouts of the first backfill whose fighters both list a reach, the median gap is 2.0 inches (top quarter 4 or more, top tenth 5.5 or more); the median height gap is 2.0 (top quarter 3 or more). The first bars sit near the 60th and 70th percentiles so a "slight" line is not on every card (reach was 2.0 in the first draft, which is the median) |
| `schedule` | gap in the opponents' average win rate at the time of each fight | 0.08 / 0.15 / 0.25 | Opponents with no earlier fight on file are left out, never scored as average |
| `results` | gap in win rate on file | 0.20 / 0.35 / 0.50 | Says nothing about who the fights were against |
| `win_streak`, `loss_streak` | the current run | win 3 / 5 / 7, loss 2 / 3 / 4 | Always thin under four fights; a run counts results only |

Several rules are two-sided: one comparison gives the better side a strength and the other a weakness (the two carry the
same evidence). The rest describe one fighter.

### Headline, routes, market view, history

**Headline.** The heaviest item by size times sample weight, among every rule except `results`, `schedule` and the runs
of form (records and the level of opposition describe where a fighter has been more than how this fight will be
fought, and are the noisiest figures on a few fights; they headline only when nothing else clears the bar). The bar is
0.6, a slight difference on fair data or a moderate one on thin data. Below it the headline says no single difference
clearly separates them "and that is a valid read", and says which fighter has nothing or little on file. A thin
headline adds "The sample behind it is thin, so treat it as an early sign."

**Routes to victory.** Built from the same items, never from outside facts: win the striking (a net-strikes strength,
with accuracy and defence when the same fighter also holds them, and "this route needs the fight to stay on the feet"),
hurt and finish (power against a chin question or a KO loss, or a finisher against a chin question), take it to the mat
(an open takedown door, with control time when the fighter holds it), find a submission (a submission threat against a
fighter who has been submitted or is easy to take down), win on the scorecards (two or more decision wins making up at
least half of the wins, from three fights), make it long (the deeper fighter in a five-round bout), keep it standing (a
closed takedown door while the other fighter is not winning the striking). A route's size is its weakest link when it
chains two facts, and its sample level is its thinnest part. The three heaviest are kept; with none the read says
"Nothing in the figures on file points to a route to a win for X" and why.

**Market view.** The market's margin-free chances (the sheet's `without_margin`), the prices as fetched, the movement from
the open (stated as a fact, never as a signal), the rounds line, and the method split. The read's own lean is the net of
its items, counting only the heaviest item of each family for each fighter so that three striking rules are one voice,
and it must reach 1.2 (two slight items on fair data, or one moderate) before it names a side. No lean: it says it
neither agrees nor disagrees and that the price is the better informed number. Agreement: it says that is expected,
because what we can see is already in the price, and that it says nothing about whether the price is right.
Disagreement: it says the likelier explanation is that the books know something the read cannot see (an injury, a bad
weight cut, camp news), and not that the price is wrong. **When either fighter is thin the read adds, always: "With this
little on file, the price is more likely right than this read."** Prices that could not be matched to the two fighters, or
only in-fight prices, give no market view and say so. It never calls a price move "closing line value".

**History.** Previous meetings (winner, method, round, date; a draw or a no contest is not called a win) and shared
opponents (what each fighter did against them), with the counts of each fighter's distinct opponents so "no overlap
between two real histories" reads differently from "a fighter with no history". A shared-opponent comparison carries the
caveat that it is a weak guide.

**Context.** Each fighter's record on file and the first fight on file; the overall record from the fighter record, only
when it was fetched before the bout (a record fetched after the start may include the fight itself, so it is not used and
is listed under "could not use"); the last three fights in plain words; a weight class move with its direction; a short
turnaround; the stance matchup; and how often each fighter's fights have gone to the scorecards (the proxy for pace and
the late rounds, since there is no round-by-round data).

### Wording rules (tested over every read the tests produce)

No dash, no field name or snake case, no double space, no gendered pronoun, no "edge", "lock", "guarantee", "profit",
"pick", "recommend", "bet", "win probability", "ROI", "+EV", "closing line", "units" or "stake"; "prediction" appears only
in the label's own denial. The strings of `src/analysis/ufc_read.py` are inside `tests/test_customer_language.py`'s scan
and pass it.

## The page

`renderFightNight(host, {eventId, analyst})` fetches `/ufc/fight-night?sheet=compact` (or the event's) and appends one
section to the page. `main.js` calls it right after `renderCard` on `#/ufc`, and `#/ufc?event=<id>` opens another card
from the "OTHER CARDS" links. `card.js` and the paused notice are untouched.

Per bout: the card slot, title fight, weight class, rounds and local start time; both fighters (name, overall record,
age, stance) with the price and the market's own share with the margin removed (or "No price on file"); the data
depth chip (THIN, FAIR or SOLID DATA) and sentence; the headline; strengths and weaknesses side by side (three of each
open, the rest under "MORE (n)"; each with size, sample chips, caveat, and its evidence under a native `<details>`);
paths to victory (two each open); history; the market sentences; "what would change this, and what we could not use"
under one toggle; and the fact sheet under a native `<details>`: the figures side by side with their samples and a THIN
tag, physical, layoff and style labels. A bout whose read could not be built shows its reason and its fighters.

Everything the page says about a fighter is a sentence the server wrote, printed verbatim. The page formats numbers it
is sent and computes nothing that could read as a view.

**390px.** One column by default, blocks only (no tables), every text node wraps (`overflow-wrap: anywhere`), no width
above 300px is fixed, nothing scrolls on its own, the two-column layouts switch on from 900px, and the fact sheet is three
flexible grid columns. Checked three ways: static assertions in `tests/test_web_ufc_fight_night.py`; a real browser at
390 by 844 (document and body widths equal, no element past the right edge, with all 68 `<details>` of a six-bout card
opened); and at 1100px for the two-column layout.

### Where the AI analyst section goes

Every bout panel carries an empty `<div data-hook="ufc-analyst-slot" data-bout-id="...">` after the written read
(history, context and the market view) and before "what would change this" and the fact sheet. The card carries one
more, `<div data-hook="ufc-analyst-event-slot">`, under the heading and the label. An empty slot takes no room (CSS
`:empty`). The seam is the `analyst` option of `renderFightNight`: a function `(slotNode, context)` called once per slot,
with the bout payload for a bout slot and `{event}` for the event slot. `main.js` is the one caller and passes nothing
today; whoever builds the UFC analyst section adds `analyst: (slot, ctx) => ...` to that one call (or imports into
`ufcfights.js`). A callback that throws or rejects leaves its slot empty and the page whole (tested). Nothing under
`src/analyst/` was touched.

## A real read: the UFC 332 main event

The bout is **Natalia Silva v Wang Cong, Women's Flyweight title, five rounds, bout 401912278 of event 600061182
(UFC 332)**, scheduled for 2026-10-04 00:00 UTC. It is the route's own output (`api.ufc_fights._build`, the function the
route runs, over the data below, with the clock at 2026-10-03 19:30 UTC).

**Data date.** The main checkout's `data/datasvc/ufc/` as it stood on 2026-10-03: events, bouts and prices fetched
2026-10-03 19:13 to 19:14 UTC (this bout's DraftKings row at 19:14:01 UTC; `data_updated_utc` for the card is
19:14:07 UTC). **One caveat about how the sample was produced:** the checkout's backfill had not yet written
`fighters.jsonl` (it holds events, bouts, fight statistics and odds only), but its raw ESPN cache already held 1,075
athlete pages and the same number of records pages, fetched 19:55 to 20:14 UTC. The sample was built over a scratch copy of the four files plus a
`fighters.jsonl` assembled from that cache with the data layer's own `fighters.parse_athlete` (no network; the main
checkout was only read). It is what the route will show once the backfill's fighters step lands.

The numbers in it were recomputed from the raw rows without the data layer (accuracy 271 of 633 and 478 of 826,
nets +2.07 and +4.02 a minute, margin-free 64.47% and 35.53%, the last three fights, ages and records) and match.

The read, as the page prints it (sentences verbatim; the bracket after each is its size and sample level):

**Natalia Silva (20-5-1) v Wang Cong (10-1-0)**, Women's Flyweight, title fight, 5 rounds. Price: Natalia Silva -205 and 64.5% of the market, Wang Cong +170 and 35.5% (DraftKings, margin removed).

> **Headline.** The biggest difference is in striking accuracy. Wang Cong is the more accurate striker, with 58% of significant strikes thrown landing against 43% for Natalia Silva (on file: Natalia Silva 4 fights, 60 minutes; Wang Cong 6 fights, 70 minutes).

**Data depth (fair).** On file before this fight: Natalia Silva 4 UFC fights (60 minutes), out of 26 professional fights in all; Wang Cong 6 UFC fights (70 minutes), out of 11 professional fights in all. That is enough to describe each fighter's recent style and not enough to settle it.

#### Natalia Silva

*Strengths*

- Natalia Silva is harder to hit, with 67% of the significant strikes thrown at Natalia Silva missing against 60% for Wang Cong (on file: Natalia Silva 4 fights, 60 minutes; Wang Cong 6 fights, 70 minutes). [slight, fair]
- Natalia Silva is the younger fighter by 4.7 years (29.7 against 34.4). [slight, fair] _Age is shown as a difference in years; these figures do not measure its effect on the fight._
- Natalia Silva has won 4 fights in a row on file. [slight, fair] _A run counts results only; it does not say how the fights were won or who they were against._
- Natalia Silva has faced the tougher opposition, with opponents who had won 58% of their UFC fights going in against 50% for Wang Cong's (opponents with a record on file: Natalia Silva 3, Wang Cong 5). [slight, thin] _Thin sample: Natalia Silva has fewer than 5 fights behind this, so one more fight could move it a long way. An opponent with no earlier fight on file is left out of the figure, not counted as average._

*Weaknesses*

- Natalia Silva is the less accurate striker, with 43% of significant strikes thrown landing against 58% for Wang Cong (on file: Natalia Silva 4 fights, 60 minutes; Wang Cong 6 fights, 70 minutes). [large, fair]
- Natalia Silva gets the worse of the striking, a net of +2.1 significant strikes a minute (landing 4.5, absorbing 2.5) against +4.0 for Wang Cong (landing 6.8, absorbing 2.8) (on file: Natalia Silva 4 fights, 60 minutes; Wang Cong 6 fights, 70 minutes). [slight, fair] _Strikes are not adjusted for who the opponents were._

*Paths to victory*

- **Win on the scorecards.** 4 of Natalia Silva's 4 wins on file came by decision, and Wang Cong has finished 17% of fights on file. [moderate, thin]

*Context*

- Natalia Silva has 4 UFC fights on file, the first on 2024-02-04, for a record of 4-0-0.
- The fighter record, fetched 2026-10-03, shows 20-5-1 overall, 26 professional fights including any outside the UFC.
- Natalia Silva's last 3 fights on file, newest first: beat Rose Namajunas by unanimous decision on 2026-01-25, round 3; beat Alexa Grasso by unanimous decision on 2025-05-11, round 3; beat Jessica Andrade by unanimous decision on 2024-09-07, round 3.

#### Wang Cong

*Strengths*

- Wang Cong is the more accurate striker, with 58% of significant strikes thrown landing against 43% for Natalia Silva (on file: Natalia Silva 4 fights, 60 minutes; Wang Cong 6 fights, 70 minutes). [large, fair]
- Wang Cong out-strikes Natalia Silva on the feet, a net of +4.0 significant strikes a minute (landing 6.8, absorbing 2.8) against +2.1 for Natalia Silva (landing 4.5, absorbing 2.5) (on file: Natalia Silva 4 fights, 60 minutes; Wang Cong 6 fights, 70 minutes). [slight, fair] _Strikes are not adjusted for who the opponents were._
- Wang Cong has won 4 fights in a row on file. [slight, fair] _A run counts results only; it does not say how the fights were won or who they were against._

*Weaknesses*

- Wang Cong is easier to hit, with only 60% of the significant strikes thrown at Wang Cong missing against 67% for Natalia Silva (on file: Natalia Silva 4 fights, 60 minutes; Wang Cong 6 fights, 70 minutes). [slight, fair]
- Wang Cong is the older fighter by 4.7 years (34.4 against 29.7). [slight, fair] _Age is shown as a difference in years; these figures do not measure its effect on the fight._
- Wang Cong has faced the weaker opposition, with opponents who had won 50% of their UFC fights going in against 58% for Natalia Silva's (opponents with a record on file: Natalia Silva 3, Wang Cong 5). [slight, thin] _Thin sample: Natalia Silva has fewer than 5 fights behind this, so one more fight could move it a long way. An opponent with no earlier fight on file is left out of the figure, not counted as average._

*Paths to victory*

- **Win the striking.** Wang Cong nets +4.0 significant strikes a minute on file against +2.1 for Natalia Silva, and Wang Cong lands more accurately as well. This route needs the fight to stay on the feet. [large, fair]
- **Win on the scorecards.** 4 of Wang Cong's 5 wins on file came by decision, and Natalia Silva has finished 0% of fights on file. [moderate, fair]

*Context*

- Wang Cong has 6 UFC fights on file, the first on 2024-08-24, for a record of 5-1-0.
- The fighter record, fetched 2026-10-03, shows 10-1-0 overall, 11 professional fights including any outside the UFC.
- Wang Cong's last 3 fights on file, newest first: beat Tracy Cortez by unanimous decision on 2026-07-11, round 3; beat Eduarda Moura by unanimous decision on 2026-02-07, round 3; beat Ariane Lipski da Silva by unanimous decision on 2025-06-07, round 3.

#### Between them

- Both fighters work from the southpaw stance. These figures do not measure what that changes.
- Natalia Silva's fights on file have gone to the scorecards 100% of the time and Wang Cong's 67% (fights with a recorded method: Natalia Silva 4, Wang Cong 6). _Thin sample: Natalia Silva has fewer than 5 fights behind this, so one more fight could move it a long way._
- Natalia Silva and Wang Cong have not met in the fights on file. Natalia Silva has faced 4 opponents on file and Wang Cong has faced 6, with none in common.

#### What the price says

- DraftKings' current prices make Natalia Silva the 64.5% favourite and Wang Cong 35.5%, with the bookmaker's margin taken out (Natalia Silva -205, Wang Cong +170, fetched 2026-10-03).
- The line has barely moved since it opened.
- The rounds line is 4.5, with the fight going past it the likelier side at 70% with the margin removed.
- Taken together, the method prices put a decision at 66%, a KO or TKO at 22% and a submission at 11%, margin removed.
- The figures on file do not lean clearly toward either fighter, so this read neither agrees nor disagrees with the price. On these inputs the price is the better informed number.
- We have not tested whether figures like these beat UFC prices. Treat this as a description of the fight, not as advice.

#### What would change it

- **A change of opponent, a withdrawal or a cancelled bout.** Everything above is built from Natalia Silva and Wang Cong as booked for 2026-10-04; a replacement fighter would void it and start the read again.
- **A move in the price.** The market takes in injuries, weight cuts and camp news that these figures cannot see; a large move after this read was built would mean something we do not see.

#### What we could not use (1)

- THIN. Natalia Silva: finishing, win and fight-length figures. 4 fights on file; a share of results is shown from 3 fights and counts as more than thin from 5.


## What it cannot support, and what it says instead

- **Strikes are not adjusted for who the opponents were.** The caveat is printed under every striking item. A strike rate
  built on three fights against weak opposition looks like a strike rate.
- **History is UFC history since the store starts** (2024 on the first backfill). "Has not fought in the UFC for 23
  months" is worded that way because he or she may have fought elsewhere; the overall record, which includes other
  organisations, is shown as context and never used in a figure, because it is not as-of-date.
- **Cardio and pace are proxies**: the average fight time (five-round bouts only), the share of fights that went to the
  scorecards, and strikes a minute. There is no round-by-round data, and the read does not pretend there is.
- **Style labels** (`wrestler`, `striker` ...) are in the fact sheet for the reader and are not used by the read, which
  works from the figures under them.
- **Nothing here is a forecast.** There is no win probability of ours, no ranking of fights by "value", and the market
  view says in every case that the figures have not been tested against UFC prices.
- **A card is only as good as its fighters file.** A bout whose fighters have no name on file shows "Name not on file".

## Things the next person should know

1. **The deploy image carries no `data/datasvc/`.** `deploy/Dockerfile` copies `data/processed`, `data/watch`,
   `data/historical` and the like, not the UFC data layer's files (which are not yet tracked either). Until the image
   carries them (or a volume does), `/data/v1` and this route see an empty store and answer "No UFC event is scheduled in
   our data right now" with `data_updated_utc: null`; the page handles that state, but it is not the card. Not changed here.
2. **`matchup()` cannot attach a finished bout and its prices** (it finds only `scheduled` bouts), so this route composes
   the same public helpers for those. If the data layer grows an `as_of`-for-this-bout parameter the route's second
   branch (`_sheet_for`) can go.
3. **The development show rule is a name match** ("contender series"). It is one function.
4. **Thresholds are placeholders in the data layer's sense.** They are round numbers placed against the first backfill's
   distributions and are meant to be revisited against the full backfill's percentiles, in the open, the way the style
   labels are. Changing one is a deliberate edit with a golden-file diff to read, never a tuning loop.

## Tests

| File | What it pins |
| --- | --- |
| `tests/test_ufc_read.py` | Each rule at every threshold (both sides of a pair, the sentence, the size), thin-sample handling (the floors are the data layer's, the levels at each boundary, down-weighting, ranking, the thin caveat), the display floors, missing data (a fighter with no fights, missing figures grouped in plain words, no bout, no price), the market view in every state, history, context, routes, and sweeps over every read: every evidence path resolves and matches, no pick or lock or profit or probability, no dash, no field name, no gendered pronoun. Ends with every pair of the data layer's synthetic world. |
| `tests/test_ufc_read_golden.py` | The read of a real upcoming bout (Vettori v Naurdiev, UFC 332) and of a real finished main event's two fighters (Rosas Jr. v Barcelos), both built from the saved ESPN responses through the data layer's own parsers, plus the synthetic world, against a frozen file; the frozen sheets against what the data layer still builds (so a data-layer change and a wording change are different failures); and the real facts the reads state. |
| `tests/test_api_ufc_fights.py` | The gate (both routes 401 signed out; demo mode cannot open it, in a subprocess), the shape and card order, the sheet and read byte for byte what the two modules make, the compact sheet, fail soft in six ways, event selection (development show, stale, under way, finished, none, unknown), a finished bout read as it was going in, loaded once, built once per store version, concurrent first requests. |
| `tests/test_web_ufc_fight_night.py` | Wiring under the paused notice, the paused notice kept, the stylesheet at 390px, no script or table or direct fetch, wording of what the module writes itself, then the real module under node on a fake DOM: panels in card order, fighters and prices, verbatim sentences, thin chips and caveats outside any toggle, folds, evidence toggles, the fact sheet, analyst slots (filled, throwing, rejecting), every other state (no event, development show, finished, unavailable bout, signed out, failed request), and the real route's own output when FastAPI is installed. |

Regenerate the golden file only when the read's wording or logic, or the data layer's sheet, changed on purpose:

```
python3 scripts/regen_ufc_read_fixtures.py
```
