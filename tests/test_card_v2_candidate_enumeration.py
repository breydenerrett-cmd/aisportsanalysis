"""The registered candidate set vs the one the live path actually builds.

`docs/PREREG_CARD_V2.md` section 2 registers the moneyline candidate set as
"Both sides of every game". This file pins what the live path does instead,
pins that the correction does not touch a single registered file, and drives
the corrected enumeration through the same rule (`best_bets_card.select`,
unedited) to show the gates still do their job on the sides it admits.

Injected fixtures only -- no live store, no network, no read of
`data/processed/*` (the frozen parameters are passed in as `frozen=`), the
same discipline `tests/test_card_v2_report.py` already follows.

THE FIXTURE'S NUMBERS ARE PINNED ON PURPOSE. A candidate has to survive
seven gates before enumeration is what decides anything, so a fixture that
leaves any of them to chance tests whichever gate happened to fire instead
of the thing it names. `b=0` in the Platt fit makes our number exactly
`sigmoid(a)` whatever the model's raw output is, so every arithmetic
assertion below is about the rule, not about a team-strength number that a
later model change could move.
"""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

from src.analysis import best_bets_card, card_v2_enum_shadow as shadow
from src.appstate import card_ledger
from src.report import card_v2


NOW = datetime(2026, 9, 20, 16, 0, 0, tzinfo=timezone.utc)
FUTURE = "2026-09-20T23:05:00Z"

# Content fingerprints over LINE-ENDING-NORMALISED bytes, for the exact file
# lists registration 11.2 and section 10 name. Hard-coded rather than
# recomputed: the point is to fail if a registered file's CONTENT changes,
# so reading the expectation from anywhere but this file would defeat it.
#
# WHY NOT SECTION 16'S OWN NUMBERS. Two defects in the registration's
# integrity mechanism, both pre-existing, both found by this test and
# written up in `docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md`:
#
#   1. `card_ledger.code_fingerprint` hashes each file's RAW bytes, so the
#      value depends on the checkout's line endings, not just its content.
#      Section 16's V2 value `8a641de0...` reproduces exactly when all seven
#      files are CRLF; this repo's Windows checkout now holds three of them
#      (best_bets_card.py, card_v2.py, card_v2_frozen_params.json) as LF
#      with byte-identical committed content, and `git diff` from the
#      registration commit is empty. A publish from Linux CI and a publish
#      from Windows therefore stamp DIFFERENT fingerprints on rows built
#      from identical code -- so the 11.2 guard ("a change to any
#      fingerprinted file restarts the counted sample") can fire on a
#      checkout change that altered no code. One-way: a FALSE ALARM, not a
#      blind spot. sha256 offers no way for one byte difference to cancel
#      another, so a real source change cannot hide behind a line-ending
#      one.
#   2. Section 16's `v1_code_fingerprint` `10f5cac7...` is not the value at
#      the registration commit it claims. It reproduces only with
#      src/report/card.py and src/appstate/card_ledger.py taken from
#      `859176ba~1` -- the two files that commit itself changed. It was
#      computed before those edits were applied.
#
# Normalising \r\n to \n removes (1) and lets this test do the job section
# 16's numbers were supposed to do: prove this correction changed no
# registered file.
V2_CONTENT_FINGERPRINT = (
    "a6957bc3851f412c84d76d9f638153c0566e47d252da75796376c83a8f15f3bf")

# CHANGED 2026-09-23, deliberately and on the owner's ruling. The ceiling
# correction edits `src/appstate/card_ledger.py`, which is a member of
# V1_FINGERPRINT_FILES, so the V1 content fingerprint moves from
# 1d79e1ba9038dac0bc43af784a86a13c1a19e80daeca82723bb6533243bacd2b
# to the value below. Registration section 16 permits exactly this entry --
# "a recorded change to the v1_code_fingerprint under 11.6, which qualifies
# the V1 comparison and changes no V2 number" -- and it is recorded there.
#
# `card_ledger.py` is NOT in V2_FINGERPRINT_FILES, so V2's own
# code_fingerprint is untouched and V2's counted sample does NOT restart.
# That is why the V2 constant above is unchanged, and why these two are
# asserted separately rather than as one "nothing moved" check.
V1_CONTENT_FINGERPRINT = (
    "ea858a545afbd2ecd981a951841cb537fb32bfcc085f8d3deecbdeafa3f793d7")


