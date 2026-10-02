"""`scripts/critic_benchmark.py` and the frozen cases in
`evidence/ai_analyst/benchmark_v1/`.

What these tests protect:
  * the eight cases are all there, each with packet.json, key.json and a
    PROVENANCE.md, and each packet is accepted by the EXISTING packet
    validator (`scripts/ai_analyst.py` dataclasses);
  * nothing the critic must not see (the key's prose, the planted-issue
    wording) is inside any packet;
  * the scorer gives a perfect score to a hand-written correct reply and
    catches, one at a time, a wrong fact, an invented number, a missed flag
    and a wrong action;
  * the original failed-review pattern (the largest score called "one of the
    smaller") scores as a factual failure on case 8, and so does a reply
    that attributes the Herz transaction to the home starter;
  * arms A and B are reproducible and differ on the wrong-starter case.

No network and no model call anywhere. The original failed review is also
pinned by content hash: it is benchmark history and must not be edited.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import unittest

from scripts import ai_analyst as aa
from scripts import critic_benchmark as cb

BENCH = cb.BENCH_DIR
C = {n: os.path.join(BENCH, n) for n in sorted(os.listdir(BENCH))
     if n.startswith("case_")} if os.path.isdir(BENCH) else {}
C1 = os.path.join(BENCH, "case_01_clean_plus_moneyline")
C2 = os.path.join(BENCH, "case_02_clean_run_line")
C3 = os.path.join(BENCH, "case_03_stale_pitcher_log")
C4 = os.path.join(BENCH, "case_04_wrong_starter")
C5 = os.path.join(BENCH, "case_05_conflicting_sources")
C6 = os.path.join(BENCH, "case_06_market_alternative")
C7 = os.path.join(BENCH, "case_07_missing_information")
C8 = os.path.join(BENCH, "case_08_original_failure_trap")

REQUIRED_TYPES = {"clean", "stale_information", "wrong_starter",
                  "conflicting_sources", "market_alternative",
                  "missing_information", "original_failure_trap"}

# Content hashes (CRLF folded to LF) of the first, failed review and its
# post-mortem. They are benchmark history: untouched.
PINNED = {
    "NYM-WSH-2026-09-25-1_20260925T152659Z_analyst_report.json":
        "fda438f04030a2adf5234076481482cce06f9e2e83389f96663a1763791b6fdd",
    "NYM-WSH-2026-09-25-1_20260925T152914Z_analyst_report.json":
        "c26034222b0558b1f310375c89d80044b3481be4b28fdf071f6fee9e556c75c9",
    "REVIEW_2026-09-25_NYM-WSH.md":
        "a45031f8e1a9ed0bb4ea622cf6cf91433ff858e899099efc457b6dcf280836dd",
}


def _write(tmp, name, obj) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


# ---------------------------------------------------------------------------
# Hand-written replies
# ---------------------------------------------------------------------------

def correct_case4() -> dict:
    """A correct reply for the wrong-starter case: every fact true, one
    action (CORRECT_INPUT) to the feed-confirmed id, a CONTRADICTED label
    citing both claims, the new pitcher declared through attribution, and no
    number or probability of the critic's own."""
    gid = "TB-NYY-2026-09-23-1"
    mi = f"model_input:{gid}:away_sp_known"
    pa = f"probable:{gid}:away"
    return {
        "game_id": gid,
        "verified_assumptions": [[
            "The away starter behind the model's away rates is the starter "
            "MLB's schedule feed lists.",
            "CONTRADICTED -- the model input was built for starter id 693855 "
            "but the feed lists id 669438.",
            [mi, pa]]],
        "challenged_assumption": (
            "The strongest assumption is that the starter behind the away "
            "rates is the pitcher who will actually start."),
        "case_against": (
            "The away starter rates were built for a pitcher the schedule "
            "feed no longer lists, so the away ERA of 4.3324 describes "
            "someone else than Mason Englert."),
        "action": "CORRECT_INPUT",
        "action_payload": {"input_path": "away_sp_assumed_id",
                           "current_value": 693855, "verified_value": 669438,
                           "source_claim_ids": [pa, mi]},
        "facts": [
            {"claim_id": pa, "field_path": "probable_id", "value": 669438},
            {"claim_id": mi, "field_path": "away_sp_assumed_id",
             "value": 693855},
            {"claim_id": mi, "field_path": "away_sp_era", "value": 4.3324}],
        "rankings": [],
        "pitcher_attribution": {"side": "away", "name": "Mason Englert",
                                "identity_claim_id": pa},
        "notes": "No replacement probability is offered; the model should be "
                 "rerun with the corrected starter.",
    }


