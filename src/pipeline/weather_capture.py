"""Weather FORECAST capture: one row per game per capture tick. 0 credits.

WHY THIS EXISTS
---------------
CAPTURE NOW, RESEARCH LATER (docs/MASTER_PLAN.md Sec.1 claim 3, Appendix C.1
item 6): a forecast made six hours before first pitch cannot be reconstructed
after the fact -- Open-Meteo's forecast endpoint answers "what does the model
say right now", and that answer changes tick to tick as the model re-runs. A
forecast is evidence only because it was written down at the moment it was
true, exactly like a price snapshot (src/pipeline/snapshots.py) or a lineup
posting (src/pipeline/rosterwatch.py).

WHAT THIS COLLECTS AND WHY IT COSTS NOTHING
--------------------------------------------
For every game on today's and tomorrow's MLB schedule (the free, keyless MLB
Stats API via `mlb.fetch_games`), this fetches the free, keyless Open-Meteo
forecast for that park and records the reading closest to first pitch. No
odds-API call, no credit, ever touches this module.

APPEND-ONLY, NEVER OVERWRITE
-----------------------------
One row per game per tick, appended to data/processed/weather_forecast.jsonl
via the same ragged-append guard every other forward store in this project
uses (`snapshots._ends_ragged`), so an interrupted write costs one row rather
than corrupting the file. Calling `run()` again later -- an hour on, a day on
-- is not a duplicate: the forecast itself has likely changed, and recording
the same game again with a fresh `observed_utc` and a shrinking
`hours_to_first_pitch` is the whole point (it lets a reader later ask "did the
forecast six hours out agree with the forecast at first pitch"). Within ONE
tick each game is looked up once, so a single `run()` call cannot duplicate a
row for the same game.

ROOFED PARKS
------------
Recorded like any other park, with `roof` carrying the park's roof type
(open/retractable/fixed) from src/data/parks.py, exactly as that module
already gates wind's use as a model input elsewhere. Whether the roof was
actually open or closed for a given game is not knowable from Open-Meteo and
is not invented here; a reader who needs that decides what to trust the same
way `parks.wind_effect` already requires an explicit `roof_closed` argument
rather than guessing.

FAILURE SEMANTICS
------------------
A schedule outage or a per-park forecast failure is an honest skip line in
the report, never a crash: one bad park must not cost the rest of the slate's
readings, and a `run()` call never raises for a provider fault.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.capture import budget as budget_module
from src.data import parks as parks_provider
from src.paths import processed_path
from src.pipeline import snapshots
from src.providers import mlb as mlb_provider
from src.providers import weather as weather_provider

LOG = logging.getLogger(__name__)

DEFAULT_STORE = processed_path("weather_forecast.jsonl")

# Beyond weather.py's baseline four fields. See weather.fetch_forecast's
# docstring for why these are asked for here and never on the archive path.
EXTRA_HOURLY_FIELDS = ("precipitation_probability", "surface_pressure")

# Per-request budget. A stalled Open-Meteo or MLB call must not hang a
# capture tick that also has odds and roster polling to do in the same run.
DEFAULT_TIMEOUT = 15


class WeatherCaptureError(RuntimeError):
    """Raised when the store or the clock is unusable. Never for a provider fault."""


def run(env=None, now=None, store=DEFAULT_STORE, mlb=mlb_provider,
        weather=weather_provider, parks=parks_provider,
        timeout=DEFAULT_TIMEOUT) -> dict:
    """One capture tick: today's and tomorrow's slate, one row each, appended.

    `env` is accepted for signature symmetry with the other capture modules
    (weather_capture needs no key and never reads it); `mlb`/`weather`/
    `parks` are injectable so tests spend nothing and touch no network.
    """
    clock_now = _now(now)
    report = {"observed_utc": _utc_iso(clock_now), "games": 0, "rows": 0,
              "errors": []}

    # Budget guard (docs/planning/attack.md F13), for signature symmetry
    # with dense/prop_listing/prop_prices only: this call spends 0 credits,
    # so `can_spend` never gates it on the floor or the envelope -- see that
    # function's zero-credit short-circuit. It exists here purely so
    # "weather" stays a family this module is honest about, not because
    # this capture can ever actually be refused.
    decision = budget_module.can_spend("weather", 0)
    if not decision.allowed:
        print(f"weather_capture.run: {decision.reason}")
        report["skipped"] = decision.reason
        return report

    games = []
    for offset in (0, 1):
        day = (clock_now + timedelta(days=offset)).date().isoformat()
        try:
            games.extend(mlb.fetch_games(day, timeout=timeout))
        except Exception as exc:  # noqa: BLE001 -- a schedule outage is a skip, not a crash
            report["errors"].append(f"schedule {day}: {exc}")

    report["games"] = len(games)

    rows = []
    for game in games:
        row, error = _capture_one(game, clock_now, weather, parks, timeout)
        if error:
            report["errors"].append(error)
        if row is not None:
            rows.append(row)

    report["rows"] = append(rows, store)
    return report


def _capture_one(game, now, weather, parks, timeout):
    """One game's reading, or (None, error). Never raises."""
    game_pk = game.get("game_pk")
    commence = game.get("start_time_utc")
    home_team = game.get("home_team")
    if not commence or not home_team:
        return None, None  # nothing to key this row on -- not a failure, just unusable

    start = _parse_iso(commence)
    if start is None:
        return None, f"game {game_pk}: unparseable start time {commence!r}"

    try:
        park = parks.get_park(home_team)
    except parks.ParkError as exc:
        return None, f"game {game_pk}: {exc}"

    try:
        payload = weather.fetch_forecast(
            park["lat"], park["lon"], start.date(), timeout=timeout,
            extra_hourly_fields=EXTRA_HOURLY_FIELDS)
        reading = weather.extract_hour(payload, start)
    except weather.WeatherError as exc:
        return None, f"game {game_pk}: {exc}"

    row = {
        "observed_utc": _utc_iso(now),
        "game_pk": game_pk,
        "game_date": game.get("date"),
        "park": parks.canonical_team(home_team),
        "venue": game.get("venue"),
        "commence_time": commence,
        "hours_to_first_pitch": round((start - now).total_seconds() / 3600.0, 3),
        "roof": park.get("roof"),
        "temp_f": reading.get("temp_f"),
        "humidity_pct": reading.get("humidity_pct"),
        "wind_mph": reading.get("wind_mph"),
        "wind_from_deg": reading.get("wind_from_deg"),
        "precip_probability_pct": reading.get("precip_probability_pct"),
        "pressure_hpa": reading.get("pressure_hpa"),
        "forecast_hour_utc": reading.get("observed_utc"),
        "forecast_hour_offset_hours": reading.get("hours_from_first_pitch"),
        "source": "forecast",
        # Open-Meteo's public forecast endpoint does not expose a model-run
        # timestamp -- recorded honestly as None rather than substituting
        # `generationtime_ms` (how long the response took to build, a
        # different fact entirely) or fabricating one.
        "provider_run_time": None,
    }
    return row, None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def append(rows, path=DEFAULT_STORE) -> int:
    """Append rows as JSON Lines. Never rewrites, never de-duplicates in place.

    Same ragged-append guard as every other forward store in this project
    (`snapshots._ends_ragged`), so a run killed mid-write costs one row
    rather than corrupting the next capture's first line.
    """
    if not rows:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        if snapshots._ends_ragged(target):
            handle.write("\n")
        for row in rows:
            handle.write(_dumps(row) + "\n")
    return len(rows)


def read(path=DEFAULT_STORE) -> list:
    """Every row in the store. A corrupt line is logged and skipped."""
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
        except json.JSONDecodeError:
            LOG.warning("weather_capture: %s:%s is not valid JSON (likely an "
                        "interrupted append); skipped", target, number)
    return rows


def _dumps(row) -> str:
    return json.dumps(row, sort_keys=True)


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def _now(now):
    if now is None:
        return datetime.now(timezone.utc)
    moment = now() if callable(now) else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise WeatherCaptureError(
            "the clock must return a timezone-aware datetime; a naive "
            "observation time cannot honestly bracket a forecast")
    return moment


def _utc_iso(moment) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _load_dotenv(path=None) -> None:
    """Read .env into os.environ. Values already exported win.

    A local copy rather than an import from src.cli, matching prop_listing's
    reasoning: this module is run standalone by the capture script.
    """
    env_file = Path(path) if path else Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv=None) -> int:
    """Entry point for `python3 -m src.pipeline.weather_capture`. 0 credits."""
    _load_dotenv()
    report = run()
    print(f"weather capture: {report['games']} game(s), {report['rows']} row(s)")
    for error in report.get("errors") or []:
        print(f"  skip: {error}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
