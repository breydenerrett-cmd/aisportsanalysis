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

THE FAN LANE. Fan tips (src/hounds/fan_tips.py) are graded by the same code and reported in their own block
(``fans``: a summary and the latest 20 tips, each with its grades), never folded into the coach's counts. The
``versus`` line sets the two side by side on LIVE grades only; hindsight gets a separate, labelled line.

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
_GRADES_CACHE: dict = {}


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


# ---- the fan lane -------------------------------------------------------------------------------------------

def fan_name(row: Mapping) -> str:
    return row.get("nickname") or "A fan"


def fan_one_liner(item: Mapping) -> str:
    """``Ann told Steamy Setter to change "..." from 3.0 points or more to 4.0 points or more. Hindsight: ...
    Live: ...`` (``A fan`` without a nickname; ``3 fans sent this`` when the same tip came in more than once)."""
    name = item.get("hound_name") or item.get("hound") or "a hound"
    who = item["fan_name"]
    more = f" ({item['count']} fans sent this.)" if item.get("count", 1) > 1 else ""
    return (f"{who} told {name} to change {item['change_text']}. {hindsight_clause(item['hindsight'])} "
            f"{live_clause(item['forward'])}{more}")


def _fan_item(row: Mapping, card: C.Card) -> dict:
    key = row["issue"]
    first = card.first_helped.get(key)
    item = {
        "issue": key, "tip_id": row.get("tip_id"), "hound": row.get("hound"),
        "hound_name": row.get("hound_name") or row.get("hound"), "nickname": row.get("nickname"),
        "fan_name": fan_name(row), "count": card.fan_counts.get(key, 1),
        "tip_created_utc": row.get("tip_created_utc"), "recorded_utc": row.get("recorded_utc"),
        "changes": row.get("changes") or [], "change_text": C.change_sentence(row.get("changes") or []),
        "hindsight": hindsight_summary(card.hindsight.get(key)),
        "forward": forward_summary(card.forward.get(key)),
        "first_helped": None if first is None else {"utc": first.get("utc"), "units_diff": _num(first.get("units_diff")),
                                                    "n_paired": int(first.get("n_paired") or 0)},
    }
    item["line"] = fan_one_liner(item)
    return item


def fans_summary(card: C.Card) -> dict:
    """The fan lane's counts, shaped like the coach's ``summarise`` (so the page reads both the same way)."""
    forward = [forward_summary(card.forward.get(k)) for k in card.fans]
    count = lambda label: sum(1 for f in forward if f["label"] == label)  # noqa: E731
    hind = [h for h in (hindsight_summary(card.hindsight.get(k)) for k in card.fans)
            if h["status"] == "ok" and h["units_diff"] is not None]
    helped, hurt, none_, early = (count(G.LABEL_HELPED), count(G.LABEL_HURT), count(G.LABEL_NONE),
                                  count(G.LABEL_EARLY))
    return {
        "tips": len(card.fans), "sent": sum(card.fan_counts.get(k, 1) for k in card.fans),
        "graded_forward": helped + hurt + none_, "helped": helped, "hurt": hurt, "no_difference": none_,
        "too_early": early,
        "forward_units_diff": round(sum(f["units_diff"] for f in forward), 4) if forward else None,
        "hindsight_units_diff": round(sum(h["units_diff"] for h in hind), 4) if hind else None,
        "hindsight_note": "Hindsight is the 30 days before each tip. A rehearsal, not evidence.",
    }


