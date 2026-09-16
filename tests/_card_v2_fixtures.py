"""Shared fixture builders for the T3/T4 V2 ledger and CLV tests.

Not itself a test module (no `Test*`/`*Case` classes), so
`python -m unittest discover` never collects it -- it is imported by the
`test_card_v2_*` files instead, the same way `tests/test_card_ledger.py`
keeps its own private `_card`/`_pick` helpers local rather than duplicating
literal fixtures in every file that needs one.

Field shapes here match what `src.appstate.card_ledger._frozen_v2_entry`
and `src.analysis.best_bets_card` actually read -- `price_class` is left
`None` by default so `_frozen_v2_entry` computes it itself from `price` via
`best_bets_card.price_class`, exactly as a real candidate from
`select()` would arrive.
"""

from __future__ import annotations


def game_entry(*, game_pk=5001, game_id=None, market="moneyline", side="home",
                price=-140, line=None, our_probability=0.62,
                market_probability=0.58, score=0.10, price_class=None,
                entry_class="pick", first_pitch_utc="2026-09-20T23:05:00Z",
                observed_utc="2026-09-20T18:00:00Z", event_id="evt-5001",
                books=8, take=True, game_type="R", failed_gates=None,
                label="STRONG", bet=None):
    return {
        "kind": "game",
        "label": label,
        "bet": bet or f"Take the moneyline at {price}",
        "why": ["because"],
        "market": market,
        "line": line,
        "side": side,
        "team": "NYY",
        "team_name": "Yankees",
        "opponent_name": "Rockies",
        "price": price,
        "book": "draftkings",
        "books": books,
        "confidence": our_probability,
        "market_probability": market_probability,
        "our_probability": our_probability,
        "model_probability": our_probability,
        "game_id": game_id,
        "game_pk": game_pk,
        "event_id": event_id,
        "away_team": "COL",
        "home_team": "NYY",
        "first_pitch_utc": first_pitch_utc,
        "observed_utc": observed_utc,
        "model": {},
        "score": score,
        "price_class": price_class,
        "entry_class": entry_class,
        "take": take,
        "no_take_reason": None,
        "game_type": game_type,
        "failed_gates": failed_gates if failed_gates is not None else [],
    }


def prop_entry(*, game_pk=5002, player="Devers", player_id="devers-1",
                market="batter_hits", price=120, line=0.5, side="over",
                our_probability=0.34, market_probability=0.30, score=0.05,
                price_class=None, entry_class="pick",
                first_pitch_utc="2026-09-20T23:05:00Z",
                observed_utc="2026-09-20T18:00:00Z", event_id="evt-5002",
                lineup_posted=True, season_games=12, take=True,
                game_type="R", label="PLUS", bet=None):
    return {
        "kind": "prop",
        "label": label,
        "bet": bet or f"Take {player} over {line} at {price}",
        "why": ["because"],
        "player": player,
        "player_id": player_id,
        "team": "BOS",
        "game_pk": game_pk,
        "event_id": event_id,
        "away_team": "BOS",
        "home_team": "NYY",
        "first_pitch_utc": first_pitch_utc,
        "market": market,
        "line": line,
        "side": side,
        "probability": our_probability,
        "market_probability": market_probability,
        "our_probability": our_probability,
        "price": price,
        "book": "draftkings",
        "books": 9,
        "batting_slot": 3,
        "expected_pa": 4.2,
        "expected_pa_source": "season_average",
        "observed_utc": observed_utc,
        "lineup_posted": lineup_posted,
        "season_games": season_games,
        "score": score,
        "price_class": price_class,
        "entry_class": entry_class,
        "take": take,
        "no_take_reason": None,
        "game_type": game_type,
        "failed_gates": [],
    }


def select_result(date="2026-09-20", picks=None, prop_picks=None, fills=None,
                   close_calls_not_shown=None, stale_board=None, params=None):
    """A dict shaped like `best_bets_card.select()`'s own return, plus the
    `date` key `publish_v2` requires -- `select()` itself carries no date
    (the caller supplies the slate date), so every ledger-facing fixture
    adds it here rather than at each call site. `all_bets` is left unset on
    purpose: `publish_v2` builds it from `picks + prop_picks + fills` when
    `all_bets` is absent, exactly as a caller handing in `select()`'s raw
    `picks`/`prop_picks`/`fills` keys would.
    """
    return {
        "date": date,
        "params": params,
        "picks": picks if picks is not None else [],
        "prop_picks": prop_picks if prop_picks is not None else [],
        "fills": fills if fills is not None else [],
        "close_calls_not_shown": close_calls_not_shown or [],
        "stale_board": stale_board,
    }


def result_row(away_score, home_score):
    return {"away_score": away_score, "home_score": home_score}
