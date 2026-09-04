"""Rendering a selection back into English: "Atlanta Braves -1.5 run line".

WHY THIS EXISTS
----------------
`src.board.ids.selection_id` deliberately hashes identity down to sixteen
hex characters, and that hash is the right key for a ledger: stable across
books, years and languages, impossible to typo into a different bet. It is
the WRONG thing to show a person. A published pick that reads
`9e8d61f45a38abf0` is not a pick anybody can check, argue with, or place;
it is an internal join key that leaked into the product (owner directive,
2026-09-04: "it needs to be 'I'm picking this bet (e.g. over 4.5 runs ATL
Braves) because xyz'").

So this module ADDS a rendering path; it removes nothing. The hash stays
the identity everywhere it already is -- `DecisionRecord.selection_id`, the
paper wager's `bet_id` derivation, the dedupe key -- and every reader-facing
surface (the `engine slate` CLI, docs/eod/*.md) renders through here on the
way out. Identity and legibility are two different jobs and this project
already learned, once, what happens when one field is asked to do both.

NONE OVER GUESS, HERE TOO
--------------------------
Team names are not carried on `PriceObservation` (they are facts about the
EVENT, not about a quote), so they arrive here from
`src.board.gamekey.events_for_date`. When the caller has no name for a
side, this module says "the home side" / "the away side" -- the honest,
unambiguous English for exactly what is known -- and NEVER invents a club,
never falls back to printing the hash, and never silently drops the side.
Same rule for the book: an unrecognized book key is printed verbatim (it is
a real fact) rather than title-cased into a brand name nobody registered.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.board.ids import MARKET_CATALOGUE
from src.board.ids import selection_id as _selection_id

# Display names for the books this project has actually observed quoting
# (data/processed/odds_multibook.jsonl). A key absent from this map is
# printed VERBATIM -- the provider's own key is a fact, and guessing a
# brand's capitalisation is the kind of small invention that makes a reader
# stop trusting the large ones.
BOOK_DISPLAY_NAMES: dict[str, str] = {
    "betmgm": "BetMGM",
    "betonlineag": "BetOnline.ag",
    "betrivers": "BetRivers",
    "betus": "BetUS",
    "bovada": "Bovada",
    "draftkings": "DraftKings",
    "fanatics": "Fanatics",
    "fanduel": "FanDuel",
    "lowvig": "LowVig.ag",
    "mybookieag": "MyBookie.ag",
    "williamhill_us": "Caesars (William Hill US)",
}

# What a side is called when no team name is available. Deliberately a
# phrase a person can read out loud, not a placeholder token: a reader who
# sees "the home side" knows exactly what is and is not known.
UNNAMED_SIDE = {"home": "the home side", "away": "the away side"}

# Scope suffixes, so a first-five bet can never be mistaken for a full-game
# one in prose the way two hashes differing in the 4th character can.
SCOPE_SUFFIX = {
    "game": "",
    "first_five": " (first 5 innings)",
    "first_inning": " (1st inning)",
    "player": "",
}


@dataclass(frozen=True, slots=True)
class GameTeams:
    """The two clubs of one event, either of which may be unknown.

    A dataclass rather than a bare tuple so `home`/`away` cannot be swapped
    by a caller counting positions -- a swapped pair renders a plausible,
    completely wrong pick, which is the worst failure this module could
    have.
    """

    home: str | None = None
    away: str | None = None

    @staticmethod
    def from_event_meta(meta: dict | None) -> "GameTeams":
        """Build from one `src.board.gamekey.events_for_date` value."""
        if not meta:
            return GameTeams()
        return GameTeams(home=meta.get("home_team"),
                         away=meta.get("away_team"))

    def name_for(self, side: str | None) -> str | None:
        if side == "home":
            return self.home
        if side == "away":
            return self.away
        return None


def book_display(book: str | None) -> str | None:
    """`BOOK_DISPLAY_NAMES[book]`, else the key verbatim, else None."""
    if not book:
        return None
    return BOOK_DISPLAY_NAMES.get(book, book)


def side_for_selection(market_key: str, selection_id: str,
                        line: str | None) -> str | None:
    """The side a `selection_id` names, recovered by re-deriving the hash
    for each of the market's declared sides -- or None when none matches.

    The hash is one-way, so this is the only honest recovery: rebuild each
    candidate identity from the catalogue's own side vocabulary and see
    which one is this selection. None (never a guess) when the market is
    unknown or nothing matches, which would mean the catalogue and
    `src.board.ids.selection_id` disagree with each other.
    """
    spec = MARKET_CATALOGUE.get(market_key)
    if spec is None:
        return None
    for side in spec.sides:
        if _selection_id(sport="mlb", market_key=market_key, side=side,
                         line=line) == selection_id:
            return side
    return None


def _signed_line(line: str | None) -> str | None:
    """A spread rendered the way a board prints it: "+1.5", "-1.5"."""
    if line is None:
        return None
    return line if line.startswith("-") else f"+{line}"


def selection_phrase(market_key: str, side: str | None, line: str | None,
                      teams: GameTeams | None = None) -> str:
    """The bet itself in English -- no price, no book, no verdict.

    Examples: "Atlanta Braves (away) moneyline", "Atlanta Braves (home)
    -1.5 run line", "Over 8.5 total runs", "the home side moneyline
    (first 5 innings)".

    The side tag "(away)"/"(home)" is carried alongside the club name on
    purpose: a system's own thesis is minted price-blind and therefore
    names the side, not the club (`src.engine.explain`), so the tag is what
    lets a reader join the two sentences without opening any code.
    """
    teams = teams or GameTeams()
    spec = MARKET_CATALOGUE.get(market_key)
    suffix = SCOPE_SUFFIX.get(spec.scope, "") if spec is not None else ""

    if side is None:
        # Never a hash, never a guess: name the market and say plainly that
        # the side could not be recovered.
        line_part = f" {line}" if line is not None else ""
        return f"{market_key}{line_part} (side not recoverable){suffix}"

    if side in ("over", "under"):
        word = side.capitalize()
        if line is None:
            return f"{word} the total runs{suffix}"
        return f"{word} {line} total runs{suffix}"

    name = teams.name_for(side) or UNNAMED_SIDE.get(side, side)
    tagged = f"{name} ({side})" if teams.name_for(side) else name

    if spec is not None and spec.has_line and line is not None:
        return f"{tagged} {_signed_line(line)} run line{suffix}"
    return f"{tagged} moneyline{suffix}"


def price_phrase(price_american: int | None, book: str | None) -> str:
    """" (-118, DraftKings)", " (-118)", or "" -- never an invented price."""
    name = book_display(book)
    if price_american is None:
        return f" (at {name})" if name else ""
    price = f"+{price_american}" if price_american > 0 else str(price_american)
    return f" ({price}, {name})" if name else f" ({price})"


def render_selection(*, market_key: str, side: str | None,
                      line: str | None = None,
                      teams: GameTeams | None = None,
                      price_american: int | None = None,
                      book: str | None = None) -> str:
    """The full reader-facing pick: "Atlanta Braves (home) -1.5 run line
    (-118, DraftKings)"."""
    return (selection_phrase(market_key, side, line, teams)
            + price_phrase(price_american, book))


def render_record(record, teams: GameTeams | None = None) -> str:
    """`render_selection` for a `src.ledger.records.DecisionRecord`,
    recovering the side from the record's own `selection_id` hash."""
    side = side_for_selection(record.market_key, record.selection_id,
                              record.line)
    return render_selection(market_key=record.market_key, side=side,
                            line=record.line, teams=teams,
                            price_american=record.price_american,
                            book=record.book)
