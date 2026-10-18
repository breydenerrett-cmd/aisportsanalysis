"""Check one stage's answer: the shape, code's risk rules, and the analyst's own checker.

Every answer the desk collects goes through `src/analyst/critic.py`, unchanged:

* a REPORT (analyst, bull, bear): each finding is checked exactly as the analyst checks a reason
  (`critic._check_reason`: every evidence path resolves and matches, every number in the claim is a packet
  number or a declared calculation the checker recomputes, every name is in the packet, banned words
  struck), and the report text is held to the same number, name and word rules. A struck finding or a
  withheld text is a REJECTION: the writer may answer again (the publication rule).
* a DECISION (desk head, persona): shape first, then the code risk manager (`risk.assess`, R1 to R5, which
  strikes without asking again), then `critic.verify` over the TAKEs code allowed, converted to the analyst's
  call shape so the checker is not re-implemented. A TAKE the checker strikes, or a summary it withholds, is a
  REJECTION.

The result is a `pilot.CheckReport`, the structure the analyst pilot's attempt record already stores, so
`pilot.record_attempt` and `pilot.publication_refusal` are used as they are and the rule cannot differ
between the pilot and the desk.

FOOTBALL: a football packet is checked with the football checker (`nfl_analyst.verify`, and its number-line
rule over every sentence). Baseball uses `critic.verify`.

Pure apart from the analyst's own modules: no I/O, no clock, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from src.analyst import critic, nfl_analyst, pilot
from src.core import odds as odds_math
from src.hounds.desk import risk, roles, schemas


def _sport_tools(packet: Mapping) -> tuple:
    """`(known_names, text_check)` for the packet's sport: baseball's defaults, or football's name
    vocabulary and number-line rule."""
    if risk.sport_of(packet) == "nfl":
        return (nfl_analyst.known_names(packet),
                lambda where, text: nfl_analyst.line_problems(packet, text, where))
    return critic.KnownNames.build(packet), None


def _verify(packet: Mapping, output: Mapping, extra_numbers: Sequence[float]) -> "critic.Verified":
    """`critic.verify` for the packet's sport. Football is `nfl_analyst.verify` with one addition,
    `extra_numbers` (the numbers the writer itself stated, which `nfl_analyst.verify` has no way to take):
    the same call it makes, the same name vocabulary, the same number-line rule and the same added
    selection problems."""
    known, text_check = _sport_tools(packet)
    result = critic.verify(packet, output, known=known, text_check=text_check,
                           extra_numbers=list(extra_numbers))
    if risk.sport_of(packet) == "nfl":
        for entry in result.struck:
            extra = nfl_analyst.selection_problems(packet, entry["original"])
            entry["problems"] = list(entry["problems"]) + [p for p in extra if p not in entry["problems"]]
    return result


@dataclass
class StageCheck:
    """A stage answer's check: the pilot-shaped report plus what only the desk needs."""
    report: pilot.CheckReport
    material: Optional[dict] = None          # report stages: what a later stage may be shown
    risk_kept: list = field(default_factory=list)      # decision stages: [risk.Taken] the checker kept
    risk_struck: list = field(default_factory=list)    # [risk.Struck]
    critic_struck: list = field(default_factory=list)  # [{"slot_id", "problems"}]
    summary_status: Optional[str] = None
    summary: Optional[str] = None


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def _prose_problems(packet: Mapping, text: Any, derived: Any, where: str, pool: "critic.NumberPool",
                    known: "critic.KnownNames", text_check: Optional[Callable]) -> list:
    problems: list = []
    verified, d_problems = critic.verify_derivations(packet, derived, f"{where}'s derived")
    problems.extend(d_problems)
    scoped = pool.with_derived(verified)
    for lit in critic.unsupported_numbers(text, scoped):
        problems.append(f"{where} quotes {lit}, which is not a number in the packet")
    for word in critic.banned_words(text, internal=True):
        problems.append(f"{where} uses the banned word {word!r}")
    for run in critic.unsupported_names(text, known):
        problems.append(f"{where} names {run!r}, which is not a name in the packet")
    if text_check is not None:
        problems.extend(text_check(where, text))
    return problems


