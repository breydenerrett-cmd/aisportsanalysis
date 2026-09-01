"""src/analysis/disclaimers.py -- the temporary beta legal disclaimer.

Pins docs/LAUNCH_DECISIONS.md's DECIDED BY BREY 2026-09-01 item 4: the
three required statements must be present, the payload must self-identify
as temporary and pending review, and the wording must never regress into
the tout vocabulary tests/test_customer_language.py bans project-wide.
"""

import re
import unittest

from src.analysis import disclaimers


class DisclaimerContentTest(unittest.TestCase):
    def test_states_it_is_information_and_research(self):
        text = disclaimers.BETA_DISCLAIMER.lower()
        self.assertIn("information", text)
        self.assertIn("research", text)

    def test_states_no_guarantee_of_outcomes_or_profits(self):
        text = disclaimers.BETA_DISCLAIMER.lower()
        self.assertIn("does not guarantee", text)
        self.assertTrue("outcome" in text or "profit" in text)

    def test_states_user_owns_wagering_decisions(self):
        text = disclaimers.BETA_DISCLAIMER.lower()
        self.assertIn("responsible for your own wagering decisions", text)

    def test_labeled_temporary_and_beta(self):
        text = disclaimers.BETA_DISCLAIMER.upper()
        self.assertIn("BETA", text)
        self.assertIn("TEMPORARY", text)


class GetDisclaimerAccessorTest(unittest.TestCase):
    def test_shape_and_flags(self):
        d = disclaimers.get_disclaimer()
        self.assertEqual(d["id"], "beta-v1")
        self.assertIs(d["temporary"], True)
        self.assertIs(d["requires_final_legal_review"], True)
        self.assertEqual(d["text"], disclaimers.BETA_DISCLAIMER)

    def test_returns_a_fresh_dict_each_call(self):
        first = disclaimers.get_disclaimer()
        first["text"] = "mutated"
        second = disclaimers.get_disclaimer()
        self.assertEqual(second["text"], disclaimers.BETA_DISCLAIMER)


# Mirrors tests/test_customer_language.py's rules directly against this
# one constant, rather than importing that test's private helpers, so this
# file stands alone and still fails loudly if tout language creeps in here.
BANNED_UNNEGATED = (
    r"\+\s*EV\b",
    r"\btrue\s+line\b",
    r"\btrue\s+probabilit",
    r"\btrue\s+odds\b",
    r"\bfree\s+money\b",
    r"\ba\s+lock\b",
    r"\bwins?\s+(bets|money|for you)\b",
)


class BannedVocabularyTest(unittest.TestCase):
    def test_no_ev_or_edge_or_win_guarantee_language(self):
        text = disclaimers.BETA_DISCLAIMER
        for pattern in BANNED_UNNEGATED:
            self.assertIsNone(
                re.search(pattern, text, re.IGNORECASE),
                f"banned pattern {pattern!r} found in disclaimer text")

    def test_guaranteed_only_appears_negated(self):
        text = disclaimers.BETA_DISCLAIMER
        for m in re.finditer(r"\bguarantee[sd]?\b", text, re.IGNORECASE):
            # 90-char lookback matches tests/test_customer_language.py's own
            # NEGATORS window -- this must pass under the real repo-wide
            # scan, not just a narrower local check.
            window = text[max(0, m.start() - 90):m.start()]
            self.assertRegex(window, r"(?i)\b(does not|no|never|nothing)\b")

    def test_edge_only_appears_negated(self):
        text = disclaimers.BETA_DISCLAIMER
        for m in re.finditer(r"\bedges?\b", text, re.IGNORECASE):
            window = text[max(0, m.start() - 90):m.start()]
            self.assertRegex(
                window, r"(?i)\b(nothing here is|no|never|not)\b",
                "'edge' affirmed without negation in disclaimer")

    def test_never_reads_as_a_promised_lock(self):
        # "a lock" (as in "a sure thing") is banned outright project-wide
        # (tests/test_customer_language.py HARD_BANNED) -- unlike "edge"
        # or "guaranteed", no negation makes it acceptable customer copy.
        self.assertNotRegex(disclaimers.BETA_DISCLAIMER,
                             r"(?i)\ba\s+lock\b")


if __name__ == "__main__":
    unittest.main()
