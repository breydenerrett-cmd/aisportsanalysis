"""`situation_for_bout`: the bigger picture around one UFC bout.

WHAT IT READS
-------------
Only the UFC data layer (`src/datasvc/ufc/`), through its public functions, all of which
already obey the layoff rule: `features.features_as_of` and `features.completed_fights`
admit only bouts that STARTED STRICTLY BEFORE the as-of instant and have a result. This
record is drawn as of the bout's scheduled start, so the bout itself, a later bout and a
bout with no result never count (`docs/datasvc/UFC_FEATURES.md` section 1). Nothing here
adds a statistic the data layer does not already hold; it arranges what it has into the
situation around the fight and says where the data runs out.

FAMILIES, AS BUILT
------------------
rest_and_rhythm    days since each fighter's last fight (and whether that is a short
                   turnaround or a long layoff), fights in the last 365 days
form               current streak, finishes among the last five fights, how the quality of
                   the last three opponents compares with the earlier ones
stakes             title bout, card slot (main event, scheduled rounds)
pressure_history   record in main events and title fights on file
head_to_head       the previous meeting between the two, opponents they share
availability       weight class against the last fight's

NOT IN THE DATA, SO NOT STATED (listed in `missing`): short-notice replacements, missed
weight, injuries, camp news and rankings. A fighter's counts cover the UFC fights in the
store only; the store begins where `coverage.data_starts` says, and a fighter with two
fights on file may have fought twenty times.

Pure given the store handed in: no clock, no network.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, List, Mapping, Optional, Sequence

from src.datasvc import names as names_mod
from src.datasvc.ufc import features as feat
from src.datasvc.ufc import matchup as mu
from src.situation import record as rec

SPORT = "ufc"
FAMILIES = ("rest_and_rhythm", "form", "stakes", "pressure_history", "head_to_head", "availability")
SIDES = ("a", "b")

# A turnaround this short or shorter, and a layoff this long or longer, get named. The
# same bars the written read uses (`ufc_read.SHORT_TURNAROUND_DAYS`, `LAYOFF_DAYS[0]`): design
# choices fixed in advance, not fitted to results.
SHORT_TURNAROUND_DAYS = 35
LONG_LAYOFF_DAYS = 365
ACTIVITY_WINDOW_DAYS = 365
# Fights counted for "recent finishes", and for each half of the opponent-quality comparison.
RECENT_FIGHTS = 5
TREND_RECENT = 3
TREND_MIN_RECENT = 2          # opponents with a record needed in the recent half
TREND_MIN_EARLIER = 1         # and in the earlier half

_METHOD_WORDS = {"ko_tko": "by knockout", "submission": "by submission", "decision": "on the scorecards",
                 "dq": "by disqualification", "other": "by another stoppage", "unknown": "by an unrecorded method"}
_OUTCOME_WORDS = {"win": "a win", "loss": "a loss", "draw": "a draw", "no_contest": "a no contest"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _day(moment) -> str:
    return moment.date().isoformat()


def _result_words(f: feat.Fight, opponent: Optional[str]) -> str:
    base = _OUTCOME_WORDS.get(f.outcome, "a result")
    if f.outcome in ("win", "loss"):
        base += " " + _METHOD_WORDS.get(f.group, "")
    base = base.strip()
    return f"{base} against {opponent}" if opponent else base


_METHOD_CODE_WORDS = {
    "KO_TKO": "knockout", "SUB": "submission", "DEC_UNANIMOUS": "unanimous decision",
    "DEC_SPLIT": "split decision", "DEC_MAJORITY": "majority decision", "DECISION": "decision",
    "DQ": "disqualification", "OTHER": "another stoppage"}


def _meeting_words(meeting: Mapping) -> str:
    """How an earlier meeting ended, from one `matchup.previous_meetings` line."""
    winner, method = meeting.get("winner_name"), meeting.get("method")
    if winner:
        how = _METHOD_CODE_WORDS.get(method)
        return f"{winner} won by {how}" if how else f"{winner} won"
    return {"DRAW": "it was a draw", "NC": "it was a no contest"}.get(method, "no winner is on file")


def _store_start(store) -> Optional[str]:
    days = [m.date().isoformat() for m in (feat.bout_start(b) for b in store.bouts) if m]
    return min(days) if days else None


class _Side:
    """One fighter: id, label, completed fights before the bout, the data layer's features."""

    def __init__(self, store, key: str, fighter_id: str, start, features: Optional[Mapping]):
        self.key = key
        self.id = str(fighter_id)
        fighter = store.fighter_by_id().get(self.id) or {}
        self.name_known = bool(fighter.get("name"))
        self.name = fighter.get("name") if self.name_known else f"Fighter {key.upper()}"
        self.fights: List[feat.Fight] = feat.completed_fights(store, self.id, start)
        self.features = dict(features) if features else feat.features_as_of(store, self.id, start)
        self.store = store

    def opponent_name(self, f: feat.Fight) -> Optional[str]:
        return (self.store.fighter_by_id().get(f.opponent_id) or {}).get("name")


