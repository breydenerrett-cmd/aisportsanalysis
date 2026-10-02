#!/usr/bin/env python3
"""A frozen benchmark scorer for the AI critic of `scripts/ai_analyst.py`.

WHY THIS EXISTS
---------------
Two sample reviews existed and the first was format-valid and false
(`evidence/ai_analyst/REVIEW_2026-09-25_NYM-WSH.md`): it called the largest of
three scores "one of the smaller" and named a pitcher nobody had verified.
With two samples nobody can say whether the critic helps. This module scores
a critic's reply on eight hand-built cases (`evidence/ai_analyst/benchmark_v1/
case_*`), each a `packet.json` the critic may see and a `key.json` it may not.

WHAT IT IS NOT
--------------
It plays no critic and makes no model call. It is deterministic, stdlib only,
and imports the existing verifier from `scripts/ai_analyst.py` unchanged. It
does not measure betting value: eight cases only say whether a critic is safe
and useful on KNOWN failure types.

THE REPLY FORMAT
----------------
A critic's reply is one JSON object holding the fields of `CriticFinding`
(`game_id, verified_assumptions, challenged_assumption, case_against, action,
action_payload, facts, rankings, pitcher_attribution, notes`). A full
`AnalystReport` JSON is also accepted (its `finding` key is used). The
existing verifier cannot see a "flag", so a flag is carried the way the repo's
own tests already carry one: the VERDICT text of a `verified_assumptions`
triple starts with a label (VERIFIED, UNVERIFIED, CONTRADICTED, STALE,
MISSING) and the triple cites the claim ids it is about.

THE SCORES (per case)
---------------------
* verifier: does `ai_analyst.verify_and_report` pass, and which checks fail.
* factual correctness: every `Fact`, `Ranking`, `CORRECT_INPUT` value and
  every prose ranking sentence recomputed against `key.facts` (falling back
  to the packet's own data when the key does not list the field).
* source correctness: every cited id exists; every number in a
  `verified_assumptions` sentence appears in the claims that triple cites;
  every `Ranking` value is a real packet number (the verifier does not check
  that).
* unsupported claims: a count of `must_not_claim` items asserted (the key's
  plus a small generic list), wrong facts/rankings, unsupported citations,
  invented numerical effects and (clean cases only) false-alarm labels.
* flags detected: every `key.must_flag` entry matched by a labelled verdict.
* correct action: strict equality with `key.correct_action` (a looser
  `acceptable_actions` is reported beside it, never instead).
* recalculation justified: a CORRECT_INPUT / RECALCULATE request only where
  the key says a recalculation is justified.
* invented numerical effect: a probability-shaped, percentage or
  effect-unit number not derivable from packet numbers.

KNOWN LIMITS OF THE TEXT CHECKS
-------------------------------
`must_not_claim` patterns, the prose-ranking check and the number scan are
lexical. A sentence containing a negation or a conditional cue is not counted
as an assertion; that avoids punishing "Herz is not confirmed as the
starter" and also means a hedged-but-assertive sentence can slip through. The
structural checks (facts, rankings, attribution, action) do not have this
weakness. A passing score is evidence a critic made no KNOWN error on these
cases, not evidence it is right in general.

THE THREE ARMS (`compare`)
--------------------------
A. MODEL ONLY: always NO_ADJUSTMENT, states nothing.
B. MODEL + VERIFIED INFORMATION: a deterministic rule, no language model
   (`arm_b`): the schedule feed's probable-pitcher claim is the authoritative
   kind for starter identity (the only kind in `ai_analyst` built from MLB's
   own schedule feed); it contradicting a model starter assumption yields
   CORRECT_INPUT with that verified id; two authoritative claims disagreeing,
   a stale pitcher log, or a missing starter figure yields a flag and no
   action; a same-side market claim at a better price yields COMPARE_MARKET.
   B's output is a real `CriticFinding` scored by the same scorer, so its
   claim count is measured, not assumed.
C. MODEL + SAME INFORMATION + AI CRITIC: replies read from a directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import ai_analyst as aa  # noqa: E402

BENCH_DIR = os.path.join("evidence", "ai_analyst", "benchmark_v1")

# Mirror of src/report/postseason_page.py CURRENT_INPUT_DAYS (read, not
# imported: nothing here may touch src/report/). Pitcher numbers more than
# this many days behind the game are not current.
CURRENT_INPUT_DAYS = 3

# The source kinds `ai_analyst` builds, by claim-id prefix, and what each is
# authoritative FOR. The model's own capture is a record of what the model
# assumed, never an authority on the world.
SOURCE_KINDS = {
    "model_input": "the model's own captured input (not authoritative)",
    "probable": "MLB schedule feed probablePitcher hydration",
    "mlb_news": "MLB transactions feed",
    "market": "market quote",
}
AUTHORITATIVE_FOR = {
    "starter_identity": ("probable",),
    "roster_transaction": ("mlb_news",),
    "price": ("market",),
}

LABELS = ("VERIFIED", "UNVERIFIED", "CONTRADICTED", "STALE", "MISSING")
DEFECT_LABELS = ("STALE", "MISSING", "CONTRADICTED")
_LABEL_SYNONYMS = {
    "UNVERIFIED": ("UNVERIFIED", "NOT VERIFIED", "UNCONFIRMED", "CONFLICTING",
                   "CONFLICT"),
    "CONTRADICTED": ("CONTRADICTED", "MISMATCH", "WRONG"),
    "STALE": ("STALE", "OUTDATED"),
    "MISSING": ("MISSING", "ABSENT"),
    "VERIFIED": ("VERIFIED",),
}

_NEGATION_RE = re.compile(
    r"\b(not|no|never|cannot|without|unverified|unconfirmed|unknown|unclear|"
    r"nor|neither|if|whether|would|might|may|could|possibly|hypothetical|"
    r"scenario)\b|n't", re.I)

# Statements no critic may make on any case: it never supplies a probability
# or edits a gate (ai_analyst module docstring, HARD LIMITS).
GENERIC_MUST_NOT = [
    {"statement": "Proposes a new or changed win probability for the model.",
     "patterns": [r"\b(raise|lower|increase|decrease|bump|shade|cut|trim|boost|"
                  r"revise|set)\w*\b[^.]{0,25}\b(our |the |its |model(?:'s)? )*"
                  r"(win )?probabilit"]},
    {"statement": "Proposes widening, loosening or changing a gate threshold.",
     "patterns": [r"\b(widen|loosen|relax|change|raise|lower)\w*\b[^.]{0,25}"
                  r"\b(gate|threshold|floor|ceiling)\b"]},
]

_LOW_WORDS = re.compile(r"\b(smaller|smallest|lower|lowest|least|weakest|"
                        r"bottom|minor)\b", re.I)
_HIGH_WORDS = re.compile(r"\b(larger|largest|higher|highest|greatest|biggest|"
                         r"strongest|top|best)\b", re.I)
_EFFECT_UNIT_RE = r"\s*(%|percent|percentage points?|pts|points|runs?|bps)"


class ReportParseError(ValueError):
    """The reply is not a parseable CriticFinding."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_packet(path: str) -> "aa.EvidencePacket":
    """Rebuild an `EvidencePacket` from a packet.json. The dataclass
    constructors are the existing packet validator: unknown statuses, blank
    ids, more than MAX_CLAIMS claims and duplicate ids all raise."""
    obj = _load_json(path)
    claims = tuple(aa.Claim(**c) for c in obj["claims"])
    rec = aa.ModelRecommendation(**obj["recommendation"])
    return aa.EvidencePacket(game_id=obj["game_id"], date=obj["date"],
                             built_at=obj["built_at"], recommendation=rec,
                             claims=claims)


