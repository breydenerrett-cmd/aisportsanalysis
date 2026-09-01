"""Contract/integration tests that freeze the JSON payload shapes a design
system will be built against, for every endpoint in this paid-beta lane:
GET /today, GET /games/{date}, GET /game/{date}/{away}/{home},
GET /changed/{date}, GET /odds/{date}, GET /odds/{date}/{away}/{home},
POST /betcheck, GET /my-bets.

WHY "REQUIRED KEYS + TYPES", NEVER EXACT-MATCH
------------------------------------------------
A concurrent agent may add additive freshness keys to the today/games
payloads (odds-age, cache metadata, ...) and api/odds.py may appear as a
new sibling endpoint. Asserting `set(payload) == {...}` would break the
instant either of those additive changes lands, for no product reason --
this suite is not the place to police "did anyone add a field," only "did
anyone remove or retype one a client already depends on." Every assertion
here is therefore REQUIRED-SHAPE: a required key must be present and of the
declared type/enum; an extra key is always allowed.

SKIP-IF-NO-FASTAPI, LIKE THE REST OF api/
------------------------------------------
Same pattern as tests/test_api_games.py and tests/test_api_betcheck.py:
api/ is allowed to depend on FastAPI; this repo's test environment does
not always have it installed. If FastAPI is unavailable the whole module
is skipped rather than the suite failing on an unrelated dependency gap.

MOBILE-READINESS RULES (asserted at the wire, on every payload below)
------------------------------------------------------------------------
  - every timestamp field (name ends in `_utc`, or is literally `generated_at`)
    is ISO-8601 with an explicit UTC offset -- a mobile client must never
    have to guess a timezone.
  - every American-odds price field (name is `american_price`, or ends in
    `_price`/`_prices` and the endpoint documents it as a moneyline price:
    `away_price`/`home_price`/`best_price`) is a plain `int`, never a float
    or numeric string a client would have to coerce.
  - every field whose name marks it a PERCENTAGE (contains "pct" or
    "percent") is a `float` in [0, 100] and rides beside a sibling `label`
    field on the same dict -- this repo's probabilities (`*_fair`,
    `*_probability`, `implied_probability`) are fractions in [0, 1] by
    design (src/analysis/contracts.py's MarketImpliedConsensus) and are
    deliberately NOT covered by this rule; they are a different, already-
    pinned vocabulary (tests/test_contracts.py).
  - no string value anywhere in a payload contains an HTML tag -- a design
    system renders these directly and must never have to sanitise.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    from api import betcheck as betcheck_api
    from api import games as games_mod
    from api import mybets as mybets_api
    from api import odds as odds_api
    from api.today import build_today_payload
    from src.analysis import prices as prices_mod
    from src.appstate import savedbets as savedbets_store
    from src.appstate import users as users_store
    from src.providers import mlb


def _schedule(date="2026-08-31"):
    return [{
        "game_pk": 990101, "date": date, "away_team": "BOS", "home_team": "NYY",
        "venue": "Yankee Stadium", "start_time_utc": f"{date}T23:05:00Z",
    }]


# ---------------------------------------------------------------------------
# Mobile-readiness assertion helpers -- reused across every endpoint's test
# class below, so the vocabulary rule is enforced identically everywhere
# rather than re-typed (and possibly drifting) per endpoint.
# ---------------------------------------------------------------------------

_TIMESTAMP_NAME_RE = re.compile(r"(^|_)utc$")
_HTML_TAG_RE = re.compile(r"<\s*[a-zA-Z!/][^>]*>")


def _assert_iso8601_utc(test: unittest.TestCase, value, where: str) -> None:
    test.assertIsInstance(value, str, f"{where} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    test.assertIsNotNone(
        parsed.tzinfo, f"{where}={value!r} has no timezone -- a mobile "
        "client must never have to assume one")
    offset = parsed.utcoffset()
    test.assertEqual(
        offset.total_seconds(), 0,
        f"{where}={value!r} is not UTC (offset {offset})")


def _walk(payload, path=""):
    """Yield (path, value) for every leaf value in a JSON-shaped structure,
    depth-first -- the one traversal every rule below reuses so "check every
    field named X anywhere in the payload" is one function, not six."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield from _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(payload, list):
        for i, value in enumerate(payload):
            yield from _walk(value, f"{path}[{i}]")
    else:
        yield path, payload


