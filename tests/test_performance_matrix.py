"""Tests for scripts/performance_matrix.py.

A small fixture world (card ledgers, a UFC card, an MLB value shadow arm, a
paper engine with decisions, wagers and per-system account ledgers) is written
to a temp directory and the whole matrix is built from it, so every number
below is a hand computation against known results. Nothing here opens the real
evidence stores.
"""

import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import unittest

from scripts import performance_matrix as pm
from scripts import value_scan as vs


# ---------------------------------------------------------------------------
# Fixture world
# ---------------------------------------------------------------------------

def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _tree_hashes(root):
    out = {}
    for base, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(base, name)
            out[os.path.relpath(p, root)] = _sha(p)
    return out


def _v1_rows(date="2026-09-12"):
    pub = {"kind": "card_published", "date": date, "row_hash": "pub1",
           "rule": "DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1",
           "picks": [{"game_pk": 11, "game_id": "A-B-1", "market": "moneyline", "price": -150,
                      "side": "home", "market_probability": 0.58, "model_probability": 0.60,
                      "label": "LEAN", "observed_utc": "2026-09-12T15:00:00Z",
                      "first_pitch_utc": "2026-09-12T23:00:00Z"}],
           "prop_picks": [{"game_pk": 11, "player": "P One", "market": "batter_hits",
                           "price": -200, "side": "Under", "line": 1.5,
                           "market_probability": 0.64, "probability": 0.70, "kind": "prop"}],
           "total_picks": []}
    settled = {"kind": "card_settled", "date": date, "published_row_hash": "pub1",
               "picks": [{"game_pk": 11, "game_id": "A-B-1", "market": "moneyline",
                          "price": -150, "result": "WIN", "profit_units": 0.6667}],
               "prop_picks": [{"game_pk": 11, "player": "P One", "market": "batter_hits",
                               "price": -200, "side": "Under", "line": 1.5,
                               "result": "LOSS", "profit_units": -1.0}],
               "total_picks": []}
    return [pub, settled]


def _v2_rows(date="2026-09-23"):
    def g(**kw):
        d = {"kind": "game", "market": "moneyline", "price": -130, "result": "WIN",
             "profit_units": 0.7692, "entry_class": "pick", "price_class": "MAIN",
             "market_probability": 0.55, "our_probability": 0.60, "our_probability_used": 0.562,
             "value_need": 0.57, "failed_gates": [], "withdrawn": False, "game_pk": 21,
             "game_type": "R", "side": "home"}
        d.update(kw)
        return d
    graded = [g(), g(entry_class="fill", failed_gates=["G7_VALUE"], result="LOSS",
                     profit_units=-1.0, game_pk=22),
              g(withdrawn=True, game_pk=23), g(result="VOID", profit_units=0.0, game_pk=24),
              g(kind="prop", market="batter_runs_scored", result="VOID", profit_units=0.0,
                game_pk=25, reason="no settlement rule for market 'batter_runs_scored'")]
    return [{"kind": "card_published", "date": date, "row_hash": "p2", "rule": "V2"},
            {"kind": "card_settled", "date": date, "rule": "V2", "published_row_hash": "p2",
             "graded": graded}]


def _nfl_rows(date="2026-09-17"):
    pick = {"game_id": "2026_02_DET_BUF", "game_pk": None, "market": "moneyline", "price": -225,
            "side": "home", "market_probability": 0.6736, "model_probability": None,
            "label": "STRONG", "rank": 1, "sport": "nfl", "home_team": "Buffalo Bills",
            "away_team": "Detroit Lions", "first_pitch_utc": "2026-09-18T00:15:00Z",
            "bet": "Take Buffalo Bills to win at -225"}
    pub = {"kind": "card_published", "date": date, "row_hash": "pubN", "rule": "NFL_CARD_V1",
           "picks": [pick], "prop_picks": [], "total_picks": []}
    settled = {"kind": "card_settled", "date": date, "published_row_hash": "pubN",
               "picks": [dict(pick, result="WIN", profit_units=0.4444)],
               "prop_picks": [], "total_picks": []}
    return [pub, settled]


UFC_PRICES = (("WIN", -120.0), ("WIN", -150.0), ("WIN", -200.0), ("WIN", -140.0),
              ("WIN", -110.0), ("LOSS", -130.0), ("VOID", -145.0))


def _ufc_rows(date="2026-09-26"):
    picks, graded = [], []
    for i, (result, price) in enumerate(UFC_PRICES):
        p = {"game_id": "bout%d" % i, "game_pk": None, "market": "moneyline", "price": price,
             "side": "away", "market_probability": 0.55, "model_probability": None,
             "label": "FAVOURITE", "rank": i + 1, "sport": "mma",
             "bet": "Fighter %d to win" % i}
        picks.append(p)
        units = {"WIN": 100.0 / abs(price), "LOSS": -1.0, "VOID": 0.0}[result]
        graded.append(dict(p, result=result, profit_units=round(units, 4)))
    pub = {"kind": "card_published", "date": date, "row_hash": "pubU", "rule": "UFC_CARD_V1",
           "picks": picks, "prop_picks": [], "total_picks": []}
    settled = {"kind": "card_settled", "date": date, "published_row_hash": "pubU",
               "picks": graded, "prop_picks": [], "total_picks": []}
    return [pub, settled]


