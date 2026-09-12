"""The direction probe's instrument, tested before its output is believed.

Every surprising result on this project has been the measuring code first and
the world second. The two failures that would matter most here are silent:

  * a home/away inversion, which flips every transaction result end to end
    while still printing a plausible number;
  * counting no-move events as hits, which would let a market that mostly
    sits still report as one that moves correctly.

Both have a test below that fails against the inverted or sloppy version.
"""

from datetime import datetime, timedelta, timezone

from tests._unittest_bridge import approx, raises

from scripts import probe_event_direction as probe


BASE = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)


def _series(points):
    """[(minutes_from_BASE, value)] -> the shape `_net` reads."""
    return [(BASE + timedelta(minutes=m), v) for m, v in points]


# --------------------------------------------------------------------------
# _net
# --------------------------------------------------------------------------

def test_net_measures_from_last_quote_before_the_anchor():
    series = _series([(-30, 0.50), (-5, 0.55), (60, 0.60)])
    got = probe._net(series, BASE, BASE + timedelta(minutes=120))
    # Base is 0.55 (the -5 quote), not 0.50 (the -30 one).
    assert got == approx(0.05)


def test_net_is_net_and_not_peak():
    """A path that spikes up and closes down is a DOWN move.

    Peak travel was the right statistic for "did anything happen" and is the
    wrong one for direction: taking the extreme of a noisy path is a free
    parameter that flatters whatever sign you went looking for.
    """
    series = _series([(0, 0.50), (30, 0.90), (110, 0.40)])
    got = probe._net(series, BASE, BASE + timedelta(minutes=120))
    assert got < 0


def test_net_is_none_without_a_quote_on_each_side():
    only_after = _series([(10, 0.5), (20, 0.6)])
    assert probe._net(only_after, BASE, BASE + timedelta(minutes=120)) is None
    only_before = _series([(-20, 0.5), (-10, 0.6)])
    assert probe._net(only_before, BASE, BASE + timedelta(minutes=120)) is None


def test_net_ignores_quotes_past_the_window():
    series = _series([(0, 0.50), (60, 0.55), (300, 0.99)])
    got = probe._net(series, BASE, BASE + timedelta(minutes=120))
    assert got == approx(0.05)


def test_before_window_reads_the_prior_two_hours():
    series = _series([(-180, 0.40), (-60, 0.50), (30, 0.80)])
    span = timedelta(minutes=probe.HORIZON_MINUTES)
    got = probe._net(series, BASE - span, BASE)
    assert got == approx(0.10)


# --------------------------------------------------------------------------
# Signs
# --------------------------------------------------------------------------

def _transaction(category, team, game_pk="1"):
    return {"kind": "transaction_relevant", "game_pk": game_pk, "at": BASE,
            "payload": {"category": category, "team": team}}


def test_il_placement_is_negative_for_the_home_team():
    sign_of = probe._transaction_sign("il_placement", -1, {"1": ("ATL", "SD")})
    assert sign_of(_transaction("il_placement", "ATL")) == -1


def test_il_placement_is_POSITIVE_for_the_away_team():
    """The board tracks the HOME probability.

    An away team losing a player makes the home team more likely to win, so
    the predicted move in the tracked number is UP. Get this backwards and
    every transaction result inverts while still looking reasonable.
    """
    sign_of = probe._transaction_sign("il_placement", -1, {"1": ("ATL", "SD")})
    assert sign_of(_transaction("il_placement", "SD")) == +1


def test_il_activation_mirrors_placement():
    sides = {"1": ("ATL", "SD")}
    activation = probe._transaction_sign("il_activation", +1, sides)
    assert activation(_transaction("il_activation", "ATL")) == +1
    assert activation(_transaction("il_activation", "SD")) == -1


def test_a_transaction_for_neither_side_is_dropped_not_guessed():
    sign_of = probe._transaction_sign("il_placement", -1, {"1": ("ATL", "SD")})
    assert sign_of(_transaction("il_placement", "NYY")) is None


def test_a_transaction_of_another_category_is_not_claimed():
    sign_of = probe._transaction_sign("il_placement", -1, {"1": ("ATL", "SD")})
    assert sign_of(_transaction("recalled", "ATL")) is None


def _weather(field, frm, to):
    return {"kind": "weather_forecast_updated", "game_pk": "1", "at": BASE,
            "payload": {field: {"from": frm, "to": to}}}


def test_temperature_rise_predicts_a_higher_total():
    assert probe._temperature_sign(_weather("temp_f", 70.0, 81.0)) == +1


