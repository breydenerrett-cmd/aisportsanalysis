"""The auto-pause: the coach kill switch that the loop itself can flip, and only the owner can undo.

TWO PLACES, ONE MEANING
-----------------------
``config/hounds_coach.json`` ``{"enabled": true}`` is the owner's kill switch (default OFF; read on
every request by ``user_coach.coach_enabled``). The loop's pause adds to it, never replaces it:

  * the scope's pause file (the user scope: ``hounds_coach_pause.json`` beside the app database, the
    one place the API process can persist a flag across a deploy) says ``{"paused": true, reason,
    since}``;
  * the house scope has no volume, so its pause rewrites ``config/hounds_coach.json`` itself to
    ``enabled: false`` with ``paused_by``, ``reason`` and ``since`` beside it (the scheduled session
    commits the file).

``coach_enabled()`` is true only when the config is on AND no pause file says paused. A pause is
cleared only by ``resume`` (the owner's CLI command), which also records a ``resume`` event; a
loop that decided it was not helping does not get to decide it is helping again.

Everything is written best effort per place and the EVENT is always written, so a pause that could
not reach a file is still in the chain and on the dashboard.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.hounds.learning import ledger as L
from src.hounds.learning import rules

CONFIG_ENV = "HOUNDS_COACH_CONFIG"
CONFIG_RELATIVE = os.path.join("config", "hounds_coach.json")


def config_path() -> Path:
    override = (os.environ.get(CONFIG_ENV) or "").strip()
    if override:
        return Path(override)
    from src import paths
    return Path(paths.repo_root()) / CONFIG_RELATIVE


def _read_json(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def file_paused(pause_file: Optional[Path]) -> bool:
    """True when ``pause_file`` exists and says ``paused: true``. An unreadable file is NOT a pause
    (a corrupt flag must not silently take the door down; the chain event is the record)."""
    if pause_file is None:
        return False
    return _read_json(pause_file).get("paused") is True


def user_paused() -> bool:
    """Is the user scope paused? Cheap: one small file read."""
    try:
        return file_paused(L.Scope.user().pause_file)
    except Exception:  # noqa: BLE001 -- never let the flag lookup break the door
        return False


def config_pause_reason() -> Optional[dict]:
    data = _read_json(config_path())
    if data.get("enabled") is False and data.get("paused_by") == "learning_loop":
        return {"reason": data.get("reason"), "since": data.get("since")}
    return None


def is_paused(scope: L.Scope) -> bool:
    """Paused by the loop, in this scope: the pause file, the config's mark, or the last chain event."""
    if file_paused(scope.pause_file):
        return True
    if scope.name == rules.SCOPE_HOUSE and config_pause_reason() is not None:
        return True
    return L.read_state(scope).paused()


def pause(scope: L.Scope, reason: str, *, now: Optional[datetime] = None,
          config_file: Optional[Path] = None) -> dict:
    """Pause the scope's loop. Idempotent: pausing a paused loop writes nothing new."""
    when = now or L.utc_now()
    if L.read_state(scope).paused():
        return {"paused": True, "already": True}
    stamp = L.iso(when)
    wrote = []
    if scope.pause_file is not None:
        try:
            Path(scope.pause_file).parent.mkdir(parents=True, exist_ok=True)
            Path(scope.pause_file).write_text(
                json.dumps({"paused": True, "reason": reason, "since": stamp}, sort_keys=True),
                encoding="utf-8")
            wrote.append(str(scope.pause_file))
        except OSError:
            pass
    if scope.name == rules.SCOPE_HOUSE:
        target = Path(config_file) if config_file is not None else config_path()
        try:
            target.write_text(json.dumps(
                {"enabled": False, "paused_by": "learning_loop", "reason": reason, "since": stamp},
                sort_keys=True, indent=1) + "\n", encoding="utf-8")
            wrote.append(str(target))
        except OSError:
            pass
    L.log_for(scope).append(L.K_PAUSE, now=when, scope=scope.name, reason=reason, wrote=wrote)
    return {"paused": True, "already": False, "wrote": wrote}


def resume(scope: L.Scope, reason: str, *, now: Optional[datetime] = None,
           config_file: Optional[Path] = None) -> dict:
    """The owner turns the coach back on: clears the pause file, switches the house config on,
    records a ``resume`` event."""
    when = now or L.utc_now()
    stamp = L.iso(when)
    if scope.pause_file is not None:
        try:
            Path(scope.pause_file).parent.mkdir(parents=True, exist_ok=True)
            Path(scope.pause_file).write_text(
                json.dumps({"paused": False, "resumed": stamp, "reason": reason}, sort_keys=True),
                encoding="utf-8")
        except OSError:
            pass
    if scope.name == rules.SCOPE_HOUSE:
        target = Path(config_file) if config_file is not None else config_path()
        try:
            target.write_text(json.dumps({"enabled": True, "resumed": stamp}, sort_keys=True,
                                         indent=1) + "\n", encoding="utf-8")
        except OSError:
            pass
    L.log_for(scope).append(L.K_RESUME, now=when, scope=scope.name, reason=reason)
    return {"paused": False}
