"""The fan lane of the coach report card (docs/COACH_REPORT_CARD.md, "The fan lane"): fan tips read from the
site's public export, recorded once, graded like the coach's suggestions, published beside them and never mixed in.

No network (``urlopen`` is injected and serves a fake export), no real ledger (everything lives under a temp
directory), and the ``hounds`` registry is a stub. Export rows are untrusted data: the tests that matter hand the
intake invalid values, repeats, floods and hostile nicknames, and prove a fan can never cause a challenger.

Nothing here needs FastAPI except the one route test, which skips cleanly where it is missing (Linux CI has none).
The page tests run the real page scripts under node against payloads built by the real Python.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

from src.hounds import coach_card as C
from src.hounds import coach_grade as G
from src.hounds import coach_intake as I
from src.hounds import coach_report as R
from src.hounds import kennel_feed as K
from src.hounds.learning import ledger as L
from tests import _coach_card_fixtures as F
from tests._coach_fixtures import NOW, World
from tests.hounds_web_runner import HAS_NODE, run_page

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = {"alpha_pup": object(), "beta_pup": object()}
BASE = "https://fan-export.test"
GAPS = (0.015, 0.02, 0.025, 0.03, 0.035, 0.04)
BARS = (80, 100, 120, 140, 160, 180, 200)


def tip(n, hound="alpha_pup", values=None, *, nickname="Ann", created="2026-11-20T08:00:00Z", **extra) -> dict:
    """One row of the export, in the shape src/hounds/fan_tips.py:export gives."""
    row = {"id": f"tip_{n:010x}", "hound_id": hound, "values": values if values is not None else {"GAP": 0.03},
           "champion_values": {"GAP": 0.02, "BARS": 120}, "champion_version": 1, "nickname": nickname,
           "created_utc": created}
    row.update(extra)
    return row


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body

    def read(self, limit=None):
        data = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode("utf-8")
        return data if limit is None else data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class FakeSite:
    """``urlopen`` for the whole run: the fake export on the site, an issues list on api.github.com."""

    def __init__(self, tips=None, issues=None, tips_error=None, issues_error=None):
        self.tips, self.issues = tips if tips is not None else [], issues if issues is not None else []
        self.tips_error, self.issues_error = tips_error, issues_error
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        url = request.full_url
        if "api.github.com" in url:
            if self.issues_error:
                raise self.issues_error
            return FakeResponse(self.issues)
        if self.tips_error:
            raise self.tips_error
        return FakeResponse({"since": None, "count": len(self.tips), "tips": self.tips})

    def tip_urls(self):
        return [r.full_url for r in self.requests if "api.github.com" not in r.full_url]


class FanCase(unittest.TestCase):
    def setUp(self):
        self.w = World(ids=("alpha_pup", "beta_pup"))
        self.addCleanup(self.w.close)
        self.paths = C.Paths.default(self.w.root / "evidence")
        (self.w.root / "evidence").mkdir(exist_ok=True)

    def intake(self, rows, *, now=NOW, say=None):
        out = io.StringIO()
        with mock.patch("src.hounds.learning.pause.config_path", return_value=self.w.root / "none.json"), \
                redirect_stdout(out):
            counts = I.record_fan_lane(rows, scope=self.w.scope, card_paths=self.paths, now=now,
                                       tunable_cfg=self.w.cfg, registry=REGISTRY, say=say or (lambda *_a: None))
        return counts

    def card(self):
        return C.load(self.paths)


class TheExportReader(unittest.TestCase):
    def test_it_asks_the_sites_public_export_with_a_user_agent_and_the_since_cursor(self):
        site = FakeSite()
        I.fetch_tip_export("2026-11-20T08:00:00Z", base_url=BASE + "/", urlopen=site)
        request = site.requests[0]
        self.assertEqual(request.full_url, f"{BASE}/hounds/tips/export?since=2026-11-20T08%3A00%3A00Z")
        self.assertTrue(request.get_header("User-agent"))
        self.assertEqual(request.get_method(), "GET")

    def test_with_no_cursor_it_asks_for_everything(self):
        site = FakeSite()
        I.fetch_tip_export(None, base_url=BASE, urlopen=site)
        self.assertEqual(site.requests[0].full_url, f"{BASE}/hounds/tips/export")

    def test_the_base_url_is_the_apps_own_public_address_with_an_env_override(self):
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "http://localhost:9"}):
            self.assertEqual(I.tips_base_url(), "http://localhost:9")
            site = FakeSite()
            I.fetch_tip_export(None, urlopen=site)
            self.assertTrue(site.requests[0].full_url.startswith("http://localhost:9/hounds/tips/export"))
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": ""}):
            self.assertEqual(I.tips_base_url(), "https://linehound.app")

    def test_every_failure_is_one_clean_error_and_a_404_names_the_url(self):
        for exc in (urllib.error.HTTPError("u", 404, "nf", {}, None), urllib.error.URLError("down"),
                    TimeoutError("slow")):
            with self.assertRaises(I.IntakeError) as ctx:
                I.fetch_tip_export(None, base_url=BASE, urlopen=FakeSite(tips_error=exc))
            self.assertEqual(ctx.exception.code, "tips_failed")
        with self.assertRaises(I.IntakeError) as ctx:
            I.fetch_tip_export(None, base_url=BASE, urlopen=FakeSite(tips_error=urllib.error.HTTPError(
                "u", 404, "nf", {}, None)))
        self.assertIn("404", str(ctx.exception))

    def test_a_body_that_is_not_a_tip_list_is_an_error(self):
        for body in (b"<html>nope</html>", {"message": "x"}, {"tips": "none"}, [1, 2]):
            site = mock.Mock(return_value=FakeResponse(body))
            with self.assertRaises(I.IntakeError):
                I.fetch_tip_export(None, base_url=BASE, urlopen=site)

    def test_a_huge_body_is_refused_unread(self):
        big = b"x" * (I.TIPS_MAX_BYTES + 10)
        with self.assertRaises(I.IntakeError) as ctx:
            I.fetch_tip_export(None, base_url=BASE, urlopen=mock.Mock(return_value=FakeResponse(big)))
        self.assertIn("larger than expected", str(ctx.exception))


class Dedupe(FanCase):
    def test_a_tip_is_recorded_once_whatever_the_cursor_re_reads(self):
        rows = [tip(1), tip(2, values={"GAP": 0.035})]
        self.assertEqual(self.intake(rows)["recorded"], 2)
        again = self.intake(rows, now=NOW + timedelta(hours=1))
        self.assertEqual((again["recorded"], again["already"]), (0, 2))
        self.assertEqual(len(self.card().fans), 2)

    def test_the_row_carries_what_grading_needs_and_the_tip_id(self):
        self.intake([tip(7, values={"GAP": 0.035}, nickname="Ann Lee")])
        key, row = next(iter(self.card().fans.items()))
        self.assertEqual(key, C.FAN_KEY_BASE + 1)
        self.assertEqual((row["kind"], row["mode"], row["tip_id"]), (C.K_FAN_TIP, "fan", tip(7)["id"]))
        self.assertEqual((row["hound"], row["hound_name"]), ("alpha_pup", "Alpha Pup"))
        self.assertEqual(row["champion_values"]["GAP"], 0.02)
        self.assertEqual(row["suggested_values"]["GAP"], 0.035)
        self.assertEqual(row["changes"][0]["new_text"], "3.5 points or more")
        self.assertEqual((row["nickname"], row["proposed_by"]), ("Ann Lee", "fan"))
        self.assertEqual(row["recorded_utc"], "2026-11-20T12:00:00Z")       # forward grading starts when WE record
        self.assertEqual(row["tip_created_utc"], "2026-11-20T08:00:00Z")
        self.assertIsNone(row["challenger_id"])

    def test_fan_keys_are_far_from_github_issue_numbers_and_never_reused(self):
        self.intake([tip(1), tip(2, values={"GAP": 0.035})])
        self.assertEqual(sorted(self.card().fans), [C.FAN_KEY_BASE + 1, C.FAN_KEY_BASE + 2])
        self.assertGreater(C.FAN_KEY_BASE, 10_000_000)
        self.intake([tip(3, values={"GAP": 0.04})], now=NOW + timedelta(hours=1))
        self.assertIn(C.FAN_KEY_BASE + 3, self.card().fans)

    def test_the_cursor_resumes_a_minute_before_the_newest_recorded_tip(self):
        self.assertIsNone(I.tips_since(self.card()))
        self.intake([tip(1, created="2026-11-20T08:00:30Z")])
        self.assertEqual(I.tips_since(self.card()), "2026-11-20T07:59:30Z")


class InvalidValuesAreRefused(FanCase):
    def refuse(self, **kw):
        rows = [tip(1, **kw)]
        counts = self.intake(rows)
        self.assertEqual(self.card().fans, {}, kw)
        return counts

    def test_off_grid_out_of_bounds_unknown_knob_and_non_numbers_are_refused(self):
        for values in ({"GAP": 0.0333}, {"GAP": 0.5}, {"NOPE": 1}, {"GAP": "high"}, {"GAP": True}, {"BARS": 125},
                       {"GAP": float("nan")}, {"GAP": float("inf")}, {}):
            self.assertEqual(self.refuse(values=values)["invalid"], 1, values)

    def test_three_knobs_or_no_change_at_all_are_refused(self):
        three = {"GAP": 0.03, "BARS": 140, "NOPE": 1}
        self.assertEqual(self.refuse(values=three)["invalid"], 1)
        self.assertEqual(self.refuse(values={"GAP": 0.02})["invalid"], 1)     # the champion's own value

    def test_a_dog_with_no_dials_or_not_in_the_registry_is_refused(self):
        self.assertEqual(self.refuse(hound="plain_dog")["not_tunable"], 1)
        self.assertEqual(self.refuse(hound="nope_pup")["not_tunable"], 1)

    def test_malformed_rows_are_dropped_not_a_crash(self):
        counts = self.intake([None, "x", {"id": "tip_1"}, tip(1, id="../etc"), tip(2, created="soon"),
                              tip(3, values="GAP=0.03"), tip(4, hound=7), tip(5, id="x" * 41)])
        self.assertEqual(counts["malformed"], 8)
        self.assertEqual(self.card().fans, {})

    def test_the_values_are_judged_against_the_champion_as_it_stands_not_the_one_in_the_row(self):
        row = tip(1, values={"GAP": 0.03}, champion_values={"GAP": 0.03, "BARS": 120})
        self.assertEqual(self.intake([row])["recorded"], 1)                     # the export's copy is not trusted
        self.assertEqual(self.card().fans[C.FAN_KEY_BASE + 1]["champion_values"]["GAP"], 0.02)

    def test_a_refusal_writes_nothing_so_a_flood_of_junk_cannot_fill_the_ledger(self):
        self.intake([tip(i, values={"GAP": 0.99}) for i in range(1, 30)])
        self.assertFalse(self.paths.ledger.exists())


class NeverAChallenger(FanCase):
    def test_an_eligible_hound_still_gets_no_challenger_and_the_proposal_code_is_never_called(self):
        # alpha_pup has 60 graded forward bets: a COACH tip on it would become a shadow challenger
        with mock.patch("src.hounds.learning.proposals.propose_pack") as propose, \
                mock.patch("src.hounds.learning.proposals.eligibility") as eligibility:
            counts = self.intake([tip(1), tip(2, values={"GAP": 0.035}), tip(3, hound="beta_pup")])
        self.assertEqual(counts["recorded"], 3)
        propose.assert_not_called()
        eligibility.assert_not_called()
        self.assertEqual(L.read_state(self.w.scope).live(), [])
        self.assertFalse(self.w.scope.events.exists())                          # not a line in the referee's log
        for row in self.card().fans.values():
            self.assertEqual((row["mode"], row["challenger_id"]), ("fan", None))

    def test_the_card_counts_a_fan_tip_apart_from_the_coachs_suggestions(self):
        self.intake([tip(1)])
        card = self.card()
        self.assertEqual((len(card.suggestions), len(card.refused), len(card.fans)), (0, 0, 1))
        self.assertEqual(R.build_from_card(card)["summary"]["suggestions"], 0)


class TheDailyCaps(FanCase):
    def valid_values(self):
        out = [{"GAP": g, "BARS": b} for g in GAPS for b in BARS if (g, b) != (0.02, 120)]
        self.assertGreaterEqual(len(out), 25)
        return out

    def test_at_most_twenty_rows_a_utc_day_first_come_first_served(self):
        rows = [tip(i, values=v, created=f"2026-11-20T08:{i:02d}:00Z") for i, v in enumerate(self.valid_values()[:25])]
        counts = self.intake(rows)
        self.assertEqual((counts["recorded"], counts["over_cap"]), (20, 5))
        kept = {r["tip_id"] for r in self.card().fans.values()}
        self.assertEqual(kept, {r["id"] for r in rows[:20]})                    # the earliest twenty
        # another run the same day changes nothing, the next day starts again
        self.assertEqual(self.intake(rows, now=NOW + timedelta(hours=2))["recorded"], 0)
        nxt = [tip(100 + i, values=v, created="2026-11-21T08:00:00Z") for i, v in enumerate(self.valid_values()[:3])]
        self.assertEqual(self.intake(nxt, now=NOW + timedelta(days=1))["recorded"], 3)

    def test_the_day_is_the_day_the_fan_sent_it_not_the_day_we_read_it(self):
        rows = [tip(i, values=v, created="2026-11-19T23:59:00Z") for i, v in enumerate(self.valid_values()[:21])]
        self.assertEqual(self.intake(rows, now=NOW)["recorded"], 20)
        late = tip(500, values=self.valid_values()[30], created="2026-11-20T00:01:00Z")
        self.assertEqual(self.intake([late], now=NOW)["recorded"], 1)

    def test_a_repeat_is_a_count_on_the_first_row_and_takes_no_slot(self):
        rows = [tip(1, nickname="Ann", created="2026-11-20T08:00:00Z"),
                tip(2, nickname="Bob", created="2026-11-20T09:00:00Z"),
                tip(3, nickname="Cy", created="2026-11-20T10:00:00Z")]
        counts = self.intake(rows)
        self.assertEqual((counts["recorded"], counts["collapsed"]), (1, 2))
        card = self.card()
        key = C.FAN_KEY_BASE + 1
        self.assertEqual(list(card.fans), [key])
        self.assertEqual(card.fans[key]["nickname"], "Ann")                     # the first row keeps its name
        self.assertEqual(card.fan_counts[key], 3)
        self.assertEqual(set(card.fan_dup_of), {rows[1]["id"], rows[2]["id"]})
        self.assertEqual(card.fan_last_tip_utc, "2026-11-20T10:00:00Z")
        # re-reading the same export collapses nothing twice
        again = self.intake(rows, now=NOW + timedelta(hours=1))
        self.assertEqual((again["collapsed"], again["already"]), (0, 3))
        self.assertEqual(self.card().fan_counts[key], 3)

    def test_the_same_values_on_another_day_or_another_hound_are_a_new_row(self):
        rows = [tip(1), tip(2, created="2026-11-21T08:00:00Z"), tip(3, hound="beta_pup")]
        counts = self.intake(rows)
        self.assertEqual((counts["recorded"], counts["collapsed"]), (3, 0))

    def test_a_repeat_is_found_even_when_the_values_are_spelled_differently(self):
        rows = [tip(1, values={"GAP": 0.03}), tip(2, values={"GAP": 0.03, "BARS": 120}),
                tip(3, values={"GAP": 0.0300000001})]
        self.assertEqual(self.intake(rows)["collapsed"], 2)

    def test_repeats_do_not_use_up_the_daily_twenty(self):
        values = self.valid_values()
        rows = [tip(1000 + i, created="2026-11-20T07:00:00Z") for i in range(10)]            # ten of one tip
        rows += [tip(i, values=v, created=f"2026-11-20T08:{i:02d}:00Z") for i, v in enumerate(values[:30]) if v != {"GAP": 0.03}][:21]
        counts = self.intake(rows)
        self.assertEqual(counts["collapsed"], 9)
        self.assertEqual(len(self.card().fans), 20)


class NicknamesAreCleaned(FanCase):
    def test_only_letters_numbers_and_spaces_survive_and_it_is_capped(self):
        self.assertEqual(I.clean_nickname("  Ann‮   Lee!! "), "Ann Lee")
        self.assertEqual(I.clean_nickname("<script>alert(1)</script>"), "script alert 1 scrip")        # 20 characters, the tip box's own cap
        self.assertEqual(I.clean_nickname("A" * 50), "A" * 20)
        self.assertEqual(I.clean_nickname("@everyone"), "everyone")

    def test_nothing_usable_or_not_allowed_on_the_site_is_no_nickname(self):
        for raw in (None, 12, "", "   ", "!!!", ["Ann"], "official", "Sex"):
            self.assertIsNone(I.clean_nickname(raw), raw)

    def test_the_recorded_row_carries_the_cleaned_nickname(self):
        self.intake([tip(1, nickname="<b>Bob</b>")])
        self.assertEqual(next(iter(self.card().fans.values()))["nickname"], "b Bob b")


class ReportShape(FanCase):
    def fwd(self, key, label, n, units, utc):
        C.append(self.paths, C.K_FORWARD, now=C.parse(utc), issue=key, hound="alpha_pup", label=label,
                 n_paired=n, n_dates=min(n, 6), units_diff=units, champion={"bets": n}, suggested={"bets": n})

    def hind(self, key, units):
        C.append(self.paths, C.K_HINDSIGHT, now=NOW, issue=key, hound="alpha_pup", hindsight=True, status="ok",
                 units_diff=units, window_first="2026-10-01", window_last="2026-10-31", window_days=30)

    def coach_tip(self, issue, label, n, units, hind=None):
        row = F.suggestion_row(issue=issue, recorded="2026-11-10T12:00:00Z")
        C.append(self.paths, C.K_SUGGESTION, now=C.parse(row["recorded_utc"]), **row)
        C.append(self.paths, C.K_FORWARD, now=C.parse("2026-11-12T00:00:00Z"), issue=issue, hound="fake_dog",
                 label=label, n_paired=n, n_dates=5, units_diff=units)
        if hind is not None:
            C.append(self.paths, C.K_HINDSIGHT, now=NOW, issue=issue, hound="fake_dog", hindsight=True,
                     status="ok", units_diff=hind)

    def report(self, **kw):
        R._CACHE.clear()
        return R.build(self.paths, **kw)

    def test_the_fans_block_is_apart_from_the_coachs_numbers(self):
        self.intake([tip(1), tip(2, values={"GAP": 0.035}, nickname=None), tip(3, values={"GAP": 0.04}),
                     tip(4)])                                                     # tip 4 repeats tip 1
        k1, k2, k3 = (C.FAN_KEY_BASE + i for i in (1, 2, 3))
        self.fwd(k1, "HELPED", 25, 3.0, "2026-11-22T00:00:00Z")
        self.fwd(k2, "HURT", 22, -2.0, "2026-11-22T00:00:00Z")
        self.hind(k1, 1.5)
        self.hind(k2, -0.5)
        self.coach_tip(1, "HELPED", 30, 4.0, hind=2.0)
        rep = self.report()
        fans = rep["fans"]
        self.assertEqual(fans["summary"]["tips"], 3)
        self.assertEqual(fans["summary"]["sent"], 4)
        self.assertEqual((fans["summary"]["helped"], fans["summary"]["hurt"], fans["summary"]["too_early"]), (1, 1, 1))
        self.assertEqual(fans["summary"]["graded_forward"], 2)
        self.assertEqual(fans["summary"]["forward_units_diff"], 1.0)
        self.assertEqual(fans["summary"]["hindsight_units_diff"], 1.0)
        self.assertEqual(rep["summary"]["suggestions"], 1)                       # the coach's own count is untouched
        self.assertEqual((rep["summary"]["helped"], rep["summary"]["forward_units_diff"]), (1, 4.0))
        self.assertEqual(len(rep["items"]), 1)
        self.assertEqual(len(fans["items"]), 3)
        self.assertTrue(fans["computed"])
        self.assertIsNone(fans["message"])

    def test_each_fan_tip_reads_as_one_plain_line_with_both_grades(self):
        self.intake([tip(1, nickname="Ann"), tip(2, values={"GAP": 0.035}, nickname=None),
                     tip(3, nickname="Cy", created="2026-11-20T09:00:00Z")])      # tip 3 repeats tip 1
        self.hind(C.FAN_KEY_BASE + 1, 2.1)
        self.fwd(C.FAN_KEY_BASE + 1, "TOO EARLY", 3, 0.5, "2026-11-22T00:00:00Z")
        by = {i["tip_id"]: i for i in self.report()["fans"]["items"]}
        one = by[tip(1)["id"]]
        self.assertEqual(one["line"], 'Ann told Alpha Pup to change "How far the model must beat the market '
                         '(probability)" from 2.0 points or more to 3.0 points or more. Hindsight: +2.1u better. '
                         "Live: too early (3 bets). (2 fans sent this.)")
        self.assertEqual(one["count"], 2)
        anon = by[tip(2)["id"]]
        self.assertTrue(anon["line"].startswith("A fan told Alpha Pup to change"))
        self.assertIn("Hindsight: still being worked out. Live: too early (0 bets).", anon["line"])
        self.assertIs(one["hindsight"]["hindsight"], True)                       # hindsight is always labelled

    def test_only_the_latest_twenty_are_listed_newest_first(self):
        values = [{"GAP": g, "BARS": b} for g in GAPS for b in BARS if (g, b) != (0.02, 120)][:25]
        for i, v in enumerate(values):
            self.intake([tip(i + 1, values=v, created=f"2026-11-{1 + i // 20:02d}T08:{i % 20:02d}:00Z")],
                        now=C.parse(f"2026-11-{1 + i // 20:02d}T12:{i % 20:02d}:00Z"))
        items = self.report()["fans"]["items"]
        self.assertEqual(len(items), 20)
        self.assertEqual(items[0]["tip_id"], tip(25)["id"])
        self.assertEqual(self.report()["fans"]["summary"]["tips"], 25)

    def test_without_any_fan_tip_the_block_is_a_calm_sentence(self):
        F.record(self.paths)
        fans = self.report()["fans"]
        self.assertFalse(fans["computed"])
        self.assertEqual(fans["items"], [])
        self.assertEqual(fans["summary"]["tips"], 0)
        self.assertIn("No fan tips have been graded yet", fans["message"])
        self.assertIn("nothing has a live grade yet", fans["versus"]["line"])

    def test_coach_vs_the_fans_uses_live_grades_and_labels_hindsight_apart(self):
        self.intake([tip(1), tip(2, values={"GAP": 0.035}), tip(3, values={"GAP": 0.04})])
        self.fwd(C.FAN_KEY_BASE + 1, "HELPED", 25, 3.0, "2026-11-22T00:00:00Z")
        self.fwd(C.FAN_KEY_BASE + 2, "HURT", 22, -2.0, "2026-11-22T00:00:00Z")
        self.hind(C.FAN_KEY_BASE + 1, 1.5)
        self.coach_tip(1, "HELPED", 30, 4.0, hind=2.0)
        self.coach_tip(2, "HELPED", 30, 1.0)
        self.coach_tip(3, "NO DIFFERENCE", 30, 0.0)
        self.coach_tip(4, "TOO EARLY", 3, 0.0)
        v = self.report()["fans"]["versus"]
        self.assertEqual(v["line"], "Coach vs the fans: the coach helped 2 of 3 graded tips, the fans helped 1 of 2 "
                                    "(live grades only).")
        self.assertEqual(v["coach"], {"helped": 2, "graded": 3})
        self.assertEqual(v["fans"], {"helped": 1, "graded": 2})
        self.assertEqual(v["hindsight_line"], "Hindsight, a rehearsal and not evidence: the coach +2.0u, the fans +1.5u.")
        self.assertNotIn("hindsight", v["line"].lower())

    def test_a_fan_tip_does_not_make_the_coachs_card_look_changed(self):
        self.coach_tip(1, "TOO EARLY", 3, 0.0)
        before = self.report()["last_change_utc"]
        self.intake([tip(1)], now=C.parse("2026-12-01T00:00:00Z"))
        self.fwd(C.FAN_KEY_BASE + 1, "HELPED", 25, 3.0, "2026-12-02T00:00:00Z")
        self.assertEqual(self.report()["last_change_utc"], before)

    def test_the_dog_pages_grades_are_by_tip_id_and_a_repeat_shares_its_first_rows(self):
        self.intake([tip(1), tip(2, created="2026-11-20T09:00:00Z"), tip(3, values={"GAP": 0.035})])
        self.fwd(C.FAN_KEY_BASE + 1, "HELPED", 25, 3.0, "2026-11-22T00:00:00Z")
        self.hind(C.FAN_KEY_BASE + 1, 1.5)
        grades = R.fan_grades(self.card())
        self.assertEqual(set(grades), {tip(1)["id"], tip(2)["id"], tip(3)["id"]})
        self.assertEqual(grades[tip(1)["id"]], grades[tip(2)["id"]])
        self.assertEqual(grades[tip(1)["id"]], {"label": "HELPED", "units_diff": 3.0, "n_paired": 25,
                                                "hindsight_units_diff": 1.5})
        self.assertEqual(grades[tip(3)["id"]]["label"], "TOO EARLY")
        R._GRADES_CACHE.clear()
        with mock.patch.object(C.Paths, "default", staticmethod(lambda root=None: self.paths)):
            self.assertEqual(R.fan_grades_now()[tip(1)["id"]]["label"], "HELPED")
        R._GRADES_CACHE.clear()
        self.assertEqual(R.fan_grades_now(C.Paths.default(self.w.root / "nowhere")), {})


class GradedLikeTheCoach(unittest.TestCase):
    """The same grading code, end to end: a fan tip is recorded, then hindsight and forward rows land under its key."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.paths = F.paths_in(self.root)
        self.cfg = F.tunable_cfg()
        self.scope = L.Scope.house(self.root / "evidence")
        self.days = [F.iso_day("2026-10-02", i) for i in range(26)]

    def record(self, nickname="Ann", values=None):
        rows = [{"id": "tip_00000000a1", "hound_id": "fake_dog", "values": values or {"MIN_PRICE": 120},
                 "nickname": nickname, "created_utc": "2026-10-02T00:00:00Z"}]
        with mock.patch("src.hounds.learning.pause.config_path", return_value=self.root / "none.json"):
            return I.record_fan_lane(rows, scope=self.scope, card_paths=self.paths,
                                     now=C.parse("2026-10-02T00:00:00Z"), tunable_cfg=self.cfg,
                                     registry=F.REGISTRY, say=lambda *_a: None)

    def grade(self, stores, now):
        return G.grade_all(self.paths, now=now, registry=F.REGISTRY, tun_cfg=self.cfg,
                           loader=lambda since, until: stores, say=lambda *_a: None)

    def play(self, stores, days):
        for day in days:
            self.grade(stores, F.lock_of(day) + timedelta(minutes=5))

    def test_a_fan_tip_that_skips_every_loser_turns_helped_and_the_feed_posts_it_once(self):
        stores = F.stores_for([(d, False) for d in self.days])      # the home club loses every game
        self.assertEqual(self.record()["recorded"], 1)
        self.play(stores, self.days)
        card = C.load(self.paths)
        key = C.FAN_KEY_BASE + 1
        self.assertIn(key, card.hindsight)                           # hindsight graded, under the fan key
        done = card.forward[key]
        self.assertEqual((done["label"], done["n_paired"], done["units_diff"]), (G.LABEL_HELPED, 26, 26.0))
        self.assertEqual(done["suggested"]["bets"], 0)
        self.assertEqual(card.suggestions, {})                       # the coach's table never saw it
        self.assertEqual(done["issue"], key)
        # shadow ids of the fan's two hounds are the coach machinery's own
        self.assertEqual(G.shadow_id(key, "suggested"), f"coach-{key}-suggested")

        report = R.build_from_card(card)
        fans = report["fans"]
        self.assertEqual(fans["summary"]["helped"], 1)
        self.assertEqual(report["summary"]["helped"], 0)
        self.assertEqual(fans["items"][0]["forward"]["label"], "HELPED")
        first = card.first_helped[key]
        self.assertEqual(len(fans["helped_events"]), 1)

        events = K.fan_events(report, base_url="https://linehound.app")
        self.assertEqual(len(events), 1)
        ev = events[0]
        units, n = first["units_diff"], first["n_paired"]
        self.assertEqual(ev["title"], f"\U0001F436 Fan tip paid off: Ann's tweak to Fake Dog is beating the dog "
                                      f"(+{units:.1f}u = +${units * 10:,.0f} paper, {n} bets)")
        self.assertEqual(ev["guid"], "kennel:fan_tip:tip_00000000a1")
        self.assertEqual(ev["pub"].isoformat().replace("+00:00", "Z"), first["utc"])
        self.assertEqual(ev["kind"], "fan_tip")
        self.assertIn("learning.html", ev["link"])
        self.assertNotRegex(ev["title"] + ev["why"], r"(?i)\block\b|guarantee|can't lose|sure thing|profit|lifetime")

        # a later wobble back to NO DIFFERENCE neither removes nor rewrites the item
        C.append(self.paths, C.K_FORWARD, now=C.parse("2026-12-01T00:00:00Z"), issue=key, hound="fake_dog",
                 label="NO DIFFERENCE", n_paired=40, n_dates=9, units_diff=0.0)
        again = K.fan_events(R.build_from_card(C.load(self.paths)), base_url="https://linehound.app")
        self.assertEqual([(e["guid"], e["title"], e["pub"]) for e in again],
                         [(ev["guid"], ev["title"], ev["pub"])])

    def test_a_tip_with_no_nickname_is_posted_as_a_fan_and_an_unhelpful_one_is_not_posted(self):
        stores = F.stores_for([(d, False) for d in self.days])
        self.record(nickname=None)
        self.play(stores, self.days)
        report = R.build_from_card(C.load(self.paths))
        ev = K.fan_events(report)[0]
        self.assertTrue(ev["title"].startswith("\U0001F436 Fan tip paid off: a fan's tweak to Fake Dog"))
        hurt = F.stores_for([(d, True) for d in self.days])
        for p in self.root.iterdir():
            if p.is_dir():
                continue
            p.unlink()
        self.paths.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.record()
        self.play(hurt, self.days)
        card = C.load(self.paths)
        self.assertEqual(card.forward[C.FAN_KEY_BASE + 1]["label"], G.LABEL_HURT)
        self.assertEqual(K.fan_events(R.build_from_card(card)), [])

    def test_the_kennel_feed_carries_the_fan_item_through_the_seam_and_in_rss(self):
        stores = F.stores_for([(d, False) for d in self.days])
        self.record()
        self.play(stores, self.days)
        report = R.build_from_card(C.load(self.paths))
        events = K.collect(SimpleNamespace(hounds={}), states={}, user_rows=[], coach=report)
        self.assertEqual([e["kind"] for e in events], ["fan_tip"])
        xml = K.render_feed(events, base_url="https://linehound.app")
        self.assertIn("kennel:fan_tip:tip_00000000a1", xml)
        self.assertIn("Fan tip paid off: Ann", xml)
        self.assertIn("Paper bets only, not advice. 21+.", xml)

    def test_a_fan_tip_followed_forward_is_capped_to_the_newest_so_the_slot_budget_holds(self):
        card = C.Card()
        for i in range(1, G.FAN_FOLLOWED_MAX + 6):
            card.fans[C.FAN_KEY_BASE + i] = {"issue": C.FAN_KEY_BASE + i, "hound": "fake_dog",
                                             "recorded_utc": f"2026-10-01T00:{i // 60:02d}:{i % 60:02d}Z"}
        card.suggestions[3] = {"issue": 3, "hound": "fake_dog", "recorded_utc": "2026-10-01T00:00:00Z"}
        follow = G.active_for_forward(card, C.parse("2026-10-05T00:00:00Z"))
        keys = [r["issue"] for r in follow]
        self.assertIn(3, keys)                                      # the coach's own are never trimmed
        self.assertEqual(len(keys), G.FAN_FOLLOWED_MAX + 1)
        self.assertNotIn(C.FAN_KEY_BASE + 1, keys)
        self.assertIn(C.FAN_KEY_BASE + G.FAN_FOLLOWED_MAX + 5, keys)


