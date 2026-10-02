"""The admin page's Testers section, run for real under node.

Owner decision (2026-10-02): the first 20 testers get 7 days of early access,
no card, granted by the owner himself from web/admin.html. This file runs the
real web/js/admin.js against a small fake DOM and a stubbed fetch (the pattern
of tests/test_admin_funnel_by_source.py) and pins what the page must do:

  * show "N of 20 granted, M remaining" from the server's numbers;
  * a form (email) with "Grant 7-day tester access"; after a grant, the token
    ONCE in a read-only box with a copy button, the expiry, and the line
    "Send this to them yourself; it is not stored and cannot be shown again.";
  * a table of testers (email, granted, expires, activated, extensions) with an
    "Extend 7 days" action that refuses to send without a typed reason;
  * a waitlisted user in the users list gets a "Grant tester access" shortcut
    that FILLS the form and sends nothing;
  * the token never reaches storage, a URL or the console, and is gone when
    the section is rebuilt.

Skipped when node is not installed.
"""

from __future__ import annotations

import json
import os
import re
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
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.listeners = {}; this.value = "";
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null; return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  focus() { globalThis.__focused = this; }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  byHook(name) { return this._all([]).filter((n) => n.attrs["data-hook"] === name); }
  one(name) { return this.byHook(name)[0] || null; }
}

const writes = { local: [], session: [] };
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  addEventListener() {}, querySelector: () => null,
};
globalThis.window = {
  sessionStorage: {
    getItem: () => "the-admin-token",
    setItem: (k, v) => writes.session.push([k, v]), removeItem() {},
  },
  localStorage: {
    getItem: () => null, setItem: (k, v) => writes.local.push([k, v]), removeItem() {},
  },
  location: { search: "", hash: "", pathname: "/web/admin.html", href: "http://x/web/admin.html" },
};
globalThis.sessionStorage = globalThis.window.sessionStorage;
globalThis.localStorage = globalThis.window.localStorage;

const logged = [];
for (const level of ["log", "info", "warn", "error", "debug"]) {
  console[level] = (...args) => logged.push(args.map(String).join(" "));
}
const copied = [];
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: { clipboard: { writeText: async (t) => { copied.push(t); } } },
});

const scenario = JSON.parse(process.env.SCENARIO);
const calls = [];
const queue = {};
for (const [key, list] of Object.entries(scenario.responses || {})) queue[key] = list.slice();
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || "GET";
  const key = method + " " + url;
  calls.push({ url: String(url), method, headers: (init && init.headers) || {},
               body: init && init.body ? JSON.parse(init.body) : null });
  const list = queue[key];
  if (!list || !list.length) throw new Error("unexpected request " + key);
  const step = list.length > 1 ? list.shift() : list[0];
  return { ok: step.status < 400, status: step.status, text: async () => JSON.stringify(step.body) };
};

const admin = await import("./admin.js");
const host = new Elem("div");
const usersHost = new Elem("div");
const press = async (node, event = {}) => {
  const fn = (node.listeners[event.type] || node.listeners.click || [])[0];
  await fn(Object.assign({ preventDefault() {} }, event));
};
const flat = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(flat).join(" "));
const snapshot = () => ({
  count: (host.one("admin-testers-count") || { textContent: null }).textContent,
  button: (host.one("admin-tester-grant") || { textContent: null }).textContent,
  formStatus: (host.one("admin-tester-form-status") || { textContent: null }).textContent,
  rows: host.byHook("admin-tester-row").map((r) => ({
    userId: r.attrs["data-user-id"], cells: r.children.map((c) => flat(c).trim().replace(/\s+/g, " ")),
    expires: r.one("admin-tester-expires").textContent,
    activated: r.one("admin-tester-activated").textContent,
    extendLabel: r.one("admin-tester-extend").textContent,
  })),
  empty: host.byHook("admin-testers-empty").length,
  result: host.one("admin-tester-result") ? {
    summary: host.one("admin-tester-result-summary").textContent,
    tokenValue: host.one("admin-tester-token").attrs.value,
    tokenReadonly: "readonly" in host.one("admin-tester-token").attrs,
    copyLabel: host.one("admin-tester-copy").textContent,
    note: host.one("admin-tester-token-note").textContent,
  } : null,
  authError: host.byHook("admin-auth-error").length + host.byHook("admin-auth-invalid").length,
});

