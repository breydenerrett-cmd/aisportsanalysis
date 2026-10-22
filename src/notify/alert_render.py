"""What a bet alert says, per channel. Pure functions: events + the member's sizing in, text out.

THE RULES (same hard lines as email_render.py, pinned by tests/test_bet_alerts.py):
  * an alert REPORTS a bet the hound made. It never recommends one, never says a bet is good, and never claims
    profit or an edge; a result is "won/lost/pushed" and a P&L is a paper figure at the member's own unit size;
  * the stake and the P&L are shown at the member's sizing (src/hounds/unit_size.py). A FIXED unit prices exactly
    (units x unit dollars). A PERCENT sizing compounds off a balance this module cannot see per bet, so it is
    shown against the starting bankroll with a leading "~" and the sizing words, never as an exact figure;
  * Bet Check is never mentioned; a price of -200 or worse is never shown;
  * every email ends with the 21+ / paper / 1-800-GAMBLER line, a link to the hound page and a one-click link
    that turns these alerts off. Every interpolated value is escaped for the medium it lands in;
  * "starting soon" and "live update" (alert_live.py) say where the game is and whether the ticket is winning or losing
    RIGHT NOW. That is the score, not a forecast: nothing says a bet will win, and the final update says grading is next
    rather than naming a result (the settled alert does that);
  * a text keeps to ONE 160-character segment where it can: the link goes first, then extra lines, then the hound's
    wording is clipped. "Reply STOP to end." and the "(paper)" mark are never the ones dropped.
"""

from __future__ import annotations

import unicodedata
from datetime import timezone
from html import escape
from typing import Mapping, Optional, Sequence

from src.notify import email_render as er
from src.notify.alerts import SHORT_LIVED_KINDS, parse_iso

MAX_LINES_IN_PUSH = 3
SMS_MAX = 300                  # two segments; a longer burst is summarised with a count and a link
SMS_ONE_SEGMENT = 160          # one GSM-7 segment; what a text tries to fit before it spends a second
SMS_PREFIX = "LINEHOUND (paper): "
SMS_STOP = "Reply STOP to end."

#: how a game starts, by family, for "<hound>'s <pick> <phrase> in 15 min"
START_PHRASE = {"NBA": "tips off", "WNBA": "tips off", "NCAAB": "tips off", "NHL": "puck drops", "NFL": "kicks off",
                "NCAAF": "kicks off", "SOCCER": "kicks off", "MLB": "has first pitch"}
DEFAULT_START_PHRASE = "starts"
#: two-word nicknames, so "Boston Red Sox" is "Red Sox" and not "Sox"
_TWO_WORD_NICKNAMES = frozenset({"red sox", "white sox", "blue jays", "trail blazers", "maple leafs", "golden knights",
                                 "blue jackets", "red wings", "timber wolves"})


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


def short_team(name) -> str:
    """'Atlanta Hawks' -> 'Hawks'; 'Boston Red Sox' -> 'Red Sox'. A name with one word is returned as is."""
    words = er._one_line(name).split()
    if len(words) < 2:
        return " ".join(words)
    if " ".join(words[-2:]).lower() in _TWO_WORD_NICKNAMES:
        return " ".join(words[-2:])
    return words[-1]


def _score_number(value) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "?"


def score_text(payload: Mapping) -> str:
    """'Hawks 54, Celtics 50': the leader first, a tie in home-away order. Empty when the score is not known."""
    home, away = payload.get("home_score"), payload.get("away_score")
    try:
        h, a = float(home), float(away)
    except (TypeError, ValueError):
        return ""
    pair = [(short_team(payload.get("home_team")), home, h), (short_team(payload.get("away_team")), away, a)]
    if a > h:
        pair.reverse()
    return ", ".join(f"{team} {_score_number(value)}" for team, value, _ in pair)


def status_word(payload: Mapping) -> str:
    """Where the ticket stands at this score, in the member's words; '' when it has no position (a prop)."""
    status = payload.get("status")
    if status in ("winning", "losing"):
        return status
    if status == "push":
        return "tied" if payload.get("market") == "moneyline" else "on the number"
    return ""


def start_phrase(payload: Mapping) -> str:
    phrase = START_PHRASE.get(str(payload.get("sport") or "").upper(), DEFAULT_START_PHRASE)
    minutes = payload.get("minutes_out")
    return f"{phrase} in {int(minutes)} min" if isinstance(minutes, (int, float)) else f"{phrase} soon"


