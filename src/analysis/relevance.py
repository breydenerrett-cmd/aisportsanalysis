"""Pre-event relevance: how much a roster event could plausibly matter, scored
from what was knowable BEFORE the market answered it.

WHAT THIS IS
------------
`rosterwatch.events()` hands V3 a stream of bracketed events -- a starter
scratched, a lineup posted, a hitter pulled, a transaction first seen -- and
`eventstudy.measure()` says how fast and how far the books moved afterwards.
Nothing in between says whether the event was a Cy Young winner scratched an
hour before first pitch or a September call-up optioned back down. Response
SIZE should scale with event importance; scored identically, the two land in
the same distribution and the star's signal drowns in the call-up's noise.

This module scores the second half of that sentence -- importance -- using
ONLY pre-response information: the player's own accumulated record in the
pitch store strictly before the cutoff, his lineup slot in the lineup that
was already posted, and the roster category MLB filed the move under. No
odds, no post-event quote, no outcome. The score is an input to reading the
response, never derived from it.

WHAT THIS IS NOT
----------------
It is DESCRIPTIVE METADATA and never an edge claim. A HIGH tier says "a
market that cares about this class had more to reprice here than usual", not
"this is a bet", not "the line will move", not "the move will be wrong".
Nothing here forecasts anything.

It also does not touch the V3 family. docs/RESEARCH_V3_TIMING.md froze four
admitted classes on 2026-08-31 and the per-event record already reserves a
"pre-event relevance estimate" slot; this fills that slot. V3 inference runs
on the frozen family REGARDLESS of tier: no tier admits, excludes, or
re-weights an event in the primary hypotheses, and slicing latency by tier
would be a new descriptive cut reported as exactly that (with intervals),
never promoted to a finding without its own pre-registration. Tiers are also
not a peek below the frozen quality floors -- a grade-C first sighting stays
inadmissible whatever it scores.

POINT-IN-TIME, THE SAME WAY EVERYTHING ELSE HERE IS
---------------------------------------------------
Every fact comes from `statcast_pitches.iter_rows(store, before=cutoff)`,
the one accumulation primitive the rebuilt features read through, so a pitch
thrown on or after the cutoff day cannot move a score by one byte
(tests/test_relevance.py pins that at byte level, in the discipline of
tests/test_matrix_v5_features.py). The index is deliberately its own small
accumulation rather than a read of a `rebuilt` snapshot: the facts relevance
needs -- appearances, per-appearance pitch counts, plate-appearance volume --
are not in that snapshot, and inferring appearances from its fastball map
would silently mean "games with a measured four-seam".

UNKNOWN IS AN ANSWER
--------------------
A player with no pitches in the store before the cutoff scores UNKNOWN, not
LOW. A September call-up who has never faced a major-league hitter is not a
low-relevance event -- he is an event we cannot characterize, and the two
must not be pooled. UNKNOWN sits OUTSIDE the LOW < MEDIUM < HIGH order
(`tier_rank` returns None for it) precisely so nothing can quietly average
it in as a zero.

EVERY FACT CARRIES ITS SAMPLE
-----------------------------
Each score's `basis` lists the facts it rests on with their denominators --
pitches, appearances, plate appearances, lineup slot -- so a reader can see
that a HIGH rests on 28 starts and a LOW rests on eleven pitches, rather
than trusting the word.
"""

from __future__ import annotations

from src.providers import statcast_pitches as sp
from src.pipeline import rosterwatch
from src.providers import mlb_news

# The ordinal scale. UNKNOWN is deliberately not on it.
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
UNKNOWN = "UNKNOWN"
TIER_ORDER = (LOW, MEDIUM, HIGH)

NOT_AN_EDGE = (
    "Descriptive pre-event relevance, from the player's own record before the "
    "cutoff. It is not a prediction, not an edge claim, and it changes nothing "
    "about which events V3 admits.")