const out = {};
await admin.mountTesters(host);
if (scenario.kind === "render") {
  out.snap = snapshot();
} else if (scenario.kind === "grant") {
  host.one("admin-tester-email").value = scenario.email;
  await press(host.one("admin-tester-form"), { type: "submit" });
  out.snap = snapshot();
  if (scenario.copy) { await press(host.one("admin-tester-copy")); out.afterCopy = snapshot().result; }
  if (scenario.rebuild) { await admin.mountTesters(host); out.rebuilt = snapshot(); }
} else if (scenario.kind === "extend") {
  const row = host.byHook("admin-tester-row")[scenario.row || 0];
  if (scenario.reason !== undefined) row.one("admin-tester-reason").value = scenario.reason;
  await press(row.one("admin-tester-extend"));
  out.snap = snapshot();
  out.rowStatus = row.one("admin-tester-extend-status").textContent;
} else if (scenario.kind === "shortcut") {
  admin.renderUsers(usersHost, scenario.users);
  const rows = usersHost.byHook("admin-user-row");
  out.shortcuts = rows.map((r) => ({
    userId: r.attrs["data-user-id"], hasButton: r.byHook("admin-user-grant-tester").length,
    testerCell: r.one("admin-user-tester").textContent,
  }));
  const button = usersHost.byHook("admin-user-grant-tester")[0];
  if (button) await press(button);
  out.filled = host.one("admin-tester-email").value;
  out.formStatus = host.one("admin-tester-form-status").textContent;
  out.focusedEmail = globalThis.__focused === host.one("admin-tester-email");
}
out.calls = calls;
out.writes = writes;
out.logged = logged;
out.copied = copied;
process.stdout.write("@@" + JSON.stringify(out) + "\n");
"""

TESTERS = {
    "granted": 3, "limit": 20, "remaining": 17, "ttl_days": 7,
    "testers": [
        {"user_id": 11, "email": "ann@example.com", "status": "invited",
         "granted_at": "2026-10-05T12:00:00+00:00", "expires_at": "2026-10-19T09:30:00+00:00",
         "first_used_at": "2026-10-05T13:00:00+00:00", "activated": True,
         "extensions": [{"extended_at": "2026-10-12T09:30:00+00:00",
                         "expires_at": "2026-10-19T09:30:00+00:00",
                         "reason": "filed three specific bugs"}]},
        {"user_id": 12, "email": "bo@example.com", "status": "invited",
         "granted_at": "2026-10-06T08:15:00+00:00", "expires_at": "2026-10-13T08:15:00+00:00",
         "first_used_at": None, "activated": False, "extensions": []},
        {"user_id": 13, "email": "cy@example.com", "status": "invited",
         "granted_at": "2026-10-07T08:15:00+00:00", "expires_at": "2026-10-14T08:15:00+00:00",
         "first_used_at": None, "activated": False, "extensions": []},
    ],
}
SECRET = "tok_SECRET_value_that_must_never_leak_0123456789"
GRANTED = {"user_id": 14, "email": "dee@example.com", "token": SECRET,
           "expires_at": "2026-10-14T16:45:00+00:00", "testers_granted": 4, "testers_limit": 20}
AFTER_GRANT = dict(TESTERS, granted=4, remaining=16)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class AdminTestersSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="admin_testers_")
        shutil.copytree(JS, Path(cls.tmp) / "js")
        (Path(cls.tmp) / "js" / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (Path(cls.tmp) / "js" / "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_page(self, **scenario):
        scenario.setdefault("responses", {})
        scenario["responses"].setdefault("GET /admin/testers", [{"status": 200, "body": TESTERS}])
        done = subprocess.run(["node", "harness.mjs"], cwd=Path(self.tmp) / "js",
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        line = [ln for ln in done.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- the list ------------------------------------------------------------

    def test_it_shows_how_many_of_twenty_are_granted_from_the_servers_numbers(self):
        snap = self.run_page(kind="render")["snap"]
        self.assertEqual(snap["count"], "3 of 20 granted, 17 remaining")
        other = dict(TESTERS, granted=20, remaining=0)
        snap = self.run_page(kind="render", responses={"GET /admin/testers": [
            {"status": 200, "body": other}]})["snap"]
        self.assertEqual(snap["count"], "20 of 20 granted, 0 remaining")

    def test_the_form_button_is_the_seven_day_grant_and_the_days_come_from_the_server(self):
        self.assertEqual(self.run_page(kind="render")["snap"]["button"],
                         "Grant 7-day tester access")
        other = dict(TESTERS, ttl_days=3)
        snap = self.run_page(kind="render", responses={"GET /admin/testers": [
            {"status": 200, "body": other}]})["snap"]
        self.assertEqual(snap["button"], "Grant 3-day tester access")
        self.assertEqual(snap["rows"][0]["extendLabel"], "Extend 3 days")

    def test_the_table_has_email_granted_expires_activated_extensions_and_an_extend_action(self):
        rows = self.run_page(kind="render")["snap"]["rows"]
        self.assertEqual([r["userId"] for r in rows], ["11", "12", "13"])
        ann, bo = rows[0], rows[1]
        self.assertEqual(ann["cells"][0], "ann@example.com")
        self.assertEqual(ann["cells"][1], "2026-10-05 12:00 UTC")
        self.assertEqual(ann["expires"], "2026-10-19 09:30 UTC")
        self.assertEqual(ann["activated"], "yes")
        self.assertEqual(ann["cells"][4], "2026-10-12 09:30 UTC: filed three specific bugs")
        self.assertEqual(bo["activated"], "no")
        self.assertEqual(bo["cells"][4], "—")
        self.assertEqual(ann["extendLabel"], "Extend 7 days")

    def test_an_empty_list_says_so(self):
        empty = {"granted": 0, "limit": 20, "remaining": 20, "ttl_days": 7, "testers": []}
        snap = self.run_page(kind="render", responses={"GET /admin/testers": [
            {"status": 200, "body": empty}]})["snap"]
        self.assertEqual(snap["empty"], 1)
        self.assertEqual(snap["count"], "0 of 20 granted, 20 remaining")

    def test_a_failed_load_renders_the_error_state_not_a_blank_section(self):
        snap = self.run_page(kind="render", responses={"GET /admin/testers": [
            {"status": 500, "body": {"detail": "boom"}}]})["snap"]
        self.assertEqual(snap["authError"], 1)
        self.assertIsNone(snap["button"], "no form is offered when the list could not load")

    # ---- granting --------------------------------------------------------------

    def _grant(self, **extra):
        responses = {"POST /admin/testers": [{"status": 200, "body": GRANTED}],
                     "GET /admin/testers": [{"status": 200, "body": TESTERS},
                                            {"status": 200, "body": AFTER_GRANT}]}
        return self.run_page(kind="grant", email="  Dee@Example.com ", responses=responses, **extra)

    def test_a_grant_posts_the_email_with_the_admin_header_and_reloads_the_count(self):
        out = self._grant()
        post = [c for c in out["calls"] if c["method"] == "POST"][0]
        self.assertEqual(post["url"], "/admin/testers")
        self.assertEqual(post["body"], {"email": "Dee@Example.com"})
        self.assertEqual(post["headers"]["X-Admin-Token"], "the-admin-token")
        self.assertEqual(out["snap"]["count"], "4 of 20 granted, 16 remaining")

    def test_the_token_is_shown_once_in_a_read_only_box_with_copy_expiry_and_the_warning(self):
        result = self._grant()["snap"]["result"]
        self.assertEqual(result["tokenValue"], SECRET)
        self.assertTrue(result["tokenReadonly"])
        self.assertEqual(result["copyLabel"], "Copy")
        self.assertIn("dee@example.com", result["summary"])
        self.assertIn("2026-10-14 16:45 UTC", result["summary"])
        self.assertEqual(result["note"],
                         "Send this to them yourself; it is not stored and cannot be shown again.")

    def test_copy_puts_the_token_on_the_clipboard_and_nowhere_else(self):
        out = self._grant(copy=True)
        self.assertEqual(out["copied"], [SECRET])
        self.assertEqual(out["afterCopy"]["copyLabel"], "Copied")

    def test_the_token_never_reaches_storage_a_url_or_the_console(self):
        out = self._grant(copy=True)
        self.assertEqual(out["writes"], {"local": [], "session": []})
        for call in out["calls"]:
            self.assertNotIn(SECRET, call["url"])
            self.assertNotIn(SECRET, json.dumps(call["headers"]))
            if call["body"]:
                self.assertNotIn(SECRET, json.dumps(call["body"]))
        self.assertNotIn(SECRET, "\n".join(out["logged"]))

    def test_the_token_is_gone_when_the_section_is_rebuilt(self):
        out = self._grant(rebuild=True)
        self.assertIsNotNone(out["snap"]["result"])
        self.assertIsNone(out["rebuilt"]["result"])
        self.assertNotIn(SECRET, json.dumps(out["rebuilt"]))

    def test_a_refusal_shows_the_servers_words_and_no_token_box(self):
        message = "20 of 20 tester slots are already granted; nothing was written"
        out = self.run_page(kind="grant", email="late@example.com", responses={
            "POST /admin/testers": [{"status": 409, "body": {"detail": {
                "error": "tester_limit_reached", "message": message,
                "testers_granted": 20, "testers_limit": 20}}}]})
        self.assertEqual(out["snap"]["formStatus"], message)
        self.assertIsNone(out["snap"]["result"])

    def test_a_wrong_admin_token_says_so(self):
        out = self.run_page(kind="grant", email="a@example.com", responses={
            "POST /admin/testers": [{"status": 401, "body": {"detail": {
                "error": "unauthorized", "message": "invalid admin token"}}}]})
        self.assertIn("admin token was rejected", out["snap"]["formStatus"])

    def test_an_empty_email_sends_nothing(self):
        out = self.run_page(kind="grant", email="   ")
        self.assertEqual([c for c in out["calls"] if c["method"] == "POST"], [])
        self.assertEqual(out["snap"]["formStatus"], "Enter an email.")

    # ---- extending ---------------------------------------------------------------

    def test_extend_without_a_typed_reason_sends_nothing(self):
        for reason in (None, "", "    "):
            with self.subTest(reason=reason):
                scenario = {"kind": "extend"}
                if reason is not None:
                    scenario["reason"] = reason
                out = self.run_page(**scenario)
                self.assertEqual([c for c in out["calls"] if c["method"] == "POST"], [])
                self.assertIn("reason", out["rowStatus"])
                self.assertIsNone(out["snap"]["result"])

    def test_extend_with_a_reason_posts_it_and_shows_the_new_token_once(self):
        issued = dict(GRANTED, user_id=12, email="bo@example.com", extension_number=1)
        out = self.run_page(kind="extend", row=1, reason="  sent a screen recording  ", responses={
            "POST /admin/testers/extend": [{"status": 200, "body": issued}]})
        post = [c for c in out["calls"] if c["method"] == "POST"][0]
        self.assertEqual(post["url"], "/admin/testers/extend")
        self.assertEqual(post["body"], {"user_id": 12, "reason": "sent a screen recording"})
        self.assertEqual(out["snap"]["result"]["tokenValue"], SECRET)
        self.assertIn("bo@example.com", out["snap"]["result"]["summary"])
        self.assertEqual(out["writes"], {"local": [], "session": []})
        self.assertNotIn(SECRET, "\n".join(out["logged"]))

    def test_an_extension_refusal_is_shown_on_its_row(self):
        out = self.run_page(kind="extend", row=0, reason="x", responses={
            "POST /admin/testers/extend": [{"status": 409, "body": {"detail": {
                "error": "user_suspended", "message": "this account is suspended"}}}]})
        self.assertEqual(out["rowStatus"], "this account is suspended")
        self.assertIsNone(out["snap"]["result"])

    # ---- the users-list shortcut -----------------------------------------------

    USERS = [
        {"id": 1, "email": "wait@example.com", "status": "waitlisted", "plan": "none",
         "created_at": "2026-10-04T10:00:00+00:00", "tester": False,
         "tester_granted_at": None, "tester_expires_at": None},
        {"id": 2, "email": "inv@example.com", "status": "invited", "plan": "none",
         "created_at": "2026-10-04T10:00:00+00:00", "tester": False,
         "tester_granted_at": None, "tester_expires_at": None},
        {"id": 3, "email": "ann@example.com", "status": "invited", "plan": "none",
         "created_at": "2026-10-04T10:00:00+00:00", "tester": True,
         "tester_granted_at": "2026-10-05T12:00:00+00:00",
         "tester_expires_at": "2026-10-19T09:30:00+00:00"},
    ]

    def test_only_a_waitlisted_non_tester_gets_the_shortcut_and_it_fills_the_form(self):
        out = self.run_page(kind="shortcut", users=self.USERS)
        self.assertEqual([(s["userId"], s["hasButton"]) for s in out["shortcuts"]],
                         [("1", 1), ("2", 0), ("3", 0)])
        self.assertEqual(out["shortcuts"][2]["testerCell"], "until 2026-10-19 09:30 UTC")
        self.assertEqual(out["shortcuts"][0]["testerCell"], "no")
        self.assertEqual(out["filled"], "wait@example.com")
        self.assertIn("wait@example.com", out["formStatus"])
        self.assertTrue(out["focusedEmail"])

    def test_the_shortcut_fills_the_form_and_sends_nothing(self):
        out = self.run_page(kind="shortcut", users=self.USERS)
        self.assertEqual([c for c in out["calls"] if c["method"] == "POST"], [])

    # ---- structure ---------------------------------------------------------------

    def test_the_html_has_a_hidden_testers_section_with_a_host(self):
        html = (ROOT / "web" / "admin.html").read_text(encoding="utf-8")
        section = re.search(r'<section[^>]*data-hook="admin-testers-section"[^>]*>(.*?)</section>',
                            html, re.S)
        self.assertIsNotNone(section)
        self.assertRegex(section.group(0).split(">")[0], r"\bhidden\b")
        self.assertIn('data-hook="admin-testers-host"', section.group(1))
        self.assertIn("<h2>Testers</h2>", section.group(1))

    def test_admin_js_keeps_its_token_rules(self):
        js = (JS / "admin.js").read_text(encoding="utf-8")
        self.assertNotIn("window.localStorage", js)
        self.assertNotIn("console.", js)
        self.assertNotRegex(js, r"\$\{[^}]*[Tt]oken[^}]*\}")
        self.assertNotRegex(js, r"[?&]token=")


if __name__ == "__main__":
    unittest.main()