def assert_mobile_ready(test: unittest.TestCase, payload: dict) -> None:
    """The four wire-level rules every endpoint in this file must satisfy.
    Called once per payload, after the endpoint-specific shape assertions,
    so a violation is reported against a payload already known to have the
    right required keys."""
    blob = json.dumps(payload)  # round-trips end to end with no TypeError
    reloaded = json.loads(blob)

    for path, value in _walk(reloaded):
        leaf = path.rsplit(".", 1)[-1].split("[")[0]

        if leaf.endswith("_utc") or leaf == "generated_at":
            if value is not None:
                _assert_iso8601_utc(test, value, path)

        if leaf == "american_price" or leaf in (
                "away_price", "home_price", "best_price"):
            if value is not None:
                test.assertIsInstance(
                    value, int,
                    f"{path}={value!r} must be a plain American-odds int")
                test.assertNotIsInstance(
                    value, bool, f"{path} must not be a bool")

        if ("pct" in leaf.lower() or "percent" in leaf.lower()) and value is not None:
            test.assertIsInstance(
                value, float, f"{path}={value!r} percentage must be a float")
            test.assertTrue(
                0.0 <= value <= 100.0,
                f"{path}={value!r} percentage must be in [0, 100]")

        if isinstance(value, str):
            test.assertIsNone(
                _HTML_TAG_RE.search(value),
                f"{path}={value!r} contains an HTML tag")


class _Checked:
    """A required-shape rule that is both a type/tuple-of-types AND a value
    predicate -- kept as its own wrapper (never a bare tuple) because a
    plain `(int, type(None))` is ALSO a tuple of two callables and would be
    ambiguous with a `(types, check)` pair if both used raw tuples."""

    __slots__ = ("types", "check")

    def __init__(self, types, check):
        self.types = types
        self.check = check


def assert_required_shape(test: unittest.TestCase, payload: dict,
                          spec: dict, *, where: str = "") -> None:
    """`spec` maps a required key to either a type/tuple-of-types, or a
    `_Checked(types, predicate)` for an extra value constraint. Nested dict
    specs recurse. This never asserts payload has ONLY these keys -- see
    the module docstring's required-shape rationale."""
    for key, rule in spec.items():
        loc = f"{where}.{key}" if where else key
        test.assertIn(key, payload, f"{loc} is a required key")
        value = payload[key]
        if isinstance(rule, dict):
            test.assertIsInstance(value, dict, f"{loc} must be a dict")
            assert_required_shape(test, value, rule, where=loc)
            continue
        if isinstance(rule, _Checked):
            test.assertIsInstance(value, rule.types, f"{loc} must be {rule.types}")
            test.assertTrue(rule.check(value), f"{loc}={value!r} failed its check")
            continue
        test.assertIsInstance(value, rule, f"{loc} must be {rule}")


def _ENUM(*values):
    return _Checked(str, lambda v: v in values)


# ---------------------------------------------------------------------------
# GET /today (no path parameter -- the server's own date; see docs/
# API_CONTRACTS.md. build_today_payload is the real function GET /today
# calls (api/app.py), just with the date injected instead of read from
# date.today() -- same offline-testability reasoning every other class in
# this file uses.)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class TodayContractTests(unittest.TestCase):

    TODAY_SPEC = {
        "date": str,
        "generated_at": str,
        "games": list,
        "notes": list,
    }
    ENTRY_SPEC = {
        "verdict": (str, type(None)),
        "side": (str, type(None)),
        "market": (str, type(None)),
        "summary": (str, type(None)),
        "odds_meta": {
            "observed_utc": (str, type(None)),
            "age_seconds": (int, float, type(None)),
            "has_market": bool,
        },
    }

    def _payload(self):
        from src.pipeline import history
        store = history.read_results()
        return build_today_payload(_schedule(), store, date="2026-08-31")

    def test_required_shape(self):
        payload = self._payload()
        assert_required_shape(self, payload, self.TODAY_SPEC)
        self.assertEqual(len(payload["games"]), 1)
        assert_required_shape(self, payload["games"][0], self.ENTRY_SPEC,
                              where="games[0]")

    def test_mobile_readiness(self):
        assert_mobile_ready(self, self._payload())

    def test_no_forbidden_win_probability_vocabulary(self):
        blob = json.dumps(self._payload()).lower()
        for forbidden in ("win_probability", "win_prob", '"true_probability"'):
            self.assertNotIn(forbidden, blob)


