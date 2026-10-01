"""Post the day's public card and the public graded record to a Discord
channel via an incoming webhook. Linehound's first paid product surface --
a community feed, not a new source of truth: everything printed here is
read straight off the same frozen ledger rows and the same reconciled
record `api/card.py` and `src/report/effective_record.py` already serve,
never recomputed or reworded.

STDLIB ONLY (urllib, json, argparse, hashlib) -- no `requests`, no Discord
SDK. This runs from `scripts/daily_loop.sh` and `scripts/afternoon_slate.sh`
on a plain Python 3 install with nothing extra pip-installed.

NEVER A LIVE CARD. `_frozen_card` reads exactly the ledger's published row
for the date (MLB: `src.report.card_v2.frozen_card_v2`, which is frozen-
read-only by construction; NFL/UFC: `src.appstate.card_ledger.published_row`
directly, reshaped by each sport's own report module's `_frozen_payload`).
None of these ever fall through to a live build -- if nothing is published
yet, there is nothing to post, and the run exits 0 having posted nothing.

NO REWORDING. A V2 ledger row freezes the FACTS behind a pick (team, price,
market, line, side, the market/our-number probabilities) but deliberately
never freezes a rendered English sentence (`bet_sentence` is not one of
`card_ledger.V2_FROZEN_FIELDS` -- verified against a real published row,
2026-09-28: `bet`/`bet_sentence`/`why`/`label` all come back `None`/absent).
So the sentence is rebuilt here from the same frozen facts, using the SAME
formula `src/report/card_v2.py` itself uses to describe a game pick
(`card_v2._bet_sentence`, imported rather than re-typed -- the exact
reasoning that module gives for importing `card.py`'s own private helpers
instead of duplicating them) and the identical inline formula
`card_v2._build_prop_candidates` uses for a prop. NFL/UFC picks are V1-
shaped and already carry a fully rendered `bet` string at publish time
(`src/analysis/daily_card.py` sets it before the pick is frozen) -- those
are used verbatim, never rebuilt.

IDEMPOTENT PER WEBHOOK, NEVER LOGS A WEBHOOK. One run delivers to every
webhook in `DISCORD_WEBHOOK_URL` (one) plus `DISCORD_WEBHOOK_URLS` (comma-
or newline-separated; blanks ignored, duplicates collapsed) plus
`--webhook-url`. Every successful post appends one row to
`data/watch/discord_feed_posted.jsonl` keyed on (webhook_hash, sport, date,
row_hash); a row already posted to THAT webhook is skipped, and a new
row_hash for a date already posted to it (the card republished -- a pick
locked, a fill turned into a pick, whatever changed) posts again with a
"card update" header. Webhooks are independent: one failing (network error,
404 because a customer deleted theirs, 429) never stops the others and never
gets a marker, so the next run retries exactly the failed ones. Exit 0 only
when every webhook is posted-or-already-posted; otherwise one `ESCALATE:`
line per failed webhook, naming it only by the first 8 hex characters of its
sha256. The URL itself is never printed or written anywhere (urllib
exceptions can carry it, so error text is scrubbed and unexpected exceptions
are reported by class name only); the marker keeps only the sha256,
`webhook_hash`, so a leaked marker file proves nothing about which webhook
it was.

CONTENT RULES, enforced here and not just hoped for: no entry priced at -200
or shorter is posted (the retired NFL V1 ledger holds some); fills are posted
under their own "Fills" heading; the footer is this file's own disclaimer
(src/analysis/disclaimers.py's wording contains the words edge, profits and
locked-in, which the feed may not use); those words and the other banned
ones (see BANNED_WORD_RE) are refused anywhere in a payload except the
sentence "No edge is claimed.", and a payload that trips the scan is not
posted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_MARKER_PATH = os.path.join("data", "watch", "discord_feed_posted.jsonl")

# Mirrors src.report.effective_record.SPORT_LABEL -- imported at call time
# rather than re-declared, but kept here too as the one place this file's
# own help text/argparse choices are declared.
SPORTS = ("mlb", "nfl", "mma")

# The only two sports whose picks settle from an automated results feed
# (src/report/effective_record.py's own MMA_UNGRADED_REASON: UFC results
# are entered by hand). Read once here rather than guessed per call.
GRADED_AUTOMATICALLY = frozenset({"mlb", "nfl"})

# Discord's own documented limits (developers.discord.com/docs/resources/
# webhook, resources/channel#embed-object-embed-limits). Kept as named
# constants so `_build_messages` reads as "why", not magic numbers.
DISCORD_CONTENT_LIMIT = 2000
DISCORD_EMBED_TOTAL_LIMIT = 6000
DISCORD_FIELD_VALUE_LIMIT = 1024
DISCORD_FIELD_NAME_LIMIT = 256
DISCORD_DESCRIPTION_LIMIT = 4096
DISCORD_FOOTER_LIMIT = 2048
DISCORD_TITLE_LIMIT = 256
# Safety margin under the real 6000 total -- leaves room for the small
# per-embed structural overhead Discord counts beyond the raw text length.
_EMBED_SAFE_LIMIT = DISCORD_EMBED_TOTAL_LIMIT - 200


# American odds: -200 and every price shorter than it (-250, -300 ...) is
# refused; -199 and longer is fine.
SHORTEST_POSTABLE_PRICE = -199

# Words a community-feed payload may not contain. Whole words and their
# plain inflections ("locked-in", "profits"), never a prefix: a prefix match
# on "lock" refuses a whole card because Tyler Lockett or Brandon Lockridge
# is on it.
BANNED_WORD_RE = re.compile(
    r"\b(?:edges?|profit(?:s|able|ably)?|lock(?:s|ed|ing)?|guarantee(?:d|s)?"
    r"|sharps?|winning|bet\s*check)\b", re.IGNORECASE)
ALLOWED_SENTENCE = "No edge is claimed."

# The feed's own footer. src/analysis/disclaimers.BETA_DISCLAIMER says the
# same things with the words "edge", "profits" and "locked-in" in it, which
# this surface may not carry -- so the feed states them its own way. Still
# marked as pending legal review, like the original.
FEED_DISCLAIMER = (
    "BETA -- TEMPORARY NOTICE, PENDING FINAL LEGAL REVIEW. "
    "Sports-betting information and research only. No edge is claimed. "
    "No outcome is promised, for any user or any bet. "
    "You are solely responsible for your own wagering decisions, including "
    "whether to bet at all. Not a sportsbook and not a gambling operator: "
    "it accepts no wagers and places no bets. For users of legal wagering "
    "age in their jurisdiction (21+ in most U.S. states). If gambling is "
    "causing you problems, help is available from your state and national "
    "problem-gambling resources.")


@dataclass
class Assembled:
    """One run's worth of Discord messages, plus the idempotency key for
    them. `messages` is almost always length 1 -- see `_build_messages`.
    `skipped` is set (and `messages` empty) when a card exists but every
    entry on it was refused by the price rule -- nothing to post."""

    messages: list
    row_hash: Optional[str]
    kind: str  # "card" | "record"
    skipped: Optional[str] = None


# ---------------------------------------------------------------------------
# Card + record sourcing -- read-only, never a live build (module docstring).
# ---------------------------------------------------------------------------

def _frozen_card(sport: str, date_str: str, *, path: Optional[str] = None) -> Optional[dict]:
    """The published row for (sport, date), or None if nothing is published
    yet. `path` overrides the real ledger file -- a test's own temp store.

    MLB goes through `card_v2.frozen_card_v2`, which is itself frozen-only
    (reads `card_ledger.published_row` against `CARD_STORE_V2` and returns
    None rather than building live -- see that function's own docstring).
    NFL/UFC have no such wrapper, so `card_ledger.published_row` is called
    directly here and reshaped by each sport's own report module's
    `_frozen_payload` -- the same pure, read-only reshape
    `nfl_card.card_for_date`/`ufc_card.card_for_date` apply to a frozen row
    before their live-build branch is ever reached. That live branch is
    never called from here.
    """
    if sport == "mlb":
        from src.report import card_v2
        return card_v2.frozen_card_v2(date_str, path=path)

    from src.appstate import card_ledger
    row = card_ledger.published_row(date_str, sport=sport, path=path)
    if row is None:
        return None

    if sport == "nfl":
        from src.report import nfl_card
        payload = nfl_card._frozen_payload(date_str, row)
    elif sport == "mma":
        from src.report import ufc_card
        payload = ufc_card._frozen_payload(date_str, row)
    else:
        raise ValueError(f"unsupported sport {sport!r}")

    # `_frozen_payload` reshapes the row for a page and drops the ledger's
    # own hash-chain fields along the way -- put back the one this script
    # needs for idempotency.
    payload["row_hash"] = row.get("row_hash")
    return payload


def _sport_snapshot(sport: str, **kwargs) -> dict:
    from src.report import effective_record
    return effective_record.sport_snapshot(sport, **kwargs)


def _sport_label(sport: str) -> str:
    from src.report import effective_record
    return effective_record.SPORT_LABEL.get(sport, sport.upper())


def _stake_basis_text() -> str:
    from src.report import effective_record
    # The product's own sentence says "profit units"; the feed says "net
    # units" (same quantity) because "profit" is not allowed here.
    return effective_record.STAKE_BASIS.replace("profit units", "net units")


def _footer_text(sport: str) -> str:
    disclaimer = FEED_DISCLAIMER
    grading = ("Graded in public the next morning." if sport in GRADED_AUTOMATICALLY
               else "Results entered by hand.")
    return f"{disclaimer} {grading}"


# ---------------------------------------------------------------------------
# Per-pick wording -- reconstructed from frozen facts, never invented.
# ---------------------------------------------------------------------------

def _entry_sentence(sport: str, entry: dict) -> str:
    """The one line naming the bet, exactly as the frozen row's own facts
    say it -- see the module docstring's "NO REWORDING" section."""
    if sport != "mlb":
        # V1-shaped (NFL/UFC): `bet` is a fully rendered sentence, written
        # once at publish time by src/analysis/daily_card.py and frozen
        # verbatim (card_ledger.FROZEN_FIELDS). Used as-is.
        return entry.get("bet") or ""

    from src.analysis import best_bets_card
    from src.analysis import daily_card
    from src.report import card_v2

    if entry.get("kind") == "prop":
        # The product's own prop sentence (daily_card._prop_bet_sentence,
        # which V1 props freeze as `bet`): "Take Devers over 0.5 hits at
        # +120" -- the side (Over/Under) and the market in plain words,
        # read off the frozen row. The "Take " is stripped here only so
        # best_bets_card.bet_sentence below decides it from the `take` flag,
        # exactly as it does for a game pick.
        raw = " ".join(daily_card._prop_bet_sentence(entry).split())
        if raw.lower().startswith("take "):
            raw = raw[5:]
    else:
        raw = card_v2._bet_sentence(entry)

    # `best_bets_card.bet_sentence` decides the "Take " prefix from the
    # frozen `take` flag (false on a locked pick whose fresh read no longer
    # clears -- see card_v2_for_date's own docstring); reusing it here
    # rather than re-typing that one-line rule keeps this script from ever
    # drifting from the product's own definition of "Take".
    return best_bets_card.bet_sentence({**entry, "bet_sentence": raw})


def _market_vs_our_suffix(entry: dict) -> str:
    """" (market NN% vs our number NN%)", read straight off the frozen
    row -- omitted entirely when either number is absent (a V1-shaped pick
    with no model behind it, e.g. a UFC consensus-only favourite)."""
    from src.analysis import daily_card

    market = entry.get("market_probability")
    # V2 freezes the MARKED-DOWN number under `our_probability_used` -- the
    # same number the public card's own "why" line calls "Our number"
    # (best_bets_card.why_sentences). V1-shaped picks carry no such field;
    # `model_probability` is the closest they have, often None.
    ours = entry.get("our_probability_used")
    if ours is None:
        ours = entry.get("model_probability")
    if market is None or ours is None:
        return ""
    return f" (market {daily_card._fmt_pct(market)} vs our number {daily_card._fmt_pct(ours)})"


def _pick_line(sport: str, entry: dict, index: int) -> str:
    return f"{index}. {_entry_sentence(sport, entry)}{_market_vs_our_suffix(entry)}"


def _is_postable(entry: dict) -> bool:
    """False for an entry priced at -200 or shorter. An entry with no
    numeric price is kept (nothing to measure); the ledger's own publish
    guard is the first line of defence, this is the second."""
    price = entry.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return True
    return price >= SHORTEST_POSTABLE_PRICE


def banned_words_in(payload) -> list:
    """Every banned word found in a payload's text, after removing the one
    allowed sentence. [] means clean."""
    blob = json.dumps(payload, ensure_ascii=False).replace(ALLOWED_SENTENCE, "")
    return sorted({m.group(0).lower() for m in BANNED_WORD_RE.finditer(blob)})


def _raw_entries(sport: str, frozen: dict) -> tuple:
    """(entries, fills) before the price rule. Withdrawn entries are never
    read from `frozen` at all -- there is no code path here that could
    render one."""
    if sport == "mlb":
        entries = list(frozen.get("picks") or ()) + list(frozen.get("prop_picks") or ())
        # `rank` is stamped across game AND prop picks together at publish
        # time (card_ledger.publish_v2), so sorting by it -- rather than by
        # the picks-then-props concatenation order above -- reproduces the
        # card's true one-list rank order.
        entries.sort(key=lambda e: e.get("rank") if e.get("rank") is not None else 10 ** 9)
        fills = list(frozen.get("fills") or ())
    else:
        entries = list(frozen.get("picks") or ())
        fills = []  # V1-shaped ledgers (NFL/UFC) have no fill/withdrawn concept.
    return entries, fills


def _card_sections(sport: str, frozen: dict) -> tuple:
    """(picks_lines, fills_lines), every entry priced at -200 or shorter
    left out."""
    entries, fills = _raw_entries(sport, frozen)
    entries = [e for e in entries if _is_postable(e)]
    fills = [e for e in fills if _is_postable(e)]
    picks_lines = ([_pick_line(sport, e, i) for i, e in enumerate(entries, 1)]
                   or ["No picks published for this date."])
    fills_lines = [_pick_line(sport, e, i) for i, e in enumerate(fills, 1)]
    return picks_lines, fills_lines


# ---------------------------------------------------------------------------
# Record block -- src/report/effective_record.sport_snapshot, never pooled.
# ---------------------------------------------------------------------------

def _fmt_units(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:+.2f}u"


def _cohort_headline(cohort: Optional[dict]) -> str:
    """The real W-L/units/nights line for a graded cohort, or the cohort's
    own honest-absence reason -- never a fabricated 0-0 for a rule that has
    not settled anything yet (effective_record's own metric contract)."""
    if not cohort:
        return "no data"
    if not cohort.get("available"):
        return f"unavailable ({cohort.get('reason') or 'unknown error'})"
    if cohort.get("grading_state") != "graded":
        return cohort.get("reason") or "no graded picks yet"
    span = cohort.get("date_span") or {}
    span_txt = f" ({span.get('first')} to {span.get('last')})" if span.get("first") else ""
    nights = cohort.get("days") or 0
    night_word = "night" if nights == 1 else "nights"
    return (f"{cohort.get('wins')}-{cohort.get('losses')}, "
            f"{_fmt_units(cohort.get('profit_units'))}, {nights} {night_word}{span_txt}")


def _record_lines(sport: str, snapshot: dict) -> list:
    current = snapshot.get("current") or {}
    previous = snapshot.get("previous")

    lines = [f"{current.get('label') or 'Current rule'}: {_cohort_headline(current)}"]
    if previous:
        lines.append(f"Previous rule — {previous.get('label') or 'previous'}: "
                      f"{_cohort_headline(previous)}")
    postseason = current.get("postseason") or {}
    if (postseason.get("n_staked") or 0) > 0:
        lines.append(f"Postseason: {postseason.get('wins')}-{postseason.get('losses')}, "
                      "graded, not counted")
    return lines


def _record_row_hash(record_lines: list) -> str:
    """Content hash used as the idempotency key for a `--record-only` post,
    which has no ledger row_hash of its own to key on -- a record-only run
    posts again only when the underlying figures actually change."""
    blob = "\n".join(record_lines).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Discord payload assembly, with the 2000/6000-char split (module docstring).
# ---------------------------------------------------------------------------

def _chunk_lines(lines: list, limit: int = DISCORD_FIELD_VALUE_LIMIT) -> list:
    chunks, buf, buf_len = [], [], 0
    for line in lines:
        add = len(line) + (1 if buf else 0)
        if buf and buf_len + add > limit:
            chunks.append("\n".join(buf))
            buf, buf_len = [line], len(line)
        else:
            buf.append(line)
            buf_len += add
    if buf:
        chunks.append("\n".join(buf))
    return chunks or [""]


def _fields_for(name: str, lines: list) -> list:
    chunks = _chunk_lines(lines)
    fields = []
    for i, chunk in enumerate(chunks):
        label = name if i == 0 else f"{name} (cont. {i + 1})"
        fields.append({"name": label[:DISCORD_FIELD_NAME_LIMIT], "value": chunk, "inline": False})
    return fields


def _embed_len(embed: dict) -> int:
    total = len(embed.get("title") or "") + len(embed.get("description") or "")
    total += len((embed.get("footer") or {}).get("text") or "")
    for f in embed.get("fields") or ():
        total += len(f.get("name") or "") + len(f.get("value") or "")
    return total


def _build_messages(content: str, embed: dict) -> list:
    """[payload] normally; [payload, payload] when the embed would exceed
    Discord's own limits (module docstring's "splitting into two posts")."""
    content = content[:DISCORD_CONTENT_LIMIT]
    if _embed_len(embed) <= _EMBED_SAFE_LIMIT:
        return [{"content": content, "embeds": [embed]}]

    fields = embed.get("fields") or []
    mid = max(1, len(fields) // 2)
    embed1 = {**embed, "fields": fields[:mid]}
    embed2 = {"title": f"{embed.get('title') or ''} (continued)"[:DISCORD_TITLE_LIMIT],
              "footer": embed.get("footer"), "fields": fields[mid:]}
    return [{"content": content, "embeds": [embed1]},
            {"content": "", "embeds": [embed2]}]


def assemble(sport: str, date_str: str, *, record_only: bool = False,
             is_update: bool = False, card_path: Optional[str] = None,
             snapshot_provider: Optional[Callable] = None,
             snapshot_kwargs: Optional[dict] = None) -> Optional[Assembled]:
    """Build the Discord message(s) for one (sport, date) run, or None when
    there is nothing to post (no frozen card, and `record_only` was not
    asked for)."""
    label = _sport_label(sport)
    provider = snapshot_provider or _sport_snapshot
    snapshot = provider(sport, **(snapshot_kwargs or {}))
    record_lines = _record_lines(sport, snapshot)

    if record_only:
        title = f"{label} record — {date_str}"
        description = _stake_basis_text()
        fields = _fields_for("Record", record_lines)
        row_hash = _record_row_hash(record_lines)
        kind = "record"
    else:
        frozen = _frozen_card(sport, date_str, path=card_path)
        if frozen is None:
            return None
        title = (f"{label} card update — {date_str}" if is_update
                  else f"{label} card — {date_str}")
        description = frozen.get("basis") or ""
        raw_entries, raw_fills = _raw_entries(sport, frozen)
        if (raw_entries or raw_fills) and not any(
                _is_postable(e) for e in raw_entries + raw_fills):
            return Assembled(messages=[], row_hash=frozen.get("row_hash"), kind="card",
                             skipped="every entry is priced at -200 or shorter")
        picks_lines, fills_lines = _card_sections(sport, frozen)
        fields = _fields_for("Picks", picks_lines)
        if fills_lines:
            fields += _fields_for("Fills", fills_lines)
        fields += _fields_for("Record", record_lines)
        row_hash = frozen.get("row_hash")
        kind = "card"

    embed = {
        "title": title[:DISCORD_TITLE_LIMIT],
        "description": description[:DISCORD_DESCRIPTION_LIMIT],
        "fields": fields,
        "footer": {"text": _footer_text(sport)[:DISCORD_FOOTER_LIMIT]},
    }
    return Assembled(messages=_build_messages(title, embed), row_hash=row_hash, kind=kind)


# ---------------------------------------------------------------------------
# Idempotency marker -- data/watch/discord_feed_posted.jsonl.
# ---------------------------------------------------------------------------

def _read_markers(marker_path: str) -> list:
    rows = []
    try:
        with open(marker_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return rows


def _already_posted(rows: list, sport: str, date_str: str, row_hash,
                    webhook_hash: str) -> bool:
    return any(r.get("webhook_hash") == webhook_hash and r.get("sport") == sport
               and r.get("date") == date_str and r.get("row_hash") == row_hash
               for r in rows)


def _has_prior_post(rows: list, sport: str, date_str: str, kind: str,
                    webhook_hash: str) -> bool:
    return any(r.get("webhook_hash") == webhook_hash and r.get("sport") == sport
               and r.get("date") == date_str and r.get("kind") == kind
               for r in rows)


def _append_marker(marker_path: str, row: dict) -> None:
    parent = os.path.dirname(marker_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(marker_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True))
        fh.write("\n")


def _webhook_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _short_id(url: str) -> str:
    """The only way a webhook is ever named in output: the first 8 hex
    characters of its sha256."""
    return _webhook_hash(url)[:8]


def parse_webhook_urls(*raw_values) -> list:
    """Every webhook URL in the given strings (each comma-, newline- or
    whitespace-separated; None/blank items ignored), duplicates collapsed,
    first-seen order kept."""
    seen, urls = set(), []
    for raw in raw_values:
        for item in re.split(r"[,\s]+", raw or ""):
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                urls.append(item)
    return urls


def _scrub(text, url: str) -> str:
    """`text` with the webhook URL -- whole, without its scheme, or just its
    id/token path segments -- replaced by [redacted]. Applied to anything an
    exception or an HTTP reason phrase could have put the URL into."""
    out = str(text)
    needles = [url, re.sub(r"^[a-z]+://", "", url)]
    needles += [seg for seg in url.split("?")[0].split("/")[3:] if len(seg) >= 8]
    for needle in sorted(set(n for n in needles if n), key=len, reverse=True):
        out = out.replace(needle, "[redacted]")
    return out


# ---------------------------------------------------------------------------
# HTTP -- urllib only, 15s timeout, the webhook URL is never printed.
# ---------------------------------------------------------------------------

def _post_one(url: str, message: dict):
    """(status_code_or_None, reason_or_None). Never raises -- every failure
    mode urlopen can produce is caught and turned into a plain status/reason
    pair so the caller never has to inspect an exception (which, for a
    URLError, can otherwise leak request internals) to decide what to print."""
    data = json.dumps(message).encode("utf-8")
    try:
        request = Request(url, data=data, method="POST",
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=15) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            return status, None
    except HTTPError as exc:
        return exc.code, _scrub(exc.reason, url)
    except URLError as exc:
        return None, _scrub(exc.reason, url)
    except Exception as exc:  # timeout mid-read, reset, malformed URL ...
        # Class name only: a ValueError from a malformed URL quotes it.
        return None, type(exc).__name__


def _post_all(url: str, messages: list):
    """(ok, status, reason) for the whole run -- all messages must succeed
    (2xx) for the marker to be written; the first failure stops the rest."""
    for message in messages:
        status, reason = _post_one(url, message)
        if status is None or not (200 <= status < 300):
            return False, status, reason
    return True, 200, None


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------

def run(sport: str, date_str: str, *, webhook_url: Optional[str] = None,
        webhook_urls: Optional[list] = None,
        dry_run: bool = False, record_only: bool = False,
        marker_path: str = DEFAULT_MARKER_PATH, card_path: Optional[str] = None,
        snapshot_provider: Optional[Callable] = None,
        snapshot_kwargs: Optional[dict] = None) -> int:
    """Deliver one (sport, date) to every webhook, each independently.
    `webhook_url` (one) and `webhook_urls` (a list, or raw comma/newline
    text) are merged and de-duplicated. Returns 0 only when every webhook
    is posted-or-already-posted (or there was nothing to post)."""
    if isinstance(webhook_urls, str):
        webhook_urls = [webhook_urls]
    urls = parse_webhook_urls(webhook_url, *(webhook_urls or ()))

    def build(is_update: bool):
        return assemble(sport, date_str, record_only=record_only, is_update=is_update,
                        card_path=card_path, snapshot_provider=snapshot_provider,
                        snapshot_kwargs=snapshot_kwargs)

    assembled = build(False)
    if assembled is None:
        print(f"no published card for {date_str}")
        return 0
    if assembled.skipped:
        print(f"nothing to post for {sport} {date_str}: {assembled.skipped}")
        return 0

    banned = banned_words_in(assembled.messages)
    if banned:
        print(f"ESCALATE: discord feed content for {sport} {date_str} contains "
              f"banned wording ({', '.join(banned)}); nothing posted")
        return 1

    if dry_run:
        for message in assembled.messages:
            print(json.dumps(message))
        return 0

    if not urls:
        print(f"ESCALATE: discord feed for {sport} {date_str} has no webhook URL configured")
        return 1

    prior_rows = _read_markers(marker_path)
    updated = None  # the "card update" variant, built only if some webhook needs it
    failures = 0
    for url in urls:
        whash = _webhook_hash(url)
        tag = f"webhook {whash[:8]}"
        if _already_posted(prior_rows, sport, date_str, assembled.row_hash, whash):
            print(f"already posted: {sport} {date_str} ({assembled.kind}, "
                  f"row_hash={assembled.row_hash}) [{tag}]")
            continue

        use = assembled
        if (not record_only) and _has_prior_post(prior_rows, sport, date_str, "card", whash):
            if updated is None:
                updated = build(True)
            use = updated

        try:
            ok, status, reason = _post_all(url, use.messages)
        except Exception as exc:  # never let one webhook's failure stop the rest
            ok, status, reason = False, None, type(exc).__name__
        if not ok:
            failures += 1
            detail = f"HTTP {status}" if status is not None else "network error"
            suffix = f" ({_scrub(reason, url)})" if reason else ""
            print(f"ESCALATE: discord feed post failed for {sport} {date_str} "
                  f"[{tag}]: {detail}{suffix}")
            continue

        try:
            _append_marker(marker_path, {
                "sport": sport,
                "date": date_str,
                "row_hash": use.row_hash,
                "webhook_hash": whash,
                "posted_utc": datetime.now(timezone.utc).isoformat(),
                "kind": use.kind,
            })
        except OSError as exc:
            failures += 1
            print(f"ESCALATE: discord feed posted {sport} {date_str} [{tag}] but "
                  f"could not record it ({type(exc).__name__}); it will post again")
            continue
        print(f"posted: {sport} {date_str} ({use.kind}) [{tag}]")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def _valid_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}, expected YYYY-MM-DD") from exc
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discord_feed.py",
        description=("Post the day's public card and the public graded record "
                     "to a Discord channel via an incoming webhook."))
    parser.add_argument("--sport", choices=SPORTS, default="mlb")
    parser.add_argument("--date", type=_valid_date, default=None,
                        help=("YYYY-MM-DD, default: today -- the same default "
                             "api/card.py's own GET /card uses (date.today())."))
    parser.add_argument("--webhook-url", default=None,
                        help=("Discord incoming webhook URL, in addition to $DISCORD_WEBHOOK_URL "
                              "and $DISCORD_WEBHOOK_URLS (comma- or newline-separated)."))
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the exact JSON payload(s) that would be posted; post nothing.")
    parser.add_argument("--record-only", action="store_true",
                        help="Post only the record block, never the card.")
    return parser


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _build_parser().parse_args(argv)
    urls = parse_webhook_urls(args.webhook_url, os.environ.get("DISCORD_WEBHOOK_URL"),
                              os.environ.get("DISCORD_WEBHOOK_URLS"))
    date_str = args.date or date_cls.today().isoformat()
    return run(args.sport, date_str, webhook_urls=urls, dry_run=args.dry_run,
              record_only=args.record_only)


if __name__ == "__main__":
    raise SystemExit(main())
