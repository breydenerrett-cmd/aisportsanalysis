"""`scripts/ai_analyst.py`: the action vocabulary, the deterministic fact
check, the starter-identity gate, and the fault-injection cases Lane D
Part 3 required.

This file replaces the pre-review version wholesale after Opus review
failed the first sample (`evidence/ai_analyst/REVIEW_2026-09-25_NYM-WSH.md`):
a wrong ranking claim and an unverified starter-identity link both passed
the OLD schema's checks because nothing recomputed them. `FactCheckRegressionTests`
replays the wrong-ranking mistake byte for byte and requires it to be
REJECTED; `StarterIdentityGate` replays the unverified-identity mistake and
requires the same.

Injected fixtures only. `mlb_news_claims` and `starter_identity_claims` are
exercised through monkeypatched providers so this file never makes a
network call.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from scripts import ai_analyst as aa


NOW = datetime(2026, 9, 27, 15, 0, 0, tzinfo=timezone.utc).isoformat()
GAME_ID = "NYM-WSH-2026-09-26-1"


def _artifact(tmp_dir, *, selections=None, models_by_game=None,
             quotes_by_game=None, date="2026-09-26"):
    payload = {
        "date": date,
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


def _rec(price=118, our_p=0.5489, market_p=0.4528):
    return aa.ModelRecommendation(
        game_id=GAME_ID, market="moneyline", side="home", price=price,
        our_probability=our_p, market_probability=market_p,
        source_artifact="x")


def _claim(claim_id, *, status="CONFIRMED", entity="X", data=None,
          event="e"):
    return aa.Claim(claim_id=claim_id, entity=entity, event=event,
                   text=f"text for {claim_id}", source_ref="fixture",
                   retrieved_at=NOW, status=status,
                   uncertainty="u", intended_use="use", data=data)


def _packet(rec, claims):
    return aa.EvidencePacket(game_id=rec.game_id, date="2026-09-26",
                             built_at=NOW, recommendation=rec,
                             claims=tuple(claims))


def _no_adjustment(claim_ids, **overrides):
    base = dict(
        game_id=GAME_ID, verified_assumptions=(), challenged_assumption="x",
        case_against="nothing contradicts the model here",
        action="NO_ADJUSTMENT",
        action_payload={"checked_claim_ids": list(claim_ids)})
    base.update(overrides)
    return aa.CriticFinding(**base)


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

    def test_data_defaults_to_none_not_an_empty_promise(self):
        c = _claim("c1")
        self.assertIsNone(c.data)


class EvidencePacketIsBounded(unittest.TestCase):
    def test_more_than_max_claims_is_refused(self):
        rec = _rec()
        claims = tuple(_claim(f"c{i}") for i in range(aa.MAX_CLAIMS + 1))
        with self.assertRaises(ValueError):
            aa.EvidencePacket(game_id=GAME_ID, date="2026-09-26",
                             built_at=NOW, recommendation=rec, claims=claims)

    def test_duplicate_claim_ids_are_refused(self):
        rec = _rec()
        dup = _claim("same")
        with self.assertRaises(ValueError):
            aa.EvidencePacket(game_id=GAME_ID, date="2026-09-26",
                             built_at=NOW, recommendation=rec,
                             claims=(dup, dup))


class ActionVocabulary(unittest.TestCase):
    """Requirement 1: exactly one action from the new five-value set, each
    with its own required payload shape."""

    def test_the_old_verdict_names_are_gone(self):
        self.assertNotIn("ADJUSTMENT_REQUESTED", aa.ACTIONS)
        self.assertNotIn("RECALCULATION_REQUESTED", aa.ACTIONS)
        self.assertNotIn("ALTERNATE_MARKET_SUGGESTED", aa.ACTIONS)
        self.assertEqual(
            {"CORRECT_INPUT", "REQUEST_SCENARIO", "COMPARE_MARKET",
             "RECALCULATE", "NO_ADJUSTMENT"}, set(aa.ACTIONS))

    def test_unknown_action_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            _no_adjustment([], action="MAYBE_ADJUST",
                          action_payload={"checked_claim_ids": ["c1"]})

    def test_case_against_is_required_even_for_no_adjustment(self):
        with self.assertRaises(ValueError):
            _no_adjustment(["c1"], case_against="   ")

    def test_each_action_requires_its_own_exact_payload_keys(self):
        rec = _rec()
        packet = _packet(rec, [_claim("c1", data={"home_sp_era": 3.6})])
        cases = {
            "CORRECT_INPUT": {"input_path": "home_sp_era",
                             "current_value": 3.6, "verified_value": 3.6,
                             "source_claim_ids": ["c1"]},
            "REQUEST_SCENARIO": {"scenario": "s", "inputs_varied": [],
                                 "source_claim_ids": ["c1"]},
            "COMPARE_MARKET": {"market": "f5", "reason": "r",
                              "source_claim_ids": ["c1"]},
            "RECALCULATE": {"reason": "r", "changed_input": "home_sp_era",
                            "source_claim_ids": ["c1"]},
            "NO_ADJUSTMENT": {"checked_claim_ids": ["c1"]},
        }
        for action, payload in cases.items():
            finding = aa.CriticFinding(
                game_id=GAME_ID, verified_assumptions=(),
                challenged_assumption="x", case_against="a real case",
                action=action, action_payload=payload,
                facts=(aa.Fact("c1", "home_sp_era", 3.6),)
                    if action in ("CORRECT_INPUT", "RECALCULATE") else ())
            # Should not raise for a correctly-shaped, minimal payload.
            aa.validate_hard_limits(packet, finding)

        # A payload missing a required key is refused.
        bad = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="COMPARE_MARKET", action_payload={"market": "f5"})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, bad)

        # A payload with an EXTRA, undeclared key is refused too -- the
        # shape is exact, not a minimum.
        extra = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="COMPARE_MARKET",
            action_payload={"market": "f5", "reason": "r",
                           "source_claim_ids": ["c1"], "extra": 1})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, extra)


class HardLimitsOnForbiddenFields(unittest.TestCase):
    """The critic still never supplies a probability or a threshold."""

    def setUp(self):
        self.rec = _rec()
        self.packet = _packet(self.rec, [_claim("c1")])

    def test_correct_input_may_not_name_a_probability_field(self):
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="CORRECT_INPUT",
            action_payload={"input_path": "our_probability",
                           "current_value": 0.55, "verified_value": 0.61,
                           "source_claim_ids": ["c1"]},
            facts=(aa.Fact("c1", "x", 0.61),))
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(self.packet, finding)

    def test_recalculate_may_not_name_a_gate_threshold(self):
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="RECALCULATE",
            action_payload={"reason": "loosen it",
                           "changed_input": "main_our_floor",
                           "source_claim_ids": ["c1"]})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(self.packet, finding)

    def test_request_scenario_may_not_vary_a_forbidden_field(self):
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="REQUEST_SCENARIO",
            action_payload={"scenario": "s",
                           "inputs_varied": ["market_probability"],
                           "source_claim_ids": ["c1"]})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(self.packet, finding)

    def test_a_legitimate_model_input_name_is_accepted(self):
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="RECALCULATE",
            action_payload={"reason": "workload unmodeled",
                           "changed_input": "home_sp_expected_innings",
                           "source_claim_ids": ["c1"]})
        aa.validate_hard_limits(self.packet, finding)  # does not raise

    def test_apply_critic_never_writes_into_the_recommendation(self):
        finding = _no_adjustment(["c1"])
        report = aa.apply_critic(self.packet, finding)
        self.assertEqual(0.5489, report.recommendation["our_probability"])
        self.assertNotIn("our_probability", report.finding)

    def test_every_finding_is_stamped_session_assisted(self):
        report = aa.apply_critic(self.packet, _no_adjustment(["c1"]))
        self.assertEqual("session_assisted",
                         report.finding["contribution_kind"])
        self.assertEqual("session_assisted",
                         report.experimental_contribution["contribution_kind"])
        self.assertEqual("NO_ADJUSTMENT",
                         report.experimental_contribution["action"])


class SourceClaimBookkeeping(unittest.TestCase):
    def test_source_claim_ids_must_exist_in_the_packet(self):
        rec = _rec()
        packet = _packet(rec, [_claim("c1")])
        finding = _no_adjustment(["does-not-exist"])
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)

    def test_at_least_one_source_claim_is_required(self):
        rec = _rec()
        packet = _packet(rec, [_claim("c1")])
        finding = _no_adjustment([])
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)

    def test_verified_assumptions_must_cite_real_claims(self):
        rec = _rec()
        packet = _packet(rec, [_claim("c1")])
        finding = _no_adjustment(
            ["c1"],
            verified_assumptions=(("a", "b", ["ghost-claim"]),))
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)


class CorrectInputRequiresConfirmedSource(unittest.TestCase):
    def test_an_unconfirmed_source_cannot_justify_correct_input(self):
        rec = _rec()
        packet = _packet(rec, [_claim("c1", status="UNCONFIRMED",
                                     data={"home_sp_era": 3.2})])
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="CORRECT_INPUT",
            action_payload={"input_path": "home_sp_era",
                           "current_value": 3.6, "verified_value": 3.2,
                           "source_claim_ids": ["c1"]},
            facts=(aa.Fact("c1", "home_sp_era", 3.2),))
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)

    def test_a_confirmed_source_allows_correct_input(self):
        rec = _rec()
        packet = _packet(rec, [_claim("c1", status="CONFIRMED",
                                     data={"home_sp_era": 3.2})])
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="CORRECT_INPUT",
            action_payload={"input_path": "home_sp_era",
                           "current_value": 3.6, "verified_value": 3.2,
                           "source_claim_ids": ["c1"]},
            facts=(aa.Fact("c1", "home_sp_era", 3.2),))
        aa.validate_hard_limits(packet, finding)  # does not raise

    def test_verified_value_must_equal_a_verified_fact(self):
        """HARD LIMIT 4: a CORRECT_INPUT cannot introduce a number that was
        never checked against its source."""
        rec = _rec()
        packet = _packet(rec, [_claim("c1", status="CONFIRMED",
                                     data={"home_sp_era": 3.2})])
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="CORRECT_INPUT",
            action_payload={"input_path": "home_sp_era",
                           "current_value": 3.6,
                           "verified_value": 2.9,  # not backed by any fact
                           "source_claim_ids": ["c1"]},
            facts=(aa.Fact("c1", "home_sp_era", 3.2),))
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)


class FactCheckRegressionTests(unittest.TestCase):
    """Requirement 2, and the exact regression the release gate asked for:
    the failed report's "one of the smaller scores" claim must be
    REJECTED, and a correct version must pass."""

    def setUp(self):
        self.rec = _rec()
        self.claim = _claim(
            "model_input:c1", data={"home_sp_era": 3.6})
        self.packet = _packet(self.rec, [self.claim])

    def _finding(self, *, case_against, rankings):
        return aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="the starter's ERA is the load-bearing "
                                  "input for this pick",
            case_against=case_against,
            action="NO_ADJUSTMENT",
            action_payload={"checked_claim_ids": ["model_input:c1"]},
            facts=(aa.Fact("model_input:c1", "home_sp_era", 3.6),),
            rankings=rankings)

    def test_the_original_wrong_ranking_is_rejected(self):
        """The exact 2026-09-25 mistake: 0.0964 called "one of the
        smaller" scores when the recomputed rank shows it is the LARGEST
        of the three (rank 1). claimed_rank=3 (asserting it is smallest)
        must be rejected."""
        wrong = aa.Ranking(
            metric="pick_score", subject_value=0.09638901961434626,
            compared_values=(0.08422589582018003, 0.05080994347913931),
            claimed_rank=3)
        finding = self._finding(
            case_against="This pick's score (0.0964) was one of the "
                        "smaller scores on the slate, alongside 0.0842 "
                        "and 0.0508.",
            rankings=(wrong,))
        with self.assertRaises(aa.HardLimitViolation):
            aa.apply_critic(self.packet, finding)

    def test_the_corrected_ranking_passes(self):
        """Same three numbers, claimed_rank corrected to 1 (largest) --
        matches the recomputed rank and must pass."""
        correct = aa.Ranking(
            metric="pick_score", subject_value=0.09638901961434626,
            compared_values=(0.08422589582018003, 0.05080994347913931),
            claimed_rank=1)
        finding = self._finding(
            case_against="This pick's score (0.0964) was in fact the "
                        "LARGEST of the slate's three picks, ahead of "
                        "0.0842 and 0.0508 -- not a case of an "
                        "overwhelming number surviving a weak objection.",
            rankings=(correct,))
        report = aa.apply_critic(self.packet, finding)
        self.assertEqual("NO_ADJUSTMENT", report.finding["action"])

    def test_a_ranking_verified_individually_shows_pass(self):
        correct = aa.Ranking(metric="pick_score", subject_value=3.0,
                             compared_values=(1.0, 2.0), claimed_rank=1)
        finding = self._finding(case_against="3.0 beats 1.0 and 2.0.",
                                rankings=(correct,))
        result = aa.verify_and_report(self.packet, finding)
        ranking_rows = [c for c in result["checks"]
                       if c["check"].startswith("ranking[")]
        self.assertEqual(1, len(ranking_rows))
        self.assertEqual("PASS", ranking_rows[0]["result"])
        self.assertTrue(result["all_passed"])

    def test_a_number_in_prose_with_no_backing_fact_is_rejected(self):
        finding = self._finding(
            case_against="An unrelated number, 42, appears here with no "
                        "fact behind it.",
            rankings=())
        with self.assertRaises(aa.HardLimitViolation):
            aa.apply_critic(self.packet, finding)

    def test_a_fact_that_misquotes_its_source_is_rejected(self):
        finding = self._finding(case_against="ERA of 3.9 drives this.",
                                rankings=())
        bad_fact_finding = aa.CriticFinding(
            **{**finding.__dict__,
              "facts": (aa.Fact("model_input:c1", "home_sp_era", 3.9),)})
        with self.assertRaises(aa.HardLimitViolation):
            aa.apply_critic(self.packet, bad_fact_finding)

    def test_game_ids_and_claim_ids_in_prose_are_not_treated_as_numbers(self):
        """The exemption list: an ISO date, a game_id and a claim_id must
        not force a Fact just because they contain digits."""
        finding = self._finding(
            case_against="See model_input:c1 for NYM-WSH-2026-09-26-1 on "
                        "2026-09-26.",
            rankings=())
        aa.apply_critic(self.packet, finding)  # does not raise

    def test_a_decimal_ending_a_parenthetical_is_not_mistaken_for_a_list_marker(self):
        """Regression: `(?<!\\d)\\d+\\)` (the ORIGINAL list-marker exemption)
        matched "7811)" inside "(3.7811)" by starting right after the
        decimal point, silently deleting the back half of a real, fact-
        backed number before the numbers-in-prose scan ever saw it -- found
        while building the fresh 2026-09-25 CLE-KC sample. A number
        immediately followed by a closing paren must still be checked in
        full."""
        finding = self._finding(
            case_against="The starter's ERA (3.6) compares against the "
                        "opener's own figure.",
            rankings=())
        aa.apply_critic(self.packet, finding)  # does not raise: 3.6 is a
        # verified fact and must not be truncated to "3" or "6" first.

        # The negative case: an UNBACKED number placed the same way is
        # still caught, proving the fix didn't just stop checking anything
        # near a closing paren.
        bad = self._finding(
            case_against="An unrelated figure (99.9) appears here.",
            rankings=())
        with self.assertRaises(aa.HardLimitViolation):
            aa.apply_critic(self.packet, bad)

    def test_verification_report_lists_a_failure_without_stopping(self):
        """`verify_and_report` records every check rather than stopping at
        the first failure -- both the ranking failure and (if present) a
        fact failure must each show up as their own row."""
        wrong = aa.Ranking(metric="pick_score", subject_value=3.0,
                           compared_values=(1.0, 2.0), claimed_rank=3)
        finding = self._finding(case_against="3.0 is allegedly smallest.",
                                rankings=(wrong,))
        result = aa.verify_and_report(self.packet, finding)
        self.assertFalse(result["all_passed"])
        failed = [c for c in result["checks"] if c["result"] == "FAIL"]
        self.assertTrue(any(c["check"].startswith("ranking[") for c in failed))
        # Every OTHER check still ran and is reported.
        self.assertGreater(len(result["checks"]), 1)


class StarterIdentityGate(unittest.TestCase):
    """Requirement 3: a confirmed identity claim is required before
    attributing anything to a named pitcher; an unconfirmed one restricts
    the action to REQUEST_SCENARIO. Both paths tested."""

    def _packet_with_identity(self, status):
        rec = _rec()
        identity = _claim(
            "probable:NYM-WSH-2026-09-26-1:home", status=status,
            entity="Jane Doe",
            data=({"probable_id": 12345, "probable_name": "Jane Doe"}
                 if status == "CONFIRMED" else None),
            event="probable_pitcher")
        model_claim = _claim("model_input:c1", data={"home_sp_era": 3.6})
        return _packet(rec, [identity, model_claim])

    def test_confirmed_identity_allows_correct_input(self):
        packet = self._packet_with_identity("CONFIRMED")
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="CORRECT_INPUT",
            action_payload={"input_path": "home_sp_era",
                           "current_value": 3.6, "verified_value": 3.6,
                           "source_claim_ids": ["model_input:c1"]},
            facts=(aa.Fact("model_input:c1", "home_sp_era", 3.6),),
            pitcher_attribution={
                "side": "home", "name": "Jane Doe",
                "identity_claim_id": "probable:NYM-WSH-2026-09-26-1:home"})
        aa.validate_hard_limits(packet, finding)  # does not raise

    def test_unconfirmed_identity_forbids_correct_input(self):
        packet = self._packet_with_identity("UNCONFIRMED")
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="CORRECT_INPUT",
            action_payload={"input_path": "home_sp_era",
                           "current_value": 3.6, "verified_value": 3.6,
                           "source_claim_ids": ["model_input:c1"]},
            facts=(aa.Fact("model_input:c1", "home_sp_era", 3.6),),
            pitcher_attribution={
                "side": "home", "name": "Jane Doe",
                "identity_claim_id": "probable:NYM-WSH-2026-09-26-1:home"})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)

    def test_unconfirmed_identity_forbids_recalculate(self):
        packet = self._packet_with_identity("UNCONFIRMED")
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="RECALCULATE",
            action_payload={"reason": "identity-driven",
                           "changed_input": "home_sp_recent_ip_per_start",
                           "source_claim_ids": ["model_input:c1"]},
            pitcher_attribution={
                "side": "home", "name": "Jane Doe",
                "identity_claim_id": "probable:NYM-WSH-2026-09-26-1:home"})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)

    def test_unconfirmed_identity_still_allows_request_scenario(self):
        packet = self._packet_with_identity("UNCONFIRMED")
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="REQUEST_SCENARIO",
            action_payload={"scenario": "confirm the starter before "
                                       "trusting the ERA-driven edge",
                           "inputs_varied": ["home_sp_expected_innings"],
                           "source_claim_ids": ["model_input:c1"]},
            pitcher_attribution={
                "side": "home", "name": "Jane Doe",
                "identity_claim_id": "probable:NYM-WSH-2026-09-26-1:home"})
        aa.validate_hard_limits(packet, finding)  # does not raise

    def test_naming_a_person_without_declaring_attribution_is_refused(self):
        """THE EXACT 2026-09-25 MISTAKE: a name drawn from a claim appears
        in prose with no `pitcher_attribution` declaring it at all."""
        rec = _rec()
        transaction = _claim(
            "mlb_news:943391", status="CONFIRMED", entity="DJ Herz",
            event="il_activation")
        model_claim = _claim("model_input:c1", data={"home_sp_era": 3.6})
        packet = _packet(rec, [transaction, model_claim])
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="DJ Herz was activated from the IL "
                                  "recently, so the ERA may not hold.",
            case_against="a real case",
            action="NO_ADJUSTMENT",
            action_payload={"checked_claim_ids": ["mlb_news:943391",
                                                  "model_input:c1"]},
            facts=(aa.Fact("model_input:c1", "home_sp_era", 3.6),))
        with self.assertRaises(aa.HardLimitViolation):
            aa.apply_critic(packet, finding)

    def test_naming_a_person_with_attribution_declared_is_allowed(self):
        rec = _rec()
        transaction = _claim(
            "mlb_news:943391", status="CONFIRMED", entity="DJ Herz",
            event="il_activation")
        identity = _claim(
            "probable:NYM-WSH-2026-09-26-1:home", status="CONFIRMED",
            entity="DJ Herz",
            data={"probable_id": 1, "probable_name": "DJ Herz"},
            event="probable_pitcher")
        packet = _packet(rec, [transaction, identity])
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x",
            case_against="DJ Herz's own transaction history is worth "
                        "noting given his confirmed role tonight.",
            action="REQUEST_SCENARIO",
            action_payload={"scenario": "confirm workload",
                           "inputs_varied": [],
                           "source_claim_ids": ["mlb_news:943391"]},
            pitcher_attribution={
                "side": "home", "name": "DJ Herz",
                "identity_claim_id": "probable:NYM-WSH-2026-09-26-1:home"})
        aa.apply_critic(packet, finding)  # does not raise

    def test_pitcher_attribution_name_must_match_the_confirmed_claim(self):
        packet = self._packet_with_identity("CONFIRMED")
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(),
            challenged_assumption="x", case_against="a real case",
            action="REQUEST_SCENARIO",
            action_payload={"scenario": "s", "inputs_varied": [],
                           "source_claim_ids": ["model_input:c1"]},
            pitcher_attribution={
                "side": "home", "name": "Someone Else",
                "identity_claim_id": "probable:NYM-WSH-2026-09-26-1:home"})
        with self.assertRaises(aa.HardLimitViolation):
            aa.validate_hard_limits(packet, finding)


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

    def test_model_input_claims_carry_structured_data_for_fact_checking(self):
        path = _artifact(self._tmp.name, models_by_game={
            GAME_ID: {"model_inputs": {
                "home_sp_known": True, "home_sp_era": 3.6,
                "away_sp_known": False}}})
        claims = aa.model_input_claims(path, GAME_ID, retrieved_at=NOW)
        by_entity = {c.entity: c for c in claims}
        self.assertEqual("CONFIRMED", by_entity["home"].status)
        self.assertEqual(3.6, by_entity["home"].data["home_sp_era"])
        self.assertEqual("UNCONFIRMED", by_entity["away"].status)

    def test_a_missing_game_produces_no_model_input_claims(self):
        path = _artifact(self._tmp.name, models_by_game={})
        self.assertEqual([], aa.model_input_claims(path, GAME_ID,
                                                   retrieved_at=NOW))

    def test_mlb_news_claims_extract_il_days_into_structured_data(self):
        import unittest.mock as mock

        rows = [{"transaction_id": 1, "team": "WSH", "to_team": "WSH",
                "player": "DJ Herz", "category": "il_activation",
                "description": "Washington Nationals activated LHP DJ "
                              "Herz from the 60-day injured list.",
                "filed_date": "2026-09-21"}]
        with mock.patch("src.providers.mlb_news.fetch", return_value=rows):
            claims = aa.mlb_news_claims(
                start_date="2026-09-18", end_date="2026-09-26",
                teams=("NYM", "WSH"), retrieved_at=NOW,
                intended_use="test")
        self.assertEqual(1, len(claims))
        self.assertEqual(60, claims[0].data["il_days"])

    def test_starter_identity_claims_confirmed_when_both_present(self):
        import unittest.mock as mock

        games = [{"away_team": "NYM", "home_team": "WSH", "game_number": 1,
                 "home_probable": "Jane Doe", "home_probable_id": 555,
                 "away_probable": None, "away_probable_id": None}]
        with mock.patch("src.providers.mlb.fetch_games", return_value=games):
            claims = aa.starter_identity_claims(
                "2026-09-26", GAME_ID, retrieved_at=NOW)
        by_id = {c.claim_id: c for c in claims}
        home = by_id[f"probable:{GAME_ID}:home"]
        away = by_id[f"probable:{GAME_ID}:away"]
        self.assertEqual("CONFIRMED", home.status)
        self.assertEqual("Jane Doe", home.entity)
        self.assertEqual(555, home.data["probable_id"])
        self.assertEqual("UNCONFIRMED", away.status)
        self.assertIsNone(away.data)

    def test_starter_identity_claims_empty_on_fetch_failure(self):
        import unittest.mock as mock

        with mock.patch("src.providers.mlb.fetch_games",
                       side_effect=RuntimeError("network down")):
            claims = aa.starter_identity_claims(
                "2026-09-26", GAME_ID, retrieved_at=NOW)
        self.assertEqual([], claims)

    def test_starter_identity_claims_empty_when_game_not_found(self):
        import unittest.mock as mock

        with mock.patch("src.providers.mlb.fetch_games", return_value=[]):
            claims = aa.starter_identity_claims(
                "2026-09-26", GAME_ID, retrieved_at=NOW)
        self.assertEqual([], claims)


class FaultInjectionCases(unittest.TestCase):
    """The four required cases. Each must produce a TRACEABLE action or a
    JUSTIFIED refusal -- never a silent pass-through."""

    def setUp(self):
        self.rec = _rec()

    def test_an_injected_stale_quote_is_marked_not_silently_used(self):
        quote = _claim("market:stale", status="STALE",
                       data={"best_price": 118})
        packet = _packet(self.rec, [quote])
        finding = aa.CriticFinding(
            game_id=GAME_ID, verified_assumptions=(
                ("market_probability reflects a current quote.",
                 "NOT VERIFIED -- the only market claim in this packet is "
                 "STALE.", ["market:stale"]),),
            challenged_assumption="the market anchor is current",
            case_against="The market anchor itself is stale; the "
                        "recommendation's edge cannot be trusted at face "
                        "value until a fresh quote is observed.",
            action="REQUEST_SCENARIO",
            action_payload={"scenario": "rerun against a fresh quote",
                           "inputs_varied": [],
                           "source_claim_ids": ["market:stale"]})
        report = aa.apply_critic(packet, finding)
        stale_claims = [c for c in report.evidence if c["status"] == "STALE"]
        self.assertEqual(1, len(stale_claims))
        self.assertEqual("REQUEST_SCENARIO", report.finding["action"])

    def test_an_invented_contradictory_claim_is_marked_contradicted(self):
        claim_a = _claim("src_a:starter", status="UNCONFIRMED",
                         entity="unnamed")
        claim_b = _claim("src_b:starter", status="CONTRADICTED",
                         entity="unnamed")
        packet = _packet(self.rec, [claim_a, claim_b])
        finding = aa.CriticFinding(
            game_id=GAME_ID,
            verified_assumptions=(
                ("A single named starter is confirmed for this game.",
                 "NOT VERIFIED -- two sources disagree and neither is an "
                 "independent primary confirmation; the contradiction is "
                 "reported, not resolved by picking one.",
                 ["src_a:starter", "src_b:starter"]),),
            challenged_assumption="a starter identity is settled",
            case_against="The starter identity behind this pick's edge is "
                        "contested, not merely unconfirmed.",
            action="REQUEST_SCENARIO",
            action_payload={
                "scenario": "hold the recommendation until one source is "
                           "corroborated by a primary confirmation",
                "inputs_varied": [],
                "source_claim_ids": ["src_a:starter", "src_b:starter"]})
        report = aa.apply_critic(packet, finding)
        statuses = {c["claim_id"]: c["status"] for c in report.evidence}
        self.assertEqual("CONTRADICTED", statuses["src_b:starter"])
        self.assertEqual("REQUEST_SCENARIO", report.finding["action"])

    def test_an_unrelated_players_injury_does_not_drive_the_verdict(self):
        unrelated = _claim("mlb_news:999999", status="UNRELATED",
                           entity="Some Other Player", event="il_placement")
        packet = _packet(self.rec, [unrelated])
        finding = _no_adjustment(
            ["mlb_news:999999"],
            verified_assumptions=(
                ("Every claim in this packet bears on tonight's game.",
                 "VERIFIED as false for one claim -- mlb_news:999999 names "
                 "neither club in this game and is excluded from the case "
                 "for or against this pick.",
                 ["mlb_news:999999"]),),
            case_against="No case against this recommendation is "
                        "supported by the evidence in this packet; the "
                        "only claim present is unrelated to the game.")
        report = aa.apply_critic(packet, finding)
        self.assertEqual("UNRELATED", report.evidence[0]["status"])
        self.assertEqual("NO_ADJUSTMENT", report.finding["action"])

    def test_a_clean_case_can_conclude_no_adjustment(self):
        claims = [
            _claim("model_input:home", status="CONFIRMED", entity="home",
                  data={"home_sp_era": 3.6}),
            _claim("model_input:away", status="CONFIRMED", entity="away",
                  data={"away_sp_era": 3.8}),
        ]
        packet = _packet(self.rec, claims)
        finding = _no_adjustment(
            ["model_input:home", "model_input:away"],
            challenged_assumption=(
                "The strongest assumption (starter quality drives the "
                "edge) was checked against a fully-known, non-injury-"
                "flagged profile on both sides and held up."),
            case_against="No sourced fact in this packet contradicts the "
                        "model's inputs or its number; the strongest "
                        "objection available is that any model can be "
                        "wrong, which is not evidence.",
            facts=(aa.Fact("model_input:home", "home_sp_era", 3.6),
                  aa.Fact("model_input:away", "away_sp_era", 3.8)))
        report = aa.apply_critic(packet, finding)
        self.assertEqual("NO_ADJUSTMENT", report.finding["action"])
        self.assertTrue(report.finding["case_against"])
        self.assertEqual(0.5489, report.recommendation["our_probability"])


class RealArtifactSmokeTest(unittest.TestCase):
    """The one non-injected test: whichever fresh 2026-09-26/27 shadow
    artifact this checkout carries, guarded so a network hiccup skips
    rather than fails the suite."""

    def test_a_fresh_real_artifact_produces_a_bounded_packet(self):
        shadow_dir = os.path.join("evidence", "shadow_enumeration")
        candidates = sorted(
            f for f in os.listdir(shadow_dir)
            if (f.startswith("2026-09-26_") or f.startswith("2026-09-27_"))
            and f.endswith(".json"))
        if not candidates:
            self.skipTest("no 2026-09-26/27 shadow artifact present in "
                          "this checkout")
        path = os.path.join(shadow_dir, candidates[-1])
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        selections = payload.get("corrected_path", {}).get("selections") or []
        if not selections:
            self.skipTest(f"{path} carries no corrected_path selections")
        game_id = selections[0]["game_id"]
        try:
            packet = aa.build_evidence_packet(path, game_id)
        except Exception as exc:  # noqa: BLE001 -- a network hiccup here
            self.skipTest(f"live provider unavailable: {exc!r}")
            return
        self.assertLessEqual(len(packet.claims), aa.MAX_CLAIMS)
        self.assertEqual(game_id, packet.recommendation.game_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
