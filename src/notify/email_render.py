"""What LINEHOUND's three emails say. Pure functions: data in, ``{subject, preheader, html, text}`` out.

VOICE (docs/VOICE.md, amendment 2026-10-20). Sober and plain: short lines, bettor language (ticket, record,
units, bankroll), the words *hound* and *house pack*, no jokes, no emoji, no exclamation marks. A loss is written
exactly like a win: the same sentence shape, the same table, the same weight.

THE HARD LINES, each one pinned by tests/test_notify_email.py:
  * never a claim of profit, an edge or winning: a result is a record ("2-1"), a balance is "paper", and units
    are never called profit and never turned into dollars of winnings;
  * Bet Check is never mentioned or linked;
  * a ticket priced -200 or worse is never shown (``price_shown``): the product does not make those picks, and a
    row that somehow carried one is dropped here rather than printed;
  * every message ends with ``DISCLOSURE`` (21+, paper bets only, not advice, 1-800-GAMBLER with a tel: link),
    the unsubscribe link, and the owner's postal address when config/business.json has one (never invented).

Inline styles and table layout only: mail clients ignore everything else. Every interpolated value is HTML-escaped.
"""

from __future__ import annotations

from html import escape
from typing import Mapping, Optional, Sequence

CAP_AMERICAN = -200               # a price at or below this is never shown (owner ruling 2026-09-22)
HOTLINE_TEL = "tel:+18004262537"  # 1-800-GAMBLER
DISCLOSURE = "21+ · Paper bets only, not advice · 1-800-GAMBLER"
START_USD = 1000.0                # config/bankroll.json starting_bankroll; callers pass the live value

_INK = "#0B0C0E"
_ACCENT = "#0090C8"
_MUTE = "#5B6472"
_RULE = "#E2E5EA"
_FONT = "-apple-system,Segoe UI,Helvetica,Arial,sans-serif"


# ---------------------------------------------------------------------------
# small formatters
# ---------------------------------------------------------------------------

def usd(value: float) -> str:
    return f"${value:,.0f}" if abs(value - round(value)) < 1e-9 else f"${value:,.2f}"


def units(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:+.2f}u"


def american(price) -> str:
    try:
        p = int(round(float(price)))
    except (TypeError, ValueError):
        return "n/a"
    return f"+{p}" if p > 0 else str(p)


def price_shown(price) -> bool:
    """False for a price of -200 or worse, and for a price that is not a number."""
    try:
        return float(price) > CAP_AMERICAN
    except (TypeError, ValueError):
        return False


def record(w: int, l: int, p: int = 0) -> str:
    return f"{w}-{l}-{p}" if p else f"{w}-{l}"


_RESULT_WORD = {"WIN": "WON", "LOSS": "LOST", "PUSH": "PUSH", "VOID": "VOID"}
_MARKET_WORD = {"moneyline": "Moneyline", "spread": "Spread", "run_line": "Run line", "total": "Total"}


def market_word(market: str, sport: str = "") -> str:
    if market == "spread" and str(sport).upper() == "MLB":
        return "Run line"
    if market in _MARKET_WORD:
        return _MARKET_WORD[market]
    return str(market or "").replace("_", " ").title()


def _one_line(text: object) -> str:
    return " ".join(str(text or "").split())


def _number_word(n: int) -> str:
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    return words[n] if 0 <= n < len(words) else str(n)


# ---------------------------------------------------------------------------
# the shell every message shares
# ---------------------------------------------------------------------------

def _button(label: str, href: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 4px">'
            f'<tr><td style="background:{_ACCENT};border-radius:4px">'
            f'<a href="{escape(href, quote=True)}" style="display:inline-block;padding:11px 20px;'
            f'font:600 15px {_FONT};color:#FFFFFF;text-decoration:none">{escape(label)}</a>'
            f'</td></tr></table>')


def _footer_html(unsubscribe_url: str, address: Optional[str], reason: str) -> str:
    addr = (f'<p style="margin:8px 0 0">{escape(address)}</p>' if address else "")
    return (f'<tr><td style="padding:18px 28px 26px;border-top:1px solid {_RULE};'
            f'font:13px/1.5 {_FONT};color:{_MUTE}">'
            f'<p style="margin:0">21+ · Paper bets only, not advice · '
            f'<a href="{HOTLINE_TEL}" style="color:{_MUTE}">1-800-GAMBLER</a></p>'
            f'<p style="margin:8px 0 0">{escape(reason)} '
            f'<a href="{escape(unsubscribe_url, quote=True)}" style="color:{_MUTE}">Pause these emails</a>.</p>'
            f'{addr}</td></tr>')


