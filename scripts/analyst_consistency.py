#!/usr/bin/env python3
"""Compare several answers to ONE frozen analyst request, slot by slot, and flag disagreements.

WHY IT EXISTS
-------------
On 2026-10-04 three answers to the same Braves-at-Dodgers request disagreed on one prop (see
evidence/analyst_consistency/2026-10-04_ATL-LAD/README.md). Whether that is noise or signal is a
question about the writer, not the game, so the comparison reads only the answers: verdict,
selection, price, book and fair_estimate for each slot, side by side. It never reads a game result
and never says which answer was right; three samples from one model are a diagnostic of how stable
the model's calls are, not sporting evidence.

INPUTS
------
A folder (every `*.json` in it that holds `calls`, plus any `*.md` that carries a partial transcript
record with a "Calls (slot, verdict, ...)" block) or explicit files. A partial record has no reasons
or evidence, so only the call table is compared and the source is marked (partial).

    python scripts/analyst_consistency.py evidence/analyst_consistency/2026-10-04_ATL-LAD
    python scripts/analyst_consistency.py DIR --report out.md

Stdlib only. Writes nothing unless `--report` is given.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

# Two fair_estimates this far apart (in probability) are flagged. Not a statistical test: a visible
# nudge for a human reading a table of three.
FAIR_GAP = 0.03

ACTION = ("TAKE", "TAKE_OTHER_SIDE")

# "prop_01 TAKE_OTHER_SIDE Under 6.5 +120 draftkings 0.52" in a partial transcript record.
_ROW = re.compile(r"^(?P<slot>[a-z_0-9]+) (?P<verdict>TAKE_OTHER_SIDE|TAKE|PASS) (?P<selection>.+?) "
                  r"(?P<price>[+-]?\d+) (?P<book>\S+) (?P<fair>\(none\)|[0-9.]+)\s*$")


def load_json_answer(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("calls"), list):
        return None
    calls = {}
    for call in data["calls"]:
        if isinstance(call, dict) and "slot_id" in call:
            calls[call["slot_id"]] = {
                "verdict": call.get("verdict"), "selection": call.get("selection"),
                "price": call.get("price"), "book": call.get("book"),
                "fair_estimate": call.get("fair_estimate")}
    return {"name": path.stem, "partial": False, "calls": calls, "slots": [c["slot_id"] for c in data["calls"]
                                                                          if isinstance(c, dict) and "slot_id" in c]}


def load_partial_record(path: Path) -> Optional[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    calls, slots = {}, []
    for line in lines:
        m = _ROW.match(line.strip())
        if not m:
            continue
        fair = m["fair"]
        calls[m["slot"]] = {
            "verdict": m["verdict"], "selection": m["selection"], "price": int(m["price"]),
            "book": m["book"], "fair_estimate": None if fair == "(none)" else float(fair)}
        slots.append(m["slot"])
    if not calls:
        return None
    return {"name": path.stem, "partial": True, "calls": calls, "slots": slots}


def load_answers(paths: list) -> list:
    files = []
    for raw in paths:
        p = Path(raw)
        files.extend(list(p.glob("*.json")) + list(p.glob("*.md")) if p.is_dir() else [p])
    answers = []
    for f in sorted(files, key=lambda f: f.name):      # attempt1, attempt2, sample3: the order they were written
        if f.name.lower() in ("readme.md",):
            continue
        got = load_json_answer(f) if f.suffix == ".json" else load_partial_record(f)
        if got:
            answers.append(got)
    return answers


def _fmt_price(price) -> str:
    if price is None:
        return "-"
    return f"{price:+d}" if isinstance(price, int) else str(price)


def _fmt_fair(fair) -> str:
    return "-" if fair is None else f"{fair:g}"


def describe(call: Optional[dict]) -> str:
    if call is None:
        return "(no call)"
    return (f"{call['verdict']} {call['selection']} {_fmt_price(call['price'])} {call['book'] or '-'} "
            f"fair {_fmt_fair(call['fair_estimate'])}")


def flags(calls: list) -> list:
    """Disagreement flags for one slot across the answers that made a call on it."""
    made = [c for c in calls if c is not None]
    out = []
    if len(made) < 2:
        return out
    verdicts = {c["verdict"] for c in made}
    acts = {c["verdict"] in ACTION for c in made}
    if acts == {True, False}:
        out.append("ACTION (one answer bets, another passes)")
    elif len(verdicts) > 1:
        out.append("VERDICT")
    if any(c["verdict"] in ACTION for c in made) and len({c["selection"] for c in made if c["verdict"] in ACTION}) > 1:
        out.append("SIDE (bets on different selections)")
    elif len({c["selection"] for c in made}) > 1 and "ACTION" not in " ".join(out):
        out.append("SELECTION")
    by_selection: dict = {}
    for c in made:                      # a price can only disagree with a price for the same selection
        by_selection.setdefault(c["selection"], set()).add((c["price"], c["book"]))
    if any(len(quotes) > 1 for quotes in by_selection.values()):
        out.append("PRICE/BOOK")
    fairs = [c["fair_estimate"] for c in made if c["fair_estimate"] is not None]
    if len(fairs) >= 2 and max(fairs) - min(fairs) >= FAIR_GAP:
        out.append(f"FAIR (gap {max(fairs) - min(fairs):.2f})")
    return out


def table(answers: list) -> list:
    """Rows of (slot, [call per answer], [flags]), in the first complete answer's slot order."""
    order = []
    for a in sorted(answers, key=lambda a: a["partial"]):      # full answers first, for slot order
        for slot in a["slots"]:
            if slot not in order:
                order.append(slot)
    rows = []
    for slot in order:
        calls = [a["calls"].get(slot) for a in answers]
        rows.append((slot, calls, flags(calls)))
    return rows


def label(answer: dict) -> str:
    return answer["name"] + (" (partial)" if answer["partial"] else "")


def print_table(answers: list, rows: list, out=print) -> None:
    out("answers: " + "; ".join(f"[{i}] {label(a)}" for i, a in enumerate(answers, 1)))
    disagreements = 0
    for slot, calls, flag in rows:
        out(f"{slot}{'   <-- ' + ', '.join(flag) if flag else ''}")
        for i, call in enumerate(calls, 1):
            out(f"    [{i}] {describe(call)}")
        disagreements += bool(flag)
    action = [slot for slot, _, flag in rows if any(f.startswith("ACTION") for f in flag)]
    out(f"{len(rows)} slots, {disagreements} with a disagreement; "
        f"{len(action)} where one answer bets and another passes"
        + (f": {', '.join(action)}" if action else ""))


def markdown(answers: list, rows: list) -> str:
    head = "| slot | " + " | ".join(f"[{i}] {label(a)}" for i, a in enumerate(answers, 1)) + " | flags |"
    lines = [head, "|" + "---|" * (len(answers) + 2)]
    for slot, calls, flag in rows:
        cells = [describe(c).replace("|", "/") for c in calls]
        lines.append(f"| {slot} | " + " | ".join(cells) + f" | {', '.join(flag) if flag else ''} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", help="a folder of answers, or answer files")
    ap.add_argument("--report", default=None, help="write the table as markdown to this file")
    args = ap.parse_args(argv)
    answers = load_answers(args.paths)
    if len(answers) < 2:
        print(f"need at least two answers to compare; found {len(answers)}", file=sys.stderr)
        return 2
    rows = table(answers)
    print_table(answers, rows)
    if args.report:
        Path(args.report).write_text(markdown(answers, rows), encoding="utf-8")
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
