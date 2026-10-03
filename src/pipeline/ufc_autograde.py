"""Automatic UFC result grading: provider fights -> the SAME results store.

WHY THIS EXISTS
---------------
UFC picks were graded only from hand-entered results
(`src.pipeline.ufc_results`, audit docs/audit/2026-10-01/UFC_GRADING.md).
This module is the swappable automatic path: a PROVIDER returns the fights
of a card as `ProviderFight` rows; `resolve_bout` decides, deterministically
and strictly, what (if anything) each published pick's bout became; and
`autograde_date` writes the decision through `ufc_results.record_result` --
the one writer -- with `entered_by="auto:<provider>"` plus provenance
(provider, provider event/fight id, fetched_utc, raw status). Grading itself
is untouched: `src.report.ufc_card.settle_for_date` reads the store exactly
as before, so an automatic row grades identically to a typed one.

RULES (each is a test)
----------------------
* Names: a provider fight matches a pick only when
  `ufc_results.fighters_match` says so -- exact normalized pair, either
  order, no fuzzy matching. Two fights matching, or a fight sharing ONE
  name whose other name merely LOOKS LIKE the missing one (a spelling
  variant), is ambiguous: nothing is graded, the bout is reported for a
  human.
* Final only: a fight whose provider status is not final or cancelled
  (scheduled, in progress, postponed, delayed, unknown ...) grades nothing.
  A "final" fight with no winner and no recognised draw / no-contest marker
  also grades nothing (the provider's draw encoding is not documented).
* Replacement: when the published pairing is absent from the provider's
  card but a published fighter appears in a different FINAL fight against
  someone who is not a name-variant of the missing opponent, the published
  pairing did not happen -> `cancelled`. Same verified fact the manual path
  uses (`ufc_card._fighter_names_seen`), now with the replacement fight's id
  on the row. A pick with neither fighter on the provider's card stays
  unresolved: absence alone is not proof.
* Never supersedes a person: a bout that already has ANY row in the store is
  never written again, so a re-run cannot bury a manual correction. (And the
  store's own newest-row-wins rule still lets a later manual row supersede an
  automatic one.) Such a bout is still COMPARED with what the provider says:
  the same grade is `skip` ("the source agrees"), a different grade is
  `disagree` -- reported loudly, nothing changed; a correction stays a new,
  human row.
* `verify=True` also examines picks that are already settled and writes
  nothing at all: the audit that replays a provider against the results on
  file (docs/UFC_RESULT_SOURCE.md).
* Settlement stays separate: this module records results only; run
  `python -m src.cli card settle --sport mma --date D` afterwards.

THE SEAM
--------
A provider may override two hooks. `fetch_for_bouts(date, bouts, now=)` is
told which published bouts it is being asked about (the default reads the
whole card with `fetch_fights`). `decide(bout, fights)` turns the fights into
a `Decision` (the default is the strict normalised-name `resolve_bout`
below); a provider that has better identity data than a name -- ESPN's
athlete ids (`src.providers.espn_mma_results`) -- overrides it, then still
leans on `resolve_bout` for status, outcome and replaced-fighter rules.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from src.appstate import card_ledger
from src.datasvc import names
from src.pipeline import ufc_results

STATUS_FINAL = "final"
STATUS_CANCELLED = "cancelled"
STATUS_PENDING = "pending"  # anything that is not yet a terminal fact

ACTION_RECORD = "record"
ACTION_UNRESOLVED = "unresolved"
ACTION_SKIP = "skip"
# The provider contradicts a result already on file. Nothing is written; the
# row on file stands until a person corrects it with a new row.
ACTION_DISAGREE = "disagree"

# Two names that differ but are at least this alike are treated as a possible
# spelling variant of one fighter (=> ambiguous, not a replacement).
_VARIANT_RATIO = 0.7


class ProviderError(RuntimeError):
    """The provider could not answer at all (no key, not entitled, network).
    Nothing is recorded; the message names the exact blocker."""


@dataclass(frozen=True)
class ProviderFight:
    """One fight as a provider reports it, already normalised.

    `outcome` is only meaningful when `status == STATUS_FINAL`: "win" (with
    `winner` naming the winning fighter exactly as the provider spells it),
    "draw", "no_contest", or None when the provider says final but the
    result cannot be read (graded as unresolved).
    """
    provider: str
    event_id: str
    fight_id: str
    fighter1: str
    fighter2: str
    status: str
    raw_status: str
    outcome: Optional[str] = None
    winner: Optional[str] = None
    fetched_utc: str = ""


class UfcResultsProvider:
    """The seam. A provider is anything with a `name` and `fetch_fights`."""

    name = "abstract"

    def fetch_fights(self, date: str, *, now: datetime) -> Sequence[ProviderFight]:
        raise NotImplementedError

    def fetch_for_bouts(self, date: str, bouts: Sequence["BoutIdentity"], *,
                        now: datetime) -> Sequence[ProviderFight]:
        """The fights to decide `bouts` from. A provider that can be asked
        about particular pairings (and so read only what they need) overrides
        this; the default reads the whole card."""
        return self.fetch_fights(date, now=now)

    def decide(self, bout: "BoutIdentity",
               fights: Sequence[ProviderFight]) -> "Decision":
        """What `fights` say about one published bout. The default is the
        strict normalised-name rule (`resolve_bout`)."""
        return resolve_bout(bout, fights)


@dataclass(frozen=True)
class BoutIdentity:
    """A published pick's bout, from the ledger row: both names plus the
    commence time and our own game id."""
    date: str
    home: str
    away: str
    commence_utc: Optional[datetime]
    game_id: str

    @property
    def fight(self) -> str:
        return f"{self.home} vs {self.away}"


@dataclass
class Decision:
    """`outcome` / `winner` / `provenance` are what the SOURCE says. For
    `record` they are what is written; for `disagree` and for a `skip` the
    source agreed with they are shown, never written. `existing` is the row
    already on file for the bout (None when there is none)."""
    bout: BoutIdentity
    action: str
    reason: str
    outcome: Optional[str] = None
    winner: Optional[str] = None
    provenance: dict = field(default_factory=dict)
    existing: Optional[dict] = None


def _norm(name: str) -> str:
    return ufc_results.normalize_name(name)


def _similar(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if difflib.SequenceMatcher(None, na, nb).ratio() >= _VARIANT_RATIO:
        return True
    # A shared last name is the usual shape of a nickname / first-name variant.
    return na.split()[-1] == nb.split()[-1]


def _prov(fight: ProviderFight, basis: str) -> dict:
    return {"provider": fight.provider, "provider_event_id": fight.event_id,
            "provider_fight_id": fight.fight_id,
            "fetched_utc": fight.fetched_utc or None,
            "raw_status": fight.raw_status, "basis": basis}


def resolve_bout(bout: BoutIdentity, fights: Sequence[ProviderFight]) -> Decision:
    """What the provider's fights say about one published bout. Pure: no I/O."""
    def unresolved(reason: str) -> Decision:
        return Decision(bout, ACTION_UNRESOLVED, reason)

    if not fights:
        return unresolved("provider returned no fights for this card")

    exact = [f for f in fights
             if ufc_results.fighters_match(f"{f.fighter1} vs {f.fighter2}",
                                           bout.home, bout.away)]
    if len(exact) > 1:
        ids = ", ".join(sorted(f.fight_id for f in exact))
        return unresolved(f"ambiguous: {len(exact)} provider fights match this "
                          f"pairing (fight ids {ids})")

    if len(exact) == 1:
        fight = exact[0]
        if fight.status == STATUS_CANCELLED:
            return Decision(bout, ACTION_RECORD,
                            f"provider marks the fight cancelled ({fight.raw_status})",
                            outcome=ufc_results.OUTCOME_CANCELLED,
                            provenance=_prov(fight, "provider status cancelled"))
        if fight.status != STATUS_FINAL:
            return unresolved(f"provider status is not final ({fight.raw_status})")
        if fight.outcome in (ufc_results.OUTCOME_DRAW, ufc_results.OUTCOME_NO_CONTEST):
            return Decision(bout, ACTION_RECORD,
                            f"final, ruled {fight.outcome.replace('_', ' ')} "
                            f"({fight.raw_status})",
                            outcome=fight.outcome,
                            provenance=_prov(fight, f"provider final, {fight.outcome}"))
        if fight.outcome == ufc_results.OUTCOME_WIN and fight.winner:
            # The winner must be exactly one of the two published names; its
            # spelling is taken from OUR pick so the store row is matched by
            # the same names the manual path uses.
            by_norm = {_norm(bout.home): bout.home, _norm(bout.away): bout.away}
            published_name = by_norm.get(_norm(fight.winner))
            if published_name is None:
                return unresolved(f"final but winner {fight.winner!r} is neither "
                                  "published fighter")
            return Decision(bout, ACTION_RECORD,
                            f"final, {published_name} won ({fight.raw_status})",
                            outcome=ufc_results.OUTCOME_WIN, winner=published_name,
                            provenance=_prov(fight, "provider final, winner named"))
        return unresolved("final but the provider names no winner and no "
                          f"recognised draw / no-contest marker ({fight.raw_status})")

    # No exact pairing. Look for the published fighters elsewhere on the card.
    names = {_norm(bout.home): bout.home, _norm(bout.away): bout.away}
    partial = []  # (fight, published_name_present, provider_opponent, missing_name)
    for f in fights:
        for mine, theirs in ((f.fighter1, f.fighter2), (f.fighter2, f.fighter1)):
            if _norm(mine) in names:
                missing = bout.away if _norm(mine) == _norm(bout.home) else bout.home
                partial.append((f, mine, theirs, missing))
    if not partial:
        return unresolved("neither published fighter is on the provider's card "
                          "(not proof the bout was cancelled)")
    for f, _mine, theirs, missing in partial:
        if _similar(theirs, missing):
            return unresolved(
                f"ambiguous: {f.fighter1} vs {f.fighter2} shares one name and "
                f"{theirs!r} looks like a spelling of {missing!r}")
    final_other = [p for p in partial if p[0].status == STATUS_FINAL]
    if not final_other:
        return unresolved("a published fighter is in a different fight that is "
                          "not final yet; cannot call the pairing replaced")
    fight, mine, theirs, _missing = final_other[0]
    return Decision(
        bout, ACTION_RECORD,
        f"published pairing did not happen: {mine} fought {theirs} instead "
        f"({fight.raw_status})",
        outcome=ufc_results.OUTCOME_CANCELLED,
        provenance=_prov(
            fight, f"fighter replaced: {mine} fought {theirs} (fight "
                   f"{fight.fight_id}); published pairing did not happen"))


