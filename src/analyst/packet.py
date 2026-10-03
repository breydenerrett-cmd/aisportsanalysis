"""The fact packet: everything the analyst may know about one game, frozen.

WHY A PACKET AND NOT "GIVE THE MODEL THE PAGE"
----------------------------------------------
A call is only worth publishing if a reader (or a checker) can walk from each
sentence back to a fact and see the fact was true when the call was made. That
needs three properties, and the packet is built to have all of them:

  1. SELF-CONTAINED. The model gets this object and nothing else. It has no
     tools, no search and no memory of other games, so a claim that is not in
     the packet has no source and the critic strikes it.
  2. FROZEN AND HASHABLE. `packet_hash` is a sha256 of the canonical JSON.
     The ledger stores the hash with the published calls and keeps the packet
     file, so "what did the analyst know" is a question with one answer that
     cannot be edited later. Building the same inputs twice gives the same
     hash: nothing here reads the clock (the caller passes `built_at`), the
     disk or the network, and every list is sorted.
  3. HONEST ABOUT HOLES. `missing` lists every input that was absent, stale or
     thin, with the reason. The prompt tells the model that PASS is the
     default when evidence is thin; this list is how it can tell.

NO FUTURE LEAKAGE
-----------------
Quotes captured after `built_at`, or at or after first pitch, are dropped. The
game block is a whitelist (identity, venue, first pitch, state, probable
starters): the payload it is built from carries final scores once a game is
over, and none of that may reach the model.

THE PATH GRAMMAR (this is what closes the benchmark's `data.` mismatch)
-----------------------------------------------------------------------
`docs/AI_CRITIC_BENCHMARK.md` records a critic that wrote every fact path as
`data.best_price` where the checker wanted `best_price`: right values, wrong
paths, 102 times, because the instruction never said what a path looked like.
Here a path is always rooted at the packet itself:

    markets.moneyline.options[0].best.price
    sections.starters.values.home_sp_era

Dot-separated keys, `[n]` for a list index, nothing else. The prompt shows two
real examples, `resolve_path` is the only resolver, and a path that does not
resolve is reported with the reason (including the specific `data.` mistake).

THE SLOTS
---------
`markets` is keyed by slot id. A slot is one thing the analyst must call:
`moneyline`, `run_line`, `total`, `team_total_away`, `team_total_home`,
`prop_01`... Each carries its options with the lean (the side the market
favours) first, so verdicts are defined without ambiguity:

    TAKE             bet the lean (the first option)
    TAKE_OTHER_SIDE  bet the other option, the side the market does not favour
    PASS             bet nothing here

Pure: no I/O, no clock, no network, no api/ import.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from src.core import odds as odds_math
from src.ledger.chain import canonical_bytes
from src.situation import record as situation_record

PACKET_VERSION = "analyst_packet_v1"
# Arm B of the side-by-side test: the same packet with a `situation` section. The version says
# so, and a packet built without a situation is byte for byte what it was (same version, same hash).
PACKET_VERSION_SITUATION = "analyst_packet_v1_situation"

# A section whose own as-of stamp is older than this is flagged stale.
STALE_SECTION_DAYS = 14

# Team and starter stats are built from the results store, which the daily loop
# ingests every morning. Stats that stop more than this many days before the
# game mean an ingest stopped, and the model is told so rather than shown a
# fortnight-old record as though it were current.
STALE_STATS_DAYS = 3

# Sections copied from the game payload, in the order they are listed. The
# market sections are NOT here: prices are rebuilt from the stores below so
# every quote carries its own capture time.
SECTION_ORDER = ("teams", "starters", "lineups", "matchup_history",
                 "matchup_depth", "splits", "arsenals", "bullpen", "travel",
                 "weather", "park", "news", "standings", "read")

# Keys dropped everywhere: identifiers the model cannot use, and coordinates.
_DROP_KEYS = frozenset({"person_id", "player_id", "lat", "lon", "team_name_alt",
                        "orientation_deg", "vs_pitch"})

LIMITS = (
    "Only the most-quoted line of each market is analyzed; alternate run lines "
    "and alternate totals are not.",
    "First-five-inning markets are not analyzed.",
    "Player props are capped per game; the contracts left out are counted in "
    "`missing`.",
    "Every quote is the newest one captured before this packet was built, with "
    "its capture time; nothing was captured after it.",
)


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*$")
_TOKEN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


def resolve_path(packet: Mapping, path: Any):
    """`(True, value)` when `path` names a value in the packet, else
    `(False, reason)`. The reason is written for the model and the log."""
    if not isinstance(path, str) or not path.strip():
        return False, "the path is empty"
    if path.startswith("data.") or path.startswith("packet."):
        return False, ("paths start at the packet's own top-level key "
                       "(markets, sections, game ...), not with "
                       f"{path.split('.')[0]!r}")
    if not _PATH_RE.match(path):
        return False, "not a valid path (dot-separated keys and [n] indexes only)"
    node: Any = packet
    for match in _TOKEN_RE.finditer(path):
        key, index = match.group(1), match.group(2)
        if key is not None:
            if not isinstance(node, Mapping) or key not in node:
                return False, f"no key {key!r} at that point in the path"
            node = node[key]
        else:
            i = int(index)
            if not isinstance(node, list) or i >= len(node):
                return False, f"no list item [{i}] at that point in the path"
            node = node[i]
    return True, node


def iter_leaves(node: Any, prefix: str = "") -> Iterable:
    """(path, scalar) for every scalar leaf, depth first, in a stable order."""
    if isinstance(node, Mapping):
        for key in sorted(node):
            yield from iter_leaves(node[key], f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from iter_leaves(item, f"{prefix}[{i}]")
    else:
        yield prefix, node


def numbers_in_packet(packet: Mapping) -> list:
    """Every real number in the packet (bools are not numbers)."""
    return [v for _p, v in iter_leaves(packet)
            if isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v)]


def packet_hash(packet: Mapping) -> str:
    """sha256 of the packet's canonical JSON. Same inputs, same hash."""
    return hashlib.sha256(canonical_bytes(packet)).hexdigest()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _clean_key(key: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(key)).strip("_") or "k"
    return f"k_{text}" if text[0].isdigit() else text


