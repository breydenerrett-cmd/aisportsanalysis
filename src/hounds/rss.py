"""A small RSS 2.0 writer for the two feeds a Zapier Zap polls (``api/feeds.py``).

WHY A FEED AT ALL. Zapier counts a task per ACTION run; a polling trigger (RSS by Zapier, Webhooks
Retrieve Poll) is free. An event-style Zap therefore polls a feed and spends a task only when a
new item appears. Zapier tells "new" from "already seen" by the item's ``guid``, so the two rules
this module enforces are the ones that keep the Zap quiet and cheap:

  * every item carries a STABLE ``guid`` (``isPermaLink="false"``) chosen by the caller from the
    event's identity, never from the request time, so a poll that sees the same event twice
    returns the same guid twice and fires nothing;
  * every item's ``pubDate`` is the EVENT'S OWN recorded time (RFC 822), never "now". The channel
    has no ``lastBuildDate`` of its own invention either: it is the newest item's date, or absent
    for an empty feed, so two polls of an unchanged world are byte-identical.

An empty feed is valid RSS (a ``channel`` with no ``item``). Text is escaped here, once, so no
caller has to remember to.

Stdlib only (the src/ <-> api/ boundary: nothing here imports a web framework).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Iterable, Mapping, Optional
from xml.sax.saxutils import escape, quoteattr

CONTENT_TYPE = "application/rss+xml; charset=utf-8"

# XML 1.0 forbids most control characters; a stray one in a name would make the whole feed unparseable
# and a Zap that cannot parse its feed stops. Tab, newline and carriage return are the legal ones.
_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def clean(text) -> str:
    """Text made safe for a feed: illegal control characters removed, whitespace folded."""
    return " ".join(_ILLEGAL_XML.sub("", str(text if text is not None else "")).split())


def rfc822(moment: datetime) -> str:
    """``Sat, 17 Oct 2026 14:30:00 +0000``: RFC 822 with a numeric zone, always UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return format_datetime(moment.astimezone(timezone.utc))


def parse_utc(value) -> Optional[datetime]:
    """An ISO date or timestamp as an aware UTC datetime, or None. A bare ``YYYY-MM-DD`` is that day at
    00:00:00Z: the earliest instant of the day, so an item dated 'today' is never in the future."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    return out.astimezone(timezone.utc) if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _tag(name: str, text: str, attrs: str = "") -> str:
    return f"<{name}{attrs}>{escape(text)}</{name}>"


def render(*, title: str, link: str, description: str, items: Iterable[Mapping],
           self_url: Optional[str] = None) -> str:
    """The feed as text. Each item is ``{title, link, guid, pub (datetime), description}``; the caller
    has already ordered them newest first and trimmed them."""
    rows = list(items)
    newest = max((r["pub"] for r in rows), default=None)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
           "<channel>",
           "  " + _tag("title", clean(title)),
           "  " + _tag("link", link),
           "  " + _tag("description", clean(description)),
           "  <language>en-us</language>"]
    if self_url:
        out.append(f'  <atom:link href={quoteattr(self_url)} rel="self" type="application/rss+xml"/>')
    if newest is not None:
        out.append("  " + _tag("lastBuildDate", rfc822(newest)))
    for r in rows:
        out.append("  <item>")
        out.append("    " + _tag("title", clean(r["title"])))
        out.append("    " + _tag("link", r["link"]))
        out.append("    " + _tag("guid", clean(r["guid"]), ' isPermaLink="false"'))
        out.append("    " + _tag("pubDate", rfc822(r["pub"])))
        out.append("    " + _tag("description", clean(r["description"])))
        out.append("  </item>")
    out.append("</channel>")
    out.append("</rss>")
    return "\n".join(out) + "\n"
