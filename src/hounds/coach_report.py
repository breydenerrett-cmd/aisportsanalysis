"""The coach report card as a payload: ``GET /hounds/coach/report``, the Training camp panel, the kennel feed
items and the daily digest line all read this one builder (docs/COACH_REPORT_CARD.md).

WHAT IT SAYS, AND WHAT IT REFUSES TO SAY
  * The summary counts every suggestion, every refusal (bad coaching counts against the coach), and the live
    verdicts: HELPED / HURT / NO DIFFERENCE / TOO EARLY. "Graded forward" means a verdict other than TOO EARLY.
  * Hindsight is ALWAYS labelled hindsight, in the field names and in the sentence: the coach could see that
    period, so it is a rehearsal, not evidence. Its units total is reported apart from the live total.
  * A number that has not been computed is ``None`` and a sentence, never a zero.
  * Words for a knob come from the change list frozen on the suggestion row (the hound's own rule words), so a
    reader sees "4.0 points or more", not "0.04".

READS THE FILE, NOT THE STORES. The ledger is small, so a request folds it (with a size+mtime cache). Nothing
here opens an odds or results store, and nothing writes. Standard library plus ``coach_card``.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

from src.hounds import coach_card as C
from src.hounds import coach_grade as G

ITEMS_SHOWN = 20
REFUSED_SHOWN = 5
DISCLAIMER = "Paper bets only, not advice. 21+."

_CACHE: dict = {}


def units_text(units) -> str:
    """``+2.1u`` / ``-1.7u`` (a rounded zero is ``+0.0u``)."""
    if not isinstance(units, (int, float)) or isinstance(units, bool):
        return "n/a"
    rounded = round(float(units), 1)
    return f"{(0.0 if rounded == 0 else rounded):+.1f}u"


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def hindsight_summary(row: Optional[Mapping]) -> dict:
    """The hindsight grade as the page shows it. Always carries ``hindsight: true``."""
    if row is None:
        return {"hindsight": True, "status": "pending", "units_diff": None}
    if row.get("status") != "ok":
        return {"hindsight": True, "status": "error", "units_diff": None}
    return {"hindsight": True, "status": "ok", "units_diff": _num(row.get("units_diff")),
            "window_first": row.get("window_first"), "window_last": row.get("window_last"),
            "window_days": row.get("window_days"),
            "champion": row.get("champion"), "suggested": row.get("suggested"),
            "both_bet": row.get("both_bet"), "n_paired": row.get("n_paired")}


def forward_summary(row: Optional[Mapping]) -> dict:
    """The live grade. With no forward row yet the label is TOO EARLY with 0 bets, not a missing field."""
    if row is None:
        return {"label": G.LABEL_EARLY, "n_paired": 0, "n_dates": 0, "units_diff": 0.0, "mean_d": None,
                "ci_low": None, "ci_high": None, "champion": None, "suggested": None, "clv_diff": None,
                "updated_utc": None}
    both = row.get("both_bet") or {}
    return {"label": row.get("label") or G.LABEL_EARLY, "n_paired": int(row.get("n_paired") or 0),
            "n_dates": int(row.get("n_dates") or 0), "units_diff": _num(row.get("units_diff")) or 0.0,
            "mean_d": _num(row.get("mean_d")), "ci_low": _num(row.get("ci_low")), "ci_high": _num(row.get("ci_high")),
            "champion": row.get("champion"), "suggested": row.get("suggested"),
            "clv_diff": _num(both.get("clv_diff")), "updated_utc": row.get("utc")}


def hindsight_clause(h: Mapping) -> str:
    if h["status"] == "pending":
        return "Hindsight: still being worked out."
    if h["status"] == "error":
        return "Hindsight: could not be worked out."
    d = h["units_diff"]
    if d is None:
        return "Hindsight: not reported."
    rounded = round(d, 1)
    word = "better" if rounded > 0 else "worse" if rounded < 0 else "no different"
    return f"Hindsight: {units_text(d)} {word}." if rounded != 0 else "Hindsight: no different (+0.0u)."


def live_clause(f: Mapping) -> str:
    label, n = f["label"], f["n_paired"]
    bets = f"{n} bet{'' if n == 1 else 's'}"
    if label == G.LABEL_EARLY:
        return f"Live: too early ({bets})."
    word = {G.LABEL_HELPED: "helped", G.LABEL_HURT: "hurt", G.LABEL_NONE: "no difference"}.get(label, label.lower())
    return f"Live: {word} ({units_text(f['units_diff'])} over {bets})."


def one_liner(item: Mapping) -> str:
    """``Coach told Steamy Setter to change "..." from 3.0 points or more to 4.0 points or more. Hindsight:
    +2.1u better. Live: too early (3 bets).``"""
    name = item.get("hound_name") or item.get("hound") or "a hound"
    return (f"Coach told {name} to change {item['change_text']}. {hindsight_clause(item['hindsight'])} "
            f"{live_clause(item['forward'])}")


def _item(row: Mapping, card: C.Card) -> dict:
    issue = row["issue"]
    item = {
        "issue": issue, "issue_url": row.get("issue_url"), "hound": row.get("hound"),
        "hound_name": row.get("hound_name") or row.get("hound"), "recorded_utc": row.get("recorded_utc"),
        "mode": row.get("mode"), "changes": row.get("changes") or [],
        "change_text": C.change_sentence(row.get("changes") or []), "hypothesis": row.get("hypothesis"),
        "challenger_id": row.get("challenger_id"), "challenger_blocked_by": row.get("challenger_blocked_by"),
        "hindsight": hindsight_summary(card.hindsight.get(issue)),
        "forward": forward_summary(card.forward.get(issue)),
    }
    item["line"] = one_liner(item)
    return item


def summarise(card: C.Card, items: list) -> dict:
    forward = [forward_summary(card.forward.get(i)) for i in card.suggestions]
    count = lambda label: sum(1 for f in forward if f["label"] == label)  # noqa: E731
    hind = [h for h in (hindsight_summary(card.hindsight.get(i)) for i in card.suggestions)
            if h["status"] == "ok" and h["units_diff"] is not None]
    helped, hurt, none_, early = (count(G.LABEL_HELPED), count(G.LABEL_HURT), count(G.LABEL_NONE),
                                  count(G.LABEL_EARLY))
    return {
        "suggestions": len(card.suggestions), "refused": len(card.refused),
        "graded_forward": helped + hurt + none_, "helped": helped, "hurt": hurt, "no_difference": none_,
        "too_early": early,
        "forward_units_diff": round(sum(f["units_diff"] for f in forward), 4) if forward else None,
        "hindsight_units_diff": round(sum(h["units_diff"] for h in hind), 4) if hind else None,
        "hindsight_note": "Hindsight is the 30 days before each tip, which the coach could see. A rehearsal, not evidence.",
        "challenger_tips": sum(1 for r in card.suggestions.values() if r.get("mode") == C.MODE_CHALLENGER),
    }


def build_from_card(card: C.Card, *, limit: int = ITEMS_SHOWN, chain_ok: Optional[bool] = None,
                    coach_on: Optional[bool] = None) -> dict:
    rows = sorted(card.suggestions.values(), key=lambda r: (str(r.get("recorded_utc") or ""), r["issue"]),
                  reverse=True)
    items = [_item(r, card) for r in rows[:limit]]
    refused = sorted(card.refused.values(), key=lambda r: r["issue"], reverse=True)[:REFUSED_SHOWN]
    return {
        "computed": bool(card.suggestions or card.refused),
        "summary": summarise(card, items), "items": items,
        "recent_refused": [{"issue": r["issue"], "issue_url": r.get("issue_url"), "hound": r.get("hound"),
                            "reason": r.get("reason"), "utc": r.get("utc")} for r in refused],
        "last_change_utc": card.last_utc, "chain_ok": chain_ok, "coach_on": coach_on,
        "message": None if (card.suggestions or card.refused)
        else "The coach has not made a suggestion yet. When it does, it shows up here and gets graded by code.",
        "paper_only": True, "not_advice": DISCLAIMER,
    }


def _signature(paths: C.Paths):
    try:
        st = os.stat(paths.ledger)
        return (str(paths.ledger), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(paths.ledger), None, None)


def build(paths: Optional[C.Paths] = None, *, limit: int = ITEMS_SHOWN, coach_on: Optional[bool] = None) -> dict:
    """The report from the ledger on disk. Cached on the file's size and mtime."""
    paths = paths or C.Paths.default()
    sig = (_signature(paths), limit, coach_on)
    hit = _CACHE.get(sig)
    if hit is not None:
        return hit
    chain_ok = None
    if paths.ledger.exists():
        try:
            chain_ok = bool(C.chain(paths).verify().ok)
        except Exception:  # noqa: BLE001 -- an unreadable chain is reported as not ok, never a 500
            chain_ok = False
    try:
        card = C.load(paths)
    except Exception:  # noqa: BLE001
        card, chain_ok = C.Card(), False
    out = build_from_card(card, limit=limit, chain_ok=chain_ok, coach_on=coach_on)
    _CACHE.clear()
    _CACHE[sig] = out
    return out


def digest_line(report: Mapping) -> Optional[str]:
    """``🧠 Coach: 3 tips so far, 1 helped, 0 hurt (live)`` or None before the first tip."""
    s = report.get("summary") or {}
    n = s.get("suggestions") or 0
    if not n:
        return None
    return f"🧠 Coach: {n} tip{'' if n == 1 else 's'} so far, {s.get('helped', 0)} helped, {s.get('hurt', 0)} hurt (live)"
