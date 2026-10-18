"""Read side of the AI desk: which games a desk hound argued, and the transcript and disagreement table of one.

WHAT IS READ, AND WHAT IS NOT
-----------------------------
``evidence/hounds_desk_v1.jsonl`` (the desk's hash-chained ledger) holds one ``desk_game`` row per publish
call for a game: the hounds published, the packet hash, and the PATHS of that game's transcript and
disagreement table (relative to ``evidence/hounds_desk/``) with the transcript's sha256. This module lists
those rows for a hound and reads the two files they name. It writes nothing, calls nothing, and is tolerant of
every part being absent: before the first publish there is no ledger and no folder, and the answer is an
honest ``started: false``, not an error.

THE FILE NAMES COME FROM THE LEDGER, NEVER FROM THE REQUEST
-----------------------------------------------------------
A request names a hound and a game id. The files read are the ones the ``desk_game`` row for that game names,
and only if they resolve inside the desk's evidence folder. A game id that is not in the ledger is not a path:
``../../anything`` finds no row and reads no file.

THE TRANSCRIPT'S HASH
---------------------
The row carries the sha256 of the transcript's bytes at publish time. The reader compares it to the file it
read and says so (``transcript_sha256_ok``); a mismatch is reported, not hidden, and the content is still
returned because the page labels it. The disagreement table has no hash of its own and is shown as it is.

Paper only. Nothing here is advice.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from src.hounds import NOT_ADVICE, PAPER_ONLY
from src.hounds.ledgers import jsonl_rows
from src.paths import evidence_path, repo_root

LEDGER_NAME = "hounds_desk_v1.jsonl"
FOLDER_NAME = "hounds_desk"
CONFIG_NAME = "desk_hounds.json"
KIND_GAME = "desk_game"

MAX_GAMES = 60                      # newest games listed for one hound
MAX_FILE_BYTES = 4 * 1024 * 1024    # a transcript larger than this is reported, not served

CAN_NOT_READ = "could not be read"


def _ledger(path: Optional[Path]) -> Path:
    return Path(path) if path else evidence_path(LEDGER_NAME)


def _folder(folder: Optional[Path]) -> Path:
    return Path(folder) if folder else evidence_path(FOLDER_NAME)


def desk_hound_ids(config: Optional[Path] = None) -> list:
    """The ids in config/desk_hounds.json, or [] when the file is absent or unreadable."""
    target = Path(config) if config else repo_root() / "config" / CONFIG_NAME
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(h["id"]) for h in (data.get("hounds") or []) if isinstance(h, dict) and h.get("id")]


def _game_rows(ledger: Optional[Path]) -> list:
    return [r for r in jsonl_rows(_ledger(ledger)) if r.get("kind") == KIND_GAME and r.get("game_id")]


def games_for(hound_id: str, *, ledger: Optional[Path] = None) -> dict:
    """``{hound_id, started, games: [...]}``: the games this hound was published for, newest first.

    ``started`` is true once the hound has any published game. Each game says how many TAKEs this hound took
    and whether its decision was readable (a hound whose answer could not be read passed the game)."""
    rows = [r for r in _game_rows(ledger) if hound_id in (r.get("hounds") or {})]
    rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("start_utc") or ""),
                             str(r.get("published_utc") or "")), reverse=True)
    games = []
    for r in rows[:MAX_GAMES]:
        mine = (r.get("hounds") or {}).get(hound_id) or {}
        games.append({
            "game_id": r["game_id"], "date": r.get("date"), "sport": r.get("sport"),
            "away": r.get("away"), "home": r.get("home"), "start_utc": r.get("start_utc"),
            "published_utc": r.get("published_utc"), "takes": mine.get("takes"),
            "attempts": mine.get("attempts"), "decision_readable": mine.get("decision_readable"),
            "has_disagreement": bool(r.get("disagreement")),
            "disagreement_counts": r.get("disagreement_counts")})
    return {"hound_id": hound_id, "started": bool(rows), "games": games,
            "paper_only": PAPER_ONLY, "not_advice": NOT_ADVICE}


def _read_json(folder: Path, relative: Optional[str]):
    """``(parsed | None, sha256 | None, problem | None)`` for a file the ledger named, inside ``folder``."""
    if not relative:
        return None, None, "the ledger names no file"
    base = folder.resolve()
    try:
        target = (base / relative).resolve()
        target.relative_to(base)
    except (OSError, ValueError):
        return None, None, "the named file is outside the desk's evidence folder"
    try:
        size = target.stat().st_size
    except OSError:
        return None, None, "the named file is not there"
    if size > MAX_FILE_BYTES:
        return None, None, f"the named file is {size} bytes, more than the {MAX_FILE_BYTES} this page serves"
    raw = target.read_bytes()
    try:
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest(), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, hashlib.sha256(raw).hexdigest(), f"the named file {CAN_NOT_READ}"


def game_payload(hound_id: str, game_id: str, *, ledger: Optional[Path] = None,
                 folder: Optional[Path] = None) -> Optional[dict]:
    """One game's transcript and disagreement table, or None when no ``desk_game`` row of this hound has that
    game id. Missing or unreadable files are named problems on a payload that still answers."""
    rows = [r for r in _game_rows(ledger)
            if r["game_id"] == game_id and hound_id in (r.get("hounds") or {})]
    if not rows:
        return None
    row = rows[-1]                                  # a later batch of the same game supersedes the first
    base = _folder(folder)
    transcript, sha, t_problem = _read_json(base, row.get("transcript"))
    table, _sha, d_problem = _read_json(base, row.get("disagreement"))
    expected = row.get("transcript_sha256")
    return {
        "hound_id": hound_id, "game_id": game_id, "date": row.get("date"), "away": row.get("away"),
        "home": row.get("home"), "start_utc": row.get("start_utc"), "published_utc": row.get("published_utc"),
        "transcript": transcript, "transcript_problem": t_problem,
        "transcript_sha256_ok": (sha == expected) if (sha and expected) else None,
        "disagreement": table, "disagreement_problem": d_problem,
        "paper_only": PAPER_ONLY, "not_advice": NOT_ADVICE}
