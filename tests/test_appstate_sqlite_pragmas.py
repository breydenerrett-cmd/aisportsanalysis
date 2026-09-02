"""Cross-store sqlite concurrency hardening: every src/appstate store's
`_connect()` factory sets WAL journal mode and a 5s busy_timeout, and
survives two connections racing to be the first to open a brand-new db
file -- which, as this file's own test development found, is NOT the same
thing as "sets the two pragmas."

WHY THIS IS ITS OWN FILE, NOT FOLDED INTO tests/test_appstate_users.py ETC.
------------------------------------------------------------------------------
Six modules (users, customers, freechecks, savedbets, support, events) each
carry their own copy of the same `_connect()` shape -- deliberately, per
each module's own docstring ("same shape src.appstate.users._connect uses").
A pragma (or a fix) added to one and missed on another would be exactly the
kind of drift six independent, structurally-identical functions invite, and
no single module's own test file would ever catch it: each only knows about
itself. This file exists to pin the property ACROSS all six at once, the
same way tests/test_appstate_gitignore.py pins a repo-wide invariant no
single module owns.

WHY WAL + busy_timeout, AND WHY NOW
--------------------------------------
deploy/fly.staging.toml pins the alpha deploy to one process
(max_machines_running=1) specifically because sqlite is not built for
concurrent writers across PROCESSES -- but two THREADS in that one process
(two overlapping requests, or a request racing a background sweep) can
still open two connections to the same db file at the same instant. Before
this task, that raced on sqlite's default rollback-journal locking, which
can raise "database is locked" the instant a writer holds the file while a
second writer tries to start. WAL lets readers proceed while a writer
commits; busy_timeout gives a second writer up to 5s to wait for the lock
instead of failing immediately. Alpha testers arrive in ~2 days
(2026-09-02) -- two testers hitting POST /my-bets or POST /support in the
same second is exactly the ordinary case this closes, not an edge case.

TWO RACES THIS FILE CAUGHT WHILE BEING WRITTEN, NOT JUST THE ONE IT SET OUT
TO TEST -- both are why ColdStartRaceRegressionTests below exists
------------------------------------------------------------------------------
1. PRAGMA ORDER. busy_timeout is a per-CONNECTION setting that defaults to
   0 (fail instantly, no retry) on a brand-new connection. Setting
   `journal_mode=WAL` BEFORE `busy_timeout` runs that first pragma with the
   default zero timeout still in effect, so a connection opened at the
   wrong instant could raise "database is locked" on the very pragma meant
   to prevent that error. Every store below now sets busy_timeout first.
2. THE FIRST-EVER WAL TRANSITION ISN'T AN ORDINARY LOCK WAIT.
   busy_timeout, even set first, does not cover every lock conflict: the
   FIRST-EVER transition of a brand-new db file into WAL mode takes a
   special, briefly-exclusive lock through a different internal sqlite
   path that does not go through the normal busy-handler retry mechanism
   busy_timeout installs. Two connections racing to be first to open a
   fresh file can hit this -- one wins, the other's identical
   `PRAGMA journal_mode=WAL` raises "database is locked" INSTANTLY, not
   after waiting out busy_timeout's 5s. Every store's `_set_wal_mode`
   helper now retries this specific failure by hand (a documented,
   standard workaround for this sqlite behavior) since busy_timeout cannot.
   A THIRD, related race -- two connections' migration-safe `PRAGMA
   table_info` + conditional `ALTER TABLE ADD COLUMN` (users.py,
   customers.py, savedbets.py) landing on the same "column absent" read
   before either's ALTER commits -- is guarded separately, at each ALTER
   site itself (see e.g. savedbets.py's `_ensure_schema` comment); this
   file's cold-start regression test exercises that race too, since it
   only manifests on a brand-new db file, same as the two above.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from src.appstate import customers, events, freechecks, savedbets, support, users

# Every store sharing the identical `_connect(path: Optional[Path] = None)`
# shape -- see module docstring. Listed once here so every test class below
# (and any future one) walks the same set instead of drifting apart.
STORE_MODULES = (users, customers, freechecks, savedbets, support, events)


class SqlitePragmaTests(unittest.TestCase):
    """Reaches for each module's private `_connect()` on purpose: the
    pragmas are connection-setup behavior, not part of any store's public
    read/write contract, so the one function that actually opens the
    connection is what has to be asserted on."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_every_store_sets_wal_journal_mode(self):
        for module in STORE_MODULES:
            with self.subTest(module=module.__name__):
                with module._connect(self.db) as conn:
                    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual(mode.lower(), "wal")

    def test_every_store_sets_a_five_second_busy_timeout(self):
        for module in STORE_MODULES:
            with self.subTest(module=module.__name__):
                with module._connect(self.db) as conn:
                    timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
                self.assertEqual(timeout_ms, 5000)

    def test_journal_mode_persists_across_a_fresh_connect_call(self):
        """WAL is recorded IN THE DB FILE (unlike busy_timeout, which is
        per-connection) -- a second, independent `_connect()` call against
        the same file must see WAL already in effect, not re-negotiate it.
        Guards against a future edit that only sets the pragma conditionally
        on a fresh file and silently stops doing so on every call after."""
        with users._connect(self.db):
            pass  # first connect creates the file and sets WAL
        with customers._connect(self.db) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")


