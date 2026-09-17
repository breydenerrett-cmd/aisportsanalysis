"""T5 -- assemble DAILY_CARD_BEST_BETS_V2's payload for one date.

Same division of labour `src/report/card.py` already keeps: this module
reads live inputs and builds candidates; `src.analysis.best_bets_card` (V2's
rule, FROZEN by registration 11.2 -- read only, never edited by this file)
decides what is a pick, a fill, or neither. This file is fingerprinted
alongside it (`src.appstate.card_ledger.V2_FINGERPRINT_FILES`) precisely
because it is the step that hands the frozen 2025-fit numbers to the model
-- get that step wrong and the fingerprint would not catch it if it lived
somewhere else.

WHY A SEPARATE MODULE FROM `src/report/card.py`
-------------------------------------------------
`card.py` is V1's plumbing and stays exactly as V1 needs it; growing V2's
candidate-building inside it would put a change made for V2's frozen
calibration behind the same file V1's own fingerprint (`V1_FINGERPRINT_FILES`)
watches, and a V2-only edit would then look like a V1 code change to anyone
reading `v1_code_fingerprint` drift. So this file imports the handful of
pure helpers `card.py` already exposes (`_game_identity`, `_flatten`,
`_has_started`, `moneyline_rows`, `run_line_rows`, `_enriched_prop_contracts`,
`relief_rates_for`, `attach_knowledge`) rather than duplicating them, and
adds nothing to `card.py` itself beyond that split (T5's own note in the
build plan: "reusing ... imported from src/report/card.py").

WHERE THE FROZEN NUMBERS COME IN
-----------------------------------
`strength.model_line(..., dispersion=...)` and the moneyline Platt
calibration both come from `data/processed/card_v2_frozen_params.json`
(T0a), read once per call by `load_frozen_params` and passed explicitly --
never read from `data/processed/card_calibration.json`, V1's nightly refit,
which this module never opens. A missing or unreadable frozen-parameter
file is not a 50/50 guess; it is `CardV2Error`, because a V2 card built
without its own fitted numbers is not V2's card at all (registration 11.2,
G9).

PROP CANDIDATES REUSE V1'S BOARD ON PURPOSE
----------------------------------------------
T0a's additive `rho`/`slot_table` arguments to `playerprops.price_prop` are
real capability, but wiring them through the live prop board
(`src.report.props.board_for_date` -> `src.analysis.propboard.build`) is
its own change to a file neither this task nor its build-plan row touches.
T5's own row says to reuse "the prop board read already in
`_build_prop_picks`", so V2's prop candidates are built from the identical
enriched contracts V1 already computes (`card._enriched_prop_contracts`),
carrying V1's live rho/slot-table numbers -- the same board every reader
already sees, gated and scored by V2's own rule instead of V1's. If the
frozen prop parameters are ever wired into the live board, this module
needs no change: it reads whatever `probability`/`season_games`/
`expected_pa_source` the contract carries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from src.analysis import best_bets_card, calibrate, daily_card, strength
from src.report import card as card_v1

FROZEN_PARAMS_PATH = "data/processed/card_v2_frozen_params.json"


class CardV2Error(Exception):
    """V2 cannot be built without a fact it needs -- never a silent guess."""


def load_frozen_params(path: str = FROZEN_PARAMS_PATH) -> dict:
    """The T0a fit, read fresh on every call (it changes once, at a fit
    run, never per-request, but a page-render cache belongs to the caller
    if it wants one -- this module makes no clock or disk-caching claim).
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise CardV2Error(
            f"card v2 frozen parameter file missing or unreadable: {path}"
        ) from exc


def _moneyline_calibration(frozen: Mapping) -> Optional[calibrate.Calibration]:
    """The frozen Platt fit as a `calibrate.Calibration`, or `None` if the
    frozen file's own fit failed (mirrors `card.load_calibration`'s "None is
    a real answer" contract) -- `card_for_date` sets `calibrated: False` and
    G9 refuses every game candidate rather than serving an uncalibrated
    number as if it were fitted.
    """
    blob = frozen.get("moneyline_calibration") or {}
    if not blob.get("fitted"):
        return None
    try:
        return calibrate.Calibration(
            float(blob["a"]), float(blob["b"]), int(blob["n"]),
            float(blob.get("base_rate", 0.5)))
    except (KeyError, TypeError, ValueError):
        return None


