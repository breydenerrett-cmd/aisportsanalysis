"""Activation is a product action, not a sign-in (owner decision, 2026-10-03).

The owner's rule: "Define ACTIVATED as a meaningful product action, not account
creation... Track time: SIGNUP -> ACTIVATION" and "Track whether testers
actually click/use: moneylines, props, postseason forecasts, NFL, UFC, deep
matchup analysis, price comparison."

src/appstate/activation.py holds the definitions; src/appstate/testers.py turns
them into the per-tester rows and the aggregate. This file pins them without
FastAPI (src/ is stdlib only): the route half, which proves the real API
records what it claims to, is tests/test_activation_routes.py.

What is pinned here, and why each is easy to get quietly wrong:

  * redeeming a token is NOT activation; the first value action is;
  * RETURNING needs 12 hours (13 yes, 12 yes, 11:59 no, 2 no);
  * active days are distinct UTC dates, not events;
  * only page_view events carrying a KNOWN feature count: a route-only
    page_view, another kind with a `feature` key, an unknown label and another
    person's events do not;
  * the read is ONE bounded, grouped SQL statement filtered by kind and by the
    tester hashes: it never reads the events table into Python;
  * the aggregate has every label (zeros included), no email and no user id,
    leaves our own test accounts out and says how many, and says which labels
    nothing can record yet so a zero is not read as "nobody used it".
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.appstate import activation
from src.appstate import attribution
from src.appstate import customers
from src.appstate import events
from src.appstate import testers
from src.appstate import users as users_store

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.isoformat()


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "app.db"

    def grant(self, i=1, *, now=T0):
        return testers.grant_tester(email=f"tester{i}@example.com", now=now, db=self.db)

    def act(self, user_id, surface="card", when=T0, *, sport="mlb", route="card"):
        """One value action at an explicit instant, through the real recorder."""
        activation.record_value_action(user_id, surface, route=route, date="2026-10-05",
                                       sport=sport, at=iso(when), db=self.db)

    def raw(self, user_id, kind, properties, when=T0):
        events.record_event(events.hash_user_id(user_id), kind, properties,
                            at=iso(when), db=self.db)

    def row(self, grant):
        rows = {r["user_id"]: r for r in testers.list_testers(db=self.db)["testers"]}
        return rows[grant.user_id]

    def report(self, now=T0 + timedelta(days=1)):
        return testers.activation_report(now=now, db=self.db)


class TheLabels(unittest.TestCase):
    def test_the_label_set_is_fixed_and_ordered(self):
        self.assertEqual(activation.FEATURES, (
            "card", "matchup", "moneyline", "props", "prices", "postseason",
            "nfl", "ufc", "slate"))

    def test_a_label_nothing_can_record_is_named_not_left_as_a_silent_zero(self):
        self.assertEqual(activation.UNMEASURED_FEATURES, ("moneyline",))
        self.assertEqual(set(activation.MEASURED_FEATURES) | set(activation.UNMEASURED_FEATURES),
                         set(activation.FEATURES))

    def test_the_sport_a_route_served_picks_the_most_specific_label(self):
        self.assertEqual(activation.feature_for("card", "nfl"), "nfl")
        self.assertEqual(activation.feature_for("card", "mma"), "ufc")
        self.assertEqual(activation.feature_for("card", "mlb"), "card")
        self.assertEqual(activation.feature_for("slate", "nfl"), "nfl")
        self.assertEqual(activation.feature_for("props", None), "props")
        self.assertEqual(activation.value_properties("card", "mma"),
                         {"feature": "ufc", "surface": "card", "sport": "mma"})

    def test_an_unknown_surface_is_refused(self):
        with self.assertRaises(ValueError):
            activation.feature_for("tennis")


class TheRecorder(_Base):
    def test_a_value_action_is_one_page_view_with_the_feature_the_surface_and_the_sport(self):
        user = self.grant()
        self.act(user.user_id, "card", sport="nfl", route="card")
        recorded = events.list_events(db=self.db)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0].kind, events.PAGE_VIEW)
        self.assertEqual(recorded[0].user_hash, events.hash_user_id(user.user_id))
        self.assertEqual(recorded[0].properties, {
            "route": "card", "date": "2026-10-05",
            "feature": "nfl", "surface": "card", "sport": "nfl"})

    def test_no_user_records_nothing(self):
        """An anonymous caller has no user id; nothing may be recorded for one."""
        activation.record_value_action(None, "card", route="card", db=self.db)
        self.assertEqual(events.list_events(db=self.db), [])

    def test_an_unknown_surface_costs_a_data_point_never_the_request(self):
        err = mock.patch.object(sys, "stderr", new=mock.Mock())
        with err:
            activation.record_value_action(7, "not-a-surface", route="x", db=self.db)
        self.assertEqual(events.list_events(db=self.db), [])

    def test_a_broken_events_database_never_raises_into_a_route(self):
        with mock.patch.object(events, "record_event", side_effect=RuntimeError("disk full")), \
                mock.patch.object(sys, "stderr", new=mock.Mock()):
            activation.record_value_action(7, "card", route="card", db=self.db)

    def test_the_raw_id_is_hashed_and_never_stored(self):
        activation.record_value_action(424242, "props", route="/props", db=self.db)
        blob = json.dumps([(e.user_hash, e.properties) for e in events.list_events(db=self.db)])
        self.assertNotIn("424242", blob)


class TokenRedemptionIsNotActivation(_Base):
    def test_a_sign_in_alone_leaves_the_tester_unactivated(self):
        user = self.grant()
        users_store.mark_token_first_used(user.token, at=iso(T0 + timedelta(hours=1)),
                                          db=self.db)
        row = self.row(user)
        self.assertEqual(row["first_used_at"], iso(T0 + timedelta(hours=1)))
        self.assertEqual(row["first_signin_at"], iso(T0 + timedelta(hours=1)))
        self.assertFalse(row["activated"])
        self.assertIsNone(row["activated_at"])
        self.assertIsNone(row["hours_signup_to_activation"])
        self.assertIsNone(row["last_active_at"])
        self.assertEqual((row["active_days"], row["returning"], row["features"]),
                         (0, False, {}))
        self.assertEqual(self.report()["activated"], 0)

    def test_the_invite_redeemed_event_is_not_a_value_action_either(self):
        user = self.grant()
        self.raw(user.user_id, events.INVITE_REDEEMED, {}, T0 + timedelta(hours=1))
        self.assertFalse(self.row(user)["activated"])

    def test_the_first_value_action_activates(self):
        user = self.grant()
        users_store.mark_token_first_used(user.token, at=iso(T0 + timedelta(hours=1)),
                                          db=self.db)
        self.act(user.user_id, "card", T0 + timedelta(hours=5, minutes=30))
        row = self.row(user)
        self.assertTrue(row["activated"])
        self.assertEqual(row["activated_at"], iso(T0 + timedelta(hours=5, minutes=30)))
        self.assertEqual(row["first_signin_at"], iso(T0 + timedelta(hours=1)),
                         "the sign-in is kept as its own fact")
        self.assertEqual(row["hours_signup_to_activation"], 5.5)
        self.assertEqual(row["account_created_at"], iso(T0))
        self.assertEqual(row["tester_granted_at"], iso(T0))
        self.assertEqual(self.report()["activated"], 1)

    def test_activating_without_ever_signing_in_still_counts(self):
        """A value action is the action; the sign-in marker is not a prerequisite
        (it is best-effort and can be lost)."""
        user = self.grant()
        self.act(user.user_id, "matchup", T0 + timedelta(hours=2))
        row = self.row(user)
        self.assertTrue(row["activated"])
        self.assertIsNone(row["first_signin_at"])

    def test_a_clock_oddity_is_never_a_negative_time_to_value(self):
        user = self.grant()
        self.act(user.user_id, "card", T0 - timedelta(hours=3))
        self.assertEqual(self.row(user)["hours_signup_to_activation"], 0.0)


class ReturningNeedsTwelveHours(_Base):
    def test_thirteen_hours_later_is_returning_and_two_hours_later_is_not(self):
        late, soon = self.grant(1), self.grant(2)
        for user, gap in ((late, timedelta(hours=13)), (soon, timedelta(hours=2))):
            self.act(user.user_id, "card", T0 + timedelta(hours=1))
            self.act(user.user_id, "props", T0 + timedelta(hours=1) + gap)
        self.assertTrue(self.row(late)["returning"])
        self.assertFalse(self.row(soon)["returning"])
        report = self.report()
        self.assertEqual((report["activated"], report["returning"]), (2, 1))

    def test_the_edge_is_twelve_hours_inclusive(self):
        edges = ((timedelta(hours=12), True), (timedelta(hours=12, seconds=-1), False),
                 (timedelta(hours=12, seconds=1), True), (timedelta(0), False))
        for i, (gap, expect) in enumerate(edges, start=1):
            with self.subTest(gap=gap):
                user = self.grant(i)
                self.act(user.user_id, "card", T0 + timedelta(hours=1))
                self.act(user.user_id, "card", T0 + timedelta(hours=1) + gap)
                self.assertEqual(self.row(user)["returning"], expect)

    def test_one_action_is_not_returning(self):
        user = self.grant()
        self.act(user.user_id, "card", T0 + timedelta(hours=1))
        self.assertFalse(self.row(user)["returning"])

    def test_many_actions_inside_twelve_hours_are_not_returning(self):
        user = self.grant()
        for minutes in range(0, 700, 60):
            self.act(user.user_id, "card", T0 + timedelta(hours=1, minutes=minutes))
        self.assertFalse(self.row(user)["returning"])

    def test_the_first_action_is_found_even_when_it_was_recorded_last(self):
        """Events arrive in any order (a backfill, a retry); first and last are
        the earliest and latest by time, not by insertion."""
        user = self.grant()
        self.act(user.user_id, "card", T0 + timedelta(hours=30))
        self.act(user.user_id, "card", T0 + timedelta(hours=1))
        row = self.row(user)
        self.assertEqual(row["activated_at"], iso(T0 + timedelta(hours=1)))
        self.assertEqual(row["last_active_at"], iso(T0 + timedelta(hours=30)))
        self.assertTrue(row["returning"])


class ActiveDaysAndFeatures(_Base):
    def test_active_days_are_distinct_utc_dates_not_events(self):
        user = self.grant()
        for when in (T0 + timedelta(hours=1), T0 + timedelta(hours=2),        # 10-05
                     T0 + timedelta(hours=14),                                # 10-06 02:00
                     T0 + timedelta(hours=14, minutes=5),                     # 10-06
                     T0 + timedelta(days=4)):                                 # 10-09
            self.act(user.user_id, "card", when)
        row = self.row(user)
        self.assertEqual(row["active_days"], 3)
        self.assertEqual(row["last_active_at"], iso(T0 + timedelta(days=4)))

    def test_a_late_evening_event_belongs_to_its_utc_date(self):
        user = self.grant()
        self.act(user.user_id, "card", datetime(2026, 10, 5, 23, 59, tzinfo=timezone.utc))
        self.act(user.user_id, "card", datetime(2026, 10, 6, 0, 1, tzinfo=timezone.utc))
        self.assertEqual(self.row(user)["active_days"], 2)

    def test_features_count_per_label_and_a_sport_label_is_its_own(self):
        user = self.grant()
        self.act(user.user_id, "card")
        self.act(user.user_id, "card")
        self.act(user.user_id, "props", route="/props")
        self.act(user.user_id, "card", sport="nfl")        # counts as nfl, not card
        self.act(user.user_id, "card", sport="mma")        # counts as ufc
        self.act(user.user_id, "slate", sport="nfl", route="/games/{date}")
        self.assertEqual(self.row(user)["features"],
                         {"card": 2, "props": 1, "nfl": 2, "ufc": 1})

    def test_the_counts_add_up_across_days(self):
        user = self.grant()
        self.act(user.user_id, "prices", T0 + timedelta(hours=1))
        self.act(user.user_id, "prices", T0 + timedelta(days=1))
        self.assertEqual(self.row(user)["features"], {"prices": 2})


class OnlyValueActionsCount(_Base):
    def test_a_route_only_page_view_is_not_a_value_action(self):
        """The page views api/games.py has always recorded (What Changed, /today)
        carry no feature and must not activate anyone."""
        user = self.grant()
        self.raw(user.user_id, events.PAGE_VIEW, {"route": "/changed/{date}", "date": "2026-10-05"})
        self.raw(user.user_id, events.PAGE_VIEW, {"route": "/today", "date": "2026-10-05"})
        self.raw(user.user_id, events.PAGE_VIEW, {})
        self.assertFalse(self.row(user)["activated"])

    def test_another_kind_with_a_feature_key_is_not_a_value_action(self):
        user = self.grant()
        self.raw(user.user_id, events.BET_SAVED, {"feature": "card"})
        self.raw(user.user_id, events.DIGEST_VIEWED, {"feature": "card"})
        self.assertFalse(self.row(user)["activated"])

    def test_an_unknown_or_malformed_feature_is_not_a_value_action(self):
        user = self.grant()
        for bad in ("bogus", "", None, 7, ["card"], {"card": 1}, "CARD"):
            self.raw(user.user_id, events.PAGE_VIEW, {"feature": bad})
        self.assertFalse(self.row(user)["activated"])
        self.assertEqual(self.row(user)["features"], {})

    def test_unreadable_properties_are_skipped_not_fatal(self):
        user = self.grant()
        self.act(user.user_id, "card", T0 + timedelta(hours=1))
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(str(self.db))) as conn:
            conn.execute(
                "INSERT INTO analytics_events (user_hash, kind, properties_json, at) "
                "VALUES (?, 'page_view', '{not json', ?)",
                (events.hash_user_id(user.user_id), iso(T0 + timedelta(hours=2))))
            conn.commit()
        row = self.row(user)
        self.assertEqual(row["features"], {"card": 1})

    def test_someone_elses_events_do_not_leak_in(self):
        mine, theirs = self.grant(1), self.grant(2)
        self.act(theirs.user_id, "card", T0 + timedelta(hours=1))
        self.act(theirs.user_id, "props", T0 + timedelta(hours=20))
        self.assertFalse(self.row(mine)["activated"])
        self.assertEqual(self.row(mine)["features"], {})
        stranger = users_store.create_user("stranger@example.com", db=self.db)
        self.act(stranger.id, "card")
        self.assertEqual(self.report()["feature_users"]["card"], 1,
                         "a non-tester is not in the tester numbers")


class TheReadIsBounded(_Base):
    """Production runs on a small machine and has run out of memory on
    whole-table reads. The tester report must be one grouped SQL statement
    filtered by kind and by the tester hashes, never the events table in Python."""

    def _traced(self):
        statements = []
        real = events._connect

        @contextmanager
        def traced(path=None):
            with real(path) as conn:
                conn.set_trace_callback(statements.append)
                yield conn

        return statements, mock.patch.object(events, "_connect", traced)

    def test_the_listing_reads_events_with_one_filtered_grouped_statement(self):
        user = self.grant()
        for i in range(30):
            self.act(user.user_id, "card", T0 + timedelta(minutes=i))
        stranger = users_store.create_user("stranger@example.com", db=self.db)
        for i in range(30):
            self.act(stranger.id, "card", T0 + timedelta(minutes=i))
        statements, patcher = self._traced()
        with patcher, mock.patch.object(events, "list_events",
                                        side_effect=AssertionError("whole-table read")):
            testers.list_testers(db=self.db)
        reads = [s for s in statements if "analytics_events" in s and "SELECT" in s.upper()]
        self.assertEqual(len(reads), 1, reads)
        sql = re.sub(r"\s+", " ", reads[0])
        self.assertIn("kind = 'page_view'", sql)
        self.assertRegex(sql, r"user_hash IN \('[0-9a-f]{64}'\)")
        self.assertIn("GROUP BY", sql)
        self.assertNotIn("SELECT *", sql)

    def test_the_aggregate_is_the_same_single_read_not_one_per_tester(self):
        for i in range(5):
            self.act(self.grant(i).user_id, "card")
        statements, patcher = self._traced()
        with patcher, mock.patch.object(events, "list_events",
                                        side_effect=AssertionError("whole-table read")):
            testers.activation_report(now=T0 + timedelta(days=1), db=self.db)
        reads = [s for s in statements if "analytics_events" in s and "SELECT" in s.upper()]
        self.assertEqual(len(reads), 1, reads)

    def test_no_testers_means_no_events_query_at_all(self):
        statements, patcher = self._traced()
        with patcher:
            testers.activation_report(now=T0, db=self.db)
        self.assertEqual([s for s in statements if "analytics_events" in s
                          and "SELECT" in s.upper()], [])

    def test_the_rows_returned_are_bounded_by_users_labels_and_days(self):
        """500 events from one tester on one day come back as one grouped row."""
        user = self.grant()
        for i in range(500):
            self.act(user.user_id, "card", T0 + timedelta(seconds=i))
        stats = activation.value_action_stats([events.hash_user_id(user.user_id)], db=self.db)
        slot = stats[events.hash_user_id(user.user_id)]
        self.assertEqual(slot["features"], {"card": 500})
        self.assertEqual(slot["days"], {"2026-10-05"})


class TheAggregate(_Base):
    KEYS = {"as_of", "testers_granted", "testers_in_window", "activated", "returning",
            "median_hours_signup_to_activation", "feature_users", "internal_excluded",
            "unmeasured_features"}

    def test_an_empty_database_is_all_zeros_and_a_null_median(self):
        report = self.report()
        self.assertEqual(set(report), self.KEYS)
        self.assertEqual((report["testers_granted"], report["testers_in_window"],
                          report["activated"], report["returning"],
                          report["internal_excluded"]), (0, 0, 0, 0, 0))
        self.assertIsNone(report["median_hours_signup_to_activation"])
        self.assertEqual(report["feature_users"], {label: 0 for label in activation.FEATURES})

    def test_every_label_is_present_with_zeros_in_label_order(self):
        user = self.grant()
        self.act(user.user_id, "props", T0 + timedelta(hours=1), route="/props")
        users = self.report()["feature_users"]
        self.assertEqual(list(users), list(activation.FEATURES))
        self.assertEqual(users["props"], 1)
        self.assertEqual(sum(users.values()), 1)
        self.assertEqual([v for k, v in users.items() if k != "props"], [0] * 8)

    def test_it_names_what_nothing_can_record_yet(self):
        self.assertEqual(self.report()["unmeasured_features"], ["moneyline"])

    def test_it_contains_no_email_no_user_id_and_no_hash(self):
        user = self.grant()
        self.act(user.user_id, "card", T0 + timedelta(hours=1))
        blob = json.dumps(self.report())
        self.assertNotIn("@", blob)
        self.assertNotIn("example.com", blob)
        self.assertNotIn(events.hash_user_id(user.user_id), blob)
        self.assertNotRegex(blob, r"[0-9a-f]{64}")
        self.assertNotIn("user_id", blob)
        self.assertNotIn("email", blob)

    def test_feature_users_counts_testers_not_events(self):
        a, b = self.grant(1), self.grant(2)
        for _ in range(5):
            self.act(a.user_id, "card")
        self.act(b.user_id, "card")
        self.act(b.user_id, "props", route="/props")
        users = self.report()["feature_users"]
        self.assertEqual((users["card"], users["props"]), (2, 1))

    def test_the_median_is_over_the_activated_and_null_when_none(self):
        for i, hours in enumerate((2, 4, 10), start=1):
            self.act(self.grant(i).user_id, "card", T0 + timedelta(hours=hours))
        self.grant(9)    # granted, never used
        self.assertEqual(self.report()["median_hours_signup_to_activation"], 4)
        self.assertEqual(self.report()["activated"], 3)
        self.assertEqual(self.report()["testers_granted"], 4)

    def test_an_even_count_averages_the_middle_two(self):
        for i, hours in enumerate((2, 4), start=1):
            self.act(self.grant(i).user_id, "card", T0 + timedelta(hours=hours))
        self.assertEqual(self.report()["median_hours_signup_to_activation"], 3)

    def test_testers_in_window_are_the_ones_whose_access_is_still_open(self):
        self.grant(1, now=T0 - timedelta(days=10))            # expired 3 days ago
        self.grant(2, now=T0)
        extended = self.grant(3, now=T0 - timedelta(days=10))
        testers.extend_tester(extended.user_id, "useful bug report", now=T0, db=self.db)
        report = self.report(now=T0 + timedelta(days=1))
        self.assertEqual(report["testers_granted"], 3)
        self.assertEqual(report["testers_in_window"], 2,
                         "the fresh one and the extended one; the expired one is out")

    def test_as_of_is_the_clock_it_was_given(self):
        self.assertEqual(self.report(now=T0)["as_of"], iso(T0))


class OurOwnTestAccountsDoNotCount(_Base):
    def tagged(self, i, source):
        grant = self.grant(i)
        if source is not None:
            customers.record_signup_attribution(grant.user_id, {"utm_source": source}, db=self.db)
        self.act(grant.user_id, "card", T0 + timedelta(hours=2))
        self.act(grant.user_id, "props", T0 + timedelta(hours=20), route="/props")
        return grant

    def test_internal_sources_are_excluded_and_counted_apart(self):
        self.tagged(1, "internal")
        self.tagged(2, "internal-test")
        self.tagged(3, "Internal-Brey")
        real = self.tagged(4, "reddit")
        self.tagged(5, None)
        report = self.report()
        self.assertEqual(report["internal_excluded"], 3)
        self.assertEqual(report["testers_granted"], 2)
        self.assertEqual(report["activated"], 2)
        self.assertEqual(report["returning"], 2)
        self.assertEqual(report["feature_users"]["card"], 2)
        self.assertEqual(report["feature_users"]["props"], 2)
        self.assertIn(real.user_id, [r["user_id"] for r in testers.list_testers(db=self.db)["testers"]])

    def test_the_hyphen_matters_international_is_a_customer(self):
        self.tagged(1, "international-bettors")
        self.tagged(2, "internalize")
        report = self.report()
        self.assertEqual((report["internal_excluded"], report["testers_granted"]), (0, 2))

    def test_internal_accounts_do_not_move_the_median_or_the_window(self):
        self.tagged(1, "internal-test")                         # 2h
        grant = self.grant(2, now=T0 - timedelta(hours=1))
        self.act(grant.user_id, "card", T0 + timedelta(hours=5))   # 6h from signup
        report = self.report()
        self.assertEqual(report["median_hours_signup_to_activation"], 6)
        self.assertEqual(report["testers_in_window"], 1)

    def test_internal_testers_still_show_in_the_per_tester_listing(self):
        """The admin table is the owner's own list: he still sees his test
        accounts and what they did. Only the aggregate leaves them out."""
        grant = self.tagged(1, "internal-test")
        rows = {r["user_id"]: r for r in testers.list_testers(db=self.db)["testers"]}
        self.assertTrue(rows[grant.user_id]["activated"])

    def test_the_rule_is_one_shared_function(self):
        for value, expect in (("internal", True), ("internal-test", True), (" Internal ", True),
                              ("INTERNAL-X", True), ("international-bettors", False),
                              ("internalize", False), ("reddit", False), ("", False),
                              (None, False), (7, False), (["internal"], False)):
            with self.subTest(value=value):
                self.assertEqual(attribution.is_internal_source(value), expect)


if __name__ == "__main__":
    unittest.main()
