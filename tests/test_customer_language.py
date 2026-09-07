"""Permanent tripwire: banned customer language must never reappear.

Scans every string literal (excluding docstrings — internal documentation)
in src/analysis/ and src/report/, plus the customer contract serialisations
and field names, for:

- tout vocabulary: "+EV", "true line", "true probability", "guaranteed"
  (outside a negation), "lock" as a noun, "free money";
- "market's true read" — the de-vigged number is MARKET-IMPLIED CONSENSUS,
  never "true" anything;
- "edge" affirmed as a thing the customer has or gets — it may appear only
  in a negation/disclaimer ("no demonstrated edge", "nothing here is an
  edge"). Price improvement is line-shopping value, never EV or edge;
- "win probability" in customer-facing strings, and any field name implying
  a win probability. The model is UNCALIBRATED; no win-probability number
  exists in the product.

This test is meant to FAIL LOUDLY the day any of this is reintroduced.
"""

import ast
import dataclasses
import json
import pathlib
import re
import unittest

from src.analysis import contracts as c

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = (ROOT / "src" / "analysis", ROOT / "src" / "report")

# Phrases banned outright, negated or not.
HARD_BANNED = (
    (r"\+\s*EV\b", "+EV"),
    (r"\btrue\s+line\b", "true line"),
    (r"\btrue\s+probabilit", "true probability"),
    (r"\btrue\s+odds\b", "true odds"),
    (r"market'?s\s+true\s+read", "market's true read"),
    (r"\bfree\s+money\b", "free money"),
    (r"\block\s+of\s+the\b", "lock of the day"),
    (r"\ba\s+lock\b", "a lock"),
    (r"\bexpected\s+value\s+play\b", "EV play"),
)

# Words allowed ONLY in a negation / disclaimer context.
NEGATION_ONLY = (
    (r"\bedge(s)?\b", "edge as a customer noun"),
    (r"\bguaranteed?\b", "guaranteed"),
    (r"\bwin[- ]probabilit\w*", "win probability"),
    (r"\bsure\s+thing\b", "sure thing"),
    (r"\bcan'?t\s+lose\b", "can't lose"),
)

# What counts as a negation/disclaimer within the preceding window.
NEGATORS = re.compile(
    r"\b(no|not|NOT|none|never|nothing|without|zero|cannot|can't|refuses?|"
    r"isn'?t|aren'?t|until|instead of|rather than|guard)\b", re.IGNORECASE)

BANNED_FIELD_NAME_PARTS = (
    "win_probability", "win_prob", "p_win", "prob_win", "winprob",
    "model_probability", "true_probability", "ev", "expected_value",
    "edge", "roi",
)
# `ev` alone would false-positive on e.g. "evidence"; match as whole
# underscore-delimited tokens instead.

# Strings that legitimately name a field inside a sentence, checked one by
# one. Each is either a developer-facing validation message, an internal
# research report that no customer route serves, or a CSS class name inside
# a stylesheet literal. Anything NOT on this list is a defect: the same
# escape reached Today, Games, Odds, Bet Check and the daily record on
# 2026-09-07 and had to be caught by eye. Add to this list only after
# confirming the string cannot reach a customer page.
PROSE_FIELD_NAME_ALLOWED = frozenset({
    # ValueError text raised at the contract boundary -- developers only.
    ("src/analysis/betcheck.py", "away_club"),
    ("src/analysis/betcheck.py", "home_club"),
    ("src/analysis/contracts.py", "evidence_status"),
    # Store diagnostics: which file and key could not be joined. These are
    # operator reasons in the audit trail, deliberately precise.
    ("src/report/daily_record.py", "game_pk"),
    ("src/report/daily_record.py", "boxscores_2026"),
    ("src/report/daily_record.py", "event_game_map"),
    # End-of-day research report; not served by any customer route.
    ("src/report/eod.py", "model_derived"),
    ("src/report/eod.py", "market_derived"),
    ("src/report/eod.py", "edge_bps"),
    ("src/report/eod.py", "assumption_exposure"),
    ("src/report/eod.py", "log_loss"),
    # CSS class names inside the dashboard's stylesheet literal.
    ("src/report/dashboard.py", "forward_testing"),
    ("src/report/dashboard.py", "tuning_evidence"),
    ("src/report/dashboard.py", "historical_candidate"),
    ("src/report/dashboard.py", "no_play"),
    ("src/report/dashboard.py", "market_unavailable"),
    ("src/report/dashboard.py", "tested_null"),
})