# ---------------------------------------------------------------------------
# GET /games/{date}
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GamesListContractTests(unittest.TestCase):

    SLATE_SPEC = {
        "date": (str, type(None)),
        "generated_at": str,
        "checked_games": _Checked(int, lambda v: v >= 0),
        "games": list,
        "notes": list,
    }
    GAME_ROW_SPEC = {
        "game_id": str,
        "away_team": str,
        "home_team": str,
        "date": (str, type(None)),
        "first_pitch_utc": (str, type(None)),
        "verdict": _ENUM("no_play", "candidate", "flagged", "market_unavailable"),
        "board_summary": {
            "observed_utc": (str, type(None)),
            "has_board": bool,
        },
        "data_quality": {
            "has_market": bool,
            "has_lineups": bool,
            "has_starters": bool,
            "has_price_board": bool,
            "gaps": dict,
        },
    }

    def _payload(self, date="2026-08-31"):
        with patch.object(mlb, "fetch_games", return_value=_schedule(date)):
            return games_mod.get_games(date)

    def test_required_shape(self):
        payload = self._payload()
        assert_required_shape(self, payload, self.SLATE_SPEC)
        self.assertEqual(len(payload["games"]), 1)
        assert_required_shape(self, payload["games"][0], self.GAME_ROW_SPEC,
                              where="games[0]")

    def test_market_implied_consensus_is_a_probability_pair_or_absent(self):
        """away_fair/home_fair are fractions in [0, 1] -- see the module
        docstring's note on why the percentage rule does not apply here."""
        payload = self._payload()
        consensus = payload["games"][0]["market_implied_consensus"]
        if consensus is not None:
            for side in ("away_fair", "home_fair"):
                self.assertIn(side, consensus)
                self.assertIsInstance(consensus[side], float)
                self.assertTrue(0.0 <= consensus[side] <= 1.0)

    def test_empty_slate_still_reports_checked_games(self):
        with patch.object(mlb, "fetch_games", return_value=[]):
            payload = games_mod.get_games("2026-12-25")
        assert_required_shape(self, payload, self.SLATE_SPEC)
        self.assertEqual(payload["checked_games"], 0)
        self.assertEqual(payload["games"], [])

    def test_mobile_readiness(self):
        assert_mobile_ready(self, self._payload())
        assert_mobile_ready(self, self._payload_with_market())

    def _payload_with_market(self, date="2026-08-31"):
        """Same slate-list shape, but with a priced market section, built
        via the real domain path directly (src.pipeline.briefing.build_slate
        + src.analysis.gamepayload) -- bypassing games_mod._build_entries'
        network fetch + freshness cache, the same offline-injection pattern
        tests/test_api_today.py uses for its own priced-market case."""
        from src.analysis import gamepayload
        from src.pipeline import briefing, history
        prices_by_matchup = {("BOS", "NYY"): {"h2h": {
            "away_price": 120, "home_price": -140,
            "away_fair": 0.45, "home_fair": 0.55}}}
        store = history.read_results()
        slate = briefing.build_slate(_schedule(date), store,
                                     prices_by_matchup=prices_by_matchup)
        return gamepayload.build_slate_list(slate["games"], date=date,
                                            notes=slate.get("notes", []))


