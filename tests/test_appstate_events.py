"""src/appstate/events.py: analytics event scaffold.

WHY THE DB-BYTES SCAN
----------------------
Asserting `hash_user_id` was called is not the same guarantee as asserting
the raw id never reached disk -- a future refactor could call
`record_event` with a raw id and every dict-shaped assertion would still
pass, because a hash and an int can occupy the same code path without the
test noticing. Reading the .db file's raw bytes and searching for the raw
id's literal digits is the same style of "prove the promise by the
artifact, not the call graph" check tests/test_api_boundary.py uses for the
api/<->src/ boundary and tests/test_appstate_gitignore.py uses for the
gitignore contract.

STDLIB-ONLY CHECK
------------------
`ACCEPTANCE`/BOUNDARIES calls out src/ as stdlib-only; this is the same
static-text check tests/test_api_boundary.py already runs for the api/<->src
import direction, narrowed to third-party names against this one new file
so this task does not have to invent a repo-wide policy test that is not
its job to own.
"""

from __future__ import annotations

import ast
import re
import tempfile
import unittest
from pathlib import Path

from src.appstate import events

MODULE_PATH = Path(__file__).resolve().parent.parent / "src" / "appstate" / "events.py"

# Standard-library top-level modules this file is allowed to import. Kept
# as an explicit allowlist (rather than "not in some third-party list")
# because the module docstring promises stdlib-only, and an allowlist is
# the only way to fail loud the moment an unexpected import is added,
# rather than only catching the third-party packages someone happened to
# think of.
_ALLOWED_STDLIB = {
    "__future__", "hashlib", "json", "os", "sqlite3", "collections",
    "contextlib", "dataclasses", "datetime", "pathlib", "typing", "src",
}