def _scrub(node: Any) -> Any:
    """Copy with identifier keys dropped and every key made path-safe."""
    if isinstance(node, Mapping):
        return {_clean_key(k): _scrub(v) for k, v in sorted(node.items(), key=lambda kv: str(kv[0]))
                if str(k) not in _DROP_KEYS}
    if isinstance(node, (list, tuple)):
        return [_scrub(v) for v in node]
    if isinstance(node, float) and not math.isfinite(node):
        return None
    return node


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _price(value: Any) -> Optional[int]:
    out = _num(value)
    if out is None or abs(out) < 100:
        return None
    return int(round(out))


def _clean_line(value: Any) -> Optional[float]:
    out = _num(value)
    return None if out is None else round(out, 2)


def _dec(price: int) -> float:
    return odds_math.american_to_decimal(price)


# ---------------------------------------------------------------------------
# quotes and options
# ---------------------------------------------------------------------------

def _latest_by_book(rows: Iterable[Mapping], *, cutoff: datetime,
                    first_pitch: Optional[datetime]) -> list:
    """The newest row per book captured before `cutoff` and before first pitch.

    Rows with no readable capture time are dropped: a quote that cannot be
    dated cannot be shown to precede the game.
    """
    newest: dict = {}
    for row in rows:
        seen = _parse_utc(row.get("observed_utc") or row.get("ts"))
        if seen is None or seen > cutoff:
            continue
        if first_pitch is not None and seen >= first_pitch:
            continue
        book = row.get("book")
        if not book:
            continue
        # Same book, same capture instant, different rows (a duplicated or
        # re-listed quote): the tie is broken on the row's own bytes, never on
        # the order the rows arrived in, so the packet hash cannot depend on it.
        rank = (seen, json.dumps(row, sort_keys=True, default=str))
        held = newest.get(book)
        if held is None or rank > held[0]:
            newest[book] = (rank, row)
    return [newest[b][1] | {"_seen": newest[b][0][0]} for b in sorted(newest)]


def _quote(book: str, price: int, seen: datetime) -> dict:
    return {"book": book, "price": price, "captured_utc": _iso(seen)}


def _best(quotes: Sequence[Mapping]) -> Optional[dict]:
    if not quotes:
        return None
    top = max(quotes, key=lambda q: (_dec(q["price"]), q["book"]))
    return {"price": top["price"], "book": top["book"]}


def _option(selection: str, side: str, line: Optional[float], quotes: list,
            fair: Optional[float]) -> dict:
    quotes = sorted(quotes, key=lambda q: q["book"])
    return {
        "selection": selection,
        "side": side,
        "line": line,
        "books": len(quotes),
        "quotes": quotes,
        "best": _best(quotes),
        "fair_probability": None if fair is None else round(fair, 4),
    }


