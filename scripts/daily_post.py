"""The day's honest public post, as plain text the owner pastes by hand into
X, Reddit or Discord. Deterministic: no model, no network, no clock except the
default `--date`.

    python scripts/daily_post.py --sport mlb --format both
    python scripts/daily_post.py --sport nfl --date 2026-09-27 --format long

LineHound publishes a card before the game and grades it in public. The
product has NOT shown an edge, so this text never implies one. Rules enforced
in code (not only in review):

- `x` is one post of at most 280 characters. If it cannot fit, `main` exits 2
  and prints why; nothing is ever cut mid-sentence. The builder first tries
  the version that lists tonight's entries, then a version that gives only
  the count; if neither fits it raises `PostError`.
- A banned-word scan (`check_text`) runs over the finished text. A hit is a
  `PostError` (exit 2), never a silent rewrite. The one allowed use of the
  word is the exact sentence "No edge is claimed."
- An entry priced at -200 or shorter is never shown, on the card or in the
  graded list; the count is stated instead.
- Fills are labelled as fills and are never added into the counted record.
  Postseason entries are labelled "postseason, graded, not counted".
- "No card published" (no input) and "nothing qualified" (a card was
  published and was empty) are different sentences.

Only `main()` touches the disk. Every builder takes its data as arguments, so
tests inject entries, graded rows and the record snapshot directly. Sourcing
is reused from `scripts/discord_feed.py` (frozen-card reader, entry wording,
record headline) and `src/report/effective_record.py` (record snapshot,
postseason test) -- imported, not copied. One deliberate difference: a prop's
wording here includes its Over/Under side, which `discord_feed._entry_sentence`
leaves out (the frozen row carries it; the feed's sentence does not).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Mapping, Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SPORTS = ("mlb", "nfl")
FORMATS = ("x", "long", "both")
X_LIMIT = 280
PRICE_CUTOFF = -200  # an entry priced at this or shorter is never shown
NO_EDGE = "No edge is claimed."
CLOSING_LINE = "No edge is claimed. 21+. Bet responsibly."
POSTSEASON_LABEL = "postseason, graded, not counted"

SECTION_PICK = "pick"
SECTION_FILL = "fill"
SECTION_POSTSEASON = "postseason"

# Whole words only, so a surname or "locked" in an unrelated sense does not
# trip it by accident; any real hit fails loudly rather than being reworded.
BANNED_PATTERNS = (
    ("edge", re.compile(r"\bedges?\b", re.I)),
    ("profit", re.compile(r"\bprofit(?:s|able|ably)?\b", re.I)),
    ("lock", re.compile(r"\block(?:s|ed|ing)?\b", re.I)),
    ("guaranteed", re.compile(r"\bguarantee(?:d|s)?\b", re.I)),
    ("sharp", re.compile(r"\bsharps?\b", re.I)),
    ("winning", re.compile(r"\bwinning\b", re.I)),
    ("Bet Check", re.compile(r"\bbet\s*check\b", re.I)),
)


class PostError(ValueError):
    """The post cannot be produced honestly (too long, or a banned word)."""


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def check_text(text: str) -> None:
    """Raise PostError if `text` contains a banned word. The exact sentence
    "No edge is claimed." is removed first; it is the only allowed use."""
    scrubbed = text.replace(NO_EDGE, "")
    hits = [label for label, pattern in BANNED_PATTERNS if pattern.search(scrubbed)]
    if hits:
        raise PostError("banned word(s) in post: " + ", ".join(hits))


def check_x_length(text: str) -> None:
    if len(text) > X_LIMIT:
        raise PostError(f"x post is {len(text)} characters; the limit is {X_LIMIT}")


def _is_hidden_price(price) -> bool:
    return price is not None and price <= PRICE_CUTOFF


def split_hidden(entries: Sequence[Mapping]) -> tuple:
    """(shown, n_hidden_by_price, n_unpriced). Hidden entries are dropped from
    everything below, including the W-L they would have contributed; the
    count is stated in the post. An entry with no price on record cannot be
    shown with its price, so it is held back and counted separately."""
    shown, hidden, unpriced = [], 0, 0
    for entry in entries:
        price = entry.get("price")
        if price is None:
            unpriced += 1
        elif _is_hidden_price(price):
            hidden += 1
        else:
            shown.append(entry)
    return shown, hidden, unpriced


def _not_shown_sentences(hidden: int, unpriced: int) -> list:
    out = []
    if hidden:
        noun = "entry" if hidden == 1 else "entries"
        out.append(f"{hidden} {noun} not shown (priced at -200 or shorter).")
    if unpriced:
        noun = "entry" if unpriced == 1 else "entries"
        out.append(f"{unpriced} {noun} not shown (no price on record).")
    return out


# ---------------------------------------------------------------------------
# Normalising ledger rows into small entry dicts (pure, no I/O)
# ---------------------------------------------------------------------------

def _price_text(price) -> str:
    return f"{int(round(price)):+d}"


def _strip_take(text: str) -> str:
    return text[5:] if text.lower().startswith("take ") else text


def _prop_text(entry: Mapping) -> str:
    market = str(entry.get("market") or "").replace("batter_", "").replace("_", " ")
    parts = [entry.get("player"), entry.get("side"), entry.get("line"), market]
    body = " ".join(str(p) for p in parts if p not in (None, ""))
    price = entry.get("price")
    return f"{body} at {_price_text(price)}" if price is not None else body


def entry_text(sport: str, entry: Mapping) -> str:
    """One line naming the bet, with its price. MLB games reuse
    `discord_feed._entry_sentence`; props add the side; NFL rows already
    carry a rendered `bet` sentence."""
    if sport == "mlb" and entry.get("kind") == "prop":
        text = _prop_text(entry)
    elif sport == "mlb":
        import scripts.discord_feed as discord_feed
        text = _strip_take(discord_feed._entry_sentence(sport, entry))
    else:
        text = _strip_take(entry.get("bet") or "")
        if not text and entry.get("kind") == "prop":
            text = _prop_text(entry)
    price = entry.get("price")
    if price is not None and _price_text(price) not in text:
        text = f"{text} at {_price_text(price)}".strip()
    return text


def _rank_key(entry: Mapping):
    rank = entry.get("rank")
    return rank if rank is not None else 10 ** 9


def card_entries(sport: str, frozen: Optional[Mapping]) -> Optional[dict]:
    """The published row reshaped to {"picks": [...], "fills": [...],
    "no_input": reason-or-None}, each entry {"text", "price"}; None when
    nothing is published. Withdrawn entries are never read."""
    if frozen is None:
        return None
    if sport == "mlb":
        rows = list(frozen.get("picks") or ()) + list(frozen.get("prop_picks") or ())
        rows.sort(key=_rank_key)
        fill_rows = list(frozen.get("fills") or ())
    else:
        rows = sorted(frozen.get("picks") or (), key=_rank_key)
        fill_rows = []

    def shape(row):
        return {"text": entry_text(sport, row), "price": row.get("price")}

    stale = frozen.get("stale_board")
    return {"picks": [shape(r) for r in rows],
            "fills": [shape(r) for r in fill_rows],
            "no_input": str(stale) if stale else None}


def graded_entries(sport: str, day: Optional[Mapping], postseason_pks: frozenset = frozenset()) -> list:
    """One settled day (card_ledger.history_v2 / history shape) reshaped to
    [{"text", "price", "result", "units", "section"}]. Withdrawn entries are
    skipped. MLB entries split into counted pick / fill / postseason using
    the same postseason test the record uses
    (`effective_record._is_postseason_entry`)."""
    if not day:
        return []
    if sport == "mlb":
        from src.report import effective_record
        rows = day.get("graded") or ()
    else:
        effective_record = None
        rows = list(day.get("picks") or ()) + list(day.get("prop_picks") or ())
    out = []
    for row in rows:
        if row.get("withdrawn"):
            continue
        if sport == "mlb" and effective_record._is_postseason_entry(row, postseason_pks):
            section = SECTION_POSTSEASON
        elif sport == "mlb" and row.get("entry_class") == "fill":
            section = SECTION_FILL
        else:
            section = SECTION_PICK
        out.append({"text": entry_text(sport, row), "price": row.get("price"),
                    "result": row.get("result"), "units": row.get("profit_units"),
                    "section": section})
    return out


# ---------------------------------------------------------------------------
# Formatting pieces
# ---------------------------------------------------------------------------

def _units(value) -> str:
    return "n/a" if value is None else f"{value:+.2f}u"


def tally(entries: Sequence[Mapping]) -> dict:
    wins = sum(1 for e in entries if e.get("result") == "WIN")
    losses = sum(1 for e in entries if e.get("result") == "LOSS")
    pushes = sum(1 for e in entries if e.get("result") == "PUSH")
    voids = sum(1 for e in entries if e.get("result") == "VOID")
    unresolved = sum(1 for e in entries if e.get("result") == "UNRESOLVED")
    units = sum((e.get("units") or 0.0) for e in entries if e.get("result") in ("WIN", "LOSS"))
    return {"wins": wins, "losses": losses, "pushes": pushes, "voids": voids,
            "unresolved": unresolved, "units": round(units, 4)}


def _tally_text(t: Mapping) -> str:
    text = f"{t['wins']}-{t['losses']}, {_units(t['units'])}"
    extras = [f"{t[k]} {k[:-1] if t[k] == 1 else k}" for k in ("pushes", "voids") if t[k]]
    if t["unresolved"]:
        extras.append(f"{t['unresolved']} unresolved")
    return text + (f" ({', '.join(extras)})" if extras else "")


def _sections(graded: Sequence[Mapping]) -> tuple:
    return tuple([e for e in graded if e.get("section") == s]
                 for s in (SECTION_PICK, SECTION_FILL, SECTION_POSTSEASON))


def _result_word(entry: Mapping) -> str:
    result = entry.get("result") or "UNGRADED"
    if result in ("WIN", "LOSS"):
        return f"{result} ({_units(entry.get('units'))})"
    return result


def record_headline(snapshot: Mapping) -> str:
    """Counted record for the CURRENT rule, exactly as the ledger reports it
    (negative stays negative); the cohort's own honest-absence reason when it
    has nothing graded. Reuses discord_feed's headline formatter."""
    import scripts.discord_feed as discord_feed
    current = (snapshot or {}).get("current") or {}
    return f"{current.get('label') or 'Current rule'}: {discord_feed._cohort_headline(current)}"


