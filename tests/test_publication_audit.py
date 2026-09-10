"""The publication audit must catch the failure it was written for.

This is the point of the whole file. On 2026-09-09 the site published 23
picks for games that were already in progress or final, and a customer found
it before we did. An audit that only passes on clean data proves nothing --
so the central test replays the REAL slip that shipped that night, at the
real clock time a reader was looking at it, and requires an ESCALATE.

If someone later loosens the audit, this goes red with the original slip in
the failure message.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.publication_audit import (
    DOCUMENTED_FAMILY_CEILING,
    SLIP_STALE_MINUTES,
    STRONG_SHARE_MIN_PICKS,
    audit_slip,
)

REPO = Path(__file__).resolve().parents[1]
SLIPS = REPO / "evidence" / "slips_v1.jsonl"

# The slip Jacob was reading, and roughly when he read it.
INCIDENT_DATE = "2026-09-09"
INCIDENT_SLIP_UTC = "2026-09-09T23:17:43.953049+00:00"
INCIDENT_NOW = datetime(2026, 9, 9, 23, 30, tzinfo=timezone.utc)


def _severities(findings):
    return {sev for sev, _ in findings}


def _slip(date_iso, slip_utc):
    with open(SLIPS, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("date") == date_iso and row.get("slip_utc") == slip_utc:
                return row
    return None


def _synthetic(picks, slip_utc=INCIDENT_SLIP_UTC):
    return {"date": INCIDENT_DATE, "slip_utc": slip_utc, "picks": picks}


def _pick(rank=1, tier="MINIMAL", families=1, market="h2h", event="e1"):
    return {"rank": rank, "evidence_tier": tier, "n_families": families,
            "market_key": market, "event_id": event}


class IncidentReplay(unittest.TestCase):
    """The real slip, the real clock, the real games."""

    def setUp(self):
        self.slip = _slip(INCIDENT_DATE, INCIDENT_SLIP_UTC)
        if self.slip is None:
            self.skipTest(f"incident slip {INCIDENT_SLIP_UTC} not in the "
                          f"ledger on this checkout")

    def test_incident_slip_escalates(self):
        """Some ESCALATE must fire on the slip that shipped 21 dead games.

        Deliberately not asserting on schedule state -- that would need a
        network call. The tier alarms alone were enough to catch this hours
        before the customer did, which is itself the finding: the evidence
        was on the slip the whole time.
        """
        findings = audit_slip(self.slip, lambda _e: None, None, INCIDENT_NOW)
        self.assertIn("ESCALATE", _severities(findings),
                      f"the audit passed the incident slip:\n"
                      + "\n".join(f"  [{s}] {m}" for s, m in findings))

    def test_incident_slip_flags_the_tier_anomaly(self):
        """17 of 23 STRONG and families well past the ceiling."""
        findings = audit_slip(self.slip, lambda _e: None, None, INCIDENT_NOW)
        blob = " ".join(m for _s, m in findings)
        self.assertIn("STRONG", blob)
        self.assertIn("independent families", blob)


class StartedGames(unittest.TestCase):
    """Claim 1 in isolation, with a hand-built world."""

    def _world(self, state, start_offset_minutes, detailed=None):
        start = INCIDENT_NOW + timedelta(minutes=start_offset_minutes)
        game = {"game_pk": 776, "state": state,
                "detailed_state": detailed or state,
                "start_time_utc": start.isoformat(),
                "away_team": "NYM", "home_team": "PHI",
                "away_score": 8, "home_score": 0}
        return (lambda _e: "776"), {"776": game}

    def test_final_game_escalates(self):
        resolve, schedule = self._world("final", -180, "Final")
        findings = audit_slip(_synthetic([_pick()]), resolve, schedule,
                              INCIDENT_NOW)
        self.assertIn("ESCALATE", _severities(findings))

    def test_in_progress_game_escalates(self):
        """Coarse state is still 'pending' mid-game -- the clock catches it."""
        resolve, schedule = self._world("pending", -60, "In Progress")
        findings = audit_slip(_synthetic([_pick()]), resolve, schedule,
                              INCIDENT_NOW)
        self.assertIn("ESCALATE", _severities(findings))

    def test_scheduled_game_is_clean(self):
        resolve, schedule = self._world("pending", +90, "Scheduled")
        findings = audit_slip(_synthetic([_pick()]), resolve, schedule,
                              INCIDENT_NOW)
        self.assertNotIn("ESCALATE", _severities(findings))

    def test_postponement_is_not_a_started_game(self):
        """A postponed game never started; it is a stand-down question, and
        escalating it would train us to ignore this alarm."""
        resolve, schedule = self._world("cancelled", -60, "Postponed")
        findings = audit_slip(_synthetic([_pick()]), resolve, schedule,
                              INCIDENT_NOW)
        self.assertNotIn("ESCALATE", _severities(findings))

    def test_unresolvable_event_warns_rather_than_passing_silently(self):
        findings = audit_slip(_synthetic([_pick()]), lambda _e: None, {},
                              INCIDENT_NOW)
        self.assertIn("WARN", _severities(findings))


class TierAlarms(unittest.TestCase):

    def test_share_alarm_needs_enough_picks_to_mean_anything(self):
        """1 of 2 is 50% and says nothing."""
        picks = [_pick(1, "STRONG", DOCUMENTED_FAMILY_CEILING), _pick(2)]
        findings = audit_slip(_synthetic(picks), lambda _e: None, None,
                              INCIDENT_NOW)
        self.assertNotIn("ESCALATE", _severities(findings))

    def test_share_alarm_fires_on_a_full_slate(self):
        picks = [_pick(i, "STRONG", DOCUMENTED_FAMILY_CEILING)
                 for i in range(STRONG_SHARE_MIN_PICKS)]
        findings = audit_slip(_synthetic(picks), lambda _e: None, None,
                              INCIDENT_NOW)
        self.assertIn("ESCALATE", _severities(findings))

    def test_families_past_the_ceiling_escalate_even_on_one_pick(self):
        picks = [_pick(1, "BUILDING", DOCUMENTED_FAMILY_CEILING + 1)]
        findings = audit_slip(_synthetic(picks), lambda _e: None, None,
                              INCIDENT_NOW)
        self.assertIn("ESCALATE", _severities(findings))

    def test_at_the_ceiling_is_clean(self):
        picks = [_pick(1, "STRONG", DOCUMENTED_FAMILY_CEILING)]
        findings = audit_slip(_synthetic(picks), lambda _e: None, None,
                              INCIDENT_NOW)
        self.assertEqual(set(), _severities(findings))


class DoctrineClaims(unittest.TestCase):

    def test_non_genome_market_escalates(self):
        """genome.MARKETS is h2h and h2h_1st_5_innings. A published spread
        means an instrument is being sold as a pick -- Jacob's Mets -2.5."""
        findings = audit_slip(_synthetic([_pick(market="spreads")]),
                              lambda _e: None, None, INCIDENT_NOW)
        self.assertIn("ESCALATE", _severities(findings))
        self.assertIn("spreads", " ".join(m for _s, m in findings))

    def test_stale_slip_warns(self):
        old = (INCIDENT_NOW
               - timedelta(minutes=SLIP_STALE_MINUTES + 30)).isoformat()
        findings = audit_slip(_synthetic([_pick()], slip_utc=old),
                              lambda _e: None, None, INCIDENT_NOW)
        self.assertIn("WARN", _severities(findings))

    def test_fresh_slip_is_clean(self):
        fresh = (INCIDENT_NOW - timedelta(minutes=5)).isoformat()
        findings = audit_slip(_synthetic([_pick()], slip_utc=fresh),
                              lambda _e: None, None, INCIDENT_NOW)
        self.assertEqual(set(), _severities(findings))


if __name__ == "__main__":
    unittest.main()