def _game_type(entry: Mapping) -> str:
    """The frozen field V2's ledger and T8's population filter both need
    (`card_ledger.V2_FROZEN_FIELDS`, registration 11's `game_type == "R"`
    filter). Every provider this repo reads (`src.providers.mlb.parse_game`)
    carries `game_type` on the RAW game dict, but `card._game_identity`
    does not forward it (V1 never needed it), so it is read here straight
    off the entry's own dossier game section, with the same regular-season
    default V1's schedule pipeline has always assumed when the field is
    absent -- this project has never captured a live postseason slate.
    """
    from src.detect import dossier as dossier_mod

    dossier = entry.get("dossier")
    payload = (dossier.to_dict() if isinstance(dossier, dossier_mod.Dossier)
              else (dossier or {}))
    game = payload.get("game") or {}
    return game.get("game_type") or entry.get("game_type") or "R"


def _observed_dt(value) -> Optional[datetime]:
    """`best_bets_card.quote_age_seconds` does `now - observed_utc` with no
    parsing of its own (by design -- it is pure and takes whatever `now` a
    caller froze), so `observed_utc` has to already be a `datetime` by the
    time a candidate reaches `select()`. Every live store this repo has
    round-trips through JSON and hands this module back an ISO string
    (`src.analysis.opportunities`'s rows, the prop board's contracts), so
    this is the one place that string is parsed before G3 ever sees it --
    get this wrong and every real candidate fails G3_STALE regardless of
    how fresh its quote actually is, which is exactly the silent failure
    `tests/test_card_v2_report.py` pins against a datetime-typed fixture.
    """
    return card_v1._parse_first_pitch(value)


def _bet_sentence(candidate: Mapping) -> str:
    """The raw selection sentence `best_bets_card.bet_sentence` prepends
    "Take " to (C2's headline). Never includes the price's sign guess --
    `daily_card._fmt_price` already renders "+124" / "-160" correctly."""
    price_txt = daily_card._fmt_price(candidate.get("price"))
    return f"{candidate.get('team_name')} moneyline at {price_txt}"