def _two_way(rows: Sequence[Mapping], key_a: str, key_b: str):
    """(quotes_a, quotes_b, fair_a) from per-book rows holding both prices.

    Fair probability is the mean over books of each book's own proportional
    de-vig, using only books that quoted BOTH sides. It is the books' read of
    the odds at that instant with their margin taken back out, not a forecast.
    """
    quotes_a, quotes_b, fairs = [], [], []
    for row in rows:
        pa, pb, seen = _price(row.get(key_a)), _price(row.get(key_b)), row["_seen"]
        if pa is not None:
            quotes_a.append(_quote(row["book"], pa, seen))
        if pb is not None:
            quotes_b.append(_quote(row["book"], pb, seen))
        if pa is not None and pb is not None:
            try:
                fairs.append(odds_math.devig_two_way(pa, pb)[0])
            except odds_math.OddsError:
                continue
    fair_a = sum(fairs) / len(fairs) if fairs else None
    return quotes_a, quotes_b, fair_a


def _ordered(opt_a: dict, opt_b: Optional[dict]) -> list:
    """[lean, other]. The lean is the option with the higher fair probability;
    with no two-way fair price it is the one with the shorter best price."""
    if opt_b is None:
        return [opt_a]
    fa, fb = opt_a["fair_probability"], opt_b["fair_probability"]
    if fa is not None and fb is not None:
        a_first = fa >= fb
    else:
        pa = opt_a["best"]["price"] if opt_a["best"] else None
        pb = opt_b["best"]["price"] if opt_b["best"] else None
        if pa is None or pb is None:
            a_first = True
        else:
            a_first = _dec(pa) <= _dec(pb)
    return [opt_a, opt_b] if a_first else [opt_b, opt_a]


def _as_of(options: Sequence[Mapping]) -> Optional[str]:
    stamps = [q["captured_utc"] for o in options for q in o["quotes"]]
    return max(stamps) if stamps else None


def _market(slot_id: str, market: str, label: str, options: list,
            context: Optional[dict] = None) -> dict:
    out = {
        "slot_id": slot_id,
        "market": market,
        "label": label,
        "as_of": _as_of(options),
        "lean": options[0]["selection"],
        "options": options,
    }
    if context:
        out["context"] = context
    return out


def _main_line(groups: Mapping, *, prefer: float) -> Optional[Any]:
    """The most-quoted line; ties go to the line nearest `prefer`."""
    if not groups:
        return None
    return sorted(groups, key=lambda k: (-len(groups[k]), abs(k - prefer), k))[0]


# ---------------------------------------------------------------------------
# the markets
# ---------------------------------------------------------------------------

def _moneyline(rows, away, home, cutoff, first_pitch):
    book_rows = _latest_by_book(
        [r for r in rows if r.get("market") in (None, "h2h")],
        cutoff=cutoff, first_pitch=first_pitch)
    book_rows = [r for r in book_rows if _price(r.get("away_price")) is not None
                 or _price(r.get("home_price")) is not None]
    if not book_rows:
        return None
    qa, qh, fair_a = _two_way(book_rows, "away_price", "home_price")
    if not qa or not qh:
        return None
    away_opt = _option(away, "away", None, qa, fair_a)
    home_opt = _option(home, "home", None, qh, None if fair_a is None else 1 - fair_a)
    return _market("moneyline", "moneyline", f"{away} at {home} moneyline",
                   _ordered(away_opt, home_opt))


def _run_line(rows, away, home, cutoff, first_pitch):
    book_rows = _latest_by_book([r for r in rows if r.get("market") == "spreads"],
                                cutoff=cutoff, first_pitch=first_pitch)
    groups: dict = {}
    for r in book_rows:
        hl, al = _clean_line(r.get("home_line")), _clean_line(r.get("away_line"))
        if hl is None or al is None or abs(hl + al) > 1e-9:
            continue
        groups.setdefault(hl, []).append(r)
    home_line = _main_line(groups, prefer=1.5)
    if home_line is None:
        return None
    qa, qh, fair_a = _two_way(groups[home_line], "away_price", "home_price")
    if not qa or not qh:
        return None
    away_line = -home_line
    away_opt = _option(f"{away} {away_line:+g}", "away", away_line, qa, fair_a)
    home_opt = _option(f"{home} {home_line:+g}", "home", home_line, qh,
                       None if fair_a is None else 1 - fair_a)
    return _market("run_line", "run_line", f"{away} at {home} run line",
                   _ordered(away_opt, home_opt))