# --- pitcher thresholds ----------------------------------------------------
# An appearance in which the pitcher threw at least this many pitches. A
# reliever's outing is 12-25 pitches and a one-inning opener rarely clears 30;
# 40 is comfortably above both, so counting APPEARANCES over the line reads
# "he carried a starter's workload that day" without needing a position label
# the pitch feed does not carry. Long relief occasionally clears it, which is
# why the tier also asks how deep those appearances went.
STARTING_APPEARANCE_PITCHES = 40
# Five starting-workload appearances is about a month in a rotation -- enough
# that the market has seen this arm start, repeatedly, and priced it.
ESTABLISHED_STARTS = 5
# A rotation regular averages 85-95 pitches a start; 80 separates a pitcher
# who works deep from a bulk/piggyback arm who clears the 40-pitch line but
# hands the ball over in the fourth. HIGH needs both counts, not either.
DEEP_START_PITCHES = 80.0
# Two starting-workload appearances, or 300 total pitches (~three starts or a
# month of relief), is "an arm with a record", short of an established
# rotation piece.
FAMILIAR_STARTS = 2
KNOWN_PITCHES = 300

# --- hitter thresholds -----------------------------------------------------
# 300 plate appearances is roughly half a season of everyday play: an
# established regular whose bat the market knows. 100 is a part-timer with a
# record. Below that the player has appeared but is not characterized.
REGULAR_PA = 300
KNOWN_PA = 100

# --- lineup slot -----------------------------------------------------------
# Slots 1-4 take the extra plate appearance when the order turns over and are
# where clubs put their best bats, so losing one is a bigger hole than the
# raw volume says. Slots 7-9 are the reverse. Middle slots adjust nothing,
# and an unknown slot adjusts nothing -- absence never moves a score.
TOP_SLOTS = (1, 2, 3, 4)
BOTTOM_SLOTS = (7, 8, 9)

# --- transaction categories ------------------------------------------------
# Categories that change who is available tonight get the player's full
# workload tier. mlb_news.NOTABLE is the same list the rest of the repo
# surfaces; restating it here would let the two drift.
AVAILABILITY_CATEGORIES = set(mlb_news.NOTABLE)
# A recall, an option, a DFA or a 60-day transfer is a bottom-of-roster move
# by construction -- the player being moved is, almost definitionally, not
# the piece the market prices tonight -- so these cap at MEDIUM however much
# record the player has. The cap never overrides UNKNOWN.
DEPTH_CATEGORIES = {mlb_news.RECALLED, mlb_news.OPTIONED,
                    mlb_news.DESIGNATED, mlb_news.IL_TRANSFER}

# lineup_posted has no within-class differentiator available before the
# response: every posting is the same nine-name confirmation, and which nine
# they are is only news relative to an expectation we do not capture. It is
# therefore a class CONSTANT, stated as one, rather than a fabricated spread.
LINEUP_POSTED_TIER = MEDIUM
LINEUP_POSTED_REASON = (
    "first confirmation of a posted lineup; the class carries no player-level "
    "differentiator that is knowable before the market responds, so every "
    "posting scores the same class constant")


class RelevanceError(RuntimeError):
    """Raised when a score is asked for on an event shape that has no class."""


def tier_rank(tier):
    """0/1/2 for LOW/MEDIUM/HIGH, None for UNKNOWN.

    UNKNOWN is not a low score, so it gets no rank at all: a caller that
    sorts, averages or thresholds on rank has to decide what to do with the
    None instead of silently treating "we know nothing" as "it did not
    matter".
    """
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else None


def _shift(tier, steps):
    """Move a ranked tier along the scale, clamped. UNKNOWN never moves."""
    rank = tier_rank(tier)
    if rank is None:
        return tier
    return TIER_ORDER[max(0, min(len(TIER_ORDER) - 1, rank + steps))]


def _best(tiers):
    """The highest ranked tier present, or UNKNOWN when none is ranked."""
    ranked = [t for t in tiers if tier_rank(t) is not None]
    return max(ranked, key=tier_rank) if ranked else UNKNOWN