def _build_game_candidates(entries: Sequence, opportunity_rows: Sequence, *,
                           date: str, now: datetime, frozen: Mapping,
                           multibook_rows=None) -> tuple:
    """`(candidates, raw_pool_size)` -- one best_bets_card-shaped candidate
    per open game with a priced moneyline side, built the same way
    `card.card_for_date`'s live branch builds V1's, but with the frozen
    dispersion and the frozen moneyline calibration in place of
    `strength.DISPERSION` and `card.load_calibration()`'s nightly refit.

    `raw_pool_size` counts every game on the slate that reached a moneyline
    consensus side at all, BEFORE any V2 gate runs -- the number this
    module's caller needs to tell "no priced board existed" (raw_pool_size
    == 0, games_on_slate == 0 or every game started) apart from "a priced
    board existed and every candidate on it was refused" (raw_pool_size > 0,
    n_picks == 0). Collapsing those two into one message is exactly the
    honesty failure `docs/CARD_V2_BUILD_PLAN.md` names for this task.
    """
    dispersion = frozen.get("DISPERSION")
    cal = _moneyline_calibration(frozen)

    games, model_lines = [], {}
    feature_rows = [card_v1._flatten(e) for e in entries or ()]
    league_rpg = strength.league_runs_per_game(feature_rows)
    relief = card_v1.relief_rates_for(date)

    for entry in entries or ():
        game = card_v1._game_identity(entry, date=date)
        if card_v1._has_started(game["first_pitch_utc"], now):
            continue
        if not league_rpg:
            continue
        game["features"]["away_bullpen_rate"] = relief.get(game["away_team"])
        game["features"]["home_bullpen_rate"] = relief.get(game["home_team"])
        game["game_type"] = _game_type(entry)
        try:
            line = strength.model_line(
                game["features"], league_rpg=league_rpg,
                run_line=card_v1.RUN_LINE, dispersion=dispersion)
        except strength.StrengthError:
            continue
        if cal is not None:
            raw = line["p_home"]
            line["p_home_raw"] = raw
            line["p_home"] = cal.apply(raw)
            line["p_away"] = 1.0 - line["p_home"]
        games.append(game)
        model_lines[game["game_id"]] = line

    ml_rows = card_v1.moneyline_rows(opportunity_rows)
    raw_candidates = daily_card.build_pick_candidates(
        games, model_lines=model_lines, moneyline_rows=ml_rows,
        runline_rows=card_v1.run_line_rows(date, rows=multibook_rows))

    game_type_by_id = {g["game_id"]: g.get("game_type", "R") for g in games}
    calibrated = cal is not None

    candidates = []
    for c in raw_candidates:
        price = c.get("price")
        candidates.append({
            "kind": "game",
            "game_id": c.get("game_id"),
            "game_pk": c.get("game_pk"),
            "player_id": None,
            "player": None,
            "price": price,
            "market_probability": c.get("market_probability"),
            "our_probability": c.get("model_probability"),
            # Aliased for `card.attach_knowledge`'s "+" grade bonus, which
            # reads this exact key name on a moneyline pick -- not read by
            # `best_bets_card` itself, which only ever reads
            # `our_probability` (see that module's `failed_gates` docstring).
            "model_probability": c.get("model_probability"),
            "books": c.get("books"),
            "observed_utc": _observed_dt(c.get("observed_utc")),
            "has_started": False,  # `games` already excludes started games
            "calibrated": calibrated,
            "first_pitch": c.get("first_pitch_utc"),
            "first_pitch_utc": c.get("first_pitch_utc"),
            "bet_sentence": _bet_sentence(c),
            "team_name": c.get("team_name"),
            "away_team": c.get("away_team"),
            "home_team": c.get("home_team"),
            "game_type": game_type_by_id.get(c.get("game_id"), "R"),
            "market": c.get("market"),
            "side": c.get("side"),
            "line": None,
        })
    return candidates, len(raw_candidates)


def _build_prop_candidates(entries: Sequence, *, date: str, now: datetime,
                           prop_board=None, event_map=None) -> tuple:
    """`(candidates, raw_pool_size)`, the prop-side counterpart of
    `_build_game_candidates`. Reuses `card._enriched_prop_contracts` (the
    join to tonight's schedule V1 already computes) so the two rules never
    read two different resolutions of the same event_id -> game_pk map.
    """
    enriched, reason = card_v1._enriched_prop_contracts(
        entries, date=date, prop_board=prop_board, event_map=event_map)
    if reason is not None:
        return [], 0

    candidates = []
    for c in enriched:
        if daily_card._prop_game_started(c.get("first_pitch_utc"), now):
            continue
        player = c.get("player")
        lineup_posted = c.get("expected_pa_source") == "batting_slot"
        candidates.append({
            "kind": "prop",
            "game_id": None,
            "game_pk": c.get("game_pk"),
            "player_id": player,
            "player": player,
            "price": c.get("price"),
            "market_probability": c.get("market_probability"),
            "our_probability": c.get("probability"),
            "books": c.get("books"),
            "observed_utc": _observed_dt(c.get("observed_utc")),
            "has_started": False,
            "calibrated": True,  # G9 is a no-op for props (best_bets_card)
            "first_pitch": c.get("first_pitch_utc"),
            "first_pitch_utc": c.get("first_pitch_utc"),
            "season_games": c.get("season_games"),
            "lineup_posted": lineup_posted,
            "expected_pa_source": c.get("expected_pa_source"),
            "bet_sentence": (
                f"{player} {c.get('market')} {c.get('line')} at "
                f"{daily_card._fmt_price(c.get('price'))}"),
            "market": c.get("market"),
            "side": c.get("side"),
            "line": c.get("line"),
            "game_type": "R",
        })
    return candidates, len(enriched)