# ---------------------------------------------------------------------------
# families
# ---------------------------------------------------------------------------

def _rest(ctx, side: _Side, out: list, gaps: list) -> None:
    fam = "rest_and_rhythm"
    if not side.fights:
        gaps.append(rec.gap(fam, "days_since_last_fight",
                            f"{side.name} has no UFC fight in the data store before this bout", side=side.key))
        return
    last = side.fights[-1]
    days = (ctx.start - last.start).days
    opponent = side.opponent_name(last)
    bucket = ("short turnaround" if days <= SHORT_TURNAROUND_DAYS
              else "long layoff" if days >= LONG_LAYOFF_DAYS else "normal")
    tail = {"short turnaround": ", a short turnaround", "long layoff": ", a long layoff", "normal": ""}[bucket]
    out.append(rec.factor(
        fam, "days_since_last_fight", days, "days", sample={"fights": len(side.fights)},
        as_of=feat.iso_utc(last.start), side=side.key,
        source=f"UFC data store: {side.name}'s last fight before this bout ({_day(last.start)})",
        sentence=(f"{side.name} last fought {days} days before this bout ({_day(last.start)}): "
                  f"{_result_words(last, opponent)}{tail}."),
        detail={"bucket": bucket, "last_fight": _day(last.start), "result": last.outcome,
                "method_group": last.group, "opponent": opponent,
                "short_turnaround_days": SHORT_TURNAROUND_DAYS, "long_layoff_days": LONG_LAYOFF_DAYS}))
    window_start = ctx.start - timedelta(days=ACTIVITY_WINDOW_DAYS)
    recent = [f for f in side.fights if f.start >= window_start]
    complete = ctx.data_starts is None or ctx.data_starts <= window_start.date().isoformat()
    sentence = (f"{side.name} has fought {_plural(len(recent), 'time')} in the {ACTIVITY_WINDOW_DAYS} days "
                "before this bout")
    sentence += "." if complete else f", counting only fights from {ctx.data_starts}, where our data begins."
    out.append(rec.factor(
        fam, "fights_last_365_days", len(recent), "fights", sample={"fights": len(side.fights)},
        as_of=feat.iso_utc(side.fights[-1].start), side=side.key,
        source=f"UFC data store: {side.name}'s fights in the {ACTIVITY_WINDOW_DAYS} days before this bout",
        sentence=sentence, detail={"window_days": ACTIVITY_WINDOW_DAYS, "window_complete": complete}))


