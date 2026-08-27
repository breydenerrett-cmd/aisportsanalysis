"""Point-in-time starting pitcher features.

WHY THIS IS THE MOST IMPORTANT MISSING INPUT
--------------------------------------------
The team-only model beats a base rate by a small margin and has a prediction range of
roughly 0.41 to 0.62 -- it is nearly always close to a coin flip. That is not a bug in
the fitting; it is what team records alone can tell you about a baseball game.

The starting pitcher is the single largest determinant of one game's outcome, and the
market prices it heavily. A model that cannot see who is pitching is guaranteed to
disagree with the market mostly at random.

SAME LOOKAHEAD DISCIPLINE AS TEAM FEATURES
------------------------------------------
Season-to-date pitcher stats from the API include the entire season. Attaching a
pitcher's final-season ERA to a game in May tells the model how the pitcher went on to
perform, which is exactly the leak that makes a backtest look brilliant and lose money.

Everything here accumulates a GAME LOG forward and reads only appearances strictly
before the target date, mirroring `features.games_before`.

ON xFIP
-------
The charter asks for xFIP weighted above ERA. xFIP replaces a pitcher's actual home runs
with an expected number derived from fly balls, and fly-ball data is not in this feed. So
xFIP is NOT computed, and nothing here is labelled xFIP.

FIP is computed instead, from home runs, walks, strikeouts, and innings -- all present.
It is the closest honest relative, it strips out defense and sequencing luck the way the
charter wanted, and it is labelled FIP because that is what it is. Calling it xFIP would
be a lie that survives right into the model.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.providers import mlb

DEFAULT_LOG_STORE = Path("data/historical/pitcher_logs.jsonl")

# Below this many prior innings a rate statistic is noise. Two starts of ERA says
# nothing, and emitting it invites the model to learn from small-sample luck.
MIN_INNINGS_FOR_RATES = 20.0

# Recent-form window, in starts. Three is the common "how is he throwing lately"
# horizon and is short enough to react to a genuine change.
RECENT_STARTS = 3

# FIP's constant scales the metric onto the ERA scale. It is league- and season-specific
# and is DERIVED from the data here rather than hardcoded, so it stays correct as run
# environments shift.
DEFAULT_FIP_CONSTANT = 3.10


class PitcherError(RuntimeError):
    """Raised when pitcher logs cannot be built or read."""


# ---------------------------------------------------------------------------
# Log store
# ---------------------------------------------------------------------------

def read_logs(path=DEFAULT_LOG_STORE) -> dict:
    """Load cached appearances keyed by person_id."""
    target = Path(path)
    if not target.exists():
        return {}
    logs = {}
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a truncated final line costs one appearance
            person = record.get("person_id")
            if person is None:
                continue
            logs.setdefault(str(person), []).append(record)
    for appearances in logs.values():
        appearances.sort(key=lambda a: a.get("date") or "")
    return logs


def write_logs(logs: dict, path=DEFAULT_LOG_STORE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for person in sorted(logs, key=lambda p: int(p)):
            for appearance in logs[person]:
                handle.write(json.dumps(appearance, separators=(",", ":")) + "\n")
    return str(target)


def probable_pitcher_ids(store) -> set:
    """Every pitcher who was a listed probable in the results store."""
    ids = set()
    for row in store.values():
        for key in ("away_probable_id", "home_probable_id"):
            value = row.get(key)
            if value not in (None, ""):
                ids.add(str(value))
    return ids


def build_log_store(person_ids, season, path=DEFAULT_LOG_STORE,
                    resume: bool = True, on_pitcher=None, timeout: int = 20,
                    flush_every: int = 25) -> dict:
    """Fetch and cache game logs for a set of pitchers.

    Resumable and idempotent, for the same reason the results ingest is: several hundred
    sequential requests will be interrupted. A pitcher already cached for this season is
    skipped, and progress is flushed periodically so an interruption does not discard
    everything collected.

    A pitcher with zero appearances is cached as an explicit empty marker. Without it,
    an injured pitcher would be re-fetched on every run forever, indistinguishable from
    one never attempted.
    """
    logs = read_logs(path)
    season = str(season)
    targets = []
    for person in sorted(set(str(p) for p in person_ids), key=int):
        if resume and _has_season(logs.get(person, []), season):
            continue
        targets.append(person)

    errors = []
    processed = 0
    for person in targets:
        try:
            appearances = mlb.fetch_pitcher_game_log(person, season, timeout=timeout)
        except mlb.MLBError as exc:
            errors.append({"person_id": person, "error": str(exc)})
            continue

        kept = [a for a in logs.get(person, []) if a.get("season") != season]
        if appearances:
            kept.extend(appearances)
        else:
            # Explicit "fetched, none found" marker so this is never re-fetched.
            kept.append({"person_id": int(person), "season": season,
                         "date": None, "empty": True})
        logs[person] = sorted(kept, key=lambda a: a.get("date") or "")

        processed += 1
        if on_pitcher is not None:
            on_pitcher({"person_id": person, "appearances": len(appearances)})
        if flush_every and processed % flush_every == 0:
            write_logs(logs, path)

    write_logs(logs, path)
    return {
        "requested": len(set(str(p) for p in person_ids)),
        "attempted": len(targets),
        "skipped_cached": len(set(str(p) for p in person_ids)) - len(targets),
        "processed": processed,
        "failed": len(errors),
        "errors": errors,
        "pitchers_in_store": len(logs),
        "appearances": sum(len([a for a in v if not a.get("empty")])
                           for v in logs.values()),
        "path": str(path),
    }


def _has_season(appearances, season) -> bool:
    return any(a.get("season") == season for a in appearances)


# ---------------------------------------------------------------------------
# Point-in-time features
# ---------------------------------------------------------------------------

def appearances_before(logs, person_id, cutoff_date) -> list:
    """Appearances strictly before a date. The gated accessor, as with team features."""
    cutoff = _to_date(cutoff_date)
    result = []
    for appearance in logs.get(str(person_id), []):
        if appearance.get("empty") or not appearance.get("date"):
            continue
        try:
            if _to_date(appearance["date"]) >= cutoff:
                continue
        except PitcherError:
            continue
        result.append(appearance)
    result.sort(key=lambda a: a["date"])
    return result


def _totals(appearances) -> dict:
    def add(field):
        return sum(a.get(field) or 0 for a in appearances)
    return {
        "appearances": len(appearances),
        "starts": add("games_started"),
        "innings": sum(a.get("innings_pitched") or 0.0 for a in appearances),
        "earned_runs": add("earned_runs"),
        "hits": add("hits"),
        "walks": add("walks"),
        "strikeouts": add("strikeouts"),
        "home_runs": add("home_runs"),
        "batters_faced": add("batters_faced"),
    }


def league_fip_constant(logs, cutoff_date) -> float:
    """Derive FIP's constant from every appearance before the cutoff.

    FIP is scaled so its league average equals league ERA. That offset shifts with the
    run environment, so deriving it from the data keeps the metric honest across seasons
    instead of hardcoding a number that silently goes stale.

    Falls back to a documented default when there is not yet enough history.
    """
    cutoff = _to_date(cutoff_date)
    innings = earned = hr = bb = k = 0.0
    for appearances in logs.values():
        for appearance in appearances:
            if appearance.get("empty") or not appearance.get("date"):
                continue
            try:
                if _to_date(appearance["date"]) >= cutoff:
                    continue
            except PitcherError:
                continue
            innings += appearance.get("innings_pitched") or 0.0
            earned += appearance.get("earned_runs") or 0
            hr += appearance.get("home_runs") or 0
            bb += appearance.get("walks") or 0
            k += appearance.get("strikeouts") or 0

    if innings < 500:
        return DEFAULT_FIP_CONSTANT
    league_era = earned * 9.0 / innings
    raw_fip = ((13.0 * hr) + (3.0 * bb) - (2.0 * k)) / innings
    return round(league_era - raw_fip, 4)


def _fip(totals, constant) -> float:
    """FIP, not xFIP. Home runs, walks, strikeouts, innings -- no fly-ball data needed.

    Hit batsmen are omitted because the feed does not carry them here; the effect is
    small and consistent, but it is a real deviation from the canonical formula and is
    recorded rather than glossed over.
    """
    innings = totals["innings"]
    if innings <= 0:
        return None
    raw = ((13.0 * totals["home_runs"]) + (3.0 * totals["walks"])
           - (2.0 * totals["strikeouts"])) / innings
    return round(raw + constant, 4)


def pitcher_features(logs, person_id, as_of_date, prefix="",
                     fip_constant=None) -> dict:
    """Point-in-time features for one starting pitcher.

    Rates are suppressed below MIN_INNINGS_FOR_RATES. A 1.50 ERA over nine innings is
    not a good pitcher, it is two good starts, and the model should not be handed it as
    though it were a rate.
    """
    prior = appearances_before(logs, person_id, as_of_date)
    totals = _totals(prior)
    innings = totals["innings"]
    thin = innings < MIN_INNINGS_FOR_RATES
    constant = (fip_constant if fip_constant is not None
                else league_fip_constant(logs, as_of_date))

    features = {
        f"{prefix}sp_known": bool(person_id) and bool(prior),
        f"{prefix}sp_appearances": totals["appearances"],
        f"{prefix}sp_innings": round(innings, 2),
        f"{prefix}sp_thin": thin,
    }

    if thin or innings <= 0:
        for field in ("era", "whip", "k9", "bb9", "hr9", "k_bb_pct", "fip",
                      "ip_per_start"):
            features[f"{prefix}sp_{field}"] = None
    else:
        features[f"{prefix}sp_era"] = round(totals["earned_runs"] * 9.0 / innings, 4)
        features[f"{prefix}sp_whip"] = round(
            (totals["hits"] + totals["walks"]) / innings, 4)
        features[f"{prefix}sp_k9"] = round(totals["strikeouts"] * 9.0 / innings, 4)
        features[f"{prefix}sp_bb9"] = round(totals["walks"] * 9.0 / innings, 4)
        features[f"{prefix}sp_hr9"] = round(totals["home_runs"] * 9.0 / innings, 4)
        features[f"{prefix}sp_fip"] = _fip(totals, constant)

        # K-BB% is explicitly named in the charter and is a better predictor than
        # either strikeout or walk rate alone.
        faced = totals["batters_faced"]
        features[f"{prefix}sp_k_bb_pct"] = (
            round((totals["strikeouts"] - totals["walks"]) / faced, 4)
            if faced else None)

        # Innings per start decides how much bullpen the game exposes.
        features[f"{prefix}sp_ip_per_start"] = (
            round(innings / totals["starts"], 3) if totals["starts"] else None)

    # Recent form, on its own threshold: three starts is meaningful regardless of
    # how much season has accumulated.
    recent = [a for a in prior if (a.get("games_started") or 0) > 0][-RECENT_STARTS:]
    recent_totals = _totals(recent)
    complete = len(recent) == RECENT_STARTS and recent_totals["innings"] > 0
    features[f"{prefix}sp_recent_starts"] = len(recent)
    features[f"{prefix}sp_recent_era"] = (
        round(recent_totals["earned_runs"] * 9.0 / recent_totals["innings"], 4)
        if complete else None)
    features[f"{prefix}sp_recent_ip_per_start"] = (
        round(recent_totals["innings"] / RECENT_STARTS, 3) if complete else None)

    features[f"{prefix}sp_days_rest"] = _days_rest(prior, as_of_date)
    return features


def _days_rest(appearances, as_of_date):
    if not appearances:
        return None
    try:
        gap = (_to_date(as_of_date) - _to_date(appearances[-1]["date"])).days
    except (PitcherError, KeyError):
        return None
    # Beyond a fortnight this is an injury layoff rather than rest, and an uncapped
    # value would let the model key on calendar position.
    return min(gap, 14) if gap >= 0 else None


def matchup_pitcher_features(logs, away_id, home_id, game_date,
                             fip_constant=None) -> dict:
    """Both starters plus differentials, mirroring the team feature shape."""
    constant = (fip_constant if fip_constant is not None
                else league_fip_constant(logs, game_date))
    features = {}
    features.update(pitcher_features(logs, away_id, game_date, prefix="away_",
                                     fip_constant=constant))
    features.update(pitcher_features(logs, home_id, game_date, prefix="home_",
                                     fip_constant=constant))

    for base in ("sp_era", "sp_whip", "sp_fip", "sp_k9", "sp_k_bb_pct",
                 "sp_ip_per_start"):
        away_value = features.get(f"away_{base}")
        home_value = features.get(f"home_{base}")
        # Home minus away, consistent with the team features. For ERA-like metrics
        # lower is better, so a negative difference favours the home side.
        features[f"diff_{base}"] = (
            round(home_value - away_value, 4)
            if away_value is not None and home_value is not None else None
        )

    features["either_sp_thin"] = bool(
        features.get("away_sp_thin") or features.get("home_sp_thin"))
    features["both_sp_known"] = bool(
        features.get("away_sp_known") and features.get("home_sp_known"))
    return features


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise PitcherError(f"date must be a string or date, got {value!r}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise PitcherError(f"date must be ISO format, got {value!r}") from exc
