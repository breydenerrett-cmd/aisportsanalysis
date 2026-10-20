"""Free result sources for the all-sports families The Odds API /scores does not cover: tennis and MMA.

WHY THIS EXISTS
---------------
`allsports_scores` grades a member dog's bet from The Odds API `/scores`. That feed has no tennis and no MMA, so
those two families could only void after 72 hours and stayed off the dog menu. Here each gets a FREE source:

  TENNIS  ESPN's ATP and WTA scoreboards (src/providers/espn_tennis_results.py)
  MMA     ESPN's UFC data, through the existing grader (src/providers/espn_mma_results.py)

Neither costs a credit. Both end in the SAME store (data/processed/allsports_scores.jsonl, append-only) and the
SAME row shape the settlement already reads, so `user_settle` needed no new path: it asks the store for the
event's row and `allsports_scores.grade_bet` grades it.

THE ROW
-------
A `score` row keyed by the ODDS API event id (the id the bet carries), with
  completed True, `home_score` / `away_score` 1.0 and 0.0 for the winner and the loser (a match-win indicator:
  sets or rounds are not comparable across a retirement or a decision), `outcome` home/away,
  or, when the bet is void, `home_score`/`away_score` None and a named `void_reason`
  (a walkover, a retirement before a set completed, a draw, a no contest, a cancelled bout);
  `source` (espn_tennis / espn_mma), `completed_utc` = the moment OUR run saw it settled (ESPN publishes no finish
  time; see espn_tennis_results), and the ESPN ids and status the result came from.

WHICH EVENTS ARE LOOKED AT
--------------------------
The family's events in the multibook store (the capture's own rows: Odds API event id, both names, start time)
that started between 20 minutes and `scores_days_from` + 1 days ago and have no completed row yet. The CI runner
that captures cannot see the hounds ledger, so this is driven by what was captured, like the Odds API poll.

MATCHING, AND WHAT NEVER GRADES
-------------------------------
An Odds API event is matched to an ESPN match only when BOTH names agree (`names.person_score`: accents,
punctuation, reversed order, initials, a dropped middle name; never a nickname) and the ESPN start is within 48
hours of the odds start, and exactly ONE ESPN match fits. Two candidates, a name that fits neither, an event ESPN
does not list (Challenger, ITF, every non-UFC MMA promotion) or a match not yet settled writes NOTHING. A
bet on an unmatched event stays pending and voids 72 hours after the start, by name, in `grade_bet`.

MMA reuses `EspnMmaResultsProvider` unchanged: its name resolution (`names.match` plus confirmed aliases), its
final-only rule, and its draw / no contest / replaced-fighter rules. A draw or no contest is a void for the
moneyline.
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Optional, Sequence

from src.datasvc import names
from src.paths import processed_path
from src.pipeline import allsports_scores as scores_mod
from src.pipeline import snapshots
from src.providers import espn_tennis_results as tennis_src
from src.sports import catalog

LOG = logging.getLogger(__name__)

FREE_SETTLES = "free_results"
SOURCE_TENNIS = "espn_tennis"
SOURCE_MMA = "espn_mma"
MATCH_WINDOW_HOURS = 48            # ESPN's scheduled start vs the odds feed's commence time
MIN_AGE_MINUTES = 20               # a match that "started" a moment ago cannot be settled yet
DEFAULT_POLL_INTERVAL_HOURS = 1.0
DEFAULT_MMA_CACHE = Path(tempfile.gettempdir()) / "linehound_espn_mma_cache"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def free_families(config: Optional[Mapping] = None) -> tuple:
    """The family codes settled from a free feed, in catalog order."""
    return tuple(code for code in catalog.family_codes(config)
                 if (catalog.family(code, config) or {}).get("settles") == FREE_SETTLES)


# ---------------------------------------------------------------------------
# which events to look for
# ---------------------------------------------------------------------------

def unresolved_events(multibook_path, index: Mapping, now: datetime, cap: Mapping,
                      config: Optional[Mapping] = None) -> dict:
    """{family code: [event dict]} for the free-result families: events of the multibook store that started
    inside the look-back window and have no completed row in `index`. Streams the file; only lines that
    mention a free family are parsed. Oldest start first."""
    wanted = {catalog.row_sport(code): code for code in free_families(config)}
    out: dict = {code: [] for code in wanted.values()}
    if not wanted:
        return out
    target = Path(multibook_path)
    if not target.exists():
        return out
    oldest = now - timedelta(days=int(cap.get("scores_days_from") or 3) + 1)
    newest = now - timedelta(minutes=MIN_AGE_MINUTES)
    latest: dict = {}
    needles = tuple(f'"{sport}"' for sport in wanted)
    with target.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not any(n in line for n in needles):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            code = wanted.get(row.get("sport"))
            if code is None or not row.get("event_id") or not row.get("home_team") or not row.get("away_team"):
                continue
            start = scores_mod._parse(row.get("commence_time"))
            if start is None:
                continue
            latest[row["event_id"]] = {
                "event_id": row["event_id"], "family": code, "commence_time": row.get("commence_time"),
                "_start": start, "home_team": row["home_team"], "away_team": row["away_team"],
                "league": row.get("league") or catalog.row_sport(code)}
    for event in latest.values():
        done = index.get(event["event_id"])
        if done is not None and done.get("completed"):
            continue
        if not (oldest <= event["_start"] <= newest):
            continue
        out[event["family"]].append(event)
    for events in out.values():
        events.sort(key=lambda e: (e["_start"], e["event_id"]))
    return out


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def result_row(event: Mapping, observed: str, *, source: str, winner: Optional[str], void_reason: Optional[str],
               evidence: Mapping) -> dict:
    """One completed `score` row in the all-sports store's shape. `winner` is 'home' or 'away' (graded) or None
    with a `void_reason` (void)."""
    if winner is not None:
        home, away = (1.0, 0.0) if winner == "home" else (0.0, 1.0)
    else:
        home = away = None
    return {
        "kind": "score", "observed_utc": observed, "sport_key": event.get("league") or event["family"].lower(),
        "event_id": event["event_id"], "commence_time": event.get("commence_time"),
        "home_team": event["home_team"], "away_team": event["away_team"], "completed": True,
        "home_score": home, "away_score": away, "outcome": winner, "scores": None, "last_update": None,
        "source": source, "completed_utc": observed, "completed_utc_basis": "observed",
        "void_reason": void_reason, "evidence": dict(evidence)}


# ---------------------------------------------------------------------------
# tennis
# ---------------------------------------------------------------------------

def match_tennis(event: Mapping, matches: Iterable["tennis_src.TennisMatch"],
                 window_hours: float = MATCH_WINDOW_HOURS) -> dict:
    """Pair one Odds API event with ONE ESPN match. -> {match, orientation ('straight': ESPN a is the odds home,
    'crossed': ESPN a is the odds away), score, reason}. match is None unless exactly one ESPN match fits."""
    window = timedelta(hours=window_hours)
    fits = []
    for match in matches:
        start = scores_mod._parse(match.start_utc)
        if start is None or abs(start - event["_start"]) > window:
            continue
        straight = min(names.person_score(event["home_team"], match.player_a),
                       names.person_score(event["away_team"], match.player_b))
        crossed = min(names.person_score(event["home_team"], match.player_b),
                      names.person_score(event["away_team"], match.player_a))
        best = max(straight, crossed)
        if best < names.PERSON_MIN or straight == crossed:
            continue
        fits.append((best, match, "straight" if straight > crossed else "crossed"))
    if not fits:
        return {"match": None, "reason": "no ESPN match with both names near the start time"}
    if len(fits) > 1:
        return {"match": None, "reason": f"ambiguous: {len(fits)} ESPN matches fit both names"}
    score, match, orientation = fits[0]
    return {"match": match, "orientation": orientation, "score": score, "reason": "matched"}


def tennis_rows(events: Sequence[Mapping], matches: Sequence["tennis_src.TennisMatch"], observed: str) -> dict:
    """{rows, matched, graded, void, pending, unresolved, unmatched: [event_id]} for the tennis events."""
    report = {"rows": [], "matched": 0, "graded": 0, "void": 0, "pending": 0, "unresolved": 0, "unmatched": []}
    for event in events:
        found = match_tennis(event, matches)
        match = found["match"]
        if match is None:
            report["unmatched"].append({"event_id": event["event_id"], "reason": found["reason"]})
            continue
        report["matched"] += 1
        verdict = tennis_src.settlement(match)
        state = verdict["state"]
        if state == tennis_src.PENDING:
            report["pending"] += 1
            continue
        if state == tennis_src.UNRESOLVED:
            report["unresolved"] += 1
            continue
        evidence = {"provider": "espn", "espn_event_id": match.espn_event_id, "espn_match_id": match.match_id,
                    "tournament": match.tournament, "tour": match.tour, "status": match.status,
                    "espn_players": [match.player_a, match.player_b], "match_score": match.score_text,
                    "matched_by": f"names.person_score {found['score']:g}, {found['orientation']}",
                    "rule": verdict["reason"]}
        if state == tennis_src.GRADED:
            side_a = match.winner == "a"
            home_won = side_a if found["orientation"] == "straight" else not side_a
            report["rows"].append(result_row(event, observed, source=SOURCE_TENNIS,
                                             winner="home" if home_won else "away", void_reason=None,
                                             evidence=evidence))
            report["graded"] += 1
        else:
            report["rows"].append(result_row(event, observed, source=SOURCE_TENNIS, winner=None,
                                             void_reason=verdict["reason"], evidence=evidence))
            report["void"] += 1
    return report


def fetch_tennis_matches(events: Sequence[Mapping], feed: "tennis_src.EspnTennisFeed") -> dict:
    """ESPN matches for every UTC date the events started on (and the next day: a late-evening start is listed
    under the following UTC date by some tournaments). -> {matches, requests_dates, errors}."""
    dates = sorted({d for e in events for d in (e["_start"].date().isoformat(),
                                                 (e["_start"] + timedelta(days=1)).date().isoformat())})
    seen, matches, errors = set(), [], []
    for date in dates:
        try:
            batch = feed.fetch_matches(date)
        except tennis_src.EspnTennisError as exc:
            errors.append(f"{date}: {exc}")
            if "browser check" in str(exc):
                break
            continue
        for match in batch:
            if (match.tour, match.match_id) not in seen:
                seen.add((match.tour, match.match_id))
                matches.append(match)
    return {"matches": matches, "dates": dates, "errors": errors}


# ---------------------------------------------------------------------------
# MMA
# ---------------------------------------------------------------------------

def default_mma_provider(cache_dir=None):
    """The ESPN UFC provider with its own throw-away cache (never written under the repo)."""
    from src.providers import espn_mma_results
    return espn_mma_results.EspnMmaResultsProvider(
        espn_mma_results.make_fetcher(cache_dir or DEFAULT_MMA_CACHE), live=True)


def mma_rows(events: Sequence[Mapping], provider, now: datetime, observed: str) -> dict:
    """{rows, matched, graded, void, unresolved, unmatched: [{event_id, reason}], errors}: each event asked of
    the ESPN provider as a `BoutIdentity`, grouped by the UTC date it starts on."""
    from src.pipeline import ufc_autograde, ufc_results
    report = {"rows": [], "matched": 0, "graded": 0, "void": 0, "pending": 0, "unresolved": 0, "unmatched": [],
              "errors": []}
    by_date: dict = {}
    for event in events:
        by_date.setdefault(event["_start"].date().isoformat(), []).append(event)
    for date, group in sorted(by_date.items()):
        bouts = [ufc_autograde.BoutIdentity(date=date, home=e["home_team"], away=e["away_team"],
                                            commence_utc=e["_start"], game_id=e["event_id"]) for e in group]
        try:
            fights = provider.fetch_for_bouts(date, bouts, now=now)
        except ufc_autograde.ProviderError as exc:
            report["errors"].append(f"{date}: {exc}")
            continue
        for event, bout in zip(group, bouts):
            decision = provider.decide(bout, fights)
            if decision.action != ufc_autograde.ACTION_RECORD:
                report["unmatched"].append({"event_id": event["event_id"], "reason": decision.reason})
                continue
            if "fighter replaced" in str((decision.provenance or {}).get("basis") or ""):
                # An INFERRED cancellation (a published fighter fought someone else) is never written here: on
                # 2026-10-17 it read Katlyn Chookagian's ESPN name, Katlyn Cerminara, as a replacement opponent
                # and would have voided a bout that happened. A bet left pending voids after 72 hours anyway;
                # only ESPN's own "canceled" status voids early.
                report["unmatched"].append({
                    "event_id": event["event_id"],
                    "reason": f"held, not graded: {decision.reason} (an inferred replacement is not trusted)"})
                continue
            report["matched"] += 1
            evidence = dict(decision.provenance or {})
            evidence["rule"] = decision.reason
            if decision.outcome == ufc_results.OUTCOME_WIN:
                if decision.winner == event["home_team"]:
                    winner = "home"
                elif decision.winner == event["away_team"]:
                    winner = "away"
                else:
                    report["unresolved"] += 1
                    continue
                report["rows"].append(result_row(event, observed, source=SOURCE_MMA, winner=winner,
                                                 void_reason=None, evidence=evidence))
                report["graded"] += 1
            elif decision.outcome in ufc_results.VOID_OUTCOMES:
                what = decision.outcome.replace("_", " ")
                report["rows"].append(result_row(
                    event, observed, source=SOURCE_MMA, winner=None,
                    void_reason=f"MMA moneyline void: the bout was a {what} ({decision.reason})", evidence=evidence))
                report["void"] += 1
            else:
                report["unresolved"] += 1
    return report


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def _last_poll(rows: Iterable[Mapping], family: str) -> Optional[datetime]:
    last = None
    for row in rows:
        if row.get("kind") == "free_poll" and row.get("family") == family:
            stamp = scores_mod._parse(row.get("observed_utc"))
            if stamp is not None and (last is None or stamp > last):
                last = stamp
    return last


def run(*, now=None, env=None, config: Optional[Mapping] = None, multibook_path=None,
        store_path=scores_mod.DEFAULT_STORE, tennis_feed=None, mma_provider=None, plan_only: bool = False,
        families: Optional[Sequence[str]] = None) -> dict:
    """One free-results tick: look up the captured tennis and MMA events with no result and append what ESPN
    settles. Spends no credits. -> {observed_utc, families: {code: report}, rows, halt}."""
    from src.pipeline import allsports_capture as cap_mod
    clock = cap_mod._now(now)
    cap = catalog.capture_config(config)
    result = {"observed_utc": _iso(clock), "families": {}, "rows": 0, "credits": 0, "halt": None}
    if not cap.get("enabled", True) or cap_mod.switched_off(env):
        result["halt"] = "disabled"
        return result
    store_rows = scores_mod._read(store_path)
    index = scores_mod.load_index(store_path)
    todo = unresolved_events(multibook_path or snapshots.DEFAULT_MULTIBOOK_PATH, index, clock, cap, config)
    interval = timedelta(hours=float(cap.get("free_results_poll_interval_hours") or DEFAULT_POLL_INTERVAL_HOURS))
    observed = _iso(clock)
    new_rows: List[dict] = []
    polls: List[dict] = []
    for code in free_families(config):
        if families is not None and code not in families:
            continue
        events = todo.get(code) or []
        info = {"events": len(events), "matched": 0, "graded": 0, "void": 0, "pending": 0, "unresolved": 0,
                "unmatched": [], "errors": [], "skipped": None}
        result["families"][code] = info
        if not events:
            continue
        last = _last_poll(store_rows, code)
        if last is not None and clock - last < interval:
            info["skipped"] = f"polled {int((clock - last).total_seconds() // 60)} minutes ago"
            continue
        if plan_only:
            continue
        if code == "TENNIS":
            feed = tennis_feed or tennis_src.EspnTennisFeed(now=lambda: clock)
            fetched = fetch_tennis_matches(events, feed)
            info["errors"] = fetched["errors"]
            if fetched["errors"] and not fetched["matches"]:
                polls.append({"kind": "free_poll", "observed_utc": observed, "family": code, "source": SOURCE_TENNIS,
                              "events": len(events), "written": 0, "errors": fetched["errors"][:5]})
                continue
            report = tennis_rows(events, fetched["matches"], observed)
            source = SOURCE_TENNIS
        elif code == "MMA":
            provider = mma_provider or default_mma_provider()
            report = mma_rows(events, provider, clock, observed)
            info["errors"] = report["errors"]
            source = SOURCE_MMA
        else:                                                   # a future free family without a reader yet
            info["skipped"] = "no free reader for this family"
            continue
        for key in ("matched", "graded", "void", "pending", "unresolved"):
            info[key] = report[key]
        info["unmatched"] = report["unmatched"]
        written = scores_mod.append_result_rows(report["rows"], store_path)
        info["written"] = written
        result["rows"] += written
        polls.append({"kind": "free_poll", "observed_utc": observed, "family": code, "source": source,
                      "events": len(events), "matched": report["matched"], "graded": report["graded"],
                      "void": report["void"], "written": written, "unmatched": len(report["unmatched"]),
                      "unmatched_ids": [u["event_id"] for u in report["unmatched"]][:25],
                      "errors": info["errors"][:5]})
    if polls:
        scores_mod._append(store_path, polls)
    return result


def summary_lines(result: Mapping) -> List[str]:
    lines = []
    if result.get("halt"):
        lines.append(f"  free results: halt: {result['halt']}")
    for code, info in sorted((result.get("families") or {}).items()):
        if info.get("skipped"):
            lines.append(f"  free results {code}: {info['events']} event(s) waiting, skipped ({info['skipped']})")
            continue
        lines.append(f"  free results {code}: {info['events']} event(s) waiting, {info['matched']} matched, "
                     f"{info['graded']} graded, {info['void']} void, {len(info['unmatched'])} unmatched, "
                     f"{info.get('written', 0)} row(s) written")
        for err in info.get("errors") or []:
            lines.append(f"    error: {err}")
    return lines


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m src.pipeline.allsports_free_results")
    parser.add_argument("--plan", action="store_true", help="list what is waiting; fetch and write nothing")
    args = parser.parse_args(argv)
    result = run(plan_only=args.plan)
    for line in summary_lines(result):
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
