"""The admin page shows which outreach link each signup came from.

GET /admin/funnel has carried `by_source` (utm_source -> {step: count}) since
every outreach link got its own source, and web/js/admin.js never drew it:
the answer to "did anyone from that server sign up" was in the API and
nowhere on screen. The real module is run under node against a small fake
DOM (the pattern of tests/test_checkout_copy_states.py).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) { this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {}; this.childNodes = []; this.parentNode = null; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener() {}
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  byHook(name) { return this._all([]).filter((n) => n.attrs["data-hook"] === name); }
}
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  addEventListener() {},
  querySelector: () => null,
};
globalThis.window = { sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
                      location: { search: "", hash: "", pathname: "/" } };
globalThis.sessionStorage = globalThis.window.sessionStorage;

const { renderFunnel } = await import("./admin.js");
const host = new Elem("div");
renderFunnel(host, JSON.parse(process.env.FUNNEL));
const cells = (row) => row.children.map((c) => c.textContent);
const table = host.byHook("admin-funnel-by-source-table")[0] || null;
console.log("@@" + JSON.stringify({
  steps: host.byHook("admin-funnel-step").length,
  header: table ? cells(table.children[0].children[0]) : null,
  rows: host.byHook("admin-funnel-source").map(cells),
  empty: host.byHook("admin-funnel-by-source-empty").map((n) => n.textContent),
  sampleHeader: host.byHook("admin-funnel-sample-table").map((t) => cells(t.children[0].children[0]))[0] || null,
  sampleRows: host.byHook("admin-funnel-sample-source").map(cells),
  sampleTotal: host.byHook("admin-funnel-sample-total").map(cells)[0] || null,
}));
"""

STEPS = [{"kind": "landing_view", "count": 12, "conversion_pct_from_previous": None},
         {"kind": "account_created", "count": 2, "conversion_pct_from_previous": 16.7}]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class AdminFunnelBySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="admin_funnel_")
        shutil.copytree(JS, Path(cls.tmp) / "js")
        (Path(cls.tmp) / "js" / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (Path(cls.tmp) / "js" / "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _render(self, funnel):
        env = dict(os.environ, FUNNEL=json.dumps(funnel))
        done = subprocess.run(["node", "harness.mjs"], cwd=Path(self.tmp) / "js", env=env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        line = [ln for ln in done.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def test_each_source_gets_a_row_with_its_own_counts(self):
        out = self._render({"start": "2026-10-01", "end": "2026-10-07", "steps": STEPS, "by_source": {
            "discord_unit_circle": {"landing_view": 9, "account_created": 2},
            "(direct)": {"landing_view": 3, "account_created": 0},
        }})
        self.assertEqual(out["steps"], 2)
        self.assertEqual(out["header"], ["Source", "landing_view", "account_created"])
        self.assertEqual(out["rows"], [["discord_unit_circle", "9", "2"], ["(direct)", "3", "0"]])
        self.assertEqual(out["empty"], [])

    def test_a_step_one_source_never_reached_reads_zero_not_blank(self):
        out = self._render({"start": "a", "end": "b", "steps": STEPS, "by_source": {
            "x_reply": {"landing_view": 4},
            "forum_covers": {"landing_view": 1, "account_created": 1},
        }})
        self.assertEqual(out["header"], ["Source", "landing_view", "account_created"])
        self.assertEqual(out["rows"], [["x_reply", "4", "0"], ["forum_covers", "1", "1"]])

    def test_no_attributed_events_says_so_and_an_old_payload_does_not_break_the_page(self):
        for funnel in ({"start": "a", "end": "b", "steps": STEPS, "by_source": {}},
                       {"start": "a", "end": "b", "steps": STEPS}):
            out = self._render(funnel)
            self.assertEqual(out["steps"], 2)
            self.assertIsNone(out["header"])
            self.assertEqual(out["empty"], ["No attributed events in this range."])

    def test_sample_views_sit_beside_the_same_sources_signups(self):
        # api/funnel.py's page_views.sample (internal links already left out) next to by_source
        out = self._render({"start": "a", "end": "b", "steps": STEPS, "by_source": {
            "l009-tommy-lorenzo": {"landing_view": 0, "signup_started": 1, "account_created": 1},
            "l012-unit-circle": {"landing_view": 0, "signup_started": 0, "account_created": 0},
        }, "page_views": {"sample": {"views": 5, "unique_visitors": 3, "by_source": {
            "l009-tommy-lorenzo": {"views": 4, "unique_visitors": 2},
            "l012-unit-circle": {"views": 1, "unique_visitors": 1},
        }}, "record-card": {"views": 9, "unique_visitors": 9, "by_source": {}}}})
        self.assertEqual(out["sampleHeader"], ["Source", "Sample views", "Unique visitors",
                                               "Signups started (any page)", "Accounts created (any page)"])
        self.assertEqual(out["sampleRows"], [["l009-tommy-lorenzo", "4", "2", "1", "1"],
                                             ["l012-unit-circle", "1", "1", "0", "0"]])
        self.assertEqual(out["sampleTotal"], ["All sources", "5", "3", "", ""])

    def test_no_sample_block_draws_no_sample_table(self):
        for page_views in (None, {}, {"record-card": {"views": 1, "unique_visitors": 1, "by_source": {}}}):
            funnel = {"start": "a", "end": "b", "steps": STEPS, "by_source": {}}
            if page_views is not None:
                funnel["page_views"] = page_views
            out = self._render(funnel)
            self.assertIsNone(out["sampleHeader"])
            self.assertEqual(out["sampleRows"], [])


if __name__ == "__main__":
    unittest.main()