def _string_literals(path):
    """All string constants in a file, minus docstrings, with line numbers."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                doc_nodes.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in doc_nodes:
            out.append((node.lineno, node.value))
    return out


def _violations_in(text, where):
    found = []
    for pattern, label in HARD_BANNED:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(f"{where}: hard-banned {label!r} in {text[:90]!r}")
    for pattern, label in NEGATION_ONLY:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            window = text[max(0, m.start() - 90):m.start()]
            if not NEGATORS.search(window):
                found.append(
                    f"{where}: {label!r} affirmed (no negation in the "
                    f"preceding window) in {text[:120]!r}")
    return found


class BannedLanguageScan(unittest.TestCase):
    def test_no_banned_language_in_source_strings(self):
        violations = []
        for directory in SCAN_DIRS:
            for path in sorted(directory.glob("*.py")):
                for lineno, text in _string_literals(path):
                    rel = path.relative_to(ROOT)
                    violations.extend(
                        _violations_in(text, f"{rel}:{lineno}"))
        self.assertEqual(violations, [],
                         "banned customer language reintroduced:\n"
                         + "\n".join(violations))

    def test_no_payload_field_names_inside_customer_prose(self):
        """A snake_case token in a SENTENCE is a field name that escaped.

        Not the same rule as BANNED_FIELD_NAME_PARTS above, which is about
        dishonest CONCEPTS (edge, EV, win probability). This one is about
        register: `value_points`, `board_summary`, `age_seconds`,
        `has_board`, `games_count`, `spread_cents` and `thesis_support` all
        reached customer pages on 2026-09-07 inside otherwise plain English,
        and every one had to be found by eye on a rendered page. They are
        honest measures said in the wrong language.

        A bare dict key like "away_team" is fine and is not matched -- the
        rule needs a sentence around the token, which is what separates a
        payload key from a line someone reads.
        """
        token = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
        violations = []
        for directory in SCAN_DIRS:
            for path in sorted(directory.glob("*.py")):
                rel = str(path.relative_to(ROOT)).replace("\\", "/")
                for lineno, text in _string_literals(path):
                    if len(text.split()) < 5:
                        continue          # a key or a fragment, not prose
                    for match in token.finditer(text):
                        found = match.group(0)
                        if (rel, found) in PROSE_FIELD_NAME_ALLOWED:
                            continue
                        violations.append(
                            f"{rel}:{lineno} says {found!r} in prose: "
                            f"{text.strip()[:90]!r}")
        self.assertEqual(violations, [],
                         "payload field names reached customer prose:\n"
                         + "\n".join(violations))

    def test_no_banned_field_names_on_contracts(self):
        classes = c.CONTRACTS + (
            c.Claim, c.QuotedPrice, c.MarketImpliedConsensus,
            c.PriceImprovement, c.OddsRow, c.ChangeItem, c.MarketBlock,
            c.Factor, c.BetQuery, c.GameRef, c.CustomerEvidence)
        bad = []
        for cls in classes:
            for f in dataclasses.fields(cls):
                tokens = f.name.lower().split("_")
                for part in BANNED_FIELD_NAME_PARTS:
                    part_tokens = part.split("_")
                    n = len(part_tokens)
                    if any(tokens[i:i + n] == part_tokens
                           for i in range(len(tokens))):
                        bad.append(f"{cls.__name__}.{f.name} ({part})")
        self.assertEqual(bad, [], f"banned field names: {bad}")

    def test_contract_serialisations_clean(self):
        now = "2026-08-31T18:00:00+00:00"
        q = c.QuotedPrice(book="fanduel", american_price=-118,
                          observed_utc=now)
        cons = c.MarketImpliedConsensus(implied_probability=0.5321, books=11,
                                        observed_utc=now)
        objs = [
            q, cons,
            c.PriceImprovement(best=q, consensus=cons,
                               improvement_points=0.005,
                               improvement_return_pct=1.2),
            c.BetCheckContract(
                query=c.BetQuery(raw="Yankees ML -125", parsed=True),
                game=None, thesis_support=(), counterargument=(),
                best_available_price=q, market_consensus=cons,
                your_price_beats_consensus=True, what_changed=()),
            c.WhatChangedContract(since_label="since this morning",
                                  events=()),
        ]
        violations = []
        for obj in objs:
            payload = obj.to_json()
            violations.extend(
                _violations_in(payload, type(obj).__name__))
            # keys too
            for key in json.loads(payload):
                violations.extend(
                    _violations_in(key, f"{type(obj).__name__} key"))
        self.assertEqual(violations, [], "\n".join(violations))

    def test_customer_evidence_labels_clean(self):
        violations = []
        for ce in c._CUSTOMER_EVIDENCE.values():
            violations.extend(_violations_in(ce.label, "evidence label"))
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