class TheCommandLine(FanCase):
    def run_main(self, argv, site, **kw):
        out = io.StringIO()
        cfg = self.w.root / "coach_on.json"
        cfg.write_text('{"enabled": true}', encoding="utf-8")
        full = ["--root", str(self.w.root / "evidence"), "--champion-ledger", str(self.w.ledger),
                "--coach-config", str(cfg), "--now", "2026-11-20T12:00:00Z", "--base-url", BASE, *argv]
        with mock.patch("src.hounds.learning.pause.config_path", return_value=self.w.root / "none.json"), \
                mock.patch("src.hounds.pack.BY_ID", REGISTRY), \
                mock.patch("src.hounds.learning.tunables.load", return_value=self.w.cfg), redirect_stdout(out):
            code = I.main(full, urlopen=site, **kw)
        return code, out.getvalue()

    def test_the_sources_parse_and_gh_runs_alone(self):
        self.assertEqual(I.parse_sources("api,tips"), ("api", "tips"))
        self.assertEqual(I.parse_sources("tips"), ("tips",))
        self.assertEqual(I.parse_sources("tips,tips"), ("tips",))
        import argparse
        for bad in ("", "gh,tips", "ftp", "api,"):
            if bad == "api,":
                self.assertEqual(I.parse_sources(bad), ("api",))
                continue
            with self.assertRaises(argparse.ArgumentTypeError):
                I.parse_sources(bad)
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                I.build_parser().parse_args(["--source", "gh,tips"])

    def test_tips_alone_records_the_fans_tips_and_asks_the_site_not_github(self):
        site = FakeSite(tips=[tip(1), tip(2, values={"GAP": 0.035})])
        code, out = self.run_main(["--source", "tips"], site)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.card().fans), 2)
        self.assertEqual(site.tip_urls(), [f"{BASE}/hounds/tips/export"])
        self.assertEqual([r for r in site.requests if "api.github.com" in r.full_url], [])
        self.assertIn("2 fan tip(s) read", out)
        self.assertIn("recorded 2", out)
        # the next run resumes from the newest tip it has
        site2 = FakeSite(tips=[])
        self.run_main(["--source", "tips"], site2)
        self.assertIn("?since=2026-11-20T07%3A59%3A00Z", site2.tip_urls()[0])

    def test_api_and_tips_together_record_both_lanes_in_one_call(self):
        from tests.test_coach_card_intake import api_issue, body_of, good
        site = FakeSite(tips=[tip(1)], issues=[api_issue(11, body_of(good("alpha_pup")))])
        code, out = self.run_main(["--source", "api,tips"], site)
        self.assertEqual(code, 0, out)
        card = self.card()
        self.assertIn(11, card.suggestions)
        self.assertEqual(len(card.fans), 1)
        self.assertEqual(card.suggestions[11]["mode"], "challenger")            # the coach's own path is unchanged
        self.assertEqual(list(card.fans.values())[0]["mode"], "fan")
        self.assertEqual(len(L.read_state(self.w.scope).live()), 1)            # one challenger: the coach's, not the fan's

    def test_a_site_without_the_export_yet_does_not_cost_the_coach_its_run(self):
        from tests.test_coach_card_intake import api_issue, body_of, good
        site = FakeSite(issues=[api_issue(12, body_of(good("alpha_pup")))],
                        tips_error=urllib.error.HTTPError("u", 404, "nf", {}, None))
        code, out = self.run_main(["--source", "api,tips"], site)
        self.assertEqual(code, 1)                                               # reported, but the slot ignores it
        self.assertIn("fan tips: the tip export answered 404", out)
        self.assertIn(12, self.card().suggestions)

    def test_an_unreachable_github_does_not_cost_the_fans_their_run(self):
        site = FakeSite(tips=[tip(1)], issues_error=urllib.error.URLError("down"))
        code, out = self.run_main(["--source", "api,tips"], site)
        self.assertEqual(code, 1)
        self.assertIn("could not reach GitHub", out)
        self.assertEqual(len(self.card().fans), 1)

    def test_when_nothing_can_be_read_the_ledger_is_not_even_created(self):
        site = FakeSite(tips_error=urllib.error.URLError("down"))
        code, out = self.run_main(["--source", "tips"], site)
        self.assertEqual(code, 1)
        self.assertIn("fan tips: could not reach the tip export", out)
        self.assertFalse(self.paths.ledger.exists())

    def test_a_dry_run_reads_and_reports_but_writes_nothing(self):
        site = FakeSite(tips=[tip(1), tip(2, values={"GAP": 0.99})])
        code, out = self.run_main(["--source", "tips", "--dry-run", "--grade"], site)
        self.assertEqual(code, 0, out)
        self.assertFalse(self.paths.ledger.exists())
        self.assertIn("[dry run]", out)
        self.assertIn("recorded 1", out)
        self.assertIn("invalid 1", out)
        self.assertIn("grading skipped in a dry run (0 suggestion(s) and 1 fan tip(s) would be graded)", out)

    def test_a_hostile_export_cannot_inject_anything_into_the_log_line(self):
        site = FakeSite(tips=[tip(1, values={"GAP": "0.03\n## ::set-output name=x::y @everyone"})])
        code, out = self.run_main(["--source", "tips"], site)
        self.assertEqual(code, 0)
        self.assertEqual(self.card().fans, {})
        self.assertNotIn("@", out)

    def test_the_capture_slot_asks_for_the_fans_in_the_same_capped_call(self):
        text = (ROOT / "scripts" / "capture_slot.sh").read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if "src.hounds.coach_intake" in ln and not ln.lstrip().startswith("#")]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("--source api,tips --grade", lines[0])
        self.assertIn("timeout 120", lines[0])
        self.assertTrue(lines[0].rstrip().endswith("|| true"))


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheDogPagesTipList(unittest.TestCase):
    def test_a_graded_tip_carries_its_grade_in_the_tip_list_and_an_ungraded_one_reads_as_before(self):
        import os
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.hounds_tips import router as tips_router
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"APP_DB_PATH": str(root / "app.db")}):
                scopes = {"house": L.Scope.house(root / "h"), "user": L.Scope.user(root / "u")}
                with mock.patch("src.hounds.learning.views.scopes", lambda: scopes):
                    app = FastAPI()
                    app.include_router(tips_router)
                    client = TestClient(app)
                    sent = [client.post("/hounds/steamy_setter/tips", json={"values": {"MOVE": v}},
                                        headers={"Fly-Client-IP": "1.1.1.1"}).json()["tip"] for v in (0.04, 0.035)]
                    paths = C.Paths.default(root / "evidence")
                    paths.ledger.parent.mkdir(parents=True)
                    C.append(paths, C.K_FAN_TIP, now=NOW, issue=C.FAN_KEY_BASE + 1, tip_id=sent[0]["id"],
                             hound="steamy_setter", hound_name="Steamy Setter", suggested_values={"MOVE": 0.04},
                             champion_values={"MOVE": 0.03}, changes=[], mode="fan", challenger_id=None,
                             nickname=None, tip_created_utc="2026-11-20T08:00:00Z",
                             recorded_utc="2026-11-20T12:00:00Z")
                    C.append(paths, C.K_FORWARD, now=NOW, issue=C.FAN_KEY_BASE + 1, hound="steamy_setter",
                             label="HELPED", n_paired=25, n_dates=6, units_diff=3.2)
                    R._GRADES_CACHE.clear()
                    with mock.patch.object(C.Paths, "default", staticmethod(lambda root=None: paths)):
                        tips = {t["id"]: t for t in client.get("/hounds/steamy_setter/tips").json()["tips"]}
                    R._GRADES_CACHE.clear()
        self.assertEqual(tips[sent[0]["id"]]["grade"], {"label": "HELPED", "units_diff": 3.2, "n_paired": 25,
                                                        "hindsight_units_diff": None})
        self.assertNotIn("grade", tips[sent[1]["id"]])

    def test_an_unreadable_report_card_never_breaks_the_tip_list(self):
        from api import hounds_tips
        with mock.patch("src.hounds.coach_report.fan_grades_now", side_effect=OSError("disk")):
            self.assertEqual(hounds_tips._grades_by_tip(), {})


def jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePagesUnderNode(unittest.TestCase):
    """The Training camp's "Fans vs the coach" block and the dog page's tip grades, by the real page scripts."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.paths = F.paths_in(self.root / "coach")
        self.paths.ledger.parent.mkdir(parents=True, exist_ok=True)

    def payload(self, with_fans=True):
        rows = [dict(tip(1), nickname="Ann", values={"MIN_PRICE": 120}, hound_id="fake_dog"),
                dict(tip(2), nickname=None, values={"MIN_PRICE": 140}, hound_id="fake_dog"),
                dict(tip(3), nickname="Cy", values={"MIN_PRICE": 160}, hound_id="fake_dog")]
        with mock.patch("src.hounds.learning.pause.config_path", return_value=self.root / "none.json"):
            I.record_fan_lane(rows, scope=L.Scope.house(self.root / "ev"), card_paths=self.paths, now=NOW,
                              tunable_cfg=F.tunable_cfg(), registry=F.REGISTRY, say=lambda *_a: None)
        k = C.FAN_KEY_BASE
        C.append(self.paths, C.K_HINDSIGHT, now=NOW, issue=k + 1, hound="fake_dog", hindsight=True, status="ok",
                 units_diff=1.5, window_first="2026-10-01", window_last="2026-10-31", window_days=30)
        C.append(self.paths, C.K_FORWARD, now=NOW, issue=k + 1, hound="fake_dog", label="HELPED", n_paired=25,
                 n_dates=6, units_diff=3.2)
        C.append(self.paths, C.K_FORWARD, now=NOW, issue=k + 2, hound="fake_dog", label="HURT", n_paired=22,
                 n_dates=6, units_diff=-2.0)
        row = F.suggestion_row(issue=1, recorded="2026-11-10T12:00:00Z")
        C.append(self.paths, C.K_SUGGESTION, now=C.parse(row["recorded_utc"]), **row)
        C.append(self.paths, C.K_FORWARD, now=NOW, issue=1, hound="fake_dog", label="HELPED", n_paired=30,
                 n_dates=6, units_diff=4.0)
        R._CACHE.clear()
        report = jsonable(R.build(self.paths))
        if not with_fans:
            report.pop("fans")
        return report

    def learning(self, report, queries):
        from tests.test_hounds_learning_web import learning_payload
        routes = {"/hounds/learning": [200, learning_payload(self.root)], "/hounds/coach/report": [200, report]}
        return run_page("learning", routes=routes, queries=queries)["final"]

    @staticmethod
    def q(name, sel, mode="text", **kw):
        return dict(name=name, sel=sel, mode=mode, **kw)

    def test_the_block_is_titled_in_the_camps_voice_and_sits_under_the_coachs_list(self):
        q = self.q
        f = self.learning(self.payload(), [
            q("title", "[data-hook='fans-title']"), q("intro", "[data-hook='fans-intro']"),
            q("versus", "[data-hook='fans-versus']"), q("hind", "[data-hook='fans-versus-hindsight']"),
            q("summary", "[data-hook='fans-summary']"), q("n", "[data-hook='fans-list'] li", "count"),
            q("lines", "[data-hook='fan-line']", "texts"), q("badges", "[data-hook='fan-badge']", "texts"),
            q("labels", "[data-hook='fans-list'] li", "attrs", attr="data-label"),
            q("coach_n", "[data-hook='coach-list'] li", "count"),
            q("coach_facts", "[data-hook='coach-facts'] dd", "texts"),
            q("block", "[data-hook='fans-block']", "count")])
        self.assertEqual(f["title"], "Fans vs the coach")
        self.assertIn("never counts in the coach's own numbers", f["intro"])
        self.assertEqual(f["versus"], "Coach vs the fans: the coach helped 1 of 1 graded tips, the fans helped 1 of 2 "
                                      "(live grades only).")
        self.assertIn("Hindsight, a rehearsal and not evidence", f["hind"])
        self.assertIn("3 fan tips graded so far.", f["summary"])
        self.assertIn("2 with a live verdict: 1 helped, 1 hurt, 0 no difference.", f["summary"])
        self.assertEqual(f["n"], 3)
        self.assertEqual(f["coach_n"], 1)                                       # the coach's list is the coach's only
        self.assertEqual(f["coach_facts"][0], "1")                              # tips made: the coach's one, not four
        self.assertEqual(sorted(f["badges"]), sorted(["HELPED", "HURT", "IN PROGRESS"]))  # owner ruling 2026-10-20, complete-product positioning
        self.assertTrue(any(ln.startswith("Ann told Fake Dog to change") and "Live: helped (+3.2u over 25 bets)" in ln
                            for ln in f["lines"]), f["lines"])
        self.assertTrue(any(ln.startswith("A fan told Fake Dog") for ln in f["lines"]))
        self.assertEqual(f["block"], 1)

    def test_with_no_fan_tips_it_invites_the_first_one_and_with_an_older_server_it_is_absent(self):
        empty = jsonable(R.build_from_card(C.Card()))
        f = self.learning(empty, [self.q("empty", "[data-hook='fans-empty']"),
                                  self.q("versus", "[data-hook='fans-versus']")])
        self.assertIn("No fan tips have been graded yet", f["empty"])
        self.assertIn("no scoreboard", f["versus"])
        f = self.learning(self.payload(with_fans=False), [self.q("block", "[data-hook='fans-block']", "count"),
                                                          self.q("coach", "[data-hook='coach-list'] li", "count")])
        self.assertEqual((f["block"], f["coach"]), (0, 1))

    def test_the_dog_page_tip_list_shows_each_graded_tips_grade_and_leaves_the_rest_alone(self):
        from tests import hounds_web_fixtures as WF
        from tests.test_hounds_dog_page import dials_fixture, rulebook
        tips = {"hound_id": "closer", "count": 3, "note": "n", "tips": [
            {"id": "tip_a", "values": {"MOVE": 0.04}, "nickname": "Ann", "created_utc": "2026-10-18T10:00:00Z",
             "grade": {"label": "HELPED", "units_diff": 3.2, "n_paired": 25, "hindsight_units_diff": 1.0}},
            {"id": "tip_b", "values": {"MOVE": 0.025}, "nickname": None, "created_utc": "2026-10-18T09:00:00Z",
             "grade": {"label": "TOO EARLY", "units_diff": 0.5, "n_paired": 1, "hindsight_units_diff": None}},
            {"id": "tip_c", "values": {"MOVE": 0.05}, "nickname": "Cy", "created_utc": "2026-10-18T08:00:00Z",
             "grade": {"label": "HURT", "units_diff": -1.25, "n_paired": 22, "hindsight_units_diff": None}},
            {"id": "tip_d", "values": {"MOVE": 0.02}, "nickname": "Di", "created_utc": "2026-10-18T07:00:00Z"}]}
        r = {k: list(v) for k, v in WF.routes(True, 45).items()}
        r["/hounds/series"] = [200, WF.series(["closer"], True)]
        r["/hounds/closer"] = [200, WF.detail("closer", True, 45)]
        r["/hounds/closer/rulebook"] = [200, rulebook(dials_fixture(1))]
        r["/hounds/closer/tips"] = [200, tips]
        out = run_page("hound", routes=r, search="?id=closer", tz="UTC", stored={}, queries=[
            self.q("list", "[data-hook='tips-list'] li", "texts"),
            self.q("count", "[data-hook='tips-count']")])["final"]
        self.assertEqual(out["list"], ["Ann: Steam needed 4 points. Live: HELPED (+3.2u over 25 bets)",
                                       "A fan: Steam needed 2.5 points. Live: IN PROGRESS (1 bet)",  # owner ruling 2026-10-20, complete-product positioning
                                       "Cy: Steam needed 5 points. Live: HURT (-1.3u over 22 bets)",
                                       "Di: Steam needed 2 points"])
        self.assertEqual(out["count"], "Fan tips: 3. Grades coming from the coach report card.")


if __name__ == "__main__":
    unittest.main()
