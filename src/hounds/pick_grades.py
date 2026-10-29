"""Two ratings on every pick, and the reasoning behind them: how much to trust it, and how its price sits against the hound's own record.

THE RULING (Brey, 2026-10-29): "Each pick publicly graded based on confidence and value -- two ratings on a meter-looking
scale, animated -- with the reasoning behind them." His hound DRAKEO is 16-7 and he wants to understand its picks, not just
count its wins and losses.

WHAT THE METERS ARE NOT
  A member hound is a rule filter. Its bet rows carry no model probability, no edge and no confidence: nobody estimated a win
  chance for the pick, and this module does not invent one. ``src/analysis/grade.py`` records the lesson that ranking by "our
  number against the price" misled (five measurements say our own number does not beat the market), so nothing here is "our
  number against the price" either. Both meters are built from one thing only: THE HOUND'S OWN PAST BETS, the prices it took
  and how they came out. They describe a record. They do not predict a result, and the page says so on every card.

VALUE (Overpriced / Fair / Value), 0 to 100, 50 is fair
  A price implies a win rate (-110 implies 52%). The hound's past bets in the same kind of spot either won more often than
  their prices implied, or less. The gap is the whole signal. For the most specific kind of spot with enough past bets:

      E       = the sum of every past bet's implied win chance (the wins the prices "owed")
      excess  = (W - E) / (n + VALUE_SHRINK_BETS)
      shrunk  = this pick's implied chance + excess
      score   = 50 + 5 points per percentage point of excess, held to 0..100

  The price still includes the book's margin (a bet row has only its own side, so the margin cannot be taken out). A hound
  that wins exactly as often as fair odds say therefore reads a little under 50. That is on purpose: the margin is a real
  cost, and it is the cost this product keeps measuring.

  WHY THE SHRINKAGE IS SO HARD. ``VALUE_SHRINK_BETS`` acts like that many invented bets that landed exactly on their prices.
  The repo's own measurements find the true gap between a hound's results and its prices is within a point or two, while
  one bet swings a small sample by tens of points. The constant is the smallest round number that makes this provable: a 3-0
  start is at most (3 - 3/11) wins ahead of its prices even at the longest price a hound may take (+1000), which moves the
  whole-number score under 10 points from 50 only when 2.73 * 500 / (3 + K) < 9.5, that is K > 140. So a 3-0 start can never read as Value or
  Overpriced, at any price (tests/test_pick_grades.py pins -110, +150, +300 and +1000). The first draft of this ruling asked for
  20 pseudo bets, which leaves a 3-0 start at 81. The two requirements disagree, and the ruling's own test (a 3-0 slice stays
  near fair) is the one that protects the reader, so the constant is 150.

CONFIDENCE (Low / Medium / High), 0 to 100. NOT A WIN CHANCE.
  How much weight the value reading can bear. It is 0.5 * sample + 0.3 * consistency + 0.2 * market:

      sample       n / (n + SAMPLE_PSEUDO_BETS), the share of the reading that is data, scaled to 100
      consistency  how far the record in that kind of spot sits ahead of its prices, in standard errors
                   (z = (W - E) / sqrt(sum p(1-p))), full marks at CONSISTENCY_FULL_Z; behind or level is 0
      market       how many books quoted the price when the bet was placed: BOOKS_FLOOR or fewer is 0, BOOKS_FULL or more
                   is 100, straight between. A price four books agree on is a firmer price than one book's.

  A part the row does not carry (no book count) is left out and the other weights scale up to fill, rather than counted as 0.

THE SPOT, FROM SPECIFIC TO BROAD. The first of these with at least ``MIN_SLICE_BETS`` past bets is used:
  sport + market + price band + favourite or underdog, then sport + market + favourite or underdog, then sport + favourite or
  underdog, then favourite or underdog, then every bet. When none reaches the minimum the broadest is used, and every sentence
  says "thin". Favourite or underdog is the sign of the American price (-110 is a favourite), because a total has no side
  to be the favourite of. A push or a void is not a win or a loss and is left out of every count.

POINT IN TIME (the rule everything else rests on)
  A pick is graded only from bets that were SETTLED (``graded_utc``) strictly BEFORE the pick was placed (``lock_utc``, else
  the stamp the row was written). A bet with no settle time, or one settled before it was placed (a corrupt row), is not
  history for anyone. Grades are worked out on read and written nowhere: the ledgers are append-only and stay so, and a
  grade can never quietly change after the fact because it is a function of rows that were already settled.

THE PRICE. The board AVERAGE the hound is graded at (``price_average``), the same one the public record's units use
  (``src/hounds/user_settle.py``: ``profit_units`` is at ``price``, the average; ``best_price`` is the small print). A row with
  no average price is not graded and is not history: the record itself cannot grade a win on it either.

Pure and deterministic. No clock, no I/O, no model, no network. Paper only. Nothing here places or suggests a bet.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

#: Pseudo bets of "landed exactly on its price" added to every slice before the value gap is read (see the module docstring:
#: the repo's measurements put the real gap within a point or two, and a 3-0 start must stay within 10 points of fair at any price).
VALUE_SHRINK_BETS = 150

#: Score points per percentage point of shrunk excess. Ten points of excess is the whole dial (0 or 100).
VALUE_POINTS_PER_PP = 5.0

#: Fewer past bets than this in a spot and the sentence says "thin"; a more specific spot needs this many to be chosen.
MIN_SLICE_BETS = 8

#: The confidence "sample" part: a slice of this many bets is half data, half prior. Set to VALUE_SHRINK_BETS (owner review
#: 2026-10-29): at 20, a 16-7 run over 23 bets read "High", which claims more than 23 bets can bear; the referee itself waits
#: for 150 measurable bets before it calls anything. High now needs a few hundred bets in that kind of spot.
SAMPLE_PSEUDO_BETS = VALUE_SHRINK_BETS

#: The confidence weights. They sum to 1.
WEIGHT_SAMPLE, WEIGHT_CONSISTENCY, WEIGHT_MARKET = 0.5, 0.3, 0.2

#: Standard errors ahead of the prices that earn the full consistency marks.
CONSISTENCY_FULL_Z = 2.0

#: Books quoting the price: this many or fewer is 0, this many or more is 100.
BOOKS_FLOOR, BOOKS_FULL = 3, 9

#: Value labels by the whole-number score: under 40 Overpriced, 40 to 60 Fair, over 60 Value.
OVERPRICED_BELOW, VALUE_ABOVE = 40, 60

#: Confidence labels by the whole-number score: under 35 Low, 35 to 65 Medium, over 65 High.
LOW_BELOW, HIGH_ABOVE = 35, 65

#: |z| under this reads "about level with the prices" in a sentence (wording only; it never moves a score).
LEVEL_Z = 0.5

LABEL_OVERPRICED, LABEL_FAIR, LABEL_VALUE = "Overpriced", "Fair", "Value"
LABEL_LOW, LABEL_MEDIUM, LABEL_HIGH = "Low", "Medium", "High"
LABEL_NA = "Not yet available"
CLV_BEAT, CLV_MATCHED, CLV_MISSED, CLV_NONE = "Beat the close", "Matched the close", "Missed the close", "Not measured"

REASON_NO_HISTORY = "No settled bets like this before it was placed."
REASON_NO_PRICE = "This bet has no recorded board price to grade."
REASON_NO_TIME = "When this bet was placed is not recorded, so the record before it cannot be fixed in time."

# The price bands the app cuts by, shortest price first. COPIED from src/hounds/interact/training.PRICE_BANDS (key, name,
# range text, lowest American price, highest) rather than imported: that module pulls in the whole coaching package, and this
# one must stay a pure leaf the API and the stats layer can import without a cycle. tests/test_pick_grades.py pins that the two
# tables are identical, so a change there fails here.
PRICE_BANDS = (
    ("short_favourites", "short favourites", "-199 to -151", -199, -151),
    ("favourites", "favourites", "-150 to -111", -150, -111),
    ("near_even", "near even", "-110 to +109", -110, 109),
    ("underdogs", "underdogs", "+110 to +199", 110, 199),
    ("long_shots", "long shots", "+200 and up", 200, 1000),
)
_BAND_NAME = {b[0]: b[1] for b in PRICE_BANDS}
_NEAR_EVEN = "near_even"

# The odds feed's words for the three game markets, and their plural for a sentence; a prop keeps its own key.
_MARKET_OF_KEY = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}
_MARKET_PLURAL = {"moneyline": "moneylines", "spread": "spreads", "total": "totals"}

_WIN, _LOSS = "win", "loss"
_RESULT_WORD = {"win": _WIN, "won": _WIN, "w": _WIN, "loss": _LOSS, "lost": _LOSS, "l": _LOSS}
_SETTLED_WORDS = frozenset({"win", "won", "w", "loss", "lost", "l", "push", "p", "void"})


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------

def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return None if (isinstance(value, float) and not math.isfinite(value)) else float(value)


def _decimal(price) -> Optional[float]:
    """Decimal odds for an American price, or None for anything that is not one (a price has |p| >= 100)."""
    p = _num(price)
    if p is None or abs(p) < 100:
        return None
    return 1.0 + p / 100.0 if p > 0 else 1.0 + 100.0 / -p


def band_of(price) -> Optional[str]:
    """The key of the price band an American price falls in; a price worse than the first band reads as the first, one past the
    last as the last (the same rule as ``training.band_of``). None when there is no usable price."""
    d = _decimal(price)
    if d is None:
        return None
    for key, _name, _range, _lo, hi in PRICE_BANDS:
        if d <= _decimal(hi) + 1e-9:
            return key
    return PRICE_BANDS[-1][0]


def _utc(value) -> Optional[datetime]:
    """A UTC datetime from an ISO stamp (``...Z`` or an offset) or a datetime; None when it does not parse."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _price_text(price) -> str:
    p = int(round(float(price)))
    return f"+{p}" if p > 0 else str(p)