def live_line(p: Mapping) -> str:
    """One line for a live update: what happened, the score, and the ticket's position."""
    pick = pick_text(p)
    who = f"{p['hound_name']}'s {pick}"
    score, word, label = score_text(p), status_word(p), er._one_line(p.get("label"))
    moment = str(p.get("moment") or "")
    where = f" ({label})" if label else ""
    if moment == "final":
        tail = f"{who} is {word}; grading next." if word else "Grading next."
        return f"Final: {score}. {tail}" if score else tail
    if moment.startswith("flip"):
        return f"Lead change: {who} is now {word or 'on the move'}. {score}{where}".strip()
    if moment == "half":
        head = (label or "Halfway") + (f": {score}." if score else ".")
        return f"{head} {who} is {word}." if word else f"{head} {who}."
    base = f"{who} is live" + (f": {score}" if score else "")
    return base + (f", {word}" if word and score else "")


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
    if event["kind"] == "starting":
        return f"{p['hound_name']}'s {pick} {start_phrase(p)} · stake {dollars(p.get('stake_units'), sizing)}"
    if event["kind"] == "live":
        return live_line(p)
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
        if first["kind"] == "starting":
            return er._one_line(f"{p['hound_name']}'s {pick_text(p)} {start_phrase(p)}")
        if first["kind"] == "live":
            return er._one_line(live_line(p))
        return er._one_line(f"{p['hound_name']} {result_word(p.get('result'))}: {pick_text(p)}")
    names = sorted({e["payload"]["hound_name"] for e in events})
    who = names[0] if len(names) == 1 else f"{len(names)} hounds"
    kinds = {e["kind"] for e in events}
    if kinds == {"starting"}:
        return er._one_line(f"{who}: {len(events)} bets start soon")
    if kinds == {"live"}:
        return er._one_line(f"{who}: {len(events)} live updates")
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
    kinds = {e["kind"] for e in events}
    # A starting / live notification gets its own tag so it replaces its own kind on the lock screen, never a "bet settled".
    tag = f"bet-alert-{next(iter(kinds))}" if len(kinds) == 1 and kinds <= set(SHORT_LIVED_KINDS) else "bet-alert"
    return {"title": subject(events), "body": "\n".join(lines),
            "url": hound_link(first["hound_id"], env), "tag": tag, "paper": True}


#: characters NFKD does not fold to ASCII on its own
_ASCII_FOLD = {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u00df": "ss",
               "\u00e6": "ae", "\u00c6": "AE", "\u00f8": "o", "\u00d8": "O", "\u0142": "l", "\u0141": "L", "\u0111": "d",
               "\u0110": "D", "\u0131": "i", "\u00a0": " "}


def _gsm(text: str) -> str:
    """Plain ASCII for a text. The middle dot the lines use is not in the GSM-7 alphabet, and neither is a team or player
    name like "Besiktas" spelled with its cedilla or "Lodz" with its stroke: ONE such character turns the whole text into
    70-character UCS-2 segments, so a 160-character message would be billed and delivered as three. Accents fold to
    their letter; anything with no ASCII form becomes "?"."""
    text = text.replace(" \u00b7 ", ", ").replace("\u00b7", "-")
    if text.isascii():
        return text
    out = []
    for char in text:
        char = _ASCII_FOLD.get(char, char)
        if not char.isascii():
            char = "".join(c for c in unicodedata.normalize("NFKD", char) if c.isascii()) or "?"
        out.append(char)
    return "".join(out)


def _fit_one_segment(lines: Sequence[str], n_events: int, link: str) -> Optional[str]:
    """The fullest wording that fits one segment, or None. Tried in order: every line with the link; every line; the
    first line and a count; the first line clipped. The STOP line and the (paper) mark are in every try."""
    def build(body: str, with_link: bool) -> str:
        return f"{SMS_PREFIX}{body}" + (f" {link}" if with_link else "") + f" {SMS_STOP}"

    more = f" +{n_events - 1} more" if n_events > 1 else ""
    for body, with_link in (("; ".join(lines), True), ("; ".join(lines), False), (lines[0] + more, False)):
        text = _gsm(build(body, with_link))
        if len(text) <= SMS_ONE_SEGMENT:
            return text
    room = SMS_ONE_SEGMENT - len(build("", False)) - len(more) - 3
    if room >= 20:
        return _gsm(build(lines[0][:room].rstrip() + "..." + more, False))
    return None


def sms_text(events: Sequence[Mapping], sizing, tz: str, env=None) -> str:
    """One text. It keeps to a single 160-character segment whenever the wording allows (see ``_fit_one_segment``);
    a burst too long for that falls back to the older shape: up to three lines, a count and the link, within SMS_MAX."""
    all_lines = [_gsm(event_line(e, sizing, tz)) for e in events]      # folded BEFORE any length is measured or clipped
    link = hound_link(events[0]["payload"]["hound_id"], env).split("?")[0]
    full = _gsm(SMS_PREFIX + " | ".join(all_lines[:3]) + (f" | +{len(events) - 3} more" if len(events) > 3 else ""))
    tail = f" {link} {SMS_STOP}"
    legacy = full[: max(0, SMS_MAX - len(tail))] + tail
    if len(legacy) <= SMS_ONE_SEGMENT:
        return legacy
    return _fit_one_segment(all_lines[:3], len(events), link) or legacy


def sample_message(*, to: str, off_url: str, settings_url: str, address: Optional[str] = None) -> dict:
    head = "Test alert from LINEHOUND"
    body_html = (er._headline(head) + er._para("This is a test. Real alerts look like this one, with a hound, a pick, "
                                               "a price and your stake. No bet was made.")
                 + f'<p style="margin:0"><a href="{escape(settings_url, quote=True)}" style="color:#0090C8">Alert settings</a></p>')
    body_text = f"{head}\n\nThis is a test. No bet was made.\nAlert settings: {settings_url}"
    return er._finish(head, head, body_html, body_text, unsubscribe_url=off_url, address=address,
                      reason="You asked for bet alerts.", to=to)