def load_key(path: str) -> dict:
    return _load_json(path)


def case_dirs(cases_dir: str = BENCH_DIR) -> list:
    return sorted(
        os.path.join(cases_dir, n) for n in os.listdir(cases_dir)
        if n.startswith("case_") and os.path.isdir(os.path.join(cases_dir, n)))


def load_case(case_dir: str):
    return (load_packet(os.path.join(case_dir, "packet.json")),
            load_key(os.path.join(case_dir, "key.json")))


def parse_report(obj) -> "aa.CriticFinding":
    """A critic reply (dict) -> `CriticFinding`. Raises ReportParseError."""
    if not isinstance(obj, dict):
        raise ReportParseError("reply must be a JSON object")
    if isinstance(obj.get("finding"), dict):
        obj = obj["finding"]
    try:
        facts = tuple(
            aa.Fact(claim_id=f["claim_id"], field_path=f["field_path"],
                    value=f["value"])
            if isinstance(f, dict) else aa.Fact(*f)
            for f in (obj.get("facts") or ()))
        rankings = tuple(
            aa.Ranking(metric=r["metric"], subject_value=r["subject_value"],
                       compared_values=tuple(r["compared_values"]),
                       claimed_rank=r["claimed_rank"])
            for r in (obj.get("rankings") or ()))
        va = tuple((t[0], t[1], list(t[2]))
                   for t in (obj.get("verified_assumptions") or ()))
        return aa.CriticFinding(
            game_id=obj["game_id"], verified_assumptions=va,
            challenged_assumption=obj.get("challenged_assumption", ""),
            case_against=obj.get("case_against", ""),
            action=obj["action"], action_payload=obj.get("action_payload"),
            facts=facts, rankings=rankings,
            pitcher_attribution=obj.get("pitcher_attribution"),
            contribution_kind=obj.get("contribution_kind", "unset"),
            notes=obj.get("notes", ""))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ReportParseError(f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "")
            if s.strip()]


def _free_texts(finding) -> list:
    """(label, text) for every prose field the verifier also scans."""
    return aa._gather_free_text(finding)


def _asserted(sentence: str, pattern: str) -> bool:
    if _NEGATION_RE.search(sentence):
        return False
    return re.search(pattern, sentence, re.I | re.S) is not None


_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_GAME_ID = re.compile(r"\b[A-Za-z]{2,4}-[A-Za-z]{2,4}-\d{4}-\d{2}-\d{2}-\d+\b")
_LIST_MARK = re.compile(r"(?<![\w.])\d{1,2}\)")


