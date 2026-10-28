#!/usr/bin/env python3
"""Pull every hound's bets and every hound version from linehound.app into data/research/bets_pull/<UTC date>/.

Needs LINEHOUND_RESEARCH_TOKEN in the environment or in .env at the repo root (see docs/owner/RESEARCH_KEY.md). Prints counts only,
never the token. Read-only against the site; the output folder is gitignored because it holds member data."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://linehound.app"
ENV_NAME = "LINEHOUND_RESEARCH_TOKEN"


def load_token(env=None, env_file: Path = ROOT / ".env") -> str:
    env = os.environ if env is None else env
    tok = (env.get(ENV_NAME) or "").strip()
    if tok:
        return tok
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == ENV_NAME and v.strip():
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def fetch(path: str, token: str, base: str = BASE) -> bytes:
    req = urllib.request.Request(base + path, headers={"X-Research-Token": token})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def pull(token: str, out_root: Path = ROOT / "data" / "research" / "bets_pull", base: str = BASE, fetcher=fetch) -> dict:
    out = out_root / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out.mkdir(parents=True, exist_ok=True)
    bets = fetcher("/research/bets.jsonl", token, base)
    hounds = fetcher("/research/hounds.json", token, base)
    (out / "bets.jsonl").write_bytes(bets)
    (out / "hounds.json").write_bytes(hounds)
    return {"dir": str(out), "bets": len([ln for ln in bets.splitlines() if ln.strip()]),
            "hounds": len(json.loads(hounds).get("hounds", []))}


def main() -> int:
    token = load_token()
    if not token:
        print(f"{ENV_NAME} is not set (environment or .env). See docs/owner/RESEARCH_KEY.md.")
        return 2
    try:
        res = pull(token)
    except Exception as exc:  # noqa: BLE001 -- say what failed, never echo the request
        print(f"pull failed: {type(exc).__name__} (404 means the key is off or wrong)")
        return 1
    print(f"saved {res['bets']} bets and {res['hounds']} hound versions to {res['dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
