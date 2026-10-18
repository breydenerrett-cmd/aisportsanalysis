"""Versions of a hound, and how the public stats show them (docs/PREREG_LEARNING_LOOP.md section 8).

A promotion makes the next VERSION. The old version keeps its own record, visible; the new one starts
its own from the promotion. For USER hounds that is automatic: a version is a hound row with its own
id and its own ledger rows. For PACK hounds a version is a stamp on the bet rows (``hound_version``),
so the stats need one step to keep them apart: ``split_versions`` gives every earlier version its own
retired entry (id ``<hound>@v<n>``, "superseded by version n+1") and leaves the hound's own id with the
current version's bets only. Nothing is rewritten: it is a regrouping of rows by the stamp they carry.

The lineage payload (``lineage_payload``) is what ``GET /hounds/{id}/lineage`` and the hound page's
"Versions and challengers" section show: every version with its record, the live challengers with
their paired numbers so far, the tried-and-failed list, and the lessons.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Mapping, Optional, Sequence

from src.hounds.learning import ledger as L
from src.hounds.learning import lessons, rules, tunables

ARCHIVE_SEP = "@v"


def archived_id(hound_id: str, version: int) -> str:
    return f"{hound_id}{ARCHIVE_SEP}{version}"


def base_id(hound_id: str) -> str:
    return hound_id.split(ARCHIVE_SEP)[0]


def version_text(tun: Optional[tunables.TunableHound], state: L.State, hound_id: str, version: int,
                 fallback: str) -> str:
    """The rule text of a version: v1 is the declared text; later versions are generated from the knob
    values their promotion recorded."""
    if tun is None or version <= 1:
        return fallback
    promo = next((p for p in state.promotions_for(hound_id) if int(p["to_version"]) == version), None)
    if promo is None:
        return fallback
    return tunables.rule_text(tun, tunables.full_values(tun, promo.get("params")))


def split_versions(defs_by_id: dict, all_bets: dict, events_paths: Sequence, *,
                   tun_cfg: Optional[Mapping] = None) -> list:
    """Regroup pack bets by version (in place). Returns the ids it archived."""
    state = L.State()
    for path in events_paths:
        p = Path(path)
        if p.exists():
            st = L.fold(L.EventLog(p).read())
            state.promotions.extend(st.promotions)
    # A row's own stamp is evidence of a version even if the registry cannot be read: group by it.
    stamped = {hid for hid, rows in all_bets.items() if any(int(b.hound_version or 1) > 1 for b in rows)}
    hounds = sorted({p["hound_id"] for p in state.promotions} | stamped)
    if not hounds:
        return []
    tun = tun_cfg if tun_cfg is not None else tunables.load()
    made = []
    for hid in hounds:
        if hid not in defs_by_id:
            continue
        current = max([state.champion_version(hid)] + [int(b.hound_version or 1) for b in all_bets.get(hid, [])])
        base_def = defs_by_id[hid]
        by_version: dict = {}
        for b in all_bets.get(hid, []):
            by_version.setdefault(int(b.hound_version or 1), []).append(b)
        versions = sorted(set(by_version) | set(range(1, current)))
        for n in versions:
            if n == current or n >= current:
                continue
            promo = next((p for p in state.promotions_for(hid) if int(p["to_version"]) == n + 1), None)
            aid = archived_id(hid, n)
            d = copy.deepcopy(base_def)
            d.update({
                "id": aid, "name": f"{base_def['name']} (version {n})",
                "rule_text": version_text(tun.get(hid), state, hid, n, base_def["rule_text"]),
                "retired": {"date": str((promo or {}).get("utc") or "")[:10] or None,
                            "cause": f"superseded by version {n + 1} (promoted challenger "
                                     f"{(promo or {}).get('challenger_id')})"},
                "status_hint": "retired", "not_started_when_empty": False,
            })
            defs_by_id[aid] = d
            mine = by_version.get(n, [])
            for b in mine:
                b.hound_id = aid
            all_bets[aid] = mine
            made.append(aid)
        all_bets[hid] = by_version.get(current, [])
        base_def["rule_text"] = version_text(tun.get(hid), state, hid, current, base_def["rule_text"])
        base_def["status_hint"] = "running"
    return made


# ---- the lineage payload -------------------------------------------------------------------------------

def _challenger_row(c: L.Challenger) -> dict:
    real = [lk for lk in c.looks if not lk.get("skipped")]
    last = real[-1] if real else None
    out = {"id": c.id, "status": c.status, "outcome_reason": c.outcome_reason, "hypothesis": c.hypothesis,
           "spec_diff": c.spec_diff, "created_utc": c.created_utc, "ended_utc": c.ended_utc,
           "parent_version": c.parent_version, "kind": c.kind,
           "rule_text": (c.spec.get("rule_text") if c.kind == "pack" else None),
           "looks": len(real)}
    if last:
        out["latest_look"] = {k: last.get(k) for k in ("look_no", "n", "dates", "mean", "lower", "upper",
                                                       "p_better", "eligible", "harm", "volume_ok", "look_date")}
    return out


def lineage_payload(hound_id: str, *, state: L.State, versions: Sequence[Mapping],
                    lesson_rows: Sequence[Mapping] = (), paused: bool = False) -> dict:
    """``versions`` are already-built per-version summaries (id, version_no, status, record, verdict, ...)
    in order; this adds the challengers and the lessons around them."""
    key = base_id(hound_id)
    mine = [c for c in state.challengers.values() if c.lineage_key == key or c.hound_id == key]
    return {
        "hound_id": hound_id, "paused": paused,
        "versions": list(versions),
        "live_challengers": [_challenger_row(c) for c in mine if c.live],
        "tried_and_failed": [_challenger_row(c) for c in mine if c.status == rules.OUTCOME_RETIRED],
        "closed_undecided": [_challenger_row(c) for c in mine if c.status == rules.OUTCOME_UNDECIDED],
        "promoted": [_challenger_row(c) for c in mine if c.status == rules.OUTCOME_PROMOTED],
        "lessons": [{k: r.get(k) for k in ("lesson_id", "outcome", "reason", "lesson", "hypothesis", "utc")}
                    for r in lesson_rows if r.get("lineage_key") == key or r.get("hound_id") == key][:20],
        "rules": {"promoted_only_by": "a pre-set sequential test of the paired closing-line value, "
                                      "controlled for false discoveries across all challengers",
                  "looks": list(rules.LOOKS), "live_cap": rules.MAX_LIVE_PER_HOUND},
    }