class ConcurrentWriterSmokeTests(unittest.TestCase):
    """Two threads writing to ONE store's db file at the same time -- the
    shape a real alpha day produces (two testers' requests landing in the
    same window) that a rollback-journal db can turn into "database is
    locked" under exactly this load. WAL + busy_timeout together are what
    make this pass instead of raise; this test is the regression pin for
    that story, not a load test.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_two_threads_writing_saved_bets_concurrently_never_locks(self):
        # savedbets over the other five stores: it is a real, unmodified
        # write path (save_bet) with no test-only shortcut, and append-only
        # semantics mean two threads' writes can never step on each other's
        # rows -- any failure here is purely a locking failure, not a data
        # race this module's own logic is responsible for avoiding.
        writes_per_thread = 25
        errors = []

        def _write(thread_id: int) -> None:
            try:
                for n in range(writes_per_thread):
                    savedbets.save_bet(1, f"game-{thread_id}-{n}", "home",
                                       db=self.db)
            except Exception as exc:  # noqa: BLE001 -- the assertion IS "nothing raised"
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"concurrent writers raised: {errors!r}")
        bets = savedbets.list_bets(1, db=self.db)
        self.assertEqual(len(bets), 2 * writes_per_thread)


# One write call per store, exercised by ColdStartRaceRegressionTests below.
# Each is a real, unmodified public write path -- no test-only shortcut --
# chosen so its very FIRST call against a brand-new db file is exactly the
# moment this file's two cold-start races (see module docstring) can occur:
# the first-ever WAL transition, and (for users/customers/savedbets) the
# first-ever migration-safe ALTER TABLE.
_STORE_FIRST_WRITES = {
    "users": lambda db, i, k: users.create_user(
        f"race-{id(db)}-{i}-{k}@example.com", db=db),
    "customers": lambda db, i, k: customers.upsert_customer(
        i * 1000 + k, f"cus_{i}_{k}", db=db),
    "freechecks": lambda db, i, k: freechecks.issue_grant(db=db),
    "savedbets": lambda db, i, k: savedbets.save_bet(
        1, f"g-{i}-{k}", "home", db=db),
    "support": lambda db, i, k: support.create_message(
        user_id=i * 1000 + k, subject="s", body="b", db=db),
    "events": lambda db, i, k: events.record_event(
        events.hash_user_id(f"{i}-{k}"), events.PAGE_VIEW, {}, db=db),
}


class ColdStartRaceRegressionTests(unittest.TestCase):
    """Regression pin for the two races this file's own development found
    (see module docstring): a `threading.Barrier` forces N threads to open
    their FIRST-EVER connection to a brand-new db file at as close to the
    same instant as this process can arrange, which is what actually
    reproduced "database is locked" reliably during development --
    `Thread.start()` alone (ConcurrentWriterSmokeTests above) only hits the
    narrow cold-start window occasionally, by luck of the scheduler. This
    class exists so the pin does not depend on that luck.
    """

    THREAD_COUNT = 4  # enough to make the race land almost every run,
                       # without turning this into a slow stress test.

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _race_first_writes(self, write_fn) -> list:
        barrier = threading.Barrier(self.THREAD_COUNT)
        errors: list = []

        def _work(thread_id: int) -> None:
            try:
                barrier.wait(timeout=5)
                for k in range(5):
                    write_fn(self.db, thread_id, k)
            except Exception as exc:  # noqa: BLE001 -- the assertion IS "nothing raised"
                errors.append(exc)

        threads = [threading.Thread(target=_work, args=(i,))
                  for i in range(self.THREAD_COUNT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        return errors

    def test_every_store_survives_a_barrier_synchronized_cold_start(self):
        for name, write_fn in _STORE_FIRST_WRITES.items():
            with self.subTest(module=name):
                # Fresh db per store -- each one's own cold-start race, not
                # a shared file where an earlier store's writes would leave
                # WAL/schema already established for the next.
                tmp = tempfile.TemporaryDirectory()
                try:
                    self.db = Path(tmp.name) / "app.db"
                    errors = self._race_first_writes(write_fn)
                    self.assertEqual(
                        errors, [],
                        f"{name}: concurrent cold-start writers raised: {errors!r}")
                finally:
                    tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
