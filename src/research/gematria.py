"""Gematria and numerology primitives: the arithmetic behind the Gematria Hound, and nothing else.

WHY THIS MODULE EXISTS
----------------------
A bettor who posts under the name RabbitSZN justifies sports picks with numbers: a team's name "equals" a number in
some cipher, that number is the Nth prime, the game date adds up to the same number, a coach is on his 19th win.
Whether any of that predicts a game is an open question and this module takes no side on it. What it does is make
the ARITHMETIC exact and reproducible so a claim can be checked ("Seattle = 19 FR": is it?) and so the hound built
on top of it (``src/hounds/gematria``) can count honestly how many comparisons it tried.

Pure functions, stdlib only, no clock, no I/O. The reduction conventions below were fixed by checking the
posted claims in ``research/rabbitszn/ledger.csv`` against the arithmetic (``tests/test_gematria_engine.py``); the
ones that did NOT check out are recorded there as such, not bent to fit.

CIPHERS (letters only; case, accents, spaces, digits and punctuation are ignored)
  EO   English Ordinal: A=1 .. Z=26, summed.
  FR   Full Reduction: each letter's ordinal reduced to a single digit (A=1 .. I=9, J=1 .. R=9, S=1 .. Z=8),
       summed. The SUM is not reduced again: "Georgia Southern University = 137 FR" is a three-digit sum.
  RO   Reverse Ordinal: A=26 .. Z=1, summed.
  RFR  Reverse Full Reduction: each letter's reverse ordinal reduced to a single digit, summed.

DATE NUMBERS (``date_numbers``) are named quantities derived from a calendar date; the names are the evidence
vocabulary the hound prints, so they are stable strings.

SPANS (``span``) count a unit between two dates and say whether the end points are included. Inclusive/exclusive
is explicit in the call and in the returned label, never implied, because "47 weeks since statehood" changes
with the convention. The posts mostly count to or from the nearest ANNIVERSARY of a founding date (33 days after
California's September 9, 19 days before the University of Washington's November 4), so the anniversary spans are
first-class units, not a special case.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

SPECIAL_NUMBERS = (33, 47)      # the "Masonic" pair the posts lean on; counted as their own signal kind
CIPHERS = ("EO", "FR", "RO", "RFR")
CIPHER_NAMES = {"EO": "English Ordinal", "FR": "Full Reduction", "RO": "Reverse Ordinal",
                "RFR": "Reverse Full Reduction"}

# A common sports-name spelling that is not letters-only: "&" is the word "and"; apostrophes inside a word
# (Hawai'i, St. John's) are dropped by the letters-only rule. Anything else (St. -> Saint) would be a guess about
# which spelling a poster used, so it is NOT folded here; callers pass the spellings they want as separate texts.
_AMPERSAND = " and "


def normalize(text: object) -> str:
    """Lower-case ASCII letters only: accents folded, ``&`` spoken as "and", everything else dropped."""
    s = unicodedata.normalize("NFKD", str(text or "").replace("&", _AMPERSAND))
    return "".join(c for c in s.lower() if "a" <= c <= "z")


def digital_root(n: int) -> int:
    """1..9 for a positive integer, 0 for 0 (the numerologist's "reduce to a single digit")."""
    n = abs(int(n))
    return 0 if n == 0 else 1 + (n - 1) % 9


def _ordinal(c: str) -> int:
    return ord(c) - 96


def eo(text: object) -> int:
    return sum(_ordinal(c) for c in normalize(text))


def fr(text: object) -> int:
    return sum(digital_root(_ordinal(c)) for c in normalize(text))


def ro(text: object) -> int:
    return sum(27 - _ordinal(c) for c in normalize(text))


def rfr(text: object) -> int:
    return sum(digital_root(27 - _ordinal(c)) for c in normalize(text))


_CIPHER_FUNCS = {"EO": eo, "FR": fr, "RO": ro, "RFR": rfr}


def cipher_value(text: object, cipher: str) -> int:
    try:
        return _CIPHER_FUNCS[cipher](text)
    except KeyError:
        raise ValueError(f"unknown cipher {cipher!r}; known: {', '.join(CIPHERS)}") from None


def values(text: object, ciphers: Iterable[str] = CIPHERS) -> Dict[str, int]:
    """{cipher: value} for one text. A text with no letters has no value in any cipher (empty dict), not four zeros:
    "0" would equal other zeros and manufacture matches out of missing data."""
    if not normalize(text):
        return {}
    return {c: cipher_value(text, c) for c in ciphers}


# ---------------------------------------------------------------------------
# primes
# ---------------------------------------------------------------------------

def is_prime(n: int) -> bool:
    n = int(n)
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def nth_prime(n: int) -> Optional[int]:
    """The Nth prime (1-indexed: 2 is the 1st, 137 the 33rd); None for n < 1 or beyond ``MAX_PRIME_INDEX``."""
    n = int(n)
    if n < 1 or n > MAX_PRIME_INDEX:
        return None
    return _PRIMES[n - 1]


def prime_index(p: int) -> Optional[int]:
    """n such that ``p`` is the nth prime, or None when ``p`` is not prime (or is past the table)."""
    p = int(p)
    return _PRIME_INDEX.get(p)


def _sieve(limit: int) -> List[int]:
    flags = bytearray([1]) * (limit + 1)
    flags[0:2] = b"\x00\x00"
    for i in range(2, int(limit ** 0.5) + 1):
        if flags[i]:
            flags[i * i::i] = bytearray(len(flags[i * i::i]))
    return [i for i, f in enumerate(flags) if f]


# Every value this module is asked about is a name (a few hundred at most) or a date quantity (a few thousand at
# most), so a small table is exact for all of them; the bound is explicit so nothing past it is guessed.
_PRIMES = _sieve(20000)
MAX_PRIME_INDEX = len(_PRIMES)
_PRIME_INDEX = {p: i + 1 for i, p in enumerate(_PRIMES)}


def triangular(k: int) -> int:
    """The kth triangular number: 1, 3, 6, 10 ... ("66 = 11th Tri #")."""
    k = int(k)
    return k * (k + 1) // 2


def triangular_index(n: int) -> Optional[int]:
    """k such that ``n`` is the kth triangular number, or None."""
    n = int(n)
    if n < 1:
        return None
    k = (int((8 * n + 1) ** 0.5) - 1) // 2
    for cand in (k - 1, k, k + 1):
        if cand >= 1 and triangular(cand) == n:
            return cand
    return None


# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------

def as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def day_of_year(d: object) -> int:
    return as_date(d).timetuple().tm_yday


def days_in_year(year: int) -> int:
    return 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 365


def days_remaining(d: object) -> int:
    """Days left in the year AFTER the date (Dec 31 -> 0). The posts do not say whether they count the day itself;
    this is the exclusive count and the hound labels it so."""
    dd = as_date(d)
    return days_in_year(dd.year) - day_of_year(dd)


def digit_sum(n: object) -> int:
    return sum(int(c) for c in str(n) if c.isdigit())


def date_numbers(d: object) -> Dict[str, int]:
    """The named numbers of one calendar date (a game's local calendar date).

    ``md_yy``       month + day + two-digit year            (Oct 15, 2026 -> 10 + 15 + 26 = 51)
    ``md_19yy``     month + day + 19 + two-digit year       (the "19" is the century's leading pair; 70 for the date above)
    ``md_20yy``     month + day + 20 + two-digit year       (the same with the century actually in force)
    ``digits``      sum of every digit of m/d/yyyy          (1+0+1+5+2+0+2+6 = 17)
    ``day``, ``month``, ``yy``  the parts themselves
    ``doy``         day of the year                         (Oct 15, 2026 -> 288)
    ``doy_left``    days remaining in the year, exclusive of the day itself
    ``root``        digital root of ``digits``
    Duplicate values under several names are kept on purpose: the hound counts every comparison it tries.
    """
    dd = as_date(d)
    yy = dd.year % 100
    return {
        "month": dd.month, "day": dd.day, "yy": yy,
        "md_yy": dd.month + dd.day + yy,
        "md_19yy": dd.month + dd.day + 19 + yy,
        "md_20yy": dd.month + dd.day + 20 + yy,
        "digits": digit_sum(f"{dd.month}{dd.day}{dd.year}"),
        "doy": day_of_year(dd),
        "doy_left": days_remaining(dd),
        "root": digital_root(digit_sum(f"{dd.month}{dd.day}{dd.year}")),
    }


# ---------------------------------------------------------------------------
# spans
# ---------------------------------------------------------------------------

def span_days(start: object, end: object, *, inclusive: bool) -> int:
    """Calendar days from ``start`` to ``end``. Exclusive: the plain difference. Inclusive: both end points count (+1)."""
    n = (as_date(end) - as_date(start)).days
    return n + 1 if inclusive else n


def span_weeks(start: object, end: object, *, inclusive: bool) -> int:
    """WHOLE weeks (floor of days / 7) between the dates under the given end-point convention."""
    return span_days(start, end, inclusive=inclusive) // 7


def span_years(start: object, end: object) -> int:
    """Completed years between two dates (the age/anniversary count: a birthday not yet reached does not count)."""
    a, b = as_date(start), as_date(end)
    years = b.year - a.year
    if (b.month, b.day) < (a.month, a.day):
        years -= 1
    return years


def calendar_year_gap(start: object, end: object) -> int:
    """end.year - start.year, ignoring month/day ("founded in 1969, so 57 years" the way a poster counts)."""
    return as_date(end).year - as_date(start).year


def _anniversary(anchor: date, year: int) -> date:
    try:
        return anchor.replace(year=year)
    except ValueError:                       # Feb 29 in a non-leap year: the anniversary is observed on Mar 1
        return date(year, 3, 1)


def days_since_anniversary(anchor: object, on: object) -> int:
    """Days from the most recent anniversary of ``anchor`` (its month and day) to ``on``, counting an anniversary that
    falls on ``on`` as 0. The posts count both directions: "33 days from California's founding date" is the days SINCE
    September 9 on October 12."""
    a, d = as_date(anchor), as_date(on)
    last = _anniversary(a, d.year)
    if last > d:
        last = _anniversary(a, d.year - 1)
    return (d - last).days


def days_until_anniversary(anchor: object, on: object) -> int:
    """Days from ``on`` to the next anniversary of ``anchor`` strictly after ``on`` ("19 days from UW's founding date" is
    the days UNTIL November 4 on October 16)."""
    a, d = as_date(anchor), as_date(on)
    nxt = _anniversary(a, d.year)
    if nxt <= d:
        nxt = _anniversary(a, d.year + 1)
    return (nxt - d).days


SPAN_UNITS = ("days", "weeks", "years", "year_gap", "anniv_since_days", "anniv_since_weeks", "anniv_until_days",
              "anniv_until_weeks")


def span(start: object, end: object, unit: str, *, inclusive: bool = False) -> int:
    """One of the span counts. ``days``/``weeks`` run from ``start`` to ``end``; the ``anniv_*`` units run from the nearest
    anniversary of ``start`` (month and day) to ``end``, backwards (``since``) or forwards (``until``). ``inclusive``
    counts both end points (one more day) and applies only to the day and week units."""
    if unit == "days":
        return span_days(start, end, inclusive=inclusive)
    if unit == "weeks":
        return span_weeks(start, end, inclusive=inclusive)
    if unit == "years":
        return span_years(start, end)
    if unit == "year_gap":
        return calendar_year_gap(start, end)
    if unit.startswith("anniv_"):
        _, direction, measure = unit.split("_")
        n = days_since_anniversary(start, end) if direction == "since" else days_until_anniversary(start, end)
        n += 1 if inclusive else 0
        return n // 7 if measure == "weeks" else n
    raise ValueError(f"unknown span unit {unit!r}")


def span_takes_inclusive(unit: str) -> bool:
    return unit.endswith(("days", "weeks"))


_UNIT_WORDS = {"days": "days", "weeks": "weeks", "years": "completed years", "year_gap": "calendar-year gap",
               "anniv_since_days": "days since the last anniversary", "anniv_since_weeks": "weeks since the last anniversary",
               "anniv_until_days": "days until the next anniversary", "anniv_until_weeks": "weeks until the next anniversary"}


def span_label(unit: str, inclusive: bool) -> str:
    """Words for a span unit, with the end-point convention spelled out wherever it matters."""
    if unit not in _UNIT_WORDS:
        raise ValueError(f"unknown span unit {unit!r}")
    if not span_takes_inclusive(unit):
        return _UNIT_WORDS[unit]
    return f"{_UNIT_WORDS[unit]} ({'inclusive' if inclusive else 'exclusive'})"


def ordinal_word(n: int) -> str:
    """33 -> '33rd', 11 -> '11th', 21 -> '21st'."""
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def weekday_name(d: object) -> str:
    return ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[as_date(d).weekday()]