def test_temperature_fall_predicts_a_lower_total():
    assert probe._temperature_sign(_weather("temp_f", 81.0, 70.0)) == -1


def test_a_first_observation_is_not_a_change():
    """`from: null` means this is the first forecast we saw, not a revision.

    145 of the stored weather rows are exactly this. Treating them as changes
    would inflate the sample with events that carry no direction at all.
    """
    assert probe._temperature_sign(_weather("temp_f", None, 81.0)) is None


def test_an_unchanged_temperature_carries_no_direction():
    assert probe._temperature_sign(_weather("temp_f", 75.0, 75.0)) is None


def test_rain_rising_predicts_a_lower_total():
    assert probe._precip_sign(_weather("precip_probability_pct", 10, 55)) == -1


# --------------------------------------------------------------------------
# The statistic
# --------------------------------------------------------------------------

def _obs(move, expected=+1, game_pk="1"):
    return {"game_pk": game_pk, "after": move, "before": None,
            "expected": expected}


def test_hits_count_only_moves_in_the_predicted_direction():
    rows = [_obs(+0.02), _obs(+0.01), _obs(-0.03)]
    hits, movers, ties = probe._hit_rate(rows)
    assert (hits, movers, ties) == (2, 3, 0)


def test_a_negative_prediction_is_hit_by_a_negative_move():
    rows = [_obs(-0.02, expected=-1), _obs(+0.02, expected=-1)]
    hits, movers, _ties = probe._hit_rate(rows)
    assert (hits, movers) == (1, 2)


def test_no_move_leaves_the_denominator_and_is_counted():
    """Zero is not evidence either way.

    Counting a tie as a miss would understate a real effect; counting it as a
    hit would let a board that never moves look like one that moves
    correctly. It leaves the fraction and gets reported on its own line.
    """
    rows = [_obs(+0.02), _obs(0.0), _obs(0.0), _obs(-0.01)]
    hits, movers, ties = probe._hit_rate(rows)
    assert (hits, movers, ties) == (1, 2, 2)


def test_missing_windows_are_skipped_entirely():
    rows = [_obs(+0.02), _obs(None)]
    hits, movers, ties = probe._hit_rate(rows)
    assert (hits, movers, ties) == (1, 1, 0)


# --------------------------------------------------------------------------
# Clustering and the gate
# --------------------------------------------------------------------------

def test_the_bootstrap_resamples_games_not_events():
    """Twenty events on ONE game are one observation, not twenty.

    They read the same board minutes apart. Resampling events would return a
    tight interval off a single game's luck; resampling games must return a
    degenerate one, because there is only one game to draw.
    """
    rows = [_obs(+0.02, game_pk="same") for _ in range(20)]
    interval = probe._clustered_interval(rows)
    assert interval is None  # fewer than two clusters: nothing to resample


def test_clustering_by_game_keeps_the_interval_honest():
    """Four games, 25 events each; two games all right, two all wrong.

    The true uncertainty here is enormous -- the answer rests on four boards,
    not a hundred draws -- and a game-clustered interval has to say so.
    Resampling EVENTS instead would report a standard error built from 100
    independent observations that do not exist, and return roughly
    [0.37, 0.63]: a tight, confident, wrong interval.

    This is the assertion an earlier version of this test could not make. It
    passed against a bootstrap that resampled events, which made it
    decoration.
    """
    rows = []
    for game in range(4):
        hit = game < 2
        for _ in range(25):
            rows.append(_obs(+0.02 if hit else -0.02, game_pk=f"g{game}"))
    interval = probe._clustered_interval(rows)
    assert interval is not None
    assert interval[1] - interval[0] > 0.6, (
        f"interval {interval} is too tight to have come from four clusters")


def test_a_wide_spread_across_games_gives_a_wide_interval():
    rows = ([_obs(+0.02, game_pk=str(i)) for i in range(5)]
            + [_obs(-0.02, game_pk=str(i)) for i in range(5, 10)])
    interval = probe._clustered_interval(rows)
    assert interval is not None
    assert interval[0] < 0.5 < interval[1]


def test_a_perfect_rate_on_too_few_events_is_undetermined():
    """1.000 on four events is not a finding however much it looks like one."""
    assert probe._verdict(4, [0.9, 1.0]) == "UNDETERMINED"


def test_confirmation_needs_the_interval_clear_of_chance():
    assert probe._verdict(100, [0.55, 0.70]) == "CONFIRMED"
    assert probe._verdict(100, [0.49, 0.70]) == "UNDETERMINED"


def test_the_market_moving_the_other_way_is_refuted_not_ignored():
    assert probe._verdict(100, [0.20, 0.45]) == "REFUTED"