def _form(ctx, side: _Side, out: list, gaps: list) -> None:
    fam = "form"
    if not side.fights:
        gaps.append(rec.gap(fam, "streak", f"{side.name} has no UFC fight in the data store before this bout",
                            side=side.key))
        return
    streak = side.features.get("streak") or {}
    kind, length = streak.get("type"), streak.get("length") or 0
    newest = feat.iso_utc(side.fights[-1].start)
    if kind in ("win", "loss"):
        word = "won" if kind == "win" else "lost"
        out.append(rec.factor(
            fam, "streak", length, "fights", sample={"fights": len(side.fights)}, as_of=newest, side=side.key,
            source=f"UFC data store: {side.name}'s results in order",
            sentence=(f"{side.name} {word} the last UFC fight on file." if length == 1
                      else f"{side.name} has {word} {length} UFC fights in a row on file."),
            detail={"type": kind}))
    elif kind in ("draw", "no_contest"):
        out.append(rec.factor(
            fam, "streak", length, "fights", sample={"fights": len(side.fights)}, as_of=newest, side=side.key,
            source=f"UFC data store: {side.name}'s results in order",
            sentence=(f"{side.name}'s last UFC fight on file ended in "
                      f"{'a draw' if kind == 'draw' else 'a no contest'}."),
            detail={"type": kind}))
    last = side.fights[-RECENT_FIGHTS:]
    finish = ("ko_tko", "submission")
    fw = sum(1 for f in last if f.outcome == "win" and f.group in finish)
    fl = sum(1 for f in last if f.outcome == "loss" and f.group in finish)
    dw = sum(1 for f in last if f.outcome == "win" and f.group == "decision")
    out.append(rec.factor(
        fam, "recent_finishes", fw, "finishing wins", sample={"fights": len(last), "window": RECENT_FIGHTS},
        as_of=newest, side=side.key, source=f"UFC data store: {side.name}'s last {len(last)} fights",
        sentence=(f"In the last {_plural(len(last), 'fight')} on file, {side.name} has {_plural(fw, 'finishing win')}, "
                  f"{_plural(dw, 'decision win')} and has been finished {_plural(fl, 'time')}."),
        detail={"finishing_wins": fw, "decision_wins": dw, "finishing_losses": fl}))
    # Opponent quality: each opponent's record going into that fight, from the data layer.
    rows = [r for r in (side.features.get("strength_of_schedule_by_fight") or [])]
    rates = [r.get("opponent_win_rate") for r in rows]
    recent_rates = [x for x in rates[-TREND_RECENT:] if x is not None]
    earlier_rates = [x for x in rates[:-TREND_RECENT] if x is not None]
    if len(recent_rates) >= TREND_MIN_RECENT and len(earlier_rates) >= TREND_MIN_EARLIER:
        rm, em = sum(recent_rates) / len(recent_rates), sum(earlier_rates) / len(earlier_rates)
        out.append(rec.factor(
            fam, "opponent_quality_trend", round(rm - em, 4), "win rate difference",
            sample={"recent_opponents": len(recent_rates), "earlier_opponents": len(earlier_rates)},
            as_of=newest, side=side.key,
            source=f"UFC data store: each opponent's record going into the fight, for {side.name}'s fights",
            sentence=(f"The last {len(recent_rates)} opponents of {side.name} had won {_pct(rm)} of their earlier UFC "
                      f"fights, against {_pct(em)} for the {len(earlier_rates)} before that."),
            detail={"recent_mean": round(rm, 4), "earlier_mean": round(em, 4)}))
    else:
        gaps.append(rec.gap(fam, "opponent_quality_trend",
                            f"too few of {side.name}'s opponents have a record in the data to compare the "
                            f"last {TREND_RECENT} with the earlier ones", side=side.key))


def _stakes(ctx, out: list, gaps: list) -> None:
    fam = "stakes"
    bout = ctx.bout
    as_of = ctx.day_before
    title = bout.get("title_bout")
    if isinstance(title, bool):
        types = [t for t in (bout.get("bout_types") or []) if t]
        out.append(rec.factor(
            fam, "title_bout", title, "bool", sample={}, as_of=as_of,
            source="the schedule: the bout's listed types",
            sentence=("This is a title bout." if title else "This is not a title bout."),
            detail=({"bout_types": ", ".join(types)} if types else None)))
    else:
        gaps.append(rec.gap(fam, "title_bout", "the schedule does not say whether this is a title bout"))
    number = bout.get("match_number")
    if isinstance(number, int) and not isinstance(number, bool):
        rounds = bout.get("scheduled_rounds")
        segment = bout.get("card_segment")
        place = "The main event" if number == 1 else f"Bout {number} from the top of the card"
        words = {"main": "main card", "prelims": "prelims", "early_prelims": "early prelims"}.get(segment, segment)
        tail = f", scheduled for {rounds} rounds" if isinstance(rounds, int) else ""
        out.append(rec.factor(
            fam, "card_position", number, "bout number", sample={}, as_of=as_of,
            source="the schedule: the bout's slot on the card",
            sentence=f"{place}{', ' + words if words else ''}{tail}.",
            detail={k: v for k, v in (("main_event", number == 1), ("card_segment", segment),
                                      ("scheduled_rounds", rounds)) if v is not None}))
    else:
        gaps.append(rec.gap(fam, "card_position", "the schedule does not give this bout's slot on the card"))
    gaps.append(rec.gap(fam, "rankings", "rankings and what a win is worth in them are not in the data"))


