"""The tiny page behind a shared dog link: ``GET /d/{hound_id}`` (api/hounds_share.py).

WHY A SERVER PAGE AT ALL. The dog page is a static file that fills itself in with JavaScript. A chat app or
a social site that unfurls a link does not run JavaScript, so a link to ``/web/hound.html?id=...`` shows up
as a bare "A dog - LINEHOUND". This route answers with a few lines of HTML whose ``<meta>`` tags say
which dog it is, its record and its catchphrase, then sends a human on to the real page
(``<meta http-equiv="refresh">`` plus a plain link, so it works with scripts off).

EVERYTHING IS ESCAPED. The name and tagline of a builder's dog are text a stranger typed. Every value
that reaches the HTML goes through ``html.escape(quote=True)``, and the id that goes in a URL is
percent-encoded; the id must also match ``ID_RE`` before anything is looked up, so a path like
``/d/<script>`` is a 404 page and never a lookup. A test feeds hostile names through the renderer.

NOTHING HERE MEASURES ANYTHING. The record is what the stats book already holds (the same numbers the
leaderboard shows): the dog page's own words for units are the average price when there is one, else the
recorded price, and this page copies that choice. The hard lines are in the body: paper only, not advice,
21+, the responsible-gambling line. The description is the owner's format and makes no claim beyond the
numbers: ``<W-L> · <units>u paper · <catchphrase>``.
"""

from __future__ import annotations

import html
import os
import re
from typing import Mapping, Optional
from urllib.parse import quote

from src.hounds import share_card

ID_RE = re.compile(r"^[A-Za-z0-9_@.\-]{1,80}$")
ORIGIN_ENV = "LINEHOUND_PUBLIC_ORIGIN"
DEFAULT_ORIGIN = "https://linehound.app"
SITE_TITLE = "LineHound Kennel"
FALLBACK_DESCRIPTION = "A paper betting dog. Paper bets only, not advice, 21+."

STATE_OK = "ok"
STATE_UNKNOWN = "unknown"
STATE_WARMING = "warming"


def origin() -> str:
    return (os.environ.get(ORIGIN_ENV) or DEFAULT_ORIGIN).strip().rstrip("/")


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def wl_text(record: Optional[Mapping]) -> str:
    """"63-46" (or "63-46-2" with pushes); "0-0" with no bets: web/js/hounds-voice.js wlText, in Python."""
    r = record or {}
    bets = _num(r.get("bets")) or 0
    if bets <= 0:
        return "0-0"
    pushes = int(r.get("pushes") or 0)
    return f"{int(r.get('wins') or 0)}-{int(r.get('losses') or 0)}" + (f"-{pushes}" if pushes else "")


def units_text(record: Optional[Mapping]) -> str:
    """"+4.20" / "-1.05" / "0.00" paper units, or "no bets yet": the average price when the dog has one,
    else the recorded price (hounds-voice.js unitsOf)."""
    r = record or {}
    if (_num(r.get("bets")) or 0) <= 0:
        return "no bets yet"
    value = _num(r.get("units_average_price"))
    if value is None:
        value = _num(r.get("units_recorded_price"))
    if value is None:
        return "units not reported"
    rounded = round(value, 2)
    if rounded == 0:
        return "0.00"
    return f"{'+' if rounded > 0 else '-'}{abs(rounded):.2f}"


def description_for(info: Mapping) -> str:
    """``<W-L> · <units>u paper · <catchphrase>`` (the owner's format); the catchphrase falls back to the
    tagline, then to nothing."""
    record = info.get("record") or {}
    units = units_text(record)
    units_part = f"{units}u paper" if units[:1] in "+-0123456789" else units
    parts = [wl_text(record), units_part]
    line = str(info.get("catchphrase") or info.get("tagline") or "").strip()
    if line:
        parts.append(line)
    return " · ".join(parts)


