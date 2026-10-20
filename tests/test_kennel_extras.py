"""A quiet kennel is not a blank one (round 2, 2026-10-19): a featured dog, the latest tickets from member dogs, a thinking dog when there are none.

The critic: "Kennels index + public kennel ~60% empty: mascot empty-state, a 'featured dog' card and a recent activity strip (latest
member-dog tickets); drop the filler breed legend." (web/js/kennel-extras.js.) "Featured" is a reading aid, not an endorsement: the card
says why it is featured, says "small sample" under 20 settled bets, and says nothing has settled when nothing has.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js, run_page

ROOT = Path(__file__).resolve().parent.parent


def q(name, sel, mode="text", **kw):
    return dict(name=name, sel=sel, mode=mode, **kw)


def dog(i, name, bets=0, wins=0, losses=0, bank=None, open_bets=0, **extra):
    d = {"id": i, "name": name, "look": None, "record": {"bets": bets, "wins": wins, "losses": losses, "pushes": 0}, "open_bets": open_bets}
    if bank is not None:
        d["bankroll"] = {"current": bank, "return_pct": round((bank - 1000) / 10, 2), "bets": bets, "start": 1000}
    d.update(extra)
    return d


def kennel(handle, dogs):
    return {"handle": handle, "display": handle.title(), "dog_count": len(dogs), "new_dogs": 0, "best": None, "href": f"kennel.html?u={handle}", "dogs": dogs}


def ticket(hid, name, selection="Rays to win", result=None):
    return {"hound_id": hid, "hound_name": name, "date": "2026-10-19", "game": "Guardians at Rays", "market": "moneyline", "selection": selection,
            "price": -110, "result": result, "recorded_utc": "2026-10-19T20:00:00Z", "start_utc": "2026-10-19T23:00:00Z", "status": "OPEN" if not result else "SETTLED"}


@unittest.skipUnless(HAS_NODE, "node not installed")
class WhichDogIsFeatured(unittest.TestCase):
    def pick(self, dogs):
        return run_js(f'''
const E = await import("./kennel-extras.js");
const r = E.featuredDog({json.dumps(dogs)});
console.log(JSON.stringify(r && {{ id: r.dog.id, why: r.why }}));''')

    def test_the_highest_paper_bankroll_among_dogs_with_a_settled_bet(self):
        got = self.pick([dog("a", "A", bets=4, wins=3, losses=1, bank=1040), dog("b", "B", bets=9, wins=5, losses=4, bank=1080), dog("c", "C", open_bets=5)])
        self.assertEqual(got, {"id": "b", "why": "Highest paper bankroll"})

    def test_with_nothing_settled_the_dog_with_the_most_open_tickets_and_the_reason_says_so(self):
        got = self.pick([dog("a", "A", open_bets=1), dog("b", "B", open_bets=3), dog("c", "C")])
        self.assertEqual(got, {"id": "b", "why": "Most open tickets"})

    def test_with_nothing_at_all_the_first_dog_and_the_reason_says_no_bets_settled(self):
        self.assertEqual(self.pick([dog("a", "A"), dog("b", "B")]), {"id": "a", "why": "No bets settled yet"})

    def test_a_retired_dog_is_never_featured_and_no_dogs_is_null(self):
        self.assertEqual(self.pick([dog("r", "R", bets=9, wins=9, bank=1500, retired=True), dog("a", "A")])["id"], "a")
        self.assertIsNone(self.pick([]))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheKennelsIndex(unittest.TestCase):
    KENNELS = [kennel("handler-1", [dog("u-1", "Rex", bets=7, wins=5, losses=2, bank=1060), dog("u-2", "Ace")]), kennel("handler-2", [dog("u-3", "Bo", open_bets=2)])]
    STREAM = {"items": [ticket("u-3", "Bo", "Over 7"), ticket("closer", "Closer", "House pick"), ticket("u-1", "Rex", "Rays to win", "won")]}

    def page(self, kennels=None, stream=True):
        routes = {"/hounds/kennels": [200, {"kennels": self.KENNELS if kennels is None else kennels, "count": 2}]}
        if stream:
            routes["/hounds/stream"] = [200, self.STREAM]
        return run_page("kennels_index", routes=routes, queries=[
            q("feat", "[data-hook='kennels-featured']", "count"), q("name", "[data-hook='featured-name']"), q("kicker", ".kn-feat__kicker"),
            q("note", "[data-hook='featured-note']"), q("acts", "[data-hook='activity-ticket']", "count"), q("who", ".kn-act-row__who", "texts"),
            q("breeds", "[data-hook='kennels-breeds']", "count"), q("cards", "[data-hook='kennel-card']", "count"), q("bigdog", ".kn-feat__dog svg", "attrs", attr="width")])

    def test_it_shows_the_featured_dog_with_its_reason_and_a_small_sample_warning(self):
        f = self.page()["final"]
        self.assertEqual((f["feat"], f["name"]), (1, "Rex"))
        self.assertEqual(f["kicker"], "Featured dog · Highest paper bankroll")
        self.assertEqual(f["note"], "7 settled bets: a small sample, not a verdict.")
        self.assertEqual(f["bigdog"], ["132"])

    def test_the_activity_strip_has_member_dog_tickets_only_and_not_the_house_dogs(self):
        f = self.page()["final"]
        self.assertEqual(f["acts"], 2)
        self.assertEqual(f["who"], ["Bo", "Rex"])

    def test_the_breed_legend_is_gone_and_the_kennel_cards_stay(self):
        f = self.page()["final"]
        self.assertEqual((f["breeds"], f["cards"]), (0, 2))
        src = (ROOT / "web" / "js" / "kennels-index.js").read_text(encoding="utf-8")
        self.assertNotIn("breedStrip", src)
        self.assertNotIn("kn-breeds", (ROOT / "web" / "css" / "studio.css").read_text(encoding="utf-8"))

    def test_a_stream_that_is_down_just_leaves_the_strip_out(self):
        f = self.page(stream=False)["final"]
        self.assertEqual((f["feat"], f["acts"], f["cards"]), (1, 0, 2))

    def test_no_kennels_is_a_thinking_dog_and_a_build_link_not_a_blank_page(self):
        out = run_page("kennels_index", routes={"/hounds/kennels": [200, {"kennels": [], "count": 0}]}, queries=[
            q("empty", "[data-hook='kennels-empty']"), q("quiet", "[data-hook='kennel-quiet'] svg.dk-badge", "attrs", attr="data-pose"), q("feat", "[data-hook='kennels-featured']", "count")])
        self.assertIn("No kennels yet", out["final"]["empty"])
        self.assertEqual(out["final"]["quiet"], ["thinking"])
        self.assertEqual(out["final"]["feat"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePublicKennel(unittest.TestCase):
    DOGS = [dog("u-1", "Rex", open_bets=1), dog("u-2", "Ace")]

    def page(self, stream_items):
        data = {"handle": "handler-1", "display": "Handler 1", "dog_count": 2, "best": None, "dogs": self.DOGS, "paper_only": True}
        routes = {"/hounds/kennels/handler-1": [200, data]}
        if stream_items is not None:
            routes["/hounds/stream"] = [200, {"items": stream_items}]
        return run_page("kennel", search="?u=handler-1", routes=routes, queries=[
            q("acts", "[data-hook='activity-ticket']", "count"), q("title", ".kn-activity__title"), q("quiet", "[data-hook='kennel-quiet']"),
            q("quiet_pose", "[data-hook='kennel-quiet'] svg.dk-badge", "attrs", attr="data-pose")])

    def test_its_own_dogs_tickets_fill_the_page(self):
        f = self.page([ticket("u-1", "Rex"), ticket("u-9", "Someone Else"), ticket("u-2", "Ace", result="lost")])["final"]
        self.assertEqual(f["acts"], 2)
        self.assertEqual(f["title"], "Latest tickets from this kennel")

    def test_with_no_tickets_a_thinking_dog_says_so(self):
        f = self.page([ticket("u-9", "Someone Else")])["final"]
        self.assertEqual(f["acts"], 0)
        self.assertIn("No tickets from this kennel yet", f["quiet"])
        self.assertEqual(f["quiet_pose"], ["thinking"])

    def test_a_stream_that_is_down_still_gets_the_quiet_state_not_an_error(self):
        f = self.page(None)["final"]
        self.assertIn("No tickets from this kennel yet", f["quiet"])


class MyKennelOnAPhone(unittest.TestCase):
    """Item 10: the fourth action ("Open") was an orphan on a line of its own at 390px; the stat labels were small and grey."""
    CSS = (ROOT / "web" / "css" / "studio.css").read_text(encoding="utf-8")

    def test_the_card_actions_are_a_two_column_grid_under_760px(self):
        self.assertRegex(self.CSS, r"@media \(max-width: 760px\) \{\s*\.kn-card__actions \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)")
        self.assertRegex(self.CSS, r"\.kn-card__actions \.kn-act \{ width: 100%;[^}]*min-height: 44px")

    def test_the_stat_labels_are_13px_and_brighter_than_the_old_mute(self):
        self.assertRegex(self.CSS, r"\.kn-stat dt \{ font-size: 13px; color: var\(--lh-ink2")

    def test_the_mine_card_still_has_the_four_actions_in_order(self):
        src = (ROOT / "web" / "js" / "kennel.js").read_text(encoding="utf-8")
        order = [src.index(h) for h in ('"dog-action-fire"', '"dog-action-ask"', '"dog-action-edit"', '"dog-action-open"')]
        self.assertEqual(order, sorted(order))


if __name__ == "__main__":
    unittest.main()