def _pressure(ctx, side: _Side, out: list, gaps: list) -> None:
    fam = "pressure_history"
    big = [f for f in side.fights if f.bout.get("match_number") == 1 or f.bout.get("title_bout") is True]
    if not side.fights:
        return
    wins = sum(1 for f in big if f.outcome == "win")
    losses = sum(1 for f in big if f.outcome == "loss")
    other = len(big) - wins - losses
    if big:
        sentence = (f"{side.name} is {wins}-{losses} in {_plural(len(big), 'main event')} and title "
                    f"{'fight' if len(big) == 1 else 'fights'} on file")
        sentence += f" ({_plural(other, 'other result')})." if other else "."
    else:
        sentence = f"{side.name} has no main event or title fight on file."
    out.append(rec.factor(
        fam, "main_event_record", len(big), "bouts", sample={"fights": len(side.fights)},
        as_of=feat.iso_utc(side.fights[-1].start), side=side.key,
        source=f"UFC data store: {side.name}'s fights that were main events or title bouts",
        sentence=sentence, detail={"wins": wins, "losses": losses, "other": other}))


def _head_to_head(ctx, a: _Side, b: _Side, out: list, gaps: list) -> None:
    fam = "head_to_head"
    meetings = mu.previous_meetings(ctx.store, a.fights, b.id)
    stamp = feat.instant(meetings[-1].get("date_utc")) if meetings else None
    as_of = (feat.iso_utc(stamp) if stamp
             else (feat.iso_utc(max(a.fights[-1].start, b.fights[-1].start)) if a.fights and b.fights
                   else ctx.day_before))
    if meetings:
        last = meetings[-1]
        when = (last.get("date_utc") or "")[:10]
        detail = {"meetings": [{"date": (m.get("date_utc") or "")[:10], "winner": m.get("winner_name"),
                                "method": m.get("method"), "round": m.get("round")} for m in meetings]}
        how = _meeting_words(last)
        if len(meetings) == 1:
            sentence = f"{a.name} and {b.name} have fought once before, on {when}: {how}."
        else:
            sentence = (f"{a.name} and {b.name} have fought {len(meetings)} times before; the last was on "
                        f"{when}: {how}.")
    else:
        detail = None
        sentence = f"{a.name} and {b.name} have not fought each other in the UFC fights on file."
    out.append(rec.factor(
        fam, "previous_meeting", len(meetings), "fights", sample={"fights_a": len(a.fights), "fights_b": len(b.fights)},
        as_of=as_of, source="UFC data store: bouts between the two fighters before this one",
        sentence=sentence, detail=detail))
    shared = mu.shared_opponents(ctx.store, a.fights, b.fights, a.id, b.id)
    count = shared["count"]
    out.append(rec.factor(
        fam, "common_opponents", count, "opponents",
        sample={"opponents_a": shared["a_opponents"], "opponents_b": shared["b_opponents"]}, as_of=as_of,
        source="UFC data store: opponents both fighters have faced before this bout",
        sentence=(f"The two share {_plural(count, 'opponent')} in common on file "
                  f"({shared['a_opponents']} for {a.name}, {shared['b_opponents']} for {b.name})."
                  if count else
                  f"The two share no opponents on file ({shared['a_opponents']} for {a.name}, "
                  f"{shared['b_opponents']} for {b.name}).")))


def _weight_class(ctx, side: _Side, out: list, gaps: list) -> None:
    fam = "availability"
    now = ctx.bout.get("weight_class")
    prior = next((f.bout.get("weight_class") for f in reversed(side.fights) if f.bout.get("weight_class")), None)
    if not now or not prior:
        why = ("this bout's weight class is not on file" if not now else
               f"{side.name} has no earlier fight with a weight class on file")
        gaps.append(rec.gap(fam, "weight_class_change", why, side=side.key))
        return
    if names_mod.normalise(now) == names_mod.normalise(prior):
        value, sentence = "same", f"{side.name} fights at {now} again."
    else:
        lo = feat.WEIGHT_LIMIT_LB.get(names_mod.normalise(prior))
        hi = feat.WEIGHT_LIMIT_LB.get(names_mod.normalise(now))
        if lo is None or hi is None or lo == hi:
            value, sentence = "changed", f"{side.name} changes weight class, from {prior} to {now}."
        elif hi > lo:
            value, sentence = "up", f"{side.name} moves up in weight, from {prior} to {now}."
        else:
            value, sentence = "down", f"{side.name} drops down in weight, from {prior} to {now}."
    out.append(rec.factor(
        fam, "weight_class_change", value, "text", sample={"fights": len(side.fights)},
        as_of=feat.iso_utc(side.fights[-1].start), side=side.key,
        source=f"UFC data store: the weight class of {side.name}'s last fight against this bout's",
        sentence=sentence, detail={"from": prior, "to": now}))


