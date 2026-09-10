"""The front page may never tell a paying reader that nothing cleared the bar.

WHY THIS FILE EXISTS
--------------------
The owner's instruction on 2026-09-10, and it was not a suggestion: never,
not once, let this site say "we checked the slate and nothing clears the
bar". There have to be three to five bets every day.

The sentence was not a bug. It was accurate -- a statement about the
evidence threshold in `src/engine/slip.py` -- and it was defended in code
comments as the honest answer most nights. What it actually did was answer a
question nobody asked, in the largest type on the screen, to someone who had
paid to be told what to bet. Being true is not sufficient. The product's
answer to "what should I bet tonight" is now `src/analysis/daily_card.py`,
which always has one.

WHAT IS BANNED, AND WHAT IS NOT
-------------------------------
Banned in every customer-facing surface: the sentence itself, and the
narrower phrases it was assembled from.

NOT banned, and deliberately so:
  * `docs/` -- the incident write-ups and the doctrine have to be able to
    quote what the page used to say, or the history becomes unreadable.
  * `tests/` -- this file has to name the strings it bans.
  * `design/` -- the V2 artboards are a frozen record of a design that
    shipped; editing them would falsify what was drawn.
  * The engine's own ledger vocabulary (`read_as: NOTHING_CLEARED` in
    `evidence/slips_v1.jsonl`) is machine-facing, never rendered, and is the
    honest name for what the slip found. The slip is a research instrument
    and it keeps its floors; the CARD is the product and it has none.

Comment stripping is not optional here. A test that matches a file's own
documentation instead of its rendered strings would pass on a page that
still says the sentence, and this repo has shipped that mistake before.
"""

from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The sentence, and the pieces it was built from. Matched case-insensitively
# and whitespace-insensitively so a re-wrap or a line break cannot smuggle it
# back in.
BANNED_PHRASES = (
    "nothing clears the bar",
    "nothing cleared the bar",
    "no demonstrated edge",
    "we checked the slate",
)

# THE JARGON BAN, from the same instruction and the same day: "nobody knows
# what divig means... no making up random words". These are terms of art
# that were correct and unreadable. Each has a plain-English replacement
# defined once in web/js/labels.js (FAIR_LABEL / FAIR_LONG / FAIR_EXPLAINER)
# and on the server in src/analysis/priceverdict.py's BASIS.
#
# The CONCEPTS are not banned and must not be dropped -- the fair price is
# the honest denominator behind every price comparison this product makes,
# and hiding it would be worse than naming it badly. What is banned is
# putting the unexplained term in front of a reader.
BANNED_JARGON = (
    "de-vig",
    "devig",
    "de-vigged",
    "closing line value",
    "basis points",
    " bps",
    "expected value play",
)

# Surfaces a customer reads. `web/` is the whole client; the two Python
# modules are the ones that compose customer-visible sentences on the server.
CUSTOMER_DIRS = ("web",)
CUSTOMER_FILES = (
    os.path.join("src", "analysis", "daily_card.py"),
    os.path.join("src", "report", "card.py"),
)

# Server modules whose STRING LITERALS reach a customer's screen verbatim.
# Narrower than "all of src/", deliberately: src/core/odds.py's `devig` is a
# function name and must keep it, and the research docs and ledgers speak
# the technical vocabulary because that is what they are for.
CUSTOMER_STRING_MODULES = (
    os.path.join("src", "analysis", "priceverdict.py"),
    os.path.join("src", "analysis", "opportunities.py"),
    os.path.join("src", "analysis", "daily_card.py"),
    os.path.join("src", "report", "card.py"),
)

SKIP_DIR_NAMES = {"node_modules", "__pycache__", ".git"}