def _market_of(raw) -> Optional[str]:
    key = str(raw or "").strip().lower()
    return _MARKET_OF_KEY.get(key, key) or None


def _market_words(market: str) -> str:
    return _MARKET_PLURAL.get(market, market.replace("_", " "))


# ---------------------------------------------------------------------------
# the rows, prepared once
# ---------------------------------------------------------------------------

class _Row:
    """One ledger bet, reduced to what grading reads. ``outcome`` is 1 (win), 0 (loss) or None (anything else)."""

    __slots__ = ("bet_id", "price", "implied", "band", "role", "sport", "market", "placed", "graded", "outcome",
                 "settled_any", "n_books", "clv_pts", "history_ok")

    def __init__(self, raw: Mapping, fallback_id: str):
        self.bet_id = str(raw.get("bet_id") if raw.get("bet_id") is not None else fallback_id)
        d = _decimal(raw.get("price_average", raw.get("price")))
        self.price = _num(raw.get("price_average", raw.get("price"))) if d is not None else None
        self.implied = 1.0 / d if d is not None else None
        self.band = band_of(self.price) if d is not None else None
        self.role = None if self.price is None else ("favourite" if self.price < 0 else "underdog")
        sport = str(raw.get("sport") or "").strip()
        self.sport = sport.upper() or None
        self.market = _market_of(raw.get("market", raw.get("market_key")))
        self.placed = _utc(raw.get("lock_utc"))
        self.graded = _utc(raw.get("graded_utc"))
        word = str(raw.get("result") or "").strip().lower()
        self.settled_any = word in _SETTLED_WORDS
        kind = _RESULT_WORD.get(word)
        self.outcome = None if kind is None else (1 if kind == _WIN else 0)
        books = _num(raw.get("n_books", raw.get("book_count")))
        self.n_books = None if books is None else int(books)
        self.clv_pts = _num(raw.get("clv_pts"))
        # History needs a price, a win or a loss, a settle time, and (when the placement is known) a settle AFTER it.
        self.history_ok = (self.implied is not None and self.outcome is not None and self.graded is not None
                           and (self.placed is None or self.graded > self.placed))


