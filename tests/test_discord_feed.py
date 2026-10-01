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
from contextlib import redirect_stderr, redirect_stdout
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

    def _picks_text(self, *props):
        card_ledger.publish_v2(
            {"date": DATE, "all_bets": list(props), "params": best_bets_card.V2},
            now=NOW1.isoformat(), path=self.path)
        assembled = discord_feed.assemble(
            sport="mlb", date_str=DATE, card_path=self.path,
            snapshot_provider=_fake_snapshot)
        return next(f for f in assembled.messages[0]["embeds"][0]["fields"]
                    if f["name"] == "Picks")["value"]

    def test_prop_pick_sentence_reads_off_real_fields_no_rewording(self):
        # CHANGED 2026-10-01 (was: "Devers batter_hits 0.5 at +120", which
        # left out the side and printed the raw market key). The frozen row
        # carries `side`; the sentence now says it, in the product's own
        # prop wording (daily_card._prop_bet_sentence).
        text = self._picks_text(prop_entry(game_pk=9101, event_id="evt-9101",
                                           player="Devers", market="batter_hits",
                                           line=0.5, price=120, side="over"))
        self.assertIn("Devers over 0.5 hits at +120", text)
        self.assertNotIn("batter_hits", text)

    def test_prop_sentence_says_under_and_names_the_market_in_plain_words(self):
        text = self._picks_text(
            prop_entry(game_pk=9102, event_id="evt-9102", player="Busch",
                       market="batter_total_bases", line=1.5, price=-130, side="under"))
        self.assertIn("Busch under 1.5 total bases at -130", text)
        self.assertNotIn("batter_total_bases", text)


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

    def test_footer_carries_the_feed_beta_disclaimer_text(self):
        # CHANGED 2026-10-01 (was: the footer contains
        # disclaimers.get_disclaimer()["text"] verbatim). That text says
        # "edge", "profits" and "locked-in", which the feed's content rules
        # forbid, so the feed carries its own wording of the same
        # statements: still BETA / pending legal review, still the 21+ and
        # problem-gambling lines, with the one allowed sentence.
        text = discord_feed._footer_text("mlb")
        self.assertIn(discord_feed.FEED_DISCLAIMER, text)
        self.assertIn("PENDING FINAL LEGAL REVIEW", text)
        self.assertIn("No edge is claimed.", text)
        self.assertIn("21+", text)
        self.assertIn("problem-gambling", text)
        self.assertEqual(discord_feed.banned_words_in(text), [])


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
    # What must hold, not how it is spelled: every feed call sits inside an
    # `if` that opens only when a webhook variable is set, the MLB call is
    # there, and a failed call escalates instead of stopping the script.
    # (CHANGED 2026-10-01: the gate may also open on DISCORD_WEBHOOK_URLS,
    # and an NFL call may sit beside the MLB one.)
    def _has_gated_call(self, text):
        lines = text.splitlines()
        calls = [i for i, l in enumerate(lines)
                 if l.strip().startswith("python3 scripts/discord_feed.py")]
        if not any("--sport mlb" in lines[i] for i in calls):
            return False
        for i in calls:
            if '|| echo "ESCALATE: discord feed failed"' not in lines[i]:
                return False
            opener = next((lines[j] for j in range(i - 1, -1, -1)
                           if lines[j].startswith("if ") or lines[j].strip() == "fi"), "")
            if not (opener.startswith('if [ -n "${DISCORD_WEBHOOK_URL:-}')
                    and opener.rstrip().endswith("]; then")):
                return False
        return True

    def test_an_ungated_call_is_refused(self):
        self.assertFalse(self._has_gated_call(
            'python3 scripts/discord_feed.py --sport mlb || echo "ESCALATE: discord feed failed"'))
        self.assertFalse(self._has_gated_call(
            'if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then\n'
            '    python3 scripts/discord_feed.py --sport mlb\nfi'))

    def test_daily_loop_contains_the_gated_call(self):
        text = (REPO / "scripts" / "daily_loop.sh").read_text(encoding="utf-8")
        self.assertTrue(self._has_gated_call(text))

    def test_afternoon_slate_contains_the_gated_call(self):
        text = (REPO / "scripts" / "afternoon_slate.sh").read_text(encoding="utf-8")
        self.assertTrue(self._has_gated_call(text))

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