def _visible_numbers(text: str, claim_ids) -> list:
    """Number literals of `text` with ONLY exact packet claim ids, ISO dates,
    game ids and list markers removed. The verifier strips anything shaped
    like `word:anything`, which lets `p:0.62` hide a number; this does not."""
    t = text or ""
    for cid in sorted(claim_ids, key=len, reverse=True):
        t = t.replace(cid, " ")
    t = _GAME_ID.sub(" ", t)
    t = _ISO_DATE.sub(" ", t)
    t = _LIST_MARK.sub(" ", t)
    return aa._NUMBER_RE.findall(t)


def _num(x) -> Optional[float]:
    if isinstance(x, bool) or x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _packet_numbers(packet) -> list:
    out = []
    rec = packet.recommendation
    for v in (rec.price, rec.our_probability, rec.market_probability):
        if _num(v) is not None:
            out.append(float(v))
    for c in packet.claims:
        for v in (c.data or {}).values():
            if _num(v) is not None:
                out.append(float(v))
        out.extend(float(n) for n in
                   _visible_numbers(c.text, [x.claim_id for x in packet.claims]))
    return out


def _implied(price: float) -> Optional[float]:
    if price == 0:
        return None
    return 100.0 / (price + 100.0) if price > 0 else -price / (-price + 100.0)


def _derivable_pool(packet) -> list:
    """Numbers a critic may legitimately STATE: every packet number, plus
    only these derivations (a wider net would let almost any decimal match
    some difference of some pair): the difference and sum of two headline
    numbers (the recommendation's price and probabilities and every market
    claim's price and implied probability), the difference between the two
    sides' values of the same field (home vs away ERA), the implied
    probability of any packet price, and a probability written as a
    percentage."""
    base = _packet_numbers(packet)
    pool = list(base)
    rec = packet.recommendation
    head = [float(v) for v in (rec.price, rec.our_probability,
                               rec.market_probability) if _num(v) is not None]
    prices = [float(rec.price)] if _num(rec.price) is not None else []
    for c in packet.claims:
        d = c.data or {}
        if c.claim_id.startswith("market:"):
            for k in ("best_price", "market_implied_probability"):
                if _num(d.get(k)) is not None:
                    head.append(float(d[k]))
            if _num(d.get("best_price")) is not None:
                prices.append(float(d["best_price"]))
    uniq = sorted(set(round(h, 6) for h in head))
    for i, a in enumerate(uniq):
        for b in uniq[i + 1:]:
            pool.extend((abs(a - b), a + b))
    groups = {}
    for c in packet.claims:
        for k, v in (c.data or {}).items():
            if _num(v) is not None:
                groups.setdefault(re.sub(r"^(home|away)_", "", k),
                                  set()).add(round(float(v), 6))
    for vals in groups.values():
        vs = sorted(vals)
        for i, a in enumerate(vs):
            for b in vs[i + 1:]:
                pool.append(abs(a - b))
    for p in prices:
        imp = _implied(p)
        if imp is not None:
            pool.append(imp)
    pool.extend(v * 100.0 for v in list(pool) if 0 < abs(v) <= 1)
    return pool


def _in_pool(literal: str, pool) -> bool:
    return aa._number_in_pool(literal, pool)


# ---------------------------------------------------------------------------
# Individual measures
# ---------------------------------------------------------------------------

def _verifier(packet, finding) -> dict:
    checks = []
    if finding.game_id != packet.game_id:
        checks.append({"check": "game_id_matches_packet", "result": "FAIL",
                       "detail": f"{finding.game_id!r} != {packet.game_id!r}"})
    try:
        rep = aa.verify_and_report(packet, finding)
    except Exception as exc:  # noqa: BLE001 -- a verifier crash is a failure
        checks.append({"check": "verifier_crashed", "result": "FAIL",
                       "detail": f"{type(exc).__name__}: {exc}"})
        rep = {"checks": [], "n_checks": 0}
    checks.extend(rep["checks"])
    failed = [c["check"] for c in checks if c["result"] == "FAIL"]
    return {"passes": not failed, "failed_checks": failed,
            "n_checks": len(checks)}


def _key_value_facts(key) -> dict:
    return {(f["claim_id"], f["field_path"]): f["value"]
            for f in key.get("facts", []) if f.get("type", "value") == "value"}


def _truth(packet, key_vals, claim_id, field_path):
    """(found, value). The key wins; the packet is the fallback."""
    if (claim_id, field_path) in key_vals:
        return True, key_vals[(claim_id, field_path)]
    for c in packet.claims:
        if c.claim_id == claim_id and field_path in (c.data or {}):
            return True, c.data[field_path]
    return False, None


def _ranking_class(rank: int, n: int) -> str:
    return "high" if rank == 1 else ("low" if rank == n else "mid")


