"""The shared point-in-time matchup matrix: one structured row per lineup game.

WHY THIS MODULE EXISTS
----------------------
Every hypothesis so far recomputed pitcher, lineup and matchup state from
scratch -- a full walk of the 2.7M-pitch store per question. The expensive part
of any lineup-shaped hypothesis is identical across hypotheses: what did we
know about tonight's starters and the nine hitters actually posted, as of a
cutoff before first pitch. So that state is computed ONCE per game here, from
the already-proven point-in-time sources, and cached as JSONL. Testing the
next pre-registered hypothesis becomes a table lookup, not a rebuild.

WHERE EVERY NUMBER COMES FROM
-----------------------------
Three sources, all audited point-in-time clean:
  - rebuilt accumulators (src/pipeline/rebuilt.py): forward accumulations over
    per-pitch rows that each carry their own date; a cutoff is a filter.
  - the posted-lineup store (src/pipeline/lineup_store.py): the nine hitters
    actually sent out, fetched per historical date.
  - the results CSV (data/historical/mlb_results.csv): schedule facts only --
    date, teams, probable starters, start time.
Nothing here touches a live season-to-date endpoint, so no row can know the
future. Rows exist only for games with a posted lineup, because every feature
is about the lineup actually played, not the club in aggregate.

CUTOFFS ARE MONTHLY, AND ONLY EVER BEHIND THE GAME
--------------------------------------------------
The stage2 runner proved the memory shape: ~7 snapshots per season from ONE
date-ordered walk of the pitch store (build_snapshots), not one walk per game.
Each game reads the snapshot taken on the first day of ITS OWN month --
under-informed by up to a month, never over-informed by a second. A game
before the store's first pitch (opening week of the store's first season)
reads an empty accumulation and reports honest Nones, NOT the next snapshot:
the next snapshot contains the game's own pitches, and that is a leak.

SIDES CROSS OVER, ONCE, HERE
----------------------------
Every away_-prefixed feature describes the AWAY LINEUP'S matchup, which is
against the HOME starter -- away_starter_platoon_gap is the split of the
starter the away lineup faces, i.e. the home team's. Same crossing as
rebuilt_sections and briefing. Getting this wrong yields a confident,
precisely wrong number on every game, which is why it happens in exactly one
place: the (side, opposing_key) pairing in row_for_game.

NONE OVER GUESS, AND GAPS ARE RECORDED
--------------------------------------
A feature whose input is missing (no probable starter, split below rebuilt's
60-BF floor, arsenal below the 50-pitch floor, no handedness) is None, and the
row's "gaps" list names what was missing and why. A blank that cannot explain
itself is indistinguishable from a bug; a gaps entry is coverage accounting.

RESUMABLE THE SAME WAY THE LINEUP STORE IS
------------------------------------------
Dates already present in the file (as rows or an explicit empty marker) are
skipped on rerun, so an interrupted season build continues instead of
re-walking the pitch store from zero. A date whose games all lack a posted
lineup writes {"date", "empty": true} -- absence from the file must always
mean "never built", never "built and found nothing".
"""

from __future__ import annotations

import json
from datetime import date as date_type
from pathlib import Path

from src.pipeline import history
from src.pipeline import lineup_store
from src.pipeline import lineups as lineup_mod
from src.pipeline import rebuilt
from src.providers import statcast_pitches as sp

DEFAULT_OUT_DIR = Path("data/research")

# Discovery data is 2023-2024 only. 2025-26 are tuning/sealed sets; building
# or reading a matrix for them from this module would put sealed data one
# import away from every hypothesis, so the guard is structural, not policy.
ALLOWED_SEASONS = (2023, 2024)


class MatrixError(RuntimeError):
    """Raised when the matchup matrix cannot be built or read honestly."""


# ---------------------------------------------------------------------------
# Build and read
# ---------------------------------------------------------------------------