def record_short(snapshot: Mapping) -> str:
    import scripts.discord_feed as discord_feed
    current = (snapshot or {}).get("current") or {}
    if (current.get("available") and current.get("grading_state") == "graded"):
        nights = current.get("days") or 0
        word = "night" if nights == 1 else "nights"
        return (f"{current.get('wins')}-{current.get('losses')}, "
                f"{_units(current.get('profit_units'))}, {nights} {word}")
    return discord_feed._cohort_headline(current)


def postseason_record_line(snapshot: Mapping) -> Optional[str]:
    post = ((snapshot or {}).get("current") or {}).get("postseason") or {}
    if (post.get("n_staked") or 0) > 0:
        return f"Postseason: {post.get('wins')}-{post.get('losses')}, {POSTSEASON_LABEL}."
    return None


def _card_lines(card: Optional[Mapping], date: str) -> tuple:
    """(lines, n_hidden, n_unpriced, shown_picks, shown_fills)."""
    if card is None:
        return [f"No card published for {date}."], 0, 0, [], []
    picks, hp, up = split_hidden(card.get("picks") or ())
    fills, hf, uf = split_hidden(card.get("fills") or ())
    hidden, unpriced = hp + hf, up + uf
    lines = []
    if card.get("no_input") and not (card.get("picks") or card.get("fills")):
        lines.append(f"No usable odds input for {date} ({card['no_input']}); nothing was selected.")
    elif not (card.get("picks") or card.get("fills")):
        lines.append(f"Card published for {date}: nothing qualified.")
    else:
        if picks:
            lines += [f"{i}. {e['text']}" for i, e in enumerate(picks, 1)]
        elif card.get("picks"):
            lines.append("No picks to show.")
        else:
            lines.append(f"Card published for {date}: no picks qualified.")
        if fills:
            lines.append("Fills (not counted in the record):")
            lines += [f"- {e['text']}" for e in fills]
    return lines, hidden, unpriced, picks, fills