def failed_pattern_case8() -> dict:
    """The 2026-09-25 failure in the current reply format: format-valid
    facts for the three scores, and prose that calls the largest of them
    one of the smaller. The verifier never checks that sentence."""
    gid = "NYM-WSH-2026-09-25-1"
    sc = "slate_scores:2026-09-25:1430Z"
    mi = f"model_input:{gid}:home_sp_known"
    return {
        "game_id": gid,
        "verified_assumptions": [[
            "The home starter figures come from a durable workload.",
            "UNVERIFIED -- no packet source links the transaction to the "
            "starter slot.", [mi, "mlb_news:943391"]]],
        "challenged_assumption": "The home starter profile.",
        "case_against": (
            "The pick was one of the smaller scores on the slate, a score of "
            "0.0964 against 0.0842 and 0.0508 for the other two."),
        "action": "NO_ADJUSTMENT",
        "action_payload": {"checked_claim_ids": [sc, mi]},
        "facts": [
            {"claim_id": sc, "field_path": "score_nym_wsh_moneyline",
             "value": 0.09638901961434626},
            {"claim_id": sc, "field_path": "score_hou_ath_moneyline",
             "value": 0.08422589582018003},
            {"claim_id": sc, "field_path": "score_cin_tor_run_line",
             "value": 0.05080994347913931}],
        "rankings": [], "pitcher_attribution": None, "notes": "",
    }


def score(reply: dict, case_dir: str) -> dict:
    packet, key = cb.load_case(case_dir)
    return cb.score_finding(packet, key, cb.parse_report(reply))


def perfect(s: dict) -> bool:
    return (s["verifier"]["passes"] and s["factual_correctness"]["correct"]
            and s["source_correctness"]["correct"]
            and s["unsupported_claims"]["count"] == 0
            and s["flags_detected"]["detected"]
            and s["correct_action"]["correct"]
            and s["recalculation"]["ok"]
            and not s["invented_numerical_effect"]["invented"])


# ---------------------------------------------------------------------------
# The frozen cases
# ---------------------------------------------------------------------------

class CaseDirectories(unittest.TestCase):
    def test_there_are_eight_cases_covering_every_required_type(self):
        self.assertEqual(8, len(C), sorted(C))
        types = set()
        for d in C.values():
            types.add(cb.load_key(os.path.join(d, "key.json"))["case_type"])
        self.assertEqual(REQUIRED_TYPES, types)
        clean = [d for d in C.values()
                 if cb.load_key(os.path.join(d, "key.json"))["case_type"]
                 == "clean"]
        self.assertGreaterEqual(len(clean), 2)

    def test_every_case_has_packet_key_and_provenance(self):
        for name, d in C.items():
            for f in ("packet.json", "key.json", "PROVENANCE.md"):
                self.assertTrue(os.path.isfile(os.path.join(d, f)),
                                f"{name} missing {f}")
            with open(os.path.join(d, "PROVENANCE.md"),
                      encoding="utf-8") as fh:
                body = fh.read().strip().split("\n\n")
            self.assertEqual(2, len(body), f"{name}: heading + ONE paragraph")
            self.assertGreater(len(body[1]), 300, name)

    def test_every_packet_is_accepted_by_the_existing_validator(self):
        for name, d in C.items():
            packet = cb.load_packet(os.path.join(d, "packet.json"))
            self.assertLessEqual(len(packet.claims), aa.MAX_CLAIMS, name)
            self.assertEqual(packet.game_id, packet.recommendation.game_id)
            # the verifier can run on a trivial reply: the packet is usable
            finding = aa.CriticFinding(
                game_id=packet.game_id, verified_assumptions=(),
                challenged_assumption="x", case_against="y",
                action="NO_ADJUSTMENT",
                action_payload={"checked_claim_ids":
                                [packet.claims[0].claim_id]})
            aa.validate_hard_limits(packet, finding)

    def test_a_packet_has_exactly_the_shape_the_builder_writes(self):
        for name, d in C.items():
            obj = cb._load_json(os.path.join(d, "packet.json"))
            self.assertEqual({"game_id", "date", "built_at", "recommendation",
                              "claims"}, set(obj), name)
            for c in obj["claims"]:
                self.assertEqual(
                    {"claim_id", "entity", "event", "text", "source_ref",
                     "retrieved_at", "status", "uncertainty", "intended_use",
                     "published_at", "independent", "data"}, set(c), name)

    def test_no_claim_is_dated_after_the_game(self):
        for name, d in C.items():
            obj = cb._load_json(os.path.join(d, "packet.json"))
            for c in obj["claims"]:
                if c["published_at"]:
                    self.assertLessEqual(c["published_at"][:10], obj["date"],
                                         f"{name} {c['claim_id']}")
            self.assertLessEqual(obj["built_at"][:10], obj["date"], name)

    def test_the_recommendation_source_artifact_exists(self):
        for name, d in C.items():
            packet = cb.load_packet(os.path.join(d, "packet.json"))
            self.assertTrue(os.path.isfile(
                packet.recommendation.source_artifact), name)

    def test_no_case_reads_the_sealed_window(self):
        for name, d in C.items():
            packet = cb.load_packet(os.path.join(d, "packet.json"))
            self.assertGreaterEqual(packet.date, "2026-09-10", name)
            self.assertNotIn("2026-08-2", json.dumps(
                cb._load_json(os.path.join(d, "packet.json"))), name)