def build(season, *, out_dir=DEFAULT_OUT_DIR, dates=None, force=False,
          store=None, results=None, lineups_by_pk=None, handedness=None) -> Path:
    """Write matchup_matrix_{season}.jsonl for every lineup game, resumably.

    Idempotent: dates already in the file are skipped, so a rerun with the
    same arguments is a no-op and an interrupted run resumes. force=True
    discards the file and rebuilds. `dates` limits the build to those dates
    (a slice for a bounded session; the orchestrator runs the rest later --
    the same monthly-cutoff snapshots are used either way, so a slice row is
    byte-identical to the full run's row).

    `store`, `results`, `lineups_by_pk` and `handedness` are injectable so
    tests run on synthetic fixtures; defaults read the real stores.
    """
    if season not in ALLOWED_SEASONS:
        raise MatrixError(f"season {season} is outside the discovery set "
                          f"{ALLOWED_SEASONS}; 2025+ is tuning/sealed data")
    target = Path(out_dir) / f"matchup_matrix_{season}.jsonl"
    if force and target.exists():
        target.unlink()

    if results is None:
        results = history.read_results()
    games = [row for row in results.values()
             if (row.get("date") or "").startswith(str(season))]

    wanted = sorted({g["date"] for g in games if g.get("date")})
    if dates is not None:
        requested = {value.isoformat() if isinstance(value, date_type)
                     else str(value).strip() for value in dates}
        wanted = [d for d in wanted if d in requested]
    covered = _covered_dates(target)
    missing = [d for d in wanted if d not in covered]
    if not missing:
        return target  # everything requested is already built

    if lineups_by_pk is None:
        lineups_by_pk = lineup_store.read()
    if handedness is None:
        handedness = _load_handedness()

    # ONE date-ordered walk of the pitch store for every cutoff at once --
    # the build_snapshots contract, and the whole reason a season build is
    # minutes, not hours. Snapshot count stays at ~7/season (monthly), which
    # is the memory footprint the stage2 runner already proved out.
    cutoffs = sorted({_cutoff_for(d) for d in missing})
    snapshots = rebuilt.build_snapshots(
        cutoffs, store=store if store is not None else sp.DEFAULT_STORE)
    totals_by_cutoff = {}  # per-batter all-pitch aggregation, once per cutoff

    by_date = {}
    for game in games:
        by_date.setdefault(game.get("date"), []).append(game)

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for day in missing:
            cutoff = _cutoff_for(day)
            acc = snapshots[cutoff]
            if cutoff not in totals_by_cutoff:
                totals_by_cutoff[cutoff] = _batter_totals(acc)
            written = 0
            for game in sorted(by_date.get(day, []),
                               key=lambda g: str(g.get("game_pk"))):
                posted = lineups_by_pk.get(str(game.get("game_pk")))
                if not posted or not (posted.get("away") or posted.get("home")):
                    continue  # no posted lineup -> no row, by definition
                row = row_for_game(acc, game, posted, handedness,
                                   batter_totals=totals_by_cutoff[cutoff])
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                written += 1
            if not written:
                # Coverage marker: this date was BUILT and had no lineup
                # games. Without it, a rerun could not tell an off-day from a
                # date the build never reached.
                handle.write(json.dumps({"date": day, "empty": True}) + "\n")
            # Flush per date so a crash costs one date, not the whole run.
            handle.flush()
    return target


def read(season, *, out_dir=DEFAULT_OUT_DIR) -> dict:
    """Stored matrix rows keyed by game_pk (str). Missing file is empty.

    Keys are str for the same reason lineup_store.read's are: the results
    store round-trips game_pk through CSV, and a join that disagrees on key
    type silently matches nothing.
    """
    if season not in ALLOWED_SEASONS:
        raise MatrixError(f"season {season} is outside the discovery set "
                          f"{ALLOWED_SEASONS}; 2025+ is tuning/sealed data")
    target = Path(out_dir) / f"matchup_matrix_{season}.jsonl"
    out = {}
    for row in _read_rows(target):
        if row.get("empty") or not row.get("game_pk"):
            continue
        out[str(row["game_pk"])] = row
    return out


# ---------------------------------------------------------------------------
# One game's row
# ---------------------------------------------------------------------------

