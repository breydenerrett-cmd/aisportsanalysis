"""What a bet alert says, per channel. Pure functions: events + the member's sizing in, text out.

THE RULES (same hard lines as email_render.py, pinned by tests/test_bet_alerts.py):
  * an alert REPORTS a bet the hound made. It never recommends one, never says a bet is good, and never claims
    profit or an edge; a result is "won/lost/pushed" and a P&L is a paper figure at the member's own unit size;
  * the stake and the P&L are shown at the member's sizing (src/hounds/unit_size.py). A FIXED unit prices exactly
    (units x unit dollars). A PERCENT sizing compounds off a balance this module cannot see per bet, so it is
    shown against the starting bankroll with a leading "~" and the sizing words, never as an exact figure;
  * Bet Check is never mentioned; a price of -200 or worse is never shown;
  * every email ends with the 21+ / paper / 1-800-GAMBLER line, a link to the hound page and a one-click link
    that turns these alerts off. Every interpolated value is escaped for the medium it lands in.
"""

from __future__ import annotations

from datetime import timezone
from html import escape
from typing import Mapping, Optional, Sequence

from src.notify import email_render as er
from src.notify.alerts import parse_iso

MAX_LINES_IN_PUSH = 3
SMS_MAX = 300                  # two segments; a longer burst is summarised with a count and a link


def _zone(name: str):
    from src.notify import alerts
    return alerts.zone(name or alerts.DEFAULT_TZ) or timezone.utc


def start_text(value, tz: str) -> str:
    moment = parse_iso(value)
    if moment is None:
        return ""
    local = moment.astimezone(_zone(tz))
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.strftime('%a')} {hour}:{local.strftime('%M %p')} {local.tzname() or ''}".strip()


def dollars(units: Optional[float], sizing, *, signed: bool = False) -> str:
    """The member's dollars for ``units``. Fixed: exact. Percent: '~' against the starting bankroll. None: 'n/a'."""
    if units is None or sizing is None:
        return "n/a"
    if sizing.mode == "fixed":
        value, mark = units * float(sizing.unit_usd), ""
    else:
        value, mark = units * float(sizing.pct) / 100.0 * float(sizing.start_usd), "~"
    sign = ("+" if value >= 0 else "-") if signed else ("-" if value < 0 else "")
    return f"{mark}{sign}{er.usd(abs(value))}"


def sizing_words(sizing) -> str:
    if sizing is None:
        return ""
    if sizing.mode == "fixed":
        return f"at your ${sizing.unit_usd:g} unit"
    return f"at {sizing.pct:g}% of a ${sizing.start_usd:,.0f} starting bankroll"


def pick_text(payload: Mapping) -> str:
    """'Atlanta Hawks ML +110': the selection with its price."""
    selection = er._one_line(payload.get("selection"))
    if payload.get("market") == "moneyline" and selection.endswith(" to win"):
        selection = selection[: -len(" to win")] + " ML"
    price = er.american(payload.get("price")) if er.price_shown(payload.get("price")) else ""
    return f"{selection} {price}".strip()


def game_text(payload: Mapping) -> str:
    away, home = payload.get("away_team"), payload.get("home_team")
    return f"{away} at {home}" if away and home else ""


def result_word(result: str) -> str:
    return {"win": "won", "loss": "lost", "push": "pushed"}.get(result, str(result))


def event_line(event: Mapping, sizing, tz: str = "America/New_York") -> str:
    """One plain line for one event, used by every channel."""
    p = event["payload"]
    pick = pick_text(p)
    if event["kind"] == "placed":
        bits = [f"{p['hound_name']} bet {pick}", f"stake {dollars(p.get('stake_units'), sizing)}"]
        start = start_text(p.get("start_utc"), tz)
        if start:
            bits.append(f"starts {start}")
        return " · ".join(bits)
    pnl = dollars(p.get("profit_units"), sizing, signed=True)
    return f"{p['hound_name']}: {pick} {result_word(p.get('result'))} ({pnl})"


