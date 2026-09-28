"""Tests for scripts/discord_feed.py -- Linehound's first paid product
deliverable, a Discord community feed.

Every ledger read goes through a TEMP path (`tempfile.TemporaryDirectory`),
never the real `evidence/*.jsonl` files, and every HTTP call is mocked at
`scripts.discord_feed._post_one` -- no test in this file ever reaches the
network or the real filesystem outside its own temp dir.

Style follows tests/test_card_v2_ledger.py (temp store, fixed clock, real
`card_ledger.publish_v2` calls rather than hand-built ledger rows) for the
V2 fixture, and tests/test_daily_loop_wiring.py (a local `_bash()` helper,
text assertions on the checked-in script) for the shell-wiring checks.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.analysis import best_bets_card
from src.appstate import card_ledger

import scripts.discord_feed as discord_feed
from tests._card_v2_fixtures import game_entry, prop_entry

DATE = "2026-09-20"
NOW1 = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
NOW2 = datetime(2026, 9, 20, 18, 5, tzinfo=timezone.utc)  # still well before
# the 19:05Z lock window (first_pitch 23:05Z minus the 4h lock lead).

FAKE_URL = "https://discord.com/api/webhooks/1234567890/fake-token-do-not-use"


def _bash():
    """A POSIX bash. On Windows `bash` on PATH is often the WSL shim, which
    fails with returncode 1 (not "not found") when no WSL distribution is
    installed -- indistinguishable from a real syntax error unless a working
    bash is found first. Same helper as tests/test_daily_loop_wiring.py,
    kept local here for the same reason that file gives."""
    candidates = []
    if sys.platform == "win32":
        candidates += [r"C:\Program Files\Git\bin\bash.exe",
                       r"C:\Program Files\Git\usr\bin\bash.exe"]
    candidates.append(shutil.which("bash"))
    for path in candidates:
        if not path or not Path(path).exists():
            continue
        low = path.lower()
        if sys.platform == "win32" and ("windowsapps" in low or "system32" in low):
            continue
        return path
    return None


BASH = _bash()


def _seed_two_picks_one_fill_one_withdrawn(path: str) -> dict:
    """Publishes DATE twice into the V2 ledger at `path`:

    Run 1: pick_A, pick_D (two picks), fill_B (one fill), pick_C (a third
    pick, about to be withdrawn).
    Run 2: a FRESH, hard-failing read for pick_C's own game_pk only
    (entry_class=None, failed_gates non-empty) -- `publish_v2`'s own
    documented mechanism for withdrawing a prior pick (see
    src/appstate/card_ledger.py `publish_v2`'s docstring and
    tests/test_card_v2_ledger.py's `test_fresh_failing_read_withdraws_a_
    provisional_pick_before_lock`, the proven recipe this mirrors). A and D
    and B are never mentioned again in run 2, so `_lock_and_merge_v2`
    carries them forward unchanged (a "stale, not locked" read, not a
    withdrawal).

    Returns {"row1": ..., "row2": ...} (both `publish_v2` return dicts).
    """
    pick_a = game_entry(game_pk=9001, event_id="evt-9001", price=-130,
                        score=0.20)
    pick_d = game_entry(game_pk=9002, event_id="evt-9002", price=105,
                        score=0.10)
    fill_b = game_entry(game_pk=9003, event_id="evt-9003", price=-150,
                        entry_class="fill", failed_gates=["G7_VALUE"],
                        score=0.05)
    pick_c = game_entry(game_pk=9004, event_id="evt-9004", price=-120,
                        score=0.15)

    row1 = card_ledger.publish_v2(
        {"date": DATE, "all_bets": [pick_a, pick_d, fill_b, pick_c],
         "params": best_bets_card.V2},
        now=NOW1.isoformat(), path=path)

    c_failing = dict(pick_c)
    c_failing["entry_class"] = None
    c_failing["failed_gates"] = ["G7_VALUE"]
    row2 = card_ledger.publish_v2(
        {"date": DATE, "all_bets": [c_failing], "params": best_bets_card.V2},
        now=NOW2.isoformat(), path=path)

    return {"row1": row1, "row2": row2}


def _fake_snapshot(_sport, **_kwargs) -> dict:
    """A canned effective_record.sport_snapshot-shaped return -- the
    "injected snapshot" the mission asks the record lines to be built from,
    independent of any real settled ledger."""
    return {
        "sport": "mlb", "sport_label": "MLB",
        "current": {
            "sport": "mlb", "rule_id": "DAILY_CARD_BEST_BETS_V2",
            "status": "current", "label": "Our value card",
            "public": True, "available": True,
            "grading_state": "graded", "reason": None, "notice": None,
            "days": 6, "date_span": {"first": "2026-09-15", "last": "2026-09-20"},
            "wins": 11, "losses": 13, "pushes": 0, "voids": 0, "unresolved": 0,
            "n_staked": 24, "win_rate": 0.4583, "profit_units": -4.95,
            "roi_pct": -20.625,
            "market_breakdown": {}, "market_note": "Game picks only.",
            "fills": None, "fills_tracked": True, "withdrawn": 1,
            "postseason": {"wins": 2, "losses": 1, "pushes": 0, "voids": 0,
                          "unresolved": 0, "n_staked": 3, "profit_units": 0.5,
                          "win_rate": None, "roi_pct": None, "days": 1,
                          "date_span": None, "label": "Postseason (graded, not counted)"},
            "counted_scope": "regular season only", "published_count": 24,
            "pending_count": 0, "settled_count": 24, "unresolved_count": 0,
            "chain_ok": True, "rows_checked": 24,
        },
        "previous": {
            "sport": "mlb", "rule_id": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
            "status": "previous", "label": "Our first card rule",
            "public": True, "available": True,
            "grading_state": "graded", "reason": None, "notice": None,
            "days": 13, "date_span": {"first": "2026-09-10", "last": "2026-09-22"},
            "wins": 73, "losses": 40, "pushes": 0, "voids": 0, "unresolved": 0,
            "n_staked": 113, "win_rate": 0.646, "profit_units": 7.61,
            "roi_pct": 6.73,
            "market_breakdown": {}, "market_note": "Game picks only.",
            "fills": None, "fills_tracked": False, "withdrawn": None,
            "postseason": {"wins": 0, "losses": 0, "pushes": 0, "voids": 0,
                          "unresolved": 0, "n_staked": 0, "profit_units": 0.0,
                          "win_rate": None, "roi_pct": None, "days": 0,
                          "date_span": None, "label": "Postseason (graded, not counted)"},
            "counted_scope": "regular season only", "published_count": 113,
            "pending_count": 0, "settled_count": 113, "unresolved_count": 0,
            "chain_ok": True, "rows_checked": 113,
        },
        "cutover_date": "2026-09-23",
    }


class AssembledPayloadTest(unittest.TestCase):
    """The core payload, built from a temp V2 ledger fixture."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")
        self.seeded = _seed_two_picks_one_fill_one_withdrawn(self.path)

    def _assemble(self, **over):
        kwargs = dict(sport="mlb", date_str=DATE, card_path=self.path,
                      snapshot_provider=_fake_snapshot)
        kwargs.update(over)
        return discord_feed.assemble(**kwargs)

    def test_row2_actually_withdrew_pick_c_and_kept_the_rest(self):
        # Ground truth about the fixture itself, independent of this
        # script -- if this ever fails, the fixture stopped reproducing the
        # withdrawal mechanism, not discord_feed.py.
        row2 = self.seeded["row2"]
        self.assertEqual(row2["n_picks"], 2)
        self.assertEqual(row2["n_fills"], 1)
        self.assertEqual(len(row2["withdrawn"]), 1)
        self.assertEqual(row2["withdrawn"][0]["game_pk"], 9004)

    def test_withdrawn_entry_is_never_rendered(self):
        assembled = self._assemble()
        blob = json.dumps(assembled.messages)
        # The withdrawn pick's own game_pk (frozen fact) must not surface
        # anywhere in the rendered payload -- the only honest way to prove
        # "omitted" rather than merely "not obviously labelled".
        self.assertNotIn("9004", blob)

    def test_two_picks_present_under_picks(self):
        assembled = self._assemble()
        embed = assembled.messages[0]["embeds"][0]
        picks_field = next(f for f in embed["fields"] if f["name"] == "Picks")
        self.assertIn("Yankees moneyline at -130", picks_field["value"])
        self.assertIn("Yankees moneyline at +105", picks_field["value"])
        self.assertEqual(picks_field["value"].count("\n") + 1, 2,
                         "exactly two picks, one per line")

    def test_fill_is_labelled_apart_from_picks(self):
        assembled = self._assemble()
        embed = assembled.messages[0]["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        self.assertIn("Fills", field_names)
        picks_field = next(f for f in embed["fields"] if f["name"] == "Picks")
        fills_field = next(f for f in embed["fields"] if f["name"] == "Fills")
        self.assertIn("-150", fills_field["value"])
        self.assertNotIn("-150", picks_field["value"],
                         "the fill's price must not also appear on the Picks line")

    def test_market_vs_our_number_present_on_a_pick(self):
        assembled = self._assemble()
        embed = assembled.messages[0]["embeds"][0]
        picks_field = next(f for f in embed["fields"] if f["name"] == "Picks")
        self.assertIn("market", picks_field["value"])
        self.assertIn("our number", picks_field["value"])

    def test_record_lines_come_from_the_injected_snapshot(self):
        assembled = self._assemble()
        embed = assembled.messages[0]["embeds"][0]
        record_field = next(f for f in embed["fields"] if f["name"] == "Record")
        self.assertIn("11-13", record_field["value"])
        self.assertIn("-4.95u", record_field["value"])
        self.assertIn("Previous rule", record_field["value"])
        self.assertIn("73-40", record_field["value"])
        # postseason.n_staked (3) > 0 in the fake snapshot -> the postseason
        # line must appear, worded exactly as the mission specifies.
        self.assertIn("Postseason: 2-1, graded, not counted", record_field["value"])

    def test_row_hash_is_the_ledgers_own_row_hash(self):
        assembled = self._assemble()
        self.assertEqual(assembled.row_hash, self.seeded["row2"]["row_hash"])
        self.assertEqual(assembled.kind, "card")

    def test_no_card_for_the_date_returns_none(self):
        assembled = discord_feed.assemble(
            sport="mlb", date_str="2099-01-01", card_path=self.path,
            snapshot_provider=_fake_snapshot)
        self.assertIsNone(assembled)

    def test_record_only_skips_the_card_entirely(self):
        assembled = self._assemble(record_only=True)
        embed = assembled.messages[0]["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        self.assertEqual(field_names, ["Record"])
        self.assertEqual(assembled.kind, "record")
        # A record-only post never depends on today's card being published.
        no_card = discord_feed.assemble(
            sport="mlb", date_str="2099-01-01", record_only=True,
            card_path=self.path, snapshot_provider=_fake_snapshot)
        self.assertIsNotNone(no_card)


class PropSentenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")

    def test_prop_pick_sentence_reads_off_real_fields_no_rewording(self):
        prop = prop_entry(game_pk=9101, event_id="evt-9101", player="Devers",
                          market="batter_hits", line=0.5, price=120)
        card_ledger.publish_v2(
            {"date": DATE, "all_bets": [prop], "params": best_bets_card.V2},
            now=NOW1.isoformat(), path=self.path)
        assembled = discord_feed.assemble(
            sport="mlb", date_str=DATE, card_path=self.path,
            snapshot_provider=_fake_snapshot)
        picks_field = next(f for f in assembled.messages[0]["embeds"][0]["fields"]
                           if f["name"] == "Picks")
        self.assertIn("Devers batter_hits 0.5 at +120", picks_field["value"])


class MarkerIdempotencyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = os.path.join(self._tmp.name, "cards_v2.jsonl")
        self.marker_path = os.path.join(self._tmp.name, "watch", "discord_feed_posted.jsonl")
        _seed_two_picks_one_fill_one_withdrawn(self.ledger_path)
        self.posted = []

    def _fake_post_one(self, url, message):
        self.posted.append((url, message))
        return 204, None

    def _run(self, **over):
        kwargs = dict(sport="mlb", date_str=DATE, webhook_url=FAKE_URL,
                      marker_path=self.marker_path, card_path=self.ledger_path,
                      snapshot_provider=_fake_snapshot)
        kwargs.update(over)
        with mock.patch.object(discord_feed, "_post_one", self._fake_post_one):
            return discord_feed.run(**kwargs)

    def test_second_run_posts_nothing(self):
        rc1 = self._run()
        self.assertEqual(rc1, 0)
        self.assertEqual(len(self.posted), 1)

        rc2 = self._run()
        self.assertEqual(rc2, 0)
        self.assertEqual(len(self.posted), 1, "a second identical run must not post again")

    def test_a_new_row_hash_posts_an_update(self):
        self._run()
        self.assertEqual(len(self.posted), 1)

        # A genuine republish: a THIRD publish_v2 call changes the picks
        # (pick_a's price moves), producing a new row_hash for the same date.
        pick_a_moved = game_entry(game_pk=9001, event_id="evt-9001", price=-105, score=0.20)
        card_ledger.publish_v2(
            {"date": DATE, "all_bets": [pick_a_moved], "params": best_bets_card.V2},
            now="2026-09-20T18:10:00Z", path=self.ledger_path)

        rc3 = self._run()
        self.assertEqual(rc3, 0)
        self.assertEqual(len(self.posted), 2, "a new row_hash must post again")
        title = self.posted[1][1]["embeds"][0]["title"]
        self.assertIn("card update", title.lower())

    def test_marker_row_shape(self):
        self._run()
        rows = discord_feed._read_markers(self.marker_path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(set(row.keys()),
                         {"sport", "date", "row_hash", "webhook_hash", "posted_utc", "kind"})
        self.assertEqual(row["sport"], "mlb")
        self.assertEqual(row["date"], DATE)
        self.assertEqual(row["kind"], "card")
        self.assertEqual(row["webhook_hash"], discord_feed._webhook_hash(FAKE_URL))


class WebhookUrlNeverLeaksTest(unittest.TestCase):
    """The URL must not appear in the marker file or in anything printed,
    across every code path: dry-run, a successful post, and a failed one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = os.path.join(self._tmp.name, "cards_v2.jsonl")
        self.marker_path = os.path.join(self._tmp.name, "watch", "discord_feed_posted.jsonl")
        _seed_two_picks_one_fill_one_withdrawn(self.ledger_path)

    def _captured(self, fn):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fn()
        return rc, buf.getvalue()

    def test_dry_run_never_prints_the_url(self):
        rc, out = self._captured(lambda: discord_feed.run(
            "mlb", DATE, webhook_url=FAKE_URL, dry_run=True,
            marker_path=self.marker_path, card_path=self.ledger_path,
            snapshot_provider=_fake_snapshot))
        self.assertEqual(rc, 0)
        self.assertNotIn(FAKE_URL, out)

    def test_successful_post_never_prints_or_stores_the_url(self):
        with mock.patch.object(discord_feed, "_post_one", lambda url, msg: (204, None)):
            rc, out = self._captured(lambda: discord_feed.run(
                "mlb", DATE, webhook_url=FAKE_URL, marker_path=self.marker_path,
                card_path=self.ledger_path, snapshot_provider=_fake_snapshot))
        self.assertEqual(rc, 0)
        self.assertNotIn(FAKE_URL, out)
        with open(self.marker_path, encoding="utf-8") as fh:
            marker_text = fh.read()
        self.assertNotIn(FAKE_URL, marker_text)

    def test_failed_post_never_prints_the_url_and_writes_no_marker(self):
        with mock.patch.object(discord_feed, "_post_one", lambda url, msg: (500, "Internal Server Error")):
            rc, out = self._captured(lambda: discord_feed.run(
                "mlb", DATE, webhook_url=FAKE_URL, marker_path=self.marker_path,
                card_path=self.ledger_path, snapshot_provider=_fake_snapshot))
        self.assertEqual(rc, 1)
        self.assertNotIn(FAKE_URL, out)
        self.assertIn("ESCALATE", out)
        self.assertFalse(os.path.exists(self.marker_path))


class NonTwoxxResponseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = os.path.join(self._tmp.name, "cards_v2.jsonl")
        self.marker_path = os.path.join(self._tmp.name, "watch", "discord_feed_posted.jsonl")
        _seed_two_picks_one_fill_one_withdrawn(self.ledger_path)

    def test_non_2xx_exits_1_and_writes_no_marker(self):
        with mock.patch.object(discord_feed, "_post_one", lambda url, msg: (404, "Not Found")):
            rc = discord_feed.run("mlb", DATE, webhook_url=FAKE_URL,
                                  marker_path=self.marker_path, card_path=self.ledger_path,
                                  snapshot_provider=_fake_snapshot)
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.marker_path))

    def test_network_failure_exits_1_and_writes_no_marker(self):
        with mock.patch.object(discord_feed, "_post_one", lambda url, msg: (None, "Name or service not known")):
            rc = discord_feed.run("mlb", DATE, webhook_url=FAKE_URL,
                                  marker_path=self.marker_path, card_path=self.ledger_path,
                                  snapshot_provider=_fake_snapshot)
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.marker_path))

    def test_missing_webhook_url_exits_1_without_attempting_a_post(self):
        calls = []
        with mock.patch.object(discord_feed, "_post_one",
                               lambda url, msg: calls.append(1) or (204, None)):
            rc = discord_feed.run("mlb", DATE, webhook_url=None,
                                  marker_path=self.marker_path, card_path=self.ledger_path,
                                  snapshot_provider=_fake_snapshot)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])


class DryRunPrintsValidJsonTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = os.path.join(self._tmp.name, "cards_v2.jsonl")
        _seed_two_picks_one_fill_one_withdrawn(self.ledger_path)

    def test_dry_run_prints_one_valid_json_payload_per_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = discord_feed.run("mlb", DATE, dry_run=True, card_path=self.ledger_path,
                                  snapshot_provider=_fake_snapshot)
        self.assertEqual(rc, 0)
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 1)
        for line in lines:
            payload = json.loads(line)  # raises if not valid JSON
            self.assertIn("embeds", payload)


class FooterGradingLineTest(unittest.TestCase):
    def test_mlb_and_nfl_say_graded_automatically(self):
        for sport in ("mlb", "nfl"):
            with self.subTest(sport=sport):
                text = discord_feed._footer_text(sport)
                self.assertIn("Graded in public the next morning.", text)
                self.assertNotIn("entered by hand", text)

    def test_ufc_says_results_entered_by_hand(self):
        text = discord_feed._footer_text("mma")
        self.assertIn("Results entered by hand.", text)
        self.assertNotIn("Graded in public", text)

    def test_footer_carries_the_real_beta_disclaimer_text(self):
        from src.analysis.disclaimers import get_disclaimer
        text = discord_feed._footer_text("mlb")
        self.assertIn(get_disclaimer()["text"], text)


class MainEntryPointTest(unittest.TestCase):
    """Exercises the real `main(argv)` CLI entry point directly -- not just
    the internal `run`/`assemble` helpers -- against a date that is
    guaranteed to have no published card, so this needs no fixture and
    touches only the real (frozen, read-only) evidence files, exactly as a
    real invocation would."""

    def test_main_dry_run_no_card_date_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = discord_feed.main(["--sport", "mlb", "--date", "2099-01-01", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("no published card for 2099-01-01", buf.getvalue())

    def test_main_rejects_a_malformed_date(self):
        with self.assertRaises(SystemExit):
            discord_feed.main(["--date", "not-a-date"])

    @unittest.skipUnless(BASH, "no POSIX bash available")
    def test_real_subprocess_invocation_dry_run(self):
        # The exact invocation the shell scripts use, minus the env gate --
        # proves argv parsing, sys.path bootstrap and the src.* imports all
        # work when launched the way python3 actually launches it, not just
        # when imported as a module inside this test process.
        result = subprocess.run(
            [sys.executable, "scripts/discord_feed.py", "--sport", "mma",
             "--date", "2099-01-01", "--dry-run"],
            cwd=REPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no published card for 2099-01-01", result.stdout)


class ShellWiringTest(unittest.TestCase):
    GATED_CALL = (
        'if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then\n'
        '    python3 scripts/discord_feed.py --sport mlb || echo "ESCALATE: discord feed failed"\n'
        'fi'
    )

    def test_daily_loop_contains_the_gated_call(self):
        text = (REPO / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
        self.assertIn(self.GATED_CALL, text)

    def test_afternoon_slate_contains_the_gated_call(self):
        text = (REPO / "scripts" / "afternoon_slate.sh").read_text(encoding="utf-8")
        self.assertIn(self.GATED_CALL, text)

    def test_afternoon_slate_placed_right_after_card_publish(self):
        text = (REPO / "scripts" / "afternoon_slate.sh").read_text(encoding="utf-8")
        publish_pos = text.index("card publish --date")
        feed_pos = text.index("discord_feed.py")
        settle_or_next_pos = text.index("engine slip", feed_pos)
        self.assertLess(publish_pos, feed_pos)
        self.assertLess(feed_pos, settle_or_next_pos)

    def test_daily_loop_placed_in_the_card_section(self):
        text = (REPO / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
        record_pos = text.index("card record (running)")
        feed_pos = text.index("discord_feed.py")
        self.assertLess(record_pos, feed_pos)

    def test_afternoon_slate_stages_data_watch(self):
        text = (REPO / "scripts" / "afternoon_slate.sh").read_text(encoding="utf-8")
        add_lines = [l for l in text.splitlines() if l.strip().startswith("git add ")]
        self.assertTrue(any("data/watch" in l for l in add_lines),
                        "afternoon_slate.sh must stage data/watch so the "
                        "discord feed's marker file is actually committed")

    def test_daily_loop_already_stages_data_watch(self):
        text = (REPO / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
        add_lines = [l for l in text.splitlines() if l.strip().startswith("git add ")]
        self.assertTrue(any("data/watch" in l for l in add_lines))

    @unittest.skipUnless(BASH, "no POSIX bash available")
    def test_daily_loop_parses_as_valid_bash(self):
        result = subprocess.run([BASH, "-n", str(REPO / "scripts" / "daily_loop.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(BASH, "no POSIX bash available")
    def test_afternoon_slate_parses_as_valid_bash(self):
        result = subprocess.run([BASH, "-n", str(REPO / "scripts" / "afternoon_slate.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class CustomerLanguageScanTest(unittest.TestCase):
    """The mission's own instruction: this scan only needs to pass on
    scripts/discord_feed.py if tests.test_customer_language actually looks
    at scripts/ at all -- check its SCAN_DIRS rather than assuming either
    way (2026-09-28: it does not; SCAN_DIRS is src/analysis and src/report
    only). If that ever changes, this test starts enforcing the same
    banned-vocabulary sweep against this file that src/analysis/src/report
    already get."""

    def test_scan_dirs_status_and_compliance_if_scanned(self):
        from tests import test_customer_language as tcl

        scripts_dir = REPO / "scripts"
        scanned = any(Path(d) == scripts_dir for d in tcl.SCAN_DIRS)
        if not scanned:
            self.skipTest("tests.test_customer_language.SCAN_DIRS does not "
                          "include scripts/ -- nothing to enforce here")

        import ast
        text = (REPO / "scripts" / "discord_feed.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        strings = [n.value for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for pattern, label in tcl.HARD_BANNED:
            for s in strings:
                self.assertNotRegex(s, pattern, f"banned phrase {label!r} found: {s!r}")


if __name__ == "__main__":
    unittest.main()
