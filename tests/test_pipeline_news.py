"""Tests for src/pipeline/news.py.

TestPointInTime is the one that matters. A move that reaches a game card dated
after that game is not a cosmetic bug: it is the card claiming to have known
something that had not happened yet, on the one surface a customer reads before
betting. `api/games.py` now calls `attach()` for all fifteen games on a slate,
so a single off-by-one in the cutoff is a slate-wide leak, not a one-card one.

The window tests exist mostly to protect that cutoff from being widened to fix
something else. `for_team` holds the line with one expression --
`earliest <= when < target` -- and both halves of it are load-bearing for a
different reason: the left half decides how much history counts as news, the
right half decides whether the future can reach the page. They are tested
separately and by day, because a test that only counts rows cannot tell which
half moved.

Nothing here touches the network. The store is a temp file in every test, and
`mlb_news.fetch` is swapped for a canned feed in the only function that fetches
at all. `read()`, `for_team()`, `attach()` and `sentence()` are pure functions
over rows and need no fake.

WHAT THE FIRST VERSION OF THIS FILE GOT WRONG
---------------------------------------------
It was green with four separate defects present, and the reason is worth
keeping written down because it is not a coverage problem. Three of the four
were fixtures too uniform to tell the bug from the fix:

- `_row` defaulted `player_id` to `transaction_id`, so `ingest` deduping on
  either field behaved identically and all seven ingest tests passed with the
  wrong one. See PLAYER_ID_BASE.
- The category test put all seven notable categories on ONE date, where
  MAX_PER_TEAM=4 caps the answer at four, and then asserted a subset relation
  that the empty set satisfies. It measured nothing.
- The dedup-key tests moved two variables at once, so no single component of
  `(player_id, category, date)` was pinned by a case that isolated it. All
  three deletions survived.

The fourth was a fixture in the wrong place: the undated-row test used a game
date three months in the past, which is the one band where a `_date` fallback
of "today" is harmless. api/games.py asks for today or tomorrow.

The habit that follows: vary one thing, name the field the assertion is about,
and put the fixture where the caller actually stands.
"""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import news
from src.providers import mlb_news

# Every date in this module is expressed relative to one game date, so the
# boundary tests read as "ten days before first pitch" rather than as two ISO
# strings a reader has to subtract in their head.
GAME_DATE = "2026-06-15"


def _day(offset, base=GAME_DATE):
    """ISO date `offset` days from the game date. Negative is before it."""
    return (dt.date.fromisoformat(base) + dt.timedelta(days=offset)).isoformat()


# Transaction ids and player ids come out of two unrelated MLB id spaces, and
# the first version of this fixture defaulted one to the other. That single
# convenience made every one of the seven TestIngest cases pass with `ingest`
# deduping on the WRONG field -- a mutation that in production would have
# discarded 192 of the 586 stored rows, every repeat move by the 134 players
# who have more than one. Defaulting into a range no transaction id in this
# module reaches keeps the two independently varied by construction, so a test
# can no longer be blind to which field is read.
PLAYER_ID_BASE = 900_000


def _player_id_for(transaction_id):
    """A player id that is never equal to the transaction id beside it."""
    if isinstance(transaction_id, int) and not isinstance(transaction_id, bool):
        return PLAYER_ID_BASE + transaction_id
    return f"P{PLAYER_ID_BASE}-{transaction_id}"


def _row(transaction_id, team, date, category=mlb_news.IL_PLACEMENT,
         player_id=None, player=None, description=None, filed_date=None):
    """One stored transaction, shaped exactly as `mlb_news.parse()` writes them.

    Built from the real writer's key set rather than a convenient subset,
    because `attach()` copies whole rows onto the card and a test fixture that
    is thinner than production data cannot catch a consumer reading a field the
    fixture never had.

    `player_id` defaults independently of `transaction_id` -- see
    PLAYER_ID_BASE. Any test that cares which of the two a caller reads must
    still set the ids it means, but no test can now pass by accident because
    they happened to be equal.
    """
    return {
        "transaction_id": transaction_id,
        "date": date,
        "filed_date": filed_date if filed_date is not None else date,
        "category": category,
        "type_desc": "Status Change",
        "player_id": (player_id if player_id is not None
                      else _player_id_for(transaction_id)),
        "player": player or f"Player {transaction_id}",
        "to_team": team,
        "from_team": None,
        "team": team,
        "description": description if description is not None else (
            f"{team} placed Player {transaction_id} on the 10-day injured list."),
        "injury_note": None,
    }


def _game(away="CIN", home="PIT"):
    """A briefing-shaped game record: raw MLB keys, the way api/games.py holds them."""
    return {"game_pk": 800001, "away_team": away, "home_team": home}


class _Dossier:
    """A dossier-shaped game. The detectors pass these; the briefing passes dicts."""

    def __init__(self, away="CIN", home="PIT"):
        self.teams = (away, home)