HOME_SEL, AWAY_SEL = "9e8d61f45a38abf0", "b5670c82188aefcf"


def _dec(system_id, market_key, selection_id, decision_utc, *, event_id, price,
         consensus, p_model=None, provenance="none", record="live_pre_commencement",
         line=None):
    return {"event_id": event_id, "system_id": system_id, "market_key": market_key,
            "selection_id": selection_id, "decision_utc": decision_utc, "line": line,
            "price_american": price, "consensus_fair": consensus, "p_model": p_model,
            "p_model_provenance": provenance, "record_provenance": record, "verdict": "play",
            "books_at_decision": 9, "friction": {"dispersion": 0.01}, "book": "lowvig",
            "recorded_utc": decision_utc}


def _wager(system_id, bet_id, date, decision_utc, *, event_id, price, side="home",
           market_key="h2h", selection_id=HOME_SEL, game_pk=None):
    return {"bet_id": bet_id, "date": date, "decision_utc": decision_utc, "event_id": event_id,
            "game_pk": game_pk, "label": "PAPER", "line": None, "market_key": market_key,
            "price_american": price, "selection_id": selection_id,
            "selection_rule": "TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1",
            "settlement_rule": "h2h", "side": side, "stake_units": 1.0, "system_id": system_id}


def _units(price, outcome):
    if outcome == "loss":
        return -1.0
    if outcome == "win":
        return price / 100.0 if price > 0 else 100.0 / -price
    return 0.0


def _account(system_id, bet_id, day, outcome, price, *, market_key="h2h",
             selection_id=HOME_SEL, side="home", void_reason=None):
    row = {"bet_id": bet_id, "day": day, "label": "PAPER", "line": None,
           "market_key": market_key, "outcome": outcome, "price_american": price,
           "profit_units": _units(price, outcome), "selection_id": selection_id,
           "settlement_rule": "h2h", "side": side, "stake_units": 1.0, "system_id": system_id}
    if void_reason:
        row["void_reason"] = void_reason
    return row


FWD = "0123456789abcdef"
NFL_VOID = ("not an MLB event -- a non-MLB game wagered by the pre-2026-09-21 engine "
            "sport-filter bug [price-store sport tag: nfl]")


def paper_world():
    """(decisions, wagers, {system_id: account rows}) with known results.

    CONTROL trivial_always_home (regular season): b1 win -110, b2 loss +120, b3 win +150,
    b4 push -105, b5 void -120, b6 win -130 on a REPLAY decision (excluded), b7 an NFL
    void. MARKET_REFERENCE h2h home: m1 win -150, m2 loss -150. FORWARD_TEST 0123...:
    f1 win +110, f2 loss -120, f3 win +100 on 2026-09-29 (postseason row)."""
    systems = {"trivial_always_home": [], "market_derived_consensus_h2h_home": [],
               FWD: []}
    decisions, wagers = [], []

    def add(system_id, bet_id, day, outcome, price, consensus, *, p_model=None,
            provenance="none", record="live_pre_commencement", void_reason=None):
        utc = "%sT12:00:00+00:00" % day
        event_id = "ev_" + bet_id
        decisions.append(_dec(system_id, "h2h", HOME_SEL, utc, event_id=event_id, price=price,
                              consensus=consensus, p_model=p_model, provenance=provenance,
                              record=record))
        wagers.append(_wager(system_id, bet_id, day, utc, event_id=event_id, price=price))
        systems[system_id].append(_account(system_id, bet_id, day, outcome, price,
                                           void_reason=void_reason))

    c = "trivial_always_home"
    add(c, "b1", "2026-09-12", "win", -110, 0.52, provenance="placeholder", p_model=0.5)
    add(c, "b2", "2026-09-12", "loss", 120, 0.45, provenance="placeholder", p_model=0.5)
    add(c, "b3", "2026-09-13", "win", 150, 0.40, provenance="placeholder", p_model=0.5)
    add(c, "b4", "2026-09-13", "push", -105, 0.50, provenance="placeholder", p_model=0.5)
    add(c, "b5", "2026-09-14", "void", -120, 0.54, provenance="placeholder", p_model=0.5)
    add(c, "b6", "2026-09-15", "win", -130, 0.56, provenance="placeholder", p_model=0.5,
        record="replay")
    add(c, "b7", "2026-09-20", "void", -300, 0.75, provenance="placeholder", p_model=0.5,
        void_reason=NFL_VOID)
    m = "market_derived_consensus_h2h_home"
    add(m, "m1", "2026-09-16", "win", -150, 0.58, p_model=0.58, provenance="market_derived")
    add(m, "m2", "2026-09-16", "loss", -150, 0.60, p_model=0.60, provenance="market_derived")
    add(FWD, "f1", "2026-09-17", "win", 110, 0.47)
    add(FWD, "f2", "2026-09-17", "loss", -120, 0.53)
    add(FWD, "f3", "2026-09-29", "win", 100, 0.49)
    # a wager that never settled
    utc = "2026-09-22T12:00:00+00:00"
    decisions.append(_dec(FWD, "h2h", HOME_SEL, utc, event_id="ev_u1", price=-110,
                          consensus=0.52))
    wagers.append(_wager(FWD, "u1", "2026-09-22", utc, event_id="ev_u1", price=-110))
    return decisions, wagers, systems