def info_from_summary(summary: Mapping) -> dict:
    """The few fields the page and the card read from a dog's summary. The extras (kind, status, kennel, sports,
    bankroll, settled, vibe) feed ``share_card.spec_from_info``; the card, not this page, decides what to show."""
    persona = summary.get("persona") if isinstance(summary.get("persona"), Mapping) else {}
    return {"id": summary.get("id"), "name": summary.get("name") or summary.get("id"),
            "record": summary.get("record") or {}, "tagline": summary.get("tagline") or "",
            "catchphrase": (persona or {}).get("catchphrase") or "",
            "kind": summary.get("kind"), "status": summary.get("status"), "retired": summary.get("retired"),
            "owner_display": summary.get("owner_display"), "sports": summary.get("sports") or [],
            "bankroll": summary.get("bankroll"), "settled": summary.get("settled"),
            "vibe": (persona or {}).get("vibe") or ""}


def lookup(hound_id: str) -> tuple:
    """``(state, info)``. ok: the dog and its numbers (and its saved look, for the card). unknown: a 404 (the book
    or the app db does not have it). warming: nothing to tell yet (no book, no saved copy, not a house dog we can
    name)."""
    state, info = _lookup(hound_id)
    if state == STATE_OK and info is not None and "look" not in info:
        info["look"] = share_card.look_for(hound_id)
    return state, info


def _lookup(hound_id: str) -> tuple:
    if not ID_RE.match(hound_id or ""):
        return STATE_UNKNOWN, None
    from src.hounds import stats, user_view
    from src.hounds.contract import to_json
    book, _state = stats.get_book_nowait()
    if book is not None:
        data = book.hounds.get(hound_id)
        if data is not None:
            return STATE_OK, info_from_summary(to_json(data.summary))
        data = user_view.hound_data(hound_id, kick_build=False)
        if data is not None:
            return STATE_OK, info_from_summary(to_json(data.summary))
        return STATE_UNKNOWN, None
    for source in (stats.saved_payload("leaderboard", season="all"), stats.saved_payload("graveyard")):
        for entry in (source or {}).get("hounds") or []:
            if isinstance(entry, Mapping) and entry.get("id") == hound_id:
                return STATE_OK, info_from_summary(entry)
    house = _house_name(hound_id)
    if house:
        return STATE_OK, {"id": hound_id, "name": house[0], "record": {}, "tagline": "", "catchphrase": house[1]}
    return STATE_WARMING, None