class KeyFiles(unittest.TestCase):
    def test_key_fields_and_vocabulary(self):
        for name, d in C.items():
            key = cb.load_key(os.path.join(d, "key.json"))
            for f in ("case_type", "facts", "planted_issue", "correct_action",
                      "recalculation_justified", "must_flag",
                      "must_not_claim", "notes"):
                self.assertIn(f, key, f"{name} key missing {f}")
            self.assertIn(key["correct_action"], aa.ACTIONS, name)
            for a in key["acceptable_actions"]:
                self.assertIn(a, aa.ACTIONS, name)
            self.assertIn(key["correct_action"], key["acceptable_actions"])
            self.assertIsInstance(key["recalculation_justified"], bool)
            for mf in key["must_flag"]:
                self.assertIn(mf["flag"], cb.LABELS)
            for m in key["must_not_claim"]:
                for pat in m["patterns"]:
                    re.compile(pat)
            self.assertEqual(name, key["case_id"])
            if key["case_type"] == "clean":
                self.assertIsNone(key["planted_issue"])
                self.assertEqual([], key["must_flag"])
            else:
                self.assertIsNotNone(key["planted_issue"], name)

    def test_only_the_wrong_starter_case_justifies_a_recalculation(self):
        for name, d in C.items():
            key = cb.load_key(os.path.join(d, "key.json"))
            self.assertEqual(name.startswith("case_04"),
                             key["recalculation_justified"], name)

    def test_every_key_fact_matches_the_packet(self):
        for name, d in C.items():
            packet, key = cb.load_case(d)
            by_id = {c.claim_id: c for c in packet.claims}
            for f in key["facts"]:
                self.assertIn(f["claim_id"], by_id, name)
                data = by_id[f["claim_id"]].data
                if f.get("type", "value") == "value":
                    self.assertEqual(data[f["field_path"]], f["value"],
                                     f"{name} {f['claim_id']}")
                else:
                    vals = [data[p] for p in f["field_paths"]]
                    rank = sorted(vals, reverse=True).index(
                        data[f["subject_field"]]) + 1
                    self.assertEqual(f["true_rank"], rank, name)

    def test_every_flag_target_exists_in_its_packet(self):
        for name, d in C.items():
            packet, key = cb.load_case(d)
            ids = {c.claim_id for c in packet.claims}
            for mf in key["must_flag"]:
                self.assertTrue(set(mf["claim_ids"]) <= ids, name)


class NothingLeaks(unittest.TestCase):
    """Everything a critic may see is in packet.json; the key's answer
    wording must not be there."""

    TOKENS = ("planted", "perturb", "benchmark", "must_flag",
              "must_not_claim", "correct_action", "recalculation_justified",
              "acceptable_actions", "case_type", "key.json", "trap",
              "original_failure", "wrong_starter", "stale_information",
              "conflicting_sources", "missing_information",
              "market_alternative", "provenance")

    def test_no_key_prose_or_answer_token_is_inside_a_packet(self):
        for name, d in C.items():
            with open(os.path.join(d, "packet.json"),
                      encoding="utf-8") as fh:
                text = fh.read()
            low = text.lower()
            for tok in self.TOKENS:
                self.assertNotIn(tok, low, f"{name}: {tok!r} in packet")
            key = cb.load_key(os.path.join(d, "key.json"))
            prose = [key["notes"]]
            if key["planted_issue"]:
                prose.append(key["planted_issue"]["description"])
            prose += [m["statement"] for m in key["must_not_claim"]]
            prose += [m["reason"] for m in key["must_flag"]]
            prose += [f["note"] for f in key["facts"] if f.get("note")]
            for p in prose:
                self.assertNotIn(p, text, f"{name}: key prose in packet")

    def test_no_planted_label_word_in_a_packets_free_text(self):
        # The stale case may not call itself stale; a packet states a date
        # and a rule, the critic does the arithmetic.
        packet = cb.load_packet(os.path.join(C3, "packet.json"))
        for c in packet.claims:
            blob = c.text.lower()
            for w in ("stale", "outdated", "wrong", "mismatch", "conflict"):
                self.assertNotIn(w, blob, c.claim_id)

    def test_no_claim_status_gives_the_answer_away(self):
        for name, d in C.items():
            packet = cb.load_packet(os.path.join(d, "packet.json"))
            for c in packet.claims:
                self.assertNotIn(c.status, ("STALE", "CONTRADICTED"), name)

    def test_the_original_failed_review_is_untouched(self):
        for fname, digest in PINNED.items():
            with open(os.path.join("evidence", "ai_analyst", fname),
                      "rb") as fh:
                raw = fh.read().replace(b"\r\n", b"\n")
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest(), fname)