def test_bonferroni_is_applied_to_the_three_primary_tests():
    assert probe.PRIMARY_HYPOTHESES == 3
    assert probe.ALPHA == approx(0.05 / 3)


# --------------------------------------------------------------------------
# Consensus construction
# --------------------------------------------------------------------------

def test_a_consensus_needs_the_book_floor():
    """One shop's number is not a market."""
    rows = []
    for minute in range(4):
        for book in range(probe.MIN_BOOKS - 1):
            rows.append({"observed_utc": (BASE + timedelta(minutes=minute)
                                          ).isoformat(),
                         "event_id": "e1", "book": f"b{book}", "total": "8.5"})
    series = probe._series_by_event_id(rows, lambda r: probe._number(
        r.get("total")))
    assert series == {}


def test_a_consensus_is_the_mean_across_books():
    rows = []
    for minute in range(4):
        for book, total in enumerate(("8.0", "8.5", "9.0")):
            rows.append({"observed_utc": (BASE + timedelta(minutes=minute)
                                          ).isoformat(),
                         "event_id": "e1", "book": f"b{book}", "total": total})
    series = probe._series_by_event_id(rows, lambda r: probe._number(
        r.get("total")))
    assert series["e1"][0][1] == approx(8.5)


def test_totals_arrive_as_strings_and_are_coerced():
    """The stores round-trip through JSON and CSV. Coerce, never isinstance."""
    assert probe._number("8.5") == approx(8.5)
    assert probe._number(8.5) == approx(8.5)
    assert probe._number("") is None
    assert probe._number(None) is None


# --------------------------------------------------------------------------
# Resolving a game to its two sides
# --------------------------------------------------------------------------

def test_full_names_translate_back_to_the_codes_the_ledger_uses():
    """The event map speaks the odds feed's full names; the ledger speaks
    abbreviations. Inverted from src/data/labels.py so the two cannot
    drift."""
    codes = probe._code_by_full_name()
    assert codes["Atlanta Braves"] == "ATL"
    assert codes["Boston Red Sox"] == "BOS"


def test_every_club_in_the_label_table_inverts_uniquely():
    """A duplicate full name would silently collapse two clubs into one and
    put half their events on the wrong side of the board."""
    from src.data import labels
    fulls = [(entry or {}).get("full") for entry in labels.TEAM_NAMES.values()]
    fulls = [f for f in fulls if f]
    assert len(fulls) == len(set(fulls)), "two clubs share a full name"
    assert len(probe._code_by_full_name()) == len(fulls)


def test_an_unknown_club_name_is_skipped_never_guessed(tmp_path, monkeypatch):
    """A club the label table does not know must drop out of the mapping.

    Inventing a code would put the event on a side of the board chosen by
    accident -- the one error that inverts a direction result while still
    printing a plausible number.
    """
    game_map = tmp_path / "event_game_map.jsonl"
    game_map.write_text(
        '{"game_pk": "1", "home_team": "Atlanta Braves", '
        '"away_team": "San Diego Padres", "commence_time": '
        '"2026-09-11T23:05:00Z"}\n'
        '{"game_pk": "2", "home_team": "Faketown Sluggers", '
        '"away_team": "San Diego Padres", "commence_time": '
        '"2026-09-11T23:05:00Z"}\n',
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    game_map.rename(tmp_path / "data" / "processed" / "event_game_map.jsonl")

    sides = probe._game_sides(path=str(tmp_path / "nonexistent.csv"))
    assert sides["1"] == ("ATL", "SD")
    assert "2" not in sides, "an unknown club was given a code anyway"


def test_the_settled_results_store_wins_over_the_schedule(tmp_path,
                                                          monkeypatch):
    """A schedule time is a plan; a results row is what happened."""
    monkeypatch.chdir(tmp_path)
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "event_game_map.jsonl").write_text(
        '{"game_pk": "1", "home_team": "Atlanta Braves", '
        '"away_team": "San Diego Padres", '
        '"commence_time": "2026-09-11T23:05:00Z"}\n', encoding="utf-8")
    results = tmp_path / "results.csv"
    results.write_text(
        "game_pk,start_time_utc,home_team,away_team\n"
        "1,2026-09-12T01:40:00Z,ATL,SD\n", encoding="utf-8")

    assert probe._first_pitch(path=str(results))["1"].hour == 1


# CI runs `python -m unittest discover` on a stdlib-only interpreter; the
# bridge turns the functions above into a TestCase there and returns None
# under pytest so nothing is collected twice.
from tests._unittest_bridge import as_test_case  # noqa: E402

FunctionTests = as_test_case(globals())