def row_for_game(acc, game, posted_lineup, handedness,
                 batter_totals=None) -> dict:
    """Every matrix feature for one game, from one rebuilt snapshot.

    Pure: everything it reads arrives as an argument, so tests exercise it on
    tiny synthetic accumulations built through rebuilt's own public API.
    `batter_totals` is the per-batter all-pitch aggregation (_batter_totals);
    build() precomputes it once per cutoff, a lone caller may omit it.
    """
    handedness = handedness or {}
    if batter_totals is None:
        batter_totals = _batter_totals(acc)

    row = {
        # Game-level facts, verbatim from the results CSV (schedule data).
        "game_pk": str(game.get("game_pk")),
        "date": game.get("date"),
        "away_team": game.get("away_team"),
        "home_team": game.get("home_team"),
        "start_time_utc": game.get("start_time_utc"),
        # Provenance: the accumulation's own cutoff, so a row can prove which
        # snapshot produced it rather than the build having to be trusted.
        "cutoff": acc.get("cutoff"),
    }
    gaps = []

    # The crossing happens here and only here: a side's features describe its
    # LINEUP, which faces the OPPOSING probable starter.
    for side, opposing_key in (("away", "home_probable_id"),
                               ("home", "away_probable_id")):
        prefix = side + "_"
        slots = (posted_lineup or {}).get(side) or []
        pitcher_id = game.get(opposing_key)
        opponent = "home" if side == "away" else "away"

        for name in ("lineup_platoon_share", "starter_platoon_gap",
                     "lineup_vs_primary_pitch", "primary_pitch",
                     "primary_pitch_share", "top_minus_bottom",
                     "lineup_vs_starter_history"):
            row[prefix + name] = None

        if not slots:
            gaps.append(f"{prefix}lineup: no posted {side} lineup stored")
        if not pitcher_id:
            gaps.append(f"{prefix}opposing_starter: no probable starter "
                        f"listed for the {opponent} side")

        throws = ((handedness.get(str(pitcher_id)) or {}).get("throws")
                  if pitcher_id else None)

        # lineup_platoon_share -- posted lineup (lineup_store) x handedness
        # cache x the opposing starter's hand; the live math, reused.
        if slots and pitcher_id:
            advantage = lineup_mod.platoon_advantage_share(
                slots, handedness, throws)
            row[prefix + "lineup_platoon_share"] = advantage["share"]
            if advantage["share"] is None:
                gaps.append(f"{prefix}lineup_platoon_share: "
                            f"{advantage['reason']}")

        # starter_platoon_gap -- rebuilt.platoon_split of the OPPOSING
        # starter (wOBA vs L minus vs R), pitch rows before the cutoff only.
        # Below the shared 60-BF-per-side floor it is None, not a small-sample
        # number.
        if pitcher_id:
            split = rebuilt.platoon_split(acc, pitcher_id)
            if split.get("usable"):
                row[prefix + "starter_platoon_gap"] = split["gap"]
            else:
                gaps.append(f"{prefix}starter_platoon_gap: {split['reason']}")

        # lineup_vs_primary_pitch -- rebuilt.pitch_mix names the opposing
        # starter's most-used pitch (50-pitch floor applied inside), then
        # rebuilt.batter_vs_pitch_type gives each posted hitter's line against
        # it; the lineup number is PA-weighted so a 3-PA fluke cannot swamp a
        # 60-PA read.
        if pitcher_id:
            mix = rebuilt.pitch_mix(acc, pitcher_id)
            if mix:
                primary = mix[0]  # pitch_mix sorts by usage, most-used first
                row[prefix + "primary_pitch"] = primary["pitch_type"]
                row[prefix + "primary_pitch_share"] = round(
                    primary["usage_pct"] / 100.0, 4)
                if slots:
                    weighted, pa_total = 0.0, 0
                    for slot in slots:
                        line = rebuilt.batter_vs_pitch_type(
                            acc, slot.get("person_id"), primary["pitch_type"])
                        if line["pa"] and line["woba"] is not None:
                            weighted += line["woba"] * line["pa"]
                            pa_total += line["pa"]
                    if pa_total:
                        row[prefix + "lineup_vs_primary_pitch"] = round(
                            weighted / pa_total, 4)
                    else:
                        gaps.append(
                            f"{prefix}lineup_vs_primary_pitch: no posted "
                            f"hitter has a measured line against "
                            f"{primary['pitch_type']} before the cutoff")
            else:
                gaps.append(
                    f"{prefix}lineup_vs_primary_pitch: starter has fewer "
                    f"than {rebuilt.MIN_PITCHES_FOR_MIX} pitches before the "
                    f"cutoff, so his primary pitch is unknown")

        # top_minus_bottom -- the lineup's own quality shape: pooled wOBA of
        # slots 1-4 minus slots 5-9, each batter aggregated across ALL pitch
        # types from the rebuilt batter_vs_pitch accumulation. Pooled
        # (sum value / sum denom), not a mean of per-batter rates, so a 2-PA
        # hitter cannot count as much as a 300-PA one.
        if slots:
            top = [s for s in slots if _order(s) is not None
                   and 1 <= _order(s) <= 4]
            bottom = [s for s in slots if _order(s) is not None
                      and _order(s) >= 5]
            top_woba = _pooled_woba(top, batter_totals)
            bottom_woba = _pooled_woba(bottom, batter_totals)
            if top_woba is not None and bottom_woba is not None:
                row[prefix + "top_minus_bottom"] = round(
                    top_woba - bottom_woba, 4)
            else:
                missing_half = [label for label, value in
                                (("slots 1-4", top_woba),
                                 ("slots 5-9", bottom_woba))
                                if value is None]
                gaps.append(f"{prefix}top_minus_bottom: no measured wOBA for "
                            f"{' or '.join(missing_half)} before the cutoff")

        # lineup_vs_starter_history -- the posted lineup's pooled career line
        # against this exact starter, from the rebuilt matchup accumulation
        # (per-pitch rows before the cutoff). pa == 0 with woba None is a
        # FACT (no history), not a gap -- the input was present and answered.
        # The PA count is kept because thin history debunks, it never proves.
        if slots and pitcher_id:
            value, denom = 0.0, 0
            matchup = acc.get("matchup") or {}
            for slot in slots:
                entry = matchup.get(
                    (str(slot.get("person_id")), str(pitcher_id)))
                if entry:
                    value += entry["value"]
                    denom += entry["denom"]
            row[prefix + "lineup_vs_starter_history"] = {
                "pa": denom,
                "woba": round(value / denom, 4) if denom else None,
            }

    row["gaps"] = gaps
    return row


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cutoff_for(day) -> str:
    """First day of the game's OWN month -- behind the game, never ahead.

    The stage2 runner fell back to its first cutoff for games before it,
    which handed opening-week games a snapshot containing their own pitches.
    Anchoring to the game's own month can only ever under-inform.
    """
    return f"{str(day)[:7]}-01"


