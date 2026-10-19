"""The coach report card's ledger: what the coach suggested, what was refused, and the grades.

WHY A SECOND LEDGER. The pre-registered loop (``src/hounds/learning``, docs/PREREG_LEARNING_LOOP.md) lets a
coach proposal become a challenger only after the hound has 50 graded FORWARD bets, and the referee looks only
after 100 paired games. Forward recording began 2026-10-18, so for weeks no proposal can reach it and nothing
visible happens. The owner's ask (2026-10-18): grade the coach's suggestions anyway and see whether the coach is
coaching. This ledger is that practice lane (docs/COACH_REPORT_CARD.md). It never feeds the referee, never
changes a hound and shares no file with the pre-registered loop.

ROWS (one hash-chained JSONL file, ``evidence/hounds_coach_v1.jsonl``, ``src.ledger.chain.HashChainLedger``)

  coach_suggestion         a valid suggestion: issue number, hound, champion values, suggested values, the
                           plain-English change list (labels frozen at record time), hypothesis, evidence,
                           ``mode`` ("challenger" when the pre-registered guards also took it, else
                           "practice"), ``recorded_utc``
  coach_refused            an issue that was not a valid suggestion, with the reason. Bad coaching counts
                           against the coach, so the report card counts these
  coach_graded_hindsight   the 30 days BEFORE the suggestion, both value sets, settled. Labelled hindsight
  coach_graded_forward     the live shadow comparison from the recorded time on; a new row when the numbers
                           move, the newest row per issue wins
  fan_tip                  a fan's tip (the "fan" lane, below): the same fields as a suggestion, ``mode``
                           "fan", the tip's id and nickname, never a challenger
  fan_tip_count            the same tip sent again the same UTC day: the first row's ``count`` goes up by one
                           (the chain is append-only, so the count is a row of its own, not an edit)

THE FAN LANE. A fan tip (the tip box on a dog's page) is graded exactly like a coach
suggestion, by the same code, and published beside it, never mixed into the coach's own numbers. Its rows reuse
the ``issue`` field as a SYNTHETIC KEY (``FAN_KEY_BASE`` plus a running number) so ``coach_grade`` can store its
hindsight and forward rows under the same ``issue`` and the grading code needs no second path. The key is far
above any GitHub issue number, so the two never meet. A fan tip is never offered to ``propose_pack``: the
only way a dog changes is still the referee.

An issue number appears at most once among suggestions and refusals: that is the dedupe the public-issues
reader depends on (it sees every issue, closed or not, every run).

Stdlib plus the repo's own chain. Nothing here reads a store of odds or results; ``coach_grade`` does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from src.ledger.chain import HashChainLedger

LEDGER_NAME = "hounds_coach_v1.jsonl"
SHADOW_NAME = "hounds_coach_shadow_v1.jsonl"

K_SUGGESTION = "coach_suggestion"
K_REFUSED = "coach_refused"
K_HINDSIGHT = "coach_graded_hindsight"
K_FORWARD = "coach_graded_forward"
K_FAN_TIP = "fan_tip"
K_FAN_COUNT = "fan_tip_count"

MODE_CHALLENGER = "challenger"
MODE_PRACTICE = "practice"
MODE_FAN = "fan"

# A fan tip's key in the ``issue`` field. GitHub issue numbers are a few hundred at most; a billion leaves the
# two ranges apart forever, and the running number is read off the ledger so it is stable and never reused.
FAN_KEY_BASE = 1_000_000_000

# Intake limits for fans, on top of the tip box's own (3 a day per caller, 60 a day for the site): the grading
# job runs two shadow hounds per followed tip, so what it takes in is capped where it is recorded. Counted by
# the day the fan SENT the tip, first come first served, so a re-run on another day records the same tips.
FAN_PER_UTC_DAY = 20
FAN_SAME_VALUES_PER_DAY = 1      # one row per (hound, values) a day; repeats raise the first row's count

LEDGER_VERSION = 1

# Practice-lane rate limits (owner brief 2026-10-18). A coach that files five issues in a day must not
# bury the report card or the compute budget; extras are refused with a code that says why.
PRACTICE_PER_HOUND_DAYS = 3
PRACTICE_PER_UTC_DAY = 3
REASON_TOO_SOON = "too_soon_practice"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        out = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Paths:
    """Where the two files live. Tests build one over a temp directory."""
    ledger: Path
    shadow: Path

    @staticmethod
    def default(root: Optional[Path] = None) -> "Paths":
        if root is not None:
            return Paths(Path(root) / LEDGER_NAME, Path(root) / SHADOW_NAME)
        from src.paths import evidence_path
        return Paths(Path(evidence_path(LEDGER_NAME)), Path(evidence_path(SHADOW_NAME)))


def chain(paths: Paths) -> HashChainLedger:
    return HashChainLedger(paths.ledger)


def append(paths: Paths, kind: str, *, now: Optional[datetime] = None, **fields) -> dict:
    row = {"kind": kind, "ledger_version": LEDGER_VERSION, "utc": iso(now or utc_now()), "paper_only": True}
    row.update(fields)
    return chain(paths).append(row)


def read_rows(paths: Paths) -> list:
    if not paths.ledger.exists():
        return []
    return chain(paths).read()


@dataclass
class Card:
    """The ledger folded: newest row wins per issue for the two grades."""
    suggestions: dict = field(default_factory=dict)      # issue -> row
    refused: dict = field(default_factory=dict)          # issue -> row
    hindsight: dict = field(default_factory=dict)        # issue -> row
    forward: dict = field(default_factory=dict)          # issue -> newest row
    last_utc: Optional[str] = None                       # newest row of any kind
    fans: dict = field(default_factory=dict)             # fan key -> fan_tip row (the fan lane)
    fan_counts: dict = field(default_factory=dict)       # fan key -> how many fans sent that tip (>= 1)
    fan_tip_ids: set = field(default_factory=set)        # every tip id recorded, a repeat's too
    fan_dup_of: dict = field(default_factory=dict)       # a repeat's tip id -> the key of the first row
    fan_last_tip_utc: Optional[str] = None               # newest ``tip_created_utc`` among fan rows
    first_helped: dict = field(default_factory=dict)     # key -> the first forward row that said HELPED

    def seen(self, issue: int) -> bool:
        return issue in self.suggestions or issue in self.refused

    def gradable(self) -> dict:
        """Every row the grading job follows: the coach's suggestions and the fans' tips, by ``issue`` key."""
        return {**self.suggestions, **self.fans}

    def fan_key_for(self, tip_id: str) -> Optional[int]:
        """The key of the row a tip id was recorded under (its own, or the first row it repeats)."""
        for key, row in self.fans.items():
            if row.get("tip_id") == tip_id:
                return key
        return self.fan_dup_of.get(tip_id)

    def outcome_of(self, issue: int) -> Optional[Mapping]:
        return self.suggestions.get(issue) or self.refused.get(issue)


def fold(rows) -> Card:
    card = Card()
    for r in rows:
        kind, issue = r.get("kind"), r.get("issue")
        if kind not in (K_SUGGESTION, K_REFUSED, K_HINDSIGHT, K_FORWARD, K_FAN_TIP, K_FAN_COUNT) \
                or not isinstance(issue, int) or isinstance(issue, bool):
            continue
        if kind in (K_FAN_TIP, K_FAN_COUNT):
            _fold_fan(card, kind, issue, r)
        elif kind == K_SUGGESTION:
            card.suggestions.setdefault(issue, r)
        elif kind == K_REFUSED:
            card.refused.setdefault(issue, r)
        elif kind == K_HINDSIGHT:
            card.hindsight[issue] = r
        else:
            card.forward[issue] = r
            if r.get("label") == "HELPED" and issue not in card.first_helped:
                card.first_helped[issue] = r
        # last_utc is the COACH's last change (it dates the daily "report card" kennel item); a fan's row, and
        # the grades of a fan's tip, must not make the coach's card look changed
        if issue < FAN_KEY_BASE and isinstance(r.get("utc"), str) \
                and (card.last_utc is None or r["utc"] > card.last_utc):
            card.last_utc = r["utc"]
    return card


def _fold_fan(card: Card, kind: str, key: int, r: Mapping) -> None:
    tip_id = r.get("tip_id")
    if isinstance(tip_id, str):
        card.fan_tip_ids.add(tip_id)
    made = r.get("tip_created_utc")
    if isinstance(made, str) and (card.fan_last_tip_utc is None or made > card.fan_last_tip_utc):
        card.fan_last_tip_utc = made
    if kind == K_FAN_TIP:
        if key not in card.fans:
            card.fans[key] = r
            card.fan_counts[key] = card.fan_counts.get(key, 0) + 1
    else:
        if isinstance(tip_id, str):
            card.fan_dup_of.setdefault(tip_id, key)
        card.fan_counts[key] = card.fan_counts.get(key, 0) + 1


def load(paths: Paths) -> Card:
    return fold(read_rows(paths))


# ---- rate limit --------------------------------------------------------------------------------------------

def rate_limit_reason(card: Card, hound_id: str, now: datetime) -> Optional[str]:
    """``too_soon_practice`` when recording one more suggestion would break the practice limits: the same
    hound within ``PRACTICE_PER_HOUND_DAYS`` days of its last suggestion, or ``PRACTICE_PER_UTC_DAY`` already
    recorded on this UTC day. Counts every recorded suggestion (a challenger-mode one is also a practice
    row), by the time it was recorded."""
    window = timedelta(days=PRACTICE_PER_HOUND_DAYS)
    today = iso(now)[:10]
    on_day = 0
    for r in card.suggestions.values():
        when = parse(r.get("recorded_utc"))
        if when is None:
            continue
        if r.get("hound") == hound_id and timedelta(0) <= now - when < window:
            return f"{REASON_TOO_SOON}: one practice suggestion per hound per {PRACTICE_PER_HOUND_DAYS} days"
        if iso(when)[:10] == today:
            on_day += 1
    if on_day >= PRACTICE_PER_UTC_DAY:
        return f"{REASON_TOO_SOON}: at most {PRACTICE_PER_UTC_DAY} practice suggestions per UTC day"
    return None


# ---- the fan lane -------------------------------------------------------------------------------------------

def next_fan_key(card: Card) -> int:
    return max([FAN_KEY_BASE, *card.fans]) + 1


def values_signature(values: Mapping) -> str:
    """A tip's knob values as one comparable string (rounded, so 0.04 and 0.0400000001 are the same tip)."""
    return ",".join(f"{k}={round(float(values[k]), 6):g}" for k in sorted(values))