def _factual(packet, key, finding) -> dict:
    wrong = []
    n_checked = 0
    key_vals = _key_value_facts(key)
    numbers = [n for c in packet.claims for n in
               [v for v in (c.data or {}).values() if _num(v) is not None]]
    for f in finding.facts:
        n_checked += 1
        found, truth = _truth(packet, key_vals, f.claim_id, f.field_path)
        if not found:
            wrong.append({"kind": "fact", "detail":
                          f"{f.claim_id}#{f.field_path} has no source value"})
        elif truth is None:
            wrong.append({"kind": "fact", "detail":
                          f"{f.claim_id}#{f.field_path} is absent in the "
                          f"source but stated as {f.value!r}"})
        elif not aa._numeric_equal(truth, f.value):
            wrong.append({"kind": "fact", "detail":
                          f"{f.claim_id}#{f.field_path} stated {f.value!r}, "
                          f"true value {truth!r}"})
    for r in finding.rankings:
        n_checked += 1
        values = [r.subject_value, *r.compared_values]
        bad = [v for v in values
               if not any(aa._numeric_equal(v, n) for n in numbers)]
        if bad:
            wrong.append({"kind": "ranking", "detail":
                          f"ranking {r.metric!r} uses value(s) {bad} that are "
                          "not numbers in the packet"})
        ordered = sorted(values, reverse=True)
        if ordered.index(r.subject_value) + 1 != r.claimed_rank:
            wrong.append({"kind": "ranking", "detail":
                          f"ranking {r.metric!r} claims rank {r.claimed_rank},"
                          f" recomputed {ordered.index(r.subject_value) + 1}"})
    wrong.extend(_payload_value_errors(packet, finding))
    wrong.extend(_prose_ranking_errors(packet, key, finding))
    if finding.pitcher_attribution:
        n_checked += 1
    return {"correct": not wrong, "n_checked": n_checked, "wrong": wrong}


def _payload_value_errors(packet, finding) -> list:
    """`CORRECT_INPUT.current_value` and string `verified_value` are values
    the existing verifier never resolves against anything."""
    if finding.action != "CORRECT_INPUT" or not isinstance(
            finding.action_payload, dict):
        return []
    p = finding.action_payload
    errs = []
    path = p.get("input_path")
    cur = p.get("current_value")
    holders = [c for c in packet.claims if path in (c.data or {})]
    if holders and cur is not None:
        have = holders[0].data[path]
        same = (aa._numeric_equal(have, cur) if _num(have) is not None
                else str(have).strip().lower() == str(cur).strip().lower())
        if not same:
            errs.append({"kind": "current_value", "detail":
                         f"CORRECT_INPUT.current_value {cur!r} but the model "
                         f"input {path!r} is {have!r}"})
    ver = p.get("verified_value")
    if ver is not None:
        cited = [c for c in packet.claims
                 if c.claim_id in (p.get("source_claim_ids") or [])]
        pool = []
        for c in cited:
            pool.extend((c.data or {}).values())
            pool.append(c.entity)
        ok = any((aa._numeric_equal(v, ver) if _num(v) is not None
                  and _num(ver) is not None
                  else str(v).strip().lower() == str(ver).strip().lower())
                 for v in pool if v is not None)
        if not ok:
            errs.append({"kind": "verified_value", "detail":
                         f"CORRECT_INPUT.verified_value {ver!r} is not a "
                         "value of any cited source claim"})
    return errs


def _prose_ranking_errors(packet, key, finding) -> list:
    errs = []
    claim_ids = [c.claim_id for c in packet.claims]
    for kf in key.get("facts", []):
        if kf.get("type") != "ranking":
            continue
        claim = next((c for c in packet.claims
                      if c.claim_id == kf["claim_id"]), None)
        if claim is None:
            continue
        subject = claim.data[kf["subject_field"]]
        cls = _ranking_class(kf["true_rank"], kf["n"])
        for label, text in _free_texts(finding):
            for s in _sentences(text):
                if not any(aa._number_in_pool(n, [subject])
                           for n in _visible_numbers(s, claim_ids)):
                    continue
                low, high = _LOW_WORDS.search(s), _HIGH_WORDS.search(s)
                if low and high:
                    continue
                if (cls == "high" and low) or (cls == "low" and high) or (
                        cls == "mid" and (low or high)
                        and re.search(r"\b(largest|smallest|highest|lowest)\b",
                                      s, re.I)):
                    errs.append({"kind": "prose_ranking", "detail":
                                 f"{label}: {s[:160]!r} mis-ranks {subject!r} "
                                 f"(true class: {cls})"})
    return errs


def _source(packet, finding) -> dict:
    ids = {c.claim_id for c in packet.claims}
    cited = []
    for _a, _v, i in finding.verified_assumptions:
        cited.extend(i)
    payload = finding.action_payload if isinstance(
        finding.action_payload, dict) else {}
    for k in ("source_claim_ids", "checked_claim_ids"):
        cited.extend(payload.get(k) or [])
    cited.extend(f.claim_id for f in finding.facts)
    if finding.pitcher_attribution:
        cited.append(finding.pitcher_attribution.get("identity_claim_id"))
    missing = sorted({c for c in cited if c not in ids})
    by_id = {c.claim_id: c for c in packet.claims}
    rec = packet.recommendation
    unsupported = []
    for idx, (a, v, i) in enumerate(finding.verified_assumptions):
        pool = [rec.price, rec.our_probability, rec.market_probability]
        for cid in i:
            c = by_id.get(cid)
            if c is None:
                continue
            pool.extend(x for x in (c.data or {}).values() if _num(x) is not None)
            pool.extend(float(n) for n in _visible_numbers(c.text, ids))
        for lit in _visible_numbers(f"{a} {v}", ids):
            if not _in_pool(lit, [p for p in pool if _num(p) is not None]):
                unsupported.append({"triple": idx, "number": lit})
    return {"correct": not missing and not unsupported,
            "citations": len(cited), "missing_ids": missing,
            "unsupported_number_citations": unsupported}