class StdlibOnlyTests(unittest.TestCase):

    def test_events_module_imports_only_stdlib_and_src(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in _ALLOWED_STDLIB:
                        offenders.append(top)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top not in _ALLOWED_STDLIB:
                    offenders.append(top)
        self.assertEqual(
            offenders, [],
            f"src/appstate/events.py must stay stdlib-only; found: {offenders}")


class HashUserIdTests(unittest.TestCase):

    def test_hash_is_deterministic_sha256_hex(self):
        import hashlib
        self.assertEqual(events.hash_user_id(42),
                         hashlib.sha256(b"42").hexdigest())

    def test_different_ids_hash_differently(self):
        self.assertNotEqual(events.hash_user_id(1), events.hash_user_id(2))

    def test_none_is_refused(self):
        with self.assertRaises(ValueError):
            events.hash_user_id(None)


class RecordEventTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_and_list_roundtrip(self):
        uh = events.hash_user_id(7)
        ev = events.record_event(uh, events.PAGE_VIEW, {"date": "2026-08-31"},
                                 db=self.db)
        self.assertIsNotNone(ev.id)
        rows = events.list_events(db=self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, events.PAGE_VIEW)
        self.assertEqual(rows[0].properties, {"date": "2026-08-31"})

    def test_raw_user_id_is_refused_not_a_valid_hash(self):
        """record_event refuses an obviously-not-a-hash value (e.g. the raw
        int id stringified) rather than silently storing it -- catching the
        mistake at the call site instead of at a later audit."""
        with self.assertRaises(ValueError):
            events.record_event("7", events.PAGE_VIEW, db=self.db)
        with self.assertRaises(ValueError):
            events.record_event("breyderrett@example.com", events.PAGE_VIEW,
                                db=self.db)

    def test_unknown_kind_is_refused(self):
        uh = events.hash_user_id(1)
        with self.assertRaises(ValueError):
            events.record_event(uh, "signup", db=self.db)

    def test_every_enumerated_kind_is_accepted(self):
        uh = events.hash_user_id(1)
        for kind in events.EVENT_KINDS:
            events.record_event(uh, kind, db=self.db)
        self.assertEqual(len(events.list_events(db=self.db)), len(events.EVENT_KINDS))

    def test_raw_user_id_never_appears_in_the_db_file_bytes(self):
        """The load-bearing privacy guarantee, checked at the artifact: scan
        the .db file's raw bytes for the raw id's own digits/email and fail
        if found. A hash collision with these literal substrings is
        astronomically unlikely; this is the same "prove it by the byte
        content" rule test_api_boundary.py applies to the import graph."""
        raw_id = 918273645
        raw_email = "breydenerrett@gmail.com"
        uh_id = events.hash_user_id(raw_id)
        uh_email = events.hash_user_id(raw_email)
        events.record_event(uh_id, events.PAGE_VIEW, {"note": "no pii here"},
                            db=self.db)
        events.record_event(uh_email, events.BET_SAVED, db=self.db)

        blob = self.db.read_bytes()
        self.assertNotIn(str(raw_id).encode("utf-8"), blob)
        self.assertNotIn(raw_email.encode("utf-8"), blob)
        # Sanity: the hash itself (not the raw value) really is in there,
        # proving the scan isn't vacuously passing on an empty table.
        self.assertIn(uh_id.encode("utf-8"), blob)
        self.assertIn(uh_email.encode("utf-8"), blob)

    def test_properties_default_to_empty_dict(self):
        uh = events.hash_user_id(1)
        ev = events.record_event(uh, events.PAGE_VIEW, db=self.db)
        self.assertEqual(ev.properties, {})
        self.assertEqual(events.list_events(db=self.db)[0].properties, {})

    def test_at_defaults_to_now_iso_utc(self):
        uh = events.hash_user_id(1)
        ev = events.record_event(uh, events.PAGE_VIEW, db=self.db)
        # Round-trips through fromisoformat without raising -- proves it is
        # a real ISO-8601 timestamp, not just a truthy string.
        from datetime import datetime
        parsed = datetime.fromisoformat(ev.at.replace("Z", "+00:00"))
        self.assertIsNotNone(parsed.tzinfo)


class DailyCountsTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_table_gives_empty_aggregate(self):
        self.assertEqual(events.daily_counts_by_kind(db=self.db), {})

    def test_counts_grouped_by_day_and_kind(self):
        uh1, uh2 = events.hash_user_id(1), events.hash_user_id(2)
        events.record_event(uh1, events.PAGE_VIEW,
                            at="2026-08-31T10:00:00+00:00", db=self.db)
        events.record_event(uh2, events.PAGE_VIEW,
                            at="2026-08-31T11:00:00+00:00", db=self.db)
        events.record_event(uh1, events.BET_CHECK_RUN,
                            at="2026-08-31T12:00:00+00:00", db=self.db)
        events.record_event(uh1, events.PAGE_VIEW,
                            at="2026-09-01T09:00:00+00:00", db=self.db)
        counts = events.daily_counts_by_kind(db=self.db)
        self.assertEqual(counts, {
            "2026-08-31": {events.PAGE_VIEW: 2, events.BET_CHECK_RUN: 1},
            "2026-09-01": {events.PAGE_VIEW: 1},
        })

    def test_aggregate_never_counts_users_only_events(self):
        """Repeated events from the SAME hashed user on the same day/kind
        all count -- this aggregate is an event count, not a unique-user
        count (a future admin view may want the latter, but that is a
        different, not-yet-built function)."""
        uh = events.hash_user_id(1)
        for _ in range(3):
            events.record_event(uh, events.PAGE_VIEW,
                                at="2026-08-31T10:00:00+00:00", db=self.db)
        self.assertEqual(events.daily_counts_by_kind(db=self.db),
                         {"2026-08-31": {events.PAGE_VIEW: 3}})


class NoWiredCallSitesTests(unittest.TestCase):
    """BOUNDARIES: analytics is additive-only and must not be wired into any
    endpoint yet -- pinned here so a later, unrelated PR that adds a
    `from src.appstate import events` import to api/ notices it just
    crossed a deliberate line, not an oversight."""

    def test_no_api_module_imports_events_yet(self):
        api_dir = Path(__file__).resolve().parent.parent / "api"
        pattern = re.compile(
            r"^\s*(?:import\s+src\.appstate\.events\b"
            r"|from\s+src\.appstate\s+import\s+.*\bevents\b"
            r"|from\s+src\.appstate\.events\s+import\b)")
        hits = []
        for path in sorted(api_dir.glob("*.py")):
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.match(line):
                    hits.append(f"{path.name}:{lineno}")
        self.assertEqual(
            hits, [],
            "analytics is additive-only for this task -- record_event() "
            "must not be wired into api/ yet (see events.py's module "
            f"docstring for the integration note). Offending line(s): {hits}")


if __name__ == "__main__":
    unittest.main()