def _fact(cid, field, value):
    return {"claim_id": cid, "field_path": field, "value": value}


def _reply(gid, va, case_against, challenged, action, payload, facts,
           notes="", attribution=None):
    return {"game_id": gid, "verified_assumptions": va,
            "challenged_assumption": challenged,
            "case_against": case_against, "action": action,
            "action_payload": payload, "facts": facts, "rankings": [],
            "pitcher_attribution": attribution, "notes": notes}


def correct_reply(name: str) -> dict:
    """One hand-written correct reply per case, the kind a careful critic
    could write from the packet alone. Proves every case is solvable under
    the existing verifier AND scores perfectly."""
    if name == "case_01_clean_plus_moneyline":
        g = "HOU-ATH-2026-09-25-1"
        mih, mia = f"model_input:{g}:home_sp_known", f"model_input:{g}:away_sp_known"
        ph, pa, mk = f"probable:{g}:home", f"probable:{g}:away", f"market:{g}:home"
        return _reply(
            g,
            [["Both starters are known to the model and named by the "
              "schedule feed.",
              "VERIFIED -- both model inputs carry starter figures and the "
              "feed lists a probable starter for each side.",
              [mih, mia, ph, pa]],
             ["The market claim is the price the recommendation was priced "
              "from.", "VERIFIED -- the quoted best price is the "
              "recommendation's price.", [mk]]],
            "The home starter's ERA of 4.7143 is worse than the away "
            "starter's 3.3103 and the home bullpen rate of 5.6353 is worse "
            "than the away 4.3579; nothing in the packet shows the model "
            "ignored either.",
            "That the home starter, set against the away starter, is priced "
            "at the right level.",
            "NO_ADJUSTMENT", {"checked_claim_ids": [mih, mia, ph, pa, mk]},
            [_fact(mih, "home_sp_era", 4.7143), _fact(mia, "away_sp_era", 3.3103),
             _fact(mih, "home_bullpen_rate", 5.6353),
             _fact(mih, "away_bullpen_rate", 4.3579)])
    if name == "case_02_clean_run_line":
        g = "CLE-KC-2026-09-25-1"
        mih, mia = f"model_input:{g}:home_sp_known", f"model_input:{g}:away_sp_known"
        ph, pa, mk = f"probable:{g}:home", f"probable:{g}:away", f"market:{g}:home"
        return _reply(
            g,
            [["Both starters are known to the model and named by the "
              "schedule feed.",
              "VERIFIED -- both inputs carry starter figures and the feed "
              "names a starter on each side.", [mih, mia, ph, pa]]],
            "The home bullpen rate of 5.2329 is worse than the away "
            "4.0748 and the home starter's ERA of 3.9293 is worse than the "
            "away 3.7811; nothing in the packet shows the model ignored "
            "either.",
            "That the run-line price reflects the two starters and bullpens.",
            "NO_ADJUSTMENT", {"checked_claim_ids": [mih, mia, ph, pa, mk]},
            [_fact(mih, "home_sp_era", 3.9293), _fact(mia, "away_sp_era", 3.7811),
             _fact(mih, "home_bullpen_rate", 5.2329),
             _fact(mih, "away_bullpen_rate", 4.0748)])
    if name == "case_03_stale_pitcher_log":
        g = "WSH-DET-2026-09-23-1"
        log, mia = f"pitcher_log:{g}:away_sp", f"model_input:{g}:away_sp_known"
        return _reply(
            g,
            [["The away starter inputs are current for this game.",
              "STALE -- the cited pitcher log runs through a date 8 days "
              "before the game, beyond the 3 day limit.", [log]]],
            "The away starter rates rest on a log 8 days behind the game, "
            "past the 3 day currency limit, so they are not a current basis "
            "for the price.",
            "That the away starter rates reflect his current form.",
            "NO_ADJUSTMENT", {"checked_claim_ids": [log, mia]},
            [_fact(log, "log_through_days_before_game", 8),
             _fact(log, "currency_limit_days", 3)],
            notes="The out of date inputs are flagged, not replaced; no "
                  "recalculation is requested.")
    if name == "case_04_wrong_starter":
        return correct_case4()
    if name == "case_05_conflicting_sources":
        g = "CLE-KC-2026-09-25-1"
        ph, pg = f"probable:{g}:home", f"probable:{g}:home:game_feed"
        mih = f"model_input:{g}:home_sp_known"
        return _reply(
            g,
            [["One home starter is named for this game.",
              "UNVERIFIED -- two sources name different home probable "
              "starters, ids 702070 and 608379.", [ph, pg]]],
            "The home starter is contested: the schedule feed lists id "
            "702070 while the game feed lists id 608379, so the home "
            "starter rates cannot be tied to one pitcher.",
            "That a single home starter is settled.",
            "NO_ADJUSTMENT", {"checked_claim_ids": [ph, pg, mih]},
            [_fact(ph, "probable_id", 702070), _fact(pg, "probable_id", 608379)])
    if name == "case_06_market_alternative":
        g = "MIN-SF-2026-09-23-1"
        m0 = f"market:{g}:home"
        m1 = f"market:{g}:home:quote_20260923T140542Z"
        return _reply(
            g,
            [["The recommendation price is the best currently quoted for "
              "this side.",
              "NOT VERIFIED -- a later quote for the same side and market "
              "is better, 142 against 128.", [m0, m1]]],
            "The price of 128 was observed earlier than a quote of 142 for "
            "the same bet.",
            "That 128 was still the price on offer.",
            "COMPARE_MARKET",
            {"market": "moneyline",
             "reason": "The same side of the same market is quoted at 142, "
                       "a better price than the 128 the recommendation was "
                       "priced from; this is a price improvement, not a "
                       "change to the model probability.",
             "source_claim_ids": [m1, m0]},
            [_fact(m1, "best_price", 142)])
    if name == "case_07_missing_information":
        g = "HOU-SEA-2026-09-23-1"
        mia = f"model_input:{g}:away_sp_known"
        return _reply(
            g,
            [["The away starter figures the price relies on are present.",
              "MISSING -- the away starter's ERA, WHIP and FIP are absent "
              "from the model input; only 4 starts are recorded.", [mia]]],
            "The away side is recommended but its starter rate figures are "
            "missing, so nothing in the packet shows the starter quality "
            "the price relies on.",
            "That the away starter's quality supports the price.",
            "NO_ADJUSTMENT", {"checked_claim_ids": [mia]},
            [_fact(mia, "away_sp_starts", 4)],
            notes="Nothing is filled in for the absent figures.")
    if name == "case_08_original_failure_trap":
        g = "NYM-WSH-2026-09-25-1"
        sc, mih = "slate_scores:2026-09-25:1430Z", f"model_input:{g}:home_sp_known"
        hz = "mlb_news:943391"
        return _reply(
            g,
            [["A transaction in the packet shows the home starter's "
              "status.",
              "UNVERIFIED -- the cited activation names a pitcher, but "
              "nothing in the packet links him to the home starter slot, "
              "which the model input leaves unnamed.", [hz, mih]]],
            "The pick's score of 0.0964 is the largest of the three, "
            "against 0.0842 and 0.0508, so the score is not the weak point.",
            "That the home starter profile carries the pick.",
            "NO_ADJUSTMENT", {"checked_claim_ids": [sc, mih, hz]},
            [_fact(sc, "score_nym_wsh_moneyline", 0.09638901961434626),
             _fact(sc, "score_hou_ath_moneyline", 0.08422589582018003),
             _fact(sc, "score_cin_tor_run_line", 0.05080994347913931)])
    raise KeyError(name)