# ---------------------------------------------------------------------------
# The pre-cutoff index
# ---------------------------------------------------------------------------

def build_index(cutoff, store=sp.DEFAULT_STORE) -> dict:
    """Per-player workload from every stored pitch strictly before `cutoff`.

    One pass. `iter_rows(before=...)` reduces a datetime cutoff to its
    calendar day and compares lexicographically, so the cutoff day's own
    pitches are excluded -- an event scored on the morning of a game can
    never see that game.

    Per-game pitch counts are folded into per-pitcher aggregates as the walk
    finishes rather than kept, so the index stays a few hundred kilobytes for
    a multi-season store.
    """
    pitcher_games, batter_games = {}, {}
    pitches, batters_faced, plate_appearances = {}, {}, {}

    for row in sp.iter_rows(store, before=cutoff):
        game = (row.get("game_date") or "", str(row.get("game_pk") or ""))
        pitcher = row.get("pitcher")
        batter = row.get("batter")
        denom = row.get("woba_denom")
        try:
            denom = int(float(denom)) if denom not in (None, "") else 0
        except (TypeError, ValueError):
            denom = 0  # unparseable feed value: not a plate appearance, not a guess
        if pitcher:
            key = str(pitcher)
            pitches[key] = pitches.get(key, 0) + 1
            counts = pitcher_games.setdefault(key, {})
            counts[game] = counts.get(game, 0) + 1
            if denom:
                batters_faced[key] = batters_faced.get(key, 0) + denom
        if batter:
            key = str(batter)
            batter_games.setdefault(key, set()).add(game)
            if denom:
                plate_appearances[key] = plate_appearances.get(key, 0) + denom

    pitchers = {}
    for key, counts in pitcher_games.items():
        deep = [n for n in counts.values() if n >= STARTING_APPEARANCE_PITCHES]
        pitchers[key] = {
            "pitches": pitches.get(key, 0),
            "appearances": len(counts),
            "starting_appearances": len(deep),
            # Mean over the starting-workload appearances only: averaging a
            # starter's relief cameo in would understate how deep he works.
            "pitches_per_start": (round(sum(deep) / len(deep), 1)
                                  if deep else None),
            "batters_faced": batters_faced.get(key, 0),
        }
    batters = {key: {"plate_appearances": plate_appearances.get(key, 0),
                     "games": len(games)}
               for key, games in batter_games.items()}
    return {"cutoff": str(cutoff), "pitchers": pitchers, "batters": batters}


def _pitcher_facts(index, player_id) -> dict:
    facts = (index.get("pitchers") or {}).get(str(player_id))
    return dict(facts) if facts else {"pitches": 0, "appearances": 0,
                                      "starting_appearances": 0,
                                      "pitches_per_start": None,
                                      "batters_faced": 0}


def _batter_facts(index, player_id) -> dict:
    facts = (index.get("batters") or {}).get(str(player_id))
    return dict(facts) if facts else {"plate_appearances": 0, "games": 0}


def pitcher_tier(facts) -> str:
    """Workload tier for a pitcher, from his own pre-cutoff record."""
    if not facts["pitches"]:
        return UNKNOWN
    per_start = facts["pitches_per_start"]
    if (facts["starting_appearances"] >= ESTABLISHED_STARTS
            and per_start is not None and per_start >= DEEP_START_PITCHES):
        return HIGH
    if (facts["starting_appearances"] >= FAMILIAR_STARTS
            or facts["pitches"] >= KNOWN_PITCHES):
        return MEDIUM
    return LOW


def batter_tier(facts) -> str:
    """Workload tier for a hitter, from his own pre-cutoff plate appearances."""
    pa = facts["plate_appearances"]
    if not pa and not facts["games"]:
        return UNKNOWN
    if pa >= REGULAR_PA:
        return HIGH
    if pa >= KNOWN_PA:
        return MEDIUM
    return LOW