def _total(rows, away, home, cutoff, first_pitch):
    book_rows = _latest_by_book([r for r in rows if r.get("market") == "totals"],
                                cutoff=cutoff, first_pitch=first_pitch)
    groups: dict = {}
    for r in book_rows:
        line = _clean_line(r.get("total"))
        if line is not None:
            groups.setdefault(line, []).append(r)
    line = _main_line(groups, prefer=8.5)
    if line is None:
        return None
    qo, qu, fair_o = _two_way(groups[line], "over_price", "under_price")
    if not qo or not qu:
        return None
    over = _option(f"Over {line:g}", "over", line, qo, fair_o)
    under = _option(f"Under {line:g}", "under", line, qu,
                    None if fair_o is None else 1 - fair_o)
    return _market("total", "total", f"{away} at {home} game total runs",
                   _ordered(over, under))


def _team_totals(rows, away, home, away_name, home_name, cutoff, first_pitch) -> dict:
    """{slot_id: market}. Rows are the derivative store's one-price-per-row
    shape: team, line, side, price, book."""
    out: dict = {}
    for slot_id, abbrev, full, side in (("team_total_away", away, away_name, "away"),
                                        ("team_total_home", home, home_name, "home")):
        mine = [r for r in rows if r.get("market") == "team_totals"
                and (r.get("team") == full)]
        per_book: dict = {}
        for r in mine:
            seen = _parse_utc(r.get("observed_utc"))
            if seen is None or seen > cutoff or (first_pitch and seen >= first_pitch):
                continue
            line, price = _clean_line(r.get("line")), _price(r.get("price"))
            sd = str(r.get("side") or "").lower()
            if line is None or price is None or sd not in ("over", "under") or not r.get("book"):
                continue
            key = (r["book"], line, sd)
            held = per_book.get(key)
            if held is None or (seen, price) > held:
                per_book[key] = (seen, price)
        # newest capture per book decides which line that book is on now
        # A book that lists two lines at the same instant is on the one nearer
        # the usual 4.0; the choice never depends on row order.
        newest_line: dict = {}
        for (book, line, _sd), (seen, _p) in per_book.items():
            rank = (seen, -abs(line - 4.0), line)
            held = newest_line.get(book)
            if held is None or rank > held[0]:
                newest_line[book] = (rank, line)
        groups: dict = {}
        for (book, line, sd), (seen, price) in per_book.items():
            if newest_line[book][1] == line:
                groups.setdefault(line, {}).setdefault(book, {})[sd] = (seen, price)
        counts = {ln: len(books) for ln, books in groups.items()}
        if not counts:
            continue
        line = sorted(counts, key=lambda k: (-counts[k], abs(k - 4.0), k))[0]
        qo, qu, fairs = [], [], []
        for book, sides in sorted(groups[line].items()):
            if "over" in sides:
                qo.append(_quote(book, sides["over"][1], sides["over"][0]))
            if "under" in sides:
                qu.append(_quote(book, sides["under"][1], sides["under"][0]))
            if "over" in sides and "under" in sides:
                try:
                    fairs.append(odds_math.devig_two_way(sides["over"][1], sides["under"][1])[0])
                except odds_math.OddsError:
                    pass
        if not qo or not qu:
            continue
        fair_o = sum(fairs) / len(fairs) if fairs else None
        over = _option(f"{abbrev} Over {line:g}", "over", line, qo, fair_o)
        under = _option(f"{abbrev} Under {line:g}", "under", line, qu,
                        None if fair_o is None else 1 - fair_o)
        market = _market(slot_id, "team_total", f"{abbrev} team total runs",
                         _ordered(over, under))
        market["context"] = {"team": abbrev, "team_side": side}
        out[slot_id] = market
    return out


# --- props -----------------------------------------------------------------

_STAT_WORDS = {
    "batter_hits": "hits", "batter_total_bases": "total bases",
    "batter_home_runs": "home runs", "batter_rbis": "RBIs",
    "batter_runs_scored": "runs scored", "batter_runs": "runs scored",
    "batter_stolen_bases": "stolen bases", "batter_walks": "walks",
    "batter_strikeouts": "strikeouts", "batter_hits_runs_rbis": "hits plus runs plus RBIs",
    "pitcher_strikeouts": "strikeouts", "pitcher_outs": "outs recorded",
    "pitcher_hits_allowed": "hits allowed", "pitcher_earned_runs": "earned runs",
    "pitcher_walks": "walks",
}


