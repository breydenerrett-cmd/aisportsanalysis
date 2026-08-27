"""Open-Meteo weather provider. Free, keyless, no attribution required.

Supplies temperature, wind speed, wind direction, and humidity at game time
for a ballpark's coordinates.

ON WIND DIRECTION
-----------------
This provider returns `wind_from_deg`, the meteorological convention: the
direction the wind is coming FROM. A reading of 180 means wind out of the
south, blowing toward the north.

Getting that backwards inverts every wind classification, so the field is named
for what it is rather than the ambiguous "wind_dir". Turning it into the fact
that matters -- blowing out, in, or across -- requires the park's orientation
and lives in src/data/parks.py. That bearing is currently unverified for every
park, so wind is collected but not yet applied as a model input.

ON HISTORICAL WEATHER
---------------------
The forecast endpoint only covers the near future. Backfilling weather for past
seasons requires the archive endpoint, which is a different host and has a
multi-day lag. `fetch_archive` handles that; `fetch_forecast` handles upcoming
games. Using the wrong one for a given date silently returns nothing useful,
so `fetch_for_game` picks based on the date.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

FORECAST_HOST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_HOST = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "aisportsanalysis/0.1 (stdlib urllib)"
DEFAULT_TIMEOUT = 20

HOURLY_FIELDS = "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m"

# The archive endpoint lags real time. Dates newer than this many days back are
# not reliably present, so the forecast endpoint is used instead.
ARCHIVE_LAG_DAYS = 5


# Open-Meteo rate-limits, and the archive endpoint is stricter than the
# forecast one -- confirmed by hitting a 429 on the very first archive call
# during development. A season-long weather backfill is thousands of requests,
# so retry with backoff is required infrastructure, not a nicety.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 2.0


class WeatherError(RuntimeError):
    """Raised when weather cannot be fetched or the response is unusable."""


class WeatherRateLimited(WeatherError):
    """Raised when Open-Meteo is still rate-limiting after every retry.

    Distinct from WeatherError so a backfill can slow itself down rather than
    treating the date as permanently unavailable.
    """


def _get_json(url: str, params: dict, timeout: int = DEFAULT_TIMEOUT,
              max_attempts: int = MAX_ATTEMPTS, sleep=time.sleep):
    """Single network seam, with backoff on retryable statuses.

    `sleep` is injected so tests can verify backoff without actually waiting.
    """
    full = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    last_status = None

    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            if exc.code not in RETRYABLE_STATUS or attempt == max_attempts - 1:
                break
            sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))
        except urllib.error.URLError as exc:
            raise WeatherError(f"could not reach Open-Meteo: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise WeatherError("Open-Meteo returned invalid JSON") from exc

    if last_status == 429:
        raise WeatherRateLimited(
            f"Open-Meteo rate-limited after {max_attempts} attempts; "
            "slow the request rate or spread the backfill over a longer window"
        )
    raise WeatherError(f"Open-Meteo returned HTTP {last_status}")


def _base_params(lat: float, lon: float) -> dict:
    _validate_coordinates(lat, lon)
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY_FIELDS,
        "timezone": "UTC",
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
    }


def fetch_forecast(lat: float, lon: float, game_date,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Hourly forecast for a park on a date. Near-future dates only."""
    day = _validate_date(game_date)
    params = _base_params(lat, lon)
    params.update({"start_date": day, "end_date": day})
    return _get_json(FORECAST_HOST, params, timeout=timeout)


def fetch_archive(lat: float, lon: float, game_date,
                  timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Hourly historical observations. Used for backfilling past seasons."""
    day = _validate_date(game_date)
    params = _base_params(lat, lon)
    params.update({"start_date": day, "end_date": day})
    return _get_json(ARCHIVE_HOST, params, timeout=timeout)


def extract_hour(payload: dict, target_utc) -> dict:
    """Pull the observation closest to first pitch out of an hourly payload.

    Returns None for any field the response did not carry rather than
    substituting a default. A missing humidity reading is blank, never zero --
    zero humidity is a real value and would be a lie here.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise WeatherError("weather response contained no hourly data")

    target = _to_utc_datetime(target_utc)
    index, best = None, None
    for i, stamp in enumerate(times):
        try:
            moment = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        gap = abs((moment - target).total_seconds())
        if best is None or gap < best:
            index, best = i, gap

    if index is None:
        raise WeatherError("weather response contained no parseable timestamps")

    def at(field):
        series = hourly.get(field)
        if not isinstance(series, list) or index >= len(series):
            return None
        return series[index]

    return {
        "observed_utc": times[index],
        "hours_from_first_pitch": round(best / 3600.0, 2) if best is not None else None,
        "temp_f": at("temperature_2m"),
        "humidity_pct": at("relative_humidity_2m"),
        "wind_mph": at("wind_speed_10m"),
        "wind_from_deg": at("wind_direction_10m"),
    }


def fetch_for_game(lat: float, lon: float, start_time_utc,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Weather at first pitch, choosing forecast or archive by date.

    Picking the wrong endpoint returns an empty series rather than an error,
    which would look like "no weather available" instead of "wrong endpoint" --
    so the choice is made here rather than left to callers.
    """
    moment = _to_utc_datetime(start_time_utc)
    day = moment.date()
    age_days = (datetime.now(timezone.utc).date() - day).days

    if age_days > ARCHIVE_LAG_DAYS:
        payload = fetch_archive(lat, lon, day, timeout=timeout)
        source = "archive"
    else:
        payload = fetch_forecast(lat, lon, day, timeout=timeout)
        source = "forecast"

    reading = extract_hour(payload, moment)
    reading["source"] = source
    return reading


def _validate_coordinates(lat, lon):
    for label, value, limit in (("latitude", lat, 90.0), ("longitude", lon, 180.0)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WeatherError(f"{label} must be numeric, got {value!r}")
        if value != value or abs(float(value)) > limit:
            raise WeatherError(f"{label} out of range: {value!r}")


def _validate_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise WeatherError(f"date must be a string or date, got {value!r}")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise WeatherError(f"date must be ISO format, got {value!r}") from exc


def _to_utc_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise WeatherError(f"timestamp must be a string or datetime, got {value!r}")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WeatherError(f"could not parse timestamp {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