def player_profile(index, player_id) -> dict:
    """Role and workload facts for a player who may be either kind.

    A transaction names a player, not a position. Whichever store holds the
    heavier record decides the role, and a player in neither is UNKNOWN --
    the case the whole module exists to keep separate from LOW.
    """
    pitcher = _pitcher_facts(index, player_id)
    batter = _batter_facts(index, player_id)
    if pitcher["pitches"] and not batter["plate_appearances"]:
        role = "pitcher"
    elif batter["plate_appearances"] and not pitcher["pitches"]:
        role = "batter"
    elif pitcher["pitches"] or batter["plate_appearances"]:
        # A two-way player, or a pitcher who has taken a plate appearance.
        # Whichever record is the larger sample is the one that characterizes
        # him; ties go to the mound, where the workload read is sharper.
        role = ("pitcher" if pitcher["batters_faced"] >= batter["plate_appearances"]
                else "batter")
    else:
        return {"player_id": str(player_id), "role": None, "tier": UNKNOWN,
                "facts": None}
    facts = pitcher if role == "pitcher" else batter
    tier = pitcher_tier(pitcher) if role == "pitcher" else batter_tier(batter)
    return {"player_id": str(player_id), "role": role, "tier": tier,
            "facts": facts}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_event(event, cutoff, *, index=None, store=sp.DEFAULT_STORE,
                lineup=None, transaction=None) -> dict:
    """Descriptive pre-event relevance for one `rosterwatch.events()` event.

    `event` is taken VERBATIM from rosterwatch -- its `class`, `detail` and
    ids are read, nothing else is required and nothing is mutated. `cutoff`
    is the point-in-time boundary (a date, an ISO string, or a datetime,
    reduced to its calendar day); pitches on or after it are invisible.

    Optional context the watch stores cannot supply on their own:
      * `lineup` -- the ordered player ids of the affected side as posted
        BEFORE a hitter scratch, which is where a lineup slot comes from;
      * `transaction` -- the parsed `mlb_news` record for a transaction
        event, because the transaction watch store keeps only the id.
    Both are pre-event facts; without them the affected fields are absent
    with a reason, never inferred.

    Returns {"class", "tier", "rank", "cutoff", "basis", "reasons",
    "unknown_reason", "not_an_edge"}. `basis` is the list of pre-event facts
    the tier rests on, each with its sample size.
    """
    if index is None:
        index = build_index(cutoff, store=store)
    event_class = (event or {}).get("class")
    detail = (event or {}).get("detail") or {}

    if event_class == rosterwatch.STARTER_SCRATCH:
        result = _score_starter_scratch(index, detail)
    elif event_class == rosterwatch.HITTER_SCRATCH:
        result = _score_hitter_scratch(index, detail, lineup)
    elif event_class == rosterwatch.LINEUP_POSTED:
        result = {"tier": LINEUP_POSTED_TIER, "basis": [],
                  "reasons": [LINEUP_POSTED_REASON], "unknown_reason": None}
    elif event_class == rosterwatch.TRANSACTION_SEEN:
        result = _score_transaction(index, transaction)
    else:
        raise RelevanceError(
            f"no relevance rule for event class {event_class!r}; the four "
            "rosterwatch classes are the only shapes this module scores")

    return {"class": event_class,
            "tier": result["tier"],
            "rank": tier_rank(result["tier"]),
            "cutoff": index.get("cutoff"),
            "basis": result["basis"],
            "reasons": result["reasons"],
            "unknown_reason": result["unknown_reason"],
            "not_an_edge": NOT_AN_EDGE}