# ---------------------------------------------------------------------------
# Reading the published card
# ---------------------------------------------------------------------------

def _parse_utc(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def bouts_to_grade(date: str, *, ledger_path: Optional[str] = None,
                   include_graded: bool = False) -> list:
    """The published picks of `date` that still need a result: every pick of
    the newest published card, minus any already graded (a settled row with
    a result other than UNRESOLVED). [] when nothing is published.

    `include_graded=True` keeps the settled picks too -- only for the
    read-only audit (`autograde_date(verify=True)`)."""
    published = card_ledger.published_row(date, sport="mma", path=ledger_path)
    if published is None:
        return []
    settled = card_ledger.settled_row(date, sport="mma", path=ledger_path)
    done = set()
    if settled is not None and not include_graded:
        done = {p.get("game_id") for p in settled.get("picks") or ()
                if p.get("result") != card_ledger.RESULT_UNRESOLVED}
    out, seen = [], set()
    for p in published.get("picks") or ():
        gid = p.get("game_id")
        home, away = p.get("home_team"), p.get("away_team")
        if gid in done or not home or not away:
            continue
        key = frozenset((_norm(home), _norm(away)))
        if key in seen:
            continue
        seen.add(key)
        out.append(BoutIdentity(
            date=date, home=home, away=away, game_id=str(gid),
            commence_utc=_parse_utc(p.get("first_pitch_utc") or p.get("kickoff_utc"))))
    return out


# ---------------------------------------------------------------------------
# A source against a result that is already on file
# ---------------------------------------------------------------------------

def _same_person(a, b) -> bool:
    """Two spellings of one fighter's name: equal once case, spacing,
    accents and punctuation are folded away."""
    if _norm(a) == _norm(b):
        return True
    folded = names.normalise(a)
    return bool(folded) and folded == names.normalise(b)


def _same_result(existing: dict, decision: Decision) -> bool:
    """Whether the result on file and the source's would GRADE a pick the
    same way: the same fighter won, or both are void outcomes (cancelled,
    draw and no contest all grade VOID, so a differing label is not a
    disagreement about the grade)."""
    on_file = existing.get("outcome")
    if on_file in ufc_results.VOID_OUTCOMES:
        return decision.outcome in ufc_results.VOID_OUTCOMES
    if on_file == ufc_results.OUTCOME_WIN and decision.outcome == ufc_results.OUTCOME_WIN:
        return _same_person(existing.get("winner"), decision.winner)
    return False


def _on_file_reason(existing: dict) -> str:
    return (f"already has a result ({existing.get('outcome')}, entered by "
            f"{existing.get('entered_by')}); automatic grading never supersedes it")


def _describe_result(outcome: Optional[str], winner: Optional[str]) -> str:
    return f"{outcome}, winner {winner}" if winner else f"{outcome}"


def _compare(bout: BoutIdentity, existing: dict, decision: Decision, source: str) -> Decision:
    """The source's decision for a bout that already has a row. Never a
    record: the row on file stands. Agreement is a `skip` that says so; a
    different grade is `disagree`; a source with nothing final to say leaves
    a `skip` that says it could not check."""
    base = _on_file_reason(existing)
    if decision.action != ACTION_RECORD:
        return Decision(bout, ACTION_SKIP,
                        f"{base}; {source} could not confirm it: {decision.reason}",
                        existing=existing)
    if _same_result(existing, decision):
        return Decision(bout, ACTION_SKIP, f"{base}; {source} agrees: {decision.reason}",
                        provenance=decision.provenance, existing=existing)
    return Decision(
        bout, ACTION_DISAGREE,
        f"{source} DISAGREES with the result on file. On file: "
        f"{_describe_result(existing.get('outcome'), existing.get('winner'))} "
        f"(entered by {existing.get('entered_by')} at {existing.get('entered_utc')}). "
        f"{source} says: {decision.reason}. Nothing was changed; if {source} is right, "
        "correct it with a new row by hand (python -m src.cli ufc result ...)",
        outcome=decision.outcome, winner=decision.winner,
        provenance=decision.provenance, existing=existing)


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

def autograde_date(date: str, provider: UfcResultsProvider, *,
                   dry_run: bool = False, verify: bool = False,
                   now: Optional[datetime] = None,
                   ledger_path: Optional[str] = None,
                   results_path=None) -> list:
    """Decide (and, unless dry_run, record) a result for every pick of
    `date` that has none. Returns the list of `Decision`s, one per bout.

    A bout that already has a row is never written again, but once it has
    started it is still compared with the source (`skip` when they agree,
    `disagree` when they do not). `verify=True` also examines picks that are
    already settled and never writes -- the read-only audit.

    Raises ProviderError (nothing recorded) when the provider cannot answer
    for a bout that needs a result. If every bout already has a row and the
    provider cannot answer, the comparison is simply skipped (and says so).
    """
    now = now or datetime.now(timezone.utc)
    kwargs = {"path": results_path} if results_path is not None else {}
    dry_run = dry_run or verify
    bouts = bouts_to_grade(date, ledger_path=ledger_path, include_graded=verify)
    if not bouts:
        return []

    decisions: list = []
    ask: list = []          # started bouts: the provider is asked about these
    on_file: dict = {}      # game_id -> the row already on file
    for bout in bouts:
        existing = ufc_results.result_for_fight(date, bout.home, bout.away, **kwargs)
        if existing is not None:
            on_file[bout.game_id] = existing
        if bout.commence_utc is None or bout.commence_utc <= now:
            ask.append(bout)
        elif existing is not None:
            decisions.append(Decision(
                bout, ACTION_SKIP,
                f"{_on_file_reason(existing)}; the bout has not started, so it was "
                "not compared with the source", existing=existing))
        else:
            decisions.append(Decision(
                bout, ACTION_UNRESOLVED,
                f"bout starts {bout.commence_utc.isoformat()}, not yet fought"))

    fights: Optional[Sequence[ProviderFight]] = []
    unavailable: Optional[ProviderError] = None
    if ask:
        needs_a_result = any(b.game_id not in on_file for b in ask)
        try:
            fights = list(provider.fetch_for_bouts(date, ask, now=now))
        except ProviderError as exc:
            if needs_a_result:
                raise
            fights, unavailable = None, exc
    for bout in ask:
        existing = on_file.get(bout.game_id)
        if existing is None:
            decisions.append(provider.decide(bout, fights))
        elif unavailable is not None:
            decisions.append(Decision(
                bout, ACTION_SKIP,
                f"{_on_file_reason(existing)}; not compared with {provider.name}: "
                f"{unavailable}", existing=existing))
        else:
            decisions.append(_compare(bout, existing, provider.decide(bout, fights),
                                      provider.name))

    if not dry_run:
        for d in decisions:
            if d.action != ACTION_RECORD:
                continue
            d.provenance["fetched_utc"] = d.provenance.get("fetched_utc") or now.isoformat()
            ufc_results.record_result(
                date=date, fight=d.bout.fight, winner=d.winner, outcome=d.outcome,
                entered_by=f"auto:{d.provenance['provider']}", now=now, **kwargs,
                **d.provenance)
    order = {b.game_id: i for i, b in enumerate(bouts)}
    decisions.sort(key=lambda d: order.get(d.bout.game_id, 0))
    return decisions