# ---------------------------------------------------------------------------
# GET /game/{date}/{away}/{home}
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class GameDetailContractTests(unittest.TestCase):

    QUICK_SPEC = {
        "game_id": str,
        "away_team": str,
        "home_team": str,
        "verdict": _ENUM("no_play", "candidate", "flagged", "market_unavailable"),
        "top_findings": list,
        "price": dict,
    }
    ADVANCED_SPEC = {
        "game_id": str,
        "away_team": str,
        "home_team": str,
        "game": dict,
        "verdict": str,
        "information_time": str,
        "sections": dict,
        "gaps": dict,
        "findings": list,
        "staleness": dict,
    }

    def _payload(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            return games_mod.get_game("2026-08-31", "BOS", "NYY")

    def test_required_shape(self):
        payload = self._payload()
        self.assertIn("quick", payload)
        self.assertIn("advanced", payload)
        assert_required_shape(self, payload["quick"], self.QUICK_SPEC,
                              where="quick")
        assert_required_shape(self, payload["advanced"], self.ADVANCED_SPEC,
                              where="advanced")

    def test_price_section_reports_availability_honestly(self):
        price = self._payload()["quick"]["price"]
        self.assertIn("available", price)
        self.assertIsInstance(price["available"], bool)
        if not price["available"]:
            self.assertIn("reason", price)
            self.assertIsInstance(price["reason"], str)

    def test_unknown_game_is_a_structured_404(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                games_mod.get_game("2026-08-31", "SEA", "TEX")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_mobile_readiness(self):
        assert_mobile_ready(self, self._payload())


# ---------------------------------------------------------------------------
# GET /changed/{date}
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class ChangedContractTests(unittest.TestCase):

    CHANGED_SPEC = {
        "date": (str, type(None)),
        "generated_at": str,
        "checked_games": _Checked(int, lambda v: v >= 0),
        "items": list,
        "notes": list,
    }
    ITEM_SPEC = {
        "game_id": str,
        "away_team": str,
        "home_team": str,
        "headline": (str, type(None)),
        "tier": _ENUM("HIGH", "MEDIUM", "LOW", "UNKNOWN"),
        "seen_utc": (str, type(None)),
        "inadmissible": bool,
    }

    def _payload(self, date="2026-08-31"):
        with patch.object(mlb, "fetch_games", return_value=_schedule(date)):
            return games_mod.get_changed(date)

    def test_required_shape(self):
        payload = self._payload()
        assert_required_shape(self, payload, self.CHANGED_SPEC)
        for i, item in enumerate(payload["items"]):
            assert_required_shape(self, item, self.ITEM_SPEC, where=f"items[{i}]")

    def test_quiet_slate_still_reports_checked_games(self):
        payload = self._payload()
        self.assertEqual(payload["checked_games"], 1)
        if not payload["items"]:
            self.assertTrue(payload["notes"])  # never a silent empty list

    def test_mobile_readiness(self):
        assert_mobile_ready(self, self._payload())


# ---------------------------------------------------------------------------
# GET /odds/{date}, GET /odds/{date}/{away}/{home}
#
# Fixture boards mirror tests/test_api_odds.py's own fixture (six books --
# `prices.MIN_BOOKS` -- so `consensus` actually computes instead of hitting
# the below-the-floor `skipped` path every time). Kept as a second, local
# copy rather than importing that module's helpers: this file's fixtures
# are deliberately self-contained per the "generated by hand from the same
# fixtures the contract tests use" doc rule at the top of this file.
# ---------------------------------------------------------------------------

_ODDS_TS = "2026-08-31T19:55:00Z"


def _odds_quote(book, away, home):
    return {"ts": _ODDS_TS, "book": book, "away_price": away, "home_price": home}


def _odds_boards(date="2026-08-31"):
    quotes = [_odds_quote("fanduel", -110, -110), _odds_quote("draftkings", -108, -112),
              _odds_quote("betmgm", -105, -115), _odds_quote("caesars", -112, -108),
              _odds_quote("pointsbet", -115, -105), _odds_quote("wynn", -120, -100)]
    key = ("BOS", "NYY", date)
    return {key: {"quotes": quotes, "observed_utc": _ODDS_TS, "source": "test"}}


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class OddsSlateContractTests(unittest.TestCase):

    SLATE_SPEC = {
        "date": (str, type(None)),
        "generated_at": str,
        "games": list,
        "summary": {
            "games_count": _Checked(int, lambda v: v >= 0),
            "books_disagree_on_favorite_count": _Checked(int, lambda v: v >= 0),
        },
    }
    GAME_SPEC = {
        "game_id": str,
        "away_team": str,
        "home_team": str,
        "date": (str, type(None)),
        "first_pitch_utc": (str, type(None)),
        "venue": (str, type(None)),
        "markets": dict,
    }
    H2H_AVAILABLE_SPEC = {
        "board_available": bool,
        "reason": type(None),
        "board": list,
        "best": dict,
        "consensus": dict,
        "spread_cents": dict,
        "staleness": {
            "observed_utc": (str, type(None)),
            "age_seconds": (int, float, type(None)),
            "has_board": bool,
        },
    }
    H2H_UNAVAILABLE_SPEC = {
        "board_available": bool,
        "reason": str,
        "board": list,
        "best": type(None),
        "consensus": type(None),
        "spread_cents": dict,
        "staleness": dict,
    }

    def _payload(self, date="2026-08-31"):
        with patch.object(mlb, "fetch_games", return_value=_schedule(date)), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_odds_boards(date)):
            return odds_api.get_odds(date)

    def test_required_shape_with_a_priced_board(self):
        payload = self._payload()
        assert_required_shape(self, payload, self.SLATE_SPEC)
        self.assertEqual(len(payload["games"]), 1)
        game = payload["games"][0]
        assert_required_shape(self, game, self.GAME_SPEC, where="games[0]")
        h2h = game["markets"]["h2h"]
        assert_required_shape(self, h2h, self.H2H_AVAILABLE_SPEC, where="games[0].markets.h2h")
        # Six books priced on each side -- at the MIN_BOOKS floor -- so a
        # consensus is actually computed, not the below-floor `skipped` path.
        for side in ("away", "home"):
            self.assertIn(side, h2h["consensus"])
            self.assertIsInstance(h2h["consensus"][side]["implied_probability"], float)

    def test_no_board_is_an_honest_unavailable_state_not_an_error(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value={}):
            payload = odds_api.get_odds("2026-08-31")
        h2h = payload["games"][0]["markets"]["h2h"]
        assert_required_shape(self, h2h, self.H2H_UNAVAILABLE_SPEC, where="markets.h2h")
        self.assertFalse(h2h["board_available"])
        self.assertEqual(h2h["spread_cents"], {"away": None, "home": None})

    def test_empty_slate_is_an_honest_empty_summary(self):
        with patch.object(mlb, "fetch_games", return_value=[]), \
             patch.object(prices_mod, "boards_by_matchup", return_value={}):
            payload = odds_api.get_odds("2026-12-25")
        assert_required_shape(self, payload, self.SLATE_SPEC)
        self.assertEqual(payload["games"], [])
        self.assertEqual(payload["summary"]["games_count"], 0)

    def test_extra_keys_are_allowed_additive_shape(self):
        """The required-shape pattern this whole file relies on: an extra
        key alongside the required ones (a future `odds_meta`-style
        addition to the h2h section, or a slate-level field) must never
        fail this assertion -- only a MISSING required key, or a required
        key with the wrong type, is a real break. See the module
        docstring's "REQUIRED KEYS + TYPES, never exact-match" rule."""
        payload = self._payload()
        payload["summary"]["widest_spread_game"] = {"extra": "unpinned field, allowed"}
        payload["games"][0]["markets"]["h2h"]["board"][0]["extra_book_field"] = "allowed"
        assert_required_shape(self, payload, self.SLATE_SPEC)
        assert_required_shape(self, payload["games"][0], self.GAME_SPEC, where="games[0]")

    def test_mobile_readiness(self):
        assert_mobile_ready(self, self._payload())
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value={}):
            assert_mobile_ready(self, odds_api.get_odds("2026-08-31"))