def _shell(preheader: str, body_html: str, footer_html: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"></head>'
        '<body style="margin:0;padding:0;background:#F3F4F6">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(preheader)}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F3F4F6">'
        '<tr><td align="center" style="padding:20px 10px">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" '
        'style="width:100%;max-width:560px;background:#FFFFFF;border-radius:6px;overflow:hidden">'
        f'<tr><td style="background:{_INK};padding:16px 28px;font:700 15px {_FONT};'
        f'letter-spacing:.14em;color:#FFFFFF">LINE<span style="color:#00E0FF">HOUND</span></td></tr>'
        f'<tr><td style="padding:24px 28px 8px;font:15px/1.55 {_FONT};color:{_INK}">{body_html}</td></tr>'
        f'{footer_html}</table></td></tr></table></body></html>')


def _footer_text(unsubscribe_url: str, address: Optional[str], reason: str) -> str:
    lines = ["", "--", f"{DISCLOSURE} (tel: +1 800 426 2537)", f"{reason} Pause these emails: {unsubscribe_url}"]
    if address:
        lines.append(address)
    return "\n".join(lines)


def _headline(text: str) -> str:
    return f'<h1 style="margin:0 0 10px;font:700 21px/1.3 {_FONT};color:{_INK}">{escape(text)}</h1>'


def _para(text: str) -> str:
    return f'<p style="margin:0 0 12px">{escape(text)}</p>'


