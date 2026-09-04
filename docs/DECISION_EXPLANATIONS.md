# Self-explaining decisions: readable picks, grounded theses, a day ranking

Owner directive, 2026-09-04: *"if our bots aren't each picking their top 10
best bets for the projected day ... with reasoning and explanation then
mission failed ... it needs to be 'I'm picking this bet (e.g. over 4.5 runs
ATL Braves) because xyz'."*

Before this change a published pick read:

    system 606be696ff199952 | selection 9e8d61f45a38abf0
    thesis "evolab genome 606be696ff199952: (('top_minus_bottom', 1),)"

Three machine identifiers and a tuple index. The `DecisionRecord` fields
(`thesis`, `evidence`, `counterarguments`) already existed and 328 of 387
published rows populated them -- the plumbing was never missing, the
CONTENT was.

## 1. The readable selection -- `src/board/readable.py`

`selection_id` stays exactly what it was: a 16-hex sha256 of (sport,
market, side, subject, line), the identity key for the ledger, the dedupe
key, and the `bet_id` derivation. Nothing about identity changed.

What is new is a rendering path alongside it:

    render_selection(market_key="spreads", side="home", line="-1.5",
                     teams=GameTeams(home="Atlanta Braves", ...),
                     price_american=-118, book="draftkings")
    -> "Atlanta Braves (home) -1.5 run line (-118, DraftKings)"

* Team names are facts about the EVENT, not about a quote, so they are not
  on `PriceObservation` or `DecisionRecord`. They join at the rendering
  boundary only, from `src.board.gamekey.events_for_date`.
* `side` is recovered from the hash by re-deriving each declared side of
  the market and seeing which one matches (`side_for_selection`). The hash
  is one-way; this is the only honest recovery, and it returns `None`
  rather than guessing when nothing matches.
* Unknown team -> "the home side moneyline". Unknown book key -> the key
  printed verbatim. A missing name degrades the prose; it never restores
  the hash and never invents a club.
* The `(home)`/`(away)` tag is deliberate: a system's thesis is minted
  price-blind and therefore names a SIDE, not a club, so the tag is what
  lets a reader join the pick line to the thesis without opening code.

## 2. The feature-grounded thesis -- `src/engine/explain.py`

`PriceBlindSnapshot` carries the seven `src.engine.features` columns per
side. When a genome fires, `explain_signal` writes one sentence group per
fired signal containing:

* both sides' actual values in their own units (shares as `%`, wOBA to
  three decimals, velocity in mph -- printing all three identically would
  make a 0.061 wOBA gap read like a 0.061 share gap, which it is not);
* the gap, in percentage POINTS for a share;
* the threshold it cleared, and which rung of the fixed three-rung dose
  ladder that is (50th / 75th / 90th percentile);
* the sample the ladder was derived over, quoted from the registry spec's
  own `provenance` string rather than retyped;
* the frozen direction (+1/-1) and therefore which side the signal points
  to;
* the pre-registered mechanism prose, VERBATIM from
  `src.evolab.registry` -- re-wording a hypothesis after the fact quietly
  relaunders its date.

A value that is absent is printed "unavailable". Nothing is defaulted,
interpolated or estimated.

## 3. Honesty rules (docs/PREREG_CALIBRATED_PROBABILITY.md)

No thesis may claim an edge, a probability advantage, or expected profit.
No proven edge exists here and 24 registered hypotheses have died.

* Every evolab thesis ends: *"This is a signal count, not a forecast ...
  p_model is null and edge_bps is null by construction."*
* Every `market_derived` thesis opens: *"This pick carries the market's own
  probability and no edge, by construction."*
* Every `placeholder` control opens: *"This is a DELIBERATE CONTROL, not a
  pick anyone should follow."*
* `explain.claims_edge(thesis)` is the machine-checkable form: it strips
  explicit denials ("edge_bps is structurally None", "no edge is claimed")
  and then looks for a value assertion (`edge`, `+EV`, `mispriced`,
  `expected profit`, ...). A denial phrasing not on the list fails CLOSED,
  which is the safe direction.

`tests/test_decision_explanations.py` runs `claims_edge` over every
registered system's thesis AND over every row of the real published
`evidence/decisions_v2.jsonl` whose `edge_bps` is None.

## 4. The day-level top-N -- `src/engine/slate.py`

`SELECTION_RULE` (`TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1`) stops at the
game boundary. `DAY_RANKING_RULE`
(`TOP_N_PER_SYSTEM_PER_DAY_BY_PRICE_STANDING_V1`) is the separately
pre-registered day-level order: each system's best N plays (default 10)
across the whole slate.

The basis is **price standing in bps** -- the board's own de-vigged
consensus for the selection minus the implied probability of the best
available price -- then more books, then lower vig, then `selection_id` and
`event_id` for determinism.

Price standing is **not an edge**. The consensus is computed FROM these
same prices, so the difference can never be evidence the market is wrong;
it measures execution quality (am I taking the best number available for
the thing I chose), which is exactly what
`value_basis="price_standing_only:no_calibrated_p_model"` on every one of
these records already says. A record with no consensus has no basis value
and is ranked last as a named "unavailable", never given a zero that would
let it outrank a real standing.

## 5. Where it shows up

* `python3 -m src.cli engine slate --date DATE [--top-n N]` prints every
  record as its readable pick, then a `TOP N PICKS PER SYSTEM` section
  naming the ranking rule, the basis, each pick's price standing and its
  full thesis.
* `docs/eod/DATE.md` renders each decision as the bet in English first,
  then the machine identity, then `because: <thesis>`.

Rows published BEFORE this change keep their old hash-shaped thesis: they
are frozen entries in a hash chain and rewriting them would falsify the
chain. Their pick lines still render readably (the rendering is applied at
read time); only their thesis text is historical.