def check_report(packet: Mapping, response: Mapping, role: "roles.Role") -> StageCheck:
    shape = schemas.report_shape_errors(response, packet, role.words)
    if shape:
        return StageCheck(report=pilot.CheckReport(shape_errors=shape))
    known, text_check = _sport_tools(packet)
    pool = critic.NumberPool.base(packet)
    calls, kept_findings = [], []
    for i, finding in enumerate(response["findings"], 1):
        problems: list = []
        critic._check_reason(packet, f"finding {i}", finding, pool, known, problems, required=True, used=[])
        if text_check is not None and isinstance(finding.get("claim"), str):
            problems.extend(text_check(f"finding {i}", finding["claim"]))
        calls.append(pilot.CallReport(slot_id=f"finding_{i}", verdict="FINDING",
                                      selection=str(finding.get("claim"))[:70], kept=not problems,
                                      problems=problems))
        if not problems:
            kept_findings.append({"claim": finding["claim"], "evidence": finding["evidence"]})
    text_problems = _prose_problems(packet, response["text"], response.get("text_derived"), "the text", pool,
                                    known, text_check)
    status = "withheld" if text_problems else "ok"
    report = pilot.CheckReport(shape_errors=[], calls=calls, summary_status=status,
                               summary_problems=text_problems)
    material = {"stage": role.stage, "title": role.title,
                "text": response["text"] if status == "ok" else None,
                "text_withheld": status != "ok",
                "findings": kept_findings,
                "findings_struck": sum(1 for c in calls if not c.kept),
                "focus": [dict(f) for f in response["focus"]]}
    return StageCheck(report=report, material=material, summary_status=status,
                      summary=response["text"] if status == "ok" else None)


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------

def _as_call(packet: Mapping, taken: "risk.Taken") -> dict:
    """A risk-approved TAKE in the analyst's call shape, so `critic.verify` can check it unchanged.
    The verdict is derived (the lean is TAKE, the other side TAKE_OTHER_SIDE), and `pass_price` is the
    break-even price of the model's own probability, computed here so the call is internally consistent:
    the checker's contradiction rule is then about the model's price and probability, not about a rounding
    the model was never asked for."""
    d = taken.decision
    market = packet["markets"][taken.slot_id]
    verdict = "TAKE" if taken.selection == market["lean"] else "TAKE_OTHER_SIDE"
    pass_price = int(round(odds_math.probability_to_american(taken.probability)))
    return {"slot_id": taken.slot_id, "market": market["market"], "selection": taken.selection,
            "verdict": verdict, "price": taken.price_best, "book": taken.book,
            "fair_estimate": taken.probability, "confidence": "medium", "reasons": d["reasons"],
            "pass_price": pass_price, "what_would_change_it": d["what_would_change_it"],
            "case_against": d["case_against"]}


def check_decision(packet: Mapping, response: Mapping, role: "roles.Role") -> StageCheck:
    shape = schemas.decision_shape_errors(response, packet, role.words)
    if shape:
        return StageCheck(report=pilot.CheckReport(shape_errors=shape))
    persona = risk.PERSONA_OF_STAGE.get(role.stage)
    assessed = risk.assess(packet, response["decisions"], persona)
    calls_in = [_as_call(packet, t) for t in assessed.kept]
    # The summary may quote the model's own stated numbers even for a TAKE code struck, so a code strike
    # is never turned into a checker rejection through the summary.
    stated = [d.get("probability") for d in response["decisions"]] + \
             [d.get("price") for d in response["decisions"]]
    stated = [v for v in stated if isinstance(v, (int, float)) and not isinstance(v, bool)]
    verified = _verify(packet, {"summary": response["summary"],
                                "summary_derived": response.get("summary_derived"), "calls": calls_in},
                       stated)
    struck = {s["slot_id"]: s["problems"] for s in verified.struck}
    report = pilot.CheckReport(shape_errors=[], summary_status=verified.summary_status,
                               summary_problems=list(verified.summary_problems), verified=verified)
    for call in calls_in:
        sid = call["slot_id"]
        report.calls.append(pilot.CallReport(slot_id=sid, verdict=call["verdict"],
                                             selection=str(call["selection"]), kept=sid not in struck,
                                             problems=list(struck.get(sid, []))))
    kept = [t for t in assessed.kept if t.slot_id not in struck]
    return StageCheck(report=report, risk_kept=kept, risk_struck=list(assessed.struck),
                      critic_struck=[{"slot_id": k, "problems": v} for k, v in struck.items()],
                      summary_status=verified.summary_status, summary=verified.summary)


def check_stage(packet: Mapping, response: Any, role: "roles.Role") -> StageCheck:
    if not isinstance(response, Mapping):
        return StageCheck(report=pilot.CheckReport(shape_errors=["the answer is not a JSON object"]))
    if role.kind == roles.KIND_REPORT:
        return check_report(packet, response, role)
    return check_decision(packet, response, role)


# ---------------------------------------------------------------------------
# printing
# ---------------------------------------------------------------------------

def print_check(check: StageCheck, out: Callable) -> None:
    """What the pilot prints, plus the code risk manager's strikes (which do not earn a new answer)."""
    pilot.print_report(check.report, out)
    for s in check.risk_struck:
        out(f"  code risk {s.rule} struck {s.slot_id}: {s.reason}")