def _levels(row: _Row) -> list:
    """``[(level, key, name)]`` for the spots this bet belongs to, most specific first. A level whose parts the row lacks
    (no sport, no market) is skipped, so the broader ones still count it; a row with no price is in none."""
    if row.role is None:
        return []
    out = []
    role_words = f"{row.role}s"
    if row.sport and row.market:
        # the band already says favourite or underdog everywhere except near even, so only there is the word added
        band = f"{_BAND_NAME[row.band]}, {row.role}" if row.band == _NEAR_EVEN else _BAND_NAME[row.band]
        out.append((0, (row.sport, row.market, row.band, row.role), f"{row.sport} {_market_words(row.market)}, {band}"))
        out.append((1, (row.sport, row.market, row.role), f"{row.sport} {_market_words(row.market)}, {role_words}"))
    if row.sport:
        out.append((2, (row.sport, row.role), f"{row.sport} {role_words}"))
    out.append((3, (row.role,), role_words))
    out.append((4, (), "bets so far"))
    return out


class _Acc:
    """Running sums for one spot: bets, wins, the wins the prices owed, and the variance of that count."""

    __slots__ = ("n", "w", "e", "v")

    def __init__(self):
        self.n = 0
        self.w = 0
        self.e = 0.0
        self.v = 0.0

    def add(self, row: _Row) -> None:
        self.n += 1
        self.w += row.outcome
        self.e += row.implied
        self.v += row.implied * (1.0 - row.implied)