URL_A = "https://discord.com/api/webhooks/1111111111/token-A-do-not-use-aaaaaaaa"
URL_B = "https://discord.com/api/webhooks/2222222222/token-B-do-not-use-bbbbbbbb"
URL_C = "https://discord.com/api/webhooks/3333333333/token-C-do-not-use-cccccccc"
ALL_URLS = (URL_A, URL_B, URL_C, FAKE_URL)


class _FeedFixture(unittest.TestCase):
    """Temp V2 ledger + temp marker file + a recording fake `_post_one`
    whose outcome per URL the test chooses (default: 204)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = os.path.join(self._tmp.name, "cards_v2.jsonl")
        self.marker_path = os.path.join(self._tmp.name, "watch", "discord_feed_posted.jsonl")
        _seed_two_picks_one_fill_one_withdrawn(self.ledger_path)
        self.posted = []   # urls successfully posted to, in order
        self.attempted = []
        self.outcome = {}  # url -> (status, reason) | an Exception to raise

    def _fake_post_one(self, url, message):
        self.attempted.append(url)
        result = self.outcome.get(url, (204, None))
        if isinstance(result, Exception):
            raise result
        if result[0] is not None and 200 <= result[0] < 300:
            self.posted.append(url)
        return result

    def _run(self, **over):
        """(rc, stdout, stderr)."""
        kwargs = dict(sport="mlb", date_str=DATE, marker_path=self.marker_path,
                      card_path=self.ledger_path, snapshot_provider=_fake_snapshot)
        kwargs.update(over)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(discord_feed, "_post_one", self._fake_post_one), \
                redirect_stdout(out), redirect_stderr(err):
            rc = discord_feed.run(**kwargs)
        return rc, out.getvalue(), err.getvalue()

    def _marker_hashes(self):
        return [r["webhook_hash"] for r in discord_feed._read_markers(self.marker_path)]

    def _marker_text(self):
        try:
            with open(self.marker_path, encoding="utf-8") as fh:
                return fh.read()
        except FileNotFoundError:
            return ""


class MultiWebhookTest(_FeedFixture):
    def test_two_webhooks_both_post_two_markers_second_run_posts_nothing(self):
        rc, out, _ = self._run(webhook_urls=[URL_A, URL_B])
        self.assertEqual(rc, 0)
        self.assertEqual(self.posted, [URL_A, URL_B])
        self.assertEqual(sorted(self._marker_hashes()),
                         sorted(discord_feed._webhook_hash(u) for u in (URL_A, URL_B)))

        rc2, out2, _ = self._run(webhook_urls=[URL_A, URL_B])
        self.assertEqual(rc2, 0)
        self.assertEqual(self.posted, [URL_A, URL_B], "a second run must post nothing")
        self.assertEqual(out2.count("already posted"), 2)
        self.assertEqual(len(self._marker_hashes()), 2)

    def test_a_new_webhook_added_later_gets_the_card_and_old_ones_do_not(self):
        self._run(webhook_urls=[URL_A])
        self._run(webhook_urls=[URL_A, URL_B])
        self.assertEqual(self.posted, [URL_A, URL_B])

    def test_one_failing_webhook_does_not_stop_the_other_nor_get_a_marker(self):
        failures = {
            "http 404 (webhook deleted)": (404, "Not Found"),
            "http 429": (429, "Too Many Requests"),
            "network error": (None, "Name or service not known"),
            "unexpected exception": OSError("boom"),
        }
        for label, failure in failures.items():
            with self.subTest(label):
                if os.path.exists(self.marker_path):
                    os.remove(self.marker_path)
                self.posted.clear()
                self.attempted.clear()
                self.outcome = {URL_A: failure}

                rc, out, err = self._run(webhook_urls=[URL_A, URL_B])
                self.assertNotEqual(rc, 0)
                self.assertEqual(self.posted, [URL_B], "B must still post")
                self.assertEqual(self._marker_hashes(), [discord_feed._webhook_hash(URL_B)],
                                 "only the success gets a marker")
                escalations = [l for l in out.splitlines() if l.startswith("ESCALATE:")]
                self.assertEqual(len(escalations), 1)
                self.assertIn(discord_feed._webhook_hash(URL_A)[:8], escalations[0])
                self.assertNotIn(discord_feed._webhook_hash(URL_B)[:8], escalations[0])

                # Re-run with A healthy: ONLY A is retried.
                self.outcome = {}
                self.attempted.clear()
                rc2, _, _ = self._run(webhook_urls=[URL_A, URL_B])
                self.assertEqual(rc2, 0)
                self.assertEqual(self.attempted, [URL_A])
                self.assertEqual(sorted(self._marker_hashes()),
                                 sorted(discord_feed._webhook_hash(u) for u in (URL_A, URL_B)))

    def test_every_webhook_failing_gives_one_escalate_line_each(self):
        self.outcome = {URL_A: (404, "Not Found"), URL_B: (None, "timed out")}
        rc, out, _ = self._run(webhook_urls=[URL_A, URL_B])
        self.assertNotEqual(rc, 0)
        escalations = [l for l in out.splitlines() if l.startswith("ESCALATE:")]
        self.assertEqual(len(escalations), 2)
        self.assertFalse(os.path.exists(self.marker_path))

    def test_a_card_update_posts_only_to_the_webhooks_that_were_behind(self):
        self._run(webhook_urls=[URL_A])
        self.assertEqual(self.posted, [URL_A])
        pick_a_moved = game_entry(game_pk=9001, event_id="evt-9001", price=-105, score=0.20)
        card_ledger.publish_v2(
            {"date": DATE, "all_bets": [pick_a_moved], "params": best_bets_card.V2},
            now="2026-09-20T18:10:00Z", path=self.ledger_path)
        titles = []
        real = self._fake_post_one

        def spy(url, message):
            titles.append((url, message["embeds"][0]["title"]))
            return real(url, message)
        with mock.patch.object(self, "_fake_post_one", spy):
            self._run(webhook_urls=[URL_A, URL_B])
        by_url = dict(titles)
        self.assertIn("card update", by_url[URL_A].lower())
        self.assertNotIn("card update", by_url[URL_B].lower(), "B never saw the first card")


class WebhookListParsingTest(unittest.TestCase):
    def test_duplicates_blanks_and_separators_collapse(self):
        raw = f"  {URL_A} ,, {URL_B}\n\n{URL_A}\r\n , {URL_C},\n  "
        self.assertEqual(discord_feed.parse_webhook_urls(raw), [URL_A, URL_B, URL_C])
        self.assertEqual(discord_feed.parse_webhook_urls(None, "", "  \n,"), [])

    def test_run_posts_once_per_distinct_webhook(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "cards_v2.jsonl")
            marker = os.path.join(tmp, "m", "posted.jsonl")
            _seed_two_picks_one_fill_one_withdrawn(ledger)
            posted = []
            with mock.patch.object(discord_feed, "_post_one",
                                   lambda url, msg: posted.append(url) or (204, None)), \
                    redirect_stdout(io.StringIO()):
                rc = discord_feed.run(
                    "mlb", DATE, webhook_url=URL_A,
                    webhook_urls=f"{URL_A}, ,{URL_B}\n{URL_B}\n,",
                    marker_path=marker, card_path=ledger, snapshot_provider=_fake_snapshot)
            self.assertEqual(rc, 0)
            self.assertEqual(posted, [URL_A, URL_B])
            self.assertEqual(len(discord_feed._read_markers(marker)), 2)

    def test_main_merges_the_single_and_the_list_env_vars_and_the_flag(self):
        seen = {}

        def fake_run(sport, date_str, **kwargs):
            seen.update(kwargs)
            return 0
        env = {"DISCORD_WEBHOOK_URL": URL_A,
               "DISCORD_WEBHOOK_URLS": f"{URL_B},\n{URL_A}\n{URL_C}"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(discord_feed, "run", fake_run):
            discord_feed.main(["--sport", "mlb", "--date", DATE, "--webhook-url", FAKE_URL])
        self.assertEqual(seen["webhook_urls"], [FAKE_URL, URL_A, URL_B, URL_C])

    def test_main_with_neither_env_var_passes_no_webhooks(self):
        seen = {}

        def fake_run(sport, date_str, **kwargs):
            seen.update(kwargs)
            return 0
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISCORD_WEBHOOK_URL", "DISCORD_WEBHOOK_URLS")}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(discord_feed, "run", fake_run):
            discord_feed.main(["--sport", "mlb", "--date", DATE, "--dry-run"])
        self.assertEqual(seen["webhook_urls"], [])


class NoUrlAnywhereTest(_FeedFixture):
    """The URL (and its token) must not appear in stdout, stderr or the
    marker file on ANY path, including every failure path -- and a failure
    path that echoes a URL into its message must be caught here."""

    def _assert_clean(self, out, err):
        blob = out + err + self._marker_text()
        for url in ALL_URLS:
            self.assertNotIn(url, blob)
            for seg in url.split("/")[-2:]:
                self.assertNotIn(seg, blob)

    def test_failure_text_that_quotes_the_url_is_scrubbed(self):
        # The fake transport itself leaks the URL in its reason text, as a
        # urllib error can. The run must not print it.
        self.outcome = {
            URL_A: (None, f"cannot reach {URL_A} (via {URL_A.split('://')[1]})"),
            URL_B: (404, f"Not Found: {URL_B}"),
            URL_C: OSError(f"connection reset talking to {URL_C}"),
        }
        rc, out, err = self._run(webhook_urls=[URL_A, URL_B, URL_C, FAKE_URL])
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.posted, [FAKE_URL])
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("ESCALATE:")]), 3)
        self._assert_clean(out, err)

    def test_success_dry_run_and_already_posted_paths_are_clean(self):
        rc, out, err = self._run(webhook_urls=[URL_A, URL_B])
        self._assert_clean(out, err)
        rc, out, err = self._run(webhook_urls=[URL_A, URL_B])  # already posted
        self._assert_clean(out, err)
        rc, out, err = self._run(webhook_urls=[URL_A, URL_B], dry_run=True)
        self.assertEqual(rc, 0)
        self._assert_clean(out, err)

    def test_real_post_one_scrubs_urllib_errors_and_names_unexpected_ones_by_class(self):
        from urllib.error import HTTPError, URLError
        cases = [
            URLError(f"<urlopen error for {URL_A}>"),
            HTTPError(URL_A, 404, f"Not Found for {URL_A}", {}, None),
            ValueError(f"unknown url type: {URL_A!r}"),
            TimeoutError(f"timed out reading {URL_A}"),
        ]
        for exc in cases:
            with self.subTest(type(exc).__name__):
                with mock.patch.object(discord_feed, "urlopen", side_effect=exc):
                    status, reason = discord_feed._post_one(URL_A, {"content": "x"})
                self.assertNotIn(URL_A, str(reason))
                self.assertNotIn("token-A", str(reason))

    def test_post_one_does_not_raise_on_a_malformed_url(self):
        status, reason = discord_feed._post_one("not a url", {"content": "x"})
        self.assertIsNone(status)
        self.assertNotIn("not a url", str(reason))


class LegacySingleWebhookTest(_FeedFixture):
    def test_single_url_behaves_as_before(self):
        rc, out, _ = self._run(webhook_url=FAKE_URL)
        self.assertEqual(rc, 0)
        self.assertEqual(self.posted, [FAKE_URL])
        self.assertTrue(out.startswith("posted: mlb 2026-09-20 (card)"), out)
        rows = discord_feed._read_markers(self.marker_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["webhook_hash"], discord_feed._webhook_hash(FAKE_URL))
        rc2, out2, _ = self._run(webhook_url=FAKE_URL)
        self.assertEqual((rc2, len(self.posted)), (0, 1))
        self.assertTrue(out2.startswith("already posted: mlb 2026-09-20 (card"), out2)

    def test_single_and_list_with_the_same_url_post_once(self):
        self._run(webhook_url=FAKE_URL, webhook_urls=[FAKE_URL])
        self.assertEqual(self.posted, [FAKE_URL])

    def test_no_webhook_at_all_is_one_escalate_and_nonzero(self):
        rc, out, _ = self._run()
        self.assertEqual(rc, 1)
        self.assertEqual(self.attempted, [])
        self.assertEqual([l for l in out.splitlines() if l.startswith("ESCALATE:")],
                         [l for l in out.splitlines()])


def _snapshot_with_reason(reason):
    snap = _fake_snapshot("nfl")
    snap["current"] = {**snap["current"], "grading_state": "ungraded", "reason": reason}
    return snap


class NflFeedTest(unittest.TestCase):
    DATE_NFL = "2026-10-04"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger_path = os.path.join(self._tmp.name, "cards_nfl_v1.jsonl")
        self.marker_path = os.path.join(self._tmp.name, "watch", "discord_feed_posted.jsonl")

    def _publish(self, picks):
        card = {"date": self.DATE_NFL, "sport": "nfl", "rule": "NFL_CARD_V2",
                "picks": picks, "basis": "NFL basis text", "week": 5}
        return card_ledger.publish(card, now="2026-10-04T10:00:00+00:00",
                                   path=self.ledger_path, sport="nfl")

    @staticmethod
    def _pick(gid, team, price, rank):
        return {"game_id": gid, "sport": "nfl", "market": "moneyline", "side": "home",
                "team": team, "home_team": team, "away_team": "Other", "price": price,
                "book": "betmgm", "first_pitch_utc": "2026-10-04T17:00:00Z",
                "market_probability": 0.55, "rank": rank,
                "bet": f"Take {team} to win at {price:+d}"}

    def _run(self, urls=(URL_A,), **over):
        posted, out = [], io.StringIO()
        kwargs = dict(webhook_urls=list(urls), marker_path=self.marker_path,
                      card_path=self.ledger_path, snapshot_provider=_fake_snapshot)
        kwargs.update(over)
        with mock.patch.object(discord_feed, "_post_one",
                               lambda url, msg: posted.append((url, msg)) or (204, None)), \
                redirect_stdout(out):
            rc = discord_feed.run("nfl", self.DATE_NFL, **kwargs)
        return rc, posted, out.getvalue()

    def test_posts_the_nfl_card_when_one_exists(self):
        self._publish([self._pick("g1", "Buffalo Bills", -130, 1),
                       self._pick("g2", "Miami Dolphins", 120, 2)])
        rc, posted, out = self._run(urls=(URL_A, URL_B))
        self.assertEqual(rc, 0)
        self.assertEqual([u for u, _ in posted], [URL_A, URL_B])
        embed = posted[0][1]["embeds"][0]
        self.assertIn("NFL card", embed["title"])
        picks = next(f for f in embed["fields"] if f["name"] == "Picks")["value"]
        self.assertIn("Take Buffalo Bills to win at -130", picks)
        self.assertIn("Take Miami Dolphins to win at +120", picks)
        self.assertEqual(len(discord_feed._read_markers(self.marker_path)), 2)
        self.assertEqual(discord_feed._read_markers(self.marker_path)[0]["sport"], "nfl")

    def test_no_nfl_card_prints_one_plain_line_posts_nothing_and_is_not_an_error(self):
        rc, posted, out = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(posted, [])
        self.assertEqual(out.strip(), f"no published card for {self.DATE_NFL}")
        self.assertFalse(os.path.exists(self.marker_path))

    def test_entries_at_minus_200_or_shorter_are_never_posted(self):
        self._publish([self._pick("g1", "Buffalo Bills", -130, 1),
                       self._pick("g2", "Kansas City Chiefs", -200, 2),
                       self._pick("g3", "Detroit Lions", -250, 3),
                       self._pick("g4", "Dallas Cowboys", -199, 4)])
        rc, posted, _ = self._run()
        self.assertEqual(rc, 0)
        blob = json.dumps(posted[0][1])
        self.assertIn("Buffalo Bills", blob)
        self.assertIn("Dallas Cowboys", blob)       # -199 is fine
        self.assertNotIn("Kansas City Chiefs", blob)
        self.assertNotIn("Detroit Lions", blob)

    def test_a_card_whose_every_entry_is_too_short_posts_nothing_and_says_so(self):
        self._publish([self._pick("g1", "Detroit Lions", -250, 1)])
        rc, posted, out = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(posted, [])
        self.assertIn("nothing to post", out)
        self.assertFalse(os.path.exists(self.marker_path))


class ContentRulesTest(unittest.TestCase):
    def test_price_rule_boundaries(self):
        ok = discord_feed._is_postable
        self.assertTrue(ok({"price": -199}))
        self.assertFalse(ok({"price": -200}))
        self.assertFalse(ok({"price": -1000}))
        self.assertTrue(ok({"price": 150}))
        self.assertTrue(ok({"price": None}))

    def test_banned_scan_catches_the_words_and_allows_the_one_sentence(self):
        for word in ("edge", "profit", "profits", "locked-in", "lock", "guaranteed",
                     "guarantee", "sharp", "winning", "Bet Check"):
            with self.subTest(word):
                self.assertNotEqual(discord_feed.banned_words_in({"x": f"a {word} b"}), [])
        self.assertEqual(
            discord_feed.banned_words_in({"x": "Fine. No edge is claimed. Fine."}), [])
        self.assertNotEqual(
            discord_feed.banned_words_in({"x": "No edge is claimed. We have an edge."}), [])

    def test_real_payloads_are_clean_card_fills_record_and_nfl(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "cards_v2.jsonl")
            _seed_two_picks_one_fill_one_withdrawn(ledger)
            payloads = [
                discord_feed.assemble("mlb", DATE, card_path=ledger,
                                      snapshot_provider=_fake_snapshot),
                discord_feed.assemble("mlb", DATE, record_only=True,
                                      snapshot_provider=_fake_snapshot),
                discord_feed.assemble("nfl", DATE, record_only=True,
                                      snapshot_provider=_fake_snapshot),
            ]
        for assembled in payloads:
            self.assertEqual(discord_feed.banned_words_in(assembled.messages), [])
            self.assertNotIn("bet check", json.dumps(assembled.messages).lower())

    def test_the_record_only_description_does_not_say_profit(self):
        text = discord_feed._stake_basis_text()
        self.assertNotIn("profit", text.lower())
        self.assertIn("net units", text)

    def test_a_payload_that_trips_the_scan_is_not_posted(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "cards_v2.jsonl")
            marker = os.path.join(tmp, "m", "posted.jsonl")
            _seed_two_picks_one_fill_one_withdrawn(ledger)
            posted, out = [], io.StringIO()

            def dirty_snapshot(sport, **kwargs):
                snap = _fake_snapshot(sport)
                snap["current"] = {**snap["current"], "grading_state": "ungraded",
                                   "reason": "a sharp edge in the profit column"}
                return snap
            with mock.patch.object(discord_feed, "_post_one",
                                   lambda url, msg: posted.append(url) or (204, None)), \
                    redirect_stdout(out):
                rc = discord_feed.run("mlb", DATE, webhook_urls=[URL_A], marker_path=marker,
                                      card_path=ledger, snapshot_provider=dirty_snapshot)
        self.assertEqual(rc, 1)
        self.assertEqual(posted, [])
        self.assertIn("ESCALATE", out.getvalue())
        self.assertIn("banned wording", out.getvalue())

    def test_fills_are_labelled_and_a_dry_run_posts_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = os.path.join(tmp, "cards_v2.jsonl")
            _seed_two_picks_one_fill_one_withdrawn(ledger)
            out = io.StringIO()
            with mock.patch.object(discord_feed, "_post_one",
                                   side_effect=AssertionError("dry run must not post")), \
                    redirect_stdout(out):
                rc = discord_feed.run("mlb", DATE, webhook_urls=[URL_A], dry_run=True,
                                      card_path=ledger, snapshot_provider=_fake_snapshot)
        self.assertEqual(rc, 0)
        names = [f["name"] for f in json.loads(out.getvalue().splitlines()[0])["embeds"][0]["fields"]]
        self.assertIn("Fills", names)


class BannedWordsAreWholeWordsTest(unittest.TestCase):
    """A player's surname is not a tout word."""

    def test_surnames_that_start_with_a_banned_word_are_clean(self):
        payload = {"content": "Tyler Lockett over 4.5 receptions at -120. "
                              "Brandon Lockridge over 0.5 hits at -130. "
                              "Edgar Quero under 1.5 total bases."}
        self.assertEqual(discord_feed.banned_words_in(payload), [])

    def test_the_words_themselves_and_their_inflections_are_caught(self):
        for text in ("a lock tonight", "locked-in value", "profits", "an edge",
                     "guaranteed", "sharp money", "winning picks", "Bet Check"):
            self.assertTrue(discord_feed.banned_words_in({"content": text}), text)


if __name__ == "__main__":
    unittest.main()