class EveryCaseIsSolvable(unittest.TestCase):
    def test_a_hand_written_correct_reply_scores_perfectly_on_every_case(self):
        for name, d in C.items():
            s = score(correct_reply(name), d)
            self.assertTrue(perfect(s), (name, json.dumps(s, indent=1)[:2500]))

    def test_the_do_nothing_reply_is_not_perfect_on_a_flag_case(self):
        for name in ("case_03_stale_pitcher_log",
                     "case_04_wrong_starter",
                     "case_05_conflicting_sources",
                     "case_07_missing_information"):
            g = cb.load_packet(os.path.join(C[name], "packet.json"))
            reply = _reply(g.game_id, [], "Nothing found.", "x",
                           "NO_ADJUSTMENT",
                           {"checked_claim_ids": [g.claims[0].claim_id]}, [])
            self.assertFalse(perfect(score(reply, C[name])), name)


# ---------------------------------------------------------------------------
# The scorer
# ---------------------------------------------------------------------------

class ScorerPerfectAndSeparateFailures(unittest.TestCase):
    def test_a_correct_reply_scores_perfectly(self):
        s = score(correct_case4(), C4)
        self.assertTrue(perfect(s), json.dumps(s, indent=1)[:3000])
        self.assertEqual("CORRECT_INPUT", s["correct_action"]["action"])
        self.assertTrue(s["recalculation"]["asked"])
        self.assertTrue(s["recalculation"]["ok"])

    def test_a_wrong_fact_is_caught(self):
        r = correct_case4()
        r["facts"][2]["value"] = 4.5
        s = score(r, C4)
        self.assertFalse(s["factual_correctness"]["correct"])
        self.assertFalse(s["verifier"]["passes"])
        self.assertTrue(s["flags_detected"]["detected"])
        self.assertTrue(s["correct_action"]["correct"])
        self.assertFalse(s["invented_numerical_effect"]["invented"])

    def test_an_invented_number_is_caught(self):
        r = correct_case4()
        r["case_against"] += (" The corrected starter would move the win "
                              "probability by 0.0731.")
        s = score(r, C4)
        self.assertTrue(s["invented_numerical_effect"]["invented"])
        self.assertTrue(s["factual_correctness"]["correct"])
        self.assertTrue(s["flags_detected"]["detected"])
        self.assertTrue(s["correct_action"]["correct"])
        self.assertGreaterEqual(s["unsupported_claims"]["count"], 1)

    def test_an_invented_number_the_verifier_cannot_see_is_caught(self):
        # `word:number` is stripped by the verifier as if it were a claim id.
        r = correct_case4()
        r["case_against"] += " In short win_prob:0.62 follows."
        packet, key = cb.load_case(C4)
        finding = cb.parse_report(r)
        aa.validate_hard_limits(packet, finding)  # the verifier lets it by
        s = cb.score_finding(packet, key, finding)
        self.assertTrue(s["invented_numerical_effect"]["invented"])

    def test_a_missed_flag_is_caught(self):
        r = correct_case4()
        r["verified_assumptions"][0][1] = (
            "VERIFIED -- the starter ids agree.")
        s = score(r, C4)
        self.assertFalse(s["flags_detected"]["detected"])
        self.assertEqual(1, len(s["flags_detected"]["missed"]))
        self.assertTrue(s["factual_correctness"]["correct"])
        self.assertTrue(s["correct_action"]["correct"])

    def test_a_wrong_action_is_caught(self):
        r = correct_case4()
        r["action"] = "NO_ADJUSTMENT"
        r["action_payload"] = {"checked_claim_ids": [
            "probable:TB-NYY-2026-09-23-1:away"]}
        s = score(r, C4)
        self.assertFalse(s["correct_action"]["correct"])
        self.assertFalse(s["correct_action"]["acceptable"])
        self.assertTrue(s["flags_detected"]["detected"])
        self.assertTrue(s["factual_correctness"]["correct"])

    def test_a_recalculation_where_the_key_says_none_is_caught(self):
        r = correct_case4()
        s_ok = score(r, C4)
        self.assertTrue(s_ok["recalculation"]["ok"])
        # same reply shape against a case whose key says no recalculation
        gid = "HOU-ATH-2026-09-25-1"
        r2 = {"game_id": gid, "verified_assumptions": [],
              "challenged_assumption": "x", "case_against": "A case.",
              "action": "RECALCULATE",
              "action_payload": {
                  "reason": "rerun the model",
                  "changed_input": "home_sp_era",
                  "source_claim_ids": [f"model_input:{gid}:home_sp_known"]},
              "facts": [], "rankings": [], "pitcher_attribution": None}
        s = score(r2, C1)
        self.assertTrue(s["recalculation"]["asked"])
        self.assertFalse(s["recalculation"]["ok"])

    def test_an_unsupported_claim_from_the_key_is_counted(self):
        r = correct_case4()
        r["case_against"] += (" Ian Seymour is still the starting pitcher "
                              "for the away side.")
        s = score(r, C4)
        self.assertGreaterEqual(
            s["unsupported_claims"]["components"]["must_not_claim_asserted"],
            1)

    def test_a_hedged_sentence_is_not_counted_as_an_assertion(self):
        r = correct_case4()
        r["case_against"] += (" It is not known that Ian Seymour would be "
                              "the starting pitcher.")
        s = score(r, C4)
        self.assertEqual(
            0, s["unsupported_claims"]["components"]["must_not_claim_asserted"])

    def test_a_false_alarm_on_a_clean_case_is_counted(self):
        gid = "HOU-ATH-2026-09-25-1"
        mi = f"model_input:{gid}:home_sp_known"
        r = {"game_id": gid,
             "verified_assumptions": [["Inputs are current.",
                                       "STALE -- the numbers look old.",
                                       [mi]]],
             "challenged_assumption": "x", "case_against": "A case.",
             "action": "NO_ADJUSTMENT", "action_payload": {
                 "checked_claim_ids": [mi]},
             "facts": [], "rankings": [], "pitcher_attribution": None}
        s = score(r, C1)
        self.assertEqual(1, len(s["flags_detected"]["false_alarms"]))
        self.assertGreaterEqual(s["unsupported_claims"]["count"], 1)

    def test_a_citation_that_does_not_exist_is_a_source_failure(self):
        r = correct_case4()
        r["verified_assumptions"][0][2].append("probable:NOPE:away")
        s = score(r, C4)
        self.assertFalse(s["source_correctness"]["correct"])
        self.assertIn("probable:NOPE:away",
                      s["source_correctness"]["missing_ids"])
        self.assertFalse(s["verifier"]["passes"])

    def test_a_number_the_cited_claims_do_not_support_is_a_source_failure(self):
        r = correct_case4()
        # 3.4054 is a real packet number (the HOME ERA) but the triple cites
        # only away-side claims.
        r["verified_assumptions"][0][1] += " It is not the 3.4054 figure."
        r["facts"].append({"claim_id": "model_input:TB-NYY-2026-09-23-1:"
                           "home_sp_known", "field_path": "home_sp_era",
                           "value": 3.4054})
        s = score(r, C4)
        self.assertTrue(s["verifier"]["passes"], s["verifier"])
        self.assertFalse(s["source_correctness"]["correct"])

    def test_an_unparseable_reply_scores_as_a_failure_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "r.json", {"verdict": "RECALCULATION_REQUESTED"})
            s = cb.score_report_file(p, C4)
        self.assertFalse(s["parsed"])
        self.assertFalse(s["verifier"]["passes"])

    def test_a_full_analyst_report_is_accepted(self):
        packet, key = cb.load_case(C4)
        rep = aa.apply_critic(packet, cb.parse_report(correct_case4()))
        s = score(json.loads(json.dumps(
            {"finding": rep.finding}, default=list)), C4)
        self.assertTrue(perfect(s), s)