def _house_name(hound_id: str) -> Optional[tuple]:
    """(name, catchphrase) of a house pack dog from the shipped config, or None: the fallback while the
    book is still warming, so a shared link to a real dog still unfurls with its name."""
    try:
        import json
        from src import paths
        cfg = json.loads((paths.repo_root() / "config" / "house_pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return None
    for entry in cfg.get("hounds") or []:
        if entry.get("id") == hound_id:
            persona = entry.get("persona") if isinstance(entry.get("persona"), dict) else {}
            return str(entry.get("name") or hound_id), str(persona.get("catchphrase") or entry.get("tagline") or "")
    return None


_FOOTER = ('<p class="fine"><strong>Paper bets only, not advice.</strong> Nobody bets real money here. '
           '21+ &middot; Gamble responsibly. <a href="tel:1-800-426-2537">1-800-GAMBLER</a></p>')

_STYLE = ("body{margin:0;background:#0A0A0B;color:#F2F2F3;font:16px/1.5 system-ui,sans-serif;padding:32px 16px}"
          "main{max-width:34rem;margin:0 auto}h1{font-size:1.6rem;margin:.2em 0}"
          "a{color:#FF7A45}.fine{color:#9AA0A6;font-size:.85rem}")


def _page(title: str, description: str, canonical: str, body: str, *, extra_head: str = "",
          image: Optional[str] = None, image_alt: str = "") -> str:
    """``image`` (an absolute URL) turns the unfurl into a large picture card: og:image plus
    twitter:card=summary_large_image. Without one the page keeps the plain ``summary`` card."""
    t = html.escape(title, quote=True)
    d = html.escape(description, quote=True)
    u = html.escape(canonical, quote=True)
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{t}</title>\n"
        f"<meta name=\"description\" content=\"{d}\">\n"
        f"<meta property=\"og:title\" content=\"{t}\">\n"
        f"<meta property=\"og:description\" content=\"{d}\">\n"
        "<meta property=\"og:type\" content=\"website\">\n"
        f"<meta property=\"og:site_name\" content=\"LINEHOUND\">\n"
        f"<meta property=\"og:url\" content=\"{u}\">\n"
        f"<meta name=\"twitter:card\" content=\"{'summary_large_image' if image else 'summary'}\">\n"
        f"<meta name=\"twitter:title\" content=\"{t}\">\n"
        f"<meta name=\"twitter:description\" content=\"{d}\">\n"
        f"{_image_meta(image, image_alt)}"
        f"{extra_head}"
        "<meta name=\"theme-color\" content=\"#0A0A0B\">\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n<main>\n{body}\n{_FOOTER}\n</main>\n</body>\n</html>\n")


def _image_meta(image: Optional[str], alt: str) -> str:
    if not image:
        return ""
    u = html.escape(image, quote=True)
    a = html.escape(alt, quote=True)
    tags = (
        ("property", "og:image", u), ("property", "og:image:type", "image/png"),
        ("property", "og:image:width", str(share_card.CARD_W)), ("property", "og:image:height", str(share_card.CARD_H)),
        ("property", "og:image:alt", a), ("name", "twitter:image", u), ("name", "twitter:image:alt", a),
    )
    return "".join(f'<meta {kind}="{key}" content="{value}">\n' for kind, key, value in tags)


def render_dog(hound_id: str, info: Mapping, *, base: Optional[str] = None) -> str:
    """The shared-link page for one dog: meta tags, a refresh to the real page, and a plain link."""
    base = (base or origin()).rstrip("/")
    name = str(info.get("name") or hound_id)
    target = f"/web/hound.html?id={quote(hound_id, safe='')}"
    canonical = f"{base}/d/{quote(hound_id, safe='')}"
    description = description_for(info) if info.get("record") or info.get("catchphrase") else FALLBACK_DESCRIPTION
    esc = html.escape
    refresh = f'<meta http-equiv="refresh" content="0; url={esc(target, quote=True)}">\n'
    body = (f"<h1>{esc(name)}</h1>\n<p>{esc(description)}</p>\n"
            f'<p><a href="{esc(target, quote=True)}">Open {esc(name)} on LINEHOUND</a></p>')
    spec = share_card.spec_from_info(hound_id, info)
    image = f"{base}{share_card.card_path(hound_id, spec.digest())}"
    alt = "A LINEHOUND hound" if spec.generic else f"{spec.name}, a LINEHOUND hound: record, paper bankroll and kennel"
    return _page(f"{name} | {SITE_TITLE}", description, canonical, body, extra_head=refresh, image=image, image_alt=alt)


def render_not_found(hound_id: str = "") -> str:
    body = ("<h1>No dog by that name</h1>\n<p>This link points at a dog that isn't in the kennel. "
            "It may have been removed, or the link is wrong.</p>\n"
            '<p><a href="/web/hounds.html">See the kennel</a></p>')
    return _page(f"Dog not found | {SITE_TITLE}", FALLBACK_DESCRIPTION, f"{origin()}/web/hounds.html", body)


def render_warming() -> str:
    body = ("<h1>The kennel is waking up</h1>\n<p>Try this link again in a minute.</p>\n"
            '<p><a href="/web/hounds.html">See the kennel</a></p>')
    return _page(f"Kennel warming up | {SITE_TITLE}", FALLBACK_DESCRIPTION, f"{origin()}/web/hounds.html", body)
