"""EXAMPLE ACCOUNTS: what a bankroll would be today if it had bet every
published pick since START_DATE.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
A hypothetical. Each account starts with a stated balance on START_DATE and
puts a stake on every pick the public card published and the ledger has
settled, at the price each pick was graded at. It is arithmetic over the
public record, shown day by day, per sport and for all sports together. It is
not a real account, not a forecast, and not advice; the page that shows it
says so in the three sentences in `NOTES`.

THE ONE RULE THAT MATTERS: RECONCILE WITH THE PUBLIC RECORD, OR SHOW NOTHING
----------------------------------------------------------------------------
The site already publishes graded records (GET /card/record for MLB, NFL and
UFC). This module never re-derives which picks count. Its inputs are the rows
the record routes read (src.appstate.card_ledger's history_v2 and history),
selected with the same rules the ledger's own record functions apply, and
every sport's account is then checked against the record the site publishes
for it, pick count, wins, losses, pushes, voids and units (4 decimals),
exactly. A single difference makes `build_payload` return
`{"available": False, ...}`; there is no "close enough".

  MLB (rule v2): the counted record is regular season only, and the
  postseason picks are graded but kept out of it (registration 11.1). An
  account that followed the card would have bet the postseason picks, so the
  MLB account is the counted record PLUS the postseason cohort, and both
  halves are checked separately against the two figures the record route
  publishes. A third check ties the pooled total to record_v2's own
  `combined` figure.
  NFL, UFC: every settled pick of the rule the record counts, all market
  kinds together, each day's picks checked against that day's own totals.

WHICH ENTRIES ARE PICKS (the rule the ledger's own record functions share)
-------------------------------------------------------------------------
  * a withdrawn entry is not a pick (record_v2 counts it apart, as
    `withdrawn`);
  * a fill is never a pick (entry_class "fill") and is never bet;
  * one row per date, the newest settlement pass (history_v2 reads
    latest_settled_rows_v2, so a re-settled date is never counted twice);
  * a pick that has no result yet (UNRESOLVED) is not settled: it moves no
    balance, and its day is marked partial until it resolves.
Voids and pushes return the stake and count as zero units.

PURE. Nothing in this file reads a ledger, a clock or the network. The one
disk read is `load_config`, which reads config/example_accounts.json and
raises `ConfigError` on anything wrong: a bad file is "unavailable", never a
crash and never a guessed default.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import re
from collections import Counter
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

START_DATE = "2026-09-22"
CONFIG_PATH = os.path.join("config", "example_accounts.json")

# The sport keys this feature shows. The ledger calls UFC "mma"; the page and
# the payload say "ufc", which is what a reader sees in the address bar.
SPORTS = ("mlb", "nfl", "ufc")
VIEWS = SPORTS + ("all",)
VIEW_LABEL = {"mlb": "MLB", "nfl": "NFL", "ufc": "UFC", "all": "All sports"}
LEDGER_SPORT = {"mlb": "mlb", "nfl": "nfl", "ufc": "mma"}

# Below this many graded picks (wins plus losses) a return as a percentage is
# noise dressed as a track record, so none is printed (owner rule 2026-10-03).
MIN_GRADED_FOR_PERCENT = 30

# The ledger's result words (src.appstate.card_ledger.RESULT_*). Kept here as
# plain strings so this module imports nothing; a test pins them to the
# ledger's own constants.
RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_PUSH = "PUSH"
RESULT_VOID = "VOID"
RESULT_UNRESOLVED = "UNRESOLVED"
SETTLED_RESULTS = (RESULT_WIN, RESULT_LOSS, RESULT_PUSH, RESULT_VOID)

STAKING_FLAT = "flat"
STAKING_PERCENT = "percent_of_balance"
STAKING_KINDS = (STAKING_FLAT, STAKING_PERCENT)

NOTES = (
    "This is a hypothetical account, not a real one. It puts the same stake on every pick "
    "at the price we published.",
    "A real account would differ: prices move, sportsbooks limit bets, and nobody bets every pick.",
    "Past results do not predict future results. This is analysis, not advice.",
)
POSTSEASON_NOTE = (
    "The MLB total here is the counted record plus the postseason picks, which the counted "
    "record leaves out but an account that followed the card would have bet.")

# One plain sentence for every way this can fail. The payload says WHY in
# `reason`; the page shows its own sentence and never the reason.
UNAVAILABLE_SENTENCE = (
    "Example account balances are not available right now, so none are shown.")

_MAX_ACCOUNTS = 12
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,23}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ZERO = Decimal(0)


class AccountsError(RuntimeError):
    """The inputs cannot be turned into a number that reconciles. Always
    surfaces as `available: False`; the message is a plain sentence."""


class ConfigError(AccountsError):
    """config/example_accounts.json is missing, unreadable or invalid."""


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def validate_config(obj: Any) -> dict:
    """The parsed config, normalised, or `ConfigError`. Never a default."""
    if not isinstance(obj, Mapping):
        raise ConfigError("The example account settings are not an object.")
    start = obj.get("start_date")
    if not isinstance(start, str) or not _DATE_RE.match(start):
        raise ConfigError("The example account start date is missing or is not a date.")
    raw = obj.get("accounts")
    if not isinstance(raw, list) or not raw:
        raise ConfigError("The example account settings list no accounts.")
    if len(raw) > _MAX_ACCOUNTS:
        raise ConfigError("The example account settings list too many accounts.")
    accounts, seen = [], set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ConfigError("An example account is not an object.")
        acct_id = item.get("id")
        if not isinstance(acct_id, str) or not _ID_RE.match(acct_id):
            raise ConfigError("An example account has a missing or invalid id.")
        if acct_id in seen:
            raise ConfigError(f"Two example accounts share the id {acct_id}.")
        seen.add(acct_id)
        label = item.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ConfigError(f"Example account {acct_id} has no usable label.")
        balance = item.get("start_balance")
        if not _is_number(balance) or not 0 < balance <= 1_000_000_000:
            raise ConfigError(f"Example account {acct_id} has an invalid start balance.")
        staking = item.get("staking")
        if not isinstance(staking, Mapping) or staking.get("kind") not in STAKING_KINDS:
            raise ConfigError(f"Example account {acct_id} has an unknown staking kind.")
        if staking["kind"] == STAKING_FLAT:
            amount = staking.get("amount")
            if not _is_number(amount) or not 0 < amount <= balance:
                raise ConfigError(f"Example account {acct_id} has an invalid flat stake.")
            norm_staking = {"kind": STAKING_FLAT, "amount": amount}
        else:
            pct = staking.get("pct")
            if not _is_number(pct) or not 0 < pct <= 100:
                raise ConfigError(f"Example account {acct_id} has an invalid percentage.")
            norm_staking = {"kind": STAKING_PERCENT, "pct": pct}
        accounts.append({"id": acct_id, "label": label.strip(),
                         "start_balance": balance, "staking": norm_staking})
    return {"start_date": start, "accounts": accounts}


def load_config(path: Optional[str] = None) -> dict:
    """Read and validate the config file. `ConfigError` on any problem."""
    target = path or CONFIG_PATH
    try:
        with open(target, "r", encoding="utf-8") as fh:
            parsed = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ConfigError("The example account settings could not be read.") from exc
    return validate_config(parsed)


# ---------------------------------------------------------------------------
# pick rows: the ledger's own rows, selected by the ledger's own rules
# ---------------------------------------------------------------------------

def _dec(value: Any) -> Decimal:
    return Decimal(str(float(value)))


def _units(result: str, profit: Any) -> Decimal:
    """Units for a 1-unit stake. A win or loss carries the ledger's own
    `profit_units`; a push or void returns the stake, which is zero."""
    if result in (RESULT_WIN, RESULT_LOSS):
        if not _is_number(profit):
            raise AccountsError("A graded pick in the record has no units, so nothing is shown.")
        return _dec(profit)
    return _ZERO


_SERIAL = itertools.count(1)


def make_row(date: str, sport: str, result: str, profit: Any, postseason: bool = False,
             pick_id: Optional[str] = None) -> dict:
    """One settled pick as this module carries it. `profit` is the ledger's own
    `profit_units` for a 1-unit stake (ignored for a push or void). A row made
    without a `pick_id` gets a unique one, so only a caller that gives two rows
    the same id (the same pick twice) can trip the duplicate check."""
    if pick_id is None:
        pick_id = f"{date}|{sport}|row{next(_SERIAL)}"
    return {"date": date, "sport": sport, "result": result,
            "units": _units(result, profit), "postseason": bool(postseason),
            "pick_id": pick_id}


def _check_result(result: Any) -> str:
    if result not in SETTLED_RESULTS and result != RESULT_UNRESOLVED:
        raise AccountsError("A pick in the record has a result this page does not know.")
    return result


def rows_from_v2_days(days: Sequence[Mapping], sport: str = "mlb") -> tuple:
    """(rows, waiting_dates) from `history_v2`-shaped days.

    The selection is the one every V2 reader of the ledger shares: skip a
    withdrawn entry, skip a fill, count the rest. `postseason` is the flag
    api.card._mark_postseason put on each entry, decided the way the counted
    record decides it; an entry with no flag is regular season, which is what
    the record does with it too."""
    rows, waiting = [], set()
    for day in days or ():
        date = str((day or {}).get("date") or "")
        if not date:
            raise AccountsError("A day in the record has no date.")
        for entry in (day.get("graded") or ()):
            if not isinstance(entry, Mapping):
                continue
            if entry.get("withdrawn") or entry.get("entry_class") == "fill":
                continue
            result = _check_result(entry.get("result"))
            if result == RESULT_UNRESOLVED:
                waiting.add(date)
                continue
            game = entry.get("game_pk") if entry.get("game_pk") is not None else entry.get("game_id")
            who = entry.get("player_id") or entry.get("player") or entry.get("team_name") or entry.get("team")
            pick_id = "|".join(str(p) for p in (
                date, sport, entry.get("kind") or "game", game, who,
                entry.get("market"), entry.get("line"), entry.get("side")))
            rows.append(make_row(date, sport, result, entry.get("profit_units"),
                             entry.get("postseason"), pick_id))
    return rows, waiting


_V1_LISTS = (("picks", "game", ""), ("prop_picks", "prop", "prop_"), ("total_picks", "total", "total_"))


def rows_from_v1_days(days: Sequence[Mapping], sport: str) -> tuple:
    """(rows, waiting_dates) from `history`-shaped days (NFL, UFC).

    card_ledger.record() sums each day's own scalar totals, not the pick
    lists, so the lists are only trusted where they add up to those totals:
    for every day and every kind (game, prop, total) the wins, losses,
    pushes, voids and units of the listed picks must equal the day's own
    figures. A day that does not add up is an `AccountsError`, never a
    guess."""
    rows, waiting = [], set()
    for day in days or ():
        date = str((day or {}).get("date") or "")
        if not date:
            raise AccountsError("A day in the record has no date.")
        for key, kind, prefix in _V1_LISTS:
            listed = Counter()
            listed_units = _ZERO
            for pick in (day.get(key) or ()):
                result = _check_result((pick or {}).get("result"))
                if result == RESULT_UNRESOLVED:
                    waiting.add(date)
                    listed["unresolved"] += 1
                    continue
                listed[result] += 1
                row = make_row(date, sport, result, pick.get("profit_units"), False,
                           "|".join(str(p) for p in (date, sport, kind, pick.get("bet"),
                                                    pick.get("market"), pick.get("line"),
                                                    pick.get("side"))))
                listed_units += row["units"]
                rows.append(row)
            stated = {
                RESULT_WIN: day.get(f"{prefix}wins") or 0,
                RESULT_LOSS: day.get(f"{prefix}losses") or 0,
                RESULT_PUSH: day.get(f"{prefix}pushes") or 0,
                RESULT_VOID: day.get(f"{prefix}voids") or 0,
                "unresolved": day.get(f"{prefix}unresolved") or 0,
            }
            if any(listed[name] != stated[name] for name in stated) or round(
                    float(listed_units), 4) != round(float(day.get(f"{prefix}profit_units") or 0.0), 4):
                raise AccountsError(
                    f"The {VIEW_LABEL.get(sport, sport)} picks for {date} do not add up to "
                    "that day's own totals, so nothing is shown.")
    return rows, waiting


# ---------------------------------------------------------------------------
# totals and the reconciliation with the published record
# ---------------------------------------------------------------------------

def tally(rows: Iterable[Mapping]) -> dict:
    """Pick count, wins, losses, pushes, voids and units (4 decimals)."""
    wins = losses = pushes = voids = 0
    units = _ZERO
    for row in rows:
        result = row["result"]
        if result == RESULT_WIN:
            wins += 1
        elif result == RESULT_LOSS:
            losses += 1
        elif result == RESULT_PUSH:
            pushes += 1
        elif result == RESULT_VOID:
            voids += 1
        units += row["units"]
    return {"picks": wins + losses + pushes + voids, "wins": wins, "losses": losses,
            "pushes": pushes, "voids": voids, "units": round(float(units), 4)}


def _record_figures(source: Any, what: str) -> dict:
    if not isinstance(source, Mapping):
        raise AccountsError(f"The published {what} is not available, so nothing is shown.")
    out = {}
    for field in ("wins", "losses", "pushes", "voids"):
        value = source.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise AccountsError(f"The published {what} is not available, so nothing is shown.")
        out[field] = value
    units = source.get("profit_units")
    if not _is_number(units):
        raise AccountsError(f"The published {what} is not available, so nothing is shown.")
    out["picks"] = out["wins"] + out["losses"] + out["pushes"] + out["voids"]
    out["units"] = round(float(units), 4)
    return {k: out[k] for k in ("picks", "wins", "losses", "pushes", "voids", "units")}


def _sum_figures(parts: Sequence[Mapping]) -> dict:
    out = {k: sum(p[k] for p in parts) for k in ("picks", "wins", "losses", "pushes", "voids")}
    out["units"] = round(float(sum((Decimal(str(p["units"])) for p in parts), _ZERO)), 4)
    return out


def reference_from_record(sport: str, record: Mapping) -> dict:
    """The record numbers one sport's account is checked against, read off
    the payload GET /card/record serves for it.

    MLB (v2): `counted` is the headline (regular season), `postseason` the
    cohort the record keeps apart, `combined` record_v2's own pooled figure.
    NFL and UFC: every market kind the record carries, pooled, which is the
    one population the site calls "every pick" (effective_record's headline).
    """
    if not isinstance(record, Mapping):
        raise AccountsError(f"The published {VIEW_LABEL[sport]} record is not available, "
                            "so nothing is shown.")
    what = f"{VIEW_LABEL[sport]} record"
    if sport == "mlb":
        combined = record.get("combined")
        return {
            "counted": _record_figures(record, what),
            "postseason": _record_figures(record.get("postseason"), f"{what} for the postseason"),
            "combined": _record_figures(combined, what) if combined is not None else None,
        }
    by_kind = record.get("by_kind")
    if isinstance(by_kind, Mapping) and by_kind:
        parts = [_record_figures(by_kind[kind], what)
                 for kind in ("game", "prop", "total") if by_kind.get(kind) is not None]
        counted = _sum_figures(parts)
    else:
        counted = _record_figures(record, what)
    return {"counted": counted, "postseason": None, "combined": None}


def _differences(label: str, account: Mapping, record: Mapping) -> list:
    return [f"{label}: {name} {account[name]} against {record[name]} in the record"
            for name in ("picks", "wins", "losses", "pushes", "voids", "units")
            if account[name] != record[name]]


def reconcile(sport: str, rows: Sequence[Mapping], reference: Mapping,
              start_date: Optional[str] = None) -> dict:
    """One sport's account population against the published record.

    The whole of what the record counts is checked first; `start_date` is
    then a plain filter on the dates of those same rows (`from_start`). `ok`
    only when every figure matches exactly. The returned dict is what the
    payload publishes under `reconciled`, numbers on both sides."""
    problems = []
    counted_rows = [r for r in rows if not r["postseason"]]
    post_rows = [r for r in rows if r["postseason"]]
    account = tally(rows)
    counted = tally(counted_rows)
    post = tally(post_rows)
    problems += _differences("counted record", counted, reference["counted"])
    if reference.get("postseason") is not None:
        problems += _differences("postseason", post, reference["postseason"])
    elif post["picks"]:
        problems.append("postseason picks found where the record has none")
    if reference.get("combined") is not None:
        problems += _differences("pooled record", account, reference["combined"])
    ids = Counter(r["pick_id"] for r in rows)
    repeated = sum(1 for n in ids.values() if n > 1)
    if repeated:
        problems.append(f"{repeated} pick(s) appear more than once")
    from_start = tally(r for r in rows if start_date is None or r["date"] >= start_date)
    return {
        "ok": not problems,
        "sport": sport,
        "account": account,
        "from_start": from_start,
        "counted_record": dict(reference["counted"]),
        "postseason_record": dict(reference["postseason"]) if reference.get("postseason") else None,
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# the accounts
# ---------------------------------------------------------------------------

def _days(rows: Sequence[Mapping], waiting: Iterable[str]) -> list:
    by_date: dict = {}
    for row in rows:
        day = by_date.setdefault(row["date"], {
            "date": row["date"], "wins": 0, "losses": 0, "pushes": 0, "voids": 0,
            "units": _ZERO, "postseason_picks": 0})
        key = {RESULT_WIN: "wins", RESULT_LOSS: "losses", RESULT_PUSH: "pushes",
               RESULT_VOID: "voids"}[row["result"]]
        day[key] += 1
        day["units"] += row["units"]
        if row["postseason"]:
            day["postseason_picks"] += 1
    waiting = set(waiting)
    return [dict(by_date[d], partial=d in waiting) for d in sorted(by_date)]


def _stake(account: Mapping, balance: Decimal) -> Decimal:
    staking = account["staking"]
    if staking["kind"] == STAKING_FLAT:
        return _dec(staking["amount"])
    # A percentage of a balance that has gone to zero or below is zero: an
    # account cannot stake money it does not have, and a negative stake would
    # turn a loss into a gain.
    return max(balance, _ZERO) * _dec(staking["pct"]) / Decimal(100)


def series_for(account: Mapping, view: str, rows: Sequence[Mapping],
               waiting: Iterable[str], start_date: str) -> dict:
    """One account's day-by-day balance for one sport view.

    `flat`: the same dollar stake on every pick. `percent_of_balance`: every
    pick on a day is staked at that percentage of the balance at the START of
    the day (picks on one day are concurrent). A day's result is stake times
    the day's units; a push or void is zero. Decimal arithmetic throughout;
    dollars are rounded to cents only where the page prints them."""
    in_play = [r for r in rows if r["date"] >= start_date]
    start = _dec(account["start_balance"])
    balance = start
    lowest, lowest_date = start, start_date
    daily = []
    for day in _days(in_play, waiting):
        stake = _stake(account, balance)
        result = stake * day["units"]
        balance += result
        if balance < lowest:
            lowest, lowest_date = balance, day["date"]
        daily.append({
            "date": day["date"],
            "picks": day["wins"] + day["losses"] + day["pushes"] + day["voids"],
            "wins": day["wins"], "losses": day["losses"],
            "pushes": day["pushes"], "voids": day["voids"],
            "units": round(float(day["units"]), 4),
            "stake": float(stake),
            "result": float(result),
            "balance": float(balance),
            "postseason": day["postseason_picks"] > 0,
            "postseason_picks": day["postseason_picks"],
            "partial": day["partial"],
        })
    totals = tally(in_play)
    graded = totals["wins"] + totals["losses"]
    return_pct = None
    if graded >= MIN_GRADED_FOR_PERCENT:
        return_pct = round(float((balance - start) / start * 100), 2)
    return {
        "sport": view,
        "label": VIEW_LABEL[view],
        "start_balance": float(start),
        "final_balance": float(balance),
        "total_units": totals["units"],
        "picks": totals["picks"], "wins": totals["wins"], "losses": totals["losses"],
        "pushes": totals["pushes"], "voids": totals["voids"],
        "graded": graded,
        "days": len(daily),
        "lowest_balance": float(lowest),
        "lowest_date": lowest_date,
        "return_pct": return_pct,
        "small_sample": graded < MIN_GRADED_FOR_PERCENT,
        "postseason_picks": sum(d["postseason_picks"] for d in daily),
        "daily": daily,
    }


def _check_series(series: Mapping[str, Mapping]) -> None:
    """What is printed adds up to what is claimed: each series' daily rows sum
    to its totals and its final balance, and the all-sports series is exactly
    the three sports added together. Anything else is `AccountsError`."""
    for view, one in series.items():
        daily = one["daily"]
        for field in ("picks", "wins", "losses", "pushes", "voids"):
            if sum(d[field] for d in daily) != one[field]:
                raise AccountsError("The day-by-day rows do not add up to their total, "
                                    "so nothing is shown.")
        if round(sum(d["units"] for d in daily), 4) != one["total_units"]:
            raise AccountsError("The day-by-day rows do not add up to their total, "
                                "so nothing is shown.")
        expected = one["start_balance"] + sum(d["result"] for d in daily)
        if abs(expected - one["final_balance"]) > 1e-6 * max(1.0, abs(expected)):
            raise AccountsError("The day-by-day rows do not add up to the final balance, "
                                "so nothing is shown.")
    for field in ("picks", "wins", "losses", "pushes", "voids"):
        if sum(series[s][field] for s in SPORTS) != series["all"][field]:
            raise AccountsError("The all-sports account is not the three sports added "
                                "together, so nothing is shown.")
    if round(sum(series[s]["total_units"] for s in SPORTS), 4) != series["all"]["total_units"]:
        raise AccountsError("The all-sports account is not the three sports added "
                            "together, so nothing is shown.")


def unavailable(reason: str, **extra: Any) -> dict:
    out = {"available": False, "reason": reason}
    out.update(extra)
    return out


def build_payload(config: Mapping, sources: Mapping[str, Mapping], *,
                  pending: Optional[Sequence[Mapping]] = None) -> dict:
    """The whole /card/accounts payload, or `unavailable(...)`.

    `sources[sport]` (sport in SPORTS) holds `rows`, `waiting` (dates with a
    pick still awaiting its result) and `reference` (see
    `reference_from_record`). Nothing is read from disk here."""
    start_date = config["start_date"]
    try:
        reconciled = {}
        rows_by_sport = {}
        waiting_all: set = set()
        for sport in SPORTS:
            source = sources.get(sport)
            if source is None:
                raise AccountsError(f"The {VIEW_LABEL[sport]} record is not available, "
                                    "so nothing is shown.")
            rows = list(source["rows"])
            rows_by_sport[sport] = rows
            waiting_all |= set(source.get("waiting") or ())
            reconciled[sport] = reconcile(sport, rows, source["reference"], start_date)
        pooled = [row for sport in SPORTS for row in rows_by_sport[sport]]
        # All sports is one account that bets every pick of the three, so its
        # total must be the sum of the three published records (MLB counted
        # plus its postseason cohort), nothing more and nothing less.
        record_parts = []
        for sport in SPORTS:
            reference = sources[sport]["reference"]
            record_parts.append(reference["counted"])
            if reference.get("postseason"):
                record_parts.append(reference["postseason"])
        expected = _sum_figures(record_parts)
        all_diffs = _differences("all sports", tally(pooled), expected)
        reconciled["all"] = {
            "ok": not all_diffs, "sport": "all", "account": tally(pooled),
            "from_start": tally(r for r in pooled if r["date"] >= start_date),
            "counted_record": expected, "postseason_record": None, "problems": all_diffs}
    except AccountsError as exc:
        return unavailable(str(exc))

    failed = [view for view in VIEWS if not reconciled[view]["ok"]]
    if failed:
        names = ", ".join(VIEW_LABEL[v] for v in failed)
        return unavailable(
            f"The account totals did not match the published record for {names}, so nothing is shown.",
            reconciled=reconciled)

    views = {"mlb": rows_by_sport["mlb"], "nfl": rows_by_sport["nfl"],
             "ufc": rows_by_sport["ufc"], "all": pooled}
    waiting_by_view = {s: sources[s].get("waiting") or () for s in SPORTS}
    waiting_by_view["all"] = waiting_all
    accounts = []
    try:
        for account in config["accounts"]:
            series = {view: series_for(account, view, views[view], waiting_by_view[view],
                                       start_date) for view in VIEWS}
            _check_series(series)
            accounts.append({
                "id": account["id"], "label": account["label"],
                "start_balance": float(account["start_balance"]),
                "staking": dict(account["staking"]),
                "series": series,
            })
    except AccountsError as exc:
        return unavailable(str(exc), reconciled=reconciled)
    settled_dates = [row["date"] for row in pooled if row["date"] >= start_date]
    return {
        "available": True,
        "start_date": start_date,
        "as_of": max(settled_dates) if settled_dates else None,
        "min_graded_for_percent": MIN_GRADED_FOR_PERCENT,
        "sports": [{"key": v, "label": VIEW_LABEL[v]} for v in VIEWS],
        "accounts": accounts,
        "reconciled": reconciled,
        "pending": [dict(p) for p in (pending or ())],
        "notes": list(NOTES),
        "postseason_note": POSTSEASON_NOTE,
    }