def _prop_groups(batter_rows, pitcher_rows, cutoff, first_pitch) -> dict:
    """{(player, market, line): {"over": {book: (seen, price)}, "under": {...}}}.

    Newest quote per (book, player, market, line, side) captured before the
    cutoff and before first pitch.
    """
    groups: dict = {}

    def put(player, market, line, side, book, price, seen):
        slot = groups.setdefault((player, market, line), {"over": {}, "under": {}})
        held = slot[side].get(book)
        if held is None or (seen, price) > held:
            slot[side][book] = (seen, price)

    for r in batter_rows:
        seen = _parse_utc(r.get("observed_utc"))
        if seen is None or seen > cutoff or (first_pitch and seen >= first_pitch):
            continue
        side = str(r.get("side") or "").lower()
        line, price = _clean_line(r.get("line")), _price(r.get("price"))
        if side not in ("over", "under") or line is None or price is None \
                or not r.get("player") or not r.get("market") or not r.get("book"):
            continue
        put(r["player"], r["market"], line, side, r["book"], price, seen)
    for r in pitcher_rows:
        seen = _parse_utc(r.get("observed_utc"))
        if seen is None or seen > cutoff or (first_pitch and seen >= first_pitch):
            continue
        line = _clean_line(r.get("point"))
        if line is None or not r.get("player") or not r.get("market") or not r.get("book"):
            continue
        for side, key in (("over", "over_price"), ("under", "under_price")):
            price = _price(r.get(key))
            if price is not None:
                put(r["player"], r["market"], line, side, r["book"], price, seen)
    return groups


def _prop_market(slot_id, player, market, line, sides, context) -> Optional[dict]:
    qo = [_quote(b, p, s) for b, (s, p) in sorted(sides["over"].items())]
    qu = [_quote(b, p, s) for b, (s, p) in sorted(sides["under"].items())]
    if not qo:
        return None
    fairs = []
    for book, (_s, po) in sides["over"].items():
        if book in sides["under"]:
            try:
                fairs.append(odds_math.devig_two_way(po, sides["under"][book][1])[0])
            except odds_math.OddsError:
                pass
    fair_o = sum(fairs) / len(fairs) if fairs else None
    over = _option(f"Over {line:g}", "over", line, qo, fair_o)
    if qu:
        under = _option(f"Under {line:g}", "under", line, qu,
                        None if fair_o is None else 1 - fair_o)
        options = _ordered(over, under)
    else:
        options = [over]  # one-sided market (home runs): there is no other side
    word = _STAT_WORDS.get(market, market.replace("_", " "))
    ctx = {"player": player, "stat": market}
    ctx.update(context or {})
    return _market(slot_id, "prop", f"{player} {word}", options, ctx)


def _select_props(groups: Mapping, board: Sequence[Mapping], *, cap: int,
                  min_books: int, probables: Sequence[str]) -> list:
    """Which (player, market, line) keys get a slot, in slot order.

    Starting pitchers' strikeout props first (at most two: there is one starter
    a side). Then the repo's own prop board order, which ranks by how likely
    the outcome is and never by the gap against the price (src/analysis/
    propboard.py measured the latter and it lost), with at most half the cap
    from one market so the analysis is not eleven near-identical hit props.
    With no board the order is books quoting, then name, which is arbitrary but
    deterministic.
    """
    def books(key):
        sides = groups[key]
        return len(set(sides["over"]) | set(sides["under"]))

    eligible = {k for k in groups if books(k) >= min_books and groups[k]["over"]}
    chosen: list = []
    for key in sorted(eligible, key=lambda k: (k[1], k[0], k[2])):
        if key[1] == "pitcher_strikeouts" and key[0] in probables and len(chosen) < 2:
            chosen.append(key)
    per_market: dict = {}
    half = max(1, math.ceil(cap / 2))

    def take(key):
        if key in chosen or key not in eligible or len(chosen) >= cap:
            return
        if per_market.get(key[1], 0) >= half:
            return
        chosen.append(key)
        per_market[key[1]] = per_market.get(key[1], 0) + 1

    for contract in board:
        line = _clean_line(contract.get("line"))
        take((contract.get("player"), contract.get("market"), line))
    for key in sorted(eligible, key=lambda k: (-books(k), k[1], k[0], k[2])):
        take(key)
    return chosen


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------