def _finish(subject: str, preheader: str, body_html: str, body_text: str, *, unsubscribe_url: str,
            address: Optional[str], reason: str, to: str) -> dict:
    return {
        "to": to, "subject": _one_line(subject), "preheader": preheader,
        "html": _shell(preheader, body_html, _footer_html(unsubscribe_url, address, reason)),
        "text": body_text.rstrip() + "\n" + _footer_text(unsubscribe_url, address, reason) + "\n",
        # RFC 8058 one-click: a mail client's own "Unsubscribe" button POSTs to the same signed link.
        "headers": {"List-Unsubscribe": f"<{unsubscribe_url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
    }


# ---------------------------------------------------------------------------
# (a) Keep confirmation
# ---------------------------------------------------------------------------

def keep_confirmation(*, to: str, dog_name: str, dog_url: str, unsubscribe_url: str,
                      address: Optional[str] = None) -> dict:
    name = _one_line(dog_name)
    subject = f"{name} is in."
    pre = "First slate tonight. We'll email you the result when it's graded."
    reason = "You are getting this because you kept a hound on LINEHOUND."
    body = (_headline(f"{name} is in.")
            + _para(f"You kept {name}. Its record starts now, and every ticket it makes goes on the public "
                    "record before the game.")
            + f'<p style="margin:16px 0 4px;font-weight:700">What happens tonight</p>'
            + _para(f"If {name}'s rule finds a bet on tonight's slate, it records a paper ticket before the game "
                    "starts. If nothing fits, it sits out. Paper bets only.")
            + _para("When a ticket is graded you get one email with every result. If none of your hounds' tickets "
                    "settle on a day, you hear nothing. A loss is written up the same way as a win.")
            + _button(f"See {name}'s page", dog_url))
    text = "\n".join([
        f"{name} is in.", "",
        f"You kept {name}. Its record starts now, and every ticket it makes goes on the public record before "
        "the game.", "",
        "What happens tonight",
        f"If {name}'s rule finds a bet on tonight's slate, it records a paper ticket before the game starts. "
        "If nothing fits, it sits out. Paper bets only.",
        "When a ticket is graded you get one email with every result. If none of your hounds' tickets settle on "
        "a day, you hear nothing. A loss is written up the same way as a win.", "",
        f"See {name}'s page: {dog_url}"])
    return _finish(subject, pre, body, text, unsubscribe_url=unsubscribe_url, address=address, reason=reason, to=to)


# ---------------------------------------------------------------------------
# (b) nightly result
# ---------------------------------------------------------------------------
#
# A dog block:  {"id", "name", "url", "tickets": [Ticket], "season": {"w","l","p"}, "bankroll": float}
# A Ticket:     {"selection", "market", "sport", "game", "price", "result", "units"}

def _dog_counts(dog: Mapping) -> tuple:
    shown = [t for t in dog["tickets"] if t["result"] in ("WIN", "LOSS", "PUSH")]
    w = sum(1 for t in shown if t["result"] == "WIN")
    l = sum(1 for t in shown if t["result"] == "LOSS")
    p = sum(1 for t in shown if t["result"] == "PUSH")
    return w, l, p


def _ticket_rows_html(tickets: Sequence[Mapping]) -> str:
    head = "".join(f'<th align="{a}" style="padding:6px 8px;font:600 12px {_FONT};color:{_MUTE};'
                   f'border-bottom:1px solid {_RULE};text-align:{a}">{h}</th>'
                   for h, a in (("Ticket", "left"), ("Price", "right"), ("Result", "left"), ("Units", "right")))
    rows = []
    for t in tickets:
        cell = f'style="padding:8px;border-bottom:1px solid {_RULE};font:14px/1.4 {_FONT};color:{_INK}'
        game = (f'<br><span style="color:{_MUTE};font-size:12px">{escape(_one_line(t.get("game")))}</span>'
                if t.get("game") else "")
        rows.append(
            f'<tr><td {cell}">{escape(_one_line(t["selection"]))} '
            f'<span style="color:{_MUTE}">· {escape(market_word(t["market"], t.get("sport", "")))}</span>{game}</td>'
            f'<td {cell};text-align:right;white-space:nowrap">{escape(american(t["price"]))}</td>'
            f'<td {cell};white-space:nowrap">{_RESULT_WORD.get(t["result"], escape(str(t["result"])))}</td>'
            f'<td {cell};text-align:right;white-space:nowrap">{escape(units(t.get("units")))}</td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin:6px 0 10px;border-collapse:collapse"><tr>{head}</tr>{"".join(rows)}</table>')


def _season_line(dog: Mapping, start: float) -> str:
    s = dog["season"]
    bets = s["w"] + s["l"] + s["p"]
    return (f"Record {record(s['w'], s['l'], s['p'])} over {bets} bets. "
            f"Bankroll {usd(dog['bankroll'])} paper (started at {usd(start)}).")


def nightly_result(*, to: str, dogs: Sequence[Mapping], unsubscribe_url: str, kennel_url: str,
                   address: Optional[str] = None, start_usd: float = START_USD) -> dict:
    """One message per user per day. ``dogs`` holds only dogs that had a ticket graded, each with its tickets
    already filtered by ``price_shown``; the caller sends nothing when no dog has a win, loss or push."""
    dogs = [d for d in dogs if _dog_counts(d) != (0, 0, 0)]
    if not dogs:
        raise ValueError("nightly_result needs at least one dog with a graded win, loss or push")
    tw = sum(_dog_counts(d)[0] for d in dogs)
    tl = sum(_dog_counts(d)[1] for d in dogs)
    tp = sum(_dog_counts(d)[2] for d in dogs)
    graded = tw + tl + tp
    ticket_word = "ticket" if graded == 1 else "tickets"
    if len(dogs) == 1:
        name = _one_line(dogs[0]["name"])
        subject = f"{name} went {record(tw, tl, tp)} last night"
        pre = f"{_number_word(graded).capitalize()} {ticket_word} graded. Bankroll {usd(dogs[0]['bankroll'])} paper."
        button_label, button_url = "See every ticket", dogs[0]["url"]
    else:
        subject = f"Your hounds went {record(tw, tl, tp)} last night"
        pre = f"{_number_word(graded).capitalize()} {ticket_word} graded across {len(dogs)} hounds."
        button_label, button_url = "See every ticket", kennel_url
    body = ""
    text_lines = []
    for index, dog in enumerate(dogs):
        w, l, p = _dog_counts(dog)
        name = _one_line(dog["name"])
        line = f"{name} went {record(w, l, p)} last night."
        body += (_headline(line) if index == 0 and len(dogs) == 1
                 else f'<p style="margin:{"0" if index == 0 else "22px"} 0 2px;font:700 17px {_FONT}">'
                      f'{escape(line)}</p>')
        body += _ticket_rows_html([t for t in dog["tickets"]])
        body += f'<p style="margin:0 0 6px;color:{_MUTE};font-size:14px">{escape(_season_line(dog, start_usd))}</p>'
        text_lines += [line, ""]
        for t in dog["tickets"]:
            text_lines.append(
                f"  {_RESULT_WORD.get(t['result'], t['result']):<5} {_one_line(t['selection'])} "
                f"({market_word(t['market'], t.get('sport', ''))}) {american(t['price'])}  {units(t.get('units'))}")
        text_lines += ["", _season_line(dog, start_usd), ""]
    body += _button(button_label, button_url)
    text_lines.append(f"{button_label}: {button_url}")
    reason = "You are getting this because a ticket from one of your hounds was graded."
    return _finish(subject, pre, body, "\n".join(text_lines), unsubscribe_url=unsubscribe_url,
                   address=address, reason=reason, to=to)


# ---------------------------------------------------------------------------
# (c) Sunday pack
# ---------------------------------------------------------------------------
#
# A dog block:   {"id", "name", "url", "week": {"w","l","p","units"}, "season": {"w","l","p"}, "bankroll"}
# A house row:   {"name", "url", "w", "l", "p", "bankroll"}

def sunday_pack(*, to: str, dogs: Sequence[Mapping], house_top: Optional[Sequence[Mapping]],
                unsubscribe_url: str, leaderboard_url: str, address: Optional[str] = None,
                start_usd: float = START_USD) -> dict:
    if not dogs:
        raise ValueError("sunday_pack needs at least one dog")
    tw = sum(d["week"]["w"] for d in dogs)
    tl = sum(d["week"]["l"] for d in dogs)
    tp = sum(d["week"]["p"] for d in dogs)
    if tw + tl + tp == 0:
        subject = "Sunday pack: no tickets settled this week"
    elif len(dogs) == 1:
        subject = f"{_one_line(dogs[0]['name'])}'s week: {record(tw, tl, tp)}"
    else:
        subject = f"Your hounds' week: {record(tw, tl, tp)}"
    pre = "Your week, and the house pack's top three by paper bankroll."
    body = _headline("Your week")
    text = ["Your week", ""]
    for dog in dogs:
        wk, name = dog["week"], _one_line(dog["name"])
        n = wk["w"] + wk["l"] + wk["p"]
        if n:
            week_line = f"{name}: {record(wk['w'], wk['l'], wk['p'])} this week over {n} bets, {units(wk.get('units'))}."
        else:
            week_line = f"{name}: no tickets settled this week."
        body += (f'<p style="margin:0 0 2px;font:700 16px {_FONT}">{escape(week_line)}</p>'
                 f'<p style="margin:0 0 14px;color:{_MUTE};font-size:14px">{escape(_season_line(dog, start_usd))}</p>')
        text += [week_line, _season_line(dog, start_usd), ""]
    if house_top:
        body += f'<p style="margin:20px 0 4px;font:700 16px {_FONT}">House pack, top three by paper bankroll</p>'
        rows = ""
        text += ["House pack, top three by paper bankroll"]
        for rank, row in enumerate(house_top[:3], start=1):
            bets = row["w"] + row["l"] + row["p"]
            cell = f'style="padding:8px;border-bottom:1px solid {_RULE};font:14px/1.4 {_FONT};color:{_INK}'
            rows += (f'<tr><td {cell};width:24px">{rank}</td>'
                     f'<td {cell}">{escape(_one_line(row["name"]))}</td>'
                     f'<td {cell};text-align:right;white-space:nowrap">'
                     f'{escape(record(row["w"], row["l"], row["p"]))} over {bets}</td>'
                     f'<td {cell};text-align:right;white-space:nowrap">{escape(usd(row["bankroll"]))}</td></tr>')
            text.append(f"  {rank}. {_one_line(row['name'])}  {record(row['w'], row['l'], row['p'])} over {bets} bets  "
                        f"{usd(row['bankroll'])} paper")
        body += (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                 f'style="border-collapse:collapse">{rows}</table>'
                 f'<p style="margin:8px 0 0;color:{_MUTE};font-size:13px">Ranked by paper bankroll with at least 20 '
                 f'settled bets. Every hound starts at {escape(usd(start_usd))}. Past results are not a forecast.</p>')
        text += ["", f"Ranked by paper bankroll with at least 20 settled bets. Every hound starts at "
                     f"{usd(start_usd)}. Past results are not a forecast.", ""]
    body += _button("See the leaderboard", leaderboard_url)
    text.append(f"See the leaderboard: {leaderboard_url}")
    reason = "You are getting this because you keep a hound on LINEHOUND."
    return _finish(subject, pre, body, "\n".join(text), unsubscribe_url=unsubscribe_url,
                   address=address, reason=reason, to=to)


# ---------------------------------------------------------------------------
# admin test
# ---------------------------------------------------------------------------

def admin_test_message(*, to: str, unsubscribe_url: str, address: Optional[str] = None) -> dict:
    body = (_headline("Test email") + _para("This is a test message from LINEHOUND. If you can read it, sending "
                                             "works and the domain is verified."))
    text = "Test email\n\nThis is a test message from LINEHOUND. If you can read it, sending works and the domain is verified."
    return _finish("LINEHOUND test email", "Sending works.", body, text, unsubscribe_url=unsubscribe_url,
                   address=address, reason="This was sent from the LINEHOUND admin page.", to=to)