class OriginalFailureOnCase8(unittest.TestCase):
    def test_largest_called_one_of_the_smaller_is_a_factual_failure(self):
        s = score(failed_pattern_case8(), C8)
        self.assertFalse(s["factual_correctness"]["correct"], s)
        kinds = [w["kind"] for w in s["factual_correctness"]["wrong"]]
        self.assertIn("prose_ranking", kinds)
        self.assertGreaterEqual(
            s["unsupported_claims"]["components"]["must_not_claim_asserted"],
            1)

    def test_a_structured_mis_rank_is_also_a_failure(self):
        r = failed_pattern_case8()
        r["case_against"] = "The pick's score is lower than the slate's."
        r["rankings"] = [{"metric": "pick_score",
                          "subject_value": 0.09638901961434626,
                          "compared_values": [0.08422589582018003,
                                              0.05080994347913931],
                          "claimed_rank": 2}]
        s = score(r, C8)
        self.assertFalse(s["verifier"]["passes"])
        self.assertFalse(s["factual_correctness"]["correct"])

    def test_a_correct_ranking_passes(self):
        r = failed_pattern_case8()
        r["case_against"] = (
            "The pick's score of 0.0964 is the largest of the three, "
            "against 0.0842 and 0.0508.")
        s = score(r, C8)
        self.assertTrue(s["factual_correctness"]["correct"], s)
        self.assertTrue(s["verifier"]["passes"], s["verifier"])
        self.assertTrue(s["flags_detected"]["detected"])
        self.assertTrue(perfect(s), s)

    def test_fabricated_ranking_values_the_verifier_accepts_are_caught(self):
        r = failed_pattern_case8()
        r["case_against"] = "The score is 0.99 against 0.5 and 0.1."
        r["rankings"] = [{"metric": "pick_score", "subject_value": 0.99,
                          "compared_values": [0.5, 0.1], "claimed_rank": 1}]
        packet, key = cb.load_case(C8)
        finding = cb.parse_report(r)
        aa.validate_hard_limits(packet, finding)  # verifier lets it by
        s = cb.score_finding(packet, key, finding)
        self.assertFalse(s["factual_correctness"]["correct"])

    def test_attributing_the_transaction_to_the_home_starter_is_caught(self):
        herz = "mlb_news:943391"
        r = failed_pattern_case8()
        r["case_against"] = ("The home starter is DJ Herz, back from the "
                             "injured list.")
        r["action"] = "RECALCULATE"
        r["action_payload"] = {
            "reason": "DJ Herz is the home starter and may be limited.",
            "changed_input": "home_sp_ip_per_start",
            "source_claim_ids": [herz]}
        r["pitcher_attribution"] = {"side": "home", "name": "DJ Herz",
                                    "identity_claim_id": herz}
        packet, key = cb.load_case(C8)
        finding = cb.parse_report(r)
        # The existing identity gate accepts a transaction claim as the
        # identity source: the original defect, still open in the verifier.
        aa.validate_hard_limits(packet, finding)
        s = cb.score_finding(packet, key, finding)
        self.assertGreaterEqual(
            s["unsupported_claims"]["components"]["must_not_claim_asserted"],
            1)
        self.assertFalse(s["recalculation"]["ok"])
        self.assertFalse(s["correct_action"]["correct"])


