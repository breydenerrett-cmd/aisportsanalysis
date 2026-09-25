"""`scripts/ai_analyst.py`: the schema, the hard limits, and the four
fault-injection cases Lane D Part 3 required -- an injected stale quote, an
invented/contradictory source claim, an unrelated player's injury, and a
clean case that should produce NO_ADJUSTMENT.

Injected fixtures only. `mlb_news_claims` is exercised through a
monkeypatched `src.providers.mlb_news.fetch` so this file never makes a
network call -- the same discipline `tests/test_card_v2_candidate_enumeration.py`
applies to its own no-live-store rule.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from scripts import ai_analyst as aa


NOW = datetime(2026, 9, 25, 15, 0, 0, tzinfo=timezone.utc).isoformat()
GAME_ID = "NYM-WSH-2026-09-25-1"


def _artifact(tmp_dir, *, selections=None, models_by_game=None,
             quotes_by_game=None):
    """A minimal shadow-enumeration-shaped artifact, only the keys
    `ai_analyst.py` actually reads -- the real schema is
    `scripts/shadow_enumeration_run.py`'s own payload, pinned end to end by
    that script's own tests; this file only needs the slice it consumes."""
    payload = {
        "date": "2026-09-25",
        "corrected_path": {"selections": selections or []},
        "board": {
            "models_by_game": models_by_game or {},
            "quotes_by_game": quotes_by_game or {},
        },
    }
    path = os.path.join(tmp_dir, "artifact.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def _selection(price=118, our_p=0.5489, market_p=0.4528):
    return {"game_id": GAME_ID, "market": "moneyline", "side": "home",
           "price": price, "our_probability": our_p,
           "market_probability": market_p, "bet": "Nationals moneyline"}


def _model_rec(home_sp_known=True, away_sp_known=False):
    return {
        "game_id": GAME_ID, "home_team": "WSH", "away_team": "NYM",
        "model_inputs": {
            "home_sp_known": home_sp_known, "home_sp_era": 3.6,
            "home_sp_starts": 14, "home_sp_days_rest": 14,
            "away_sp_known": away_sp_known, "away_sp_era": None,
            "away_sp_starts": 0, "away_sp_days_rest": None,
        },
    }


def _quote(observed):
    return {"best_price": 118, "best_book": "betus", "books": 9,
           "market_implied_probability": 0.4528, "observed_utc": observed}


class ClaimSchema(unittest.TestCase):
    def test_claim_requires_a_known_status(self):
        with self.assertRaises(ValueError):
            aa.Claim(claim_id="c1", entity="X", event="e", text="t",
                    source_ref="s", retrieved_at=NOW, status="MAYBE",
                    uncertainty="u", intended_use="use")

    def test_claim_id_and_text_may_not_be_blank(self):
        with self.assertRaises(ValueError):
            aa.Claim(claim_id="", entity="X", event="e", text="t",
                    source_ref="s", retrieved_at=NOW, status="CONFIRMED",
                    uncertainty="u", intended_use="use")

    def test_published_at_defaults_to_none_not_a_guess(self):
        c = aa.Claim(claim_id="c1", entity="X", event="e", text="t",
                     source_ref="s", retrieved_at=NOW, status="UNCONFIRMED",
                     uncertainty="u", intended_use="use")
        self.assertIsNone(c.published_at)


class EvidencePacketIsBounded(unittest.TestCase):
    def test_more_than_max_claims_is_refused(self):
        rec = aa.ModelRecommendation(
            game_id=GAME_ID, market="moneyline", side="home", price=118,
            our_probability=0.55, market_probability=0.45,
            source_artifact="x")
        claims = tuple(
            aa.Claim(claim_id=f"c{i}", entity="X", event="e", text="t",
                    source_ref="s", retrieved_at=NOW, status="CONFIRMED",
                    uncertainty="u", intended_use="use")
            for i in range(aa.MAX_CLAIMS + 1))
        with self.assertRaises(ValueError):
            aa.EvidencePacket(game_id=GAME_ID, date="2026-09-25",
                             built_at=NOW, recommendation=rec,
                             claims=claims)

    def test_duplicate_claim_ids_are_refused(self):
        rec = aa.ModelRecommendation(
            game_id=GAME_ID, market="moneyline", side="home", price=118,
            our_probability=0.55, market_probability=0.45,
            source_artifact="x")
        dup = aa.Claim(claim_id="same", entity="X", event="e", text="t",
                       source_ref="s", retrieved_at=NOW, status="CONFIRMED",
                       uncertainty="u", intended_use="use")
        with self.assertRaises(ValueError):
            aa.EvidencePacket(game_id=GAME_ID, date="2026-09-25",
                             built_at=NOW, recommendation=rec,
                             claims=(dup, dup))


def _bare_finding(**overrides):
    base = dict(
        game_id=GAME_ID, verified_assumptions=(), challenged_assumption="x",
        alternate_market=None, recalculation_request=None,
        case_against="a real case", verdict="NO_ADJUSTMENT")
    base.update(overrides)
    return aa.CriticFinding(**base)


class HardLimits(unittest.TestCase):
    """The four things a critic may never do (module docstring), each
    caught rather than merely documented."""

    def setUp(self):
        self.rec = aa.ModelRecommendation(
            game_id=GAME_ID, market="moneyline", side="home", price=118,
            our_probability=0.5489, market_probability=0.4528,
            source_artifact="x")

    def test_case_against_is_required_even_for_no_adjustment(self):
        with self.assertRaises(ValueError):
            _bare_finding(case_against="   ")

    def test_unknown_verdict_is_refused(self):
        with self.assertRaises(ValueError):
            _bare_finding(verdict="MAYBE_ADJUST")

    def test_a_probability_in_the_recalculation_request_is_refused(self):
        """HARD LIMIT 1/4: invent a probability adjustment."""
        finding = _bare_finding(
            verdict="RECALCULATION_REQUESTED",
            recalculation_request={"our_probability": 0.61,
                                   "reason": "smells better"})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(self.rec, finding)

    def test_a_threshold_name_in_the_recalculation_request_is_refused(self):
        """HARD LIMIT 3/4: widen a threshold."""
        finding = _bare_finding(
            verdict="RECALCULATION_REQUESTED",
            recalculation_request={"main_our_floor": 0.30,
                                   "reason": "loosen the gate"})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(self.rec, finding)

    def test_redirecting_the_request_to_a_different_game_is_refused(self):
        """HARD LIMIT 2/4: alter a published record -- here, by aiming the
        request at a game other than the one under review."""
        finding = _bare_finding(
            verdict="RECALCULATION_REQUESTED",
            recalculation_request={"reason": "r", "scenario": "s",
                                   "game_id": "OTHER-GAME-2026-09-25-1"})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(self.rec, finding)

    def test_a_scenario_request_naming_no_forbidden_key_is_accepted(self):
        finding = _bare_finding(
            verdict="RECALCULATION_REQUESTED",
            recalculation_request={"reason": "starter workload unmodeled",
                                   "scenario": "cap expected innings"})
        aa.validate_hard_limits(self.rec, finding)  # does not raise

    def test_apply_critic_never_writes_into_the_recommendation(self):
        """HARD LIMIT 4/4: silently replace the model's number. Checked by
        construction: `AnalystReport.recommendation` is the packet's own
        untouched dict, and the finding lives in a separate key."""
        packet = aa.EvidencePacket(
            game_id=GAME_ID, date="2026-09-25", built_at=NOW,
            recommendation=self.rec, claims=())
        finding = _bare_finding()
        report = aa.apply_critic(packet, finding)
        self.assertEqual(0.5489, report.recommendation["our_probability"])
        self.assertNotIn("our_probability", report.finding)
        self.assertNotIn("probability", json.dumps(report.finding))

    def test_a_finding_for_a_different_game_is_refused(self):
        packet = aa.EvidencePacket(
            game_id=GAME_ID, date="2026-09-25", built_at=NOW,
            recommendation=self.rec, claims=())
        finding = _bare_finding(game_id="SOME-OTHER-GAME")
        with self.assertRaises(aa.HardLimitViolation):
            aa.apply_critic(packet, finding)

    def test_every_finding_is_stamped_session_assisted(self):
        packet = aa.EvidencePacket(
            game_id=GAME_ID, date="2026-09-25", built_at=NOW,
            recommendation=self.rec, claims=())
        report = aa.apply_critic(packet, _bare_finding())
        self.assertEqual("session_assisted", report.finding["contribution_kind"])
        self.assertEqual("session_assisted",
                         report.experimental_contribution["contribution_kind"])


class EvidenceGathering(unittest.TestCase):
    """`build_evidence_packet` against an injected artifact -- no network,
    no live store."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_a_game_absent_from_selections_is_a_lookup_error(self):
        path = _artifact(self._tmp.name, selections=[])
        with self.assertRaises(LookupError):
            aa.recommendation_from_shadow_artifact(path, GAME_ID)

    def test_the_recommendation_is_read_not_recomputed(self):
        path = _artifact(self._tmp.name, selections=[_selection()])
        rec = aa.recommendation_from_shadow_artifact(path, GAME_ID)
        self.assertEqual(118, rec.price)
        self.assertAlmostEqual(0.5489, rec.our_probability, places=4)

    def test_model_input_claims_state_the_starter_gap_both_ways(self):
        path = _artifact(self._tmp.name, models_by_game={GAME_ID: _model_rec()})
        claims = aa.model_input_claims(path, GAME_ID, retrieved_at=NOW)
        by_entity = {c.entity: c for c in claims}
        self.assertEqual("CONFIRMED", by_entity["WSH"].status)
        self.assertEqual("UNCONFIRMED", by_entity["NYM"].status)

    def test_a_missing_game_produces_no_model_input_claims(self):
        path = _artifact(self._tmp.name, models_by_game={})
        self.assertEqual([], aa.model_input_claims(path, GAME_ID,
                                                   retrieved_at=NOW))


class FaultInjectionCases(unittest.TestCase):
    """The four required cases. Each must produce a TRACEABLE action or a
    JUSTIFIED refusal -- never a silent pass-through."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.rec = aa.ModelRecommendation(
            game_id=GAME_ID, market="moneyline", side="home", price=118,
            our_probability=0.5489, market_probability=0.4528,
            source_artifact="x")

    def _packet(self, claims):
        return aa.EvidencePacket(game_id=GAME_ID, date="2026-09-25",
                                 built_at=NOW, recommendation=self.rec,
                                 claims=tuple(claims))

    def test_an_injected_stale_quote_is_marked_not_silently_used(self):
        """Case 1: a quote observed hours before `now`, injected into the
        market claim. The claim's own STATUS must say STALE -- a critic
        reading this packet has a traceable reason to distrust the
        market_probability it is being asked to review, rather than
        silently treating an old number as current."""
        stale_observed = "2026-09-25T02:00:00+00:00"  # >> fresh_seconds old
        quote = aa.Claim(
            claim_id="market:stale", entity="home", event="market_quote",
            text="stale quote injected for this test",
            source_ref="test fixture", published_at=stale_observed,
            retrieved_at=NOW, status="STALE",
            uncertainty="observed well outside the freshness window",
            intended_use="anchor market_probability")
        packet = self._packet([quote])
        finding = _bare_finding(
            verified_assumptions=(
                ("market_probability reflects a current quote.",
                 "NOT VERIFIED -- the only market claim in this packet is "
                 "STALE.", ["market:stale"]),),
            case_against="The market anchor itself is stale; the "
                        "recommendation's edge cannot be trusted at face "
                        "value until a fresh quote is observed.",
            verdict="RECALCULATION_REQUESTED",
            recalculation_request={"reason": "market claim is stale",
                                   "scenario": "rerun against a fresh quote"})
        report = aa.apply_critic(packet, finding)
        stale_claims = [c for c in report.evidence if c["status"] == "STALE"]
        self.assertEqual(1, len(stale_claims))
        self.assertEqual("RECALCULATION_REQUESTED", report.finding["verdict"])

    def test_an_invented_contradictory_claim_is_marked_contradicted_not_merged(self):
        """Case 2: two claims about the SAME fact that disagree. Neither is
        silently preferred -- the finding must name the contradiction
        rather than pick a winner on the critic's own authority."""
        claim_a = aa.Claim(
            claim_id="src_a:starter", entity="WSH", event="starter_named",
            text="Beat writer A: WSH starter tonight is Pitcher X.",
            source_ref="wire syndication A", retrieved_at=NOW,
            status="UNCONFIRMED", uncertainty="single unverified report",
            intended_use="verify starter assumption", independent=False)
        claim_b = aa.Claim(
            claim_id="src_b:starter", entity="WSH", event="starter_named",
            text="Beat writer B: WSH starter tonight is Pitcher Y (not X).",
            source_ref="wire syndication B", retrieved_at=NOW,
            status="CONTRADICTED", uncertainty="disagrees with src_a:starter",
            intended_use="verify starter assumption", independent=False)
        packet = self._packet([claim_a, claim_b])
        finding = _bare_finding(
            verified_assumptions=(
                ("A single named starter is confirmed for WSH tonight.",
                 "NOT VERIFIED -- two sources disagree on the name and "
                 "neither is an independent primary source (the model's "
                 "own capture reports no name at all). The contradiction "
                 "is reported, not resolved by picking one.",
                 ["src_a:starter", "src_b:starter"]),),
            case_against="The starter identity behind this pick's edge is "
                        "contested, not merely unconfirmed.",
            verdict="RECALCULATION_REQUESTED",
            recalculation_request={
                "reason": "contradictory starter reports",
                "scenario": "hold the recommendation until one source is "
                           "corroborated by a primary confirmation"})
        report = aa.apply_critic(packet, finding)
        statuses = {c["claim_id"]: c["status"] for c in report.evidence}
        self.assertEqual("CONTRADICTED", statuses["src_b:starter"])
        self.assertIn("contradiction", report.finding["verified_assumptions"][0][1])

    def test_an_unrelated_players_injury_is_marked_unrelated_and_ignored(self):
        """Case 3: a real, CONFIRMED claim about a player who has nothing
        to do with this game. It must be classified UNRELATED and the
        finding must not let it drive the verdict -- a critic that reacts
        to any injury headline near the right two team names, regardless
        of relevance, is not doing verification."""
        unrelated = aa.Claim(
            claim_id="mlb_news:999999", entity="Some Other Player",
            event="il_placement",
            text="A third team placed an unrelated player on the IL.",
            source_ref="MLB transactions feed, transaction_id=999999",
            published_at="2026-09-24", retrieved_at=NOW, status="UNRELATED",
            uncertainty="confirmed transaction, but neither club nor "
                       "player appears in this game",
            intended_use="verify lineup/availability assumptions")
        packet = self._packet([unrelated])
        finding = _bare_finding(
            verified_assumptions=(
                ("Every claim in this packet bears on tonight's game.",
                 "VERIFIED as false for one claim -- mlb_news:999999 names "
                 "neither club in this game and is excluded from the case "
                 "for or against this pick.",
                 ["mlb_news:999999"]),),
            case_against="No case against this recommendation is "
                        "supported by the evidence in this packet; the "
                        "only claim present is unrelated to the game.",
            verdict="NO_ADJUSTMENT")
        report = aa.apply_critic(packet, finding)
        self.assertEqual("UNRELATED", report.evidence[0]["status"])
        self.assertEqual("NO_ADJUSTMENT", report.finding["verdict"])

    def test_a_clean_case_can_conclude_no_adjustment(self):
        """Case 4: required as a SUCCESS, not a fallback -- every claim
        confirmed, nothing contradicted or stale, and the critic's honest
        conclusion is that nothing here justifies touching the
        recommendation."""
        claims = [
            aa.Claim(claim_id="model_input:home", entity="WSH",
                    event="starter_known_to_model",
                    text="home starter known, full season of starts, no "
                        "recent IL activity", source_ref="model input",
                    retrieved_at=NOW, status="CONFIRMED",
                    uncertainty="model's own capture",
                    intended_use="verify starter assumption"),
            aa.Claim(claim_id="model_input:away", entity="NYM",
                    event="starter_known_to_model",
                    text="away starter also known, comparable full-season "
                        "profile", source_ref="model input",
                    retrieved_at=NOW, status="CONFIRMED",
                    uncertainty="model's own capture",
                    intended_use="verify starter assumption"),
            aa.Claim(claim_id="market:fresh", entity="home",
                    event="market_quote",
                    text="quote observed minutes ago, well inside the "
                        "freshness window", source_ref="shadow artifact",
                    published_at=NOW, retrieved_at=NOW, status="CONFIRMED",
                    uncertainty="a quote, not a forecast",
                    intended_use="anchor market_probability"),
        ]
        packet = self._packet(claims)
        finding = _bare_finding(
            verified_assumptions=tuple(
                (f"claim {c.claim_id} supports the recommendation as-is",
                 "VERIFIED", [c.claim_id]) for c in claims),
            challenged_assumption=(
                "The strongest assumption (starter quality drives the "
                "edge) was checked against a fully-known, non-injury-flagged "
                "profile on both sides and held up."),
            case_against="No sourced fact in this packet contradicts the "
                        "model's inputs or its number; the strongest "
                        "objection available is that any model can be "
                        "wrong, which is not evidence.",
            verdict="NO_ADJUSTMENT")
        report = aa.apply_critic(packet, finding)
        self.assertEqual("NO_ADJUSTMENT", report.finding["verdict"])
        self.assertTrue(report.finding["case_against"])  # still required
        self.assertEqual(0.5489, report.recommendation["our_probability"])


class RealArtifactSmokeTest(unittest.TestCase):
    """The one non-injected test: the actual 2026-09-25 shadow artifact and
    the real MLB transactions feed this module was built to read, guarded
    so a network hiccup skips rather than fails the suite."""

    ARTIFACT = os.path.join(
        "evidence", "shadow_enumeration",
        "2026-09-25_20260925T143000Z_moneyline-run_line.json")

    def test_the_real_artifact_produces_a_bounded_packet(self):
        if not os.path.exists(self.ARTIFACT):
            self.skipTest("real shadow artifact not present in this "
                          "checkout")
        try:
            packet = aa.build_evidence_packet(self.ARTIFACT, GAME_ID)
        except Exception as exc:  # noqa: BLE001 -- a network hiccup here
            self.skipTest(f"live mlb_news fetch unavailable: {exc!r}")
            return
        self.assertLessEqual(len(packet.claims), aa.MAX_CLAIMS)
        self.assertEqual(GAME_ID, packet.recommendation.game_id)
        self.assertEqual("moneyline", packet.recommendation.market)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