def _must_not_hits(key, finding) -> list:
    hits = []
    entries = [dict(e, source="key") for e in key.get("must_not_claim", [])]
    entries += [dict(e, source="generic") for e in GENERIC_MUST_NOT]
    # The first element of a verified_assumptions triple is the assumption
    # UNDER TEST ("the inputs are current"), not something the critic
    # asserts; only its verdict (element 1) is an assertion.
    texts = [(lab, t) for lab, t in _free_texts(finding)
             if not (lab.startswith("verified_assumptions[")
                     and lab.endswith("[0]"))]
    for e in entries:
        done = False
        st = e.get("structural") or {}
        attr = finding.pitcher_attribution or {}
        if st.get("attribution_name") and str(attr.get("name", "")).strip(
                ).lower() == st["attribution_name"].lower():
            hits.append({"statement": e["statement"], "how":
                         "pitcher_attribution names " + st["attribution_name"]})
            done = True
        if not done and st.get("action_in") and finding.action in st["action_in"]:
            hits.append({"statement": e["statement"],
                         "how": f"action {finding.action}"})
            done = True
        for label, text in ([] if done else texts):
            for s in _sentences(text):
                if any(_asserted(s, p) for p in e.get("patterns", [])):
                    hits.append({"statement": e["statement"],
                                 "how": f"{label}: {s[:160]}"})
                    done = True
                    break
            if done:
                break
    return hits


def _label_of(verdict: str) -> Optional[str]:
    head = (verdict or "").strip().upper()
    for label, syns in _LABEL_SYNONYMS.items():
        for syn in sorted(syns, key=len, reverse=True):
            if head.startswith(syn):
                return label
    return None


def _flags(key, finding, packet) -> dict:
    found, missed = [], []
    for entry in key.get("must_flag", []):
        want, targets = entry["flag"], set(entry["claim_ids"])
        ok = False
        for _a, verdict, cited in finding.verified_assumptions:
            if _label_of(verdict) == want and targets & set(cited):
                ok = True
        if not ok:
            for label, text in _free_texts(finding):
                if label.startswith("verified_assumptions"):
                    continue
                for s in _sentences(text):
                    words = [w for w in _LABEL_SYNONYMS[want]
                             if re.search(r"\b" + re.escape(w) + r"\b", s, re.I)]
                    if words and any(t in s for t in targets):
                        ok = True
        (found if ok else missed).append(
            {"flag": want, "claim_ids": entry["claim_ids"]})
    false_alarms = []
    if key.get("case_type") == "clean":
        for idx, (_a, verdict, cited) in enumerate(finding.verified_assumptions):
            lab = _label_of(verdict)
            if lab in DEFECT_LABELS:
                false_alarms.append({"triple": idx, "label": lab,
                                     "claim_ids": list(cited)})
    required = len(key.get("must_flag", []))
    return {"detected": not missed, "required": required, "found": found,
            "missed": missed, "false_alarms": false_alarms}


def _invented_numbers(packet, finding) -> dict:
    pool = _derivable_pool(packet)
    claim_ids = [c.claim_id for c in packet.claims]
    invented = []
    for label, text in _free_texts(finding):
        for s in _sentences(text):
            for lit in _visible_numbers(s, claim_ids):
                if _in_pool(lit, pool):
                    continue
                val = _num(lit)
                prob_like = "." in lit and val is not None and 0 < abs(val) < 1
                unit = re.search(re.escape(lit) + _EFFECT_UNIT_RE, s, re.I)
                if prob_like or unit:
                    invented.append({"number": lit, "where": label,
                                     "sentence": s[:160]})
    return {"invented": bool(invented), "numbers": invented}


def score_finding(packet, key, finding, *, report_label: str = "") -> dict:
    """Score a parsed finding against one case."""
    ver = _verifier(packet, finding)
    fact = _factual(packet, key, finding)
    src = _source(packet, finding)
    hits = _must_not_hits(key, finding)
    flg = _flags(key, finding, packet)
    inv = _invented_numbers(packet, finding)
    components = {
        "must_not_claim_asserted": len(hits),
        "wrong_facts_or_rankings": len(fact["wrong"]),
        "unsupported_citations": len(src["missing_ids"])
        + len(src["unsupported_number_citations"]),
        "invented_numerical_effects": len(inv["numbers"]),
        "false_alarm_labels": len(flg["false_alarms"]),
    }
    asked = finding.action in ("CORRECT_INPUT", "RECALCULATE")
    justified = bool(key.get("recalculation_justified"))
    acceptable = key.get("acceptable_actions") or [key["correct_action"]]
    return {
        "case_id": key["case_id"], "case_type": key["case_type"],
        "report": report_label, "parsed": True,
        "verifier": ver,
        "factual_correctness": fact,
        "source_correctness": src,
        "unsupported_claims": {"count": sum(components.values()),
                               "components": components, "items": hits},
        "flags_detected": flg,
        "correct_action": {"action": finding.action,
                           "expected": key["correct_action"],
                           "correct": finding.action == key["correct_action"],
                           "acceptable": finding.action in acceptable},
        "recalculation": {"asked": asked, "justified": justified,
                          "ok": (not asked) or justified},
        "invented_numerical_effect": inv,
    }