class FakeFeed:
    """Stands in for `mlb_news.fetch`. Records every range asked for."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def __call__(self, start_date, end_date=None, timeout=None):
        self.calls.append((start_date, end_date))
        return [dict(row) for row in self.rows]


class StoreCase(unittest.TestCase):
    """Base for anything that touches disk. One temp store per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "transactions.jsonl"

    def write_store(self, *lines):
        self.store.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def use_feed(self, *rows):
        """Swap the provider's fetch for a canned one, restored after the test."""
        feed = FakeFeed(rows)
        original = mlb_news.fetch
        mlb_news.fetch = feed
        self.addCleanup(setattr, mlb_news, "fetch", original)
        return feed


class TestRead(StoreCase):

    def test_a_missing_store_is_empty_not_an_error(self):
        # A store that has never been ingested is a normal state -- a fresh
        # checkout, a new season -- and the page says "no news" rather than 500.
        self.assertEqual(news.read(self.store), [])

    def test_a_missing_store_is_empty_for_stored_ids_too(self):
        # `ingest` reads the id set before it writes anything, so the very first
        # ingest of a season runs through this path.
        self.assertEqual(news.stored_ids(self.store), set())

    def test_an_empty_file_is_empty(self):
        self.store.write_text("", encoding="utf-8")
        self.assertEqual(news.read(self.store), [])

    def test_blank_lines_are_skipped_rather_than_parsed(self):
        self.write_store(json.dumps(_row(1, "CIN", _day(-2))), "", "   ")
        self.assertEqual(len(news.read(self.store)), 1)

    def test_one_corrupt_line_costs_one_transaction_not_the_file(self):
        # This is the entire reason the store is JSON Lines. A half-written line
        # from an interrupted ingest must not blank the news section for a slate.
        self.write_store(json.dumps(_row(1, "CIN", _day(-3))),
                         '{"transaction_id": 2, "date": ',
                         json.dumps(_row(3, "CIN", _day(-1))))
        ids = [row["transaction_id"] for row in news.read(self.store)]
        self.assertEqual(ids, [1, 3])

    def test_rows_come_back_oldest_first_regardless_of_write_order(self):
        self.write_store(json.dumps(_row(3, "CIN", _day(-1))),
                         json.dumps(_row(1, "CIN", _day(-9))),
                         json.dumps(_row(2, "CIN", _day(-5))))
        self.assertEqual([row["transaction_id"] for row in news.read(self.store)],
                         [1, 2, 3])

    def test_stored_ids_is_the_transaction_id_set_not_some_other_id(self):
        # Named after the field on purpose. `ingest` seeds its dedup set from
        # this function, so a stored_ids that returned player ids would make
        # every re-ingest write duplicates. The fixture's player ids are
        # 900011/900012, so reading the wrong field cannot look right.
        self.write_store(json.dumps(_row(11, "CIN", _day(-2))),
                         json.dumps(_row(12, "PIT", _day(-2))))
        self.assertEqual(news.stored_ids(self.store), {11, 12})

    def test_ids_that_tie_on_date_order_numerically_not_lexicographically(self):
        # The tie-break only runs when two rows share a date, which in a
        # 586-row store is most of them. Coercing ids to str to make mixed
        # types comparable -- the obvious one-line fix for the case below --
        # would put 10 before 2 and silently reshuffle every same-date group.
        self.write_store(json.dumps(_row(10, "CIN", _day(-2))),
                         json.dumps(_row(2, "CIN", _day(-2))))
        self.assertEqual([row["transaction_id"] for row in news.read(self.store)],
                         [2, 10])

    def test_a_str_id_beside_an_int_id_on_one_date_reads_instead_of_raising(self):
        # Latent, and latent is the dangerous kind here. All 586 stored ids are
        # ints today, so the sort never reaches two types -- but this store is
        # append-only JSON Lines, `api/games.py` wraps the read in a bare
        # except, and one str id would therefore blank the news section for the
        # WHOLE slate while the page said "roster news not fetched". A stated
        # gap would be survivable; a silent one is not.
        self.write_store(json.dumps(_row("T-9", "CIN", _day(-2))),
                         json.dumps(_row(7, "CIN", _day(-2))))
        self.assertEqual([row["transaction_id"] for row in news.read(self.store)],
                         [7, "T-9"])

    def test_a_row_with_no_transaction_id_does_not_break_the_ordering(self):
        # `mlb_news.parse()` copies MLB's id through without requiring it, so a
        # feed row that omits one is stored with None.
        self.write_store(json.dumps(_row(2, "CIN", _day(-2))),
                         json.dumps(_row(None, "CIN", _day(-2))))
        self.assertEqual([row["transaction_id"] for row in news.read(self.store)],
                         [None, 2])

    def test_a_non_string_date_does_not_break_the_ordering_either(self):
        # The same defect one element to the left of the id: the primary sort
        # term is the date, and it is compared raw. `20260613` is what a JSON
        # writer produces from an unquoted basic-format date, and it is enough
        # to take the whole read down.
        self.write_store(json.dumps(_row(1, "CIN", 20260613)),
                         json.dumps(_row(2, "CIN", _day(-2))))
        self.assertEqual(len(news.read(self.store)), 2)