def versus(coach: Mapping, fans: Mapping) -> dict:
    """The AI coach against the fans on LIVE grades: ``helped`` out of ``graded`` (a verdict other than TOO
    EARLY) on each side. Hindsight totals get their own labelled line and never enter the live one."""
    c_h, c_g = int(coach.get("helped") or 0), int(coach.get("graded_forward") or 0)
    f_h, f_g = int(fans.get("helped") or 0), int(fans.get("graded_forward") or 0)
    if c_g == 0 and f_g == 0:
        line = "Coach vs the fans: nothing has a live grade yet on either side, so there is no scoreboard."
    else:
        line = (f"Coach vs the fans: the coach helped {c_h} of {c_g} graded tips, the fans helped {f_h} of "
                f"{f_g} (live grades only).")
    c_u, f_u = coach.get("hindsight_units_diff"), fans.get("hindsight_units_diff")
    hind = None
    if c_u is not None or f_u is not None:
        hind = ("Hindsight, a rehearsal and not evidence: the coach " + (units_text(c_u) if c_u is not None else "n/a")
                + ", the fans " + (units_text(f_u) if f_u is not None else "n/a") + ".")
    return {"coach": {"helped": c_h, "graded": c_g}, "fans": {"helped": f_h, "graded": f_g},
            "line": line, "hindsight_line": hind}


def fans_block(card: C.Card, coach_summary: Mapping, *, limit: int = ITEMS_SHOWN) -> dict:
    rows = sorted(card.fans.values(), key=lambda r: (str(r.get("recorded_utc") or ""), r["issue"]), reverse=True)
    summary = fans_summary(card)
    helped = sorted((_fan_item(r, card) for r in card.fans.values() if r["issue"] in card.first_helped),
                    key=lambda i: (str((i["first_helped"] or {}).get("utc") or ""), i["issue"]), reverse=True)
    return {
        "computed": bool(card.fans), "summary": summary, "items": [_fan_item(r, card) for r in rows[:limit]],
        "helped_events": helped[:50],
        "versus": versus(coach_summary, summary),
        "message": None if card.fans else
        "No fan tips have been graded yet. Send one from a dog's page and it gets the coach's treatment.",
    }


def fan_grades(card: C.Card) -> dict:
    """``{tip_id: {label, units_diff, n_paired, hindsight_units_diff}}`` for every recorded tip id (a repeat
    of a tip shares its first row's grade). The dog page's tip list reads this."""
    out = {}
    for key, row in card.fans.items():
        f = forward_summary(card.forward.get(key))
        h = hindsight_summary(card.hindsight.get(key))
        grade = {"label": f["label"], "units_diff": f["units_diff"], "n_paired": f["n_paired"],
                 "hindsight_units_diff": h["units_diff"] if h["status"] == "ok" else None}
        for tid in [row.get("tip_id"), *(t for t, k in card.fan_dup_of.items() if k == key)]:
            if isinstance(tid, str):
                out[tid] = grade
    return out


def build_from_card(card: C.Card, *, limit: int = ITEMS_SHOWN, chain_ok: Optional[bool] = None,
                    coach_on: Optional[bool] = None) -> dict:
    rows = sorted(card.suggestions.values(), key=lambda r: (str(r.get("recorded_utc") or ""), r["issue"]),
                  reverse=True)
    items = [_item(r, card) for r in rows[:limit]]
    refused = sorted(card.refused.values(), key=lambda r: r["issue"], reverse=True)[:REFUSED_SHOWN]
    summary = summarise(card, items)
    return {
        "computed": bool(card.suggestions or card.refused),
        "summary": summary, "items": items,
        "fans": fans_block(card, summary, limit=limit),
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


def fan_grades_now(paths: Optional[C.Paths] = None) -> dict:
    """``fan_grades`` from the ledger on disk (cached on its size and mtime). {} when there is none or it
    cannot be read: a dog page's tip list must never fail because the report card did."""
    paths = paths or C.Paths.default()
    sig = _signature(paths)
    hit = _GRADES_CACHE.get(sig)
    if hit is not None:
        return hit
    try:
        out = fan_grades(C.load(paths)) if paths.ledger.exists() else {}
    except Exception:  # noqa: BLE001
        return {}
    _GRADES_CACHE.clear()
    _GRADES_CACHE[sig] = out
    return out


def digest_line(report: Mapping) -> Optional[str]:
    """``🧠 Coach: 3 tips so far, 1 helped, 0 hurt (live)`` or None before the first tip."""
    s = report.get("summary") or {}
    n = s.get("suggestions") or 0
    if not n:
        return None
    return f"🧠 Coach: {n} tip{'' if n == 1 else 's'} so far, {s.get('helped', 0)} helped, {s.get('hurt', 0)} hurt (live)"
