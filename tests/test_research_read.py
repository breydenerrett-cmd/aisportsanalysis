"""Owner research feed (src/hounds/research_read.py, api/research_read.py, scripts/research_pull.py)."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:                      # Linux CI runs the no-FastAPI harness
    HAS_FASTAPI = False

from scripts import research_pull
from src.hounds import research_read as rr

SECRET = "s3cret-token-value"
_REAL_PULL = research_pull.pull


class Token(unittest.TestCase):
    def test_off_when_unset_or_empty(self):
        self.assertFalse(rr.token_ok(SECRET, {}))
        self.assertFalse(rr.token_ok(SECRET, {rr.TOKEN_ENV: ""}))
        self.assertFalse(rr.token_ok("", {rr.TOKEN_ENV: ""}))

    def test_bad_and_good(self):
        env = {rr.TOKEN_ENV: SECRET}
        self.assertFalse(rr.token_ok(None, env))
        self.assertFalse(rr.token_ok("nope", env))
        self.assertTrue(rr.token_ok(SECRET, env))


def _versions():
    base = {"owner_user_id": 7, "tagline": "", "spec": {"x": 1}, "version_of": None, "retired_at": None,
            "retire_reason": None, "created_at": "2026-10-01T00:00:00Z"}
    return [dict(base, id="u-1", name="Dee", root_id="u-1", version_no=1, status="retired", retired_at="2026-10-05T00:00:00Z"),
            dict(base, id="u-2", name="Dee", root_id="u-1", version_no=2, status="running", version_of="u-1")]


def _rows(view):
    return [{"bet_id": f"{view}-1", "date": "2026-10-02", "hound_id": view, "reason": "r"},
            {"bet_id": f"{view}-2", "date": "2026-10-09", "hound_id": view, "reason": "r"}]


class Rows(unittest.TestCase):
    def setUp(self):
        from src.hounds.interact import common
        ps = [mock.patch.object(rr, "_user_versions", _versions),
              mock.patch.object(common, "resolve",
                                lambda hid: SimpleNamespace(id=hid, kind="user", name="Dee", root_id="u-1", status="x", spec={})),
              mock.patch.object(common, "rule_text", lambda dog: "rule"),
              mock.patch.object(common, "hound_data",
                                lambda dog: SimpleNamespace(view=lambda _k, hid=dog.id: hid)),
              mock.patch.object(rr.bet_export, "build_rows", lambda view, now=None: _rows(view)),
              mock.patch("src.hounds.pack.BY_ID", {}),
              mock.patch("src.hounds.stats.peek_book", lambda: None)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def test_all_versions_including_retired(self):
        rows = list(rr.bet_rows())
        self.assertEqual({r["version_no"] for r in rows}, {1, 2})
        self.assertEqual({r["version_status"] for r in rows}, {"retired", "running"})
        self.assertEqual({r["root_id"] for r in rows}, {"u-1"})
        self.assertEqual(len(rows), 4)

    def test_filters(self):
        self.assertEqual(len(list(rr.bet_rows(since="2026-10-05"))), 2)
        self.assertEqual(len(list(rr.bet_rows(hound_id="u-2"))), 2)

    def test_no_personal_fields(self):
        blob = json.dumps(list(rr.bet_rows())) + json.dumps(rr.hound_records())
        self.assertNotIn("owner_user_id", blob)
        self.assertNotIn("email", blob)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class Routes(unittest.TestCase):
    def call(self, token, env):
        from fastapi import HTTPException
        from api import research_read as api
        with mock.patch.dict("os.environ", env, clear=False):
            try:
                api._gate(token)
                return 200
            except HTTPException as e:
                return e.status_code

    def test_404s_and_ok(self):
        self.assertEqual(self.call(SECRET, {rr.TOKEN_ENV: ""}), 404)
        self.assertEqual(self.call("bad", {rr.TOKEN_ENV: SECRET}), 404)
        self.assertEqual(self.call(None, {rr.TOKEN_ENV: SECRET}), 404)
        self.assertEqual(self.call(SECRET, {rr.TOKEN_ENV: SECRET}), 200)

    def test_headers(self):
        from api import research_read as api
        self.assertEqual(api._HEADERS["Cache-Control"], "no-store")
        self.assertEqual(api._HEADERS["X-Robots-Tag"], "noindex")

    def test_mounted(self):
        src = (Path(__file__).resolve().parent.parent / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(research_read_router)", src)


class Client(unittest.TestCase):
    def test_token_never_printed(self):
        with tempfile.TemporaryDirectory() as d:
            def fake(path, tok, base):
                return b'{"a":1}\n{"a":2}\n' if path.endswith("jsonl") else b'{"hounds":[{"x":1}]}'
            buf = io.StringIO()
            with redirect_stdout(buf), mock.patch.object(research_pull, "load_token", lambda: SECRET), \
                    mock.patch.object(research_pull, "pull", lambda t: _REAL_PULL(t, Path(d), fetcher=fake)):
                code = research_pull.main()
            self.assertEqual(code, 0)
            self.assertNotIn(SECRET, buf.getvalue())
            self.assertIn("2 bets", buf.getvalue())

    def test_failure_does_not_print_token(self):
        buf = io.StringIO()

        def boom(t):
            raise RuntimeError(t)
        with redirect_stdout(buf), mock.patch.object(research_pull, "load_token", lambda: SECRET), \
                mock.patch.object(research_pull, "pull", boom):
            self.assertEqual(research_pull.main(), 1)
        self.assertNotIn(SECRET, buf.getvalue())

    def test_token_from_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"
            f.write_text(f"{research_pull.ENV_NAME}={SECRET}\n")
            self.assertEqual(research_pull.load_token({}, f), SECRET)
            self.assertEqual(research_pull.load_token({}, Path(d) / "none"), "")


if __name__ == "__main__":
    unittest.main()