# ---------------------------------------------------------------------------
# the grade for one pick
# ---------------------------------------------------------------------------

def _unavailable(reason: str, implied: Optional[float] = None) -> dict:
    value = {"score": None, "label": LABEL_NA, "slice": None, "shrunk_rate": None,
             "implied": None if implied is None else round(implied, 4), "reason": reason}
    confidence = {"score": None, "label": LABEL_NA, "parts": None, "reason": reason}
    return {"value": value, "confidence": confidence}


def _value_label(score: int) -> str:
    return LABEL_OVERPRICED if score < OVERPRICED_BELOW else LABEL_VALUE if score > VALUE_ABOVE else LABEL_FAIR


def _confidence_label(score: int) -> str:
    return LABEL_LOW if score < LOW_BELOW else LABEL_HIGH if score > HIGH_ABOVE else LABEL_MEDIUM


def _books_part(n_books: Optional[int]) -> Optional[int]:
    if n_books is None:
        return None
    return _round_half_up(100.0 * _clamp((n_books - BOOKS_FLOOR) / (BOOKS_FULL - BOOKS_FLOOR), 0.0, 1.0))


def _pick_slice(row: _Row, acc: list) -> Optional[tuple]:
    """``(name, level, _Acc)`` for the first spot with enough past bets, else the broadest spot that has any; None when the
    hound has no usable history at all."""
    levels = _levels(row)
    for level, key, name in levels:
        a = acc[level].get(key)
        if a is not None and a.n >= MIN_SLICE_BETS:
            return name, level, a
    level, key, name = levels[-1]            # the last is always "every bet"
    a = acc[level].get(key)
    return (name, level, a) if a is not None and a.n > 0 else None


def _clv_block(row: _Row) -> Optional[dict]:
    if not row.settled_any:
        return None
    pts = row.clv_pts
    if pts is None:
        return {"pts": None, "label": CLV_NONE}
    pts = round(pts, 1)
    return {"pts": pts, "label": CLV_BEAT if pts > 0 else CLV_MISSED if pts < 0 else CLV_MATCHED}


def _grade_one(row: _Row, acc: list) -> dict:
    if row.implied is None:
        out = _unavailable(REASON_NO_PRICE)
    elif row.placed is None:
        out = _unavailable(REASON_NO_TIME, row.implied)
    else:
        picked = _pick_slice(row, acc)
        if picked is None:
            out = _unavailable(REASON_NO_HISTORY, row.implied)
        else:
            out = _graded(row, *picked)
    out["clv"] = _clv_block(row)
    return out


def _graded(row: _Row, name: str, level: int, a: _Acc) -> dict:
    n, w = a.n, a.w
    thin = n < MIN_SLICE_BETS
    gap = w - a.e
    excess = gap / (n + VALUE_SHRINK_BETS)
    shrunk = _clamp(row.implied + excess, 0.0, 1.0)
    score = _round_half_up(_clamp(50.0 + excess * 100.0 * VALUE_POINTS_PER_PP, 0.0, 100.0))
    thin_word = " (thin)" if thin else ""
    value = {
        "score": score, "label": _value_label(score),
        "slice": {"name": name, "n": n, "w": w, "l": n - w, "expected_w": round(a.e, 1)},
        "shrunk_rate": round(shrunk, 4), "implied": round(row.implied, 4),
        "reason": (f"Its {name}: {w}-{n - w}{thin_word}. {_price_text(row.price)} implies "
                   f"{_round_half_up(row.implied * 100)}%; its record shrinks to {_round_half_up(shrunk * 100)}%."),
    }
    sd = math.sqrt(a.v) if a.v > 1e-12 else None
    z = None if sd is None else gap / sd
    sample = _round_half_up(100.0 * n / (n + SAMPLE_PSEUDO_BETS))
    consistency = 0 if z is None else _round_half_up(100.0 * _clamp(max(z, 0.0) / CONSISTENCY_FULL_Z, 0.0, 1.0))
    market = _books_part(row.n_books)
    parts = {"sample": sample, "consistency": consistency, "market": market}
    weights = {"sample": WEIGHT_SAMPLE, "consistency": WEIGHT_CONSISTENCY, "market": WEIGHT_MARKET}
    used = {k: v for k, v in parts.items() if v is not None}
    total = sum(weights[k] for k in used)
    cscore = _round_half_up(sum(weights[k] * used[k] for k in used) / total)
    if z is None or abs(z) < LEVEL_Z:
        ahead = "about level with the prices"
    else:
        ahead = "ahead of the prices" if z > 0 else "behind the prices"
    kind = "earlier bets" if level == 4 else "similar bets"
    books = ("the number of books that quoted it is not recorded" if row.n_books is None
             else f"{row.n_books} book{'s' if row.n_books != 1 else ''} quoted it")
    confidence = {
        "score": cscore, "label": _confidence_label(cscore), "parts": parts,
        "reason": f"Built on {n} {kind}{thin_word}; its record in them is {ahead}; {books}. Not a win chance.",
    }
    return {"value": value, "confidence": confidence}


