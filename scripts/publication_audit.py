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
# picks are STRONG is not a good night, it is a broken measurement. Set well
# above any plausible real rate so this fires on the pathological case only.
STRONG_SHARE_ALARM = 0.40
STRONG_SHARE_MIN_PICKS = 5

# The largest number of independent families anyone has VERIFIED can agree on
# one selection. Raising it is a deliberate act that must be justified in the
# commit that raises it -- that is the whole point of the constant.
DOCUMENTED_FAMILY_CEILING = 3

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


def main():
    date_iso = sys.argv[1] if len(sys.argv) > 1 else None
    findings = audit(date_iso)
    escalations = [m for sev, m in findings if sev == "ESCALATE"]
    for severity, message in findings:
        prefix = "ESCALATE: " if severity == "ESCALATE" else f"[{severity}] "
        print(f"{prefix}{message}")
    if not findings:
        print("publication audit: clean -- every published claim checks out")
    return 1 if escalations else 0


if __name__ == "__main__":
    raise SystemExit(main())
