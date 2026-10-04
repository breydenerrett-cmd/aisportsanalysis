"""The analyst's record: append-only, hash-chained, separate from the cards.

THE PATTERN, COPIED AND NOT SHARED
----------------------------------
`src/appstate/card_ledger.py` is fingerprinted: editing it restarts the counted
sample of the card record. So this module copies its PATTERN (frozen before
first pitch, graded by a separate row, corrections append and never rewrite)
and none of its code. It builds on `src.ledger.chain.HashChainLedger`, the
primitive every ledger here uses: each row's hash covers its payload and the
previous row's hash, so editing or deleting any row breaks every hash after it
and `verify` names the first break.

The analyst's file is `evidence/analyst_v1.jsonl`. It is never merged into the
card record: different file, different rows, different record page section.

THREE KINDS OF ROW
------------------
`analyst_published`  the calls, written before first pitch. Refused for a game
                     that has started, whose first pitch is unknown, or whose
                     state is not "pending". Carries the packet's hash and the
                     path of the frozen packet file, the model and prompt
                     identity, the published calls (with each call's grading
                     spec), every call the critic struck (the audit trail) and
                     the run's cost.
`analyst_graded`     the results of one published row, from the same results
                     the cards use. A later graded row for the same published
                     row replaces an earlier one only when it adds a result.
`analyst_correction` fixes one call's grade. The corrected result is what the
                     record shows; the row it corrects is untouched.

A game can be published again (`refresh`) while it has not started and has not
been graded; every version stays in the file, and only the NEWEST version of a
game counts in the record. Without `refresh` a published game is frozen: the
second `publish` returns the first row.

WHY THE PACKET IS A FILE, NOT A ROW
-----------------------------------
A packet is tens of kilobytes. Fifteen games a day in one JSONL would make
every ledger read pay for them. The packet is written once as gzip under
`evidence/analyst_packets_v1/<date>/`, named by its hash, and the row carries
the hash, so `verify` can prove the file is the packet the calls were made from.

THE RECORD'S SMALL-SAMPLE RULE
------------------------------
Counts are always shown. A win rate or a return is withheld for a family until
it has `min_graded` graded calls (30), because a rate on twelve calls is a
story, not a measurement.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from src import paths
from src.analyst import LABEL
from src.analyst import analyst as analyst_mod
from src.analyst import grading, packet as packet_mod
from src.ledger.chain import HashChainLedger, canonical_bytes

STORE = os.path.join("evidence", "analyst_v1.jsonl")
USAGE_STORE = os.path.join("evidence", "analyst_usage_v1.jsonl")
PACKET_DIR = os.path.join("evidence", "analyst_packets_v1")

KIND_PUBLISHED = "analyst_published"
KIND_GRADED = "analyst_graded"
KIND_CORRECTION = "analyst_correction"
KIND_USAGE = "analyst_usage"

# Only a game still "pending" can be published. Anything else (live, final,
# postponed, cancelled) has information the packet cannot exclude.
PUBLISHABLE_STATES = ("pending",)

CORRECTABLE = ("result", "profit_units", "reason")


class AnalystLedgerError(RuntimeError):
    pass


class GameStarted(AnalystLedgerError):
    """Refused: the game has started, or cannot be shown not to have."""


def _path(path: Optional[str], default: str) -> str:
    return path or str(paths.repo_root() / default)


def _ledger(path: Optional[str] = None) -> HashChainLedger:
    return HashChainLedger(_path(path, STORE))


def _utc(value: Any) -> Optional[datetime]:
    return packet_mod._parse_utc(value)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def prompt_hash(system_prompt: Optional[str] = None) -> str:
    """sha256 of the prompt and the schema a row was made with. Arm B passes its own prompt
    (`analyst.SITUATION_SYSTEM_PROMPT`); the default is arm A's. The schema is the MLB one (prompt
    v2 added `case_against`); the UFC analyst hashes the shared schema in `ufc_analyst.prompt_hash`."""
    return hashlib.sha256(((system_prompt or analyst_mod.SYSTEM_PROMPT) + "\n" + json.dumps(
        analyst_mod.MLB_RESPONSE_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def rows(path: Optional[str] = None) -> list:
    return _ledger(path).read()


def latest_published(all_rows: Sequence[Mapping]) -> dict:
    """{game_id: newest published row}. Later rows win: the file is ordered."""
    out: dict = {}
    for row in all_rows:
        if row.get("kind") == KIND_PUBLISHED:
            out[row["game_id"]] = row
    return out


def _published_versions(all_rows, game_id) -> list:
    return [r for r in all_rows if r.get("kind") == KIND_PUBLISHED and r.get("game_id") == game_id]


def latest_graded(all_rows: Sequence[Mapping]) -> dict:
    """{published row_hash: newest graded row for it}."""
    out: dict = {}
    for row in all_rows:
        if row.get("kind") == KIND_GRADED:
            out[row["published_row_hash"]] = row
    return out


def corrections_for(all_rows: Sequence[Mapping]) -> dict:
    """{(graded row_hash, slot_id): newest correction}."""
    out: dict = {}
    for row in all_rows:
        if row.get("kind") == KIND_CORRECTION:
            out[(row["graded_row_hash"], row["slot_id"])] = row
    return out


def effective_calls(graded: Optional[Mapping], corrections: Mapping) -> dict:
    """{slot_id: graded call with corrections applied} for one graded row."""
    out: dict = {}
    if graded is None:
        return out
    for call in graded.get("calls") or []:
        fixed = dict(call)
        corr = corrections.get((graded["row_hash"], call["slot_id"]))
        if corr:
            for key in CORRECTABLE:
                if key in corr["fields"]:
                    fixed[key] = corr["fields"][key]
            fixed["corrected"] = True
        out[call["slot_id"]] = fixed
    return out


# ---------------------------------------------------------------------------
# publishing
# ---------------------------------------------------------------------------

def _write_packet(packet: Mapping, digest: str, date: str, packet_dir: Optional[str]) -> str:
    base = Path(_path(packet_dir, PACKET_DIR))
    gid = str(packet["game"]["game_id"])
    target = base / str(date) / f"{gid}_{digest[:12]}.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with open(target, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as fh:
                fh.write(canonical_bytes(packet))
    try:
        return target.relative_to(paths.repo_root()).as_posix()
    except ValueError:
        return str(target)


def read_packet(row: Mapping, *, root: Optional[Path] = None) -> dict:
    """The frozen packet a published row was made from. Raises if the file is
    missing or is not the packet whose hash the row carries."""
    ref = Path(row["packet_path"])
    target = ref if ref.is_absolute() else (root or paths.repo_root()) / ref
    with gzip.open(target, "rb") as fh:
        packet = json.loads(fh.read())
    if packet_mod.packet_hash(packet) != row["packet_hash"]:
        raise AnalystLedgerError(f"{target} is not the packet {row['packet_hash'][:12]}")
    return packet


def publish_refusal(packet: Mapping, now: datetime, lock_lead_minutes: float = 0.0) -> Optional[str]:
    """Why this game cannot be published at `now`, or None.

    The one place the "before first pitch" rule lives. `publish` raises on it
    and the CLI asks it BEFORE calling the model, so a game that cannot be
    published is never paid for.
    """
    game = packet["game"]
    first = _utc(game.get("first_pitch_utc"))
    if first is None:
        return "first pitch is unknown, so it cannot be shown to be ahead"
    if game.get("state") not in PUBLISHABLE_STATES:
        return f"the game is {game.get('state')!r}, not pending"
    if now >= first - timedelta(minutes=float(lock_lead_minutes)):
        return (f"first pitch {_iso(first)} has passed or is inside the "
                f"{lock_lead_minutes}-minute lock; nothing can be published")
    return None


def publish(packet: Mapping, verified, *, now: datetime, model: str,
            run: Optional[Mapping] = None, path: Optional[str] = None,
            packet_dir: Optional[str] = None, lock_lead_minutes: float = 0.0,
            refresh: bool = False, prompt_version: Optional[str] = None,
            system_prompt: Optional[str] = None, extra: Optional[Mapping] = None) -> tuple:
    """Freeze one game's analysis. Returns `(row, created)`.

    Refuses (GameStarted) unless the game is provably still ahead of us: first
    pitch known and in the future by more than `lock_lead_minutes`, and the
    game's state "pending". An existing published row is returned untouched
    (`created` False) unless `refresh`, which writes a new version while the
    game is ungraded. Nothing but the ledger row and the packet file is
    written.

    `prompt_version`, `system_prompt` and `extra` are arm B's (the situation arm writes its own
    file, with its own prompt identity and an `arm` marker the comparison checks). Left alone
    they are arm A's, and the row is exactly the row it has always been.
    """
    game = packet["game"]
    gid = game["game_id"]
    why = publish_refusal(packet, now, lock_lead_minutes)
    if why:
        raise GameStarted(f"{gid}: {why}")
    existing = _published_versions(rows(path), gid)
    if existing and not refresh:
        return existing[-1], False
    if existing and any(g for g in rows(path) if g.get("kind") == KIND_GRADED
                        and g.get("published_row_hash") == existing[-1]["row_hash"]):
        raise AnalystLedgerError(f"{gid}: already graded; it cannot be published again")
    digest = packet_mod.packet_hash(packet)
    packet_path = _write_packet(packet, digest, game["date"], packet_dir)
    calls = []
    for call in verified.calls:
        entry = dict(call)
        entry["grading"] = grading.spec_for(packet["markets"][call["slot_id"]], call["selection"])
        calls.append(entry)
    payload = {
        "kind": KIND_PUBLISHED,
        "game_id": gid, "game_pk": game.get("game_pk"), "date": game["date"],
        "away": game["away"], "home": game["home"],
        "first_pitch_utc": game["first_pitch_utc"],
        "published_utc": _iso(now),
        "version": len(existing) + 1,
        "supersedes": existing[-1]["row_hash"] if existing else None,
        "packet_hash": digest, "packet_path": packet_path,
        "packet_version": packet.get("packet_version"),
        "prompt_version": prompt_version or analyst_mod.PROMPT_VERSION,
        "prompt_hash": prompt_hash(system_prompt),
        "model": model,
        "summary": verified.summary, "summary_status": verified.summary_status,
        "summary_problems": list(verified.summary_problems),
        "calls": calls,
        "struck": [{"slot_id": s["slot_id"], "problems": s["problems"], "original": s["original"]}
                   for s in verified.struck],
        "model_critic": verified.model_critic,
        "run": dict(run or {}),
    }
    if extra:
        payload.update(extra)
    return _ledger(path).append(payload), True


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------

def _progress(old: Optional[Mapping], new_calls: Sequence[Mapping]) -> bool:
    """Does `new_calls` say something the previous graded row did not?"""
    if old is None:
        return True
    prior = {c["slot_id"]: (c.get("result"), c.get("profit_units"),
                            (c.get("would_have") or {}).get("result"))
             for c in old.get("calls") or []}
    now = {c["slot_id"]: (c.get("result"), c.get("profit_units"),
                          (c.get("would_have") or {}).get("result")) for c in new_calls}
    return prior != now


def grade_date(date: str, results_by_pk: Mapping, box_rows: Sequence, *,
               now: datetime, path: Optional[str] = None) -> dict:
    """Grade every published game of `date` that can be advanced. Appends one
    graded row per game whose picture changed; returns counts and a reason for
    every game left alone. Idempotent: running it again changes nothing."""
    ledger = _ledger(path)
    all_rows = ledger.read()
    pubs = [p for p in latest_published(all_rows).values() if p["date"] == date]
    graded_by_hash = latest_graded(all_rows)
    counts = {"published": len(pubs), "graded": 0, "unchanged": 0, "complete": 0, "notes": []}
    for pub in sorted(pubs, key=lambda r: r["game_id"]):
        previous = graded_by_hash.get(pub["row_hash"])
        if previous and previous.get("complete"):
            counts["complete"] += 1
            continue
        pk = pub.get("game_pk")
        result = results_by_pk.get(pk) or results_by_pk.get(str(pk))
        body = grading.grade_game(pub, result, box_rows)
        # An all-unresolved picture is not a grade: nothing is written until
        # at least one call has a result (or a passed side has one).
        meaningful = any(c["result"] in grading.SETTLED or c.get("would_have")
                         for c in body["calls"])
        if not meaningful or not _progress(previous, body["calls"]):
            counts["unchanged"] += 1
            counts["notes"].append(f"{pub['game_id']}: no new result yet")
            continue
        ledger.append({
            "kind": KIND_GRADED, "game_id": pub["game_id"], "date": date,
            "published_row_hash": pub["row_hash"], "version": pub["version"],
            "graded_utc": _iso(now), "complete": body["complete"],
            "final": body["final"], "calls": body["calls"],
        })
        counts["graded"] += 1
        if body["complete"]:
            counts["complete"] += 1
    return counts


def correct(game_id: str, slot_id: str, fields: Mapping, reason: str, *,
            now: datetime, path: Optional[str] = None) -> dict:
    """Append a correction to one graded call. The graded row is untouched."""
    bad = set(fields) - set(CORRECTABLE)
    if bad or not fields:
        raise AnalystLedgerError(f"a correction may set only {list(CORRECTABLE)}")
    if not reason or not str(reason).strip():
        raise AnalystLedgerError("a correction needs a reason")
    all_rows = rows(path)
    pub = latest_published(all_rows).get(game_id)
    graded = latest_graded(all_rows).get(pub["row_hash"]) if pub else None
    if graded is None or slot_id not in {c["slot_id"] for c in graded["calls"]}:
        raise AnalystLedgerError(f"no graded call {slot_id!r} for {game_id!r}")
    return _ledger(path).append({
        "kind": KIND_CORRECTION, "game_id": game_id, "slot_id": slot_id,
        "graded_row_hash": graded["row_hash"], "fields": dict(fields),
        "reason": str(reason).strip(), "corrected_utc": _iso(now)})


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------

_FAMILY_TITLES = {"moneyline": "Moneyline", "run_line": "Run line", "total": "Game total",
                  "team_total": "Team total"}


def call_title(spec: Mapping) -> str:
    """What a call is about, in words a reader can use: the market's name, or
    for a prop the player and the stat ("Junior Caminero hits")."""
    family = spec.get("family")
    if family == "prop":
        stat = spec.get("stat") or ""
        word = packet_mod._STAT_WORDS.get(stat, stat.replace("_", " "))
        return f"{spec.get('player') or 'Player'} {word}".strip()
    return _FAMILY_TITLES.get(family, str(family or ""))


def _missing_list(pub: Mapping, root: Optional[Path]) -> Optional[list]:
    """What the packet said it could not use (its `missing` list), read from the frozen packet
    file the row points at. None, never a guess, when the file cannot be read: a page that said
    "nothing was missing" because a file was absent would be telling a different story."""
    try:
        packet = read_packet(pub, root=root)
    except (OSError, ValueError, KeyError, AnalystLedgerError, EOFError):
        return None
    missing = packet.get("missing")
    return list(missing) if isinstance(missing, list) else None


def game_view(date: str, away: str, home: str, *, path: Optional[str] = None,
              all_rows: Optional[Sequence[Mapping]] = None,
              root: Optional[Path] = None) -> Optional[dict]:
    """The published analysis for one game, merged with its grade, or None
    when nothing was published. Reads only the ledger and the frozen packet file the row names:
    no model call, ever.

    Also carries, for each call, its `case_against` (prompt v2 rows; None on a PASS and on a row
    written before v2), and for the game the packet's `missing` list and the `provenance` of the
    row: "session_assisted" for a supervised-session row (src/analyst/pilot.py), else "api"."""
    all_rows = rows(path) if all_rows is None else all_rows
    pubs = [p for p in latest_published(all_rows).values()
            if p["date"] == date and p["away"].upper() == away.upper()
            and p["home"].upper() == home.upper()]
    if not pubs:
        return None
    pub = sorted(pubs, key=lambda r: r["first_pitch_utc"])[0]
    graded = latest_graded(all_rows).get(pub["row_hash"])
    grades = effective_calls(graded, corrections_for(all_rows))
    calls = []
    for c in pub["calls"]:
        item = {k: c.get(k) for k in ("slot_id", "market", "selection", "verdict", "price",
                                      "book", "fair_estimate", "confidence", "reasons",
                                      "pass_price", "what_would_change_it", "verification", "case_against")}
        spec = c.get("grading") or {}
        item["family"] = spec.get("family")
        item["player"] = spec.get("player")
        item["title"] = call_title(spec)
        g = grades.get(c["slot_id"])
        if g:
            item["result"] = g.get("result")
            item["would_have"] = g.get("would_have")
        calls.append(item)
    return {
        "game_id": pub["game_id"], "date": pub["date"], "away": pub["away"], "home": pub["home"],
        "published_utc": pub["published_utc"], "first_pitch_utc": pub["first_pitch_utc"],
        "model": pub["model"], "version": pub["version"],
        "summary": pub["summary"], "summary_status": pub["summary_status"],
        "provenance": pub.get("provenance") or "api",
        "missing": _missing_list(pub, root),
        "calls": calls,
        "final": (graded or {}).get("final"),
        "graded": graded is not None,
    }


def _blank_family() -> dict:
    return {"taken": 0, "taken_other_side": 0, "passes": 0, "graded": 0, "wins": 0,
            "losses": 0, "pushes": 0, "voids": 0, "unresolved": 0, "units": 0.0,
            "passes_would_have_won": 0, "passes_would_have_lost": 0,
            "passes_would_have_pushed": 0}


def record(*, path: Optional[str] = None, min_graded: int = 30,
           all_rows: Optional[Sequence[Mapping]] = None, recent: int = 20) -> dict:
    """The public record, by market family. Pure fold over the ledger.

    A win rate and a return appear for a family only at `min_graded` graded
    calls (win, loss or push); below that they are None and
    `withheld_reason` says why. Counts always appear. Only the NEWEST version
    of each game counts, and corrections are applied.
    """
    all_rows = rows(path) if all_rows is None else all_rows
    graded_by_hash = latest_graded(all_rows)
    corrections = corrections_for(all_rows)
    families = {f: _blank_family() for f in grading.FAMILIES}
    settled_games = published_games = 0
    recent_calls: list = []
    for pub in latest_published(all_rows).values():
        published_games += 1
        graded = graded_by_hash.get(pub["row_hash"])
        results = effective_calls(graded, corrections)
        if graded and graded.get("complete"):
            settled_games += 1
        for c in pub["calls"]:
            fam = (c.get("grading") or {}).get("family")
            if fam not in families:
                continue
            f = families[fam]
            verdict = c["verdict"]
            g = results.get(c["slot_id"])
            if verdict == "PASS":
                f["passes"] += 1
                would = ((g or {}).get("would_have") or {}).get("result")
                key = {"WIN": "passes_would_have_won", "LOSS": "passes_would_have_lost",
                       "PUSH": "passes_would_have_pushed"}.get(would)
                if key:
                    f[key] += 1
                continue
            f["taken"] += 1
            if verdict == "TAKE_OTHER_SIDE":
                f["taken_other_side"] += 1
            res = (g or {}).get("result", grading.UNRESOLVED)
            if res == grading.WIN:
                f["wins"] += 1
            elif res == grading.LOSS:
                f["losses"] += 1
            elif res == grading.PUSH:
                f["pushes"] += 1
            elif res == grading.VOID:
                f["voids"] += 1
            else:
                f["unresolved"] += 1
            if res in (grading.WIN, grading.LOSS, grading.PUSH):
                f["graded"] += 1
                f["units"] += float((g or {}).get("profit_units") or 0.0)
            if res in grading.SETTLED:
                recent_calls.append({
                    "date": pub["date"], "away": pub["away"], "home": pub["home"],
                    "family": fam, "selection": c["selection"], "player": (c.get("grading") or {}).get("player"),
                    "verdict": verdict, "price": c.get("price"), "result": res,
                    "reason": (g or {}).get("reason")})
    out_fams = {}
    for name, f in families.items():
        shown = dict(f)
        decided = f["wins"] + f["losses"]
        if f["graded"] >= min_graded:
            shown["win_rate"] = round(f["wins"] / decided, 4) if decided else None
            shown["units"] = round(f["units"], 2)
            shown["withheld_reason"] = None
        else:
            shown["win_rate"] = None
            shown["units"] = None
            shown["withheld_reason"] = (f"fewer than {min_graded} graded calls "
                                        f"({f['graded']} so far)")
        out_fams[name] = shown
    recent_calls.sort(key=lambda c: (c["date"], c["family"]), reverse=True)
    return {
        "label": LABEL,
        "min_graded": min_graded,
        "games_published": published_games, "games_settled": settled_games,
        "families": out_fams, "recent": recent_calls[:recent],
    }


# ---------------------------------------------------------------------------
# integrity
# ---------------------------------------------------------------------------

def verify(path: Optional[str] = None, *, root: Optional[Path] = None) -> dict:
    """Walk the chain, then check every published row's packet file against
    its hash. `{"ok": bool, "rows": n, "problems": [...]}`."""
    result = _ledger(path).verify()
    problems = []
    if not result.ok:
        problems.append(f"chain broken at line {result.broken_at_line}: {result.reason}")
    for row in rows(path):
        if row.get("kind") != KIND_PUBLISHED:
            continue
        try:
            read_packet(row, root=root)
        except (OSError, ValueError, AnalystLedgerError, EOFError) as exc:
            problems.append(f"{row.get('game_id')}: packet file: {exc}")
    return {"ok": not problems, "rows": result.rows_checked, "problems": problems}


# ---------------------------------------------------------------------------
# cost log
# ---------------------------------------------------------------------------

def log_usage(*, date: str, game_id: str, run_id: str, outcome: str, model: str,
              usage: Mapping, cost_usd: float, attempts: int, cfg: Mapping,
              now: datetime, extra: Optional[Mapping] = None,
              path: Optional[str] = None) -> dict:
    """One row per game attempt: what it cost, from the usage the API returned.
    Tracked, hash-chained like the rest, so cost per day is a fold over it."""
    payload = {
        "kind": KIND_USAGE, "date": date, "game_id": game_id, "run_id": run_id,
        "logged_utc": _iso(now), "outcome": outcome, "model": model,
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "cost_usd": round(float(cost_usd), 4), "attempts": attempts,
        "price_per_million_usd": dict(cfg["price_per_million_usd"]),
    }
    if extra:
        payload.update(extra)
    return HashChainLedger(_path(path, USAGE_STORE)).append(payload)


def usage_by_day(path: Optional[str] = None) -> dict:
    """{date: {"games", "published", "input_tokens", "output_tokens", "cost_usd"}}"""
    out: dict = {}
    for row in HashChainLedger(_path(path, USAGE_STORE)).read():
        if row.get("kind") != KIND_USAGE:
            continue
        d = out.setdefault(row["date"], {"games": 0, "published": 0, "input_tokens": 0,
                                         "output_tokens": 0, "cost_usd": 0.0})
        d["games"] += 1
        d["published"] += 1 if row.get("outcome") == "published" else 0
        d["input_tokens"] += row.get("input_tokens", 0)
        d["output_tokens"] += row.get("output_tokens", 0)
        d["cost_usd"] = round(d["cost_usd"] + row.get("cost_usd", 0.0), 4)
    return out