# ---------------------------------------------------------------------------
# the public entry points
# ---------------------------------------------------------------------------

def grade_bets(rows: Iterable[Mapping]) -> dict:
    """``{bet_id: grades}`` for every bet in ``rows`` (one hound lineage, settled and open together).

    A row is a mapping with ``bet_id``, ``price`` (or ``price_average``: the board average, American), ``sport``, ``market``,
    ``result``, ``lock_utc``, ``graded_utc``, ``n_books`` and ``clv_pts``; anything missing is None, never a guess. ``grades`` is
    ``{value, confidence, clv}``; ``clv`` is None until the bet is settled. One sort of the settled bets and one sweep: each pick
    sees exactly the bets settled strictly before it was placed, so the cost is O(n log n) however many bets there are, and a
    later settlement cannot change an earlier grade. A repeated ``bet_id`` keeps the last row."""
    prepared = {}
    for i, raw in enumerate(rows):
        row = _Row(raw, str(i))
        prepared[row.bet_id] = row
    history = sorted((r for r in prepared.values() if r.history_ok), key=lambda r: (r.graded, r.bet_id))
    picks = sorted(prepared.values(), key=lambda r: (r.placed is None, r.placed or datetime.min.replace(tzinfo=timezone.utc),
                                                      r.bet_id))
    acc = [defaultdict(_Acc) for _ in range(5)]
    seen = 0
    out = {}
    for pick in picks:
        if pick.placed is not None:
            while seen < len(history) and history[seen].graded < pick.placed:
                for level, key, _name in _levels(history[seen]):
                    acc[level][key].add(history[seen])
                seen += 1
        out[pick.bet_id] = _grade_one(pick, acc)
    return out


def row_from_bet(bet, bet_id: str) -> dict:
    """The grading row for a ``contract.BetRow`` (or anything with its attribute names). The placement instant is the bet's
    ``lock_utc``; a row from before that stamp existed falls back to the instant it was written (``recorded_utc``), which is
    never later than the first pitch and so still cannot see a result it could not have known."""
    return {
        "bet_id": bet_id, "price_average": getattr(bet, "price_average", None), "sport": getattr(bet, "sport", None),
        "market": getattr(bet, "market", None), "result": getattr(bet, "result", None),
        "lock_utc": getattr(bet, "lock_utc", None) or getattr(bet, "recorded_utc", None),
        "graded_utc": getattr(bet, "graded_utc", None), "n_books": getattr(bet, "book_count", None),
        "clv_pts": getattr(bet, "clv_pts", None),
    }


def grades_for_page(history: Iterable, page: Iterable) -> list:
    """The ``grades`` block for each bet of ``page``, in order. ``history`` is every bet of the hound's lineage (the whole
    record, not the page, the filter or the season); ``page`` is the ``BetRow`` objects being returned, which are found in
    ``history`` by their identity fields. A page bet that is not in the history is graded as if it were, on its own row.

    Replay bets (rows written after the games) are neither history nor graded: they return None, and a client shows
    "not yet available" for them."""
    def ident(bet):
        return (getattr(bet, "hound_id", None), getattr(bet, "date", None), getattr(bet, "event_id", None),
                getattr(bet, "game", None), getattr(bet, "market", None), getattr(bet, "selection", None),
                getattr(bet, "line", None), getattr(bet, "segment", None), getattr(bet, "recorded_utc", None))

    rows, keys = [], {}
    for bet in history:
        if getattr(bet, "segment", "forward") != "forward":
            continue
        key = ident(bet)
        if key in keys:
            continue
        keys[key] = str(len(rows))
        rows.append(row_from_bet(bet, keys[key]))
    extra = []
    page = list(page)
    for bet in page:
        if getattr(bet, "segment", "forward") != "forward":
            continue
        key = ident(bet)
        if key not in keys:
            keys[key] = str(len(rows) + len(extra))
            extra.append(row_from_bet(bet, keys[key]))
    graded = grade_bets(rows + extra)
    return [None if getattr(bet, "segment", "forward") != "forward" else graded.get(keys.get(ident(bet))) for bet in page]