class TestIngest(StoreCase):

    def test_a_first_ingest_writes_every_fetched_row(self):
        feed = self.use_feed(_row(1, "CIN", _day(-3)), _row(2, "PIT", _day(-2)))
        report = news.ingest(_day(-3), _day(-1), store=self.store)
        self.assertEqual(report["fetched"], 2)
        self.assertEqual(report["written"], 2)
        self.assertEqual(report["skipped_duplicate"], 0)
        self.assertEqual(feed.calls, [(_day(-3), _day(-1))])

    def test_re_ingesting_the_same_window_writes_nothing_new(self):
        # The daily loop re-runs overlapping ranges on purpose, to pick up moves
        # MLB filed late. Without the id check an append-only store would grow a
        # copy of the same transaction every night it was re-fetched.
        self.use_feed(_row(1, "CIN", _day(-3)), _row(2, "PIT", _day(-2)))
        news.ingest(_day(-3), _day(-1), store=self.store)
        report = news.ingest(_day(-3), _day(-1), store=self.store)
        self.assertEqual(report["fetched"], 2)
        self.assertEqual(report["written"], 0)
        self.assertEqual(report["skipped_duplicate"], 2)
        self.assertEqual(len(news.read(self.store)), 2)

    def test_an_overlapping_window_writes_only_the_genuinely_new_row(self):
        self.use_feed(_row(1, "CIN", _day(-3)), _row(2, "PIT", _day(-2)))
        news.ingest(_day(-3), _day(-2), store=self.store)
        self.use_feed(_row(1, "CIN", _day(-3)), _row(2, "PIT", _day(-2)),
                      _row(3, "CIN", _day(-1)))
        report = news.ingest(_day(-3), _day(-1), store=self.store)
        self.assertEqual(report["written"], 1)
        self.assertEqual(report["skipped_duplicate"], 2)
        self.assertEqual([row["transaction_id"] for row in news.read(self.store)],
                         [1, 2, 3])

    def test_dedup_holds_within_a_single_fetch(self):
        # The feed genuinely repeats a move inside one range. Deduping only
        # against what was already on disk would let the repeat through.
        self.use_feed(_row(1, "CIN", _day(-3)), _row(1, "CIN", _day(-3)))
        report = news.ingest(_day(-3), store=self.store)
        self.assertEqual(report["written"], 1)
        self.assertEqual(len(news.read(self.store)), 1)

    def test_a_second_move_by_a_player_already_fetched_is_still_written(self):
        # WHICH field the dedup key reads, measured directly. Deduping on the
        # player instead of the transaction would keep a player's first move
        # and silently drop every later one -- 192 of the 586 stored production
        # rows, across the 134 players who have more than one. Silently, in the
        # store, with no count anywhere saying rows went missing.
        self.use_feed(_row(1, "CIN", _day(-3), player_id=555),
                      _row(2, "CIN", _day(-1), player_id=555,
                           category=mlb_news.IL_ACTIVATION))
        report = news.ingest(_day(-3), _day(-1), store=self.store)
        self.assertEqual(report["written"], 2)
        self.assertEqual([row["transaction_id"] for row in news.read(self.store)],
                         [1, 2])

    def test_a_move_by_a_player_already_on_disk_is_still_written(self):
        # The same question across two runs, which is how the daily loop meets
        # it: the player is in the store from last night, tonight's move is new.
        self.use_feed(_row(1, "CIN", _day(-3), player_id=555))
        news.ingest(_day(-3), store=self.store)
        self.use_feed(_row(2, "CIN", _day(-1), player_id=555,
                           category=mlb_news.IL_ACTIVATION))
        report = news.ingest(_day(-1), store=self.store)
        self.assertEqual((report["written"], report["skipped_duplicate"]), (1, 0))
        self.assertEqual([row["transaction_id"] for row in news.read(self.store)],
                         [1, 2])

    def test_a_repeated_transaction_id_is_a_duplicate_whatever_else_differs(self):
        # The converse, so the pair pins the key rather than one direction of
        # it. Same transaction id, different player id: still one transaction,
        # because the id is what MLB says is the same move.
        self.use_feed(_row(1, "CIN", _day(-3), player_id=555),
                      _row(1, "CIN", _day(-3), player_id=777))
        report = news.ingest(_day(-3), store=self.store)
        self.assertEqual((report["written"], report["skipped_duplicate"]), (1, 1))

    def test_the_store_directory_is_created_when_it_does_not_exist(self):
        nested = Path(self.tmp.name) / "historical" / "transactions.jsonl"
        self.use_feed(_row(1, "CIN", _day(-3)))
        report = news.ingest(_day(-3), store=nested)
        self.assertTrue(nested.exists())
        self.assertEqual(report["store"], str(nested))

    def test_an_empty_range_is_a_quiet_no_op_not_a_failure(self):
        # The off-season files nothing for weeks. That is not a fault.
        self.use_feed()
        report = news.ingest(_day(-3), _day(-1), store=self.store)
        self.assertEqual((report["fetched"], report["written"]), (0, 0))
        self.assertEqual(news.read(self.store), [])

    def test_end_date_defaults_to_the_provider_not_to_today(self):
        # `ingest` must hand the range through untouched -- an end date invented
        # here would silently widen every daily pull.
        feed = self.use_feed()
        news.ingest(_day(-3), store=self.store)
        self.assertEqual(feed.calls, [(_day(-3), None)])