def _unparsed(key, label, err) -> dict:
    return {"case_id": key["case_id"], "case_type": key["case_type"],
            "report": label, "parsed": False, "parse_error": err,
            "verifier": {"passes": False, "failed_checks": ["parse"],
                         "n_checks": 0},
            "factual_correctness": {"correct": False, "n_checked": 0,
                                    "wrong": []},
            "source_correctness": {"correct": False, "citations": 0,
                                   "missing_ids": [],
                                   "unsupported_number_citations": []},
            "unsupported_claims": {"count": 0, "components": {}, "items": []},
            "flags_detected": {"detected": False,
                               "required": len(key.get("must_flag", [])),
                               "found": [], "missed": key.get("must_flag", []),
                               "false_alarms": []},
            "correct_action": {"action": None, "expected":
                               key["correct_action"], "correct": False,
                               "acceptable": False},
            "recalculation": {"asked": False, "justified":
                              bool(key.get("recalculation_justified")),
                              "ok": True},
            "invented_numerical_effect": {"invented": False, "numbers": []}}


def score_report_file(report_path: str, case_dir: str) -> dict:
    packet, key = load_case(case_dir)
    try:
        finding = parse_report(_load_json(report_path))
    except (ReportParseError, json.JSONDecodeError, OSError) as exc:
        return _unparsed(key, report_path, f"{type(exc).__name__}: {exc}")
    return score_finding(packet, key, finding, report_label=report_path)


# ---------------------------------------------------------------------------
# Arms A and B
# ---------------------------------------------------------------------------

def arm_a(packet, key) -> dict:
    """MODEL ONLY: always no adjustment, states nothing."""
    return {"action": "NO_ADJUSTMENT", "stated_claims": 0}


def _kind(claim_id: str) -> str:
    return claim_id.split(":", 1)[0]


def _side_of(claim_id: str) -> Optional[str]:
    parts = claim_id.split(":")
    return parts[2] if len(parts) > 2 and parts[2] in ("home", "away") else None


def arm_b(packet) -> dict:
    """MODEL + VERIFIED INFORMATION, deterministic and model-free. Returns a
    reply dict (CriticFinding fields) built by rules, plus nothing else, so
    the scorer treats it exactly like a critic's reply."""
    gid = packet.game_id
    rec = packet.recommendation
    claims = list(packet.claims)
    flags = []          # (label, [claim ids], reason)
    correction = None   # (side, model claim, probable claim, assumed id)
    conflicted = set()

    id_kinds = AUTHORITATIVE_FOR["starter_identity"]
    for side in ("home", "away"):
        probs = [c for c in claims
                 if _kind(c.claim_id) in id_kinds and _side_of(c.claim_id) == side]
        confirmed = [c for c in probs if c.status == "CONFIRMED"
                     and (c.data or {}).get("probable_id") is not None]
        for c in probs:
            if c not in confirmed:
                flags.append(("MISSING", [c.claim_id],
                              "no probable starter is listed for this side"))
        pids = {c.data["probable_id"] for c in confirmed}
        if len(pids) > 1:
            conflicted.add(side)
            flags.append(("UNVERIFIED", [c.claim_id for c in confirmed],
                          "two authoritative sources name different starters "
                          "for this side and neither outranks the other"))
        elif len(pids) == 1:
            mi = next((c for c in claims
                       if c.claim_id == f"model_input:{gid}:{side}_sp_known"),
                      None)
            assumed = (mi.data or {}).get(f"{side}_sp_assumed_id") if mi else None
            if assumed is not None and assumed != next(iter(pids)):
                correction = (side, mi, confirmed[0], assumed)

    for c in claims:
        if _kind(c.claim_id) == "pitcher_log":
            behind = (c.data or {}).get("log_through_days_before_game")
            if _num(behind) is not None and behind > CURRENT_INPUT_DAYS:
                flags.append(("STALE", [c.claim_id],
                              "the pitcher log is older than the currency "
                              "limit for a model input"))

    for side in ("home", "away"):
        mi = next((c for c in claims
                   if c.claim_id == f"model_input:{gid}:{side}_sp_known"), None)
        if mi is None:
            continue
        d = mi.data or {}
        if not d.get(f"{side}_sp_known") or d.get(f"{side}_sp_era") is None:
            flags.append(("MISSING", [mi.claim_id],
                          "the starter figures for this side are absent from "
                          "the model input"))

    better = None
    price_kinds = AUTHORITATIVE_FOR["price"]
    for c in claims:
        if (_kind(c.claim_id) in price_kinds
                and c.claim_id.startswith(f"market:{gid}:{rec.side}")
                and _num((c.data or {}).get("best_price")) is not None
                and c.data["best_price"] > rec.price):
            if better is None or c.data["best_price"] > better.data["best_price"]:
                better = c

    all_ids = [c.claim_id for c in claims]
    facts = ()
    if correction and correction[0] not in conflicted:
        side, mi, pc, assumed = correction
        action = "CORRECT_INPUT"
        payload = {"input_path": f"{side}_sp_assumed_id",
                   "current_value": assumed,
                   "verified_value": pc.data["probable_id"],
                   "source_claim_ids": [pc.claim_id, mi.claim_id]}
        facts = (aa.Fact(pc.claim_id, "probable_id", pc.data["probable_id"]),)
        flags.append(("CONTRADICTED", [mi.claim_id, pc.claim_id],
                      "the starter the model assumed differs from the "
                      "schedule feed"))
        case_against = ("The model's starter assumption conflicts with the "
                        "schedule feed's probable starter for the same side.")
    elif better is not None:
        action = "COMPARE_MARKET"
        payload = {"market": rec.market,
                   "reason": (f"the same side of the same market is quoted at "
                              f"a better price, {int(better.data['best_price'])} "
                              f"against {int(rec.price)}"),
                   "source_claim_ids": [better.claim_id]}
        facts = (aa.Fact(better.claim_id, "best_price",
                         better.data["best_price"]),)
        case_against = ("A better price for the same bet exists in the "
                        "packet; this is a price improvement, not a change to "
                        "the model probability.")
    else:
        action = "NO_ADJUSTMENT"
        payload = {"checked_claim_ids": all_ids}
        case_against = ("The rule-based checks found no sourced fact that "
                        "contradicts the model's inputs or the quoted price.")

    triples = [(f"{lab.lower()} check on the cited claims",
                f"{lab} -- {why}.", list(ids)) for lab, ids, why in flags]
    return {
        "game_id": gid,
        "verified_assumptions": [list(t) for t in triples],
        "challenged_assumption": ("Starter identity, input currency and "
                                  "completeness, and the quoted price."),
        "case_against": case_against,
        "action": action, "action_payload": payload,
        "facts": [{"claim_id": f.claim_id, "field_path": f.field_path,
                   "value": f.value} for f in facts],
        "rankings": [], "pitcher_attribution": None,
        "notes": "Deterministic rule-based review; no language model.",
    }