def _score_starter_scratch(index, detail) -> dict:
    """A listed probable replaced: the scratched arm's record decides the tier.

    The replacement's record is carried too, and does one thing: an
    established starter replaced by another established starter is closer to
    a like-for-like swap than a star replaced by an unknown, so that case
    steps down one notch. It never steps anything UP -- a replacement cannot
    make the pitcher who was scratched more of a known quantity than he is.
    """
    scratched_id, replacement_id = detail.get("from"), detail.get("to")
    if scratched_id is None:
        return {"tier": UNKNOWN, "basis": [], "reasons": [],
                "unknown_reason": ("the event names no scratched pitcher, so "
                                   "there is no record to read")}

    scratched = _pitcher_facts(index, scratched_id)
    tier = pitcher_tier(scratched)
    basis = [dict(scratched, player_id=str(scratched_id), role="pitcher",
                  part="scratched", tier=tier)]
    reasons, unknown_reason = [], None

    replacement_tier = None
    if replacement_id is not None:
        replacement = _pitcher_facts(index, replacement_id)
        replacement_tier = pitcher_tier(replacement)
        basis.append(dict(replacement, player_id=str(replacement_id),
                          role="pitcher", part="replacement",
                          tier=replacement_tier))

    if tier == UNKNOWN:
        unknown_reason = (
            f"pitcher {scratched_id} threw no pitches in the store before the "
            "cutoff, so how much the market had priced into him is unknown, "
            "not low")
        return {"tier": tier, "basis": basis, "reasons": reasons,
                "unknown_reason": unknown_reason}

    reasons.append(
        f"the scratched starter had {scratched['starting_appearances']} "
        f"appearance(s) of at least {STARTING_APPEARANCE_PITCHES} pitches "
        f"({scratched['pitches']} pitches, {scratched['appearances']} "
        "appearances) before the cutoff")
    if tier == HIGH and replacement_tier == HIGH:
        tier = _shift(tier, -1)
        reasons.append(
            "the listed replacement is himself an established starter by the "
            "same measure, so the swap is nearer like-for-like")
    return {"tier": tier, "basis": basis, "reasons": reasons,
            "unknown_reason": None}


def _score_hitter_scratch(index, detail, lineup) -> dict:
    """A posted lineup loses listed hitters: the biggest loss sets the tier.

    Several names can vanish between two captures (a lineup re-posted with
    two changes). Each is scored on its own record and slot, and the tier is
    the HIGHEST of them -- the market's response to a re-post is dominated by
    the largest single hole, and averaging a star out against a bench bat
    would understate exactly the events this scale exists to separate.
    """
    removed = detail.get("removed") or []
    if not removed:
        return {"tier": UNKNOWN, "basis": [], "reasons": [],
                "unknown_reason": ("the event names no removed hitter, so "
                                   "there is no record to read")}

    order = [str(pid) for pid in (lineup or [])]
    basis, tiers, reasons = [], [], []
    for player_id in removed:
        facts = _batter_facts(index, player_id)
        tier = batter_tier(facts)
        slot = order.index(str(player_id)) + 1 if str(player_id) in order else None
        if slot in TOP_SLOTS:
            tier = _shift(tier, +1)
        elif slot in BOTTOM_SLOTS:
            tier = _shift(tier, -1)
        tiers.append(tier)
        basis.append(dict(facts, player_id=str(player_id), role="batter",
                          part="removed", lineup_slot=slot, tier=tier))
        if tier == UNKNOWN:
            continue
        slot_note = (f"batting {slot}" if slot
                     else "lineup slot not supplied")
        reasons.append(
            f"hitter {player_id} had {facts['plate_appearances']} plate "
            f"appearances over {facts['games']} games before the cutoff "
            f"({slot_note})")

    tier = _best(tiers)
    unknown_reason = None
    if tier == UNKNOWN:
        unknown_reason = (
            "none of the removed hitters had a plate appearance in the store "
            "before the cutoff, so their value to tonight's lineup is "
            "unknown, not low")
    return {"tier": tier, "basis": basis, "reasons": reasons,
            "unknown_reason": unknown_reason}