def _batter_totals(acc) -> dict:
    """batter -> [woba value, denom] summed across every pitch type.

    Reads the batter_vs_pitch accumulation directly (the same pattern
    rebuilt_sections uses for acc['arsenal']) because the per-type public
    accessor would need this very enumeration to know which types exist.
    """
    totals = {}
    for key, entry in (acc.get("batter_vs_pitch") or {}).items():
        batter = str(key[0])
        slot = totals.setdefault(batter, [0.0, 0])
        slot[0] += entry["value"]
        slot[1] += entry["denom"]
    return totals


def _pooled_woba(slots, batter_totals):
    """Sum-of-value over sum-of-denom for a group of lineup slots, or None."""
    value, denom = 0.0, 0
    for slot in slots:
        entry = batter_totals.get(str(slot.get("person_id")))
        if entry:
            value += entry[0]
            denom += entry[1]
    return value / denom if denom else None


def _order(slot):
    """A slot's batting order as an int, or None -- a slot whose order is
    unknown is excluded from the top/bottom split rather than guessed into
    one half."""
    try:
        order = int(slot.get("order"))
    except (TypeError, ValueError):
        return None
    return order if order >= 1 else None


def _covered_dates(path) -> set:
    """Every date the build already attempted, empty markers included."""
    return {row.get("date") for row in _read_rows(path) if row.get("date")}


def _read_rows(path) -> list:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for number, line in enumerate(
            target.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise MatrixError(f"{target}:{number} is not valid JSON") from exc
    return rows


def _load_handedness(path=lineup_mod.DEFAULT_HANDEDNESS) -> dict:
    """The shared handedness cache, read without touching the network.

    Biographical data already topped up by the lineup-store build; a missing
    cache is empty, which surfaces as platoon-share gaps, not as a crash.
    """
    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MatrixError(f"{target} is not valid JSON") from exc