# ---------------------------------------------------------------------------
# Batch: score-all and compare
# ---------------------------------------------------------------------------

def _report_for(reports_dir: str, case_dir: str) -> Optional[str]:
    name = os.path.basename(case_dir)
    exact = os.path.join(reports_dir, name + ".json")
    if os.path.isfile(exact):
        return exact
    for f in sorted(os.listdir(reports_dir)) if os.path.isdir(reports_dir) else []:
        if f.startswith(name) and f.endswith(".json"):
            return os.path.join(reports_dir, f)
    return None


def score_all(reports_dir: str, cases_dir: str = BENCH_DIR) -> list:
    out = []
    for cd in case_dirs(cases_dir):
        rp = _report_for(reports_dir, cd)
        if rp is None:
            _p, key = load_case(cd)
            row = _unparsed(key, None, "no report file for this case")
            row["parsed"] = False
            out.append(row)
        else:
            out.append(score_report_file(rp, cd))
    return out


def _yn(b) -> str:
    return "yes" if b else "no"


def markdown_table(rows: list) -> str:
    head = ("| case | verifier | facts | sources | unsupported | flags | "
            "action | recalc ok | invented number |\n"
            "|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for r in rows:
        if not r["parsed"]:
            lines.append(f"| {r['case_id']} | no report ({r['parse_error']}) "
                         "| | | | | | | |")
            continue
        v = r["verifier"]
        vs = "pass" if v["passes"] else "FAIL: " + ",".join(
            v["failed_checks"])[:60]
        fl = r["flags_detected"]
        fls = ("n/a" if not fl["required"] else
               f"{len(fl['found'])}/{fl['required']}")
        if fl["false_alarms"]:
            fls += f" +{len(fl['false_alarms'])} false alarm"
        a = r["correct_action"]
        lines.append(
            f"| {r['case_id']} | {vs} | "
            f"{_yn(r['factual_correctness']['correct'])} | "
            f"{_yn(r['source_correctness']['correct'])} | "
            f"{r['unsupported_claims']['count']} | {fls} | "
            f"{a['action']} ({'ok' if a['correct'] else 'want ' + a['expected']})"
            f" | {_yn(r['recalculation']['ok'])} | "
            f"{_yn(r['invented_numerical_effect']['invented'])} |")
    return "\n".join(lines)


def _flags_ok(row) -> bool:
    return row["flags_detected"]["detected"]


def compare(cases_dir: str = BENCH_DIR, reports_dir: Optional[str] = None
            ) -> dict:
    """Arms A, B and (when replies exist) C, per case. A and B are
    reproducible from the frozen cases alone."""
    rows = []
    c_present = False
    for cd in case_dirs(cases_dir):
        packet, key = load_case(cd)
        a = arm_a(packet, key)
        a_row = {
            "action": a["action"],
            "correct_action": a["action"] == key["correct_action"],
            "flags_detected": not key.get("must_flag"),
            "unsupported_claims": 0,
            "verifier_passes": None,
        }
        b_reply = arm_b(packet)
        b_score = score_finding(packet, key, parse_report(b_reply),
                                report_label="arm_b")
        b_row = {
            "action": b_score["correct_action"]["action"],
            "correct_action": b_score["correct_action"]["correct"],
            "flags_detected": b_score["flags_detected"]["detected"],
            "unsupported_claims": b_score["unsupported_claims"]["count"],
            "verifier_passes": b_score["verifier"]["passes"],
        }
        c_row = None
        if reports_dir:
            rp = _report_for(reports_dir, cd)
            if rp is not None:
                c_present = True
                s = score_report_file(rp, cd)
                c_row = {
                    "action": s["correct_action"]["action"],
                    "correct_action": s["correct_action"]["correct"],
                    "flags_detected": s["flags_detected"]["detected"],
                    "unsupported_claims": s["unsupported_claims"]["count"],
                    "verifier_passes": s["verifier"]["passes"],
                }
        rows.append({"case_id": key["case_id"], "case_type": key["case_type"],
                     "expected_action": key["correct_action"],
                     "A": a_row, "B": b_row, "C": c_row})
    return {"rows": rows, "c_status": "scored" if c_present else "pending"}


def _arm_totals(rows, arm) -> Optional[dict]:
    cells = [r[arm] for r in rows]
    if any(c is None for c in cells):
        return None
    n = len(cells)
    return {"n": n,
            "correct_action": sum(c["correct_action"] for c in cells),
            "flags_detected": sum(c["flags_detected"] for c in cells),
            "unsupported_claims": sum(c["unsupported_claims"] for c in cells),
            "fully_correct": sum(
                c["correct_action"] and c["flags_detected"]
                and c["unsupported_claims"] == 0
                and c["verifier_passes"] is not False for c in cells)}


def compare_markdown(result: dict) -> str:
    rows = result["rows"]

    def cell(c):
        if c is None:
            return "pending"
        return (f"{'ok' if c['correct_action'] else 'WRONG'} {c['action']}"
                f" / flags {'ok' if c['flags_detected'] else 'MISSED'}"
                f" / unsupported {c['unsupported_claims']}")

    lines = ["| case | expected | A model only | B model + verified info | "
             "C model + info + critic |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['case_id']} | {r['expected_action']} | "
                     f"{cell(r['A'])} | {cell(r['B'])} | {cell(r['C'])} |")
    lines.append("")
    for arm, name in (("A", "A model only"), ("B", "B model + verified info"),
                      ("C", "C model + info + critic")):
        t = _arm_totals(rows, arm)
        if t is None:
            lines.append(f"- {name}: pending (no critic replies scored yet; "
                         "give `compare --reports-dir DIR` a directory of "
                         "`<case_id>.json` replies)")
        else:
            lines.append(
                f"- {name}: correct action {t['correct_action']}/{t['n']}, "
                f"flags detected {t['flags_detected']}/{t['n']}, "
                f"unsupported claims {t['unsupported_claims']}, "
                f"fully correct {t['fully_correct']}/{t['n']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="score one reply against one case")
    s.add_argument("report")
    s.add_argument("--case", required=True, help="a case directory")

    sa = sub.add_parser("score-all", help="score a directory of replies")
    sa.add_argument("reports_dir")
    sa.add_argument("--cases-dir", default=BENCH_DIR)
    sa.add_argument("--out-dir", help="also write <case>.score.json + scores.md")
    sa.add_argument("--json", action="store_true",
                    help="print the JSON array after the table")

    c = sub.add_parser("compare", help="arms A, B and (if present) C")
    c.add_argument("--cases-dir", default=BENCH_DIR)
    c.add_argument("--reports-dir")
    c.add_argument("--json", action="store_true")

    b = sub.add_parser("arm-b", help="print arm B's rule-built reply for a case")
    b.add_argument("--case", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "score":
        print(json.dumps(score_report_file(args.report, args.case), indent=2))
        return 0
    if args.cmd == "score-all":
        rows = score_all(args.reports_dir, args.cases_dir)
        table = markdown_table(rows)
        print(table)
        if args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            for r in rows:
                with open(os.path.join(args.out_dir,
                                       r["case_id"] + ".score.json"), "w",
                          encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps(r, indent=2) + "\n")
            with open(os.path.join(args.out_dir, "scores.md"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write(table + "\n")
        if args.json:
            print(json.dumps(rows, indent=2))
        return 0
    if args.cmd == "compare":
        res = compare(args.cases_dir, args.reports_dir)
        print(compare_markdown(res))
        if res["c_status"] == "pending":
            print("\nArm C is pending: no critic replies were found"
                  + (f" in {args.reports_dir}" if args.reports_dir else
                     " (no --reports-dir given)") + ".")
        if args.json:
            print(json.dumps(res, indent=2))
        return 0
    if args.cmd == "arm-b":
        packet, _key = load_case(args.case)
        print(json.dumps(arm_b(packet), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
