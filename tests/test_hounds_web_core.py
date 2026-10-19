"""The pure half of the Hounds pages: ordering, chart geometry, series shapes, the poller, the rule preview.

Runs web/js/hounds-core.js under node (no DOM needed for these); skipped when node is not installed.
The pages themselves are exercised in tests/test_hounds_web_pages.py.
"""

from __future__ import annotations

import json
import unittest

from tests.hounds_web_runner import HAS_NODE, run_js


def js(body: str):
    """Run `body` as an ES module with the core helpers imported; it must console.log(JSON)."""
    return run_js('import * as C from "./hounds-core.js";\n' + body)


def mk(hid, name, verdict, bets=10, units=0.0, kind="house", category="stats"):
    return {"id": hid, "name": name, "kind": kind, "category": category, "verdict": {"label": verdict, "sentence": "s"},
            "record": {"bets": bets, "units_average_price": units, "units_recorded_price": units}}


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheOrderIsTheVerdictNeverTheUnits(unittest.TestCase):
    def order(self, hounds):
        return js(f"console.log(JSON.stringify(C.sortByVerdict({json.dumps(hounds)}).map(h => h.id)));")

    def test_verdict_rank_beats_units_in_every_direction(self):
        hounds = [
            mk("vig-rich", "A", "PAYING THE VIG", units=+90.0),
            mk("early-rich", "B", "TOO EARLY", units=+40.0),
            mk("flat-rich", "C", "NO DIFFERENT FROM THE MARKET", units=+20.0),
            mk("beat-poor", "D", "BEATING THE CLOSE", units=-30.0),
        ]
        self.assertEqual(self.order(hounds), ["beat-poor", "flat-rich", "early-rich", "vig-rich"])

    def test_inside_a_verdict_more_bets_first_then_name_and_units_do_not_matter(self):
        hounds = [
            mk("small-rich", "Zed", "TOO EARLY", bets=5, units=+50.0),
            mk("big-poor", "Yak", "TOO EARLY", bets=50, units=-50.0),
            mk("tie-b", "Bee", "TOO EARLY", bets=20, units=0.0),
            mk("tie-a", "Ant", "TOO EARLY", bets=20, units=+9.0),
        ]
        self.assertEqual(self.order(hounds), ["big-poor", "tie-a", "tie-b", "small-rich"])

    def test_an_unknown_or_missing_verdict_sorts_after_every_known_one(self):
        hounds = [mk("x", "X", "SOMETHING NEW"), {"id": "none", "name": "N", "record": {"bets": 99}},
                  mk("vig", "V", "PAYING THE VIG")]
        # both unknowns share the last rank, so the sample-size tiebreak (99 bets before 10) orders them
        self.assertEqual(self.order(hounds), ["vig", "none", "x"])

    def test_the_input_is_not_mutated(self):
        out = js("const a=[{id:'b',name:'B',verdict:{label:'TOO EARLY'}},{id:'a',name:'A',verdict:{label:'BEATING THE CLOSE'}}];"
                 "C.sortByVerdict(a); console.log(JSON.stringify(a.map(h=>h.id)));")
        self.assertEqual(out, ["b", "a"])

    def test_filters_and_the_baseline_split(self):
        hs = [mk("h", "H", "TOO EARLY"), mk("u", "U", "TOO EARLY", kind="user"),
              mk("b", "B", "PAYING THE VIG", category="baseline")]
        out = js(f"const hs={json.dumps(hs)};"
                 "console.log(JSON.stringify({house:C.filterHounds(hs,'house').map(h=>h.id),"
                 "user:C.filterHounds(hs,'user').map(h=>h.id),cat:C.filterHounds(hs,'all','baseline').map(h=>h.id),"
                 "split:{race:C.splitBaselines(hs).race.map(h=>h.id),base:C.splitBaselines(hs).baselines.map(h=>h.id)},"
                 "present:C.presentCategories(hs)}));")
        self.assertEqual(out["house"], ["h", "b"])
        self.assertEqual(out["user"], ["u"])
        self.assertEqual(out["cat"], ["b"])
        self.assertEqual(out["split"], {"race": ["h", "u"], "base": ["b"]})
        self.assertEqual(out["present"], ["stats"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheBadgesFollowTheCategory(unittest.TestCase):
    def test_colour_by_category_with_a_name_hash_fallback_and_eight_fallback_colours(self):
        out = js("console.log(JSON.stringify({a:C.categoryColor('Closer','stats'),b:C.categoryColor('Other','stats'),"
                 "c:C.categoryColor('Closer','esoteric'),fallback:C.categoryColor('Closer',''),"
                 "same:C.categoryColor('Closer','')===C.categoryColor('Closer',''),n:C.AVATAR_COLORS.length,"
                 "hound:C.houndColor({name:'Closer',category:'stats'})}));")
        self.assertEqual(out["a"], out["b"])
        self.assertEqual(out["hound"], out["a"])
        self.assertNotEqual(out["a"], out["c"])
        self.assertIn(out["fallback"], ["#6E9BFF", "#E0A458", "#5CC8B5", "#B58CFF", "#78B8D8", "#C9A66B", "#8FA3C0", "#D68FB3"])
        self.assertTrue(out["same"])
        self.assertEqual(out["n"], 8)

    def test_initials_are_two_letters_and_the_cartoon_dog_is_gone_from_the_module(self):
        out = js("console.log(JSON.stringify({i:['Steamy Setter','Pointer','Coin-Flip Collie','The Desk','',null].map(C.initialsOf),"
                 "avatar: typeof C.avatarSvg, vibe: typeof C.vibeOf, mono: typeof C.monogram, svg: typeof C.monogramSvg}));")
        self.assertEqual(out["i"], ["SS", "PO", "CF", "TD", "?", "?"])
        self.assertEqual((out["avatar"], out["vibe"]), ("undefined", "undefined"))
        self.assertEqual((out["mono"], out["svg"]), ("function", "function"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheChartGeometry(unittest.TestCase):
    def layout(self, series, **opts):
        return js(f"const L=C.layoutChart({json.dumps(series)},{json.dumps(opts)});"
                  "console.log(JSON.stringify({empty:L.empty,zeroY:L.zeroY,plot:L.plot,yTicks:L.yTicks,xTicks:L.xTicks,"
                  "lines:L.lines.map(l=>({id:l.id,d:l.d,single:l.single,empty:l.empty,pts:l.points.map(p=>[p.x,p.y,p.value])})),"
                  "yMin:L.yMin,yMax:L.yMax}));")

    def test_points_scale_linearly_in_x_and_y(self):
        series = [{"id": "a", "name": "A", "color": "#fff", "points": [
            {"date": "2026-10-01", "value": 0, "bets": 1}, {"date": "2026-10-03", "value": 2, "bets": 2},
            {"date": "2026-10-05", "value": 4, "bets": 3}]}]
        out = self.layout(series, width=500, height=300, margin={"l": 50, "r": 10, "t": 10, "b": 30})
        pts = out["lines"][0]["pts"]
        plot = out["plot"]
        self.assertEqual((plot["x0"], plot["x1"], plot["y0"], plot["y1"]), (50, 490, 10, 270))
        # x: first date at the left edge, last at the right edge, the middle date exactly halfway
        self.assertAlmostEqual(pts[0][0], 50)
        self.assertAlmostEqual(pts[2][0], 490)
        self.assertAlmostEqual(pts[1][0], 270)
        # y: higher values are higher on screen (smaller y), and spacing is proportional
        self.assertGreater(pts[0][1], pts[1][1])
        self.assertGreater(pts[1][1], pts[2][1])
        self.assertAlmostEqual(pts[0][1] - pts[1][1], pts[1][1] - pts[2][1], places=1)
        # every point is inside the plot box
        for x, y, _ in pts:
            self.assertTrue(plot["x0"] - 1e-6 <= x <= plot["x1"] + 1e-6)
            self.assertTrue(plot["y0"] - 1e-6 <= y <= plot["y1"] + 1e-6)

    def test_zero_is_always_on_the_chart_and_lines_up_with_a_value_of_zero(self):
        series = [{"id": "a", "name": "A", "color": "#fff", "points": [
            {"date": "2026-10-01", "value": 3, "bets": 1}, {"date": "2026-10-02", "value": 5, "bets": 2}]}]
        out = self.layout(series)
        self.assertLessEqual(out["yMin"], 0)
        self.assertGreaterEqual(out["yMax"], 5)
        zero_tick = [t for t in out["yTicks"] if t["value"] == 0]
        self.assertEqual(len(zero_tick), 1)
        self.assertAlmostEqual(zero_tick[0]["y"], out["zeroY"])
        self.assertEqual(zero_tick[0]["label"], "0")

    def test_all_negative_series_still_include_zero_at_the_top(self):
        series = [{"id": "a", "name": "A", "color": "#fff", "points": [
            {"date": "2026-10-01", "value": -3, "bets": 1}, {"date": "2026-10-02", "value": -5, "bets": 2}]}]
        out = self.layout(series)
        self.assertGreaterEqual(out["yMax"], 0)
        self.assertLess(out["zeroY"], out["lines"][0]["pts"][0][1])

    def test_an_empty_series_set_is_flagged_and_has_no_baseline_or_lines(self):
        for series in ([], [{"id": "a", "name": "A", "color": "#fff", "points": []}]):
            out = self.layout(series)
            self.assertTrue(out["empty"])
            self.assertIsNone(out["zeroY"])
            self.assertEqual(out["yTicks"], [])

    def test_a_one_point_series_is_a_dot_with_no_line_in_the_middle_of_the_plot(self):
        series = [{"id": "a", "name": "A", "color": "#fff", "points": [{"date": "2026-10-01", "value": 2, "bets": 4}]}]
        out = self.layout(series, width=500, height=300)
        line = out["lines"][0]
        self.assertTrue(line["single"])
        self.assertEqual(line["d"], "")
        self.assertEqual(len(line["pts"]), 1)
        plot = out["plot"]
        self.assertAlmostEqual(line["pts"][0][0], (plot["x0"] + plot["x1"]) / 2)
        self.assertFalse(out["empty"])
        self.assertEqual(len([t for t in out["yTicks"] if t["value"] == 0]), 1)

    def test_all_zero_values_do_not_divide_by_zero(self):
        series = [{"id": "a", "name": "A", "color": "#fff", "points": [
            {"date": "2026-10-01", "value": 0, "bets": 1}, {"date": "2026-10-02", "value": 0, "bets": 2}]}]
        out = self.layout(series)
        self.assertFalse(out["empty"])
        self.assertAlmostEqual(out["lines"][0]["pts"][0][1], out["zeroY"])

    def test_two_series_with_different_dates_share_one_x_axis(self):
        series = [
            {"id": "a", "name": "A", "color": "#fff", "points": [{"date": "2026-10-01", "value": 1}, {"date": "2026-10-10", "value": 2}]},
            {"id": "b", "name": "B", "color": "#f00", "points": [{"date": "2026-10-05", "value": -1}]},
        ]
        out = self.layout(series, width=600, height=300, margin={"l": 0, "r": 0, "t": 0, "b": 0})
        b = out["lines"][1]["pts"][0]
        self.assertAlmostEqual(b[0], 600 * 4 / 9, places=1)

    def test_a_monotone_curve_never_overshoots_its_points(self):
        out = js("const p=[{x:0,y:100},{x:10,y:20},{x:20,y:20},{x:30,y:80}];"
                 "const d=C.monotonePath(p);"
                 "const nums=d.match(/-?\\d+\\.?\\d*/g).map(Number);"
                 "const ys=nums.filter((_, i) => i % 2 === 1);"
                 "console.log(JSON.stringify({d, min:Math.min(...ys), max:Math.max(...ys)}));")
        self.assertTrue(out["d"].startswith("M0,100C"))
        self.assertGreaterEqual(out["min"], 20 - 1e-6)
        self.assertLessEqual(out["max"], 100 + 1e-6)

    def test_nearest_day_and_the_values_at_it_carry_forward_without_inventing_a_start(self):
        series = [
            {"id": "a", "name": "A", "color": "#fff", "points": [{"date": "2026-10-01", "value": 1, "bets": 2}, {"date": "2026-10-04", "value": 3, "bets": 6}]},
            {"id": "b", "name": "B", "color": "#f00", "points": [{"date": "2026-10-03", "value": -1, "bets": 1}]},
        ]
        out = js(f"const L=C.layoutChart({json.dumps(series)},{{width:600,height:300}});"
                 "const d=C.nearestDay(L, L.x(L.dayMin)+1); const rows=C.valuesAtDay(L, d);"
                 "const d3=C.dayNumber('2026-10-03'); const rows3=C.valuesAtDay(L, d3);"
                 "console.log(JSON.stringify({isMin:d===L.dayMin,first:rows.map(r=>r.id),at3:rows3.map(r=>[r.id,r.value,r.exact])}));")
        self.assertTrue(out["isMin"])
        self.assertEqual(out["first"], ["a"])          # b has no point yet: not shown, not zero
        self.assertEqual(out["at3"], [["a", 1, False], ["b", -1, True]])  # a carried forward, flagged not exact

    def test_sparkline_needs_two_points_and_draws_zero_only_inside_its_range(self):
        out = js("console.log(JSON.stringify({none:C.layoutSparkline([]).empty,one:C.layoutSparkline([3]).empty,"
                 "two:C.layoutSparkline([1,2]),span:C.layoutSparkline([-1,2])}));")
        self.assertTrue(out["none"] and out["one"])
        self.assertFalse(out["two"]["empty"])
        self.assertTrue(out["two"]["d"].startswith("M"))
        self.assertEqual(out["two"]["n"], 2)
        self.assertGreater(out["span"]["zeroY"], 0)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSeriesShapes(unittest.TestCase):
    def norm(self, payload):
        return js(f"console.log(JSON.stringify(C.normalizeSeries({json.dumps(payload)})));")

    def test_accepts_the_shapes_the_endpoint_might_use(self):
        pts = [{"date": "2026-10-02", "cum_units_average_price": 1}, {"date": "2026-10-01T12:00:00Z", "cum_units_average_price": 0}]
        for payload in ({"series": {"a": pts}}, {"a": pts}, {"series": [{"id": "a", "points": pts}]}, [{"id": "a", "points": pts}]):
            out = self.norm(payload)
            self.assertEqual([p["date"][:10] for p in out["a"]], ["2026-10-01", "2026-10-02"], payload)
            self.assertTrue(all(p["segment"] == "forward" for p in out["a"]))

    def test_segments_from_the_points_or_from_forward_and_replay_lists(self):
        mixed = self.norm({"a": [{"date": "2026-10-01", "segment": "replay"}, {"date": "2026-10-20", "segment": "forward"}]})
        self.assertEqual([p["segment"] for p in mixed["a"]], ["replay", "forward"])
        split = self.norm({"a": {"replay": [{"date": "2026-10-01"}], "forward": [{"date": "2026-10-20"}]}})
        self.assertEqual(sorted(p["segment"] for p in split["a"]), ["forward", "replay"])

    def test_garbage_gives_an_empty_map_not_a_crash(self):
        for payload in (None, "x", 5, {"series": "nope"}, [None, 3]):
            self.assertEqual(self.norm(payload), {})

    def test_forward_data_exists_only_with_a_settled_forward_point(self):
        out = js("const rep={a:[{date:'2026-10-01',segment:'replay',bets_settled:9}]};"
                 "const fwd0={a:[{date:'2026-10-20',segment:'forward',bets_settled:0}]};"
                 "const fwd={a:[{date:'2026-10-20',segment:'forward',bets_settled:2}]};"
                 "console.log(JSON.stringify([C.hasForwardData(rep),C.hasForwardData(fwd0),C.hasForwardData(fwd),C.hasForwardData(null)]));")
        self.assertEqual(out, [False, False, True, False])

    def test_chart_points_drop_rows_where_the_field_is_null_not_zero_them(self):
        out = js("console.log(JSON.stringify(C.toChartPoints([{date:'2026-10-01',cum_clv_mean_pts:null,bets_settled:1},"
                 "{date:'2026-10-02',cum_clv_mean_pts:0.5,bets_settled:2}],'cum_clv_mean_pts')));")
        self.assertEqual(out, [{"date": "2026-10-02", "value": 0.5, "bets": 2}])

    def test_the_replay_block_of_the_contract_is_a_record_not_a_series(self):
        """contract.ReplayBlock is {bets, wins, losses, pushes, voids, units_recorded_price, note}."""
        out = js("const h={record:{bets:3},clv:null,replay:{bets:90,wins:40,losses:50,pushes:0,voids:0,"
                 "units_recorded_price:-4.2,note:'n'}};"
                 "console.log(JSON.stringify({r:C.segmentView(h,'replay'),f:C.segmentView(h,'forward')}));")
        self.assertEqual(out["r"]["record"]["bets"], 90)
        self.assertEqual(out["f"]["record"]["bets"], 3)

    def test_segment_views_forward_headline_replay_separate(self):
        out = js("const h={record:{bets:3},clv:null,replay:{record:{bets:90},clv:{n:90,mean_pts:1}}};"
                 "const only={segments:{replay:{record:{bets:5}}}};"
                 "console.log(JSON.stringify({f:C.segmentView(h,'forward'),r:C.segmentView(h,'replay'),"
                 "onlyF:C.segmentView(only,'forward'),onlyR:C.segmentView(only,'replay')}));")
        self.assertEqual(out["f"]["record"]["bets"], 3)
        self.assertEqual(out["r"]["record"]["bets"], 90)
        self.assertIsNone(out["onlyF"])
        self.assertEqual(out["onlyR"]["record"]["bets"], 5)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePollerStopsWhenNobodyIsLooking(unittest.TestCase):
    SETUP = """
let runs = 0, timers = new Map(), nextId = 1, listeners = [];
const doc = { visibilityState: 'visible',
  addEventListener: (t, f) => listeners.push(f), removeEventListener: (t, f) => { listeners = listeners.filter(x => x !== f); } };
const p = C.createPoller({ run: () => { runs++; }, intervalMs: 60000, doc,
  setTimer: (fn, ms) => { const id = nextId++; timers.set(id, fn); return id; }, clearTimer: (id) => timers.delete(id) });
const fire = () => { for (const fn of [...timers.values()]) fn(); };
const vis = (s) => { doc.visibilityState = s; for (const f of listeners) f({ type: 'visibilitychange' }); };
"""

    def test_visible_polls_hidden_does_not_and_returning_refreshes_once_immediately(self):
        out = js(self.SETUP + """
p.start(); fire(); fire();
const a = { runs, armed: p.armed };
vis('hidden'); fire(); fire();
const b = { runs, armed: p.armed, timers: timers.size };
vis('visible');
const c = { runs, armed: p.armed };
fire();
const d = { runs };
p.stop(); fire();
console.log(JSON.stringify({ a, b, c, d, after: runs, listeners: listeners.length }));""")
        self.assertEqual(out["a"], {"runs": 2, "armed": True})
        self.assertEqual(out["b"], {"runs": 2, "armed": False, "timers": 0})
        self.assertEqual(out["c"], {"runs": 3, "armed": True})
        self.assertEqual(out["d"], {"runs": 4})
        self.assertEqual(out["after"], 4)
        self.assertEqual(out["listeners"], 0)

    def test_a_tick_that_lands_while_hidden_does_nothing(self):
        out = js(self.SETUP + """
p.start(); doc.visibilityState = 'hidden'; fire();
console.log(JSON.stringify({ runs }));""")
        self.assertEqual(out["runs"], 0)

    def test_starting_hidden_does_not_arm_a_timer(self):
        out = js(self.SETUP.replace("visibilityState: 'visible'", "visibilityState: 'hidden'") + """
p.start(); console.log(JSON.stringify({ armed: p.armed, runs }));""")
        self.assertEqual(out, {"armed": False, "runs": 0})


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheRulePreviewAndTheSpec(unittest.TestCase):
    MENU = {"sports": [{"id": "mlb", "label": "MLB"}], "markets": [{"id": "moneyline", "label": "Moneyline"}],
            "side_rules": [{"id": "underdog", "label": "the underdog"}]}

    def test_the_preview_is_written_from_the_menu_labels_and_states_the_cap(self):
        form = {"sports": ["mlb"], "markets": ["moneyline"], "side_rule": "underdog", "price_min": -150, "price_max": 250,
                "min_books": 4, "max_bets_per_day": 3, "lock_minutes": 30}
        out = js(f"console.log(JSON.stringify(C.previewRuleSentence({json.dumps(form)},{json.dumps(self.MENU)})));")
        self.assertIn("Bet the underdog in moneyline (MLB)", out)
        self.assertIn("between -150 and +250", out)
        self.assertIn("at most 3 bets a day", out)
        self.assertIn("never takes a price of -200 or worse", out)

    def test_an_incomplete_form_says_what_is_missing_instead_of_inventing_a_rule(self):
        out = js(f"console.log(JSON.stringify(C.previewRuleSentence({{sports:[],markets:[],side_rule:''}},{json.dumps(self.MENU)})));")
        self.assertIn("Choose a sport, a market and a side rule", out)

    def test_spec_to_form_reads_what_get_spec_really_answers(self):
        """GET /hounds/{id}/spec -> {spec, copied_from, rule_text} (api/hounds_create.py): the form is
        filled from `spec`, including the fresh name the server suggests, and remembers `copied_from`."""
        payload = {"spec": {"name": "Closer II", "tagline": "t", "sports": ["MLB", "NFL"], "markets": ["moneyline", "total"],
                            "side_rule": "market_moved_toward", "price_min": -150, "price_max": 250, "min_books": 4,
                            "max_bets_per_day": 3, "lock_minutes": 60},
                   "copied_from": "u-ab12", "rule_text": "x"}
        out = js(f"console.log(JSON.stringify(C.specToForm({json.dumps(payload)})));")
        self.assertEqual(out, {"name": "Closer II", "tagline": "t", "sports": ["MLB", "NFL"], "markets": ["moneyline", "total"],
                               "side_rule": "market_moved_toward", "price_min": -150, "price_max": 250, "min_books": 4,
                               "max_bets_per_day": 3, "lock_minutes": 60, "copied_from": "u-ab12"})
        bare = js("console.log(JSON.stringify(C.specToForm(null)));")
        self.assertEqual((bare["sports"], bare["side_rule"], bare["copied_from"]), ([], "", ""))

    def test_the_posted_body_is_what_create_hound_takes_a_spec_and_copied_from(self):
        """api/hounds_create.py CreateHoundRequest: {spec: {...}, copied_from?}. The spec holds the menu's
        fields and nothing else (the server refuses unknown keys), and copied_from rides beside it."""
        form = ("{name:'N',tagline:'T',sports:['MLB'],markets:['moneyline'],side_rule:'underdog',"
                "price_min:-100,price_max:200,min_books:3,max_bets_per_day:2,lock_minutes:60,extra:'dropped',copied_from:'no'}")
        plain, copy = js(f"console.log(JSON.stringify([C.buildSpec({form}), C.buildSpec({form}, 'u-ab12')]));")
        self.assertEqual(sorted(plain), ["spec"])
        self.assertEqual(sorted(plain["spec"]), ["lock_minutes", "markets", "max_bets_per_day", "min_books", "name",
                                                 "price_max", "price_min", "side_rule", "sports", "tagline"])
        self.assertEqual(sorted(copy), ["copied_from", "spec"])
        self.assertEqual(copy["copied_from"], "u-ab12")

    def test_menu_options_are_value_label_pairs_and_side_rules_carry_their_markets(self):
        out = js("console.log(JSON.stringify([C.optionOf({value:'over',label:'The over',markets:['total']}),"
                 "C.optionOf({id:'old',label:'Old'}), C.optionOf('bare')]));")
        self.assertEqual(out[0], {"id": "over", "label": "The over", "markets": ["total"]})
        self.assertEqual(out[1]["id"], "old")
        self.assertEqual((out[2]["id"], out[2]["markets"]), ("bare", None))

    def test_american_prices_compare_by_decimal_odds(self):
        out = js("console.log(JSON.stringify([C.americanDecimal(-150), C.americanDecimal(120), C.americanDecimal(50),"
                 "C.americanDecimal(null), C.americanDecimal(-100), C.americanDecimal(100)]));")
        self.assertEqual(out[0], 1 + 100 / 150)
        self.assertEqual(out[1], 2.2)
        self.assertIsNone(out[2])           # +50 is not an American price
        self.assertIsNone(out[3])
        self.assertEqual((out[4], out[5]), (2.0, 2.0))


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStreamTheWarmingAndTheUnitsWords(unittest.TestCase):
    def test_a_stream_item_reads_from_the_contract_fields_and_a_refusal_says_it_passed(self):
        play = {"selection": "Yankees to win", "game": "Yankees at Red Sox", "price": -115, "price_average": -120,
                "book": "bookB", "reason": "Rule: the underdog.", "refused": False}
        refusal = {"game": "Mariners at Astros", "reason": "Refused: too few books were quoting this market.",
                   "refused": True, "selection": "(no bet)"}
        out = js(f"console.log(JSON.stringify([C.streamSummary({json.dumps(play)}), C.streamSummary({json.dumps(refusal)})]));")
        self.assertEqual(out[0], "Yankees to win in Yankees at Red Sox at -120 average price, -115 best price at bookB. Rule: the underdog.")
        self.assertEqual(out[1], "Passed in Mariners at Astros: too few books were quoting this market.")

    def test_warming_is_a_flag_on_a_200_and_the_retry_follows_the_servers_cadence_within_bounds(self):
        out = js("console.log(JSON.stringify([C.isWarming({warming_up:true}), C.isWarming({hounds:[]}), C.isWarming(null),"
                 "C.warmingRetryMs({retry_after_seconds:5}), C.warmingRetryMs({retry_after_seconds:0}),"
                 "C.warmingRetryMs({retry_after_seconds:900}), C.warmingRetryMs({})]));")
        self.assertEqual(out, [True, False, False, 5000, 1000, 30000, 5000])

    def test_the_two_prices_are_labelled_average_first_and_best_second(self):
        out = js("console.log(JSON.stringify([C.unitsPairText({units_average_price:1.2,units_recorded_price:1.5}),"
                 "C.unitsPairText({units_average_price:null,units_recorded_price:-2})]));")
        self.assertEqual(out[0], "+1.20u average price, +1.50u best price")
        self.assertEqual(out[1], "not reported average price, -2.00u best price")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFormattersNeverInventANumber(unittest.TestCase):
    def test_missing_values_read_as_not_reported_and_clv_null_is_not_zero(self):
        out = js("console.log(JSON.stringify({u:C.fmtUnits(undefined),s:C.signed(null),r:C.fmtRecord(null),c:C.fmtClv(null),"
                 "c2:C.fmtClv({n:12,mean_pts:0.4,ci_low:-0.2,ci_high:1.0}),c3:C.fmtClv({n:3,mean_pts:0.4}),"
                 "z:C.signed(-0.001,2),rec:C.fmtRecord({bets:1,wins:1,losses:0})}));")
        self.assertEqual(out["u"], "not reported")
        self.assertEqual(out["s"], "not reported")
        self.assertEqual(out["r"], "not reported")
        self.assertEqual(out["c"]["main"], "not measured yet")
        self.assertEqual(out["c2"], {"main": "+0.4 pts", "detail": "interval -0.2 to +1.0, n=12"})
        self.assertIn("no interval yet", out["c3"]["detail"])
        self.assertEqual(out["z"], "0.00")
        self.assertEqual(out["rec"], "1 bet (1-0)")


if __name__ == "__main__":
    unittest.main()
