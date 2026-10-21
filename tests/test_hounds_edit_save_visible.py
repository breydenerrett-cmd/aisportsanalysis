"""Editing a dog and tapping "Review the changes" must never end in nothing: the page, run for real under node.

THE REPORT (a real member, Jacob, iPhone, 2026-10-20): he opened his dog "Jsmooth27", changed the stake to 3 units, tapped
"Review the changes", and "nothing happens". The dog is a classic (version 1) dog the builder opens as an equivalent rule
set; his other dog "Jsmooth" is a version 2 dog with repeated conditions (the market moved toward the pick twice, a night
game twice, numerology twice, two moon phases).

WHAT WAS WALKED. Both dogs, from the stored row through the real routes' own functions (GET /hounds/mine, the editor, POST
/hounds/{id}/diff, POST /hounds/{id}/version) and the real validator: the server accepts both edits, the page posts a valid
spec, and a diff comes back. So "the server refused a good edit" is NOT what these tests pin. What they pin is what the page
did when ANYTHING went wrong, because that is the only way a tap can "do nothing":

  1. A refusal (the validator's 422) was written into the rules panel in step 2, far above the Save button, and a lapsed
     sign-in went to a banner at the very top of the page. On a phone neither is on screen next to the button, so the tap
     read as dead. Every outcome now lands in a box above the button, scrolled into view.
  2. A tap while busy, or before a rule existed, returned without a word.
  3. A refusal with no field list (a request-shape error, an empty list, a bare string) rendered as nothing at all.
  4. The editor sent back every key the stored spec carried. The validator REFUSES a key it does not know, so a stored dog
     carrying one the editor never shows was refused on every save and the reason was out of sight. The page now sends only
     the fields the server accepts.
  5. The preview pill (position: fixed at the foot of the phone) took taps meant for the button beneath it.

Skipped without node; the store half needs no FastAPI (Linux CI has none).
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from src.appstate import users as users_store
from src.hounds import stats, user_engine, user_spec, user_store
from src.hounds.english import render
from tests.hounds_web_runner import HAS_NODE, WEB
from tests.test_hounds_builder_web import SIGNED, base_routes, build, posts_to, q

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # CI's no-FastAPI run
    HAS_FASTAPI = False

JS = (WEB / "js" / "hounds-build.js").read_text(encoding="utf-8")
HTML = (WEB / "build-a-hound.html").read_text(encoding="utf-8")
CSS = (WEB / "css" / "builder.css").read_text(encoding="utf-8")

# Jsmooth27 as the store holds it: a classic dog made while the dog menu had four sports ("any sport" is written out as the list).
V1 = {"name": "Jsmooth27", "tagline": "", "sports": ["MLB", "NFL", "NCAAF", "NBA"], "markets": ["moneyline", "spread", "total"],
      "side_rule": "market_moved_toward", "price_min": -160, "price_max": 250, "min_books": 1, "lock_minutes": 60,
      "max_bets_per_day": 3}

# Jsmooth: version 2, the same condition more than once, and two moon phases.
V2 = {"version": 2, "name": "Jsmooth", "tagline": "", "color": "ember", "badge": "bone", "lock_minutes": 120,
      "max_bets_per_day": 3, "stake_units": 1, "rank_by": "earliest_lock",
      "rules": [{"label": "", "sports": ["MLB", "NFL", "NCAAF", "NBA"], "markets": ["moneyline", "spread"], "side": "either",
                 "price_min": -150, "price_max": 250, "min_books": 1,
                 "when": {"op": "all", "items": [
                     {"id": "steam", "direction": "toward"}, {"id": "steam", "direction": "toward"},
                     {"id": "time_of_day", "value": "night"}, {"id": "time_of_day", "value": "night"},
                     {"id": "numerology", "value": "closer"}, {"id": "numerology", "value": "closer"},
                     {"id": "moon_phase", "value": "other"}, {"id": "moon_phase", "value": "full"}]}}]}


def owner_row(hid, name, draft):
    """What GET /hounds/mine lists for the owner: the spec as a version 2 draft, plus its rules in sentences."""
    return json.loads(json.dumps({
        "id": hid, "name": name, "tagline": "", "status": "running", "version_no": 1, "color": "ember", "badge": "bone",
        "record": {}, "spec": draft, "rule_sentences": render.rule_sentences(draft) + render.global_sentences(draft)}))


def jsmooth27_draft():
    return user_spec.upgrade_v1(user_spec.validate_spec(dict(V1, version=1)))


def jsmooth_draft():
    return user_spec.validate_spec(deepcopy(V2))


def mine_routes(rows, **over):
    routes = {"/hounds/mine": [200, {"hounds": rows, "limit_running": 3}]}
    routes.update(over)
    return base_routes(**routes)


DIFF_OK = {"changes": [{"what": "Stake", "before": "1 paper unit", "after": "3 paper units"}], "paper_only": True}
EDIT = dict(do="click", sel="[data-hook='edit-dog']", index=0, wait=200)
STAKE3 = dict(do="set", sel="[data-hook='g-stake']", value="3", wait=40)
REVIEW = dict(do="click", sel="[data-hook='build-submit']", wait=300, label="review")
SEEN = [q("diff_hidden", "[data-hook='diff']", "hidden"), q("diff", "[data-hook='diff-list']"),
        q("problems_hidden", "[data-hook='build-save-problems']", "hidden"), q("problems", "[data-hook='build-save-problems']"),
        q("err_hidden", "[data-hook='build-server-error']", "hidden"), q("err", "[data-hook='build-server-error']"),
        q("btn", "[data-hook='build-submit']")]
NEAR_THE_BUTTON = ("diff", "build-save-problems", "build-server-error", "build-message")


def visible_near_button(cap):
    """The text of whatever the tap left next to the button: the diff, the reasons, or the failure line."""
    parts = []
    if not cap["diff_hidden"]:
        parts.append(cap["diff"])
    if not cap["problems_hidden"]:
        parts.append(cap["problems"])
    if not cap["err_hidden"]:
        parts.append(cap["err"])
    return " ".join(parts).strip()


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheRealEditPathForBothDogs(unittest.TestCase):
    """Load the dog into the editor, change the stake to 3, review, save: the spec the page sends is one the validator takes."""

    def walk(self, row, hid):
        routes = mine_routes([row], **{f"POST /hounds/{hid}/diff": [200, DIFF_OK],
                                       f"POST /hounds/{hid}/version": [200, {"hound": {"id": hid + "b", "name": row["name"], "version_no": 2}}]})
        out = build(routes, **SIGNED, actions=[
            dict(EDIT), dict(STAKE3), dict(REVIEW, capture=SEEN),
            dict(do="click", sel="[data-hook='build-submit']", wait=300, label="save", capture=[q("msg", "[data-hook='build-message']")])])
        return out

    def check(self, out, hid, name):
        review = out["captures"]["review"]
        self.assertFalse(review["diff_hidden"], review)
        self.assertEqual(review["btn"], "Save as version 2")
        for suffix in ("/diff", "/version"):
            sent = posts_to(out, f"/hounds/{hid}{suffix}")
            self.assertEqual(len(sent), 1, suffix)
            spec = user_spec.validate_spec(sent[0]["body"]["spec"])          # the real validator takes exactly what was sent
            self.assertEqual((spec["name"], spec["stake_units"]), (name, 3.0))
        self.assertIn("Saved as version 2", out["captures"]["save"]["msg"])

    def test_jsmooth27_a_classic_dog_opens_as_rules_and_a_stake_of_three_reviews_and_saves(self):
        out = self.walk(owner_row("u-fcc8e8c168", "Jsmooth27", jsmooth27_draft()), "u-fcc8e8c168")
        self.check(out, "u-fcc8e8c168", "Jsmooth27")
        sent = posts_to(out, "/hounds/u-fcc8e8c168/diff")[0]["body"]["spec"]
        self.assertEqual([r["markets"] for r in sent["rules"]], [["moneyline", "spread"], ["total"]])
        self.assertEqual(sent["rules"][0]["sports"], ["MLB", "NFL", "NCAAF", "NBA"])

    def test_jsmooth_repeated_conditions_are_sent_as_they_are_and_the_validator_takes_them(self):
        out = self.walk(owner_row("u-ecf8387bdb", "Jsmooth", jsmooth_draft()), "u-ecf8387bdb")
        self.check(out, "u-ecf8387bdb", "Jsmooth")
        items = posts_to(out, "/hounds/u-ecf8387bdb/diff")[0]["body"]["spec"]["rules"][0]["when"]["items"]
        self.assertEqual([i["id"] for i in items], ["steam", "steam", "time_of_day", "time_of_day",
                                                    "numerology", "numerology", "moon_phase", "moon_phase"])

    def test_the_diff_is_scrolled_into_view_so_a_tap_on_a_phone_visibly_does_something(self):
        out = self.walk(owner_row("u-fcc8e8c168", "Jsmooth27", jsmooth27_draft()), "u-fcc8e8c168")
        self.assertIn("diff", out["scrolls"])

    def test_a_field_the_editor_never_shows_is_not_sent_back_to_be_refused(self):
        # A stored spec can carry a key this validator has no place for (an older build wrote it). The validator refuses
        # an unknown key, so before the fix every save of that dog was refused, with the reason out of sight.
        draft = jsmooth_draft()
        draft["legacy_flag"] = True
        draft["rules"][0]["note"] = "from an older build"
        with self.assertRaises(user_spec.SpecError):                         # the premise: sent as it stands, it is refused
            user_spec.validate_spec(draft)
        out = self.walk(owner_row("u-ecf8387bdb", "Jsmooth", draft), "u-ecf8387bdb")
        sent = posts_to(out, "/hounds/u-ecf8387bdb/diff")[0]["body"]["spec"]
        self.assertNotIn("legacy_flag", sent)
        self.assertNotIn("note", sent["rules"][0])
        user_spec.validate_spec(sent)
        self.assertFalse(out["captures"]["review"]["diff_hidden"])

    def test_the_page_names_exactly_the_keys_the_validator_accepts(self):
        top = re.search(r"const SPEC_KEYS = \[(.*?)\];", JS).group(1)
        rule = re.search(r"const RULE_KEYS = \[(.*?)\];", JS).group(1)
        names = lambda text: re.findall(r'"([a-z_]+)"', text)                # noqa: E731
        self.assertEqual(set(names(top)), set(user_spec.V2_TOP_KEYS) - set(user_spec.V2_DERIVED_KEYS))
        self.assertEqual(set(names(rule)), set(user_spec.V2_RULE_KEYS))


@unittest.skipUnless(HAS_NODE, "node is not installed")
class EveryTapEndsInSomethingYouCanSee(unittest.TestCase):
    """The rule: after a tap on the Save button there is text next to the button, scrolled into view, whatever the server did."""

    def run_review(self, status=None, payload=None, down=False):
        row = owner_row("u-1", "Jsmooth27", jsmooth27_draft())
        hit = {} if down else {"POST /hounds/u-1/diff": [status, payload]}
        extra = {"down": ["/hounds/u-1/diff"]} if down else {}
        return build(mine_routes([row], **hit), **SIGNED, **extra,
                     actions=[dict(EDIT), dict(STAKE3), dict(REVIEW, capture=SEEN)])

    def assert_seen(self, out, *needles):
        cap = out["captures"]["review"]
        text = visible_near_button(cap)
        self.assertTrue(text, f"the tap left nothing next to the button: {cap}")
        for needle in needles:
            self.assertIn(needle, text)
        self.assertTrue(set(out["scrolls"]) & set(NEAR_THE_BUTTON), f"nothing was scrolled into view: {out['scrolls']}")

    def test_a_refusal_with_reasons_is_listed_above_the_button(self):
        out = self.run_review(422, {"detail": {"error": "spec_invalid", "fields": {"stake_units": "must be one of 0.5, 1 paper units",
                                                                                 "rules[1].price_max": "must be longer"}}})
        self.assert_seen(out, "Not saved", "stake units: must be one of", "Rule 2, price max: must be longer")

    def test_a_refusal_with_an_empty_reason_list_still_says_so(self):
        out = self.run_review(422, {"detail": {"error": "spec_invalid", "fields": {}}})
        self.assert_seen(out, "no reason")

    def test_a_request_shape_refusal_is_read_out(self):
        out = self.run_review(422, {"detail": [{"loc": ["body", "spec"], "msg": "Field required", "type": "missing"}]})
        self.assert_seen(out, "Field required")

    def test_a_refusal_that_is_only_words_is_read_out(self):
        out = self.run_review(422, {"detail": "that dog cannot be changed"})
        self.assert_seen(out, "that dog cannot be changed")

    def test_a_lapsed_sign_in_is_said_next_to_the_button_with_a_way_back(self):
        for status in (401, 403):
            out = self.run_review(status, {"detail": "no"})
            self.assert_seen(out, "sign-in", "Sign in")

    def test_the_dog_limit_is_said_in_the_servers_words(self):
        out = self.run_review(409, {"detail": {"error": "limit", "message": "an account can run at most 3 hounds; retire one first"}})
        self.assert_seen(out, "at most 3 hounds")

    def test_too_many_saves_in_an_hour_is_said_in_words(self):
        out = self.run_review(429, {"detail": "slow down"})
        self.assert_seen(out, "too many saves", "Nothing was saved")

    def test_a_server_fault_says_nothing_was_saved(self):
        out = self.run_review(500, {})
        self.assert_seen(out, "500", "nothing was saved")

    def test_a_dead_connection_says_nothing_was_saved(self):
        out = self.run_review(down=True)
        self.assert_seen(out, "Could not reach", "nothing was saved")

    def test_an_answer_the_page_cannot_use_says_something_went_wrong_and_nothing_was_saved(self):
        out = self.run_review(200, None)
        cap = out["captures"]["review"]
        self.assertTrue(visible_near_button(cap), cap)
        self.assertEqual(cap["btn"], "Review the changes")

    def test_a_diff_with_no_changes_says_so(self):
        out = self.run_review(200, {"changes": []})
        self.assert_seen(out, "Nothing has changed")

    def test_the_reasons_clear_when_the_draft_changes(self):
        row = owner_row("u-1", "Jsmooth27", jsmooth27_draft())
        routes = mine_routes([row], **{"POST /hounds/u-1/diff": [422, {"detail": {"fields": {"name": "is already taken"}}}]})
        out = build(routes, **SIGNED, actions=[dict(EDIT), dict(STAKE3), dict(REVIEW), dict(do="set", sel="[data-hook='g-bets']", value="2", wait=60,
                                                                                         label="after", capture=SEEN)])
        self.assertTrue(out["captures"]["after"]["problems_hidden"])

    def test_a_tap_with_no_rule_yet_says_so_instead_of_returning_quietly(self):
        out = build(base_routes(), **SIGNED, actions=[dict(do="click", sel="[data-hook='build-submit']", wait=100, label="tap", capture=SEEN)])
        text = visible_near_button(out["captures"]["tap"])
        self.assertIn("no rule yet", text)
        self.assertEqual(posts_to(out, "/hounds"), [])

    def test_signed_out_the_prompt_is_next_to_the_button_as_well_as_at_the_top(self):
        out = build(actions=[dict(do="click", sel="[data-hook='blank-rule']", wait=60),
                             dict(do="set", sel="[data-hook='f-name']", value="Pup Test", wait=30),
                             dict(do="click", sel="[data-hook='build-submit']", wait=100, label="tap", capture=SEEN)])
        self.assertIn("Sign in to keep your hound", visible_near_button(out["captures"]["tap"]))

    def test_a_missing_name_is_listed_above_the_button(self):
        out = build(**SIGNED, actions=[dict(do="click", sel="[data-hook='blank-rule']", wait=60),
                                       dict(do="click", sel="[data-hook='build-submit']", wait=100, label="tap", capture=SEEN)])
        self.assertIn("give your hound a name", visible_near_button(out["captures"]["tap"]).lower())

    def test_the_page_has_a_box_for_it_above_the_save_button(self):
        self.assertLess(HTML.index('data-hook="build-save-problems"'), HTML.index('data-hook="build-submit"'))
        self.assertIn('data-hook="build-save-problems" role="alert"', HTML)


class ThePillNeverEatsATap(unittest.TestCase):
    def test_the_fixed_preview_pill_lets_taps_through_to_the_button_under_it(self):
        block = re.search(r"\.bd-pill \{(.*?)\n\}", CSS, re.S).group(1)
        self.assertIn("position: fixed", block)
        self.assertIn("pointer-events: none", block)


class TheStoreHalfNeedsNoFastapi(unittest.TestCase):
    """The same two dogs from the store through the editor's draft, the validator, the diff and the new version: the server takes both."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.db = tmp / "app.db"
        ledger = str(tmp / "hounds_user_v1.jsonl")
        for p in (mock.patch.object(users_store, "db_path", lambda: self.db),
                  mock.patch.object(user_engine, "LEDGER", ledger),
                  mock.patch.object(user_engine, "ledger_path", lambda path=None: path or ledger),
                  mock.patch.object(stats, "refresh_async", lambda *a, **k: False)):
            p.start()
            self.addCleanup(p.stop)
        self.owner = users_store.create_user("jacob@example.com", status="active", db=self.db)

    def edit_to_three_units(self, hound):
        stored = user_store.get_hound(hound["id"])
        draft = deepcopy(stored["spec"] if user_spec.is_v2(stored["spec"]) else user_spec.upgrade_v1(stored["spec"]))
        draft["stake_units"] = 3
        for key in ("sports", "markets", "side_rule"):                         # what the page leaves out
            draft.pop(key, None)
        for rule in draft["rules"]:
            for key in ("line_min", "line_max"):
                if rule.get(key) is None:
                    rule.pop(key, None)
        taken = [n for n in user_store.taken_names() if user_spec._fold(n) != user_spec._fold(stored["name"])]
        new = user_spec.validate_spec(draft, taken_names=taken)
        self.assertEqual(render.diff_specs(stored["spec"], new), [{"what": "Stake", "before": "1 paper unit", "after": "3 paper units"}])
        saved = user_store.create_version(hound["id"], draft, actor=f"owner:{self.owner.id}", reason="edited in the builder")
        self.assertEqual((saved["version_no"], saved["name"], saved["spec"]["stake_units"]), (2, stored["name"], 3.0))

    def test_both_dogs_edit_to_three_units_and_save_as_version_two(self):
        classic = user_store.create_hound(self.owner.id, dict(V1, version=1))
        self.assertEqual(classic["spec"]["version"], 1)
        custom = user_store.create_hound(self.owner.id, deepcopy(V2))
        self.edit_to_three_units(classic)
        self.edit_to_three_units(custom)

    @unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
    def test_the_routes_themselves_agree(self):
        from api import hounds_create as api
        classic = user_store.create_hound(self.owner.id, dict(V1, version=1))
        mine = {d["id"]: d for d in api.my_hounds(current_user=self.owner, _rl=None)["hounds"]}
        draft = deepcopy(mine[classic["id"]]["spec"])
        draft["stake_units"] = 3
        out = api.hound_diff(classic["id"], api.PreviewRequest(spec=draft), current_user=self.owner, _rl=None)
        self.assertEqual([c["what"] for c in out["changes"]], ["Stake"])
        new = api.hound_new_version(classic["id"], api.VersionRequest(spec=draft), current_user=self.owner, _rl=None)
        self.assertEqual(new["hound"]["version_no"], 2)


if __name__ == "__main__":
    unittest.main()