class TestWindowBoundaries(unittest.TestCase):
    """The left edge of the window: how far back a move still counts as news."""

    def team_rows(self, *dates):
        return [_row(index, "CIN", date) for index, date in enumerate(dates, 1)]

    def test_a_move_exactly_window_days_old_is_still_news(self):
        # earliest == when. Ten days back is the oldest day that counts, and the
        # window is therefore ten distinct days: -10 through -1.
        rows = self.team_rows(_day(-news.WINDOW_DAYS))
        self.assertEqual(len(news.for_team(rows, "CIN", GAME_DATE)), 1)

    def test_a_move_one_day_older_than_the_window_is_gone(self):
        rows = self.team_rows(_day(-news.WINDOW_DAYS - 1))
        self.assertEqual(news.for_team(rows, "CIN", GAME_DATE), [])

    def test_the_day_before_the_game_is_news(self):
        rows = self.team_rows(_day(-1))
        self.assertEqual(len(news.for_team(rows, "CIN", GAME_DATE)), 1)

    def test_the_window_spans_exactly_window_days_calendar_days(self):
        # Counted with an explicit narrow window so MAX_PER_TEAM cannot mask the
        # arithmetic. Three days means -3, -2, -1: not -4, and not the game day.
        rows = self.team_rows(_day(-4), _day(-3), _day(-2), _day(-1), _day(0))
        got = news.for_team(rows, "CIN", GAME_DATE, window_days=3)
        self.assertEqual(sorted(row["date"] for row in got),
                         [_day(-3), _day(-2), _day(-1)])

    def test_a_wider_window_reaches_further_back_and_no_further_forward(self):
        rows = self.team_rows(_day(-40), _day(0), _day(1))
        got = news.for_team(rows, "CIN", GAME_DATE, window_days=60)
        self.assertEqual([row["date"] for row in got], [_day(-40)])

    def test_another_club_s_move_is_not_this_club_s_news(self):
        rows = [_row(1, "PIT", _day(-2))]
        self.assertEqual(news.for_team(rows, "CIN", GAME_DATE), [])

    def test_an_undated_row_is_dropped_rather_than_treated_as_today(self):
        # A row with no usable date is the one row most likely to be wrong. The
        # only safe default is to drop it; treating it as current would make it
        # news on every single date forever.
        rows = [_row(1, "CIN", None), _row(2, "CIN", "not-a-date"),
                _row(3, "CIN", "")]
        self.assertEqual(news.for_team(rows, "CIN", GAME_DATE), [])

    def test_an_undated_row_is_dropped_across_the_band_the_product_runs_in(self):
        # The test above says the right thing and cannot see the failure it
        # names. GAME_DATE is fixed and in the past, so a `_date` that fell back
        # to TODAY on an unparseable value put the row after the cutoff and it
        # was dropped anyway -- for the wrong reason, and green either way.
        #
        # api/games.py attaches news with the slate date, which is today or
        # tomorrow. That band is exactly where a today-shaped fallback leaks: on
        # an as-of of tomorrow, `earliest <= today < tomorrow` holds and the
        # undated row lands on all fifteen cards. So sweep the band, and sweep a
        # century-wide window too, which catches a fallback to any fixed past
        # date the default window would have hidden.
        #
        # The control row makes the sweep non-vacuous: every case must return
        # exactly it, so "nothing came back" cannot be mistaken for "nothing
        # leaked".
        undated = [_row(1, "CIN", None), _row(2, "CIN", "not-a-date"),
                   _row(3, "CIN", ""), _row(4, "CIN", "2026-02-30")]
        today = dt.date.today()
        for offset in (-30, -1, 0, 1, 30):
            as_of = today + dt.timedelta(days=offset)
            control = _row(99, "CIN", (as_of - dt.timedelta(days=1)).isoformat())
            for window in (news.WINDOW_DAYS, 36500):
                with self.subTest(as_of=as_of.isoformat(), window_days=window):
                    got = news.for_team(undated + [control], "CIN",
                                        as_of.isoformat(), window_days=window)
                    self.assertEqual(
                        [row["transaction_id"] for row in got], [99],
                        f"as-of {as_of}: a row with no usable date reached the "
                        f"card, which would make it news on every date forever")

    def test_an_unparseable_as_of_date_yields_nothing_rather_than_everything(self):
        # If the caller's date is junk there is no cutoff to enforce, so the
        # answer is no news -- never the whole store.
        rows = self.team_rows(_day(-2))
        self.assertEqual(news.for_team(rows, "CIN", "whenever"), [])
        self.assertEqual(news.for_team(rows, "CIN", None), [])

    def test_a_non_string_date_on_one_row_does_not_take_the_whole_card_down(self):
        # `read()` has its own version of this; this is the second sort, the one
        # that orders the card inside `for_team`, and it is reached even when
        # the store was never read from disk. `_date` parses 20260613 as
        # 2026-06-13 -- basic-format ISO -- so the row clears the window and
        # arrives at a sort that compared it against a str and raised.
        # `attach()` runs under api/games.py's bare except, so the result is
        # fifteen blank cards and a page saying the news was never fetched.
        #
        # Where a non-ISO date sorts among real ones is not worth pinning; that
        # it does not raise is the whole point, so this asserts the set.
        rows = [_row(1, "CIN", 20260613, player_id=555),
                _row(2, "CIN", _day(-1), player_id=777)]
        got = news.for_team(rows, "CIN", GAME_DATE)
        self.assertEqual({row["transaction_id"] for row in got}, {1, 2})

    def test_a_timestamped_date_is_read_as_its_calendar_day(self):
        rows = [_row(1, "CIN", _day(-2) + "T23:41:00Z")]
        self.assertEqual(len(news.for_team(rows, "CIN", GAME_DATE)), 1)

    def test_a_date_object_works_as_the_as_of_argument(self):
        rows = self.team_rows(_day(-2))
        as_of = dt.date.fromisoformat(GAME_DATE)
        self.assertEqual(len(news.for_team(rows, "CIN", as_of)), 1)

    def test_the_window_is_measured_on_the_effective_date_not_the_filed_date(self):
        # Pins WHICH date governs. MLB backdates retroactive IL placements, so
        # `date` (effective) and `filed_date` (announced) can differ by days.
        # This module ranks on the effective date; if a later lane starts
        # honouring the filed date -- see the concern raised with this file --
        # this test SHOULD fail, and that failure is the signal, not a nuisance.
        row = _row(1, "CIN", _day(-2), filed_date=_day(5))
        self.assertEqual(len(news.for_team([row], "CIN", GAME_DATE)), 1)


