"""Take them out back (src/hounds/interact/outback.py): a member's dog is buried, its record frozen and public.

Owner ruling 2026-10-20: "kill it and bury it and grave stone and record is frozen and public, and is posted to a public
graveyard but is dead and removed". Every case runs without FastAPI (the CI harness hides it; the last class proves the
module imports with FastAPI hidden), over a temp app database and a temp ledger.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from src.hounds import kennel_feed, kennels, stats, user_defs, user_spec, user_store, user_view
from src.hounds.interact import camp, outback, rites
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for, ticket

REPO = Path(__file__).resolve().parent.parent
LOSING = [(7, dict(result="LOSS", side="away", price=150)), (3, dict(result="WIN", side="away", price=150)),
          (4, dict(result="WIN", side="home", price=-110)), (2, dict(result="LOSS", side="home", price=-110))]


def refusal(test, fn, *a, **k):
    with test.assertRaises(rites.RiteError) as ctx:
        fn(*a, **k)
    return ctx.exception


class WhoMayBuryWhat(RitesCase):
    def test_the_owner_of_a_member_dog_buries_it(self):
        hound = self.dog()
        out = outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual(out["headstone"]["name"], "Rusty Pup")
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "buried")

    def test_someone_elses_dog_reads_as_not_there(self):
        hound = self.dog()
        exc = refusal(self, outback.bury, self.resolve(hound["id"]), self.other.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual((exc.code, exc.status), ("not_found", 404))
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "running")

    def test_a_house_dog_is_refused_in_words(self):
        exc = refusal(self, outback.bury, self.resolve("chalk_chihuahua"), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual((exc.code, exc.status), ("not_a_member_dog", 422))
        self.assertIn("house pack", str(exc))

    def test_an_unknown_dog_is_not_found(self):
        self.assertEqual(refusal(self, outback.bury, None, self.owner.id, confirmed=True).code, "not_found")

    def test_without_the_second_tap_nothing_is_buried(self):
        hound = self.dog()
        exc = refusal(self, outback.bury, self.resolve(hound["id"]), self.owner.id, confirmed=False, now=NOW, rows=[])
        self.assertEqual((exc.code, exc.status), ("confirm_required", 400))
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "running")
        self.assertEqual(user_store.list_events(), [])

    def test_a_dog_already_buried_is_refused_and_writes_no_second_event(self):
        hound = self.dog()
        dog = self.resolve(hound["id"])
        outback.bury(dog, self.owner.id, confirmed=True, now=NOW, rows=[])
        exc = refusal(self, outback.bury, self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual((exc.code, exc.status), ("already_buried", 409))
        self.assertEqual(len(user_store.list_events(user_store.EVENT_BURIED)), 1)

    def test_a_retired_dog_cannot_be_buried(self):
        hound = self.dog()
        user_store.retire_hound(hound["id"], by=f"owner:{self.owner.id}", reason="removed")
        exc = refusal(self, outback.bury, self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual(exc.code, "not_active")


class OpenTicketsBlockTheBurial(RitesCase):
    def test_an_open_ticket_blocks_it_with_the_owners_words(self):
        hound = self.dog()
        rows = rows_for(hound["id"], [(2, dict(result="WIN"))]) + ticket(hound["id"], result=None, start_hours_ago=-3, now=NOW)
        exc = refusal(self, outback.bury, self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows)
        self.assertEqual((exc.code, exc.status), ("open_tickets", 409))
        self.assertIn("Wait until its open tickets settle", str(exc))
        self.assertEqual(exc.extra["open_tickets"], 1)
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "running")

    def test_a_ticket_still_waiting_for_a_grade_blocks_it_too(self):
        """More than 36 hours past the start with no grade is "ungraded", not open, but a late grade must not land on a
        frozen record, so it blocks the burial as well."""
        hound = self.dog()
        rows = ticket(hound["id"], result=None, start_hours_ago=60, now=NOW)
        exc = refusal(self, outback.bury, self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows)
        self.assertEqual(exc.code, "open_tickets")
        self.assertIn("waiting for a grade", str(exc))

    def test_it_reads_the_ledger_not_the_cached_book(self):
        """A ticket written after the stats book was built must still count: the book can be an hour old."""
        hound = self.dog()
        from tests._hounds_rites_fixtures import write_ledger
        write_ledger(self.ledger, ticket(hound["id"], result=None, start_hours_ago=-2, now=NOW))
        exc = refusal(self, outback.bury, self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW)
        self.assertEqual(exc.code, "open_tickets")

    def test_once_every_ticket_settles_it_goes_through(self):
        hound = self.dog()
        rows = rows_for(hound["id"], [(3, dict(result="LOSS"))])
        out = outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows)
        self.assertEqual(out["headstone"]["record"]["losses"], 3)

    def test_another_dogs_open_ticket_is_not_this_dogs(self):
        a, b = self.dog("Dog A"), self.dog("Dog B")
        rows = ticket(b["id"], result=None, start_hours_ago=-2, now=NOW)
        outback.bury(self.resolve(a["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows)
        self.assertEqual(user_store.get_hound(a["id"])["status"], "buried")


class WhatBurialDoes(RitesCase):
    def bury(self, hound, rows=None):
        return outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW,
                            rows=rows if rows is not None else rows_for(hound["id"], LOSING))

    def test_the_status_is_buried_and_the_spec_and_ledger_are_untouched(self):
        hound = self.dog(side_rule="market_moved_toward")
        rows = rows_for(hound["id"], LOSING)
        before = len(rows)
        self.bury(hound, rows)
        row = user_store.get_hound(hound["id"])
        self.assertEqual((row["status"], row["retire_reason"], row["retired_by"]), ("buried", "buried by its owner", f"owner:{self.owner.id}"))
        self.assertEqual(row["spec"], hound["spec"])
        self.assertEqual(len(rows), before)                            # nothing was written to a ledger

    def test_one_append_only_event_row_per_burial(self):
        hound = self.dog()
        self.bury(hound)
        events = user_store.list_events(user_store.EVENT_BURIED)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]["hound_id"], events[0]["owner_user_id"]), (hound["id"], self.owner.id))
        self.assertFalse([n for n in dir(user_store) if n.startswith(("update_event", "delete_event"))],
                         "the store has no way to change or remove an event")

    def test_the_headstone_holds_the_frozen_numbers(self):
        hound = self.dog(side_rule="market_moved_toward")
        stone = self.bury(hound)["headstone"]
        self.assertEqual((stone["record"]["wins"], stone["record"]["losses"], stone["record"]["pushes"]), (7, 9, 0))
        self.assertEqual(stone["name"], "Rusty Pup")
        self.assertEqual(stone["died"], "2026-10-20")
        self.assertTrue(stone["born"])
        self.assertEqual(stone["bankroll"]["start"], 1000.0)
        self.assertIsNotNone(stone["bankroll"]["final"])
        self.assertEqual(stone["best_win"]["selection"], "Boston Red Sox to win")      # the +150 away win pays the most
        self.assertTrue(stone["frozen"])
        self.assertNotIn("owner_user_id", stone)
        self.assertEqual(stone["kennel"]["display"], user_defs.owner_display(self.owner.id))

    def test_the_headstone_is_frozen_in_the_event_not_recomputed(self):
        hound = self.dog()
        self.bury(hound, rows_for(hound["id"], [(3, dict(result="WIN"))]))
        first = outback.headstone_for(hound["id"])
        later = rows_for(hound["id"], [(5, dict(result="LOSS"))])               # a late grade would change a recomputed record
        self.assertEqual(outback.headstone_for(hound["id"]), first)
        self.assertEqual(first["record"]["wins"], 3)
        self.assertEqual(len(later), 10)

    def test_a_buried_dog_stops_betting(self):
        hound = self.dog()
        self.assertEqual([h["id"] for h in user_store.list_running()], [hound["id"]])
        self.bury(hound)
        self.assertEqual(user_store.list_running(), [])

    def test_a_buried_dog_cannot_be_changed_or_retired_over(self):
        hound = self.dog()
        self.bury(hound)
        with self.assertRaises(user_store.StoreError) as ctx:
            user_store.create_version(hound["id"], hound["spec"], actor="owner", reason="edit")
        self.assertEqual(ctx.exception.code, "buried")
        user_store.retire_hound(hound["id"], by="admin", reason="moderation")
        self.assertEqual(user_store.get_hound(hound["id"])["status"], "buried")


class TheLearningLoopLeavesABuriedDogAlone(RitesCase):
    def test_a_challenger_born_under_a_buried_champion_has_no_champion_left_to_pair_with(self):
        from src.hounds.learning import user_scope
        from types import SimpleNamespace
        hound = self.dog()
        challenger = SimpleNamespace(parent_ref=hound["id"])
        self.assertTrue(user_scope.champion_current(challenger, None))
        outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertFalse(user_scope.champion_current(challenger, None))

    def test_the_coachs_undo_refuses_a_buried_dog(self):
        from src.hounds import user_coach
        hound = self.dog()
        outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        with self.assertRaises(user_coach.CoachError) as ctx:
            user_coach.undo(hound["id"])
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("not_running", 409))


class RankingAndTheLists(RitesCase):
    def book(self, *hounds):
        data = {h["id"]: user_view.hound_data(h["id"], kick_build=False, rows=[]) for h in hounds}
        return stats.HoundBook(hounds=data, stream=[], as_of="2026-10-20", built_utc="2026-10-20T00:00:00Z", fingerprint=())

    def test_a_buried_dog_leaves_the_leaderboards_ranking_and_enters_the_stats_graveyard(self):
        live, gone = self.dog("Live Dog"), self.dog("Gone Dog")
        outback.bury(self.resolve(gone["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        book = self.book(live, user_store.get_hound(gone["id"]))
        ranked = [s.id for s in stats.leaderboard(book)]
        self.assertEqual(ranked, [live["id"]])
        yard = stats.graveyard(book)
        self.assertEqual([s.id for s in yard], [gone["id"]])
        self.assertEqual(yard[0].retired.cause, "buried by the owner")

    def test_a_buried_dog_leaves_the_kennel_list_and_the_count_but_is_in_the_graveyard(self):
        live, gone = self.dog("Live Dog"), self.dog("Gone Dog")
        outback.bury(self.resolve(gone["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        handle = kennels.handle_for(self.owner.id)
        page = kennels.kennel_detail(handle)
        self.assertEqual([d["id"] for d in page["dogs"]], [live["id"]])
        self.assertEqual(page["dog_count"], 1)
        self.assertEqual([s["hound_id"] for s in page["graveyard"]], [gone["id"]])
        self.assertEqual([k["dog_count"] for k in kennels.kennel_list()["kennels"]], [1])
        mine = kennels.my_kennel(self.owner.id)
        self.assertEqual([d["id"] for d in mine["dogs"]], [live["id"]])
        self.assertEqual(mine["dog_count"], 1)
        self.assertEqual([s["hound_id"] for s in mine["graveyard"]], [gone["id"]])

    def test_a_kennel_whose_dogs_are_all_buried_still_has_a_page_but_no_place_in_the_index(self):
        gone = self.dog("Gone Dog")
        outback.bury(self.resolve(gone["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        page = kennels.kennel_detail(kennels.handle_for(self.owner.id))
        self.assertEqual((page["dog_count"], page["dogs"], len(page["graveyard"])), (0, [], 1))
        self.assertEqual(kennels.kennel_list()["kennels"], [])

    def test_earlier_versions_of_a_buried_lineage_go_with_it(self):
        v1 = self.dog("Old Timer")
        v2 = user_store.create_version(v1["id"], v1["spec"] | {"max_bets_per_day": 1}, actor="owner", reason="edit")
        outback.bury(self.resolve(v2["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual(kennels.my_kennel(self.owner.id)["dogs"], [])

    def test_the_graveyard_lists_every_kennel_newest_first(self):
        a, b, c = self.dog("Dog A"), self.dog("Dog B", owner=self.other), self.dog("Dog C")
        from datetime import timedelta
        for i, (hound, who) in enumerate(((a, self.owner), (b, self.other), (c, self.owner))):
            outback.bury(self.resolve(hound["id"]), who.id, confirmed=True, now=NOW + timedelta(hours=i), rows=[])
        stones = outback.headstones()
        self.assertEqual([s["name"] for s in stones], ["Dog C", "Dog B", "Dog A"])
        self.assertEqual(len({s["kennel"]["handle"] for s in stones}), 2)
        self.assertEqual([s["name"] for s in outback.headstones(owner_user_id=self.other.id)], ["Dog B"])

    def test_the_kit_stops_offering_the_rites_to_a_buried_dog(self):
        hound = self.dog()
        live = camp.kit(self.resolve(hound["id"]), self.owner.id)
        self.assertTrue(live["can_train"] and live["can_out_back"] and live["can_fire"])
        outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        gone = camp.kit(self.resolve(hound["id"]), self.owner.id)
        self.assertEqual((gone["buried"], gone["can_train"], gone["can_out_back"], gone["can_fire"]), (True, False, False, False))

    def test_the_training_camp_does_not_list_a_buried_dog(self):
        hound = self.dog()
        outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual(camp.mine(self.owner.id)["dogs"], [])


class TheSlotIsFree(RitesCase):
    def test_a_free_account_can_build_again_after_burying_its_one_dog(self):
        first = user_store.create_hound(self.owner.id, self.dog_spec("Only Dog"), free_tier=True)
        with self.assertRaises(user_store.StoreError) as ctx:
            user_store.create_hound(self.owner.id, self.dog_spec("Second Dog"), free_tier=True)
        self.assertEqual(ctx.exception.code, "upgrade_required")
        outback.bury(self.resolve(first["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        second = user_store.create_hound(self.owner.id, self.dog_spec("Second Dog"), free_tier=True)
        self.assertEqual(second["status"], "running")

    def test_a_paid_account_at_five_dogs_can_build_a_sixth_after_a_burial(self):
        dogs = [user_store.create_hound(self.owner.id, self.dog_spec(f"Dog Number {n}")) for n in "ABCDE"]
        with self.assertRaises(user_store.StoreError) as ctx:
            user_store.create_hound(self.owner.id, self.dog_spec("Dog Number F"))
        self.assertEqual(ctx.exception.code, "limit")
        outback.bury(self.resolve(dogs[0]["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        self.assertEqual(user_store.create_hound(self.owner.id, self.dog_spec("Dog Number F"))["status"], "running")

    def test_a_benched_dog_buried_frees_a_free_slot_too(self):
        first = user_store.create_hound(self.owner.id, self.dog_spec("Only Dog"), free_tier=True)
        with user_store._connect() as conn:
            conn.execute("UPDATE hounds SET status = 'benched' WHERE id = ?", (first["id"],))
        outback.bury(self.resolve(first["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        user_store.create_hound(self.owner.id, self.dog_spec("Next Dog"), free_tier=True)

    @staticmethod
    def dog_spec(name="Only Dog"):
        from tests._hounds_user_fixtures import spec_dict
        return spec_dict(name=name)


class TheEpitaph(unittest.TestCase):
    STEAM = user_spec.validate_spec(dict(name="Steamy Pup", tagline="", sports=["MLB"], markets=["moneyline"],
                                         side_rule="market_moved_toward", price_min=100, price_max=250, min_books=3,
                                         max_bets_per_day=2, lock_minutes=120))

    def test_the_same_stats_always_write_the_same_words(self):
        for seed in ("u-aaa", "u-bbb", "u-ccc"):
            a = outback.epitaph(self.STEAM, 7, 12, 0, -6.4, seed)
            b = outback.epitaph(self.STEAM, 7, 12, 0, -6.4, seed)
            self.assertEqual(a, b)

    def test_a_losing_steam_chaser_ends_in_the_wall_with_its_record(self):
        lines = {outback.epitaph(self.STEAM, 7, 12, 0, -6.4, f"u-{i}") for i in range(40)}
        self.assertIn("Chased steam into a wall. 7-12.", lines)
        for line in lines:
            self.assertTrue(line.startswith("Chased steam"), line)
            self.assertTrue(line.endswith(" 7-12."), line)

    def test_the_record_carries_pushes_only_when_there_are_some(self):
        self.assertTrue(outback.epitaph(self.STEAM, 7, 12, 2, -6.4, "u-1").endswith(" 7-12-2."))

    def test_the_tiers_read_differently(self):
        seed = "u-same"
        none = outback.epitaph(self.STEAM, 0, 0, 0, None, seed)
        young = outback.epitaph(self.STEAM, 1, 2, 0, -1.0, seed)
        losing = outback.epitaph(self.STEAM, 7, 12, 0, -6.4, seed)
        level = outback.epitaph(self.STEAM, 10, 10, 0, 0.3, seed)
        winning = outback.epitaph(self.STEAM, 14, 6, 0, 7.5, seed)
        self.assertEqual(none, "Never got a ticket down. 0-0.")
        self.assertEqual(len({none, young, losing, level, winning}), 5)

    def test_the_trait_comes_from_the_rule(self):
        def trait(**over):
            return outback.trait_of(user_spec.validate_spec({**dict(self.STEAM), **over}))
        self.assertEqual(trait(side_rule="underdog"), "Took the dogs")
        self.assertEqual(trait(side_rule="favourite"), "Backed the chalk")
        self.assertEqual(trait(side_rule="market_moved_away"), "Faded the steam")
        self.assertEqual(trait(side_rule="over", markets=["total"]), "Bet the over")

    def test_a_custom_rules_dog_is_known_by_its_conditions(self):
        spec = user_spec.validate_spec({"version": 2, "name": "Rule Pup", "rules": [
            {"sports": ["MLB"], "markets": ["moneyline"], "side": "either", "when": {"op": "all", "items": [{"id": "role", "value": "underdog"}]}}]})
        self.assertEqual(outback.trait_of(spec), "Took the dogs")

    def test_no_emoji_no_exclamation_and_no_money_claim(self):
        for w, l, u in ((0, 0, None), (1, 2, -1.0), (7, 12, -6.4), (10, 10, 0.3), (14, 6, 7.5)):
            for seed in range(8):
                line = outback.epitaph(self.STEAM, w, l, 0, u, f"u-{seed}")
                self.assertTrue(line.isascii(), line)
                self.assertNotIn("!", line)
                self.assertNotRegex(line.lower(), r"profit|edge|guarantee|winner|beat the|\$")


class TheFeedAnnouncesIt(RitesCase):
    def test_a_burial_is_a_news_item_with_its_epitaph_and_no_second_put_down_item(self):
        hound = self.dog(side_rule="market_moved_toward")
        outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=rows_for(hound["id"], LOSING))
        events = kennel_feed.rite_events(user_store.list_events())
        self.assertEqual(len(events), 1)
        item = events[0]
        self.assertEqual((item["kind"], item["guid"]), ("buried", f"kennel:buried:{hound['id']}"))
        self.assertIn("Rusty Pup was taken out back", item["title"])
        self.assertIn("Its record is frozen and it is in the graveyard.", item["why"])
        self.assertIn("7-9", item["why"])                              # the record is in the epitaph
        self.assertEqual(item["pub"].strftime("%Y-%m-%d"), "2026-10-20")
        # the stats book's own "retired" item skips a buried dog, so the news says it once
        book = RankingAndTheLists.book(self, hound)
        book.hounds[hound["id"]] = user_view.hound_data(hound["id"], kick_build=False, rows=[])
        self.assertEqual(kennel_feed.retired_events(book), [])

    def test_the_item_is_in_the_built_feed(self):
        hound = self.dog()
        outback.bury(self.resolve(hound["id"]), self.owner.id, confirmed=True, now=NOW, rows=[])
        book = RankingAndTheLists.book(self, hound)
        built = kennel_feed.build_events(book, {}, user_store.list_all(), rites=user_store.list_events())
        self.assertIn("buried", {e["kind"] for e in built})
        xml = kennel_feed.render_feed(built)
        self.assertIn("was taken out back", xml)
        self.assertIn("Paper bets only, not advice. 21+.", xml)


class NoFastApiNeeded(unittest.TestCase):
    def test_the_rites_import_with_fastapi_hidden(self):
        code = ("import sys\nfor n in ('fastapi','starlette','pydantic','uvicorn'): sys.modules[n] = None\n"
                "import src.hounds.interact.outback, src.hounds.interact.training, src.hounds.interact.rites, src.hounds.kennels, src.hounds.kennel_feed\n"
                "print('ok')")
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), "ok", proc.stderr[-800:])

    def test_no_rites_file_imports_fastapi_or_api(self):
        for name in ("outback.py", "training.py", "rites.py"):
            text = (REPO / "src" / "hounds" / "interact" / name).read_text(encoding="utf-8")
            for banned in ("import fastapi", "from fastapi", "from api", "import api"):
                self.assertNotIn(banned, text, name)


if __name__ == "__main__":
    unittest.main()