def subject(events: Sequence[Mapping]) -> str:
    first = events[0]
    p = first["payload"]
    if len(events) == 1:
        if first["kind"] == "placed":
            return er._one_line(f"{p['hound_name']} just bet: {pick_text(p)}")
        return er._one_line(f"{p['hound_name']} {result_word(p.get('result'))}: {pick_text(p)}")
    names = sorted({e["payload"]["hound_name"] for e in events})
    who = names[0] if len(names) == 1 else f"{len(names)} hounds"
    return er._one_line(f"{who}: {len(events)} new bet updates")


def hound_link(hound_id: str, env=None) -> str:
    from src.notify import email_prefs as prefs
    return prefs.dog_url(hound_id, "alert", env=env)


def email_message(*, to: str, events: Sequence[Mapping], sizing, tz: str, off_url: str, settings_url: str,
                  env=None, address: Optional[str] = None) -> dict:
    """The one alert email: a plain list of what happened, a link per hound, the disclosure line."""
    head = subject(events)
    rows_html, rows_text = [], []
    for e in events:
        p = e["payload"]
        line = event_line(e, sizing, tz)
        url = hound_link(p["hound_id"], env)
        game = game_text(p)
        rows_html.append(
            f'<p style="margin:0 0 14px"><strong>{escape(line)}</strong>'
            + (f'<br><span style="color:#5B6472">{escape(game)}</span>' if game else "")
            + f'<br><a href="{escape(url, quote=True)}" style="color:#0090C8">{escape(p["hound_name"])} page</a></p>')
        rows_text.append(f"{line}\n{game}\n{url}" if game else f"{line}\n{url}")
    words = sizing_words(sizing)
    note = f"Paper bets. Dollars shown {words}." if words else "Paper bets."
    body_html = (er._headline(head) + "".join(rows_html)
                 + f'<p style="margin:0 0 6px;color:#5B6472;font-size:13px">{escape(note)} '
                   f'<a href="{escape(settings_url, quote=True)}" style="color:#5B6472">Alert settings</a></p>')
    body_text = head + "\n\n" + "\n\n".join(rows_text) + f"\n\n{note}\nAlert settings: {settings_url}"
    return er._finish(head, head, body_html, body_text, unsubscribe_url=off_url, address=address,
                      reason="You asked for bet alerts.", to=to)


def push_payload(events: Sequence[Mapping], sizing, tz: str, env=None) -> dict:
    lines = [event_line(e, sizing, tz) for e in events[:MAX_LINES_IN_PUSH]]
    if len(events) > MAX_LINES_IN_PUSH:
        lines.append(f"and {len(events) - MAX_LINES_IN_PUSH} more")
    first = events[0]["payload"]
    return {"title": subject(events), "body": "\n".join(lines),
            "url": hound_link(first["hound_id"], env), "tag": "bet-alert", "paper": True}


def sms_text(events: Sequence[Mapping], sizing, tz: str, env=None) -> str:
    lines = [event_line(e, sizing, tz) for e in events[:3]]
    if len(events) > 3:
        lines.append(f"+{len(events) - 3} more")
    text = "LINEHOUND (paper): " + " | ".join(lines)
    link = hound_link(events[0]["payload"]["hound_id"], env).split("?")[0]
    tail = f" {link} Reply STOP to end."
    return text[: max(0, SMS_MAX - len(tail))] + tail


def sample_message(*, to: str, off_url: str, settings_url: str, address: Optional[str] = None) -> dict:
    head = "Test alert from LINEHOUND"
    body_html = (er._headline(head) + er._para("This is a test. Real alerts look like this one, with a hound, a pick, "
                                               "a price and your stake. No bet was made.")
                 + f'<p style="margin:0"><a href="{escape(settings_url, quote=True)}" style="color:#0090C8">Alert settings</a></p>')
    body_text = f"{head}\n\nThis is a test. No bet was made.\nAlert settings: {settings_url}"
    return er._finish(head, head, body_html, body_text, unsubscribe_url=off_url, address=address,
                      reason="You asked for bet alerts.", to=to)
