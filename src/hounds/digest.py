"""The daily Discord post for the Hounds race: facts from code, voice from a sports-betting server.

WHY CODE WRITES IT. A Zapier job let an AI write the race summary from the leaderboard JSON and it said 21
hounds when the board had 35. Every number and name in the post now comes from this module: the count is
``len(hounds)``, the records are tallied from the settled forward bets, the verdict names are the referee's
labels. The VOICE is fixed strings (short, punchy, a little trash talk, a few emojis) because the audience
is a betting Discord and the first version read like a science paper. Nothing here asks a model anything.

WHAT THE FUN MAY AND MAY NOT SAY (owner rulings 2026-10-18):
  allowed   W-L records and the PAPER bankroll figure (degens care): last 7 days when the live book is at
            hand, the season record when only the saved copy is (it carries no per-bet rows, and a
            last-7-days line made from a season record would be a false label; the line says which one it
            is). Since the owner's bankroll ruling (2026-10-19, docs/BANKROLL.md) money is said the way the
            site says it: a return on the shared $1,000 paper bankroll, "+3.0% (+$30 paper)", never raw
            units. The word "paper" rides on every dollar figure; a "$" or "money" in a NAME or a CAUSE
            (data from strangers) is still refused by ``BANNED``.
  never     a hound being profitable long term, an edge, a lock or a sure thing, any advice to bet
  always    the closing-line verdict line (the referee's one question), and the closing line:
            "Paper bets only, not advice. 21+. Gamble responsibly: 1-800-GAMBLER" then the link
``BANNED`` is checked against every name and cause that goes into the post (a hound named "Edge Finder" is
left out of the highlights rather than printed), and the tests check the finished post.

Standard library only, so the module loads (and its tests run) where FastAPI is not installed.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date as date_cls, timedelta
from typing import Optional

MAX_POST_CHARS = 900
MAX_NAME_CHARS = 40
WINDOW_DAYS = 7                    # "last 7 days": the as_of day and the six before it
MIN_SETTLED_FOR_HIGHLIGHT = 3      # one 1-0 night is not a hot streak; fewer settled bets than this are not named

LINK = ("https://linehound.app/web/hounds.html"
        "?utm_source=discord&utm_medium=digest&utm_campaign=hounds_daily")
CLOSING_LINE = "Paper bets only, not advice. 21+. Gamble responsibly: 1-800-GAMBLER"

# The Coin-Flip line compares these two by id: the random control against the stats hound it is meant to
# embarrass. Either one missing or without a settled bet means the line is left out, never guessed.
COIN_FLIP_ID, PROFESSOR_ID = "coin_flip_collie", "professor_paws"

BEATING_THE_CLOSE = "BEATING THE CLOSE"

# Phrases and shapes the post must not contain (case-insensitive).
BANNED = re.compile(
    r"edge|guarantee|\block(s|ed)?\b|can'?t lose|sure thing|profitable|money|\$|#", re.IGNORECASE)

# Retired causes in plain words (src.hounds.verdict CAUSE_UNITS / CAUSE_CLV; src.hounds.stats owner retirement).
_CAUSE_REWRITES = (
    ("retired: down more than 25 units", "down more than 25 units"),
    ("retired: closing price verdict paying the vig at 300+ bets",
     "couldn't beat the closing line over 300+ bets"),
    ("retired by the owner", "the owner pulled it"),
)
_FALLBACK_CAUSE = "retired from the race"


def _clean(text) -> str:
    """One line of plain text: no control characters, no hashtag marks, no emoji in a data string (the
    post's own emojis are fixed in this module)."""
    out = []
    for ch in str(text or ""):
        cat = unicodedata.category(ch)
        if ch in "‍️#" or cat in ("So", "Sk", "Cs", "Co", "Cn") or ord(ch) >= 0x1F000:
            continue
        out.append(" " if cat.startswith("C") else ch)
    return " ".join("".join(out).split())


def _short(text: str) -> str:
    return text if len(text) <= MAX_NAME_CHARS else text[:MAX_NAME_CHARS - 3].rstrip() + "..."


def _banned(text: str) -> bool:
    return BANNED.search(text) is not None


def _name(hound: dict) -> Optional[str]:
    """The hound's name for the post, or None when it is empty or would break the post's rules."""
    name = _short(_clean(hound.get("name")))
    return name if name and not _banned(name) else None


def _category_of(hound: dict) -> str:
    return str(hound.get("category") or "").strip().lower()


def _label_of(hound: dict) -> str:
    verdict = hound.get("verdict")
    return str(verdict.get("label") or "").strip().upper() if isinstance(verdict, dict) else ""


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _count(record, key) -> int:
    value = record.get(key) if isinstance(record, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def units_text(units: float) -> str:
    """``+4.2u`` / ``-3.1u`` (a rounded zero is ``+0.0u``, never ``-0.0u``)."""
    rounded = round(units, 1)
    return f"{(0.0 if rounded == 0 else rounded):+.1f}u"


def pct_text(pct: float) -> str:
    """``+3.0%`` / ``-1.3%`` (a rounded zero is ``+0.0%``, never ``-0.0%``)."""
    rounded = round(pct, 1)
    return f"{(0.0 if rounded == 0 else rounded):+.1f}%"


def money_text(usd: float) -> str:
    """``+$30`` / ``-$13`` in whole paper dollars (a rounded zero is ``+$0``)."""
    rounded = int(round(usd))
    return f"{'-' if rounded < 0 else '+'}${abs(rounded):,}"


def figure_text(row: dict) -> str:
    """``+3.0% (+$30 paper)``: the return on the shared paper bankroll, then the dollars it is."""
    return f"{pct_text(row['pct'])} ({money_text(row['usd'])} paper)"


def _start() -> float:
    from src.hounds import bankroll as bk
    return bk.params().start


def _money_of(units: float, block=None) -> tuple:
    """``(usd, pct)``: from the hound's own bankroll figures when it reports them (they are stake-weighted for
    a member dog), else the units at the shared flat unit (an old saved copy has no bankroll block)."""
    from src.hounds import bankroll as bk
    if isinstance(block, dict) and _num(block.get("pnl_usd")) is not None and _num(block.get("return_pct")) is not None:
        return float(block["pnl_usd"]), float(block["return_pct"])
    p = bk.params()
    usd = units * p.unit_usd
    return usd, usd / p.start * 100.0


# ---- the numbers ----------------------------------------------------------------------------------

def season_stats(hound: dict) -> Optional[dict]:
    """W, L and units from the leaderboard record (the page's headline basis: average price when it is
    reported, else the recorded price), or None when the record has no settled bet."""
    record = hound.get("record")
    wins, losses = _count(record, "wins"), _count(record, "losses")
    if not isinstance(record, dict) or wins + losses == 0:
        return None
    units = _num(record.get("units_average_price"))
    if units is None:
        units = _num(record.get("units_recorded_price"))
    if units is None:
        return None
    usd, pct = _money_of(units, hound.get("bankroll"))
    return {"wins": wins, "losses": losses, "units": units, "usd": usd, "pct": pct}


def _window_start(as_of_day: str) -> str:
    return (date_cls.fromisoformat(as_of_day) - timedelta(days=WINDOW_DAYS - 1)).isoformat()


def _cum_usd(series: list, on_or_before: Optional[str] = None, before: Optional[str] = None) -> Optional[float]:
    """The account balance at the last series point inside the bound; None when a point has no dollar figure
    (a series from before the bankroll view), so the caller falls back to units."""
    last = None
    for point in series:
        day = str(getattr(point, "date", ""))[:10]
        if (on_or_before is not None and day > on_or_before) or (before is not None and day >= before):
            break
        value = getattr(point, "bankroll_usd", None)
        if value is None:
            return None
        last = value
    return last


def _cum_units(series: list, basis: str, on_or_before: Optional[str] = None,
               before: Optional[str] = None) -> float:
    """Cumulative units at the last series point inside the bound (0.0 before the first point)."""
    last = 0.0
    for point in series:
        day = str(getattr(point, "date", ""))[:10]
        if (on_or_before is not None and day > on_or_before) or (before is not None and day >= before):
            break
        value = getattr(point, "cum_units_average_price" if basis == "average_price"
                        else "cum_units_recorded_price", None)
        if value is not None:
            last = value
    return last


def week_stats(hounds: dict, as_of: Optional[str]) -> dict:
    """``{hound_id: {wins, losses, units}}`` for forward bets that SETTLED in the last 7 days
    (``as_of`` day and the six before), from the live book's per-bet rows and series.

    Units are the difference of the hound's cumulative units across the window, on the same basis as its
    season headline (``spark_basis``), so a week can never use a different price than the season does.
    Hounds with no settled win or loss in the window are absent."""
    try:
        end = str(as_of or "")[:10]
        start = _window_start(end)
    except ValueError:
        return {}
    out = {}
    for hid, data in (hounds or {}).items():
        rows = [b for b in data.bets if b.segment == "forward" and b.result in ("win", "loss")
                and start <= str(b.date)[:10] <= end]
        if not rows:
            continue
        basis = data.summary.spark_basis or "recorded_price"
        units = (_cum_units(data.series, basis, on_or_before=end)
                 - _cum_units(data.series, basis, before=start))
        block = None
        end_bal = _cum_usd(data.series, on_or_before=end)
        if end_bal is not None:
            before_bal = _cum_usd(data.series, before=start)
            usd_week = end_bal - (before_bal if before_bal is not None else _start())
            block = {"pnl_usd": usd_week, "return_pct": usd_week / _start() * 100.0}
        usd, pct = _money_of(units, block)
        out[hid] = {"wins": sum(1 for b in rows if b.result == "win"),
                    "losses": sum(1 for b in rows if b.result == "loss"), "units": round(units, 4),
                    "usd": round(usd, 2), "pct": round(pct, 3)}
    return out


# ---- the lines ------------------------------------------------------------------------------------

def _race(hounds: list) -> list:
    return [h for h in hounds if isinstance(h, dict) and _category_of(h) != "baseline"]


def _stats_for(hound: dict, window: Optional[dict]) -> Optional[dict]:
    if window is None:
        return season_stats(hound)
    s = window.get(str(hound.get("id")))
    if not s or ("usd" in s and "pct" in s):
        return s
    usd, pct = _money_of(_num(s.get("units")) or 0.0)     # a window from before the bankroll view: units at the flat unit
    return {**s, "usd": usd, "pct": pct}


def _span(window: Optional[dict]) -> str:
    return "season" if window is None else "last 7 days"


def _pool(hounds: list) -> list:
    """Who can be named hottest or coldest: the models RANKED in the payload's season (``ranked: true``, at least
    ``seasons.MIN_RANKED_BETS`` settled bets there) when any are, else the whole race. A one-bet model is not a
    hot streak, and a young season should not be named from a handful of its tickets while seasoned models
    exist. A payload with no ``ranked`` flag (an old saved copy) has no ranked model, so it is the whole race."""
    race = _race(hounds)
    ranked = [h for h in race if h.get("ranked") is True]
    return ranked or race


def _pick(hounds: list, window: Optional[dict], hot: bool):
    """The hottest (or coldest) race hound by paper dollars: at least MIN_SETTLED_FOR_HIGHLIGHT settled bets in
    the span, dollars strictly above (below) zero at the whole dollar the post prints. Ties: more wins (losses)
    first, then name."""
    best = None
    for h in _pool(hounds):
        s, name = _stats_for(h, window), _name(h)
        if not s or not name or s["wins"] + s["losses"] < MIN_SETTLED_FOR_HIGHLIGHT:
            continue
        shown = round(s["usd"])
        if (shown <= 0) if hot else (shown >= 0):
            continue
        key = (-shown if hot else shown, -(s["wins"] if hot else s["losses"]), name.casefold(), name)
        if best is None or key < best[0]:
            best = (key, name, s)
    return best


def hottest_line(hounds: list, window: Optional[dict]) -> Optional[str]:
    best = _pick(hounds, window, hot=True)
    if not best:
        return None
    _, name, s = best
    return f"🔥 Hottest dog: {name} {s['wins']}-{s['losses']} {_span(window)}, {figure_text(s)}"


def coldest_line(hounds: list, window: Optional[dict]) -> Optional[str]:
    best = _pick(hounds, window, hot=False)
    if not best:
        return None
    _, name, s = best
    return (f"🥶 Ice cold: {name} {s['wins']}-{s['losses']} {_span(window)}, {figure_text(s)}. "
            "Check its pulse.")


def coin_flip_line(hounds: list) -> Optional[str]:
    """Season return, whatever the window: a 7-day rivalry would flip on a single night. Both hounds need a
    settled bet or the line is left out."""
    by_id = {str(h.get("id")): h for h in hounds if isinstance(h, dict)}
    collie, prof = by_id.get(COIN_FLIP_ID), by_id.get(PROFESSOR_ID)
    if not collie or not prof:
        return None
    a, b = season_stats(collie), season_stats(prof)
    na, nb = _name(collie), _name(prof)
    if not (a and b and na and nb):
        return None
    ua, ub = round(a["pct"], 1), round(b["pct"], 1)
    both = f"({pct_text(a['pct'])} vs {pct_text(b['pct'])}, season)"
    if ua > ub:
        return f"🪙 {na} is ahead of {nb} {both}. The random dog is embarrassing the stats guys."
    if ua < ub:
        return f"🪙 {na} is behind {nb} {both}. Order restored."
    return f"🪙 {na} is level with {nb} {both}. Coin flips, folks."


def sharp_line(hounds: list) -> str:
    """The referee's one question, answered from the verdict labels. Baselines are yardsticks, not entrants."""
    names = sorted((n for n in (_name(h) for h in _race(hounds) if _label_of(h) == BEATING_THE_CLOSE) if n),
                   key=lambda n: (n.casefold(), n))
    if not names:
        return "🧠 Nobody's beating the closing line yet. The ref says it's all luck so far."
    if len(names) == 1:
        return f"🧠 Sharp or lucky? {names[0]} is the only one beating the closing line."
    shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    return f"🧠 Sharp or lucky? {len(names)} dogs are beating the closing line: {shown}."


def safe_cause(cause) -> str:
    """The retired cause in plain words that pass the post's rules."""
    text = _clean(cause)
    for original, plain in _CAUSE_REWRITES:
        if text.lower() == original:
            return plain
    if text.lower().startswith("retired: "):
        text = text[len("retired: "):]
    return text if text and not _banned(text) else _FALLBACK_CAUSE


def _coach_line(line) -> Optional[str]:
    """The coach line if it passes the post's own rules (one line, no banned phrase), else None: the digest
    leaves a line out rather than print something it would not have written."""
    text = " ".join(str(line or "").split())
    return text if text and not _banned(text) else None


def graveyard_line(graveyard_hounds: list) -> Optional[str]:
    """``💀 Graveyard: <name> (<cause>)`` for the most recently retired hound (latest retired date; a hound
    with no date ranks last), or None."""
    rows = [h for h in graveyard_hounds or [] if isinstance(h, dict) and h.get("name")]

    def when(h):
        r = h.get("retired")
        return str(r.get("date") or "") if isinstance(r, dict) else ""

    # Latest date first; the name breaks ties so the answer never depends on file order.
    for h in sorted(rows, key=lambda h: (when(h), str(h.get("name"))), reverse=True):
        name = _name(h)
        r = h.get("retired")
        if name:
            return f"💀 Graveyard: {name} ({safe_cause(r.get('cause') if isinstance(r, dict) else '')})"
    return None


def race_date(leaderboard: dict) -> Optional[str]:
    """The board's own date as 'Sun Oct 18'; None when the board carries no date. (A "Day N" count was
    dropped: the board includes back-filled history, so it overstated how long the live race has run.)"""
    today = str(leaderboard.get("data_as_of") or leaderboard.get("as_of") or "")[:10]
    try:
        d = date_cls.fromisoformat(today)
    except (ValueError, TypeError):
        return None
    return f"{d.strftime('%a %b')} {d.day}"


# ---- assembly --------------------------------------------------------------------------------------

def _assemble(leaderboard: dict, middle: list) -> str:
    when = race_date(leaderboard)
    head = "🐶 LineHound Kennel" + (f" | {when}" if when else "")
    lines = [head, f"{len(leaderboard['hounds'])} dogs in the race (paper bets, MLB and NFL)."]
    lines.extend(middle)
    lines.extend([CLOSING_LINE, LINK])
    return "\n".join(lines)


def build_post(leaderboard: dict, graveyard: Optional[dict] = None, window: Optional[dict] = None,
               coach_line: Optional[str] = None) -> str:
    """The post text. ``window`` is ``week_stats`` output from the live book, or None to use season records
    (the saved-copy path). ``coach_line`` is the coach report card's one line (``coach_report.digest_line``),
    present only once the coach has made a suggestion; it goes right after the closing-line verdict. Over
    MAX_POST_CHARS the optional lines go in this order: graveyard, Coin-Flip, ice cold, hottest, the coach line
    (the owner's priority: dropped last); the count, the closing-line verdict, the responsible-gambling line and
    the link are never trimmed."""
    hounds = leaderboard["hounds"]
    hot, cold = hottest_line(hounds, window), coldest_line(hounds, window)
    optional = [("hot", hot), ("cold", cold), ("coin", coin_flip_line(hounds)),
                ("grave", graveyard_line((graveyard or {}).get("hounds") or [])),
                ("coach", _coach_line(coach_line))]
    sharp = sharp_line(hounds)
    kept = [(k, v) for k, v in optional if v]

    def post_of(entries):
        order = ([v for k, v in entries if k in ("hot", "cold")] + [sharp]
                 + [v for k, v in entries if k == "coach"]
                 + [v for k, v in entries if k in ("coin", "grave")])
        return _assemble(leaderboard, order)

    post = post_of(kept)
    for drop in ("grave", "coin", "cold", "hot", "coach"):
        if len(post) <= MAX_POST_CHARS:
            break
        kept = [(k, v) for k, v in kept if k != drop]
        post = post_of(kept)
    return post


def _usable(payload) -> bool:
    return (isinstance(payload, dict) and not payload.get("warming_up")
            and isinstance(payload.get("hounds"), list) and bool(payload["hounds"]))


def skip_payload() -> dict:
    return {"post": "", "skip": True, "as_of": None, "hounds_total": 0, "paper_only": True}


def digest(leaderboard: Optional[dict], graveyard: Optional[dict] = None,
           window: Optional[dict] = None, coach_line: Optional[str] = None) -> dict:
    """The /hounds/digest body. ``skip`` is true only when there is no leaderboard to speak from: no live
    book, no saved copy (``warming_up``), or an empty race."""
    if not _usable(leaderboard):
        return skip_payload()
    return {"post": build_post(leaderboard, graveyard, window, coach_line), "skip": False,
            "as_of": leaderboard.get("as_of"), "hounds_total": len(leaderboard["hounds"]),
            "paper_only": True}