class TestSelection(unittest.TestCase):
    """What survives the window: category filter, dedup, ordering, the cap."""

    def test_only_notable_categories_reach_a_card_by_default(self):
        rows = [_row(1, "CIN", _day(-2), category=mlb_news.SIGNED),
                _row(2, "CIN", _day(-2), category=mlb_news.REHAB),
                _row(3, "CIN", _day(-2), category=mlb_news.OTHER)]
        self.assertEqual(news.for_team(rows, "CIN", GAME_DATE), [])

    def test_every_notable_category_survives_the_filter(self):
        # One category per call, because all seven in one call measures nothing.
        # MAX_PER_TEAM is 4 and mlb_news.NOTABLE holds 7, so three are dropped
        # by the cap no matter what the filter does -- and `set(cats) <=
        # set(NOTABLE)` is satisfied by any subset, the empty set included.
        # That form stayed green with `optioned`, `designated` and `traded`
        # removed from the filter: 132 of the 586 stored production rows.
        #
        # Asked one at a time, the cap cannot hide anything and the assertion is
        # an equality, so dropping any single category fails here by name.
        checked = []
        for index, category in enumerate(mlb_news.NOTABLE, 1):
            with self.subTest(category=category):
                row = _row(index, "CIN", _day(-2), category=category)
                got = news.for_team([row], "CIN", GAME_DATE)
                self.assertEqual([r["category"] for r in got], [category])
            checked.append(category)
        self.assertTrue(checked,
                        "mlb_news.NOTABLE is empty -- this test measured nothing")

    def test_categories_none_means_no_category_filter_at_all(self):
        # The stored categories a card ignores today are kept for hypotheses
        # tomorrow, and a caller must be able to ask for them.
        rows = [_row(1, "CIN", _day(-2), category=mlb_news.SIGNED)]
        self.assertEqual(len(news.for_team(rows, "CIN", GAME_DATE,
                                           categories=None)), 1)

    # The dedup key is (player_id, category, date). The three tests below vary
    # exactly ONE of those three at a time and the collapse test above them
    # varies none, so each component is pinned by a case that isolates it.
    #
    # This is the shape the earlier pair lacked. Two tests pinned only the
    # collapse direction, and the "two dates" one moved the date AND the
    # category together -- so dropping either component from the key left both
    # green, and dropping player_id was unguarded entirely. All three deletions
    # survived the suite.

    def test_one_player_one_category_one_date_is_one_piece_of_news(self):
        # The feed files the same move under separate ids. To a reader that is
        # one line, and printing it twice reads as two injuries.
        rows = [_row(1, "CIN", _day(-2), player_id=555),
                _row(2, "CIN", _day(-2), player_id=555)]
        self.assertEqual(len(news.for_team(rows, "CIN", GAME_DATE)), 1)

    def test_two_players_moved_the_same_way_that_day_are_two_pieces_of_news(self):
        # Varies player_id alone. A club placing two players on the IL on one
        # day is an ordinary Monday and it is two facts; collapsing it would
        # print one injury and hide the other, which is the worst direction for
        # this section to fail in.
        rows = [_row(1, "CIN", _day(-2), player_id=555),
                _row(2, "CIN", _day(-2), player_id=777)]
        self.assertEqual(sorted(row["player_id"]
                                for row in news.for_team(rows, "CIN", GAME_DATE)),
                         [555, 777])

    def test_one_player_two_categories_on_one_day_is_two_pieces_of_news(self):
        # Varies category alone. Placed on the 10-day IL and transferred to the
        # 60-day the same day is two moves MLB files separately, and the second
        # is the one that says the player is gone for the season.
        rows = [_row(1, "CIN", _day(-2), player_id=555,
                     category=mlb_news.IL_PLACEMENT),
                _row(2, "CIN", _day(-2), player_id=555,
                     category=mlb_news.IL_TRANSFER)]
        self.assertEqual(sorted(row["category"]
                                for row in news.for_team(rows, "CIN", GAME_DATE)),
                         sorted([mlb_news.IL_PLACEMENT, mlb_news.IL_TRANSFER]))

    def test_one_player_one_category_on_two_dates_is_two_pieces_of_news(self):
        # Varies date alone. A pitcher recalled, optioned back, and recalled
        # again inside a week is the shuttle every bullpen runs; the second
        # recall is the one that says he is available tonight.
        rows = [_row(1, "CIN", _day(-6), player_id=555,
                     category=mlb_news.RECALLED),
                _row(2, "CIN", _day(-2), player_id=555,
                     category=mlb_news.RECALLED)]
        self.assertEqual([row["date"]
                          for row in news.for_team(rows, "CIN", GAME_DATE)],
                         [_day(-2), _day(-6)])

    def test_the_same_player_on_two_dates_is_two_pieces_of_news(self):
        # Placed on the IL, then activated, is a story. Collapsing it would hide
        # the half that says the player is back.
        rows = [_row(1, "CIN", _day(-6), player_id=555),
                _row(2, "CIN", _day(-2), player_id=555,
                     category=mlb_news.IL_ACTIVATION)]
        self.assertEqual(len(news.for_team(rows, "CIN", GAME_DATE)), 2)

    def test_the_newest_move_is_first(self):
        rows = [_row(1, "CIN", _day(-8), player_id=1),
                _row(2, "CIN", _day(-1), player_id=2),
                _row(3, "CIN", _day(-4), player_id=3)]
        self.assertEqual([row["date"] for row in news.for_team(rows, "CIN", GAME_DATE)],
                         [_day(-1), _day(-4), _day(-8)])

    def test_the_cap_keeps_the_newest_moves_not_the_first_ones_scanned(self):
        # A card that lists nine roster moves is a card nobody reads. If the cap
        # kept the oldest, the section would show last week's news and drop the
        # placement that happened yesterday.
        rows = [_row(index, "CIN", _day(-index), player_id=index)
                for index in range(1, 7)]
        got = news.for_team(rows, "CIN", GAME_DATE)
        self.assertEqual(len(got), news.MAX_PER_TEAM)
        self.assertEqual([row["date"] for row in got],
                         [_day(-1), _day(-2), _day(-3), _day(-4)])


