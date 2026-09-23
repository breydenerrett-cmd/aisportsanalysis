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
from datetime import date, datetime, timezone
from pathlib import Path

from src.paths import historical_path
from src.pipeline import store_archive
from src.providers import mlb

DEFAULT_LOG_STORE = historical_path("pitcher_logs.jsonl")

# Below this many prior innings a rate statistic is noise. Two starts of ERA says
# nothing, and emitting it invites the model to learn from small-sample luck.
MIN_INNINGS_FOR_RATES = 20.0

# How long a current-season "checked" marker is trusted before `refresh=True`
# will re-fetch that pitcher again. The daily loop calls this once/day, so 20h
# (comfortably under 24h) means one refetch per calendar day per pitcher even
# if the job's run time drifts a little -- never a same-day double-fetch, but
# never a day silently skipped either. See `build_log_store`'s docstring for
# why this exists at all (2026-09-22, the "0 pitchers fetched" incident).
DEFAULT_REFRESH_AFTER_HOURS = 20.0

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
                    flush_every: int = 25, *, refresh: bool = False,
                    refresh_after_hours: float = DEFAULT_REFRESH_AFTER_HOURS,
                    max_refetch_per_run: int | None = None, now=None) -> dict:
    """Fetch and cache game logs for a set of pitchers.

    TWO DIFFERENT CONTRACTS, ONE FUNCTION -- read this before changing either.

    `resume=True, refresh=False` (the default) is HISTORICAL/BACKFILL semantics:
    "this season is finished, do not touch it again." A pitcher is skipped the
    moment ANY row -- a real appearance or the empty marker -- exists for
    `season` (`_has_season`). That is correct and cheap for a season nothing
    will ever add rows to (2025 and earlier, sealed per CLAUDE.md), which is
    the only case `scripts/backfill_pitchers_bullpen_2025.py` and this
    function's original callers ever used it for.

    `refresh=True` is ONGOING-SEASON semantics: "this season is still
    accruing appearances, come back and check again." Passing the CURRENT
    season through the historical contract above is exactly the bug found
    2026-09-22 ("0 pitchers fetched" for five straight daily runs since
    2026-09-19, reported by the owner, no written postmortem yet):
    `_has_season` returns True the moment a starter
    has ONE cached 2026 row, so every later start that same starter makes is
    never fetched again, and an explicit empty-season marker (an injured or
    not-yet-debuted pitcher) is "complete" forever even after his first
    appearance. Under `refresh=True`:

      * a pitcher never checked this season (no marker at all) is always
        fetched -- covers a rookie call-up exactly like a never-attempted one
        always did;
      * a pitcher already checked this season is re-fetched only once
        `checked_utc` on that season's marker is older than
        `refresh_after_hours` (default `DEFAULT_REFRESH_AFTER_HOURS`) --
        bounds the work to about once per calendar day per pitcher rather
        than re-pulling everyone's whole season on every invocation of a
        script that might run more than once a day;
      * `max_refetch_per_run`, if given, caps how many pitchers get
        refetched in one call, oldest-checked/never-checked first -- a
        resumable, bounded budget in the same spirit as
        `docs/COLLECTION_POLICY.md`'s credit envelope, even though this
        provider is free and keyless: nothing here should be able to turn
        into an unbounded number of blocking HTTP calls in one run. Anyone
        left out this run is untouched (not marked, not skipped-forever) and
        is exactly what the NEXT run's staleness check picks up first.

    A REFRESH NEVER LOSES DATA ON FAILURE. `mlb.MLBError` for a person leaves
    `logs[person]` completely untouched -- old appearances AND the old
    `checked_utc` marker survive exactly as they were, so a failed fetch is
    retried on the very next run rather than silently marked done.

    A REFRESH NEVER DUPLICATES A ROW. Every successful fetch replaces ALL of
    that person's rows for `season` (`kept = [... if a.get("season") !=
    season]`) with the freshly returned list before writing back -- the same
    "full season log, oldest first" contract `mlb.fetch_pitcher_game_log`
    already returns on every call, so a provider correction (an inning count
    revised after review, say) lands as a clean replace, never an append next
    to a stale duplicate.

    Resumable and idempotent within one run for the same reason the results
    ingest is: several hundred sequential requests will be interrupted, and
    progress is flushed periodically so an interruption does not discard
    everything collected.
    """
    logs = read_logs(path)
    season = str(season)
    now_dt = _now(now) if refresh else None

    all_ids = sorted(set(str(p) for p in person_ids), key=int)
    targets = []
    for person in all_ids:
        existing = logs.get(person, [])
        if not resume:
            targets.append(person)
            continue
        if refresh:
            marker = coverage_marker(existing, season)
            if marker is None or _marker_is_stale(marker, now_dt, refresh_after_hours):
                targets.append(person)
            continue
        if _has_season(existing, season):
            continue
        targets.append(person)

    truncated = 0
    if refresh and max_refetch_per_run is not None and len(targets) > max_refetch_per_run:
        def staleness_key(person):
            marker = coverage_marker(logs.get(person, []), season)
            checked = marker.get("checked_utc") if marker else None
            # Never-checked (marker is None -> checked is None) sorts before
            # any real timestamp, so brand-new pitchers are never starved by
            # a budget that is otherwise full of merely-stale ones.
            return (checked is not None, checked or "")

        targets = sorted(targets, key=staleness_key)
        truncated = len(targets) - max_refetch_per_run
        targets = targets[:max_refetch_per_run]

    # Snapshot the store as it stood BEFORE this run touches it, so the
    # original live inputs stay reconstructible even after `write_logs`
    # below rewrites the whole file (unlike odds_multibook, this store has
    # no append-only hot/cold split of its own -- every call replaces the
    # full file). Reuses src.pipeline.store_archive's existing archive
    # directory/gzip/verification machinery (`snapshot_full`) rather than a
    # second mechanism. Only taken when something might actually change
    # (`targets` non-empty) and there is a pre-existing file to protect --
    # a no-op run must not grow the archive directory forever.
    if targets and Path(path).exists():
        store_archive.snapshot_full(path, now=now_dt if now_dt is not None else _now(None))

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
            if refresh:
                # Bookkeeping only -- `date: None` keeps this invisible to
                # appearances_before/pitcher_features (see their own "skip
                # rows with no date" guard), the same way the empty marker
                # always has been.
                kept.append({"person_id": int(person), "season": season,
                             "date": None, "empty": False,
                             "checked_utc": _iso(now_dt)})
        else:
            # Explicit "fetched, none found" marker. Under the legacy
            # (non-refresh) contract this is what made an injured pitcher
            # skip forever -- correct for a closed season, never appropriate
            # for an ongoing one, which is why `refresh` mode re-checks a
            # marker's OWN staleness instead of treating its mere presence
            # as permanent completion.
            marker = {"person_id": int(person), "season": season,
                      "date": None, "empty": True}
            if refresh:
                marker["checked_utc"] = _iso(now_dt)
            kept.append(marker)
        logs[person] = sorted(kept, key=lambda a: a.get("date") or "")

        processed += 1
        if on_pitcher is not None:
            on_pitcher({"person_id": person, "appearances": len(appearances)})
        if flush_every and processed % flush_every == 0:
            write_logs(logs, path)

    write_logs(logs, path)
    return {
        "requested": len(all_ids),
        "attempted": len(targets),
        "skipped_cached": len(all_ids) - len(targets) - truncated,
        "deferred_by_budget": truncated,
        "processed": processed,
        "failed": len(errors),
        "errors": errors,
        "pitchers_in_store": len(logs),
        "appearances": sum(len([a for a in v if not a.get("empty") and a.get("date")])
                           for v in logs.values()),
        "path": str(path),
    }