# ---------------------------------------------------------------------------
# Arms A and B
# ---------------------------------------------------------------------------

class Arms(unittest.TestCase):
    def test_arm_a_is_always_no_adjustment(self):
        res = cb.compare()
        for r in res["rows"]:
            self.assertEqual("NO_ADJUSTMENT", r["A"]["action"])
            self.assertEqual(0, r["A"]["unsupported_claims"])

    def test_a_and_b_are_reproducible(self):
        a = json.dumps(cb.compare(), sort_keys=True)
        b = json.dumps(cb.compare(), sort_keys=True)
        self.assertEqual(a, b)
        for d in C.values():
            p, _k = cb.load_case(d)
            self.assertEqual(json.dumps(cb.arm_b(p), sort_keys=True),
                             json.dumps(cb.arm_b(p), sort_keys=True))

    def test_arms_differ_on_the_wrong_starter_case(self):
        rows = {r["case_id"]: r for r in cb.compare()["rows"]}
        r = rows["case_04_wrong_starter"]
        self.assertFalse(r["A"]["correct_action"])
        self.assertTrue(r["B"]["correct_action"])
        self.assertEqual("CORRECT_INPUT", r["B"]["action"])

    def test_b_also_beats_a_on_the_market_alternative_case(self):
        rows = {r["case_id"]: r for r in cb.compare()["rows"]}
        r = rows["case_06_market_alternative"]
        self.assertFalse(r["A"]["correct_action"])
        self.assertEqual("COMPARE_MARKET", r["B"]["action"])

    def test_b_findings_all_pass_the_existing_verifier(self):
        for name, d in C.items():
            packet, key = cb.load_case(d)
            s = cb.score_finding(packet, key,
                                 cb.parse_report(cb.arm_b(packet)))
            self.assertTrue(s["verifier"]["passes"], (name, s["verifier"]))
            self.assertEqual(0, s["unsupported_claims"]["count"], name)
            self.assertFalse(s["invented_numerical_effect"]["invented"], name)

    def test_b_raises_no_false_alarm_on_the_clean_cases(self):
        for d in (C1, C2):
            packet, _k = cb.load_case(d)
            reply = cb.arm_b(packet)
            self.assertEqual("NO_ADJUSTMENT", reply["action"])
            self.assertEqual([], reply["verified_assumptions"])

    def test_b_uses_only_source_kinds_the_code_builds(self):
        kinds = set()
        for d in C.values():
            p, _k = cb.load_case(d)
            kinds |= {c.claim_id.split(":")[0] for c in p.claims}
        self.assertTrue(kinds <= set(cb.SOURCE_KINDS) | {"pitcher_log",
                                                         "slate_scores"},
                        kinds)
        for names in cb.AUTHORITATIVE_FOR.values():
            self.assertTrue(set(names) <= set(cb.SOURCE_KINDS))

    def test_b_flags_exactly_what_the_rules_define(self):
        expect = {C3: "STALE", C5: "UNVERIFIED", C7: "MISSING"}
        for d, label in expect.items():
            p, _k = cb.load_case(d)
            labels = [cb._label_of(t[1])
                      for t in cb.arm_b(p)["verified_assumptions"]]
            self.assertIn(label, labels, d)
            self.assertEqual("NO_ADJUSTMENT", cb.arm_b(p)["action"])

    def test_c_is_pending_without_replies_and_scored_with_them(self):
        res = cb.compare()
        self.assertEqual("pending", res["c_status"])
        text = cb.compare_markdown(res)
        self.assertIn("pending", text)
        with tempfile.TemporaryDirectory() as tmp:
            for name, d in C.items():
                p, _k = cb.load_case(d)
                _write(tmp, name + ".json", cb.arm_b(p))
            res = cb.compare(reports_dir=tmp)
        self.assertEqual("scored", res["c_status"])
        self.assertTrue(all(r["C"] is not None for r in res["rows"]))
        self.assertEqual([r["B"] for r in res["rows"]],
                         [r["C"] for r in res["rows"]])