def card_v2_for_date(entries: Sequence, opportunity_rows: Sequence, *,
                     date: str, now: Optional[datetime] = None,
                     params: best_bets_card.RuleParams = best_bets_card.V2,
                     frozen: Optional[Mapping] = None,
                     prior: Optional[Mapping] = None,
                     multibook_rows=None, prop_board=None,
                     event_map=None) -> dict:
    """The V2 payload for one date, live-built (never the ledger's frozen
    row -- see `frozen_card_v2` for that). Raises `CardV2Error` if the
    frozen parameter file is missing or unreadable rather than falling back
    to V1's numbers: a caller must decide what to do about that, this
    function must never guess.

    Shape (registration R5, `tests/test_api_card_v2.py`'s own list): `rule`,
    `picks`, `prop_picks`, `fills`, `withdrawn`, `all_bets`, `n_picks`,
    `n_fills`, `n_plus_money_picks`, `stale_board`, plus `take`,
    `entry_class` and `price_class` on every entry (stamped by
    `best_bets_card.select` already) and `lineup_posted` on every prop
    entry. `take` is added here: `select()` itself never sets it, and
    section 7's "no Take when the frozen number no longer clears the price"
    rule only matters once a pick is LOCKED and re-checked on a later run
    (`card_ledger`'s job); a freshly-built candidate that passed every gate
    this run is always shown with "Take" (`take=True`), which is the only
    state this live-build path can produce -- the ledger is what carries a
    locked pick's `take=False` forward across runs.
    """
    now = now or datetime.now(timezone.utc)
    frozen = frozen if frozen is not None else load_frozen_params()

    game_candidates, game_pool = _build_game_candidates(
        entries, opportunity_rows, date=date, now=now, frozen=frozen,
        multibook_rows=multibook_rows)
    prop_candidates, prop_pool = _build_prop_candidates(
        entries, date=date, now=now, prop_board=prop_board,
        event_map=event_map)

    candidates = game_candidates + prop_candidates
    raw_pool_size = game_pool + prop_pool

    result = best_bets_card.select(candidates, now=now, params=params,
                                   prior=prior)

    for entry in result["all_bets"]:
        entry.setdefault("take", entry.get("entry_class") == "pick")
        if entry.get("kind") == "prop":
            entry.setdefault("lineup_posted",
                             entry.get("expected_pa_source") == "batting_slot")

    result.update({
        "date": date,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "games_on_slate": len(entries or ()),
        "raw_pool_size": raw_pool_size,
    })

    # HONESTY CONSTRAINT 1 -- two distinct empty messages, never collapsed.
    # `raw_pool_size == 0` means no priced board existed to evaluate at all
    # (no games, every game started, or no moneyline/prop consensus posted
    # yet); `raw_pool_size > 0` with `n_picks == 0` means a board existed and
    # every candidate on it was refused by a gate. Both states can also
    # carry fills (a stale-but-priced board still produces close calls), so
    # the message is set whenever `n_picks < params.floor`, matching
    # `best_bets_card.short_card_sentence`'s own trigger, but its WORDING
    # differs by which of the two facts actually happened.
    if result["n_picks"] < params.floor:
        if raw_pool_size == 0:
            result["empty_reason"] = (
                "No priced board to evaluate for this date: no game or "
                "player prop reached a priced, unstarted candidate.")
        else:
            result["empty_reason"] = best_bets_card.short_card_sentence(
                result["n_picks"])

    card_v1.attach_knowledge(result, entries, now=now)
    return result


def frozen_card_v2(date: str, *, path: Optional[str] = None) -> Optional[dict]:
    """The V2 card as it was PUBLISHED for `date`, or `None` before it is.

    Mirrors `card.frozen_card`'s promise for V2's own ledger
    (`src.appstate.card_ledger.CARD_STORE_V2`): once published, a reader
    sees the frozen row, not a rebuild that could drift from it as prices
    move. No live rebuild is attempted here -- a caller wanting a live
    preview before publication calls `card_v2_for_date` directly (this is
    exactly the `?rule=v2` preview path T5 adds, since nothing publishes V2
    before T0's registration commit).
    """
    from src.appstate import card_ledger

    row = card_ledger.published_row(date, path=path or card_ledger.CARD_STORE_V2)
    if row is None:
        return None
    payload = dict(row)
    payload["date"] = date
    payload["frozen"] = True
    payload["frozen_at"] = row.get("published_utc")
    return payload