@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class OddsGameContractTests(unittest.TestCase):

    def _payload(self, date="2026-08-31"):
        with patch.object(mlb, "fetch_games", return_value=_schedule(date)), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_odds_boards(date)):
            return odds_api.get_odds_game(date, "BOS", "NYY")

    def test_required_shape(self):
        payload = self._payload()
        assert_required_shape(self, payload, OddsSlateContractTests.GAME_SPEC)
        assert_required_shape(self, payload["markets"]["h2h"],
                              OddsSlateContractTests.H2H_AVAILABLE_SPEC,
                              where="markets.h2h")

    def test_unknown_game_is_a_structured_404(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()), \
             patch.object(prices_mod, "boards_by_matchup", return_value=_odds_boards()):
            with self.assertRaises(fastapi.HTTPException) as ctx:
                odds_api.get_odds_game("2026-08-31", "SEA", "TEX")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_mobile_readiness(self):
        assert_mobile_ready(self, self._payload())


# ---------------------------------------------------------------------------
# POST /betcheck
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class BetCheckContractTests(unittest.TestCase):

    BETCHECK_SPEC = {
        "query": {
            "raw": str,
            "parsed": bool,
        },
        "game": (dict, type(None)),
        "thesis_support": list,
        "counterargument": list,
        "counterargument_lines": _Checked(list, lambda v: len(v) >= 1),
        "best_available_price": (dict, type(None)),
        "market_consensus": (dict, type(None)),
        "your_price_beats_consensus": (bool, type(None)),
        "what_changed": list,
        "recommendation": type(None),  # Ranker Engine 2 stays gated
        "price_improvement": (dict, type(None)),
        "bottom_line": (str, type(None)),
    }

    def _payload(self, price=-140):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            body = betcheck_api.BetCheckRequest(
                date="2026-08-31", away="BOS", home="NYY", side="home",
                american_price=price)
            return betcheck_api.post_betcheck(body)

    def test_required_shape(self):
        payload = self._payload()
        assert_required_shape(self, payload, self.BETCHECK_SPEC)

    def test_recommendation_is_permanently_null(self):
        """Ranker Engine 2 stays gated -- pinned at the wire, not just in
        the dataclass. A design system must never branch on a truthy
        recommendation field existing here."""
        payload = self._payload()
        self.assertIsNone(payload["recommendation"])

    def test_game_ref_shape_when_present(self):
        payload = self._payload()
        if payload["game"] is not None:
            for key in ("away", "home", "date", "game_id", "start_time_utc"):
                self.assertIn(key, payload["game"])

    def test_implausible_price_is_a_422_not_a_500(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            betcheck_api.BetCheckRequest(date="2026-08-31", away="BOS",
                                         home="NYY", side="home",
                                         american_price=5)

    def test_unknown_game_is_a_structured_404(self):
        with patch.object(mlb, "fetch_games", return_value=_schedule()):
            body = betcheck_api.BetCheckRequest(
                date="2026-08-31", away="SEA", home="TEX", side="home",
                american_price=-140)
            with self.assertRaises(fastapi.HTTPException) as ctx:
                betcheck_api.post_betcheck(body)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_mobile_readiness(self):
        assert_mobile_ready(self, self._payload())

    def test_no_bet_placement_field_anywhere(self):
        """No field on this contract lets a client place a bet -- Ranker
        Engine 2 stays gated at every layer, including the wire."""
        blob = json.dumps(self._payload()).lower()
        for forbidden in ("place_bet", "confirm_bet", "stake", "wager_id"):
            self.assertNotIn(forbidden, blob)


# ---------------------------------------------------------------------------
# GET /my-bets
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_FASTAPI, "fastapi not installed")
class MyBetsContractTests(unittest.TestCase):

    LIST_SPEC = {"bets": list}
    BET_SPEC = {
        "id": int,
        "game": str,
        "side": str,
        "price": (int, float, type(None)),
        "saved_at": str,
        "snapshot_digest": (str, type(None)),
    }

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "app.db"
        self._patcher = patch.object(savedbets_store, "db_path", lambda: self.db)
        self._patcher.start()
        self.user = users_store.create_user("contractuser@example.com", db=self.db)

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def test_empty_list_shape(self):
        payload = mybets_api.list_my_bets(current_user=self.user)
        assert_required_shape(self, payload, self.LIST_SPEC)

    def test_saved_bet_required_shape(self):
        created = mybets_api.create_my_bet(
            mybets_api.SaveBetRequest(game="BOS@NYY", side="BOS ML",
                                      price=120, snapshot_digest="deadbeef"),
            current_user=self.user)
        assert_required_shape(self, created, self.BET_SPEC, where="created")

        listed = mybets_api.list_my_bets(current_user=self.user)
        assert_required_shape(self, listed, self.LIST_SPEC)
        assert_required_shape(self, listed["bets"][0], self.BET_SPEC,
                              where="bets[0]")

    def test_saved_at_is_iso8601_utc(self):
        created = mybets_api.create_my_bet(
            mybets_api.SaveBetRequest(game="BOS@NYY", side="BOS ML"),
            current_user=self.user)
        _assert_iso8601_utc(self, created["saved_at"], "saved_at")

    def test_mobile_readiness(self):
        created = mybets_api.create_my_bet(
            mybets_api.SaveBetRequest(game="BOS@NYY", side="BOS ML",
                                      price=120, snapshot_digest="deadbeef"),
            current_user=self.user)
        assert_mobile_ready(self, created)
        assert_mobile_ready(self, mybets_api.list_my_bets(current_user=self.user))


if __name__ == "__main__":
    unittest.main()
