"""Stage 18 join-integrity audit (2026-09-16).

The NFL outage (fixed at commit 9a45be1a) was a join that silently dropped
every row and returned an empty dict with no error. A copy sweep after that
fix flagged the MLB card's `_game_identity` vs `gamepayload.game_id()` as
possibly the same shape.

This module covers:
  * `src.joins.report_join_result` -- the shared helper that distinguishes
    an honest empty (one side had nothing to join) from an alarming zero
    (both sides non-empty, nothing matched) -- pure, no disk.
  * `src.report.card.card_for_date` -- proof the moneyline join is now
    WIRED to that helper: a slate and a priced board that are both
    non-empty but whose ids do not line up prints `ESCALATE: `, and a
    normal build (ids agree, or one side legitimately empty) stays quiet.
  * The real-data question the task asked first: `card._game_identity`'s
    `game_id` and `gamepayload.game_id()` now agree BY CONSTRUCTION (the
    former delegates to the latter) rather than by coincidence of today's
    data shape (every game on the 2026-09-16 real slate happened to carry
    `game_number: 1`, so both the old hand-rolled string and the shared
    function produced the same suffix -- see the docstring in
    `src/report/card.py::_game_identity` for the real-data check and the
    latent divergence it closed).
"""

from __future__ import annotations

import contextlib
import io
import unittest
from datetime import datetime, timezone

from src import joins
from src.report import card as card_mod

FUTURE = "2026-09-14T22:40:00Z"


def _entry(away="SD", home="COL", game_pk=744001, game_number=1,
          first_pitch=FUTURE):
    return {"dossier": {
        "game": {"away_team": away, "home_team": home, "game_pk": game_pk,
                 "game_number": game_number, "start_time_utc": first_pitch},
        "sections": {
            "teams": {
                "away_runs_scored_pg": 4.6, "away_runs_allowed_pg": 4.2,
                "away_games_played": 140,
                "home_runs_scored_pg": 4.8, "home_runs_allowed_pg": 4.1,
                "home_games_played": 140,
            },
            "starters": {},
        },
    }}


def _ml_row(game_id, side="away", price=-150, prob=0.6):
    return {
        "game_id": game_id, "side": side, "market": "h2h",
        "best_price": price, "best_book": "dk", "books": 8,
        "market_implied_probability": prob,
    }


class ReportJoinResultTests(unittest.TestCase):
    """Pure tests of the shared helper -- no card, no disk."""

    def _captured(self, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = joins.report_join_result(**kwargs)
        return ok, buf.getvalue()

    def test_both_sides_empty_stays_quiet(self):
        ok, out = self._captured(name="x", left=[], right=[], matched=[])
        self.assertTrue(ok)
        self.assertNotIn("ESCALATE:", out)

    def test_one_side_empty_stays_quiet(self):
        ok, out = self._captured(name="x", left=["a"], right=[], matched=[])
        self.assertTrue(ok)
        self.assertNotIn("ESCALATE:", out)

    def test_a_real_match_stays_quiet(self):
        ok, out = self._captured(name="x", left=["a"], right=["a"], matched=["a"])
        self.assertTrue(ok)
        self.assertNotIn("ESCALATE:", out)

    def test_both_sides_nonempty_and_zero_matches_escalates(self):
        ok, out = self._captured(name="my-join", left=["a", "b"],
                                 right=["c", "d"], matched=[])
        self.assertFalse(ok)
        self.assertTrue(out.startswith("ESCALATE: "))
        self.assertIn("my-join", out)


class CardMoneylineJoinWiring(unittest.TestCase):
    """`card_for_date`'s moneyline join, starved on purpose."""

    def test_starved_join_escalates_when_ids_cannot_possibly_match(self):
        """A slate entry and a priced moneyline row that are both real and
        non-empty, but whose ids were built two different ways, must print
        the alarming ESCALATE line -- this is the exact shape the NFL bug
        had. `game_id="totally-unrelated-key"` never matches anything
        `_game_identity` could produce for this entry, by construction."""
        now = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
        entries = [_entry()]
        opportunity_rows = [_ml_row("totally-unrelated-key")]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            card_mod.card_for_date(
                entries, opportunity_rows, date="2026-09-14", now=now,
                multibook_rows=[], prefer_frozen=False,
                prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        out = buf.getvalue()
        self.assertTrue(any(line.startswith("ESCALATE: ") for line in out.splitlines()),
                        f"expected an ESCALATE: line, got:\n{out}")

    def test_matching_ids_stay_quiet(self):
        """The normal case: the moneyline row's game_id is the SAME id
        `_game_identity` computes for this entry (gamepayload.game_id's
        construction) -- a real join, must not escalate."""
        now = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
        entries = [_entry()]
        gid = card_mod._game_identity(entries[0], date="2026-09-14")["game_id"]
        opportunity_rows = [_ml_row(gid, side="away"),
                            _ml_row(gid, side="home", prob=0.4)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            card_mod.card_for_date(
                entries, opportunity_rows, date="2026-09-14", now=now,
                multibook_rows=[], prefer_frozen=False,
                prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        out = buf.getvalue()
        self.assertFalse(any(line.startswith("ESCALATE: ") for line in out.splitlines()),
                         f"did not expect an ESCALATE: line, got:\n{out}")

    def test_no_priced_board_at_all_stays_quiet_the_honest_empty(self):
        """No moneyline rows at all (nobody has posted prices yet) is the
        HONEST empty this surface already reports via `_reason` -- it must
        never print ESCALATE, which would misfile a quiet morning as a bug."""
        now = datetime(2026, 9, 14, 16, 0, tzinfo=timezone.utc)
        entries = [_entry()]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            card_mod.card_for_date(
                entries, [], date="2026-09-14", now=now, multibook_rows=[],
                prefer_frozen=False,
                prop_board=lambda d: {"contracts": [], "reason": "n/a"})
        out = buf.getvalue()
        self.assertFalse(any(line.startswith("ESCALATE: ") for line in out.splitlines()),
                         f"did not expect an ESCALATE: line, got:\n{out}")


class RealDataIdConstructionAgreement(unittest.TestCase):
    """`_game_identity`'s `game_id` now DELEGATES to `gamepayload.game_id`,
    so agreement holds by construction, not by coincidence -- this pins
    that down against a shape that used to be able to diverge: a game with
    no `game_number` and no `game_pk` at all."""

    def test_no_number_no_pk_still_agrees(self):
        from src.analysis import gamepayload

        entry = {"dossier": {"game": {"away_team": "SD", "home_team": "COL"},
                             "sections": {}}}
        identity = card_mod._game_identity(entry, date="2026-09-14")
        expected = gamepayload.game_id(
            {"away_team": "SD", "home_team": "COL", "date": "2026-09-14"})
        self.assertEqual(expected, identity["game_id"])
        # Before the fix this function always appended "-1" regardless of
        # whether a marker existed; the shared function appends nothing
        # when neither game_number nor game_pk is present.
        self.assertEqual("SD-COL-2026-09-14", identity["game_id"])


if __name__ == "__main__":
    unittest.main()
