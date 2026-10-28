"""One tick of capture, and the loop around it (docs/PREREG_LIVE_TENNIS.md sections 5, 6 and 9).

A tick, in order, and nothing in it can place a bet:

    1  the switch. OFF (the default) makes no request and spends no credit; the tick returns at once.
    2  the frozen-constants check against the ledger's first row, then the genesis row on the first tick.
    3  free reads: the active tennis keys, each key's free event list, the ESPN ATP and WTA scoreboards. An ESPN
       match is paired with an Odds API event by the repo's matcher (names both ways, one fit).
    4  ARM every paired match at a set start (`state.is_set_start`) not yet armed. A match with no admissible
       pre-match price or an out-of-range one is decided at once (NO_PREMATCH_PRICE / MODEL_OUT_OF_RANGE) and costs
       no credit.
    5  close what cannot continue: a window past DP_WINDOW_SECONDS (WINDOW_EXPIRED), a score that moved (SCORE_MOVED).
    6  buy at most MAX_CALLS_PER_TICK boards, one per key, decision keys first, then reference keys, then pre-match
       keys. Each is guarded (`guard.can_spend`), logged to the live credit log from its own x-requests-last,
       bracketed by a second ESPN read, and stored verbatim (`SnapshotStore`).
    7  decide every open DP of a bought key (`decision.evaluate`), write its row, and resolve references from every
       stored board (`grade.resolve_references`).
    8  a heartbeat row, one per tick, so downtime is counted and never reads as a quiet day.

Everything the loop needs after a restart is in the ledger and the snapshot store, so a tick is restartable and
`--once` is exactly one iteration of `--loop`. All network and clock access goes through `Seams`, so the tests
drive the whole machine with scripted feeds and a fake clock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from src.providers import espn_tennis_results as espn
from src.research.live_tennis import board, config, decision as decision_mod, grade, guard, state as state_mod
from src.research.live_tennis.ledger import LedgerError, PaperLedger, SnapshotStore

LOG = logging.getLogger("linehound.research.live_tennis")

MAX_CALLS_PER_TICK = 6
EVENTS_TTL_SECONDS = 300
KEYS_TTL_SECONDS = 1800
PAIR_WINDOW_HOURS = 12
P0_LOOKBACK_HOURS = 12
SKIP_KEY_SUFFIXES = ("_winner", "_winners", "_outright", "_outrights", "_futures")


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------

@dataclass
class Seams:
    clock: Callable[[], datetime]
    espn_json: Callable[[str], dict]
    list_keys: Callable[[], List[str]]
    list_events: Callable[[str], List[dict]]
    fetch_odds: Callable[[str], Tuple[List[dict], dict]]
    quota: Callable[[], dict]
    sleep: Callable[[float], None] = time.sleep


def default_seams(env: Optional[Mapping] = None) -> Seams:
    """The real feeds: the free ESPN scoreboards, The Odds API (the sports list and event lists free, odds 1 credit)."""
    from src.providers import odds

    def keys() -> List[str]:
        found = odds.fetch_sports(all_sports=False, env=env)
        return sorted(s["key"] for s in found
                      if isinstance(s, dict) and str(s.get("key") or "").startswith("tennis_")
                      and s.get("active") is not False and not str(s["key"]).endswith(SKIP_KEY_SUFFIXES))

    return Seams(
        clock=lambda: datetime.now(timezone.utc),
        espn_json=espn.default_get_json,
        list_keys=keys,
        list_events=lambda key: odds.fetch_sport_events(key, env=env),
        fetch_odds=lambda key: odds.fetch_sport_odds_with_usage(key, ("h2h",), ("us",), env=env),
        quota=lambda: odds.quota(env),
    )


def prereg_sha256(root: Optional[Path] = None) -> Optional[str]:
    """sha256 of docs/PREREG_LIVE_TENNIS.md with line endings normalised to LF, or None when it is not on disk."""
    base = root or Path(__file__).resolve().parents[3]
    path = base / config.PREREG_DOC
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ---------------------------------------------------------------------------
# the world as one tick sees it
# ---------------------------------------------------------------------------

@dataclass
class Tracked:
    key: str
    event: dict
    match: "espn.TennisMatch"
    orientation: str
    state: "state_mod.LiveState"
    server: Optional[str]                  # 'home' | 'away' | None, ESPN's possession flag (recorded, never used)

    @property
    def event_id(self) -> str:
        return self.event["id"]

    @property
    def home(self) -> str:
        return self.event["home_team"]

    @property
    def away(self) -> str:
        return self.event["away_team"]


def _espn_item(t: Optional[Tracked]) -> Optional[dict]:
    return state_mod.to_dict(t.state) if t is not None else None


class Runner:
    def __init__(self, *, ledger: Optional[PaperLedger] = None, snapshots: Optional[SnapshotStore] = None,
                 seams: Optional[Seams] = None, env: Optional[Mapping] = None, heartbeat_path=None,
                 credit_stores=None, credit_record=None, prereg_root: Optional[Path] = None):
        self.ledger = ledger or PaperLedger()
        self.snapshots = snapshots or SnapshotStore()
        self.env = env
        self.seams = seams or default_seams(env)
        self.heartbeat_path = Path(heartbeat_path) if heartbeat_path is not None else config.heartbeat_path()
        self.credit_stores = credit_stores
        self.credit_record = credit_record
        self.prereg_root = prereg_root
        self._keys_cache: Tuple[Optional[datetime], List[str]] = (None, [])
        self._events_cache: Dict[str, Tuple[datetime, List[dict]]] = {}
        self._p0: Dict[str, dict] = {}
        self._p0_loaded = False
        self._last_ok_poll: Optional[datetime] = self._read_last_ok_poll()
        self._prev_poll_for_arm: Optional[datetime] = None

    def _read_last_ok_poll(self) -> Optional[datetime]:
        """The time of the newest heartbeat row with a good ESPN read, so a restarted (or --once) run still knows the
        last poll that came before a set start. None when there is no heartbeat file yet."""
        try:
            size = self.heartbeat_path.stat().st_size
            with self.heartbeat_path.open("rb") as fh:
                fh.seek(max(0, size - 65536))
                tail = fh.read().splitlines()
        except OSError:
            return None
        for raw in reversed(tail):
            try:
                row = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if row.get("espn_ok"):
                return board.parse_utc(row.get("utc"))
        return None

    # ---- free reads -----------------------------------------------------

    def _active_keys(self, now: datetime, errors: List[str]) -> List[str]:
        stamp, keys = self._keys_cache
        if stamp is None or (now - stamp).total_seconds() >= KEYS_TTL_SECONDS:
            try:
                keys = list(self.seams.list_keys())
                self._keys_cache = (now, keys)
            except Exception as exc:  # noqa: BLE001 -- keep the old list; a failed free read never stops the tick
                errors.append(f"keys: {type(exc).__name__}")
        return [k for k in keys if config.tour_of(k)]

    def _events(self, key: str, now: datetime, errors: List[str]) -> List[dict]:
        cached = self._events_cache.get(key)
        if cached is not None and (now - cached[0]).total_seconds() < EVENTS_TTL_SECONDS:
            return cached[1]
        try:
            events = [e for e in self.seams.list_events(key) if isinstance(e, dict) and e.get("id")]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"events {key}: {type(exc).__name__}")
            return cached[1] if cached is not None else []
        self._events_cache[key] = (now, events)
        return events

    def _read_espn(self, now: datetime, errors: List[str]) -> Tuple[List["espn.TennisMatch"], Dict[str, str], bool]:
        matches: List["espn.TennisMatch"] = []
        server_by_match: Dict[str, str] = {}
        ok = False
        date_iso = now.astimezone(timezone.utc).date().isoformat()
        for tour in espn.TOURS:
            try:
                doc = self.seams.espn_json(espn.scoreboard_url(tour, date_iso))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"espn {tour}: {type(exc).__name__}")
                continue
            ok = True
            matches.extend(espn.parse_scoreboard(doc, tour))
            for mid, who in state_mod.possession_map(doc).items():
                server_by_match[f"{tour}:{mid}"] = who
        return matches, server_by_match, ok

    def _pair(self, keys: List[str], matches: List["espn.TennisMatch"], server_by_match: Mapping[str, str],
              now: datetime, errors: List[str], unmatched_live: List[str]) -> List[Tracked]:
        from src.pipeline import allsports_free_results as afr

        tracked: List[Tracked] = []
        for key in keys:
            tour = config.tour_of(key)
            candidates = [m for m in matches if m.tour == tour and m.state in ("pre", "in")]
            for event in self._events(key, now, errors):
                start = board.parse_utc(event.get("commence_time"))
                if start is None or abs((now - start).total_seconds()) > PAIR_WINDOW_HOURS * 3600:
                    continue
                found = afr.match_tennis({"event_id": event["id"], "home_team": event.get("home_team"),
                                          "away_team": event.get("away_team"), "_start": start},
                                         candidates, window_hours=PAIR_WINDOW_HOURS)
                match = found.get("match")
                if match is None:
                    if start <= now:
                        unmatched_live.append(event["id"])
                    continue
                st = state_mod.live_state(match, config.sets_to_win(key))
                who = server_by_match.get(f"{match.tour}:{match.match_id}")
                server = None
                if who in ("a", "b"):
                    pair = state_mod.orient((who, "-"), found["orientation"])
                    server = "home" if pair[0] == who else "away"
                tracked.append(Tracked(key, dict(event), match, found["orientation"], st, server))
        return tracked

    # ---- p0 cache -------------------------------------------------------

    def _load_p0(self, now: datetime) -> None:
        if self._p0_loaded:
            return
        for row in self.snapshots.recent(now - timedelta(hours=P0_LOOKBACK_HOURS)):
            self._note_p0(row)
        self._p0_loaded = True

    def _note_p0(self, snap: Mapping) -> None:
        for event_id, item in (snap.get("events") or {}).items():
            if item.get("prematch_p0"):
                self._p0[event_id] = {**item["prematch_p0"], "snapshot_id": snap["snapshot_id"], "t_resp": snap["t_resp"]}

    # ---- decision-point bookkeeping ------------------------------------------

    def _arm(self, t: Tracked, now: datetime, report: dict) -> None:
        st = t.state
        dp = decision_mod.dp_id(t.event_id, st.set_number)
        home_sets, away_sets = state_mod.orient(st.sets_won, t.orientation)
        base = {
            "dp_id": dp, "event_id": t.event_id, "sport_key": t.key, "tour": config.tour_of(t.key),
            "espn_tour": t.match.tour, "espn_match_id": t.match.match_id, "espn_event_id": t.match.espn_event_id,
            "orientation": t.orientation, "home": t.home, "away": t.away, "set_number": st.set_number,
            "sets_won_home": home_sets, "sets_won_away": away_sets,
            "t_c": board.iso_utc(now), "commence_time": t.event.get("commence_time"),
            "espn_start_utc": t.match.start_utc, "server_hint": t.server,
            "t_prev_poll": board.iso_utc(self._prev_poll_for_arm) if self._prev_poll_for_arm else None,
        }
        p0 = self._p0.get(t.event_id)
        model = None
        reason = None
        if st.contradiction:
            reason = "FORMAT_CONTRADICTION"
        elif p0 is None:
            reason = "NO_PREMATCH_PRICE"
        else:
            model = decision_mod.model_for(p0["p0_home"], t.key, home_sets, away_sets)
            if model is None:
                reason = "MODEL_OUT_OF_RANGE"
        base["p0"] = p0
        base["model"] = model
        self.ledger.append("armed", base, now=now)
        report["armed"] += 1
        if reason is not None:
            self._write_decision(base, now=now, status=decision_mod.EXCLUDED, reason=reason, report=report)

    def _write_decision(self, armed: Mapping, *, now: datetime, status: str, reason: Optional[str], report: dict,
                        snapshot: Optional[Mapping] = None, attempt_no: Optional[int] = None,
                        evaluation: Optional[Mapping] = None, fresh: Optional[List[dict]] = None,
                        stale_count: Optional[int] = None, detail: Optional[Mapping] = None,
                        all_quotes: Optional[List[dict]] = None, permissive: Optional[Mapping] = None) -> dict:
        stats = (evaluation or {}).get("stats")
        side = (evaluation or {}).get("side")
        entry = None
        if stats is not None and side is not None:
            entry = {"side": side, **board.side_view(stats, side)}
        row = {
            "dp_id": armed["dp_id"], "event_id": armed["event_id"], "sport_key": armed["sport_key"],
            "tour": armed["tour"], "home": armed["home"], "away": armed["away"], "set_number": armed["set_number"],
            "sets_won_home": armed["sets_won_home"], "sets_won_away": armed["sets_won_away"],
            "t_c": armed["t_c"], "t_decision": snapshot["t_resp"] if snapshot else board.iso_utc(now),
            "snapshot_id": snapshot["snapshot_id"] if snapshot else None, "attempt_no": attempt_no,
            "status": status, "reason": reason, "side": side if status in (decision_mod.BET, decision_mod.NO_BET) else None,
            "gap_pp_home": (evaluation or {}).get("gap_pp_home"), "gap_pp_away": (evaluation or {}).get("gap_pp_away"),
            "model": armed.get("model"), "p0": armed.get("p0"),
            "board": stats, "n_fresh": (evaluation or {}).get("n_fresh"), "n_stale": stale_count,
            "fresh_quotes": fresh, "all_quotes": all_quotes,
            "entry": entry if status in (decision_mod.BET, decision_mod.NO_BET) else None,
            "permissive": dict(permissive) if permissive else None,
            "shadow_bet": bool(permissive and permissive.get("status") == decision_mod.BET
                               and status != decision_mod.BET),
            "detail": dict(detail) if detail else None,
        }
        written = self.ledger.append("decision", row, now=now)
        report["decisions"] += 1
        return written

    def _attempts(self, dp: str) -> List[dict]:
        return [r for r in self.ledger.of_kind("attempt") if r.get("dp_id") == dp]

    def _open_dps(self) -> List[dict]:
        decided = set(self.ledger.by_dp("decision"))
        return [a for a in self.ledger.of_kind("armed") if a["dp_id"] not in decided]

    # ---- buying a board ---------------------------------------------------

    def _buy(self, key: str, purpose: str, tracked: List[Tracked], now: datetime, tick: dict,
             report: dict) -> Optional[dict]:
        if tick.get("remaining") is None and not tick.get("quota_failed"):
            try:
                tick["remaining"] = self.seams.quota().get("remaining")
            except Exception as exc:  # noqa: BLE001 -- an unreadable balance fails closed below
                tick["quota_failed"] = True
                report["errors"].append(f"quota: {type(exc).__name__}")
        verdict = guard.can_spend(1, purpose=purpose, now=now, env=self.env, remaining=tick.get("remaining"),
                                  stores=self.credit_stores)
        if not verdict.allowed:
            report["refused"].append({"key": key, "purpose": purpose, "reason": verdict.reason})
            return None
        in_key = [t for t in tracked if t.key == key]
        before = {t.event_id: _espn_item(t) for t in in_key}
        t_req = self.seams.clock()
        try:
            events, usage = self.seams.fetch_odds(key)
        except Exception as exc:  # noqa: BLE001 -- nothing was billed that we know of; the attempt is not consumed
            report["errors"].append(f"odds {key}: {type(exc).__name__}")
            return None
        t_resp = self.seams.clock()
        billed = guard.log_call(purpose=purpose, usage=usage, now=t_resp, store=None if self.credit_stores is None
                                else self.credit_stores[0], record=self.credit_record)
        if isinstance(usage, Mapping) and usage.get("remaining") is not None:
            tick["remaining"] = usage["remaining"]
        elif tick.get("remaining") is not None:
            tick["remaining"] = tick["remaining"] - billed
        report["calls"].append({"key": key, "purpose": purpose, "credits": billed})
        # the second score read that closes the bracket
        errors: List[str] = []
        after_matches, _, ok = self._read_espn(t_resp, errors)
        after_state = {}
        if ok:
            for t in in_key:
                m = next((x for x in after_matches if x.tour == t.match.tour and x.match_id == t.match.match_id), None)
                after_state[t.event_id] = state_mod.to_dict(state_mod.live_state(m, config.sets_to_win(key))) if m else None
        else:
            report["errors"].extend(errors)
        raw_by_id = {e.get("id"): e for e in events if isinstance(e, Mapping)}
        items = {}
        for t in in_key:
            raw = raw_by_id.get(t.event_id)
            quotes = board.parse_quotes(raw) if raw else []
            item = {"quotes": quotes, "home": t.home, "away": t.away, "commence_time": t.event.get("commence_time"),
                    "espn_before": before[t.event_id], "espn_after": after_state.get(t.event_id),
                    "espn_match": f"{t.match.tour}:{t.match.match_id}", "prematch_p0": None}
            b, a = item["espn_before"], item["espn_after"]
            if b and a and b.get("state") == "pre" and a.get("state") == "pre":
                item["prematch_p0"] = decision_mod.prematch_p0(quotes)
            items[t.event_id] = item
        snap = {"snapshot_id": f"{key}@{board.iso_utc(t_resp)}", "key": key, "purpose": purpose,
                "t_req": board.iso_utc(t_req), "t_resp": board.iso_utc(t_resp), "credits": billed,
                "usage": dict(usage) if isinstance(usage, Mapping) else None, "events": items}
        self.snapshots.append(snap)
        self._note_p0(snap)
        return snap

    # ---- deciding ---------------------------------------------------------

    def _bracket_ok(self, armed: Mapping, item: Mapping) -> bool:
        before = state_mod.from_dict(item.get("espn_before"))
        after = state_mod.from_dict(item.get("espn_after"))
        if not state_mod.same_set_start(before, after):
            return False
        home, away = state_mod.orient(before.sets_won, armed["orientation"])
        return (home == armed["sets_won_home"] and away == armed["sets_won_away"]
                and before.set_number == armed["set_number"])

    def _decide_from_snapshot(self, armed: dict, snap: dict, now: datetime, report: dict) -> None:
        item = (snap.get("events") or {}).get(armed["event_id"])
        attempts = self._attempts(armed["dp_id"])
        attempt_no = len(attempts) + 1
        if item is None or not self._bracket_ok(armed, item):
            why = ("the match was not on the scoreboard for this snapshot" if item is None
                   else "both score reads must show the same set start")
            self._write_decision(armed, now=now, status=decision_mod.EXCLUDED, reason="SCORE_MOVED", report=report,
                                 snapshot=snap, attempt_no=attempt_no, detail={"bracket": why})
            return
        t_c = board.parse_utc(armed["t_c"])
        quotes = item.get("quotes") or []
        fresh, stale = board.split_fresh(quotes, t_c)
        evaluation = decision_mod.evaluate(armed["model"]["p_match_home"], fresh)
        permissive = self._permissive(armed, quotes, fresh)
        if evaluation["reason"] == "THIN_BOARD":
            window_over = (board.parse_utc(snap["t_resp"]) - t_c).total_seconds() >= config.DP_WINDOW_SECONDS
            if attempt_no >= config.MAX_DECISION_ATTEMPTS or window_over:
                self._write_decision(armed, now=now, status=decision_mod.EXCLUDED, reason="THIN_BOARD", report=report,
                                     snapshot=snap, attempt_no=attempt_no, evaluation=evaluation, fresh=fresh,
                                     stale_count=len(stale), all_quotes=quotes, permissive=permissive)
            else:
                self.ledger.append("attempt", {"dp_id": armed["dp_id"], "attempt_no": attempt_no,
                                               "snapshot_id": snap["snapshot_id"], "result": "THIN_BOARD",
                                               "n_fresh": len(fresh), "n_stale": len(stale)}, now=now)
            return
        self._write_decision(armed, now=now, status=evaluation["status"], reason=evaluation["reason"], report=report,
                             snapshot=snap, attempt_no=attempt_no, evaluation=evaluation, fresh=fresh,
                             stale_count=len(stale), all_quotes=quotes, permissive=permissive)

    def _permissive(self, armed: Mapping, quotes: List[dict], strict_fresh: List[dict]) -> Optional[dict]:
        """The same decision with freshness relaxed to `last_update >= the last poll that still showed the set in
        progress` (docs/PREREG_LIVE_TENNIS.md section 7, descriptive only, labelled permissive). None when that poll
        time is unknown. It never changes the real decision; it lets the report show how much of any apparent result
        is stale-quote contamination, by recomputing the entry on a board that admits them."""
        prev = board.parse_utc(armed.get("t_prev_poll"))
        if prev is None:
            return None
        loose, _ = board.split_fresh(quotes, prev)
        result = decision_mod.evaluate(armed["model"]["p_match_home"], loose)
        side = result.get("side")
        return {"n_fresh": result["n_fresh"], "status": result["status"], "reason": result["reason"], "side": side,
                "gap_pp_home": result["gap_pp_home"], "gap_pp_away": result["gap_pp_away"], "board": result["stats"],
                "entry": ({"side": side, **board.side_view(result["stats"], side)}
                          if result["stats"] is not None and side is not None else None)}

    # ---- the tick ---------------------------------------------------------

    def tick(self) -> dict:
        now = self.seams.clock()
        report = {"utc": board.iso_utc(now), "off": False, "stopped": False, "errors": [], "calls": [], "refused": [],
                  "armed": 0, "decisions": 0, "references": 0, "no_reference": 0, "outcomes": 0, "busy": False,
                  "paired": 0, "unmatched_live": [], "espn_ok": False}
        if not config.switch_on(self.env):
            report["off"] = True
            return report                                   # no request, no credit, no file written
        problem = self.ledger.fingerprint_problem()
        if problem:
            report["errors"].append(problem)
            report["stopped"] = True
            return report
        self.ledger.ensure_genesis(now=now, prereg_sha256=prereg_sha256(self.prereg_root))
        if now.astimezone(timezone.utc).date() > date.fromisoformat(config.STOP_DATE):
            report["stopped"] = True
            report["errors"].append(f"past the stop date {config.STOP_DATE}: capture is finished")
            self._heartbeat(report)
            return report
        self._load_p0(now)

        keys = self._active_keys(now, report["errors"])
        matches, server_by_match, ok = self._read_espn(now, report["errors"])
        report["espn_ok"] = ok
        if not ok:
            self._heartbeat(report)
            return report
        t_poll = self.seams.clock()
        self._prev_poll_for_arm = self._last_ok_poll
        tracked = self._pair(keys, matches, server_by_match, now, report["errors"], report["unmatched_live"])
        report["paired"] = len(tracked)
        by_event = {t.event_id: t for t in tracked}

        # 4. arm
        armed_ids = set(self.ledger.by_dp("armed"))
        for t in tracked:
            st = t.state
            candidate = st.in_progress and not st.decided and st.set_number >= config.MIN_DECISION_SET
            if not candidate:
                continue
            if not (state_mod.is_set_start(st, config.MIN_DECISION_SET) or st.contradiction):
                continue
            dp = decision_mod.dp_id(t.event_id, st.set_number)
            if dp in armed_ids:
                continue
            armed_ids.add(dp)
            self._arm(t, t_poll, report)

        self._last_ok_poll = t_poll

        # 5. close what cannot continue
        needs_decision: Dict[str, List[dict]] = {}
        for armed in self._open_dps():
            t_c = board.parse_utc(armed["t_c"])
            current = by_event.get(armed["event_id"])
            if (now - t_c).total_seconds() > config.DP_WINDOW_SECONDS:
                self._write_decision(armed, now=now, status=decision_mod.EXCLUDED, reason="WINDOW_EXPIRED", report=report,
                                     detail={"attempts": len(self._attempts(armed["dp_id"]))})
                continue
            if current is not None and not state_mod.is_set_start(current.state, config.MIN_DECISION_SET):
                self._write_decision(armed, now=now, status=decision_mod.EXCLUDED, reason="SCORE_MOVED", report=report,
                                     detail={"seen": "the score is no longer at the set start"})
                continue
            if current is not None:
                home, away = state_mod.orient(current.state.sets_won, current.orientation)
                if (home, away, current.state.set_number) != (armed["sets_won_home"], armed["sets_won_away"],
                                                              armed["set_number"]):
                    self._write_decision(armed, now=now, status=decision_mod.EXCLUDED, reason="SCORE_MOVED",
                                         report=report, detail={"seen": "the set count changed"})
                    continue
            attempts = self._attempts(armed["dp_id"])
            if len(attempts) >= config.MAX_DECISION_ATTEMPTS:
                continue
            if attempts:
                last = board.parse_utc(attempts[-1]["recorded_utc"])
                if (now - last).total_seconds() < config.ATTEMPT_SPACING_SECONDS:
                    continue
            needs_decision.setdefault(armed["sport_key"], []).append(armed)

        # references
        ref_state = grade.resolve_references(self.ledger, self.snapshots, now)
        needs_ref: Dict[str, bool] = {}
        for pend in ref_state["pending"]:
            if pend.get("shadow") or board.parse_utc(pend["dedicated_after_utc"]) > now:
                continue
            live = by_event.get(pend["event_id"])
            # a credit is spent on a reference only while the match is on the scoreboard and in progress: a board bought
            # for a match that ended or was suspended could not be a valid reference, so it would be wasted
            if live is not None and live.state.in_progress:
                needs_ref[pend["sport_key"]] = True

        # pre-match
        needs_pre: Dict[str, bool] = {}
        for t in tracked:
            if t.match.state != "pre":
                continue
            start = board.parse_utc(t.match.start_utc) or board.parse_utc(t.event.get("commence_time"))
            if start is None:
                continue
            until = (start - now).total_seconds()
            if until > config.PREMATCH_LEAD_MINUTES * 60 or until < -3 * 3600:
                continue
            known = self._p0.get(t.event_id)
            if known is None or (now - board.parse_utc(known["t_resp"])).total_seconds() >= config.PREMATCH_REFRESH_MINUTES * 60:
                needs_pre[t.key] = True

        # 6/7. buy, then decide
        order: List[Tuple[str, str]] = [(k, "decision") for k in sorted(needs_decision)]
        order += [(k, "reference") for k in sorted(needs_ref) if k not in needs_decision]
        order += [(k, "prematch") for k in sorted(needs_pre) if k not in needs_decision and k not in needs_ref]
        ctx: dict = {}
        for key, purpose in order[:MAX_CALLS_PER_TICK]:
            snap = self._buy(key, purpose, tracked, now, ctx, report)
            if snap is None:
                if purpose == "decision" and report["refused"] and report["refused"][-1]["key"] == key:
                    for armed in needs_decision.get(key, []):
                        self._write_decision(armed, now=now, status=decision_mod.EXCLUDED, reason="CREDIT_REFUSED",
                                             report=report, detail={"guard": report["refused"][-1]["reason"]})
                continue
            for armed in needs_decision.get(key, []):
                self._decide_from_snapshot(armed, snap, now, report)

        ref_after = grade.resolve_references(self.ledger, self.snapshots, now)
        report["references"] = ref_state["references"] + ref_after["references"]
        report["no_reference"] = ref_state["no_reference"] + ref_after["no_reference"]
        report["busy"] = bool(self._open_dps() or ref_after["pending"]
                              or any(t.state.in_progress or t.match.state == "pre" and self._near(t, now) for t in tracked))
        self._heartbeat(report)
        return report

    @staticmethod
    def _near(t: Tracked, now: datetime) -> bool:
        start = board.parse_utc(t.match.start_utc) or board.parse_utc(t.event.get("commence_time"))
        return start is not None and (start - now).total_seconds() <= config.PREMATCH_LEAD_MINUTES * 60

    def _heartbeat(self, report: Mapping) -> None:
        row = {"utc": report["utc"], "espn_ok": report["espn_ok"], "paired": report["paired"],
               "armed": report["armed"], "decisions": report["decisions"], "references": report["references"],
               "calls": report["calls"], "refused": report["refused"], "errors": report["errors"],
               "unmatched_live": sorted(set(report["unmatched_live"])), "busy": report["busy"],
               "stopped": report["stopped"]}
        try:
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            with self.heartbeat_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        except OSError as exc:  # noqa: BLE001 -- a heartbeat failure never stops a capture
            LOG.warning("live tennis heartbeat not written: %s", exc)

    # ---- the loop -----------------------------------------------------------

    def run_loop(self, *, max_minutes: Optional[float] = None, on_tick: Optional[Callable[[dict], None]] = None) -> int:
        """Tick until `max_minutes` pass or the stop date. Sleeps POLL_INTERVAL_SECONDS while anything is live or
        due, IDLE_POLL_INTERVAL_SECONDS otherwise. A tick that raises is logged and the loop carries on."""
        started = self.seams.clock()
        ticks = 0
        while True:
            now = self.seams.clock()
            if max_minutes is not None and (now - started).total_seconds() >= max_minutes * 60:
                break
            try:
                report = self.tick()
            except Exception as exc:  # noqa: BLE001 -- the loop must outlive any one bad tick
                LOG.exception("live tennis tick failed")
                report = {"busy": True, "off": False, "stopped": False, "errors": [f"{type(exc).__name__}: {str(exc)[:120]}"]}
            ticks += 1
            if on_tick is not None:
                on_tick(report)
            if report.get("off") or report.get("stopped"):
                break
            self.seams.sleep(config.POLL_INTERVAL_SECONDS if report.get("busy") else config.IDLE_POLL_INTERVAL_SECONDS)
        return ticks
