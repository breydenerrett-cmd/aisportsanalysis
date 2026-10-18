"""The kennel's news as events, for ``GET /feeds/kennel.rss`` (a Zap posts each new one to Discord).

An event is something that HAPPENED, read from what the site already records, never invented here:

  retired    a hound put down (the stats book's graveyard: its own retirement date and cause)
  promoted   a challenger made the team (the learning loop's ``promotion`` event, with its version)
  cut        a challenger's tryout was cut (a ``decision`` event whose outcome is ``retired``)
  new        a new user hound entered (the app database's first version of a hound)
  streak     a hound's latest settled day ends a run of 5+ wins or 5+ losses (from its graded bets)

Every event carries the three things a polling Zap needs (``src/hounds/rss.py``): a STABLE ``guid``
built from the event's identity (hound + date + kind, or the challenger's id), the event's OWN
recorded time as ``pub`` (a bare date means 00:00Z that day, so nothing is ever dated in the future
and nothing is ever dated "now"), and a link to the hound's page with the Zapier/Discord campaign tags.

VOICE. Short, sports-Discord. No "lock", "guaranteed", "can't lose", "sure thing"; no claim that
anyone profits, now or later; the last words of every description are ``DISCLAIMER``. A streak is
reported as what it is: a run of paper results, with the record beside it.

NAMES ARE DATA. A user hound's name is chosen by a stranger. It passed the site's name rules at
creation (letters, digits, spaces, hyphens), and ``_name`` still strips ``@`` here so a name can never
become a Discord mention on its way through a Zap.

Stdlib only; nothing here reads a ledger. ``api/feeds.py`` gathers the inputs (the cached book, the
two learning states, the user hound rows) and passes them in, which is also how the tests drive it.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, Mapping, Optional
from urllib.parse import quote

from src.hounds import rss

MAX_ITEMS = 30
STREAK_MIN = 5

DISCLAIMER = "Paper bets only, not advice. 21+."
UTM = "utm_source=zapier&utm_medium=discord&utm_campaign=kennel_feed"

# The canonical public address (docs/audit/2026-10-02/LAUNCH_CHAIN.md; deploy/fly.production.toml sets
# PUBLIC_BASE_URL to it). The app's other links read that variable, so this does too; unset, it is the
# production domain rather than billing's ``example.invalid`` placeholder, which would put a dead link
# in every Discord post.
ENV_PUBLIC_BASE_URL = "PUBLIC_BASE_URL"
DEFAULT_BASE_URL = "https://linehound.app"

KIND_RETIRED = "retired"
KIND_PROMOTED = "promoted"
KIND_CUT = "cut"
KIND_NEW = "new"
KIND_WIN_STREAK = "win_streak"
KIND_LOSS_STREAK = "loss_streak"

# Why a challenger was cut, in the words a fan reads. The codes are the referee's
# (src/hounds/learning/referee.py); an unknown code falls back to the neutral line, never a guess.
CUT_WHY = {
    "harm": "It did worse than the version it was trying to replace.",
    "no_win_at_300": "It never beat the old version over its whole tryout.",
    "bh_failed_at_300": "It looked good for a bit, then did not hold up in the monthly check.",
}
CUT_WHY_DEFAULT = "The referee ended its tryout."
PROMOTED_WHY = "It beat the old version against the closing line, and the referee moved it up."


def site_base_url() -> str:
    return (os.environ.get(ENV_PUBLIC_BASE_URL) or "").strip().rstrip("/") or DEFAULT_BASE_URL


def hound_link(base_url: str, hound_id: str) -> str:
    return f"{base_url.rstrip('/')}/web/hound.html?id={quote(str(hound_id), safe='')}&{UTM}"


def _name(value, fallback: str = "A hound") -> str:
    text = rss.clean(value).replace("@", "")
    return text or fallback


def _sentence(text: str) -> str:
    text = rss.clean(text)
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _event(kind: str, guid: str, pub: Optional[datetime], hound_id: str, title: str, why: str) -> Optional[dict]:
    if pub is None:
        return None            # no recorded time, no item: an undated event cannot be ordered or deduped
    return {"kind": kind, "guid": guid, "pub": pub, "hound_id": hound_id, "title": title, "why": why}


# ---- the five kinds -------------------------------------------------------------------------------------

def retired_events(book) -> list:
    out = []
    for hid, data in book.hounds.items():
        s = data.summary
        if "@v" in hid or s.status != "retired" or s.retired is None or not s.retired.date:
            continue
        cause = rss.clean(s.retired.cause)
        if cause.lower().startswith("superseded"):
            continue           # replaced by its own next version: not put down
        if s.kind == "user" and "moderator" in cause.lower():
            why = "A moderator retired it."
        else:
            why = "Why: " + cause.removeprefix("retired: ").removeprefix("Retired: ").strip()
        ev = _event(KIND_RETIRED, f"kennel:{KIND_RETIRED}:{hid}:{s.retired.date}", rss.parse_utc(s.retired.date),
                    hid, f"\U0001F480 {_name(s.name)} got put down", _sentence(why))
        if ev:
            out.append(ev)
    return out


def _settled_run(book_rows) -> Optional[tuple]:
    """``(result, length, latest_day, wins, losses)`` for the trailing run of one hound's FORWARD graded
    results, or None. ``book_rows`` are BetRows newest first. Pushes and voids neither extend nor break a
    run (they are not a win or a loss), and replay rows are not forward results."""
    chronological = [r for r in reversed(list(book_rows))
                     if r.segment == "forward" and r.result in ("win", "loss")]
    if not chronological:
        return None
    chronological.sort(key=lambda r: r.date)        # stable: the within-day order of the ledger is kept
    last = chronological[-1]
    run = 0
    for r in reversed(chronological):
        if r.result != last.result:
            break
        run += 1
    wins = sum(1 for r in chronological if r.result == "win")
    return last.result, run, last.date, wins, len(chronological) - wins


def streak_events(book, *, minimum: int = STREAK_MIN) -> list:
    out = []
    for hid, data in book.hounds.items():
        if "@v" in hid:
            continue
        found = _settled_run(data.bets)
        if found is None:
            continue
        result, run, day, wins, losses = found
        if run < minimum or not day:
            continue
        won = result == "win"
        kind = KIND_WIN_STREAK if won else KIND_LOSS_STREAK
        name = _name(data.summary.name)
        title = (f"\U0001F525 {name} has won {run} in a row" if won
                 else f"\U0001F976 {name} has lost {run} in a row")
        why = (f"Latest settled day: {day}. Forward record: {wins}-{losses}. Runs end; this one is just paper.")
        ev = _event(kind, f"kennel:{hid}:{day}:{kind}", rss.parse_utc(day), hid, title, why)
        if ev:
            out.append(ev)
    return out


def _diff_text(spec_diff: Optional[Mapping]) -> str:
    parts = []
    for knob, pair in sorted((spec_diff or {}).items()):
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            parts.append(f"{rss.clean(knob)} {pair[0]} to {pair[1]}")
    return ("Tweak tried: " + "; ".join(parts) + ". ") if parts else ""


def learning_events(states: Mapping, names: Mapping) -> list:
    """Promotions and cut tryouts from the learning loop's folded states (``{scope: State}``)."""
    out = []
    for state in states.values():
        for p in state.promotions:
            hid = str(p.get("hound_id") or p.get("lineage_key") or "")
            when = rss.parse_utc(p.get("utc"))
            if not hid or when is None:
                continue
            version = p.get("to_version")
            ident = p.get("challenger_id") or f"{hid}-v{version}"
            ev = _event(KIND_PROMOTED, f"kennel:{KIND_PROMOTED}:{ident}", when, hid,
                        f"\U0001F3C6 {_name(names.get(hid), hid)} made the team: new version v{version}",
                        PROMOTED_WHY)
            if ev:
                out.append(ev)
        for c in state.challengers.values():
            if c.status != "retired" or not c.ended_utc:
                continue
            hid = c.hound_id
            why = _diff_text(c.spec_diff) + CUT_WHY.get(c.outcome_reason or "", CUT_WHY_DEFAULT)
            ev = _event(KIND_CUT, f"kennel:{KIND_CUT}:{c.id}", rss.parse_utc(c.ended_utc), hid,
                        f"✂️ {_name(names.get(hid), hid)}'s tryout got cut", why)
            if ev:
                out.append(ev)
    return out