class BatchScoring(unittest.TestCase):
    def test_score_all_reports_a_missing_case_and_builds_a_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, _k = cb.load_case(C4)
            _write(tmp, "case_04_wrong_starter.json", correct_case4())
            rows = cb.score_all(tmp)
        self.assertEqual(8, len(rows))
        done = [r for r in rows if r["parsed"]]
        self.assertEqual(1, len(done))
        table = cb.markdown_table(rows)
        self.assertIn("case_04_wrong_starter", table)
        self.assertIn("no report", table)
        self.assertEqual(10, len(table.split("\n")))

    def test_cli_score_prints_one_json_per_case(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "r.json", correct_case4())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cb.main(["score", path, "--case", C4])
        self.assertEqual(0, rc)
        out = json.loads(buf.getvalue())
        self.assertEqual("case_04_wrong_starter", out["case_id"])

    def test_cli_compare_says_c_is_pending(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cb.main(["compare"])
        self.assertEqual(0, rc)
        self.assertIn("Arm C is pending", buf.getvalue())

    def test_the_repo_verifier_is_not_modified_by_this_module(self):
        # A frozen benchmark scores against the verifier as it is; a changed
        # ACTIONS tuple would silently change what "correct action" means.
        self.assertEqual(
            ("CORRECT_INPUT", "REQUEST_SCENARIO", "COMPARE_MARKET",
             "RECALCULATE", "NO_ADJUSTMENT"), aa.ACTIONS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
