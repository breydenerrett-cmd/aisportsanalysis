"""scripts/foundry_beat.py -- Python helper for THE FOUNDRY's Phase 4B
heartbeat contract (see /home/user/thefoundry/PHASE4_HEARTBEAT_CONTRACT.md).

Appends one JSON line per event to `<repo>/.foundry/events.jsonl`. Foundry is
read-only; this only ever emits. Never pass secrets, prompts, PII, raw API
payloads, URLs with tokens, or transcript content as `artifact`/`error` --
short descriptive strings only.

foundry_beat() must never raise or otherwise affect the caller: every
failure is swallowed silently.
"""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            root = out.stdout.strip()
            if root:
                return Path(root)
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent


def foundry_beat(component: str, event: str, status: str,
                  artifact: str = "", error: str = "") -> None:
    """component event status [artifact] [error] -> append one JSON line.

    Never raises; a heartbeat failure must never affect the caller.
    """
    try:
        root = _repo_root()
        foundry_dir = root / ".foundry"
        foundry_dir.mkdir(parents=True, exist_ok=True)
        events_path = foundry_dir / "events.jsonl"

        def _clean(s: str) -> str:
            return (s or "").replace("\n", " ").replace("\r", " ")[:200]

        rec = {
            "component": component,
            "event": event,
            "status": status,
            "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        artifact = _clean(artifact)
        error = _clean(error)
        if artifact:
            rec["artifact"] = artifact
        if error:
            rec["error"] = error

        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