def fan_day(row: Mapping) -> Optional[str]:
    """The UTC day the fan sent the tip (not the day intake read it)."""
    when = parse(row.get("tip_created_utc"))
    return iso(when)[:10] if when else None


def fan_duplicate_of(card: Card, hound_id: str, values: Mapping, day: str) -> Optional[int]:
    """The key of today's first row for the same hound and values, else None."""
    sig = values_signature(values)
    for key, row in card.fans.items():
        if row.get("hound") == hound_id and fan_day(row) == day \
                and values_signature(row.get("suggested_values") or {}) == sig:
            return key
    return None


def fan_day_full(card: Card, day: str) -> bool:
    """True when ``day`` already holds ``FAN_PER_UTC_DAY`` fan rows (repeats do not count: they are a count)."""
    return sum(1 for row in card.fans.values() if fan_day(row) == day) >= FAN_PER_UTC_DAY


# ---- the change, in words ------------------------------------------------------------------------------------

def _plain_number(value) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def change_list(tunable, old_values: Mapping, new_values: Mapping) -> list:
    """``[{knob, label, old, new, old_text, new_text}]`` for every knob that differs. The texts are the
    hound's own rule words (``tunables.render``) when the knob declares them, else the plain numbers, so a
    reader sees "4.0 points or more" and not "0.04"."""
    from src.hounds.learning import tunables
    out = []
    for name, knob in tunable.knobs.items():
        old, new = old_values.get(name, knob.default), new_values.get(name, knob.default)
        if abs(float(old) - float(new)) < 1e-9:
            continue

        def words(v):
            pairs = tunables.render(knob, v)
            return pairs[0][1] if pairs else _plain_number(v)

        out.append({"knob": name, "label": knob.label, "old": old, "new": new,
                    "old_text": words(old), "new_text": words(new)})
    return out


def change_sentence(changes: list) -> str:
    """``Consensus move ... from 3.0 points or more to 4.0 points or more`` (several changes joined by 'and')."""
    parts = [f'"{c["label"]}" from {c["old_text"]} to {c["new_text"]}' for c in changes]
    return " and ".join(parts) if parts else "no change"