def _embedded_as_of(node: Any) -> list:
    found = []
    if isinstance(node, Mapping):
        for k, v in node.items():
            if k == "as_of" and isinstance(v, str):
                found.append(v)
            else:
                found.extend(_embedded_as_of(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_embedded_as_of(v))
    return found


def _compact(name: str, section: Any) -> Any:
    """Drop what the model cannot use and what would cost tokens for nothing."""
    if name == "arsenals" and isinstance(section, Mapping):
        out = {}
        for side in ("away", "home"):
            rows = section.get(side) or []
            out[side] = [{
                "pitcher": r.get("name"), "pitch": r.get("pitch_name"),
                "usage_pct": r.get("pitch_usage"), "whiff_pct": r.get("whiff_percent"),
                "k_pct": r.get("k_percent"), "hard_hit_pct": r.get("hard_hit_percent"),
                "woba": r.get("woba"), "est_woba": r.get("est_woba"), "pa": r.get("pa"),
            } for r in rows if isinstance(r, Mapping)]
        return out
    if name == "lineups" and isinstance(section, Mapping):
        out = {}
        for side in ("away", "home"):
            blk = section.get(side)
            if isinstance(blk, Mapping):
                out[side] = {
                    "batters": [{"order": b.get("order"), "name": b.get("name"),
                                 "position": b.get("position")}
                                for b in (blk.get("batters") or []) if isinstance(b, Mapping)],
                    "handedness": blk.get("handedness"),
                    "platoon_advantage": blk.get("platoon_advantage"),
                    "faces_starter_throwing": blk.get("faces_starter_throwing"),
                }
        return out
    return section


STATS_BASIS = "stats through this date"


def _section_as_of(name: str, values: Any, information_time: Optional[str],
                   overrides: Mapping) -> tuple:
    if name in overrides:
        return overrides[name], STATS_BASIS
    if name == "weather" and isinstance(values, Mapping) and values.get("observed_utc"):
        return values["observed_utc"], "forecast for the hour shown"
    embedded = _embedded_as_of(values)
    if embedded:
        return max(embedded), "newest stamp inside the section"
    return information_time, "when the game payload was built"


def _sections(advanced: Mapping, payload: Mapping, overrides: Mapping,
              game_date: str) -> tuple:
    raw = dict(advanced.get("sections") or {})
    read = payload.get("read") if isinstance(payload.get("read"), Mapping) else advanced.get("read")
    if isinstance(read, Mapping) and read:
        # The page's written read can carry a "Situation" block. The situation reaches the analyst
        # only through its own section (arm B), never through the read: otherwise arm A, the arm
        # that must not see it, would read it here.
        raw["read"] = {k: v for k, v in read.items() if k != "situation"}
    info = advanced.get("information_time")
    info = _iso(_parse_utc(info)) if info else None
    sections: dict = {}
    missing: list = []
    for name in SECTION_ORDER:
        if name not in raw or raw[name] in (None, {}, []):
            continue
        values = _scrub(_compact(name, raw[name]))
        as_of, basis = _section_as_of(name, values, info, overrides)
        sections[name] = {"as_of": as_of, "as_of_basis": basis, "values": values}
        if basis == STATS_BASIS and as_of:
            a = _parse_utc(str(as_of)[:10] + "T12:00:00Z")
            g = _parse_utc(game_date + "T12:00:00Z")
            if a and g and (g - a).days > STALE_STATS_DAYS:
                missing.append({"item": name, "kind": "stale",
                                "reason": f"{name} stats run only through {str(as_of)[:10]}, "
                                          f"{(g - a).days} days before the game"})
        for stamp in _embedded_as_of(values):
            a, g = _parse_utc(stamp), _parse_utc(game_date + "T12:00:00Z")
            if a and g and (g - a).days > STALE_SECTION_DAYS:
                missing.append({"item": name, "kind": "stale",
                                "reason": f"newest stamp inside this section is {stamp[:10]}, "
                                          f"more than {STALE_SECTION_DAYS} days before the game"})
                break
    # absent: the payload's own gap reasons, verbatim
    for name, reason in sorted((advanced.get("gaps") or {}).items()):
        if name in SECTION_ORDER or name == "lineups":
            missing.append({"item": name, "kind": "absent", "reason": str(reason)})
    # present but empty in substance
    pen = sections.get("bullpen", {}).get("values") or {}
    if pen and all(isinstance(v, Mapping) and not v.get("relievers") for v in pen.values()):
        missing.append({"item": "bullpen", "kind": "absent",
                        "reason": "no reliever appearances recorded for either club in the window"})
    trav = sections.get("travel", {}).get("values") or {}
    if trav and all(isinstance(v, Mapping) and v.get("miles") is None for v in trav.values()):
        missing.append({"item": "travel", "kind": "absent",
                        "reason": "no recent games to measure travel from for either club"})
    st = sections.get("starters", {}).get("values") or {}
    for side in ("away", "home"):
        if st and not st.get(f"{side}_sp_known"):
            missing.append({"item": f"starters.{side}", "kind": "absent",
                            "reason": f"the {side} probable starter has no stored pitching log"})
        elif st and st.get(f"{side}_sp_thin"):
            missing.append({"item": f"starters.{side}", "kind": "thin",
                            "reason": f"the {side} probable starter has a small sample"})
    teams = sections.get("teams", {}).get("values") or {}
    for side in ("away", "home"):
        if teams.get(f"{side}_sample_is_thin"):
            missing.append({"item": f"teams.{side}", "kind": "thin",
                            "reason": f"the {side} club has a small sample of games"})
    return sections, missing


# ---------------------------------------------------------------------------
# the packet
# ---------------------------------------------------------------------------

def _game_block(advanced: Mapping) -> dict:
    g = advanced.get("game") or {}
    return {
        "game_id": advanced.get("game_id"),
        "game_pk": g.get("game_pk"),
        "date": g.get("date"),
        "away": g.get("away_team") or advanced.get("away_team"),
        "home": g.get("home_team") or advanced.get("home_team"),
        "venue": g.get("venue"),
        "first_pitch_utc": g.get("start_time_utc"),
        "state": g.get("state"),
        "detailed_state": g.get("detailed_state"),
        "game_type": g.get("game_type"),
        "probables": {
            "away": {"name": g.get("away_probable")},
            "home": {"name": g.get("home_probable")},
        },
    }


def build_packet(payload: Mapping, *, built_at: str,
                 multibook_rows: Sequence[Mapping] = (),
                 team_total_rows: Sequence[Mapping] = (),
                 batter_prop_rows: Sequence[Mapping] = (),
                 pitcher_prop_rows: Sequence[Mapping] = (),
                 prop_board: Sequence[Mapping] = (),
                 team_names: Optional[Mapping] = None,
                 section_as_of: Optional[Mapping] = None,
                 cfg: Optional[Mapping] = None,
                 situation: Optional[Mapping] = None) -> dict:
    """One game's frozen fact packet. Deterministic in its arguments.

    `situation` (a `src.situation.mlb.situation_for_game` record) adds `sections.situation` and
    changes `packet_version`: that is arm B of the side-by-side test. Left None, nothing is added
    and the packet is exactly the one arm A has always had. Its holes stay in the section's own
    `missing`; the packet's top-level `missing` is the same in both arms.

    `payload` is what GET /game/{date}/{away}/{home} returns (or its
    `advanced` block alone). The row arguments are this game's rows from the
    price stores, unfiltered by time: this function applies the no-future rule
    itself. `team_names` is {"away": full club name, "home": full club name} as
    the price feed spells them (the team-total rows are keyed by it).
    """
    from src.analyst import config as config_mod

    cfg = dict(cfg) if cfg is not None else config_mod.DEFAULTS
    advanced = payload.get("advanced") if isinstance(payload.get("advanced"), Mapping) else payload
    game = _game_block(advanced)
    away, home = game["away"], game["home"]
    cutoff = _parse_utc(built_at)
    if cutoff is None:
        raise ValueError(f"built_at must be an ISO UTC time, got {built_at!r}")
    first_pitch = _parse_utc(game["first_pitch_utc"])
    names = dict(team_names or {})

    sections, missing = _sections(advanced, payload, dict(section_as_of or {}),
                                  str(game["date"] or ""))
    if situation is not None:
        sections["situation"] = _scrub(situation_record.packet_section(situation))

    markets: dict = {}
    rows = list(multibook_rows)
    for built in (_moneyline(rows, away, home, cutoff, first_pitch),
                  _run_line(rows, away, home, cutoff, first_pitch),
                  _total(rows, away, home, cutoff, first_pitch)):
        if built:
            markets[built["slot_id"]] = built
    markets.update(_team_totals(list(team_total_rows), away, home,
                                names.get("away"), names.get("home"), cutoff, first_pitch))

    stale_minutes = float(cfg.get("stale_quote_minutes", 180))
    for slot_id, label in (("moneyline", "moneyline"), ("run_line", "run line"),
                           ("total", "game total"), ("team_total_away", "away team total"),
                           ("team_total_home", "home team total")):
        market = markets.get(slot_id)
        if market is None:
            if slot_id.startswith("team_total"):
                if "team_totals" not in {m["item"] for m in missing}:
                    missing.append({"item": "team_totals", "kind": "absent",
                                    "reason": "no team-total prices were captured for this game"})
            else:
                missing.append({"item": slot_id, "kind": "absent",
                                "reason": f"no {label} prices were captured before this packet was built"})
            continue
        age = (cutoff - _parse_utc(market["as_of"])).total_seconds() / 60.0
        if age > stale_minutes:
            missing.append({"item": slot_id, "kind": "stale",
                            "reason": f"the newest {label} quote is {int(age)} minutes old"})

    groups = _prop_groups(batter_prop_rows, pitcher_prop_rows, cutoff, first_pitch)
    probables = [p for p in (game["probables"]["away"]["name"],
                             game["probables"]["home"]["name"]) if p]
    event_ids = {c.get("event_id") for c in prop_board if c.get("event_id")}
    board = [c for c in prop_board
             if not event_ids or c.get("event_id") in event_ids]
    keys = _select_props(groups, board, cap=int(cfg.get("max_props_per_game", 16)),
                         min_books=int(cfg.get("min_books_for_prop", 2)),
                         probables=probables)
    by_key: dict = {}
    for contract in board:
        k = (contract.get("player"), contract.get("market"), _clean_line(contract.get("line")))
        by_key.setdefault(k, contract)
    n = 0
    for key in keys:
        player, market, line = key
        contract = by_key.get(key)
        context = {}
        if contract:
            context = {k: v for k, v in {
                "repo_model_side": str(contract.get("side") or "").lower() or None,
                "repo_model_probability": contract.get("probability"),
                "repo_market_probability": contract.get("market_probability"),
                "season_rate": contract.get("season_rate"),
                "season_games": contract.get("season_games"),
                "expected_pa": contract.get("expected_pa"),
                "batting_slot": contract.get("batting_slot"),
            }.items() if v is not None}
        n += 1
        built = _prop_market(f"prop_{n:02d}", player, market, line, groups[key], context)
        if built:
            markets[built["slot_id"]] = built
        else:
            n -= 1
    priced = len([k for k in groups if groups[k]["over"]])
    analyzed = len([m for m in markets.values() if m["market"] == "prop"])
    if priced == 0:
        missing.append({"item": "props", "kind": "absent",
                        "reason": "no player-prop prices were captured for this game"})
    elif priced > analyzed:
        missing.append({"item": "props", "kind": "thin",
                        "reason": f"{priced} prop contracts were priced; {analyzed} are analyzed "
                                  "(the rest are left out by the per-game cap)"})

    prop_ages = [(cutoff - _parse_utc(m["as_of"])).total_seconds() / 60.0
                 for m in markets.values() if m["market"] == "prop" and m["as_of"]]
    if prop_ages and min(prop_ages) > stale_minutes:
        missing.append({"item": "prop_prices", "kind": "stale",
                        "reason": f"the newest player-prop quote is {int(min(prop_ages))} "
                                  "minutes old"})

    order = ["moneyline", "run_line", "total", "team_total_away", "team_total_home"]
    markets = {k: markets[k] for k in order if k in markets} | {
        k: v for k, v in sorted(markets.items()) if k.startswith("prop_")}
    missing = sorted({(m["item"], m["kind"], m["reason"]): m for m in missing}.values(),
                     key=lambda m: (m["item"], m["kind"], m["reason"]))

    return {
        "packet_version": PACKET_VERSION if situation is None else PACKET_VERSION_SITUATION,
        "built_at": _iso(cutoff),
        "game": game,
        "sections": sections,
        "markets": markets,
        "slots": [{"slot_id": sid, "market": m["market"], "label": m["label"],
                   "selections": [o["selection"] for o in m["options"]]}
                  for sid, m in markets.items()],
        "missing": missing,
        "limits": list(LIMITS),
    }


# ---------------------------------------------------------------------------
# lookups the critic and the ledger share
# ---------------------------------------------------------------------------

def slot(packet: Mapping, slot_id: str) -> Optional[Mapping]:
    return (packet.get("markets") or {}).get(slot_id)


def option(packet: Mapping, slot_id: str, selection: str) -> Optional[Mapping]:
    market = slot(packet, slot_id)
    for opt in (market or {}).get("options", []):
        if opt["selection"] == selection:
            return opt
    return None


def has_quote(packet: Mapping, slot_id: str, selection: str, book: Any, price: Any) -> bool:
    """True when `book` quoted exactly `price` on that selection in the packet."""
    opt = option(packet, slot_id, selection)
    if opt is None:
        return False
    return any(q["book"] == book and q["price"] == price for q in opt["quotes"])
