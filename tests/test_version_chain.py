"""src/hounds/version_chain.py: a hound's lineage, every version of it, for the Deep reviews, the all-versions sheet and the coaching feed.

Pure: the book's hounds and the member rows are passed in, so none of this needs a database or the app.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from src.hounds import version_chain as vc
from tests.backfill_fixtures import user_row


def book(*pairs):
    """{hound id: HoundData-ish} with a summary that has a name and a status."""
    return {hid: SimpleNamespace(summary=SimpleNamespace(name=name, status=status)) for hid, name, status in pairs}


class TheMemberHoundsChain(unittest.TestCase):
    def setUp(self):
        self.rows = [user_row("u-3", "u-1", 3, status="benched"), user_row("u-1", "u-1", 1, status="retired", reason="superseded by u-2: edit"),
                     user_row("u-2", "u-1", 2, status="retired", reason="superseded by u-3: training"), user_row("u-9", "u-9", 1)]

    def test_the_versions_are_in_order_under_their_root_whatever_order_the_rows_came_in(self):
        chains = vc.build_chains({}, self.rows)
        self.assertEqual(sorted(chains), ["u-1", "u-9"])
        chain = chains["u-1"]
        self.assertEqual(chain.ids, ["u-1", "u-2", "u-3"])
        self.assertEqual([m.label for m in chain.members], ["v1", "v2", "v3"])
        self.assertEqual(chain.current.hound_id, "u-3")

    def test_each_versions_status_is_said_in_plain_words(self):
        members = vc.build_chains({}, self.rows)["u-1"].members
        self.assertEqual([m.status_text for m in members], ["replaced by a later version", "replaced by a later version", "benched"])
        mix = [user_row("a", "a", 1, status="retired", reason="removed from the kennel by its owner"), user_row("b", "b", 1, status="buried"),
               user_row("c", "c", 1, status="running")]
        chains = vc.build_chains({}, mix)
        self.assertEqual(chains["a"].current.status_text, "retired")
        self.assertEqual(chains["b"].current.status_text, "buried")
        self.assertEqual(chains["c"].current.status_text, "running")

    def test_a_version_the_book_has_not_built_yet_is_still_a_member(self):
        chains = vc.build_chains(book(("u-3", "Dee", "running")), self.rows)
        self.assertEqual(chains["u-1"].ids, ["u-1", "u-2", "u-3"])
        self.assertNotIn("u-3", chains)                                                         # and is never made a lineage of its own

    def test_a_member_hound_is_not_mistaken_for_a_pack_archive(self):
        rows = [user_row("x@v1", "x@v1", 1)]
        chains = vc.build_chains(book(("x@v1", "X", "running")), rows)
        self.assertEqual(list(chains), ["x@v1"])


class ThePackHoundsChain(unittest.TestCase):
    def test_an_archive_is_an_earlier_version_and_the_base_id_is_the_current_one(self):
        chains = vc.build_chains(book(("pk@v2", "Pack", "retired"), ("pk", "Pack", "running"), ("pk@v1", "Pack", "retired")))
        chain = chains["pk"]
        self.assertEqual(chain.ids, ["pk@v1", "pk@v2", "pk"])
        self.assertEqual([m.label for m in chain.members], ["v1", "v2", "v3"])
        self.assertEqual([m.status_text for m in chain.members], ["replaced by a later version", "replaced by a later version", "running"])

    def test_the_current_version_takes_the_status_the_book_gives_it(self):
        chains = vc.build_chains(book(("pk@v1", "Pack", "retired"), ("pk", "Pack", "benched")))
        self.assertEqual(chains["pk"].current.status_text, "benched")

    def test_an_unversioned_hound_is_a_lineage_of_one(self):
        chains = vc.build_chains(book(("h-1", "House", "running"), ("b-1", "Baseline", "running")))
        self.assertEqual({k: c.ids for k, c in chains.items()}, {"h-1": ["h-1"], "b-1": ["b-1"]})
        self.assertEqual(chains["h-1"].current.label, "v1")

    def test_archives_without_their_base_are_still_listed(self):
        chains = vc.build_chains(book(("pk@v1", "Pack", "retired")))
        self.assertEqual(chains["pk"].ids, ["pk@v1"])

    def test_an_id_that_only_looks_like_an_archive_is_not_one(self):
        for odd in ("a@vx", "@v1", "a@v", "a@v1b"):
            chains = vc.build_chains(book((odd, "Odd", "running")))
            self.assertEqual(list(chains), [odd], odd)

    def test_the_separator_is_the_learning_loops_own(self):
        from src.hounds.learning import lineage
        self.assertEqual(vc.ARCHIVE_SEP, lineage.ARCHIVE_SEP)
        self.assertEqual(vc.lineage_key_of(lineage.archived_id("pk", 3)), lineage.base_id(lineage.archived_id("pk", 3)))


class TheLookups(unittest.TestCase):
    def test_the_lineage_key_without_scanning_anything(self):
        self.assertEqual(vc.lineage_key_of("u-2", "u-1"), "u-1")
        self.assertEqual(vc.lineage_key_of("pk@v4"), "pk")
        self.assertEqual(vc.lineage_key_of("pk"), "pk")

    def test_chain_for_and_version_of_find_any_version(self):
        rows = [user_row("u-1", "u-1", 1), user_row("u-2", "u-1", 2)]
        chains = vc.build_chains({}, rows)
        self.assertEqual(vc.chain_for("u-2", chains).key, "u-1")
        self.assertEqual(vc.version_of("u-1", chains).label, "v1")
        self.assertIsNone(vc.chain_for("nobody", chains))
        self.assertIsNone(vc.version_of("nobody", chains))

    def test_member_ids_falls_back_to_the_one_id_it_was_given(self):
        self.assertEqual(vc.member_ids("lone", {}, []), ["lone"])
        rows = [user_row("u-1", "u-1", 1), user_row("u-2", "u-1", 2)]
        self.assertEqual(vc.member_ids("u-2", {}, rows), ["u-1", "u-2"])

    def test_loading_the_rows_never_raises_and_never_makes_the_database_appear(self):
        from src.hounds import user_defs
        with mock.patch.object(user_defs, "db_exists", lambda: False):
            self.assertEqual(vc.load_user_rows(), [])

        def boom():
            raise OSError("disk")
        with mock.patch.object(user_defs, "db_exists", boom):
            self.assertEqual(vc.load_user_rows(), [])


if __name__ == "__main__":
    unittest.main()