# ---------------------------------------------------------------------------
# Builders (pure)
# ---------------------------------------------------------------------------

def build_long(*, sport_label: str, date: str, prev_date: str,
               card: Optional[Mapping], graded: Sequence[Mapping],
               snapshot: Mapping) -> str:
    out = [f"LineHound {sport_label} card, {date}", ""]

    # Yesterday, graded.
    shown, g_hidden, g_unpriced = split_hidden(graded or ())
    picks, fills, post = _sections(shown)
    out.append(f"Yesterday ({prev_date}), graded:")
    if not (graded or ()):
        out.append(f"Nothing was graded for {prev_date}.")
    else:
        if picks:
            out.append(f"Counted picks: {_tally_text(tally(picks))}")
            out += [f"- {e['text']}: {_result_word(e)}" for e in picks]
        elif g_hidden or g_unpriced:
            out.append(f"No counted picks to show for {prev_date}.")
        else:
            out.append(f"No counted picks were graded for {prev_date}.")
        if fills:
            out.append(f"Fills, not counted: {_tally_text(tally(fills))}")
            out += [f"- {e['text']}: {_result_word(e)}" for e in fills]
        if post:
            out.append(f"Postseason ({POSTSEASON_LABEL}): {_tally_text(tally(post))}")
            out += [f"- {e['text']}: {_result_word(e)}" for e in post]
        out += _not_shown_sentences(g_hidden, g_unpriced)
    out.append("")

    # Tonight's card.
    card_lines, c_hidden, c_unpriced, _, _ = _card_lines(card, date)
    out.append(f"Tonight's card ({date}):")
    out += card_lines
    out += _not_shown_sentences(c_hidden, c_unpriced)
    out.append("")

    # Counted record.
    out.append("Counted record (current rule, regular season, fills excluded):")
    out.append(record_headline(snapshot))
    extra = postseason_record_line(snapshot)
    if extra:
        out.append(extra)
    out.append("")
    out.append(CLOSING_LINE)

    text = "\n".join(out)
    check_text(text)
    return text