# ---------------------------------------------------------------------------
# the public function
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(self, store, bout: Mapping, start):
        self.store, self.bout, self.start = store, bout, start
        self.day_before = feat.iso_utc(start - timedelta(days=1))
        self.data_starts = _store_start(store)


def situation_for_bout(store, bout_id: str, *, sheet: Optional[Mapping] = None,
                       strict: bool = False) -> dict:
    """The situation around one UFC bout, drawn as of its scheduled start.

    `store` is a `src.datasvc.ufc.store.UfcStore`. `sheet` (optional) is the data layer's
    matchup sheet for this bout as of its start: its per-fighter features are reused so
    the page does not compute them twice. Raises `LookupError` for a bout not in the store
    and `ValueError` for a bout that does not name two different fighters or has no
    readable start (nothing can be shown to precede a bout with no start). A part that
    fails is left out and listed as missing; `strict=True` re-raises instead.
    """
    bout = store.bout_by_id().get(str(bout_id))
    if bout is None:
        raise LookupError(f"no bout {bout_id!r} in the store")
    a_id, b_id = bout.get("fighter_a_id"), bout.get("fighter_b_id")
    if not a_id or not b_id or str(a_id) == str(b_id):
        raise ValueError(f"bout {bout_id!r} does not name two different fighters")
    start = feat.bout_start(bout)
    if start is None:
        raise ValueError(f"bout {bout_id!r} has no readable start, so nothing can be shown to precede it")
    feats = (sheet or {}).get("features") or {}
    fa = feats.get("a") if str((feats.get("a") or {}).get("fighter_id")) == str(a_id) else None
    fb = feats.get("b") if str((feats.get("b") or {}).get("fighter_id")) == str(b_id) else None
    ctx = _Ctx(store, bout, start)
    a = _Side(store, "a", a_id, start, fa)
    b = _Side(store, "b", b_id, start, fb)
    factors: List[dict] = []
    gaps: List[dict] = []

    def run(label: str, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 -- one part never takes the record down
            if strict:
                raise
            family = label.split(".")[0]
            gaps.append(rec.gap(family, label.split(".")[-1],
                                f"this part could not be worked out from the data ({type(exc).__name__})"))

    for side in (a, b):
        run("rest_and_rhythm.rest", _rest, ctx, side, factors, gaps)
        run("form.form", _form, ctx, side, factors, gaps)
        run("pressure_history.pressure", _pressure, ctx, side, factors, gaps)
        run("availability.weight_class", _weight_class, ctx, side, factors, gaps)
    run("stakes.stakes", _stakes, ctx, factors, gaps)
    run("head_to_head.head_to_head", _head_to_head, ctx, a, b, factors, gaps)
    gaps.append(rec.gap("availability", "short_notice_and_missed_weight",
                        "short-notice replacements, missed weight, injuries and camp news are not in the data"))
    display = [("stakes", "title_bout", "game"), ("stakes", "card_position", "game"),
               ("rest_and_rhythm", "days_since_last_fight", "a"), ("rest_and_rhythm", "days_since_last_fight", "b"),
               ("form", "streak", "a"), ("form", "streak", "b"), ("head_to_head", "previous_meeting", "game"),
               ("availability", "weight_class_change", "a"), ("availability", "weight_class_change", "b")]
    return rec.build(
        sport=SPORT,
        subject={"bout_id": str(bout_id), "event_id": bout.get("event_id"), "start_utc": feat.iso_utc(start),
                 "fighter_a": a.name, "fighter_b": b.name, "weight_class": bout.get("weight_class")},
        as_of=feat.iso_utc(start),
        as_of_basis=("UFC bouts in the data store that started before this bout and have a result"
                     + (f" (the store begins {ctx.data_starts})" if ctx.data_starts else "")),
        families=FAMILIES, sides=SIDES, factors=factors, missing=gaps,
        coverage={"data_starts": ctx.data_starts,
                  "fights_a": len(a.fights), "fights_b": len(b.fights)},
        display=display)