def _content_fingerprint(paths) -> str:
    """`card_ledger.code_fingerprint`'s framing, over LF-normalised bytes."""
    import hashlib

    hasher = hashlib.sha256()
    for rel in paths:
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        try:
            with open(rel, "rb") as fh:
                hasher.update(fh.read().replace(b"\r\n", b"\n"))
        except OSError:
            hasher.update(b"<absent>")
        hasher.update(b"\0")
    return hasher.hexdigest()


def _frozen(our_home: float) -> dict:
    """A frozen fit whose calibrated `p_home` is exactly `our_home`.

    `Calibration.apply` is `sigmoid(a + b*logit(p_raw))`, so `b = 0` pins
    the output at `sigmoid(a)` regardless of the model's raw number, and
    `card_v2._build_game_candidates` then sets `p_away = 1.0 - p_home`.
    """
    return {
        "DISPERSION": 2.3352,
        "moneyline_calibration": {
            "fitted": True,
            "a": math.log(our_home / (1.0 - our_home)),
            "b": 0.0,
            "n": 2027,
            "base_rate": 0.5295,
        },
    }


def _entry(away="COL", home="NYY", game_pk=744001, first_pitch=FUTURE,
           game_number=1):
    return {"dossier": {
        "game": {"away_team": away, "home_team": home, "game_pk": game_pk,
                 "start_time_utc": first_pitch, "game_number": game_number,
                 "game_type": "R"},
        "sections": {
            "teams": {
                "away_runs_scored_pg": 4.6, "away_runs_allowed_pg": 4.2,
                "away_games_played": 140,
                "home_runs_scored_pg": 4.8, "home_runs_allowed_pg": 4.1,
                "home_games_played": 140,
            },
            "starters": {},
        },
    }}


def _game_id(away="COL", home="NYY", game_number=1):
    from src.analysis import gamepayload
    return gamepayload.game_id({"away_team": away, "home_team": home,
                                "date": "2026-09-20",
                                "game_number": game_number})


def _rows(game_id, *, away_p=0.60, home_p=0.40, away_price=-160,
          home_price=150, books=8, away_observed=None, home_observed=None,
          drop_home=False):
    """A COMPLEMENTARY board: `away_p + home_p == 1.0`.

    The board this repo's own de-vigging produces always sums to one, which
    is exactly why `daily_card._consensus_side`'s `max(p_away, p_home)` can
    never be below 0.50 in production. A fixture that lets both sides sit at
    0.40 (as `tests/test_card_v2_report.py` did before this file was
    written) describes a board that cannot exist and hides that fact.

    G13 is the constraint that ties the prices to those numbers: it refuses
    a candidate whose consensus exceeds its best price's break-even, so
    -160 (break-even 0.61538) carries a 0.60 favourite and +150 (break-even
    0.40000) carries a 0.40 underdog, and neither trips it.
    """
    observed_away = away_observed or NOW.isoformat()
    observed_home = home_observed or NOW.isoformat()
    out = [
        {"game_id": game_id, "side": "away", "market": "h2h",
         "market_implied_probability": away_p, "best_price": away_price,
         "best_book": "fd", "books": books, "observed_utc": observed_away},
    ]
    if not drop_home:
        out.append(
            {"game_id": game_id, "side": "home", "market": "h2h",
             "market_implied_probability": home_p, "best_price": home_price,
             "best_book": "dk", "books": books, "observed_utc": observed_home})
    return out


def _no_props(_date):
    return {"contracts": [], "reason": "no player props are posted for "
                                       "this slate yet"}


def _slate(n: int, *, our_home: float):
    """`n` distinct games on one date, each with the same priced board."""
    teams = [("COL", "NYY"), ("SDP", "LAD"), ("PIT", "CHC"), ("MIA", "ATL"),
             ("OAK", "HOU"), ("KCR", "MIN"), ("WSN", "PHI"), ("CIN", "MIL"),
             ("TOR", "BOS"), ("DET", "CLE"), ("TEX", "SEA"), ("ARI", "SFG")]
    entries, rows = [], []
    for i in range(n):
        away, home = teams[i % len(teams)]
        entries.append(_entry(away=away, home=home, game_pk=744001 + i))
        rows.extend(_rows(_game_id(away, home)))
    return entries, rows, _frozen(our_home)