class TestPointInTime(unittest.TestCase):
    """The cutoff. Nothing dated on or after the as-of date may reach a card."""

    def rows_every_day(self, team="CIN", first=-15, last=15):
        return [_row(1000 + offset, team, _day(offset), player_id=1000 + offset)
                for offset in range(first, last + 1)]

    def test_a_move_dated_after_the_game_never_appears(self):
        rows = [_row(1, "CIN", _day(1))]
        section = news.attach(_game(), rows, GAME_DATE)
        self.assertEqual(section["teams"]["CIN"], [])

    def test_a_move_dated_the_day_of_the_game_never_appears(self):
        # MLB dates a move by the day it took effect, not the minute it was
        # announced. Treating a same-day move as known before first pitch would
        # be a guess wearing the costume of a fact.
        rows = [_row(1, "CIN", _day(0))]
        section = news.attach(_game(), rows, GAME_DATE)
        self.assertEqual(section["teams"]["CIN"], [])

    def test_a_future_move_cannot_be_dragged_in_by_a_huge_window(self):
        # window_days only moves the left edge. If widening the window could
        # also reach forward, every caller would hold a leak switch.
        rows = [_row(1, "CIN", _day(0)), _row(2, "CIN", _day(30))]
        section = news.attach(_game(), rows, GAME_DATE, window_days=3650)
        self.assertEqual(section["teams"]["CIN"], [])

    def test_a_future_move_cannot_be_dragged_in_by_a_zero_window(self):
        rows = [_row(1, "CIN", _day(0)), _row(2, "CIN", _day(1))]
        self.assertEqual(news.for_team(rows, "CIN", GAME_DATE, window_days=0), [])

    def test_no_as_of_date_in_a_month_ever_surfaces_a_later_move(self):
        # The sweep. Thirty-one as-of dates, a move on every one of them, and
        # the window widened to a year so the only thing holding the line is the
        # cutoff itself. One leaked row anywhere in the sweep fails this.
        rows = self.rows_every_day() + self.rows_every_day(team="PIT")
        for offset in range(-15, 16):
            as_of = _day(offset)
            section = news.attach(_game(), rows, as_of, window_days=365)
            for team, team_rows in section["teams"].items():
                for row in team_rows:
                    self.assertLess(
                        row["date"], as_of,
                        f"{team} card for {as_of} surfaced a move dated "
                        f"{row['date']} -- post-game information on a pregame card")

    def test_the_sweep_is_not_vacuous(self):
        # A leak test that returns nothing on every date would pass for the
        # wrong reason. Prove the same rows DO produce cards when they are old
        # enough, so the sweep above is measuring a filter and not an outage.
        rows = self.rows_every_day()
        section = news.attach(_game(), rows, _day(5), window_days=365)
        self.assertTrue(section["teams"]["CIN"])
        self.assertEqual(section["teams"]["CIN"][0]["date"], _day(4))

    def test_a_slate_of_future_moves_reports_absence_not_an_empty_lie(self):
        rows = [_row(1, "CIN", _day(2)), _row(2, "PIT", _day(3))]
        section = news.attach(_game(), rows, GAME_DATE)
        self.assertIsNotNone(section["reason"])
        self.assertEqual(section["teams"], {"CIN": [], "PIT": []})