def write_world(root, *, extra_decisions=(), extra_wagers=(), extra_accounts=None,
                with_cards=True):
    ev = os.path.join(root, "evidence")
    acc = os.path.join(root, "paper_accounts")
    os.makedirs(ev, exist_ok=True)
    os.makedirs(acc, exist_ok=True)
    if with_cards:
        _write_jsonl(os.path.join(ev, "cards_v1.jsonl"), _v1_rows())
        _write_jsonl(os.path.join(ev, "cards_v2.jsonl"), _v2_rows())
        _write_jsonl(os.path.join(ev, "cards_nfl_v1.jsonl"), _nfl_rows())
        _write_jsonl(os.path.join(ev, "cards_mma_v1.jsonl"), _ufc_rows())
        mvs = os.path.join(ev, "mlb_value_shadow_v1")
        os.makedirs(mvs, exist_ok=True)
        _write_jsonl(os.path.join(mvs, "C_RUN_LINE_decisions.jsonl"), [{
            "kind": "decision", "row_hash": "mvs1", "date": "2026-09-25", "market": "spreads",
            "price": -143, "side": "away", "line": 1.5, "fair_probability": 0.60,
            "quote_observed_utc": "2026-09-25T20:52:45+00:00", "event_id": "mvsev1",
            "game_pk": "822760", "first_pitch_utc": "2026-09-25T23:08:00Z",
            "home_team": "H", "away_team": "A", "player": None}])
        _write_jsonl(os.path.join(mvs, "C_RUN_LINE_settled.jsonl"), [{
            "kind": "settled", "decision_row_hash": "mvs1", "date": "2026-09-25",
            "result": "WIN", "profit_units": 0.6993}])
        _write_jsonl(os.path.join(mvs, "D_GAME_TOTAL_scans.jsonl"), [{"kind": "scan"}] * 3)
        _write_jsonl(os.path.join(ev, "forward_ledger.jsonl"), [{
            "kind": "recommendation", "market": "first_five", "verdict": "flagged",
            "date": "2026-09-12", "side": "home", "game_pk": 1}])
    decisions, wagers, systems = paper_world()
    _write_jsonl(os.path.join(ev, "decisions_v2.jsonl"), list(decisions) + list(extra_decisions))
    _write_jsonl(os.path.join(ev, "paper_wagers_v2.jsonl"), list(wagers) + list(extra_wagers))
    systems = dict(systems)
    systems.update(extra_accounts or {})
    for sid, rows in systems.items():
        _write_jsonl(os.path.join(acc, sid + ".jsonl"), rows)
    return ev, acc


def build(root, **kw):
    ev, acc = write_world(root, **kw)
    sources = pm.load_sources(
        evidence_dir=ev, accounts_dir=acc,
        multibook=os.path.join(root, "no_multibook.jsonl"),
        event_map=os.path.join(root, "no_event_map.jsonl"))
    return pm.build_matrix(sources), sources


def find_row(matrix, **match):
    out = []
    for r in matrix["rows"]:
        ok = True
        for k, v in match.items():
            have = r["s"].get(k) if k in r["s"] else r.get(k)
            if k == "cls":
                have = r["cls"]
            if have != v:
                ok = False
        if ok:
            out.append(r)
    return out