def new_hound_events(user_rows: Iterable[Mapping]) -> list:
    """A user hound's FIRST version is the new dog; a later version of the same dog is not."""
    from src.hounds import user_spec
    out = []
    for h in user_rows:
        if int(h.get("version_no") or 1) != 1:
            continue
        try:
            rule = user_spec.rule_text(h["spec"])
        except Exception:  # noqa: BLE001 -- a spec this build cannot phrase still announces the dog
            rule = ""
        why = ("Its rule: " + rule) if rule else "Fresh paper record, nothing graded yet."
        ev = _event(KIND_NEW, f"kennel:{KIND_NEW}:{h['id']}", rss.parse_utc(h.get("created_at")), h["id"],
                    f"\U0001F436 New dog in the kennel: {_name(h.get('name'))}", _sentence(why))
        if ev:
            out.append(ev)
    return out


# ---- the feed ---------------------------------------------------------------------------------------------

def build_events(book, states: Mapping, user_rows: Iterable[Mapping], *, limit: int = MAX_ITEMS) -> list:
    """Every event, newest first (ties broken by guid so two polls order the same), trimmed to ``limit``."""
    names = {hid: data.summary.name for hid, data in book.hounds.items()}
    events = (retired_events(book) + streak_events(book) + learning_events(states, names)
              + new_hound_events(user_rows))
    seen, unique = set(), []
    for ev in events:
        if ev["guid"] in seen:
            continue
        seen.add(ev["guid"])
        unique.append(ev)
    unique.sort(key=lambda e: e["guid"])
    unique.sort(key=lambda e: e["pub"], reverse=True)
    return unique[:limit]


def render_feed(events: Iterable[Mapping], *, base_url: Optional[str] = None,
                self_url: Optional[str] = None) -> str:
    base = (base_url or site_base_url()).rstrip("/")
    items = [{"title": e["title"], "link": hound_link(base, e["hound_id"]), "guid": e["guid"],
              "pub": e["pub"], "description": f"{e['why']} {DISCLAIMER}"} for e in events]
    return rss.render(title="LINEHOUND kennel news",
                      link=f"{base}/web/hounds.html",
                      description="Hounds put down, challengers promoted or cut, new dogs, and streaks. "
                                  "Paper bets only, not advice. 21+.",
                      items=items, self_url=self_url)


def collect(book, *, states: Optional[Mapping] = None, user_rows: Optional[Iterable[Mapping]] = None) -> list:
    """The events from the live stores. ``states`` and ``user_rows`` default to the real ones (the two
    learning scopes' folded ledgers; the app database's hound rows) and are the tests' seams."""
    if states is None:
        from src.hounds.learning import ledger as L, views
        states = {name: views._safe_state(sc) for name, sc in L.default_scopes().items()}
    if user_rows is None:
        user_rows = []
        from src.hounds import user_defs
        if user_defs.db_exists():
            from src.hounds import user_store
            try:
                user_rows = user_store.list_all()
            except Exception:  # noqa: BLE001 -- an unreadable app db means no "new dog" items, not a 500
                user_rows = []
    return build_events(book, states, user_rows)