def _score_transaction(index, transaction) -> dict:
    """A roster move: the category says whether it can matter, the player's
    own record says how much.

    The transactions watch store keeps only the id it first saw (that is all
    a first-seen bracket needs), so without the parsed feed record there is
    nothing to score -- and that is reported as UNKNOWN, not assumed small.
    """
    if not transaction:
        return {"tier": UNKNOWN, "basis": [], "reasons": [],
                "unknown_reason": ("the transaction watch store keeps only the "
                                   "id; without the parsed feed record there "
                                   "is no player or category to score")}

    category = transaction.get("category")
    player_id = transaction.get("player_id")
    if player_id is None:
        return {"tier": UNKNOWN, "basis": [], "reasons": [],
                "unknown_reason": ("the transaction names no player, so there "
                                   "is no record to read")}

    profile = player_profile(index, player_id)
    basis = [dict(profile.get("facts") or {}, player_id=profile["player_id"],
                  role=profile["role"], part="moved", tier=profile["tier"],
                  category=category)]
    if profile["tier"] == UNKNOWN:
        return {"tier": UNKNOWN, "basis": basis, "reasons": [],
                "unknown_reason": (
                    f"player {player_id} has no pitches or plate appearances "
                    "in the store before the cutoff -- a call-up nobody has "
                    "seen is unknown, not low")}

    if category not in AVAILABILITY_CATEGORIES:
        return {"tier": LOW, "basis": basis,
                "reasons": [f"category {category!r} does not change who is "
                            "available tonight"],
                "unknown_reason": None}

    tier = profile["tier"]
    reasons = [f"the moved player is a {profile['role']} with "
               + (f"{profile['facts']['pitches']} pitches over "
                  f"{profile['facts']['appearances']} appearances"
                  if profile["role"] == "pitcher" else
                  f"{profile['facts']['plate_appearances']} plate appearances "
                  f"over {profile['facts']['games']} games")
               + " before the cutoff"]
    if category in DEPTH_CATEGORIES and tier == HIGH:
        tier = _shift(tier, -1)
        reasons.append(
            f"a {category} move is a bottom-of-roster action by construction, "
            "so it is capped below the top tier however large the record")
    return {"tier": tier, "basis": basis, "reasons": reasons,
            "unknown_reason": None}


# ---------------------------------------------------------------------------
# Batch and prose
# ---------------------------------------------------------------------------

def score_events(events, cutoff, *, store=sp.DEFAULT_STORE, index=None,
                 lineups_by_game=None, transactions=None) -> list:
    """score_event over a slate's events, building the index exactly once.

    `lineups_by_game` is {game_pk: {"away": [ids], "home": [ids]}} as posted
    before the scratch; `transactions` is {transaction_id: parsed record}.
    Both are optional -- an event whose context is missing scores on what is
    available and says what was not.
    """
    if index is None:
        index = build_index(cutoff, store=store)
    out = []
    for event in events or []:
        detail = event.get("detail") or {}
        side = detail.get("side")
        lineup = None
        if side:
            lineup = ((lineups_by_game or {}).get(event.get("game_pk"))
                      or {}).get(side)
        transaction = (transactions or {}).get(event.get("transaction_id"))
        score = score_event(event, cutoff, index=index, lineup=lineup,
                            transaction=transaction)
        out.append(dict(score, event=event))
    return out


def what_changed(score) -> str:
    """One sentence for the Analyzer's "what changed" section.

    Says the tier, then WHY -- the pre-event facts, with their samples -- so
    the sentence can be read without the dict behind it. An UNKNOWN says it
    is unknown and why, because "we have no record of this player" is the
    honest thing for a reader to see rather than a quiet omission.
    """
    label = {rosterwatch.STARTER_SCRATCH: "Listed starter changed",
             rosterwatch.HITTER_SCRATCH: "Posted lineup lost a listed hitter",
             rosterwatch.LINEUP_POSTED: "Lineup posted",
             rosterwatch.TRANSACTION_SEEN: "Roster move seen",
             }.get(score.get("class"), "Roster event")
    if score.get("tier") == UNKNOWN:
        return (f"{label}: relevance UNKNOWN -- "
                f"{score.get('unknown_reason')}.")
    detail = "; ".join(score.get("reasons") or [])
    return (f"{label}: relevance {score.get('tier')}"
            + (f" -- {detail}." if detail else "."))
