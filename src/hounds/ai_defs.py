"""What the AI hounds ARE, read from ``config/ai_hounds.json``; and the one sentence that says why they cannot be replayed.

Kept apart from the runner and the hound classes on purpose: the dog-page code (``interact/common.py``,
``interact/drill.py``) has to recognise an AI hound's id and refuse a backtest with a clear message, and it
must be able to do that with nothing heavier than a JSON file read (no router, no stores, no SDK).

FORWARD ONLY, AND WHY. A language model has read about games that were already played. Replaying one over
old boards would measure its memory, not its judgment, and the page would show a record that means nothing.
So an AI hound is only ever asked about a game that has not started, at that game's lock, and every code
path that replays a rule over past boards (the runner's ``--replay``, the dog page's Backtest, Ask's
"earlier today") refuses an AI hound with ``FORWARD_ONLY_MESSAGE``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

PACK_ID = "ai_v1"
CONFIG_NAME = "ai_hounds.json"
LEDGER_NAME = "ai_hounds_v1.jsonl"
DECISIONS_NAME = "ai_decisions_v1.jsonl"
CATEGORY = "ai"

FORWARD_ONLY_MESSAGE = (
    "AI hounds are forward-only. A language model has already read about games that were played, so replaying "
    "one over old boards would test its memory, not its judgment. There is no backtest or drill for an AI "
    "hound; its record is built only from games it was asked about before they started."
)


class ForwardOnlyError(RuntimeError):
    """An AI hound was asked to replay the past."""

    def __init__(self, message: str = FORWARD_ONLY_MESSAGE):
        super().__init__(message)


def config_path() -> Path:
    from src import paths

    return Path(paths.repo_root()) / "config" / CONFIG_NAME


def load_config(path: Optional[Path] = None) -> dict:
    target = Path(path) if path else config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def entries(path: Optional[Path] = None, *, include_parked: bool = False) -> List[dict]:
    """The hound entries in file order. An entry with ``"enabled": false`` is parked (written, not running,
    not listed anywhere) unless ``include_parked``."""
    out = []
    for entry in load_config(path).get("hounds") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        if entry.get("enabled") is False and not include_parked:
            continue
        out.append(entry)
    return out


def ids(path: Optional[Path] = None, *, include_parked: bool = True) -> frozenset:
    return frozenset(str(e["id"]) for e in entries(path, include_parked=include_parked))


def is_ai_hound(hound_id: object, path: Optional[Path] = None) -> bool:
    return isinstance(hound_id, str) and hound_id in ids(path)


def entry_for(hound_id: str, path: Optional[Path] = None) -> Optional[dict]:
    for e in entries(path, include_parked=True):
        if e["id"] == hound_id:
            return e
    return None


def ledger_path(path: Optional[str] = None) -> str:
    """The AI bets' hash-chained ledger: an explicit path, else ``AI_HOUNDS_LEDGER``, else a file BESIDE THE
    APP DATABASE (the Fly volume in production), for the reason ``user_engine.ledger_path`` gives: the engine
    that writes it runs in the API process, and ``evidence/`` is baked into the image."""
    import os

    if path:
        return path
    override = (os.environ.get("AI_HOUNDS_LEDGER") or "").strip()
    if override:
        return override
    from src.appstate import users as users_store

    return str(users_store.db_path().parent / LEDGER_NAME)


def decisions_path(path: Optional[str] = None) -> str:
    """The decision log (every answer, bet or pass, and every failure) sits beside the bets ledger."""
    import os

    if path:
        return path
    override = (os.environ.get("AI_HOUNDS_DECISIONS") or "").strip()
    if override:
        return override
    return str(Path(ledger_path()).parent / DECISIONS_NAME)
