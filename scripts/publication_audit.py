#!/usr/bin/env python3
"""Audit what the product is CLAIMING right now, not what the code does.

WHY THIS EXISTS
----------------
On 2026-09-09 the site published 23 picks, 21 of them for games already in
progress or final, including one labelled STRONG next to a game sitting at
8-0. A customer found it. Nobody here did.

That day had heavy verification behind it -- mutation tests on the tier
function, the join key, the class filter, the dedup, the cadence gate; four
separate browser sessions reading the live DOM. Every one of those checks
asked the same question: DOES THIS CODE DO WHAT I INTENDED? A slip full of
finished games passes all of them. Not one check asked the question a reader
would ask first: IS THIS TRUE RIGHT NOW?

That is the gap this script exists to close. It reads the published
artifacts -- the slip ledger, the record strip, the opportunities surface --
and interrogates the CLAIMS they make against the world as it currently is.
It knows nothing about the implementation and deliberately re-derives every
number independently rather than importing the function that produced it: a
check that calls the code under test is an echo, not an audit.

IT IS NOT A TEST SUITE. Tests pin intent. This pins truth, and truth has a
clock in it -- the same slip that was correct at 19:00Z is a lie at 23:30Z.
Anything here can be true at one instant and false an hour later with no
code change at all, which is exactly why it has to run on a cadence rather
than in CI.

EXIT CODES: 0 clean, 1 findings. Prints ESCALATE lines the capture cadence
already greps for.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SLIPS = REPO / "evidence" / "slips_v1.jsonl"

# A tier the product declares RARE must not fire routinely. src/engine/slip.py
# sets STRONG at "3+ independent families agree" and its own comment says the
# whole-ledger historical ceiling is 3 -- so a night where most published
# picks are STRONG is not a good night, it is a broken measurement.
#
# THE MINIMUM WAS 5 AND THAT IS WHY IT NEVER FIRED. On 2026-09-10 the engine
# published 14 picks across the day, EVERY ONE of them STRONG, and this check
# stayed silent throughout because no single slip carried five. A rare-tier
# alarm that needs five picks cannot see a day of one- and two-pick slips,
# which is exactly the shape a selective engine produces. Three is enough to
# tell "all of them" from "one of them".
STRONG_SHARE_ALARM = 0.40
STRONG_SHARE_MIN_PICKS = 3

# The largest number of independent families anyone has VERIFIED can agree on
# one selection. Raising it is a deliberate act that must be justified in the
# commit that raises it -- that is the whole point of the constant.
#
# RAISED FROM 3 TO 16 ON 2026-09-10, and the verification is the reason:
#
#   * The "3" came from a 2026-09-08 measurement, recorded in slip.py's own
#     comment. On that date essentially NOTHING forward-test played, so it
#     was the ceiling of a population of almost zero.
#   * By 2026-09-10 the engine ran 166 forward-test decisions from 29
#     distinct systems that played. More systems agreeing is the arithmetic
#     consequence, not an anomaly.
#   * The obvious alternative -- a structure-blind clustering counting
#     near-duplicates as independent -- was checked and REFUTED. The
#     clustering is collapsing: 22 systems into 16 families, 17 into 14, 6
#     into 6. A structure-blind run would collapse nothing anywhere.
#   * The day's largest observed value is 16, from 22 backing systems.
#
# So this ceiling is now descriptive of a real population. What it does NOT
# settle is whether EVIDENCE_STRONG firing at 3+ families still means
# anything -- see THE_STRONG_TIER_IS_NO_LONGER_RARE below.
DOCUMENTED_FAMILY_CEILING = 16

# THE CEILING ABOVE IS A RATCHET, AND A RATCHET CANNOT CATCH THE NEXT ONE.
#
# Raising it to today's largest observation means it cannot fire on today's
# data by construction. That is honest for what the constant claims to be --
# "the largest anyone has verified" -- and it is useless as a detector, for
# the same reason every threshold set to the largest observed value is
# useless.
#
# So the real guard is this one, and it is population-independent. A
# structure-blind clustering has a signature that does not depend on how many
# systems exist: EVERY SYSTEM BECOMES ITS OWN FAMILY. Nothing merges.
#
#   22 systems -> 16 families    collapsing, healthy
#    4 systems ->  4 families    collapsed nothing, and legitimate: four
#                                genuinely distinct systems agreed
#   22 systems -> 22 families    collapsed nothing at 22, which cannot be
#                                right in a population with known
#                                structural twins
#
# Zero collapse is unremarkable on a handful of systems and implausible on
# many. Eight is where "these four happen to be distinct" stops being the
# easy explanation. The threshold is about the ARITHMETIC of the clustering,
# not about how good tonight's picks are, so it does not drift as the
# population grows.
COLLAPSE_CHECK_MIN_SYSTEMS = 8

# EVERY PICK PUBLISHED ON 2026-09-10 WAS STRONG. Fourteen of fourteen, at
# family counts of 4, 6, 13, 14, 15 and 16 against a threshold of 3.
#
# EVIDENCE_STRONG's own comment in src/engine/slip.py justifies the 3 by
# saying 3 is "the strongest agreement ever measured on this project's live
# ledger, across its whole history". That was true on 2026-09-08 and stopped
# being true the moment the engine started playing. A tier calibrated to the
# ceiling of a population that no longer exists now fires on everything, and
# a label that fires on everything tells a reader nothing.
#
# THIS FILE DOES NOT PICK A NEW THRESHOLD. slip.py's own words: "a threshold
# picked to produce a target number of picks is the purest form of the thing
# this project's whole research discipline exists to resist." Choosing 12
# because it would make today's picks look selective is that, exactly.
#
# What it does is refuse to let the condition pass silently.
STRONG_TIER_RECALIBRATION_OWED = True

# A published slip is a live recommendation. Past this age it is stale
# regardless of game states, because prices have moved even if nothing
# started.
SLIP_STALE_MINUTES = 180


def _parse_utc(value):
    if not value:
        return None
    v = str(value)
    v = v.replace("Z", "+00:00") if v.endswith("Z") else v
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _read_jsonl(path):
    if not Path(path).exists():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def latest_slip(date_iso):
    rows = [r for r in _read_jsonl(SLIPS) if r.get("date") == date_iso]
    return rows[-1] if rows else None


def audit_slip(slip, resolve, schedule, now):
    """The claim checks, as a pure function, so the regression test can run
    the real 2026-09-09 slip through them without a network call.

    `resolve` maps an event_id to a game_pk string; `schedule` maps that
    string to a parsed game record. Passing both in rather than importing
    them keeps this honest about what it actually depends on -- and lets the
    test pin the exact world state that produced the failure.

    Every finding is a (severity, message) pair. ESCALATE is customer-visible
    wrongness; WARN is worth a look before it becomes that.
    """
    findings = []
    picks = slip.get("picks") or []
    slip_utc = _parse_utc(slip.get("slip_utc"))

    # ---- CLAIM 1: every published pick is still actionable ---------------
    # The 2026-09-09 failure, verbatim.
    if schedule is not None:
        started = []
        unresolved = []
        for p in picks:
            pk = resolve(p.get("event_id"))
            game = schedule.get(str(pk)) if pk else None
            if game is None:
                unresolved.append(p.get("rank"))
                continue
            # Two independent signals, either one damning: the coarse state
            # the settle path itself trusts, and the clock. A postponement is
            # neither -- it has not started and never will tonight, so it is
            # a stand-down question, not a false-live-pick question.
            start = _parse_utc(game.get("start_time_utc"))
            coarse = game.get("state")
            detail = game.get("detailed_state") or coarse
            if coarse == "cancelled":
                continue
            if coarse == "final" or (start and start <= now):
                started.append(
                    f"#{p.get('rank')} {game.get('away_team')}@"
                    f"{game.get('home_team')} [{detail}] "
                    f"{game.get('away_score')}-{game.get('home_score')}")
        if started:
            findings.append((
                "ESCALATE",
                f"{len(started)} of {len(picks)} PUBLISHED picks are for "
                f"games already started or final -- the page is presenting "
                f"settled outcomes as live recommendations: "
                + "; ".join(started[:6])
                + (f" (+{len(started) - 6} more)" if len(started) > 6 else "")))
        if unresolved:
            findings.append((
                "WARN", f"{len(unresolved)} published pick(s) could not be "
                        f"resolved to a scheduled game: ranks {unresolved}"))

    # ---- CLAIM 2: a tier declared rare is behaving rarely ----------------
    if picks:
        n_strong = sum(1 for p in picks if p.get("evidence_tier") == "STRONG")
        share = n_strong / len(picks)
        # Share needs enough picks to mean anything -- 1 of 2 is 50% and says
        # nothing. Below the floor the per-pick check below still runs, so a
        # thin slate cannot hide an impossible claim.
        if len(picks) >= STRONG_SHARE_MIN_PICKS and share >= STRONG_SHARE_ALARM:
            findings.append((
                "ESCALATE",
                f"{n_strong} of {len(picks)} published picks are STRONG "
                f"({share:.0%}). STRONG means 3+ INDEPENDENT families agree "
                f"and src/engine/slip.py documents the whole-ledger ceiling "
                f"as {DOCUMENTED_FAMILY_CEILING}. A rare grade firing this "
                f"often is a broken measurement, not a good night -- check "
                f"the clustering before believing any of it"))

        # THE STANDING DEBT, reported on every run until it is paid. Not
        # conditional on today's slate: the threshold is miscalibrated
        # whether or not any pick happens to clear it tonight, and a check
        # that goes quiet on an empty night is a check that gets forgotten.
        if STRONG_TIER_RECALIBRATION_OWED:
            findings.append((
                "WARN",
                "EVIDENCE_STRONG still fires at 3+ families, a threshold set "
                "when the ceiling of the whole ledger was 3. On 2026-09-10 "
                "the verified ceiling was 16 and every published pick was "
                "STRONG. The label currently distinguishes nothing. "
                "Recalibrating it is a deliberate decision that must not be "
                "made by picking whatever number flatters tonight's picks -- "
                "see this file's STRONG_TIER_RECALIBRATION_OWED"))

        # This one is ESCALATE rather than WARN on purpose. The temptation on
        # 2026-09-09 was to reason about how a grown population MIGHT justify
        # a surprising number, and ship. The only way to clear this alarm is
        # to verify the clustering and then RAISE the documented ceiling in
        # source -- which forces the explanation to be written down where the
        # next reader can check it, instead of dissolving in a chat message.
        worst = max((p.get("n_families") or 0) for p in picks)
        if worst > DOCUMENTED_FAMILY_CEILING:
            findings.append((
                "ESCALATE",
                f"a published pick claims {worst} independent families agree; "
                f"the documented ceiling is {DOCUMENTED_FAMILY_CEILING}. "
                f"Either the clustering is collapsing too little (near-"
                f"duplicate genomes counted as independent, which manufactures "
                f"exactly the confidence doctrine amendment 9 forbids), or the "
                f"ceiling is genuinely higher now -- verify which, then raise "
                f"DOCUMENTED_FAMILY_CEILING with the reason"))

        # THE CHECK THAT DOES NOT DRIFT. A structure-blind clustering makes
        # every system its own family and merges nothing, and that signature
        # is the same whatever the population size -- unlike the ceiling
        # above, which stops being able to fire the moment it is raised to
        # the largest thing anyone has seen.
        for pick in picks:
            families = pick.get("n_families")
            systems = pick.get("n_systems")
            if not isinstance(families, int) or not isinstance(systems, int):
                continue
            if systems < COLLAPSE_CHECK_MIN_SYSTEMS or families != systems:
                continue
            findings.append((
                "ESCALATE",
                f"pick #{pick.get('rank')} is backed by {systems} systems in "
                f"{families} families -- the clustering merged NOTHING at "
                f"that size. On a population with known structural twins "
                f"(every first-five genome is a feature-set twin of an h2h "
                f"one) that is the signature of a structure-blind run, and "
                f"the agreement count behind this pick is a raw system count "
                f"wearing a family count's name"))

    # ---- CLAIM 3: the slip is fresh enough to be a recommendation --------
    if slip_utc and (now - slip_utc) > timedelta(minutes=SLIP_STALE_MINUTES):
        age = (now - slip_utc).total_seconds() / 60.0
        findings.append((
            "WARN", f"the published slip is {age:.0f} minutes old (limit "
                    f"{SLIP_STALE_MINUTES}); prices have moved under it"))

    # ---- CLAIM 3b: the slip does not contradict itself -------------------
    # Found on 2026-09-10 by reading the live slip instead of the code: the
    # two published picks were opposite sides of CIN@LAD, both tagged TOP_3.
    # A reader who takes the slip at its word bets both sides and loses the
    # vig with certainty. Nothing upstream forbade it, because each side
    # cleared the evidence bar on its own and the ranker never asked whether
    # rank 1 and rank 2 could both be right.
    by_event = {}
    for p in picks:
        by_event.setdefault(p.get("event_id"), []).append(p)
    for eid, group in by_event.items():
        if len(group) < 2:
            continue
        markets = {p.get("market_key") for p in group}
        sides = {p.get("selection_id") for p in group}
        ranks = sorted(str(p.get("rank")) for p in group)
        if len(markets) == 1 and len(sides) > 1:
            findings.append((
                "ESCALATE",
                f"picks #{', #'.join(ranks)} are OPPOSITE SIDES of the same "
                f"{markets.pop()} market on event {eid} -- the slip is "
                f"recommending both teams; a reader who follows it loses the "
                f"hold with certainty"))
        else:
            # Same game, different markets (h2h and the F5 h2h, say). Not a
            # contradiction, but not two independent picks either -- a Top 3
            # holding two correlated bets overstates its own diversification.
            findings.append((
                "WARN",
                f"picks #{', #'.join(ranks)} are all on event {eid} "
                f"({sorted(markets)}); correlated positions presented as "
                f"separate ranked picks"))

    # ---- CLAIM 4: nothing published contradicts the doctrine -------------
    # Spreads and totals are not expressible as a genome (genome.MARKETS is
    # h2h and h2h_1st_5_innings only), so a published pick on one would mean
    # something upstream is mislabelling an instrument as a product pick.
    off_market = [p.get("market_key") for p in picks
                  if p.get("market_key") not in ("h2h", "h2h_1st_5_innings")]
    if off_market:
        findings.append((
            "ESCALATE", f"published picks on markets no genome can express: "
                        f"{sorted(set(off_market))} -- doctrine says spreads "
                        f"and totals are covered by null controls only"))

    return findings


def audit(date_iso=None, now=None):
    """Load today's published slip and the real world, then check the claims.

    The I/O lives here and only here; `audit_slip` above does the judging.
    The schedule is fetched through the same provider the settle path uses,
    NOT through slip.py's own commence-time map -- if that map is what is
    broken, importing it would reproduce the bug rather than catch it.
    """
    now = now or datetime.now(timezone.utc)
    date_iso = date_iso or now.date().isoformat()

    slip = latest_slip(date_iso)
    if slip is None:
        # Not automatically wrong -- no slate may have run yet today. Said
        # out loud rather than passed over, because "no slip" and "a slip
        # with no picks" are different facts and only one of them is normal.
        return [("INFO", f"no slip published for {date_iso} yet")]

    try:
        from src.board import gamekey
        from src.providers import mlb
        gk_map = gamekey.load_map()
        # Keyed by str: game_pk_for_event returns the canonical string form
        # while parse_game keeps the raw int, and an int/str mismatch here
        # would silently resolve nothing and report a clean slip.
        schedule = {str(g.get("game_pk")): g for g in mlb.fetch_games(date_iso)}

        def resolve(event_id):
            return gamekey.game_pk_for_event(event_id, gk_map)
    except Exception as exc:  # noqa: BLE001
        return ([("WARN", f"schedule unavailable, cannot verify game states: "
                          f"{exc}")]
                + audit_slip(slip, lambda _e: None, None, now))

    return audit_slip(slip, resolve, schedule, now)


# THE CARD'S OWN CHECKS.
#
# The card became the headline surface on 2026-09-10 -- it is the first
# thing a paying reader sees and the only thing most of them will read. An
# audit that asks "is what the page claims true right now" and does not look
# at it is auditing last month's front page.
#
# Every check below is a way the card can be WRONG WHILE LOOKING FINE, which
# is the only failure mode worth an audit. A card that fails to build is
# loud on its own.
CARD_STALE_MINUTES = 240

# How old the Platt fit may get before its numbers stop describing the
# model. It is refit nightly; a week means the loop has been failing quietly
# for a week, and every published probability has been drifting from the
# model's real accuracy that whole time.
CALIBRATION_STALE_DAYS = 7


def audit_card(date_iso, now):
    """The published card for `date_iso`, checked against the world."""
    from src.appstate import card_ledger
    from src.report import card as card_mod

    findings = []

    published = card_ledger.published_row(date_iso)
    if published is None:
        # Normal before the afternoon pass. Stated rather than skipped: "no
        # card yet" and "a card with no picks" are different facts.
        findings.append(("INFO", f"no card published for {date_iso} yet"))
    else:
        picks = published.get("picks") or []
        if len(picks) < 3:
            findings.append((
                "ESCALATE",
                f"the published card for {date_iso} carries {len(picks)} "
                f"pick(s); the floor is 3 and it is met by lowering the "
                f"LABEL, never by publishing fewer"))

        # Started games. The 2026-09-09 failure, on the new surface: the
        # card is frozen once and then served for the rest of the day, so
        # nothing stops it presenting a game in the sixth inning as a live
        # recommendation.
        started = []
        for pick in picks:
            first_pitch = _parse_utc(pick.get("first_pitch_utc"))
            if first_pitch is None:
                findings.append((
                    "WARN",
                    f"card pick #{pick.get('rank')} has no first-pitch time, "
                    f"so whether it is still actionable cannot be checked"))
            elif first_pitch <= now:
                started.append(pick)
        if started:
            findings.append((
                "WARN",
                f"{len(started)} of {len(picks)} card picks are for games "
                f"that have already started -- the card is frozen by design, "
                f"but the page must not present these as live"))

        published_at = _parse_utc(published.get("published_utc"))
        if published_at is not None:
            age = (now - published_at).total_seconds() / 60.0
            if age > CARD_STALE_MINUTES and len(started) < len(picks):
                findings.append((
                    "WARN",
                    f"the card was frozen {age:.0f} minutes ago (limit "
                    f"{CARD_STALE_MINUTES}); the prices on it are quoted "
                    f"from that instant and books move"))

        # A pick with no book or no price is an instruction a reader cannot
        # act on, which is worse than no pick.
        for pick in picks:
            if pick.get("price") is None or not pick.get("book"):
                findings.append((
                    "ESCALATE",
                    f"card pick #{pick.get('rank')} ({pick.get('bet')}) "
                    f"carries no price or no book -- it names a bet nobody "
                    f"can place"))

        if published.get("calibrated") is False:
            findings.append((
                "ESCALATE",
                f"the card for {date_iso} was published UNCALIBRATED. Its "
                f"own probabilities run about twice as confident as the "
                f"model's accuracy earns, under the same words a calibrated "
                f"card uses"))

    # The calibration file itself, independently of any card.
    cal_path = REPO / card_mod.CALIBRATION_STORE
    if not cal_path.exists():
        findings.append((
            "ESCALATE",
            f"{card_mod.CALIBRATION_STORE} is missing; every card built "
            f"from here serves the raw model's overconfident numbers"))
    else:
        try:
            blob = json.loads(cal_path.read_text(encoding="utf-8"))
            fitted_at = _parse_utc(blob.get("fitted_at"))
        except (OSError, ValueError):
            findings.append((
                "ESCALATE",
                f"{card_mod.CALIBRATION_STORE} could not be read"))
            fitted_at = None
        if fitted_at is not None:
            days = (now - fitted_at).total_seconds() / 86400.0
            if days > CALIBRATION_STALE_DAYS:
                findings.append((
                    "WARN",
                    f"the card calibration was last fit {days:.0f} days ago "
                    f"(limit {CALIBRATION_STALE_DAYS}) -- the nightly refit "
                    f"in scripts/daily_loop.sh has been failing quietly"))

    # THE LEDGER MUST STILL BE A CHAIN. A published record whose chain is
    # broken is not a record, and the page that shows it has to know.
    chain = card_ledger.verify()
    if not getattr(chain, "ok", True):
        findings.append((
            "ESCALATE",
            f"the card ledger's hash chain is broken: {chain}"))

    return findings


def main():
    date_iso = sys.argv[1] if len(sys.argv) > 1 else None
    findings = audit(date_iso)
    try:
        findings = findings + audit_card(
            date_iso or datetime.now(timezone.utc).date().isoformat(),
            datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        # An audit that dies takes the whole check down and reports CLEAN by
        # absence, which is the one outcome this file exists to prevent.
        findings = findings + [
            ("ESCALATE", f"the card audit itself failed to run: {exc!r}")]
    escalations = [m for sev, m in findings if sev == "ESCALATE"]
    for severity, message in findings:
        prefix = "ESCALATE: " if severity == "ESCALATE" else f"[{severity}] "
        print(f"{prefix}{message}")
    if not findings:
        print("publication audit: clean -- every published claim checks out")
    return 1 if escalations else 0


if __name__ == "__main__":
    raise SystemExit(main())