class TestAttach(unittest.TestCase):

    def test_both_clubs_get_a_key_even_when_only_one_has_news(self):
        # An absent key and an empty list read differently to a template. Every
        # club that was checked must appear, so "checked, nothing" is visible.
        rows = [_row(1, "CIN", _day(-2))]
        section = news.attach(_game(), rows, GAME_DATE)
        self.assertEqual(set(section["teams"]), {"CIN", "PIT"})
        self.assertEqual(section["teams"]["PIT"], [])
        self.assertIsNone(section["reason"])

    def test_an_empty_section_states_why_rather_than_being_silently_empty(self):
        # `{}` with no reason is indistinguishable from "never fetched", and the
        # difference is the whole product. The reason has to name the window.
        section = news.attach(_game(), [], GAME_DATE)
        self.assertIsNotNone(section["reason"])
        self.assertIn(str(news.WINDOW_DAYS), section["reason"])
        self.assertEqual(section["teams"], {"CIN": [], "PIT": []})

    def test_the_stated_reason_names_the_window_the_caller_actually_asked_for(self):
        # A reason quoting the default while a shorter window was applied is a
        # false statement about what was checked.
        section = news.attach(_game(), [_row(1, "CIN", _day(-5))], GAME_DATE,
                              window_days=3)
        self.assertIn("3 days", section["reason"])

    def test_a_row_that_survives_carries_its_rendered_sentence(self):
        rows = [_row(1, "CIN", _day(-2))]
        card = news.attach(_game(), rows, GAME_DATE)["teams"]["CIN"][0]
        self.assertIn("sentence", card)
        self.assertTrue(card["sentence"])
        self.assertEqual(card["transaction_id"], 1)

    def test_attach_does_not_mutate_the_rows_it_was_handed(self):
        # The same row list is attached to all fifteen games on a slate. Writing
        # a rendered sentence back into it would leak one game's rendering into
        # the next, and worse, would survive into whatever else reads the store.
        rows = [_row(1, "CIN", _day(-2))]
        news.attach(_game(), rows, GAME_DATE)
        self.assertNotIn("sentence", rows[0])

    def test_a_dossier_shaped_game_resolves_the_same_two_clubs(self):
        rows = [_row(1, "CIN", _day(-2))]
        section = news.attach(_Dossier(), rows, GAME_DATE)
        self.assertEqual(set(section["teams"]), {"CIN", "PIT"})
        self.assertEqual(len(section["teams"]["CIN"]), 1)

    def test_a_game_dict_carrying_a_teams_pair_resolves_too(self):
        game = {"game_pk": 1, "teams": ["CIN", "PIT"]}
        section = news.attach(game, [_row(1, "PIT", _day(-2))], GAME_DATE)
        self.assertEqual(len(section["teams"]["PIT"]), 1)

    def test_a_game_with_no_identifiable_clubs_states_absence_not_a_crash(self):
        # api/games.py wraps this call in a bare except, so a raise here would
        # drop the news section for the whole slate without saying so.
        section = news.attach({"game_pk": 1}, [_row(1, "CIN", _day(-2))],
                              GAME_DATE)
        self.assertEqual(section["teams"], {})
        self.assertIsNotNone(section["reason"])

    def test_the_away_club_s_news_does_not_land_on_the_home_club(self):
        rows = [_row(1, "CIN", _day(-2)), _row(2, "PIT", _day(-3))]
        section = news.attach(_game(), rows, GAME_DATE)
        self.assertEqual([row["team"] for row in section["teams"]["CIN"]], ["CIN"])
        self.assertEqual([row["team"] for row in section["teams"]["PIT"]], ["PIT"])