def _has_season(appearances, season) -> bool:
    """Legacy resume check: ANY row (real appearance or marker) for `season`.

    Correct only for a season nothing will ever add rows to again -- see
    `build_log_store`'s docstring. Left exactly as it always behaved so
    every historical/backfill caller (`resume=True, refresh=False`, the
    default) is unaffected by the ongoing-season refresh work added
    2026-09-22.
    """
    return any(a.get("season") == season for a in appearances)


def coverage_marker(appearances, season):
    """The bookkeeping row for `season`, if one exists: `date is None` marks
    it as a marker rather than a real appearance (an empty-season marker, or
    a refresh-mode "checked, had appearances" marker) -- both are written
    with `date: None` specifically so appearances_before/pitcher_features
    already skip them via their own "no date" guard. Returns None if this
    season has never been checked at all.

    Public (not `_`-prefixed) because callers outside this module need it
    too -- `scripts/pitcher_log_freshness_audit.py` reads a pitcher's own
    `checked_utc` to tell "not yet refreshed since this game" apart from
    "refreshed and still missing".
    """
    for a in appearances:
        if a.get("season") == season and a.get("date") is None:
            return a
    return None


def _marker_is_stale(marker, now_dt, refresh_after_hours) -> bool:
    checked = marker.get("checked_utc")
    if not checked:
        return True  # a legacy empty marker predating `checked_utc`: treat as never checked
    try:
        parsed = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
    except ValueError:
        return True  # an unparseable timestamp must not permanently suppress a refresh
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = (now_dt - parsed).total_seconds() / 3600.0
    return age_hours >= refresh_after_hours


def _now(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(now_dt: datetime) -> str:
    return now_dt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Point-in-time features
# ---------------------------------------------------------------------------

def appearances_before(logs, person_id, cutoff_date,
                       same_season_only: bool = True) -> list:
    """Appearances strictly before a date. The gated accessor, as with team features.

    Season-scoped by default for the same reason team form is: a pitcher's ERA from
    two seasons ago describes a different arm, and often a different role. Carrying it
    forward produces a number that looks plausible and is about the wrong year.
    """
    cutoff = _to_date(cutoff_date)
    season = cutoff.year
    result = []
    for appearance in logs.get(str(person_id), []):
        if appearance.get("empty") or not appearance.get("date"):
            continue
        try:
            parsed = _to_date(appearance["date"])
        except PitcherError:
            continue
        if parsed >= cutoff:
            continue
        if same_season_only and parsed.year != season:
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
        # Innings thrown IN STARTS, separately from total innings.
        #
        # ip_per_start was innings / starts, which divides a pitcher's RELIEF
        # innings by his start count. A swingman with 40 relief innings and 3
        # starts came out at 13.56 innings per start -- an impossible number that
        # nothing raised on, and that fed straight into a detector claiming the
        # bullpen would barely be used. Only innings in games he actually started
        # belong in that average.
        "innings_as_starter": sum(
            a.get("innings_pitched") or 0.0 for a in appearances
            if (a.get("games_started") or 0) > 0),
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
        # Published because an average is only as good as its denominator, and
        # a consumer of sp_ip_per_start cannot tell one start from thirty
        # without it. An opener's 1.00 innings a start is arithmetically
        # identical to an ace's collapse; only the start count separates them.
        f"{prefix}sp_starts": totals["starts"],
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

        # Innings per start decides how much bullpen the game exposes, so it has
        # to be innings AS A STARTER over starts -- see _totals.
        features[f"{prefix}sp_ip_per_start"] = (
            round(totals["innings_as_starter"] / totals["starts"], 3)
            if totals["starts"] else None)

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
        round(recent_totals["innings_as_starter"] / RECENT_STARTS, 3)
        if complete else None)

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