class FixtureCase(unittest.TestCase):
    """Builds the fixture world once per class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.matrix, cls.sources = build(cls.tmp.name)
        cls.text = pm.render(cls.matrix, now="NOW")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


# ---------------------------------------------------------------------------
# Families, MISSING rows, vocabulary
# ---------------------------------------------------------------------------

class FamilyCoverageTest(FixtureCase):
    def test_every_required_family_appears_exactly_as_a_row_or_a_missing_row(self):
        names = [f[0] for f in pm.FAMILIES]
        self.assertEqual(len(names), 12)
        for fam in names:
            cells = self.matrix["families"][fam]
            self.assertGreaterEqual(len(cells), 3, fam)   # one cell per visibility, at least
            for vis in pm.VIS_ORDER:
                mine = [c for c in cells if c["vis"] == vis]
                self.assertGreaterEqual(len(mine), 1, (fam, vis))
                kinds = {"reason" in c for c in mine}
                self.assertEqual(len(kinds), 1, "a cell mixes measured and MISSING rows")
            self.assertIn("### %s\n" % fam, self.text)

    def test_the_required_families_are_named_in_order(self):
        wanted = ["MLB moneyline", "MLB run line", "MLB totals", "MLB first-five (F5)",
                  "MLB pitcher props", "MLB hitter props: hits",
                  "MLB hitter props: total bases", "MLB hitter props: runs scored",
                  "NFL sides", "NFL totals", "NFL player props", "UFC sides"]
        self.assertEqual([f[0] for f in pm.FAMILIES], wanted)

    def test_missing_rows_carry_a_reason_from_the_fixed_vocabulary(self):
        self.assertTrue(self.matrix["missing"])
        for m in self.matrix["missing"]:
            self.assertIn(m["reason"], pm.MISSING_REASONS)
            self.assertTrue(m["detail"])
        self.assertEqual(set(pm.MISSING_REASONS), {
            "NEVER_PUBLISHED", "PUBLISHED_UNGRADED", "PUBLISHED_NOT_STAKED",
            "NO_CLOSING_LINE_CAPTURED", "NO_PROBABILITY_FROZEN"})

    def test_missing_reasons_are_precise_in_the_fixture(self):
        def cell(fam, vis):
            return [m for m in self.matrix["missing"]
                    if m["family"] == fam and m["vis"] == vis][0]
        self.assertEqual(cell("MLB totals", "public")["reason"], pm.NEVER_PUBLISHED)
        self.assertIn("scan rows and no decision", cell("MLB totals", "shadow")["detail"])
        self.assertEqual(cell("MLB pitcher props", "paper")["reason"], pm.NEVER_PUBLISHED)
        self.assertEqual(cell("MLB first-five (F5)", "public")["reason"], pm.PUBLISHED_NOT_STAKED)
        self.assertEqual(cell("MLB hitter props: runs scored", "public")["reason"],
                         pm.PUBLISHED_UNGRADED)
        self.assertIn("no settlement rule", cell("MLB hitter props: runs scored", "public")["detail"])
        nfl_paper = cell("NFL sides", "paper")
        self.assertEqual(nfl_paper["reason"], pm.PUBLISHED_UNGRADED)
        self.assertIn("VOID x1", nfl_paper["detail"])

    def test_a_world_with_no_ledgers_is_all_missing_and_never_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "evidence"))
            os.makedirs(os.path.join(tmp, "acc"))
            sources = pm.load_sources(
                evidence_dir=os.path.join(tmp, "evidence"), accounts_dir=os.path.join(tmp, "acc"),
                multibook=os.path.join(tmp, "x.jsonl"), event_map=os.path.join(tmp, "y.jsonl"))
            matrix = pm.build_matrix(sources)
            self.assertEqual(matrix["rows"], [])
            self.assertEqual(len(matrix["missing"]), 36)
            self.assertEqual({m["reason"] for m in matrix["missing"]}, {pm.NEVER_PUBLISHED})
            text = pm.render(matrix, now="NOW")
            self.assertIn("## What this says about where to build", text)


# ---------------------------------------------------------------------------
# Pooling
# ---------------------------------------------------------------------------

class NoPoolingTest(FixtureCase):
    def test_every_row_holds_exactly_one_rule_class_scope_model_and_visibility(self):
        for r in self.matrix["rows"]:
            keys = {pm.row_key(e) for e in r["entries"]}
            self.assertEqual(len(keys), 1, r["id"])
            self.assertEqual(len({e["rule"] for e in r["entries"]}), 1)
        total = sum(r["n_entries"] for r in self.matrix["rows"]) + \
            sum(r["n_entries"] for r in self.matrix["idle"])
        self.assertEqual(total, len(self.sources["entries"]))

    def test_two_rules_on_one_market_are_two_rows(self):
        v1 = find_row(self.matrix, market="moneyline", rule="V1 public", cls="pick")
        v2 = find_row(self.matrix, market="moneyline", rule="V2 public", cls="pick")
        self.assertEqual((len(v1), len(v2)), (1, 1))
        self.assertIsNot(v1[0], v2[0])

    def test_fills_postseason_and_models_never_enter_another_row(self):
        fills = find_row(self.matrix, market="moneyline", rule="V2 public", cls="fill")
        self.assertEqual(len(fills), 1)
        self.assertEqual((fills[0]["s"]["wins"], fills[0]["s"]["losses"]), (0, 1))
        fwd = [r for r in self.matrix["rows"] if r["model"] == FWD]
        self.assertEqual(sorted(r["scope"] for r in fwd), ["postseason", "regular"])
        self.assertEqual({r["s"]["n_staked"] for r in fwd if r["scope"] == "postseason"}, {1})
        # three different paper systems -> three different rows, never one "paper" row
        paper = [r for r in self.matrix["rows"] if r["vis"] == "paper" and r["scope"] == "regular"]
        self.assertEqual(len({r["model"] for r in paper}), len(paper))


# ---------------------------------------------------------------------------
# Hand-computed results
# ---------------------------------------------------------------------------

class KnownResultsTest(FixtureCase):
    def test_v1_public_moneyline_pick(self):
        (r,) = find_row(self.matrix, market="moneyline", rule="V1 public", cls="pick")
        s = r["s"]
        self.assertEqual((s["n_staked"], s["wins"], s["losses"]), (1, 1, 0))
        self.assertAlmostEqual(s["units"], 100.0 / 150.0)
        self.assertAlmostEqual(s["roi"], 100.0 / 150.0)
        self.assertEqual(s["verdict"], "TOO FEW")

    def test_paper_control_row_reproduces_n_wl_units_roi_by_hand(self):
        (r,) = [r for r in self.matrix["rows"]
                if r["model"] == "trivial_always_home" and r["scope"] == "regular"
                and r["sport"] == "mlb"]
        s = r["s"]
        # staked: b1 win -110, b2 loss +120, b3 win +150. b4 push, b5 void are never staked;
        # b6 sits on a replay decision (excluded); b7 is an NFL void (its own row/cell).
        self.assertEqual((s["n_staked"], s["wins"], s["losses"]), (3, 2, 1))
        self.assertEqual((s["pushes"], s["voids"]), (1, 1))
        expected = 100.0 / 110.0 - 1.0 + 1.5
        self.assertAlmostEqual(s["units"], expected)
        self.assertAlmostEqual(s["roi"], expected / 3.0)
        self.assertEqual(r["baseline"], pm.BASELINE_CONTROL)
        self.assertEqual((r["first"], r["last"]), ("2026-09-12", "2026-09-13"))
        text = [ln for ln in self.text.splitlines() if "trivial_always_home" in ln and "| 3 | 2-1-1-1 |" in ln]
        self.assertEqual(len(text), 1)
        self.assertIn("+1.41", text[0])

    def test_paper_market_reference_row_and_z(self):
        (r,) = [r for r in self.matrix["rows"]
                if r["model"] == "market_derived_consensus_h2h_home"]
        s = r["s"]
        self.assertEqual((s["n_staked"], s["wins"], s["losses"]), (2, 1, 1))
        self.assertAlmostEqual(s["units"], 100.0 / 150.0 - 1.0)
        # z = (wins - sum p) / sqrt(sum p(1-p)), p the frozen consensus_fair
        ps = (0.58, 0.60)
        z = (1 - sum(ps)) / (sum(p * (1 - p) for p in ps)) ** 0.5
        self.assertAlmostEqual(s["z"], z)
        self.assertEqual(r["baseline"], pm.BASELINE_MARKET_REFERENCE)

    def test_ufc_n6_is_too_few_and_its_n_is_in_the_row(self):
        (r,) = find_row(self.matrix, market="moneyline", rule="UFC V1", cls="pick")
        s = r["s"]
        self.assertEqual((s["n_staked"], s["wins"], s["losses"], s["voids"]), (6, 5, 1, 1))
        wins = sum(100.0 / abs(p) for res, p in UFC_PRICES if res == "WIN")
        self.assertAlmostEqual(s["units"], wins - 1.0, places=3)
        self.assertEqual(s["verdict"], "TOO FEW")
        row = [ln for ln in self.text.splitlines() if "| UFC V1 / pick |" in ln][0]
        self.assertIn("TOO FEW (n=6)", row)
        self.assertIn("| 5-1-0-1 |", row)
        # nothing about this sample can make it more than TOO FEW
        self.assertEqual(vs.verdict(6, 9.9, 9.9, 99.0), "TOO FEW")

    def test_value_shadow_run_line_is_a_shadow_row_with_the_market_p_only(self):
        (r,) = [r for r in self.matrix["rows"] if r["market"] == "run line"
                and r["vis"] == "shadow"]
        self.assertEqual((r["s"]["n_staked"], r["s"]["wins"]), (1, 1))
        self.assertAlmostEqual(r["s"]["units"], 100.0 / 143.0, places=3)
        self.assertIsNone(r["cal"])
        self.assertEqual(r["s"]["mean_mkt"], 0.60)

    def test_v2_withdrawn_void_and_runs_scored_are_never_staked(self):
        v2 = [r for r in self.matrix["rows"] if r["rule"] == "V2 public"]
        self.assertEqual(sum(r["s"]["n_staked"] for r in v2), 2)   # 1 pick + 1 fill
        text = self.text
        self.assertIn("withdrawn", text.split("## Entries counted and never staked")[1])


class PaperEngineTest(FixtureCase):
    def test_replay_decisions_are_excluded_by_name_not_staked(self):
        inv = self.sources["paper"]
        self.assertEqual(sum(inv["excluded_provenance"].values()), 1)
        ((cls, mk, prov), n), = inv["excluded_provenance"].items()
        self.assertEqual((cls, mk, prov, n), ("CONTROL", "moneyline", "replay", 1))
        self.assertIn("replay", self.text)

    def test_unsettled_wagers_and_non_mlb_voids_are_inventoried(self):
        inv = self.sources["paper"]
        self.assertEqual(dict(inv["unsettled_by_date"]), {"2026-09-22": 1})
        self.assertEqual(dict(inv["void_non_mlb"]), {"nfl": 1})
        self.assertEqual(inv["unjoined"], 0)
        self.assertEqual(inv["price_mismatch"], 0)

    def test_forward_test_and_control_have_no_model_probability(self):
        for r in self.matrix["rows"]:
            if r["vis"] == "paper" and r["baseline"] != pm.BASELINE_MARKET_REFERENCE:
                self.assertIsNone(r["cal"], r["model"])

    def test_pre_window_account_rows_are_counted_and_never_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev, acc = write_world(tmp)
            path = os.path.join(acc, "trivial_always_home.jsonl")
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                # not valid JSON: if it were parsed the run would fail
                fh.write('{"day": "2023-04-18", "bet_id": "old", "outcome": BROKEN\n')
            inv = pm.load_paper(acc, os.path.join(ev, "paper_wagers_v2.jsonl"),
                                os.path.join(ev, "decisions_v2.jsonl"))[1]
            self.assertEqual(inv["excluded_pre_window_rows"], 1)
            self.assertEqual(dict(inv["excluded_pre_window_by_month"]), {"2023-04": 1})
            self.assertEqual(inv["accounts"]["trivial_always_home"]["unparseable"], 0)

    def test_decisions_dated_in_the_sealed_window_are_skipped_unparsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev, acc = write_world(tmp)
            with open(os.path.join(ev, "decisions_v2.jsonl"), "a", encoding="utf-8",
                      newline="\n") as fh:
                fh.write('{"decision_utc": "2026-05-05T12:00:00+00:00", "BROKEN\n')
                fh.write('{"decision_utc": "2025-05-05T12:00:00+00:00", "BROKEN\n')
            inv = pm.load_paper(acc, os.path.join(ev, "paper_wagers_v2.jsonl"),
                                os.path.join(ev, "decisions_v2.jsonl"))[1]
            self.assertEqual(inv["decisions"]["sealed_dates"], ["2026-05-05"])
            self.assertEqual(inv["decisions"]["pre_window"], 1)
            self.assertEqual(inv["decisions"]["unparseable"], 0)


# ---------------------------------------------------------------------------
# Calibration only where a probability is frozen
# ---------------------------------------------------------------------------

class CalibrationTest(FixtureCase):
    def test_rows_with_no_frozen_probability_print_no_calibration_number(self):
        none_frozen = [r for r in self.matrix["rows"] if r["cal"] is None]
        self.assertTrue(none_frozen)
        for r in none_frozen:
            cell = pm.cell_cal(r)
            self.assertEqual(cell, pm.NO_PROBABILITY_FROZEN)
            self.assertFalse(re.search(r"\d", cell), cell)
            self.assertEqual(pm.cell_brier(r), "-")
        for who in ("UFC V1", "NFL V1"):
            (r,) = [r for r in self.matrix["rows"] if r["rule"] == who]
            self.assertIsNone(r["cal"])
            line = [ln for ln in self.text.splitlines() if "| %s / pick |" % who in ln][0]
            self.assertIn(pm.NO_PROBABILITY_FROZEN, line)
            self.assertNotIn("pred ", line)
        (c,) = [r for r in self.matrix["rows"] if r["model"] == FWD and r["scope"] == "regular"]
        self.assertIsNone(c["cal"])

    def test_a_row_with_a_frozen_probability_prints_pred_obs_gap_and_n(self):
        (r,) = find_row(self.matrix, market="moneyline", rule="V1 public", cls="pick")
        cal = r["cal"]
        self.assertEqual(cal["n"], 1)
        self.assertAlmostEqual(cal["pred"], 0.60)
        self.assertAlmostEqual(cal["obs"], 1.0)
        self.assertAlmostEqual(cal["gap"], 0.60 - 1.0)
        cell = pm.cell_cal(r)
        self.assertIn("pred 0.600", cell)
        self.assertIn("gap -0.400", cell)
        self.assertIn("n=1", cell)

    def test_market_reference_calibration_is_labelled_as_the_markets_own(self):
        (r,) = [r for r in self.matrix["rows"] if r["model"] == "market_derived_consensus_h2h_home"]
        self.assertIsNotNone(r["cal"])
        self.assertIn("market's own p", pm.cell_cal(r))
        self.assertAlmostEqual(r["cal"]["pred"], 0.59)
        self.assertEqual(pm.cell_brier(r), "identical to market by construction")

    def test_calibration_helper_by_hand(self):
        es = [pm.new_entry(price=-150, result="WIN", p_our=0.7),
              pm.new_entry(price=-150, result="LOSS", p_our=0.5),
              pm.new_entry(price=-150, result="WIN", p_our=None)]
        c = pm.calibration(es)
        self.assertEqual(c["n"], 2)
        self.assertAlmostEqual(c["pred"], 0.6)
        self.assertAlmostEqual(c["obs"], 0.5)
        self.assertAlmostEqual(c["gap"], 0.1)
        self.assertAlmostEqual(c["se"], (0.21 + 0.25) ** 0.5 / 2)
        self.assertIsNone(pm.calibration([pm.new_entry(price=-150, result="WIN")]))


# ---------------------------------------------------------------------------
# Labels, integrity, document shape
# ---------------------------------------------------------------------------

class LabelAndDocumentTest(FixtureCase):
    def test_baselines_are_labelled_and_models_are_not(self):
        for r in self.matrix["rows"]:
            line = [ln for ln in self.text.splitlines() if ln.startswith("| %s |" % r["id"])][0]
            if r["model"].startswith("trivial_"):
                self.assertEqual(r["baseline"], pm.BASELINE_CONTROL)
                self.assertIn("BASELINE: CONTROL", line)
            elif r["model"].startswith("market_derived_consensus_"):
                self.assertEqual(r["baseline"], pm.BASELINE_MARKET_REFERENCE)
                self.assertIn("BASELINE: MARKET REFERENCE", line)
            else:
                self.assertIsNone(r["baseline"])
                self.assertNotIn("BASELINE", line)

    def test_the_verdict_rule_is_stated_once_and_matches_value_scan(self):
        self.assertEqual(self.text.count("Verdict rule (fixed, stated once"), 1)
        self.assertIn("n staked < %d" % vs.MIN_N_STAKED, self.text)
        for r in self.matrix["rows"]:
            s = r["s"]
            self.assertEqual(s["verdict"], vs.verdict(
                s["n_staked"], s["clv"]["mean"], s["clv"]["lo"], s["z"]))

    def test_multiplicity_warning_is_at_the_top(self):
        head = self.text.split("## Coverage grid")[0]
        self.assertIn("**Multiplicity.**", head)
        self.assertIn("will look good by chance alone", head)
        self.assertIn("z above 2", head)

    def test_integrity_recomputed_units_match_the_ledgers_own(self):
        integ = self.matrix["integrity"]
        self.assertEqual(integ["mismatches"], 0)
        self.assertGreater(integ["checked"], 5)
        self.assertEqual(vs.unit_mismatches(self.sources["entries"]), 0)
        self.assertIn("Integrity check: 0 of", self.text)

    def test_integrity_detects_a_ledger_whose_units_are_wrong(self):
        es = [dict(e) for e in self.sources["entries"]]
        victim = [e for e in es if vs.is_staked(e) and e["vis"] == "paper"][0]
        victim["ledger_units"] += 0.5
        self.assertEqual(pm.integrity(es)["mismatches"], 1)

    def test_conclusions_section_is_last_and_has_the_three_answers(self):
        marker = "## What this says about where to build"
        self.assertEqual(self.text.count(marker), 1)
        tail = self.text.split(marker)[1]
        self.assertNotIn("\n## ", tail)
        for n in ("**1. ", "**2. ", "**3. "):
            self.assertIn(n, tail)
        self.assertIn("Descriptive, not a finding.", tail)
        hyp = tail.split("**3. ")[1]
        self.assertLessEqual(len([ln for ln in hyp.splitlines() if ln.startswith("- ")]), 8)

    def test_no_markdown_table_row_is_ragged(self):
        width = None
        seen = 0
        for ln in self.text.splitlines():
            if ln.startswith("| Row |"):
                width = ln.count("|")
            elif re.match(r"^\| [RM]\d{3} \|", ln):
                self.assertEqual(ln.count("|"), width, ln)
                seen += 1
        self.assertIsNotNone(width)
        self.assertGreater(seen, 20)

    def test_deterministic_but_for_the_generated_line(self):
        again = pm.render(pm.build_matrix(self.sources), now="NOW")
        self.assertEqual(again, self.text)


# ---------------------------------------------------------------------------
# Refusals: sealed window, ambiguity, read-only
# ---------------------------------------------------------------------------

def _run(argv):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = pm.main(argv)
    return code, err.getvalue()


class RefusalTest(unittest.TestCase):
    def _argv(self, root, out, ev, acc):
        return ["--evidence-dir", ev, "--accounts-dir", acc, "--out", out,
                "--multibook", os.path.join(root, "no_mb.jsonl"),
                "--event-map", os.path.join(root, "no_em.jsonl")]

    def test_a_paper_account_row_in_the_sealed_window_exits_2_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {"trivial_always_home_x": [_account("trivial_always_home_x", "s1",
                                                       "2026-05-01", "win", -110)]}
            ev, acc = write_world(tmp, extra_accounts=bad)
            out = os.path.join(tmp, "PM.md")
            code, err = _run(self._argv(tmp, out, ev, acc))
            self.assertEqual(code, 2)
            self.assertIn("sealed window", err)
            self.assertFalse(os.path.exists(out))

    def test_a_paper_wager_in_the_sealed_window_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            utc = "2026-03-01T12:00:00+00:00"
            w = _wager("trivial_always_home", "sw1", "2026-03-01", utc, event_id="e", price=-110)
            ev, acc = write_world(tmp, extra_wagers=[w])
            with self.assertRaises(vs.SealedWindowError):
                pm.load_paper(acc, os.path.join(ev, "paper_wagers_v2.jsonl"),
                              os.path.join(ev, "decisions_v2.jsonl"))

    def test_a_card_ledger_in_the_sealed_window_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev, acc = write_world(tmp)
            _write_jsonl(os.path.join(ev, "cards_v1.jsonl"), _v1_rows(date="2026-05-01"))
            out = os.path.join(tmp, "PM.md")
            code, _err = _run(self._argv(tmp, out, ev, acc))
            self.assertEqual(code, 2)
            self.assertFalse(os.path.exists(out))

    def test_a_duplicate_decision_key_stops_the_run_with_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            dup = _dec("trivial_always_home", "h2h", HOME_SEL, "2026-09-12T12:00:00+00:00",
                       event_id="ev_b1", price=-110, consensus=0.52)
            ev, acc = write_world(tmp, extra_decisions=[dup])
            out = os.path.join(tmp, "PM.md")
            code, err = _run(self._argv(tmp, out, ev, acc))
            self.assertEqual(code, 3)
            self.assertIn("not unique", err)
            self.assertFalse(os.path.exists(out))

    def test_a_duplicate_wager_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            dup = _wager("trivial_always_home", "b1", "2026-09-12", "2026-09-12T12:00:00+00:00",
                         event_id="ev_b1", price=-110)
            ev, acc = write_world(tmp, extra_wagers=[dup])
            with self.assertRaises(pm.AmbiguousJoinError):
                pm.load_paper(acc, os.path.join(ev, "paper_wagers_v2.jsonl"),
                              os.path.join(ev, "decisions_v2.jsonl"))

    def test_a_second_settlement_for_one_shadow_decision_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev, _acc = write_world(tmp)
            path = os.path.join(ev, "mlb_value_shadow_v1", "C_RUN_LINE_settled.jsonl")
            row = {"kind": "settled", "decision_row_hash": "mvs1", "date": "2026-09-25",
                   "result": "LOSS", "profit_units": -1.0}
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(row) + "\n")
            with self.assertRaises(pm.AmbiguousJoinError):
                pm.load_mvs(os.path.join(ev, "mlb_value_shadow_v1"))

    def test_main_is_read_only_and_writes_exactly_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev, acc = write_world(tmp)
            before = _tree_hashes(tmp)
            out = os.path.join(tmp, "docs", "PM.md")
            code, _err = _run(self._argv(tmp, out, ev, acc))
            self.assertEqual(code, 0)
            after = _tree_hashes(tmp)
            self.assertEqual({k: v for k, v in after.items() if k != os.path.join("docs", "PM.md")},
                             before)
            self.assertIn(os.path.join("docs", "PM.md"), after)
            with open(out, encoding="utf-8", newline="") as fh:
                text = fh.read()
            self.assertTrue(text.startswith("# Performance matrix"))
            self.assertNotIn("\r", text)


class MarketLabelTest(unittest.TestCase):
    def test_market_labels(self):
        self.assertEqual(pm.market_for("mlb", "game", "moneyline"), "moneyline")
        self.assertEqual(pm.market_for("mlb", "game", "h2h"), "moneyline")
        self.assertEqual(pm.market_for("mlb", "game", "spreads"), "run line")
        self.assertEqual(pm.market_for("mlb", "game", "h2h_1st_5_innings"), "F5 moneyline")
        self.assertEqual(pm.market_for("mlb", "total", "total"), "totals")
        self.assertEqual(pm.market_for("mlb", "prop", "batter_runs_scored"), "runs-scored prop")
        self.assertEqual(pm.market_for("mlb", "prop", "pitcher_strikeouts"), "pitcher props")
        self.assertEqual(pm.market_for("nfl", "prop", "player_pass_yds"), "player props")
        self.assertEqual(pm.family_for("mma", "moneyline"), "UFC sides")
        self.assertEqual(pm.family_for("nfl", "moneyline"), "NFL sides")
        self.assertEqual(pm.family_for("mlb", "moneyline"), "MLB moneyline")


if __name__ == "__main__":
    unittest.main()
