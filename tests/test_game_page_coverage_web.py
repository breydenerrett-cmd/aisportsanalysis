"""The game page's store-age labels read `advanced.data_coverage`, never the dossier.

Server half: tests/test_stale_data_surfaces.py (`coverage_for_game`, the route,
the day after a league-wide off day). This is the page half. The labels were
first written against dossier fields (`teams.results_stale`,
`starters.logs_stale`, a bullpen workload's `log_stale`); a dossier section is
a model and ledger input and the fields were read off the newest GAME, so they
moved out to a display block the game route attaches beside the dossier:

    advanced.data_coverage = {results|pitcher_logs|bullpen_log: {through, stale}}

Two halves, the pattern of tests/test_matchup_read_web.py:
  * static: the page no longer reads a dossier label, and does read the block;
  * behavioural: the real gamestory.js and games.js under node against a small
    fake DOM. games.js keeps its renderers private, so the harness appends an
    export line to a COPY of the file (the shipped file is not modified). Skipped
    when node is missing. It checks what a person would see: the chips, the
    sentence under a bullpen with no rows, the days-rest note and the record's
    "results end ..." suffix, with the block present, fresh, stale and absent,
    and with an old-style dossier label present to prove the page ignores it.
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
GAMES_JS = (JS / "games.js").read_text(encoding="utf-8")
STORY_JS = (JS / "gamestory.js").read_text(encoding="utf-8")

DOSSIER_LABELS = ("results_stale", "results_through", "logs_stale", "logs_through",
                  "log_stale", "log_through")


class ThePageReadsTheDisplayBlockAndNoDossierLabel(unittest.TestCase):

    def test_neither_module_reads_a_label_from_a_dossier_section(self):
        for name, source in (("games.js", GAMES_JS), ("gamestory.js", STORY_JS)):
            for label in DOSSIER_LABELS:
                self.assertNotIn(label, source, f"{name} still reads {label}")

    def test_both_modules_read_the_block_the_route_attaches(self):
        self.assertIn("advanced.data_coverage", GAMES_JS)
        self.assertIn("advanced.data_coverage", STORY_JS)

    def test_the_call_sites_games_js_is_pinned_to_are_unchanged(self):
        # tests/test_matchup_read_web.py orders the page by these exact strings.
        for call in ("renderGameStory(advanced, quick)", "gqvTeams(advanced, quick)"):
            self.assertIn(call, GAMES_JS)


HARNESS = r"""
import fs from "node:fs";
class TextNode { constructor(t){ this.nodeType=3; this.textContent=String(t); this.parentNode=null; } }
class Elem { constructor(tag){ this.nodeType=1; this.tagName=String(tag).toUpperCase(); this.attrs={}; this.childNodes=[]; this.parentNode=null; this.style={}; }
  get children(){ return this.childNodes.filter(c=>c.nodeType===1); }
  appendChild(c){ if(c.parentNode) c.parentNode.removeChild(c); c.parentNode=this; this.childNodes.push(c); return c; }
  removeChild(c){ const i=this.childNodes.indexOf(c); if(i>=0) this.childNodes.splice(i,1); c.parentNode=null; return c; }
  setAttribute(k,v){ this.attrs[k]=String(v); } getAttribute(k){ return k in this.attrs?this.attrs[k]:null; }
  set hidden(v){ if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden(){ return "hidden" in this.attrs; }
  set textContent(v){ const t=new TextNode(v); t.parentNode=this; this.childNodes=[t]; }
  get textContent(){ return this.childNodes.map(c=>c.textContent).join(""); }
  get classList(){ const s=this; return { add(c){ s.attrs.class=((s.attrs.class||"")+" "+c).trim(); }, remove(){} }; }
  addEventListener(){} _all(out){ for(const c of this.children){ out.push(c); c._all(out);} return out; } }
globalThis.document = { createElement:(t)=>new Elem(t), createTextNode:(t)=>new TextNode(t), body:new Elem("body"), referrer:"", addEventListener(){}, querySelector:()=>null, querySelectorAll:()=>[] };
const store = new Map();
globalThis.window = { localStorage:{ getItem:k=>store.has(k)?store.get(k):null, setItem:(k,v)=>store.set(k,String(v)), removeItem:k=>store.delete(k) }, location:{search:"",host:"linehound.test",pathname:"/",hash:""}, history:{replaceState(){}}, addEventListener(){}, dispatchEvent(){return true;}, crypto: globalThis.crypto };
globalThis.fetch = async()=>({ok:true,status:200,text:async()=>"{}"});

// games.js keeps its renderers private: test a COPY that also exports them.
fs.writeFileSync("./games_under_test.js",
  fs.readFileSync("./games.js", "utf8") + "\nexport { gqvIdentity, gqvTeams };\n");
const games = await import("./games_under_test.js");
const story = await import("./gamestory.js");

const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const byClass = (node, cls) => node._all([]).filter((n) => (n.attrs.class || "").split(" ").includes(cls));
const texts = (node, cls) => byClass(node, cls).map((n) => n.textContent);

const scenario = JSON.parse(process.env.SCENARIO);
const out = [];
for (const c of scenario.cases) {
  let node = null;
  if (c.kind === "story") node = story.renderGameStory(c.advanced, c.quick);
  else if (c.kind === "teams") node = games.gqvTeams(c.advanced, c.quick);
  else if (c.kind === "identity") node = games.gqvIdentity(c.quick, c.advanced);
  out.push(node === null ? null : {
    chips: texts(node, "pv-chip--warn"),
    notes: texts(node, "gs-note"),
    facts: byClass(node, "gs-fact").map((n) => text(n)),
    cellSamples: texts(node, "gqv-stat__n"),
    teamSamples: texts(node, "gqv-team__n"),
    text: text(node),
  });
}
console.log("@@" + JSON.stringify(out));
"""

QUICK = {"away_team": "NYY", "home_team": "BOS"}


def _starters(**extra):
    out = {"both_sp_known": True}
    for side, era in (("away", 3.2), ("home", 4.1)):
        out.update({f"{side}_sp_known": True, f"{side}_sp_thin": False, f"{side}_sp_starts": 30,
                    f"{side}_sp_era": era, f"{side}_sp_fip": 3.5, f"{side}_sp_whip": 1.1,
                    f"{side}_sp_k9": 9.0, f"{side}_sp_ip_per_start": 6.0, f"{side}_sp_days_rest": 6})
    out.update(extra)
    return out


def _bullpen(**extra):
    row = {"team": "NYY", "as_of": "2026-10-03", "window_days": 7, "relievers": [],
           "total_innings": 0.0, "reliever_count": 0}
    row.update(extra)
    return {"NYY": dict(row), "BOS": dict(row, team="BOS")}


def _teams(**extra):
    out = {}
    for side in ("away", "home"):
        out.update({f"{side}_games_played": 150, f"{side}_wins": 90, f"{side}_losses": 60,
                    f"{side}_win_pct": 0.6, f"{side}_runs_scored_pg": 4.8,
                    f"{side}_runs_allowed_pg": 4.1})
    out.update(extra)
    return out


def _advanced(sections, coverage="absent"):
    advanced = {"sections": sections, "gaps": {}, "game": {"away_team": "NYY", "home_team": "BOS"}}
    if coverage != "absent":
        advanced["data_coverage"] = coverage
    return advanced


def _block(**stores):
    return {key: {"through": through, "stale": stale} for key, (through, stale) in stores.items()}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheLabelsRenderUnderNode(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def render(self, *cases):
        env = dict(os.environ, SCENARIO=json.dumps({"cases": list(cases)}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # -- the starters panel -----------------------------------------------

    def story(self, sections, coverage="absent"):
        return {"kind": "story", "advanced": _advanced(sections, coverage), "quick": QUICK}

    def test_a_pitcher_log_that_ends_early_is_labelled_on_both_starters(self):
        out = self.render(self.story({"starters": _starters()},
                                     _block(pitcher_logs=("2026-09-07", True))))[0]
        self.assertEqual(out["chips"].count("PITCHER LOG ENDS SEPT 7"), 2, out["chips"])
        self.assertTrue(any("counted from the log, which ends Sept 7" in f for f in out["facts"]), out["facts"])

    def test_a_log_refreshed_this_morning_has_no_label_and_a_plain_days_rest(self):
        out = self.render(self.story({"starters": _starters()},
                                     _block(pitcher_logs=("2026-10-03", False))))[0]
        self.assertEqual([c for c in out["chips"] if "PITCHER LOG" in c], [])
        rest = [f for f in out["facts"] if f.startswith("DAYS REST")]
        self.assertEqual(len(rest), 2)
        self.assertTrue(all("counted from the log" not in f for f in rest), rest)

    def test_no_block_means_no_label_not_a_guess(self):
        out = self.render(self.story({"starters": _starters()}))[0]
        self.assertEqual([c for c in out["chips"] if "PITCHER LOG" in c], [])

    def test_an_unknown_end_date_says_so(self):
        out = self.render(self.story({"starters": _starters()},
                                     _block(pitcher_logs=(None, True))))[0]
        self.assertEqual(out["chips"].count("PITCHER LOG DATE UNKNOWN"), 2, out["chips"])

    def test_a_dossier_label_is_ignored_the_block_decides(self):
        # An old-style label inside the section says "stale"; the block, which
        # reads coverage, says the log was refreshed this morning. The page
        # believes the block.
        section = _starters(logs_stale=True, logs_through="2026-09-07")
        out = self.render(self.story({"starters": section},
                                     _block(pitcher_logs=("2026-10-03", False))))[0]
        self.assertEqual([c for c in out["chips"] if "PITCHER LOG" in c], [])

    # -- the bullpen panel -------------------------------------------------

    def test_a_bullpen_log_that_ends_early_never_says_no_relief_appearances(self):
        out = self.render(self.story({"bullpen": _bullpen()},
                                     _block(bullpen_log=("2026-09-06", True))))[0]
        self.assertEqual(out["chips"].count("BULLPEN LOG ENDS SEPT 6"), 2, out["chips"])
        self.assertIn("The bullpen log ends Sept 6; games since then are not in it, "
                      "so recent relief use is unknown.", out["notes"])
        self.assertFalse([n for n in out["notes"] if n.startswith("No relief appearances")])

    def test_a_current_bullpen_log_with_no_rows_is_a_real_rested_pen(self):
        out = self.render(self.story({"bullpen": _bullpen()},
                                     _block(bullpen_log=("2026-10-02", False))))[0]
        self.assertEqual([c for c in out["chips"] if "BULLPEN" in c], [])
        self.assertTrue([n for n in out["notes"] if n.startswith("No relief appearances")], out["notes"])

    def test_a_bullpen_dossier_label_is_ignored(self):
        out = self.render(self.story({"bullpen": _bullpen(log_stale=True, log_through="2026-09-06")},
                                     _block(bullpen_log=("2026-10-02", False))))[0]
        self.assertEqual([c for c in out["chips"] if "BULLPEN" in c], [])

    # -- the record --------------------------------------------------------

    def test_a_results_store_that_ends_early_dates_the_record(self):
        advanced = _advanced({"teams": _teams()}, _block(results=("2026-09-23", True)))
        teams, identity = self.render({"kind": "teams", "advanced": advanced, "quick": QUICK},
                                      {"kind": "identity", "advanced": advanced, "quick": QUICK})
        suffix = "150 games · results end Sept 23"
        self.assertIn(suffix, teams["cellSamples"])
        self.assertEqual(identity["teamSamples"], [suffix, suffix])

    def test_the_day_after_an_off_day_the_record_carries_no_suffix(self):
        advanced = _advanced({"teams": _teams()}, _block(results=("2026-10-03", False)))
        teams, identity = self.render({"kind": "teams", "advanced": advanced, "quick": QUICK},
                                      {"kind": "identity", "advanced": advanced, "quick": QUICK})
        self.assertNotIn("results end", teams["text"])
        self.assertEqual(identity["teamSamples"], ["150 games", "150 games"])

    def test_the_teams_dossier_label_is_ignored(self):
        advanced = _advanced({"teams": _teams(results_stale=True, results_through="2026-10-02")},
                             _block(results=("2026-10-03", False)))
        out = self.render({"kind": "teams", "advanced": advanced, "quick": QUICK})[0]
        self.assertNotIn("results end", out["text"])

    def test_no_block_no_suffix(self):
        advanced = _advanced({"teams": _teams()})
        out = self.render({"kind": "teams", "advanced": advanced, "quick": QUICK})[0]
        self.assertNotIn("results end", out["text"])
        self.assertIn("150 games", out["cellSamples"])


if __name__ == "__main__":
    unittest.main()