# ---------------------------------------------------------------------------
# 1. The correction changes no registered file. Checked, not asserted in prose.
# ---------------------------------------------------------------------------

class RegisteredFilesAreUntouched(unittest.TestCase):
    """Registration 11.2: a change to any fingerprinted file "restarts the
    counted sample". The correction lives in a module neither fingerprint
    covers, so V2's published sample keeps counting. If someone later moves
    the fix into `card_v2.py` or `best_bets_card.py` these two tests fail
    and say why, instead of the restart happening silently."""

    def test_no_v2_fingerprinted_file_changed(self):
        self.assertEqual(V2_CONTENT_FINGERPRINT,
                         _content_fingerprint(
                             card_ledger.V2_FINGERPRINT_FILES))

    def test_no_v1_fingerprinted_file_changed(self):
        self.assertEqual(V1_CONTENT_FINGERPRINT,
                         _content_fingerprint(
                             card_ledger.V1_FINGERPRINT_FILES))

    def test_the_live_fingerprint_is_checkout_dependent(self):
        """Defect (1) above, pinned so it cannot be forgotten.

        Same content, two line-ending conventions, two different
        `code_fingerprint` values -- which is why the two tests above
        normalise and section 16's own numbers are not asserted here.
        """
        import hashlib

        def raw(convert):
            h = hashlib.sha256()
            for rel in card_ledger.V2_FINGERPRINT_FILES:
                h.update(rel.encode("utf-8"))
                h.update(b"\0")
                with open(rel, "rb") as fh:
                    data = fh.read().replace(b"\r\n", b"\n")
                h.update(data.replace(b"\n", b"\r\n") if convert else data)
                h.update(b"\0")
            return h.hexdigest()

        self.assertNotEqual(raw(True), raw(False))

    def test_the_shadow_module_is_in_neither_fingerprint(self):
        name = "src/analysis/card_v2_enum_shadow.py"
        self.assertNotIn(name, card_ledger.V2_FINGERPRINT_FILES)
        self.assertNotIn(name, card_ledger.V1_FINGERPRINT_FILES)

    def test_the_default_path_behaves_identically_with_the_module_loaded(self):
        """BEHAVIOUR, not hashes.

        Equal fingerprints say the two source files are unchanged. They say
        nothing about a shared dependency, a module-level side effect on
        import, or a config or data file the new module might touch. This
        builds the SAME card through the registered entry point in two
        subprocesses -- one that never imports the shadow module, one that
        imports it first -- and compares the payloads. Subprocesses, because
        this test process has already imported it, so an in-process check
        could not tell the two states apart.
        """
        import subprocess
        import sys

        script = (
            "import json,sys,math\n"
            "{IMPORT}"
            "sys.path.insert(0,'.')\n"
            "from datetime import datetime,timezone\n"
            "from src.report import card_v2\n"
            "from src.analysis import gamepayload\n"
            "NOW=datetime(2026,9,20,16,0,0,tzinfo=timezone.utc)\n"
            "e={'dossier':{'game':{'away_team':'COL','home_team':'NYY',"
            "'game_pk':744001,'start_time_utc':'2026-09-20T23:05:00Z',"
            "'game_number':1,'game_type':'R'},'sections':{'teams':"
            "{'away_runs_scored_pg':4.6,'away_runs_allowed_pg':4.2,"
            "'away_games_played':140,'home_runs_scored_pg':4.8,"
            "'home_runs_allowed_pg':4.1,'home_games_played':140},"
            "'starters':{}}}}\n"
            "gid=gamepayload.game_id({'away_team':'COL','home_team':'NYY',"
            "'date':'2026-09-20','game_number':1})\n"
            "rows=[{'game_id':gid,'side':'away','market':'h2h',"
            "'market_implied_probability':0.60,'best_price':-160,"
            "'best_book':'fd','books':8,'observed_utc':NOW.isoformat()},"
            "{'game_id':gid,'side':'home','market':'h2h',"
            "'market_implied_probability':0.40,'best_price':150,"
            "'best_book':'dk','books':8,'observed_utc':NOW.isoformat()}]\n"
            "fz={'DISPERSION':2.3352,'moneyline_calibration':{'fitted':True,"
            "'a':math.log(0.47/0.53),'b':0.0,'n':2027,'base_rate':0.5295}}\n"
            "p=card_v2.card_v2_for_date(entries=[e],opportunity_rows=rows,"
            "date='2026-09-20',now=NOW,frozen=fz,"
            "prop_board=lambda d:{'contracts':[],'reason':'none'},"
            "event_map={})\n"
            "p.pop('params',None)\n"
            "print(json.dumps(p,sort_keys=True,default=str))\n"
        )

        def run(import_line):
            out = subprocess.run(
                [sys.executable, "-c", script.replace("{IMPORT}", import_line)],
                capture_output=True, text=True, cwd=".")
            self.assertEqual(0, out.returncode, out.stderr[-2000:])
            return out.stdout.strip()

        without = run("")
        with_shadow = run("sys.path.insert(0,'.')\n"
                          "from src.analysis import card_v2_enum_shadow\n")
        self.assertEqual(without, with_shadow)
        self.assertTrue(without)

    def test_the_shadow_module_writes_nothing(self):
        """It reads inputs and returns a payload. No store, no ledger, no
        file, no network -- so it cannot change what a later publish sees."""
        import ast

        with open("src/analysis/card_v2_enum_shadow.py", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        # Parsed, not grepped: the module's prose says "publish" a dozen
        # times explaining that it never does, and a substring check on the
        # source would fail on its own documentation.
        banned_calls = {"open", "print", "exec", "eval", "input"}
        banned_attrs = {"write", "writelines", "publish", "publish_v2",
                        "remove", "unlink", "rename", "replace", "mkdir",
                        "urlopen", "post", "put", "delete"}
        banned_imports = {"subprocess", "shutil", "socket", "urllib",
                          "requests", "http", "pathlib", "os", "io"}

        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in banned_calls:
                    bad.append(f"call {fn.id}()")
                if isinstance(fn, ast.Attribute) and fn.attr in banned_attrs:
                    bad.append(f"call .{fn.attr}()")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in banned_imports:
                        bad.append(f"import {alias.name}")
            if isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in banned_imports:
                    bad.append(f"from {node.module} import ...")
        self.assertEqual([], bad)

    def test_only_the_authorised_runner_imports_the_shadow_module(self):
        """Shadow-first, enforced by the import graph rather than a flag.

        A default-off flag inside the published module is a promise; an
        import that does not exist is a fact. `src/`, `api/` and `scripts/`
        are every path a scheduled publish or a served request can run
        through.

        ALLOWED, deliberately, since 2026-09-22: the forward shadow runner
        `scripts/shadow_enumeration_run.py`. Forbidding every caller would
        forbid measuring the thing, which is the opposite of the point. The
        rule is an allow-list of one, not a ban -- so a NEW importer still
        fails this test and has to be argued for, while the authorised
        runner does not have to fight it.

        What the allow-list does NOT permit: the runner is not a publisher.
        `test_the_runner_publishes_nothing` below is what holds that line.
        """
        import os

        allowed = {
            os.path.normpath("src/analysis/card_v2_enum_shadow.py"),
            os.path.normpath("scripts/shadow_enumeration_run.py"),
        }
        offenders = []
        for root_dir in ("src", "api", "scripts"):
            for dirpath, _dirnames, filenames in os.walk(root_dir):
                if "__pycache__" in dirpath:
                    continue
                for name in filenames:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, name)
                    if os.path.normpath(path) in allowed:
                        continue
                    with open(path, encoding="utf-8") as fh:
                        if "card_v2_enum_shadow" in fh.read():
                            offenders.append(path)
        self.assertEqual([], offenders)

    def test_the_runner_publishes_nothing(self):
        """The allow-list buys the runner an import, not a publish.

        Parsed rather than grepped: the file's prose explains at length that
        it never publishes, so a substring search would fail on its own
        documentation.
        """
        import ast

        with open("scripts/shadow_enumeration_run.py", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())

        banned_attrs = {"publish", "publish_v2", "publish_all",
                        "write_logs", "append_row"}
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func,
                                                         ast.Attribute):
                if node.func.attr in banned_attrs:
                    bad.append(f"call .{node.func.attr}()")
        self.assertEqual([], bad)

        # And it may only write inside its own evidence directory.
        with open("scripts/shadow_enumeration_run.py", encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn('OUT_DIR = os.path.join("evidence", '
                      '"shadow_enumeration")', source)


# ---------------------------------------------------------------------------
# 2. What the live path actually builds. This is the defect, recorded.
# ---------------------------------------------------------------------------

class RegisteredPathBuildsOneSide(unittest.TestCase):

    def _registered(self, our_home=0.47):
        entries = [_entry()]
        rows = _rows(_game_id())
        return card_v2._build_game_candidates(
            entries, rows, date="2026-09-20", now=NOW,
            frozen=_frozen(our_home))

    def test_one_candidate_per_game_and_it_is_the_market_favourite(self):
        candidates, pool = self._registered()
        self.assertEqual(1, len(candidates))
        self.assertEqual(1, pool)
        self.assertEqual("away", candidates[0]["side"])
        self.assertGreaterEqual(candidates[0]["market_probability"], 0.50)

    def test_the_market_underdog_side_is_never_built(self):
        candidates, _pool = self._registered()
        self.assertEqual([], [c for c in candidates
                              if c["market_probability"] < 0.50])

    def test_no_moneyline_candidate_can_carry_a_plus_money_price(self):
        """The two blocks, shown together.

        `_consensus_side` guarantees `market_probability >= 0.50`; G5's
        PLUS_MONEY branch requires `market_probability < 0.50`. Disjoint, so
        the registered PLUS_MONEY class cannot fire on a game moneyline --
        which is what 332 live moneyline rows, every one negatively priced,
        already say.
        """
        candidates, _pool = self._registered()
        for c in candidates:
            fails = best_bets_card.failed_gates(
                dict(c), now=NOW, params=best_bets_card.V2)
            if best_bets_card.price_class(c["price"]) == "PLUS_MONEY":
                self.assertIn(best_bets_card.G5_MARKET, fails)

    @unittest.expectedFailure
    def test_registration_section_2_requires_both_sides_of_every_game(self):
        """THE DEFECT, pinned as an expected failure.

        Section 2's moneyline row reads "Both sides of every game". This
        asserts exactly that against the live builder, and it fails. It is
        marked expected so the suite stays green while the departure is
        recorded rather than hidden -- and so that if the live path is ever
        corrected in place, this turns into an unexpected success and forces
        whoever did it to deal with the fingerprint restart 11.2 requires.
        See `docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md`.
        """
        candidates, _pool = self._registered()
        self.assertEqual({"away", "home"}, {c["side"] for c in candidates})


# ---------------------------------------------------------------------------
# 3. The corrected enumeration.
# ---------------------------------------------------------------------------

class ShadowEnumeratesBothSides(unittest.TestCase):

    def _build(self, *, our_home=0.47, entries=None, rows=None, **kw):
        entries = entries if entries is not None else [_entry()]
        rows = rows if rows is not None else _rows(_game_id(), **kw)
        return shadow.build_game_candidates(
            entries, rows, date="2026-09-20", now=NOW,
            frozen=_frozen(our_home))

    def test_both_priced_sides_reach_evaluation(self):
        candidates, pool, not_built = self._build()
        self.assertEqual({"away", "home"}, {c["side"] for c in candidates})
        self.assertEqual(2, len(candidates))
        self.assertEqual(2, pool)
        self.assertEqual([], not_built)

    def test_the_registered_candidate_is_passed_through_unchanged(self):
        """Only enumeration changed -- the favoured side's dict is the one
        the registered builder returned, field for field, and carries no
        provenance key the live path would not have produced."""
        entries, rows = [_entry()], _rows(_game_id())
        registered, _pool = card_v2._build_game_candidates(
            entries, rows, date="2026-09-20", now=NOW, frozen=_frozen(0.47))
        candidates, _pool2, _nb = self._build(entries=entries, rows=rows)
        self.assertEqual(registered[0], candidates[0])
        self.assertNotIn("enumeration", candidates[0])
        self.assertEqual(shadow.ENUMERATION_ID, candidates[1]["enumeration"])

    def test_the_added_side_carries_the_opposite_quote_not_the_favourites(self):
        candidates, _pool, _nb = self._build()
        fav, dog = candidates
        self.assertEqual(-160, fav["price"])
        self.assertEqual(150, dog["price"])
        self.assertAlmostEqual(0.60, fav["market_probability"])
        self.assertAlmostEqual(0.40, dog["market_probability"])
        self.assertAlmostEqual(0.53, fav["our_probability"], places=9)
        self.assertAlmostEqual(0.47, dog["our_probability"], places=9)
        self.assertEqual(fav["game_id"], dog["game_id"])
        self.assertEqual("moneyline", dog["market"])
        self.assertIsNone(dog["line"])

    def test_reversed_home_away_gives_the_mirrored_result(self):
        """Same board with the sides swapped: the market favourite is now
        home, so the side the live path discards is away."""
        rows = _rows(_game_id(), away_p=0.40, home_p=0.60,
                     away_price=150, home_price=-160)
        candidates, _pool, _nb = self._build(our_home=0.53, rows=rows)
        self.assertEqual("home", candidates[0]["side"])
        self.assertEqual("away", candidates[1]["side"])
        self.assertAlmostEqual(0.40, candidates[1]["market_probability"])
        self.assertAlmostEqual(0.47, candidates[1]["our_probability"],
                               places=9)

    def test_a_market_underdog_is_a_different_field_from_a_plus_price(self):
        """The distinction the old `is_underdog` flag lost.

        `daily_card` computed `is_underdog` as `best_price > 0` on the
        FAVOURED side, so a near-pick'em favourite quoted at +105 was
        recorded as an underdog. G5 tests the market number, not the sign of
        the price, so the two facts are carried separately and named for
        what they are.
        """
        rows = _rows(_game_id(), away_p=0.51, home_p=0.49,
                     away_price=105, home_price=-115)
        candidates, _pool, _nb = self._build(our_home=0.47, rows=rows)
        fav, dog = candidates
        # The favoured side carries a PLUS price and is not an underdog.
        self.assertGreater(fav["price"], 0)
        self.assertGreaterEqual(fav["market_probability"], 0.50)
        # The discarded side is a genuine market underdog at a MINUS price.
        self.assertLess(dog["price"], 0)
        self.assertFalse(dog["positive_price"])
        self.assertTrue(dog["market_underdog"])
        self.assertEqual("market_underdog", dog["enumerated_side_role"])

    def test_no_side_is_enumerated_twice(self):
        entries, rows, frozen = _slate(4, our_home=0.47)
        candidates, pool, _nb = shadow.build_game_candidates(
            entries, rows, date="2026-09-20", now=NOW, frozen=frozen)
        keys = [(c["game_id"], c["market"], c["side"]) for c in candidates]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(8, len(candidates))
        self.assertEqual(8, pool)


# ---------------------------------------------------------------------------
# 4. A side that cannot be built is COUNTED, with a reason -- never absent.
# ---------------------------------------------------------------------------

class MissingAndStaleQuotesAreObservable(unittest.TestCase):

    def test_a_one_sided_board_builds_nothing_on_either_side(self):
        """A LIMIT of this correction, asserted rather than assumed.

        `_consensus_side` needs both rows to return anything at all, so a
        game quoted on one side only produces no candidate on the live path
        and none here either -- widening enumeration does not rescue it. The
        reason that game vanished therefore cannot come from this module;
        it has to come from the coverage ledger's earlier stage, which is
        why that stage exists and why `card_ledger.publish_v2` dropping
        `games_on_slate` matters.
        """
        rows = _rows(_game_id(), drop_home=True)
        candidates, pool, not_built = shadow.build_game_candidates(
            [_entry()], rows, date="2026-09-20", now=NOW,
            frozen=_frozen(0.47))
        self.assertEqual([], candidates)
        self.assertEqual(0, pool)
        self.assertEqual([], not_built)

    def test_an_opposite_quote_with_no_price_is_reported_with_its_reason(self):
        rows = _rows(_game_id())
        rows[1]["best_price"] = None
        candidates, pool, not_built = shadow.build_game_candidates(
            [_entry()], rows, date="2026-09-20", now=NOW,
            frozen=_frozen(0.47))
        self.assertEqual(1, len(candidates))
        self.assertEqual(1, pool)
        self.assertEqual([{"game_id": _game_id(), "side": "home",
                           "reason": shadow.NO_OPPOSITE_PRICE}], not_built)

    def test_a_stale_opposite_quote_is_enumerated_and_refused_by_g3(self):
        """Staleness is a GATE outcome, not an enumeration outcome.

        The side is built -- so the coverage ledger counts it -- and G3 is
        what refuses it. Collapsing the two would make a stale board look
        like a board that was never posted.
        """
        stale = (NOW - timedelta(hours=6)).isoformat()
        rows = _rows(_game_id(), home_observed=stale)
        candidates, _pool, _nb = shadow.build_game_candidates(
            [_entry()], rows, date="2026-09-20", now=NOW,
            frozen=_frozen(0.47))
        census = shadow.gate_census(candidates, now=NOW,
                                    params=best_bets_card.V2)
        dog = [r for r in census if r["side"] == "home"][0]
        self.assertEqual(best_bets_card.G3_STALE, dog["primary_reason"])
        self.assertTrue(dog["fill_eligible"])


# ---------------------------------------------------------------------------
# 5. The gates still decide. Enumeration widens the pool, nothing else.
# ---------------------------------------------------------------------------

class GatesStillRunAfterEnumeration(unittest.TestCase):

    def _card(self, n=1, *, our_home=0.47, params=None):
        entries, rows, frozen = _slate(n, our_home=our_home)
        return shadow.card_v2_for_date_shadow(
            entries, rows, date="2026-09-20", now=NOW, frozen=frozen,
            prop_board=_no_props, event_map={},
            params=params or best_bets_card.V2)

    def test_the_newly_admitted_underdog_can_become_a_plus_money_pick(self):
        """What the live path could not produce at all.

        +150, consensus 0.40, our number 0.47: inside the band (G4), inside
        the plus-money market band (G5), above the 0.30 plus floor (G6),
        marked down to 0.432 against a 0.41538 bar (G7), 0.07 from the
        market (G8), and its consensus does not exceed break-even (G13).
        """
        payload = self._card()
        self.assertEqual(1, payload["n_picks"])
        pick = payload["picks"][0]
        self.assertEqual("PLUS_MONEY", pick["price_class"])
        self.assertEqual(150, pick["price"])
        self.assertEqual("home", pick["side"])
        self.assertEqual(shadow.ENUMERATION_ID, pick["enumeration"])
        self.assertEqual(1, payload["n_plus_money_picks"])

    def test_the_live_path_publishes_no_pick_on_the_same_board(self):
        """The before half of the same comparison, through the real entry
        point: the favoured side fails G7 and is shown as a labelled fill,
        and there is no pick at all."""
        entries, rows, frozen = _slate(1, our_home=0.47)
        payload = card_v2.card_v2_for_date(
            entries, rows, date="2026-09-20", now=NOW, frozen=frozen,
            prop_board=_no_props, event_map={})
        self.assertEqual(0, payload["n_picks"])
        self.assertEqual(1, payload["n_fills"])
        self.assertEqual(1, payload["raw_pool_size"])

    def test_g11_still_keeps_one_entry_per_game_after_ranking(self):
        """Both sides of one game can pass together only under SHADOW_A,
        which drops the value test -- V2's own G7 cannot be satisfied on
        both sides of a complementary board at once. G11 is what stops the
        card listing a game twice, and it still runs after the pool widens.
        """
        payload = self._card(params=best_bets_card.SHADOW_A)
        game_ids = [e.get("game_id") for e in payload["all_bets"]]
        self.assertEqual(len(game_ids), len(set(game_ids)))
        self.assertEqual(1, len(payload["all_bets"]))

    def test_g14_still_caps_plus_money_picks_at_three(self):
        payload = self._card(n=6)
        self.assertEqual(3, payload["n_plus_money_picks"])
        self.assertEqual(3, len(payload["plus_money_dropped_by_subcap"]))

    def test_g12_still_caps_the_card_at_ten_entries(self):
        """With our number at 0.67 the FAVOURED side clears G7, so twelve
        games produce twelve eligible MAIN picks -- more than the ceiling
        the owner set on 2026-09-16."""
        payload = self._card(n=12, our_home=0.33)
        self.assertLessEqual(len(payload["all_bets"]), 10)
        self.assertEqual(10, payload["n_picks"])
        self.assertEqual(2, len(payload["ceiling_refused"]))

    def test_the_payload_is_marked_as_shadow_output(self):
        payload = self._card()
        self.assertTrue(payload["shadow"])
        self.assertEqual(shadow.ENUMERATION_ID, payload["enumeration"])
        self.assertEqual(best_bets_card.V2.rule_id, payload["rule"])


# ---------------------------------------------------------------------------
# 6. The prop arm. A SEPARATE arm, and the moneyline arm must not move.
# ---------------------------------------------------------------------------

def _contract(player, side, *, probability, price, market="batter_hits",
              line=0.5):
    """A propboard-shaped contract, both sides of which are complementary."""
    return {
        "player": player, "market": market, "line": line, "side": side,
        "probability": probability, "market_probability": 0.5,
        "breakeven": 0.5, "price": price, "books": 4,
        "observed_utc": NOW.isoformat(), "season_games": 120,
        "expected_pa_source": "batting_slot", "event_id": "E1",
    }


class PropArmIsSeparate(unittest.TestCase):

    def test_the_moneyline_arm_is_unchanged_when_props_are_off(self):
        """The arm already collecting a forward record must be byte-identical
        with the prop capability present. Folding props into it would change
        what that arm measures halfway through its own sample."""
        entries, rows, frozen = _slate(1, our_home=0.47)
        off = shadow.card_v2_for_date_shadow(
            entries, rows, date="2026-09-20", now=NOW, frozen=frozen,
            prop_board=_no_props, event_map={})
        self.assertEqual(shadow.ENUMERATION_ID, off["enumeration"])
        self.assertFalse(off["enumerate_props"])

    def test_turning_props_on_gives_the_run_its_own_identity(self):
        entries, rows, frozen = _slate(1, our_home=0.47)
        on = shadow.card_v2_for_date_shadow(
            entries, rows, date="2026-09-20", now=NOW, frozen=frozen,
            prop_board=_no_props, event_map={}, enumerate_props=True)
        self.assertIn(shadow.ENUMERATION_ID_PROPS, on["enumeration"])
        self.assertTrue(on["enumerate_props"])
        self.assertNotEqual(shadow.ENUMERATION_ID, on["enumeration"])

    def test_an_explicit_prop_board_is_never_overridden(self):
        """A caller that injects its own board -- every test in this repo --
        keeps it even with the prop arm on."""
        entries, rows, frozen = _slate(1, our_home=0.47)
        on = shadow.card_v2_for_date_shadow(
            entries, rows, date="2026-09-20", now=NOW, frozen=frozen,
            prop_board=_no_props, event_map={}, enumerate_props=True)
        self.assertEqual(0, on["raw_pool_size"] - 2)


class BothSidesPropBoard(unittest.TestCase):
    """`both_sides_prop_board` against `propboard.most_likely`'s own rule."""

    def test_the_under_side_is_what_the_live_filter_discards(self):
        """The defect, stated as arithmetic rather than asserted.

        The two sides of a contract are complementary, so exactly one of
        them can exceed 0.50. `most_likely` keeps only that one, which is
        why the under side of every contract is invisible to V2.
        """
        from src.analysis import propboard

        contracts = [
            _contract("A", "Over", probability=0.62, price=-140),
            _contract("A", "Under", probability=0.38, price=115),
            _contract("B", "Over", probability=0.44, price=120),
            _contract("B", "Under", probability=0.56, price=-135),
        ]
        kept = propboard.most_likely(contracts)
        self.assertEqual(2, len(kept))
        self.assertEqual({("A", "Over"), ("B", "Under")},
                         {(c["player"], c["side"]) for c in kept})
        # Both discarded sides carry a real price and a real probability --
        # they are not missing data, they are filtered data.
        discarded = [c for c in contracts if c not in kept]
        self.assertEqual(2, len(discarded))
        for c in discarded:
            self.assertIsNotNone(c["price"])
            self.assertGreater(c["probability"], 0.0)

    def test_only_the_registered_markets_are_enumerated(self):
        """Section 2 registers batter_hits and batter_total_bases. Home runs
        are not registered, and no book quotes their under anyway."""
        from src.analysis import daily_card as dc

        self.assertEqual(("batter_hits", "batter_total_bases"),
                         dc.PROP_MARKETS)
        self.assertNotIn("batter_home_runs", dc.PROP_MARKETS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