def _strip_js_comments(text: str) -> str:
    """Block and line comments out, string literals intact.

    Crude on purpose: it removes a `//` even inside a string literal, which
    can only ever make this test STRICTER (a false positive is a reviewable
    failure; a false negative is the sentence shipping). The one thing it
    must not do is leave comments in, because then the test would pass by
    matching prose that explains the ban.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(^|[^:])//[^\n]*", r"\1", text)


def _strip_py_comments(text: str) -> str:
    text = re.sub(r'"""(?:.|\n)*?"""', " ", text)
    text = re.sub(r"'''(?:.|\n)*?'''", " ", text)
    return re.sub(r"(^|[^\"'])#[^\n]*", r"\1", text)


def _strip_html_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", " ", text, flags=re.S)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _customer_files():
    for rel_dir in CUSTOMER_DIRS:
        base = os.path.join(ROOT, rel_dir)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            for name in filenames:
                if name.endswith((".js", ".html", ".css", ".json")):
                    yield os.path.join(dirpath, name)
    for rel in CUSTOMER_FILES:
        path = os.path.join(ROOT, rel)
        if os.path.exists(path):
            yield path


def _rendered_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    if path.endswith(".js"):
        raw = _strip_js_comments(raw)
    elif path.endswith(".py"):
        raw = _strip_py_comments(raw)
    elif path.endswith(".html"):
        raw = _strip_html_comments(raw)
    elif path.endswith(".css"):
        # CSS is still scanned rather than skipped: `content: "..."` renders
        # real text to a reader. Only its /* */ comments come out, and those
        # are where a stylesheet legitimately explains what a class is for.
        raw = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
    return _normalise(raw)


class NoBannedVerdictCopy(unittest.TestCase):
    def test_no_customer_surface_carries_a_banned_phrase(self):
        offenders = []
        for path in _customer_files():
            text = _rendered_text(path)
            for phrase in BANNED_PHRASES:
                if phrase in text:
                    offenders.append(
                        f"{os.path.relpath(path, ROOT)}: {phrase!r}")
        self.assertEqual(
            [], offenders,
            "a customer-facing surface says one of the banned verdict "
            "phrases. The product's answer to 'what should I bet' is "
            "src/analysis/daily_card.py, which always has one. See this "
            "file's docstring:\n  " + "\n  ".join(offenders))

    def test_no_customer_surface_uses_unexplained_jargon(self):
        offenders = []
        for path in _customer_files():
            text = _rendered_text(path)
            for phrase in BANNED_JARGON:
                if phrase in text:
                    offenders.append(
                        f"{os.path.relpath(path, ROOT)}: {phrase!r}")
        self.assertEqual(
            [], offenders,
            "a customer-facing surface prints a term of art with no "
            "explanation. The plain-English wording lives in "
            "web/js/labels.js (FAIR_LABEL / FAIR_LONG / FAIR_EXPLAINER) and "
            "src/analysis/priceverdict.py's BASIS -- use those rather than "
            "inventing a second phrase for the same number:\n  "
            + "\n  ".join(offenders))

    def test_the_server_sentences_that_reach_a_screen_are_clean_too(self):
        """A payload's `basis` and `label` render verbatim in the client, so
        banning jargon in web/ alone would leave it on the page."""
        offenders = []
        for rel in CUSTOMER_STRING_MODULES:
            path = os.path.join(ROOT, rel)
            if not os.path.exists(path):
                continue
            text = _rendered_text(path)
            for phrase in BANNED_JARGON + BANNED_PHRASES:
                if phrase in text:
                    offenders.append(f"{rel}: {phrase!r}")
        self.assertEqual([], offenders, "\n  ".join(offenders))

    def test_the_plain_wording_actually_exists_where_it_is_pointed_at(self):
        """A ban with no replacement is how copy quietly gets worse. These
        are the strings the rest of the app is told to use."""
        labels = os.path.join(ROOT, "web", "js", "labels.js")
        with open(labels, encoding="utf-8") as fh:
            src = fh.read()
        for name in ("FAIR_LABEL", "FAIR_LONG", "FAIR_EXPLAINER", "fairPhrase"):
            self.assertIn(f"export const {name}" if name != "fairPhrase"
                          else "export function fairPhrase", src,
                          f"{name} is missing from web/js/labels.js")

    def test_the_ban_is_actually_testing_rendered_strings(self):
        """The stripper must remove documentation, or this whole file is a
        test that reads its own comments. Proven against a fixture rather
        than asserted, because that is the failure mode this guards."""
        js = 'const a = 1; // nothing clears the bar\nconst b = "keep me";'
        self.assertNotIn("nothing clears the bar", _normalise(_strip_js_comments(js)))
        self.assertIn("keep me", _normalise(_strip_js_comments(js)))

        py = '# no demonstrated edge\nX = "kept"\n'
        self.assertNotIn("no demonstrated edge", _normalise(_strip_py_comments(py)))
        self.assertIn("kept", _normalise(_strip_py_comments(py)))

    def test_a_banned_phrase_in_a_string_literal_is_still_caught(self):
        """The stripper must not be so eager it eats real copy."""
        js = 'el("p", { text: "We checked the slate." });'
        self.assertIn("we checked the slate", _normalise(_strip_js_comments(js)))


class TheCardAlwaysHasAFloor(unittest.TestCase):
    """The other half of the instruction: three to five bets, every day."""

    def test_the_floor_is_three(self):
        from src.analysis import daily_card
        self.assertEqual(3, daily_card.MIN_PICKS)
        self.assertEqual(5, daily_card.MAX_PICKS)

    def test_the_floor_is_met_by_filling_from_the_split_pile(self):
        """A thin night must produce picks, and each filled one must be
        labelled -- the floor is met by lowering the label, never by
        inventing a claim."""
        from src.analysis import daily_card

        def _c(gid, confidence, agrees):
            return {"game_id": gid, "confidence": confidence,
                    "market_probability": confidence, "model_probability": 0.5,
                    "agrees": agrees, "price": -110, "market": "moneyline",
                    "team_name": "Padres", "opponent_name": "Nationals",
                    "is_underdog": False, "label": None,
                    "us": {"runs_scored": 4.9, "runs_allowed": 3.9},
                    "them": {"runs_scored": 4.1, "runs_allowed": 5.2}}

        one_agrees = [_c("g1", 0.61, True), _c("g2", 0.58, False),
                      _c("g3", 0.55, False), _c("g4", 0.53, False)]
        for c in one_agrees:
            c["label"] = daily_card._label(c["confidence"], c["agrees"])

        out = daily_card.select(one_agrees)
        self.assertEqual(3, len(out["picks"]))
        self.assertEqual(2, out["filled"])
        filled = [p for p in out["picks"] if p["label"] == daily_card.LABEL_SPLIT]
        self.assertEqual(2, len(filled))
        for pick in out["picks"]:
            self.assertTrue(pick["bet"].startswith("Take "), pick["bet"])

    def test_the_alternative_names_the_line_it_was_priced_at(self):
        """A bet instruction naming the wrong line is worse than no
        alternative at all.

        The first draft derived the run line from the sign of the MONEYLINE
        price -- favourite implies -1.5, underdog implies +1.5 -- which is
        wrong whenever the two markets disagree about who is favoured, and
        on a near-pick'em game they often do. Measured live on 2026-09-10 it
        printed "White Sox -1.5 at -185 pays more" when -185 was the price
        for +1.5 and paid LESS than the -104 moneyline beside it.
        """
        from src.analysis import daily_card

        candidate = {"side": "away", "price": -104, "team_name": "White Sox"}
        # The board says this side is TAKING the runs, whatever the
        # moneyline's sign suggests.
        daily_card._attach_run_line(
            candidate, {"away": {"best_price": -185, "best_book": "betus",
                                 "books": 11, "line": 1.5}})
        alt = candidate["alternative"]
        self.assertEqual(1.5, alt["line"])
        self.assertIn("+1.5", alt["bet"])
        self.assertNotIn("pays more", alt["trade"])
        self.assertIn("safer", alt["trade"])

    def test_the_alternative_says_pays_more_only_when_laying_runs(self):
        from src.analysis import daily_card

        candidate = {"side": "home", "price": -280, "team_name": "Yankees"}
        daily_card._attach_run_line(
            candidate, {"home": {"best_price": -128, "best_book": "dk",
                                 "books": 8, "line": -1.5}})
        alt = candidate["alternative"]
        self.assertEqual(-1.5, alt["line"])
        self.assertIn("-1.5", alt["bet"])
        self.assertIn("pays more", alt["trade"])

    def test_a_non_standard_run_line_is_not_offered(self):
        """An alternate line is a different bet and must not be presented
        under the standard one's wording."""
        from src.analysis import daily_card

        candidate = {"side": "home", "price": -280, "team_name": "Yankees"}
        daily_card._attach_run_line(
            candidate, {"home": {"best_price": +240, "line": -2.5}})
        self.assertNotIn("alternative", candidate)

    def test_the_card_never_chooses_the_run_line_as_the_pick(self):
        """The comparison that used to do this is deleted; see
        RUNLINE_AS_ALTERNATIVE. A future edit that reinstates it has to
        trip over this."""
        from src.analysis import daily_card

        self.assertTrue(daily_card.RUNLINE_AS_ALTERNATIVE)
        self.assertFalse(hasattr(daily_card, "RUNLINE_PREFERENCE_POINTS"),
                         "the model-vs-model market comparison is back, and "
                         "one of its inputs is measured wrong -- see "
                         "docs/PREREG_RUN_DISPERSION.md")

    def test_no_more_than_one_pick_per_game(self):
        from src.analysis import daily_card

        def _c(gid, confidence):
            return {"game_id": gid, "confidence": confidence,
                    "market_probability": confidence, "model_probability": 0.6,
                    "agrees": True, "price": -110, "market": "moneyline",
                    "team_name": "Padres", "opponent_name": "Nationals",
                    "is_underdog": False, "label": daily_card.LABEL_LEAN,
                    "us": {"runs_scored": 4.9, "runs_allowed": 3.9},
                    "them": {"runs_scored": 4.1, "runs_allowed": 5.2}}

        out = daily_card.select([_c("same", 0.61), _c("same", 0.60),
                                 _c("b", 0.59), _c("c", 0.58)])
        ids = [p["game_id"] for p in out["picks"]]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
