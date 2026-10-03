"""Rebuild the golden fixtures behind tests/test_matchup_read.py.

Each fixture is one real game payload for 2026-10-03, built by the app
in-process (api.games.get_game) exactly as the route serves it, `read` and
`read_inputs` included. The golden test strips `read`, rebuilds it from the
rest of the payload, and compares: any change to the read's wording or logic
shows up as a fixture diff that a person has to look at and accept.

This reaches the MLB schedule provider (one request) because the app builds
its slate from the live schedule. It does not touch any deployed host. Run it
only when the read's wording or logic changed on purpose:

    python3 scripts/regen_matchup_read_fixtures.py

Only the `read` block is regenerated for the existing payloads by default
(`--keep-payloads`), so the stored inputs stay frozen while the wording moves.
Pass `--rebuild-payloads` to re-fetch today's games, which a different day
would change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"
DATE = "2026-10-03"
GAMES = (("CWS", "CLE"), ("ATL", "LAD"), ("NYY", "TB"), ("SD", "MIL"))


def fixture_path(away: str, home: str) -> Path:
    return FIXTURES / f"matchup_read_{DATE}_{away}_{home}.json"


DOC = ROOT / "docs" / "MATCHUP_READ.md"
START, END = "<!-- READS:START -->", "<!-- READS:END -->"


def _value(v) -> str:
    return f"{round(v, 3)}" if isinstance(v, float) else str(v)


def read_markdown(away: str, home: str, game: dict, read: dict) -> str:
    """One read, every sentence verbatim, as markdown."""
    out = [f"### {away} at {home}", ""]
    out.append(f"**Headline.** {read['headline']}")
    out.append("")
    for note in read["notices"]:
        out.append(f"**Notice.** {note}")
        out.append("")
    out.append(f"_{read['label']}_")
    out.append("")
    out.append("**What stands out, largest first**")
    out.append("")
    for f in read["factors"]:
        side = "no side" if f["favours"] == "even" else f"favours {f['favours']}"
        out.append(f"{f['rank']}. **{f['title']}** ({side}, {f['size']}, "
                   f"{f['confidence']} confidence). {f['sentence']}")
        out.append(f"   - Caveat: {f['caveat']}")
        ev = "; ".join(f"{e['label']} = {_value(e['value'])}"
                       + (" (worked out)" if e.get("derived") else "") for e in f["evidence"])
        out.append(f"   - Evidence ({len(f['evidence'])}): {ev}")
    out.append("")
    env = read["run_environment"]
    out.append("**Expected runs, an estimate**")
    out.append("")
    out.append(env["label"])
    out.append("")
    if env["available"]:
        for side in ("away", "home"):
            row = env[side]
            out.append(f"- {row['team']}: {row['expected_runs']:.1f}, range {row['low']:.1f} to {row['high']:.1f}")
        g = env["game"]
        out.append(f"- Game total: {g['expected_total']:.1f}, range {g['low']:.1f} to {g['high']:.1f}")
        out.append("")
        out.append("The arithmetic:")
        out.append("")
        for line in env["arithmetic"] + env["caveats"]:
            out.append(f"- {line}")
    else:
        out.append(env.get("reason", "No estimate."))
    out.append("")
    out.append("**What the price says**")
    out.append("")
    for s in read["market_view"]["sentences"]:
        out.append(f"- {s}")
    out.append("")
    out.append("**What would change it**")
    out.append("")
    for w in read["what_would_change_it"]:
        out.append(f"- {w['fact']} {w['because']}")
    out.append("")
    out.append(f"**What we could not use ({len(read['missing'])})**")
    out.append("")
    for m in read["missing"]:
        out.append(f"- [{m['status']}] {m['input']}. {m['detail']}")
    out.append("")
    return "\n".join(out)


def write_doc() -> None:
    parts = []
    for away, home in GAMES:
        payload = json.loads(fixture_path(away, home).read_text(encoding="utf-8"))
        parts.append(read_markdown(away, home, payload["advanced"]["game"], payload["read"]))
    text = DOC.read_text(encoding="utf-8")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    DOC.write_text(head + START + "\n\n" + "\n".join(parts) + "\n" + END + tail,
                   encoding="utf-8")
    print(f"wrote {DOC.relative_to(ROOT)}")


def main(argv) -> int:
    from src.analysis import matchup_read

    rebuild = "--rebuild-payloads" in argv
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for away, home in GAMES:
        path = fixture_path(away, home)
        if rebuild or not path.exists():
            from api import games as games_mod
            payload = games_mod.get_game(DATE, away, home)
            payload = json.loads(json.dumps(payload, default=str))
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("read", None)
        payload["read"] = matchup_read.build_read(payload)
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True)
                        + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}: {payload['read']['headline']}")
    write_doc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