class TestSentence(unittest.TestCase):

    def test_an_empty_row_renders_rather_than_raising(self):
        # Every field on a stored row is optional to a reader of the store, and
        # this function runs inside the slate render path. A KeyError here is a
        # blank news section on fifteen cards.
        self.assertEqual(news.sentence({}), "A player: roster move.")

    def test_a_row_with_no_description_falls_back_to_player_and_category(self):
        row = _row(1, "CIN", _day(-2), player="Ke'Bryan Hayes", description="")
        self.assertEqual(news.sentence(row), "Ke'Bryan Hayes: il placement.")

    def test_a_row_with_no_description_and_no_player_still_renders(self):
        row = _row(1, "CIN", _day(-2), description="")
        row["player"] = None
        self.assertEqual(news.sentence(row), "A player: il placement.")

    def test_a_null_category_renders_the_fallback_rather_than_raising(self):
        # A MISSING key and a key holding None are different questions, and
        # `row.get('category', 'roster move')` only answers the first. Every row
        # here carries the key -- `mlb_news.parse()` always writes it -- so the
        # default never fired and None reached `.replace()`: AttributeError,
        # inside the slate render path. `api/games.py` swallows it, so the
        # customer page reports "roster news not fetched" for all fifteen games
        # while the store holds 586 rows. A stated gap would be honest; this one
        # is a lie the page cannot tell it is telling.
        row = _row(1, "CIN", _day(-2), player="Ke'Bryan Hayes", description="")
        row["category"] = None
        self.assertEqual(news.sentence(row),
                         f"Ke'Bryan Hayes: {news.UNCATEGORISED_MOVE}.")

    def test_an_empty_category_falls_back_the_same_way_a_null_one_does(self):
        # "" is a value too, and it renders "Ke'Bryan Hayes: ." -- which reads
        # as a rendering fault rather than as a move nobody classified.
        row = _row(1, "CIN", _day(-2), player="Ke'Bryan Hayes", description="")
        row["category"] = ""
        self.assertEqual(news.sentence(row),
                         f"Ke'Bryan Hayes: {news.UNCATEGORISED_MOVE}.")

    def test_a_null_category_survives_the_whole_attach_path(self):
        # End to end, because the raise above only matters where it is caught.
        # `categories=None` is how a caller asks for the stored categories the
        # card ignores today, and it is the path that carries an unclassified
        # row all the way to `sentence()`.
        row = _row(1, "CIN", _day(-2), player="Ke'Bryan Hayes", description="")
        row["category"] = None
        got = news.for_team([row], "CIN", GAME_DATE, categories=None)
        self.assertEqual([news.sentence(r) for r in got],
                         [f"Ke'Bryan Hayes: {news.UNCATEGORISED_MOVE}."])

    def test_a_whitespace_only_description_counts_as_no_description(self):
        row = _row(1, "CIN", _day(-2), player="A Hitter", description="   \n ")
        self.assertEqual(news.sentence(row), "A Hitter: il placement.")

    def test_mlbs_own_sentence_is_kept_rather_than_rewritten(self):
        text = "Cincinnati Reds recalled RHP Someone from Louisville."
        self.assertEqual(news.sentence(_row(1, "CIN", _day(-2), description=text)),
                         text)

    def test_the_retroactive_clause_is_dropped_and_the_diagnosis_kept(self):
        # The retroactive date is administrative detail. The diagnosis is the
        # part the reader is actually there for.
        text = ("Cincinnati Reds placed 3B Someone on the 10-day injured list "
                "retroactive to June 11, 2026. Left groin strain.")
        self.assertEqual(
            news.sentence(_row(1, "CIN", _day(-2), description=text)),
            "Cincinnati Reds placed 3B Someone on the 10-day injured list. "
            "Left groin strain.")

    def test_a_retroactive_clause_with_no_following_sentence_just_ends(self):
        text = ("Cincinnati Reds placed 3B Someone on the 10-day injured list "
                "retroactive to June 11, 2026")
        self.assertEqual(
            news.sentence(_row(1, "CIN", _day(-2), description=text)),
            "Cincinnati Reds placed 3B Someone on the 10-day injured list")

    def test_wrapped_whitespace_is_collapsed_to_one_line(self):
        text = "Cincinnati Reds\n  recalled RHP Someone\tfrom Louisville."
        self.assertEqual(news.sentence(_row(1, "CIN", _day(-2), description=text)),
                         "Cincinnati Reds recalled RHP Someone from Louisville.")


if __name__ == "__main__":
    unittest.main()