def _x_yesterday(prev_date: str, graded: Sequence[Mapping]) -> tuple:
    shown, hidden, unpriced = split_hidden(graded or ())
    picks, _, _ = _sections(shown)
    if not (graded or ()):
        return f"Yesterday ({prev_date}): nothing was graded.", hidden, unpriced
    if picks:
        return f"Yesterday ({prev_date}): {_tally_text(tally(picks))}.", hidden, unpriced
    if hidden or unpriced:
        return f"Yesterday ({prev_date}): no counted picks to show.", hidden, unpriced
    return f"Yesterday ({prev_date}): no counted picks graded.", hidden, unpriced


def build_x_candidates(*, sport_label: str, date: str, prev_date: str,
                       card: Optional[Mapping], graded: Sequence[Mapping],
                       snapshot: Mapping) -> list:
    """Candidate X posts, most detailed first. All are honest; the shorter
    ones only drop the entry list for a count."""
    yesterday, g_hidden, g_unpriced = _x_yesterday(prev_date, graded)
    picks_all = (card or {}).get("picks") or ()
    fills_all = (card or {}).get("fills") or ()
    picks, hp, up = split_hidden(picks_all)
    fills, hf, uf = split_hidden(fills_all)
    hidden, unpriced = g_hidden + hp + hf, g_unpriced + up + uf
    fills_note = f" +{len(fills)} fill{'s' if len(fills) != 1 else ''}, not counted" if fills else ""

    if card is None:
        tonight_full = tonight_short = f"No card published for {date}."
    elif not (picks_all or fills_all):
        if card.get("no_input"):
            tonight_full = tonight_short = f"No usable odds input for {date}; nothing selected."
        else:
            tonight_full = tonight_short = f"Card published for {date}: nothing qualified."
    else:
        n = len(picks)
        tonight_short = (f"Tonight: {n} pick{'s' if n != 1 else ''}{fills_note}. "
                         "Full card in the longer post.")
        tonight_full = (("Tonight: " + "; ".join(e["text"] for e in picks) + fills_note + ".")
                        if picks else f"Tonight: no picks to show{fills_note}.")

    tail = " ".join(_not_shown_sentences(hidden, unpriced))
    record = f"Record, current rule: {record_short(snapshot)}."
    head = f"LineHound {sport_label} {date}"

    candidates = []
    for tonight in (tonight_full, tonight_short):
        lines = [head, tonight, yesterday, record]
        if tail:
            lines.append(tail)
        lines.append(CLOSING_LINE)
        candidates.append("\n".join(lines))
    return candidates


def build_x(**kwargs) -> str:
    """The first candidate that fits 280 characters, or PostError. Never a
    silent cut: a candidate is used whole or not at all."""
    candidates = build_x_candidates(**kwargs)
    for text in candidates:
        if len(text) <= X_LIMIT:
            check_text(text)
            return text
    check_x_length(candidates[-1])  # raises with the real length
    raise PostError("x post does not fit")  # unreachable; keeps the contract explicit


# ---------------------------------------------------------------------------
# Disk / CLI (the only I/O)
# ---------------------------------------------------------------------------

def _valid_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}, expected YYYY-MM-DD") from exc
    return value


def previous_date(date: str) -> str:
    return (datetime.strptime(date, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()


def load_inputs(sport: str, date: str) -> dict:
    """Read the frozen card, the previous day's graded row and the record
    snapshot from the real ledgers. Read-only; the only function here that
    touches the disk."""
    import scripts.discord_feed as discord_feed
    from src.appstate import card_ledger
    from src.report import effective_record

    prev = previous_date(date)
    frozen = discord_feed._frozen_card(sport, date)
    if sport == "mlb":
        history = card_ledger.history_v2(limit=None)
        postseason_pks = effective_record._postseason_game_pks()
    else:
        history = card_ledger.history(sport=sport, limit=None)
        postseason_pks = frozenset()
    day = next((d for d in history.get("days") or () if d.get("date") == prev), None)
    return {
        "sport_label": effective_record.SPORT_LABEL.get(sport, sport.upper()),
        "date": date, "prev_date": prev,
        "card": card_entries(sport, frozen),
        "graded": graded_entries(sport, day, postseason_pks),
        "snapshot": discord_feed._sport_snapshot(sport),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily_post.py",
        description="Print the day's honest public post for X / Reddit / Discord.")
    parser.add_argument("--sport", choices=SPORTS, default="mlb")
    parser.add_argument("--date", type=_valid_date, default=None,
                        help="YYYY-MM-DD, default: today")
    parser.add_argument("--format", choices=FORMATS, default="both", dest="fmt")
    return parser


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    date = args.date or date_cls.today().isoformat()
    try:
        inputs = load_inputs(args.sport, date)
        parts = []
        if args.fmt in ("x", "both"):
            parts.append(("x", build_x(**inputs)))
        if args.fmt in ("long", "both"):
            parts.append(("long", build_long(**inputs)))
    except PostError as exc:
        print(f"daily_post: refusing to print: {exc}", file=sys.stderr)
        return 2
    if len(parts) == 1:
        print(parts[0][1])
    else:
        for i, (name, text) in enumerate(parts):
            if i:
                print()
            suffix = f" ({len(text)}/{X_LIMIT} characters)" if name == "x" else ""
            print(f"===== {name}{suffix} =====")
            print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
