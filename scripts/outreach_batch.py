"""Prepare outreach batches as paste-ready text, and log what was sent by hand.

Nothing here sends anything. Brey sends every message himself.

    python scripts/outreach_batch.py build --batch 1 [--size 20] [--date YYYY-MM-DD]
    python scripts/outreach_batch.py rebuild --batch 1 [--date YYYY-MM-DD]
    python scripts/outreach_batch.py seed
    python scripts/outreach_batch.py sent  --batch 1 --items 1,3,4 [--date|--at ...] [--note "..."]
    python scripts/outreach_batch.py reply --lead l012-unit-circle --type CURIOUS
                                           [--said "what they wrote"] [--by owner|ai] [--at ...]
    python scripts/outreach_batch.py add --via l001-covers-website-promotions-forum --channel discord
                                         [--handle "..."] [--sport "..."] [--type TYPE] [--said "..."]
    python scripts/outreach_batch.py alias --lead l041-p --handle "second identity"
    python scripts/outreach_batch.py signup|tester-access|activated --lead <id> [--at ...]
    python scripts/outreach_batch.py feedback --lead <id> [--said "..."]
    python scripts/outreach_batch.py would-pay --lead <id> [--no] [--price N] [--said "..."]
    python scripts/outreach_batch.py paid  --lead <id> [--revenue N] [--at ...]
    python scripts/outreach_batch.py followup --lead <id> --date YYYY-MM-DD
    python scripts/outreach_batch.py set-group --leads ID,ID,... --group N
    python scripts/outreach_batch.py next-group | status | milestones
    python scripts/outreach_batch.py reply --target "<name>" --stage replied|demo|trial|paid|lost
                                           [--revenue N] [--note "..."] [--date ...]   (legacy)

build    writes docs/sales/batch_NN.md from docs/sales/targets.csv and gives each
         selected target a lead in docs/sales/outreach_queue.csv. Message text is
         PARSED from docs/sales/scripts.md at run time, never retyped here. Every
         link to our own pages is tagged utm_source=<lead_id> (base URLs come from
         config/business.json public_urls and nowhere else).
rebuild  regenerates an existing batch file with the SAME leads in the SAME order
         (no reselection); refuses once any item of the batch is marked sent.
seed     adds a queue row for every item already in the batch files (idempotent).
sent     marks items sent: updates the queue row, appends one event to pipeline.csv.
reply, signup, tester-access, activated, feedback, would-pay, paid, followup
         each UPDATE one lead's row (a timestamp is set once and never overwritten;
         a reply keeps its first time and follows the latest type; a would-pay answer
         can be corrected) and append one event row to pipeline.csv.
add      the only way a person enters the queue after the batches: a human who
         answered a channel post (or wrote in unprompted). Refused when their handle
         already belongs to a lead: use `alias`.
set-group, next-group
         plan the sending order: groups of unsent leads, with the exact `sent` command.
status, milestones
         one line per lead with activity and the counts by reply type; the first
         timestamp (and lead) of each funnel step.

THE REPOSITORY IS PUBLIC. docs/sales/outreach_queue.csv and pipeline.csv hold ids,
channels, timestamps and reply types only. What a person wrote (--said) and who they
are (--handle, aliases) go to data/private/outreach_private.jsonl, which is gitignored
and append-only (override the path with $LINEHOUND_OUTREACH_PRIVATE). --note and --sport
land in tracked files, so a handle, an email, a link or a known identity in them is refused.

kind=channel_post (a forum thread) is a public post, not a human; kind=person is one human.
Only people count as leads, replies, signups and payments.

Exit code 2 means a refusal: a missing script section, a guard hit, a duplicate person,
an unknown lead, an illegal transition (reply before sent). A refusal writes nothing.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SALES = Path("docs") / "sales"
PIPELINE_FIELDS = ["date", "source", "campaign", "target", "contact_path", "message_variant",
                   "stage", "last_touch", "next_action", "revenue", "notes"]
REPLY_STAGES = ("replied", "demo", "trial", "paid", "lost")

# The canonical outreach queue: ONE row per lead (a person or a channel post), the
# entity store every count and milestone is read from. pipeline.csv stays the
# append-only event history beside it (one row per command, never edited).
# Schema v2 (2026-10-03): one column per funnel step, `kind` to tell a human from a
# public thread, `via_lead` for a person who answered a post. v1 files are migrated on read.
QUEUE_NAME = "outreach_queue.csv"
QUEUE_FIELDS = ["lead_id", "kind", "person", "channel", "campaign", "sport_interest", "message_version",
                "send_group", "sent_at", "reply_at", "reply_type", "signup_at", "tester_access_at",
                "activated_at", "feedback_at", "would_pay", "would_pay_at", "payment_at", "next_followup",
                "notes", "via_lead", "batch"]
OLD_QUEUE_FIELDS = ["lead_id", "person_channel", "source", "sport_interest", "message_version",
                    "sent_at", "reply_at", "reply_classification", "signup_at", "activated_at",
                    "payment_at", "next_followup", "notes", "batch", "would_pay_at"]
KINDS = ("channel_post", "person")
REPLY_TYPES = ("POSITIVE_INTEREST", "CURIOUS", "SIGNED_UP", "ACTIVE_TESTER", "WOULD_PAY", "PRICE_OBJECTION",
               "TRUST_OBJECTION", "PRODUCT_CONFUSION", "NOT_INTERESTED", "NO_REPLY", "SPAM_OR_IRRELEVANT")
POSITIVE_TYPES = ("POSITIVE_INTEREST", "SIGNED_UP", "ACTIVE_TESTER", "WOULD_PAY")
TYPE_ALIASES = {"interested": "POSITIVE_INTEREST", "question": "CURIOUS", "not_interested": "NOT_INTERESTED",
                "auto": "SPAM_OR_IRRELEVANT", "hostile": "TRUST_OBJECTION"}
NO_REPLY_DAYS = 7                      # sent, unanswered for longer than this reads as NO_REPLY
TESTER_WINDOW = timedelta(days=7)      # an early-access grant lasts this long (src.appstate.testers)

# Verbatim text and identities live here, never in a tracked file (the repo is public).
PRIVATE_REL = Path("data") / "private" / "outreach_private.jsonl"
PRIVATE_ENV = "LINEHOUND_OUTREACH_PRIVATE"
PRIVATE_FIELDS = ("lead_id", "at", "type", "text", "by")
PRIVATE_TYPES = ("identity", "reply", "feedback", "note", "classification")
PRIVATE_BY = ("owner", "ai")
LEAD_ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")
FOLLOWUP_DAYS = 3  # `sent` sets next_followup this many days out (scripts.md: day 3, day 7)

# Quotas for a batch of 20, in the order the items are numbered.
BASE_QUOTA = (("forum", 2), ("creator", 5), ("x_account", 5), ("discord_server", 8))
BASE_SIZE = 20

BANNED = re.compile(r"\b(?:profit|lock|sharp|winning|guaranteed)\w*|bet\s*check", re.IGNORECASE)
EDGE = re.compile(r"\bedge\w*", re.IGNORECASE)
# Candidate forms of the one allowed use of "edge". Only the forms scripts.md itself
# contains (after quote normalisation) are allowed; nothing else is.
EDGE_CANDIDATES = ("no edge is claimed", "no edge claimed", "not claiming an edge",
                   "i'm not claiming an edge", "i am not claiming an edge")
LINK = re.compile(r"https?://|www\.|\[RECORD_URL\]|\b\w+\.(?:app|com|org|io)\b", re.IGNORECASE)
BRACKET = re.compile(r"\[[^\]\n]*\]")


class OutreachError(Exception):
    """A refusal. main() prints it and exits 2."""


# --------------------------------------------------------------------------- parsing

def _blockquote_after(lines: list, start: int) -> str:
    """The first run of '>' lines at or after lines[start]; '>' alone is a blank line."""
    i = start
    while i < len(lines) and not lines[i].startswith(">"):
        i += 1
    out = []
    while i < len(lines) and lines[i].startswith(">"):
        out.append(lines[i][2:] if lines[i].startswith("> ") else lines[i][1:])
        i += 1
    return "\n".join(out).strip()


def _find_one(lines: list, pattern: str, section: str) -> int:
    hits = [i for i, line in enumerate(lines) if re.match(pattern, line)]
    if not hits:
        raise OutreachError(f"scripts.md: section not found: {section}")
    if len(hits) > 1:
        raise OutreachError(f"scripts.md: section is ambiguous ({len(hits)} matches): {section}")
    return hits[0]


def parse_scripts(text: str) -> dict:
    """Pull the texts out of scripts.md. Raises OutreachError naming a missing section."""
    lines = text.splitlines()
    found = {}
    for key, letter in (("variant_a", "A"), ("variant_b", "B"), ("variant_c", "C")):
        idx = _find_one(lines, rf"^\*\*Variant {letter}\b", f"**Variant {letter} ...** heading")
        body = _blockquote_after(lines, idx + 1)
        if not body:
            raise OutreachError(f"scripts.md: no blockquote under **Variant {letter} ...**")
        found[key] = body
    t_idx = _find_one(lines, r"^\*\*Title:\*\*", "**Title:** (feedback post)")
    title = lines[t_idx].split("**Title:**", 1)[1].strip()
    if not title:
        raise OutreachError("scripts.md: **Title:** line is empty (feedback post)")
    b_idx = _find_one(lines, r"^\*\*Body:\*\*", "**Body:** (feedback post)")
    body = _blockquote_after(lines, b_idx + 1)
    if not body:
        raise OutreachError("scripts.md: no blockquote under **Body:** (feedback post)")
    found["post_title"], found["post_body"] = title, body
    x_idx = _find_one(lines, r"^## \(c\) Reply template for X", "## (c) Reply template for X")
    x_text = _blockquote_after(lines, x_idx + 1)
    if not x_text:
        raise OutreachError("scripts.md: no blockquote under '## (c) Reply template for X'")
    found["x_reply"] = x_text
    return found


def _norm(text: str) -> str:
    return (text.replace("’", "'").replace("‘", "'")
            .replace("“", '"').replace("”", '"').lower())


def allowed_edge_forms(scripts_text: str) -> tuple:
    """Candidate forms that scripts.md itself uses. A form it does not use is not allowed."""
    low = _norm(scripts_text)
    return tuple(form for form in EDGE_CANDIDATES if form in low)


def guard_message(text: str, allowed_edge: tuple) -> list:
    """Return a list of problems (empty = clean)."""
    problems = []
    for m in BANNED.finditer(text):
        problems.append(f"banned word {m.group(0)!r}")
    low = _norm(text)
    spans = []
    for form in allowed_edge:
        for m in re.finditer(re.escape(form), low):
            spans.append((m.start(), m.end()))
    for m in EDGE.finditer(low):
        if not any(s <= m.start() and m.end() <= e for s, e in spans):
            problems.append(f"'edge' outside an allowed phrase at offset {m.start()}")
    return problems


# --------------------------------------------------------------------------- selection

def parse_members(size: str):
    m = re.search(r"([\d][\d.,]*)\s*([kK])?\s*members", size or "")
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    return int(round(num * 1000)) if m.group(2) else int(num)


def norm_name(name: str) -> str:
    return " ".join((name or "").casefold().split())


def eligible(row: dict) -> bool:
    status = (row.get("rule_status") or "").strip()
    up = status.upper()
    if up.startswith("NOT_ALLOWED") or up.startswith("UNVERIFIED"):
        return False
    if "competitor" in status.lower():
        return False
    # The researcher's own note counts too: a target described as a possible
    # competitor (it sells picks itself) is not someone to pitch.
    return "competitor" not in (row.get("why_fit") or "").lower()


def people(row: dict) -> set:
    """The people a target is: the name before any bracket, and each name
    inside brackets, lower-cased, handles dropped. "JustBaseball Betting
    (Peter Appel, TheDannyClassic)" and "Peter Appel (@PeterAppel23)" share
    "peter appel", so one batch never writes to the same person twice."""
    name = row.get("name") or ""
    head, _, rest = name.partition("(")
    parts = [head] + rest.rstrip(")").split(",")
    out = set()
    for part in parts:
        part = part.strip()
        if part and not part.startswith("@"):
            out.add(" ".join(part.casefold().split()))
    # "Farley's Substack" and "Farley (@FarleyBets)" are one person too: a
    # distinctive first word (possessive dropped) is also a key.
    first = head.strip().split(" ")[0].casefold() if head.strip() else ""
    for suffix in ("'s", "’s"):
        if first.endswith(suffix):
            first = first[: -len(suffix)]
    if len(first) >= 5 and first not in {"sports", "picks", "fantasy", "betting", "baseball",
                                         "football", "dynasty", "monotone"}:
        out.add("first:" + first)
    return out


def _prefers(row: dict) -> bool:
    members = parse_members(row.get("size", ""))
    if members is None or not 500 <= members <= 4000:
        return False
    return bool(re.search(r"\bMLB\b|\bNFL\b|prop", row.get("sport_focus", ""), re.IGNORECASE))


def quotas(size: int) -> dict:
    forum = size * 2 // BASE_SIZE
    creator = size * 5 // BASE_SIZE
    xacc = size * 5 // BASE_SIZE
    return {"forum": forum, "creator": creator, "x_account": xacc,
            "discord_server": size - forum - creator - xacc}


def select_targets(targets: list, contacted: set, size: int = BASE_SIZE,
                   exclude: set = frozenset(), exclude_people: set = frozenset()) -> list:
    """Deterministic. `contacted` and `exclude` hold normalised names (pipeline, other batches).

    `exclude_people` holds `people()` keys of everyone already in another
    batch or the pipeline. Batch 2 first came out with Peter Appel and Farley
    in it again, as X accounts, after batch 1 had them as a site and a
    newsletter: the one-person-once rule only looked inside a single batch."""
    seen = set(contacted) | set(exclude)
    pool = []
    for row in targets:
        key = norm_name(row.get("name"))
        if not key or key in seen or not eligible(row):
            continue
        seen.add(key)  # a name listed twice is one target
        pool.append(row)
    want = quotas(size)
    picked = {}
    shortfall = 0
    met = set(exclude_people)
    for kind in ("forum", "creator", "x_account"):
        rows = []
        for r in pool:
            if r.get("type") != kind or len(rows) >= want[kind]:
                continue
            if people(r) & met:
                continue          # the same person is already in this batch
            met |= people(r)
            rows.append(r)
        picked[kind] = rows
        shortfall += want[kind] - len(rows)
    discord = [r for r in pool if r.get("type") == "discord_server"]
    ordered = [r for r in discord if _prefers(r)] + [r for r in discord if not _prefers(r)]
    picked["discord_server"] = ordered[: want["discord_server"] + shortfall]
    return [r for kind, _ in BASE_QUOTA for r in picked.get(kind, [])]


# --------------------------------------------------------------------------- text

def record_phrase(record: dict) -> str:
    """'16-17, -5.05 units over 6 graded nights' from the counted record. Refuses if not negative."""
    try:
        wins, losses = int(record["wins"]), int(record["losses"])
        units, days = float(record["profit_units"]), int(record["days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OutreachError(f"counted MLB record unavailable or incomplete: {exc!r}")
    if units >= 0:
        raise OutreachError(
            f"the counted MLB record is {units:+.2f} units, not negative; scripts.md says "
            "'negative' and 'losses included'. Review the scripts before sending.")
    nights = "graded night" if days == 1 else "graded nights"
    return f"{wins}-{losses}, {units:+.2f} units over {days} {nights}"


def fill(text: str, mlb_record: str, record_url: str) -> str:
    return text.replace("[MLB_RECORD]", mlb_record).replace("[RECORD_URL]", record_url)


NOTE_NAME = "[Name]: the owner's or person's first name or handle, as shown on the server or profile."
NOTE_SERVER = "[Server]: the server's exact name."
NOTE_X = ("The bracket at the start: replace it with one specific thing you actually read in their "
          "post. Open a recent post first; do not paste without one.")


def placeholder_notes(text: str) -> list:
    notes = []
    for token in BRACKET.findall(text):
        if token == "[Name]":
            note = NOTE_NAME
        elif token == "[Server]":
            note = NOTE_SERVER
        elif token.startswith("[One specific thing"):
            note = NOTE_X
        else:
            raise OutreachError(f"unfilled placeholder not understood: {token}")
        if note not in notes:
            notes.append(note)
    return notes


def tailored_first_message(first_line: str, variant_b: str) -> str:
    """ONE first message: the greeting, the line written for this target, then
    Variant B's own disclosure ("I'm not claiming an edge.") and its closing
    yes/no question, taken from the parsed text, never retyped.

    The first draft of batch 1 sent the tailored line alone, a statement with
    nothing to answer, and held Variant B back "until they reply". A cold note
    that asks nothing gets no reply. Variant B's middle sentence (what the
    record is) is left out because every tailored line already says it."""
    sentences = re.split(r"(?<=[.?!])\s+", variant_b.strip())
    greeting = sentences[0] if sentences and sentences[0].lower().startswith("hi ") else "Hi [Name],"
    greeting = greeting.split(",")[0] + ","
    disclosure = next((x for x in sentences if "claiming an edge" in x.lower()), None)
    question = next((x for x in reversed(sentences) if x.endswith("?")), None)
    if disclosure is None or question is None:
        raise OutreachError("Variant B no longer has a disclosure sentence and a closing "
                            "question; scripts.md changed shape")
    opening = first_line.strip()
    # After "Hi [Name]," an ordinary opener reads better in lower case; a
    # proper name ("Unit Circle's ...") keeps its capital.
    if opening.split(" ")[0] in ("You", "Your", "Quick", "Do", "With"):
        opening = opening[0].lower() + opening[1:]
    return " ".join([greeting, opening, disclosure, question])


# What each channel type sends. The queue's message_version and the pipeline's
# message_variant both read this, so a rename happens in one place.
VARIANT_BY_TYPE = {"discord_server": "first_line + Variant B", "creator": "first_line + Variant B",
                   "x_account": "X reply template", "forum": "feedback post + record link"}


def build_item(row: dict, scripts: dict, mlb_record: str, record_url: str) -> dict:
    """One batch item: the exact messages to paste, and what must be filled by hand.

    `record_url` is the link written into the message. build/rebuild pass the
    lead's TAGGED link (tag_url), so the visit is attributed to this lead."""
    kind = row["type"]
    msgs = []
    if kind in ("discord_server", "creator"):
        first = (row.get("first_line") or "").strip()
        if not first:
            raise OutreachError(f"{row['name']}: targets.csv has no first_line")
        msgs.append({"label": "Message (tailored opening + Variant B's disclosure and question)",
                     "cold": True,
                     "text": tailored_first_message(first, fill(scripts["variant_b"],
                                                                mlb_record, record_url))})
        variant = VARIANT_BY_TYPE[kind]
    elif kind == "x_account":
        msgs.append({"label": "Reply (X reply template)", "cold": True,
                     "text": fill(scripts["x_reply"], mlb_record, record_url)})
        variant = VARIANT_BY_TYPE[kind]
    elif kind == "forum":
        body = fill(scripts["post_body"], mlb_record, record_url)
        body = f"{body}\n\nRecord page: {record_url}"
        msgs.append({"label": "Thread title", "cold": False,
                     "text": fill(scripts["post_title"], mlb_record, record_url)})
        msgs.append({"label": "Thread body (ends with the one record link this forum allows)",
                     "cold": False, "text": body})
        variant = VARIANT_BY_TYPE[kind]
    else:
        raise OutreachError(f"{row['name']}: type {kind!r} has no message plan")
    notes = []
    for msg in msgs:
        for note in placeholder_notes(msg["text"]):
            if note not in notes:
                notes.append(note)
    return {"row": row, "messages": msgs, "variant": variant, "notes": notes,
            "record_url": record_url}


def guard_item(item: dict, allowed_edge: tuple) -> list:
    problems = []
    for msg in item["messages"]:
        for p in guard_message(msg["text"], allowed_edge):
            problems.append(f"{msg['label']}: {p}")
        if msg["cold"] and LINK.search(msg["text"]):
            problems.append(f"{msg['label']}: link in a cold message")
    return problems


def channel_rule(row: dict, channels_text: str) -> str:
    """The one line of channels.md that matches the channel, or ''."""
    kind, name = row.get("type"), row.get("name", "")
    if kind == "discord_server":
        key = "No link in the first message"
    elif kind == "x_account":
        key = "Compliant way: reply to a specific post"
    elif kind == "creator":
        key = "No platform rule applies to emailing"
    elif kind == "forum" and "Covers" in name:
        key = "Status: Website Promotions"
    elif kind == "forum" and "TheRX" in name:
        key = "Status: ALLOWED WITH CONDITIONS (post only in this forum)"
    elif kind == "forum" and "TrustMyRecord" in name:
        key = "Status UNKNOWN: read its terms"
    else:
        return ""
    for line in channels_text.splitlines():
        stripped = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line).strip()
        if key in stripped:
            if kind in ("forum", "creator"):  # whole paragraphs: keep just the first relevant sentence
                tail = stripped[stripped.index(key):]
                return re.split(r"(?<=[.])\s", tail, maxsplit=1)[0]
            return stripped
    return ""


def followups(start: date) -> tuple:
    return start + timedelta(days=3), start + timedelta(days=7)


def render_batch(batch: int, items: list, when: date, record_line: str, read_at: str,
                 channels_text: str, verb: str = "build") -> str:
    d3, d7 = followups(when)
    out = [f"# Outreach batch {batch:02d}", ""]
    out.append(f"Generated by `scripts/outreach_batch.py {verb} --batch {batch}` on {when.isoformat()}. "
               "Nothing here has been sent. You send every message yourself, from your own account.")
    out.append("")
    out.append("## Honest-only rules (all five bind every message)")
    out.append("")
    out.append("1. Never claim profit, an edge or a win rate. The only allowed wording is that no edge is claimed.")
    out.append("2. Say the current MLB record is negative, with the number copied live from the record page the day you send.")
    out.append("3. No link in a cold first message; give the record link only when they ask, or where a forum allows it.")
    out.append("4. Disclose that you built it. 21+, bet responsibly. No referral or affiliate links. Never mention Bet Check.")
    out.append("5. One hand-written message per person, no tools or bulk, at most about five new Discord DMs a day. A no ends the thread.")
    out.append("")
    out.append("## Record used in these messages")
    out.append("")
    out.append(f"- {record_line}")
    out.append(f"- Read at {read_at}. Before each send, open the record page and check the number still matches; "
               f"if it has moved, re-run `rebuild --batch {batch}` (same leads, same order) or edit the number by hand.")
    out.append("")
    out.append("## Log what you sent")
    out.append("")
    out.append("After sending, log it so the dashboard moves (item numbers from this file):")
    out.append("")
    out.append("```")
    out.append(f"python scripts/outreach_batch.py sent --batch {batch} --items 1,2,3")
    out.append("```")
    out.append("")
    out.append("When someone answers, signs up, gets access or pays, log it against that lead (ids are in "
               "each item below). What they wrote goes in --said: it is saved to a private local file "
               "and never to the repository.")
    out.append("")
    out.append("```")
    out.append('python scripts/outreach_batch.py reply --lead <lead_id> --type TYPE --said "what they wrote"')
    out.append("python scripts/outreach_batch.py signup|tester-access|activated|feedback|would-pay|paid "
               "--lead <lead_id>")
    out.append("```")
    out.append("")
    out.append("TYPE is one of " + ", ".join(t for t in REPLY_TYPES if t not in ("NO_REPLY",)) + ". "
               "NO_REPLY fills itself in when a message has had no answer for "
               f"{NO_REPLY_DAYS} days; you never type it.")
    out.append("")
    out.append("A forum thread is a post, not a person. When a human answers one (or writes to you on "
               "their own), add them once, then log everything they do against the new id:")
    out.append("")
    out.append("```")
    out.append('python scripts/outreach_batch.py add --via <thread_lead_id> --channel discord '
               '--handle "their handle" --type TYPE --said "what they wrote"')
    out.append('python scripts/outreach_batch.py alias --lead <new_id> --handle "their email or other handle"')
    out.append("```")
    out.append("")
    out.append("If `add` says the handle already belongs to a lead, that human is already in the queue: "
               "use `alias` and log against the existing id. Never put names, handles, emails or quotes "
               "in --note.")
    out.append("")
    out.append(f"Follow-up dates below are counted from {when.isoformat()}; `sent` recomputes them "
               "from the day you log. Follow-up texts: `docs/sales/scripts.md` section (d). "
               "For forums and X, follow up only if the first message was a DM.")
    out.append("")
    out.append("---")
    for n, item in enumerate(items, start=1):
        row = item["row"]
        meta = {"n": n, "type": row["type"], "name": row["name"], "url": row.get("url", ""),
                "contact_path": row.get("contact_path", ""), "variant": item["variant"]}
        if item.get("lead_id"):
            meta["lead_id"] = item["lead_id"]
        out.append("")
        out.append(f"<!--ITEM {json.dumps(meta, ensure_ascii=False)}-->")
        out.append(f"## {n}. {row['name']}")
        out.append("")
        if item.get("lead_id"):
            out.append(f"- Lead: `{item['lead_id']}`")
        out.append(f"- Type: {row['type']}; size: {row.get('size', '')}")
        out.append(f"- Send it here: {row.get('contact_path', '')} -- {row.get('url', '')}")
        rule = f"{row.get('rule_status', '')}"
        line = channel_rule(row, channels_text)
        out.append(f"- Rule first: {rule}" + (f" | channels.md: {line}" if line else ""))
        for note in item["notes"]:
            out.append(f"- Fill by hand: {note}")
        out.append(f"- Follow up: day 3 {d3.isoformat()}, day 7 {d7.isoformat()}")
        if row["type"] != "forum" and item.get("record_url"):
            # Cold messages carry no link; this is the one to paste when they ask for it.
            out.append(f"- Record link, only if they ask for it (tagged for this lead): {item['record_url']}")
        for msg in item["messages"]:
            out.append("")
            out.append(f"**{msg['label']}**")
            out.append("")
            out.append("```")
            out.append(msg["text"])
            out.append("```")
        out.append("")
        out.append("---")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- batch file and pipeline

ITEM_RE = re.compile(r"^<!--ITEM (\{.*\})-->\s*$", re.MULTILINE)


def parse_batch(text: str) -> list:
    return [json.loads(m.group(1)) for m in ITEM_RE.finditer(text)]


def read_pipeline(path: Path) -> tuple:
    """(fieldnames, rows). A missing or empty file gives the standard header and no rows."""
    if not path.exists() or path.stat().st_size == 0:
        return list(PIPELINE_FIELDS), []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or PIPELINE_FIELDS), [dict(r) for r in reader]


def pipeline_names(rows: list) -> set:
    return {norm_name(r.get("target")) for r in rows if (r.get("target") or "").strip()}


def sent_rows(items: list, batch: int, when: date, note: str = "") -> list:
    d3, _ = followups(when)
    rows = []
    for item in items:
        notes = item.get("url", "")
        if note:
            notes = f"{notes} | {note}" if notes else note
        if item.get("lead_id"):
            lead = f"lead_id={item['lead_id']}"
            notes = f"{notes} | {lead}" if notes else lead
        rows.append({"date": when.isoformat(), "source": item["type"], "campaign": f"batch_{batch:02d}",
                     "target": item["name"], "contact_path": item.get("contact_path", ""),
                     "message_variant": item.get("variant", ""), "stage": "sent",
                     "last_touch": when.isoformat(), "next_action": f"follow up {d3.isoformat()}",
                     "revenue": "0", "notes": notes})
    return rows


REPLY_NEXT = {"replied": "answer the reply; send the record link if they asked",
              "demo": "run the demo; ask for the trial",
              "trial": "check in on trial day 3 and day 6",
              "paid": "confirm the subscription is active",
              "lost": "none; stop contact"}


def reply_row(history: list, target: str, stage: str, when: date, revenue: str = "0",
              note: str = "") -> dict:
    """A new row for `target` copied from its latest row. Refuses an unknown target or stage."""
    if stage not in REPLY_STAGES:
        raise OutreachError(f"stage must be one of {', '.join(REPLY_STAGES)}; got {stage!r}")
    rows = [r for r in history if norm_name(r.get("target")) == norm_name(target)]
    if not rows:
        raise OutreachError(f"{target!r} is not in pipeline.csv; log it with `sent` first")
    last = rows[-1]
    if (last.get("stage") or "").strip().lower() == stage:
        raise OutreachError(f"{target!r} is already at stage {stage!r}")
    try:
        float(revenue)
    except ValueError:
        raise OutreachError(f"--revenue must be a number; got {revenue!r}")
    return {"date": when.isoformat(), "source": last.get("source", ""), "campaign": last.get("campaign", ""),
            "target": last.get("target", target), "contact_path": last.get("contact_path", ""),
            "message_variant": last.get("message_variant", ""), "stage": stage,
            "last_touch": when.isoformat(), "next_action": REPLY_NEXT[stage],
            "revenue": revenue, "notes": note}


def append_rows(path: Path, fieldnames: list, new_rows: list) -> str:
    """Append only. Earlier bytes are never touched. LF line endings, CSV quoting."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore",
                            restval="")
    existing = path.read_bytes() if path.exists() else b""
    if not existing:
        writer.writeheader()
    for row in new_rows:
        writer.writerow(row)
    data = buf.getvalue().encode("utf-8")
    if existing and not existing.endswith(b"\n"):
        data = b"\n" + data
    with path.open("ab") as handle:
        handle.write(data)
    return data.decode("utf-8")


def check_new_targets(names: list, existing: set) -> None:
    seen = set()
    for name in names:
        key = norm_name(name)
        if key in existing:
            raise OutreachError(f"{name!r} is already in pipeline.csv; nothing was written")
        if key in seen:
            raise OutreachError(f"{name!r} listed twice; nothing was written")
        seen.add(key)


def parse_items_arg(arg: str, available: set) -> list:
    try:
        nums = [int(p) for p in arg.split(",") if p.strip()]
    except ValueError:
        raise OutreachError(f"--items must be numbers like 1,3,4; got {arg!r}")
    if not nums:
        raise OutreachError("--items is empty")
    missing = [n for n in nums if n not in available]
    if missing:
        raise OutreachError(f"no such item number(s) in the batch file: {missing}")
    return nums


# --------------------------------------------------------------------------- tracked links

def tag_url(base: str, lead_id: str, medium: str, batch: int) -> str:
    """`base` with ?utm_source=<lead_id>&utm_medium=<type>&utm_campaign=batch_NN.

    The query goes BEFORE any #fragment: the record page is a hash route
    (".../index.html#/record-card"), and a query placed after the '#' never
    reaches the server, so the visit would have been unattributed. `base` comes
    from config/business.json public_urls and nowhere else; switching the
    domain later is one config edit plus `rebuild`. A base that already
    carries utm_ parameters is refused rather than overwritten."""
    if not LEAD_ID_RE.match(lead_id or ""):
        raise OutreachError(f"lead id {lead_id!r} is not lowercase letters, digits and hyphens (max 40)")
    if not re.fullmatch(r"[a-z0-9_]+", medium or ""):
        raise OutreachError(f"utm_medium {medium!r} must be lowercase letters, digits and underscores")
    url, hash_mark, fragment = base.partition("#")
    if "utm_" in url:
        raise OutreachError(f"{base!r} already carries utm_ parameters; refusing to overwrite them")
    query = f"utm_source={lead_id}&utm_medium={medium}&utm_campaign=batch_{batch:02d}"
    return f"{url}{'&' if '?' in url else '?'}{query}{hash_mark}{fragment}"


# --------------------------------------------------------------------------- queue

def slugify(name: str, room: int) -> str:
    """Lower-case ascii slug of the part of `name` before any bracket, at most `room` characters."""
    head = unicodedata.normalize("NFKD", name.partition("(")[0]).encode("ascii", "ignore").decode()
    head = head.casefold().replace("'", "")
    slug = re.sub(r"[^a-z0-9]+", "-", head).strip("-") or "lead"
    if len(slug) > room:
        slug = slug[:room].rsplit("-", 1)[0] if "-" in slug[:room] else slug[:room]
    return slug.strip("-") or "lead"


def make_lead_id(number: int, name: str) -> str:
    prefix = f"l{number:03d}-"
    return prefix + slugify(name, 40 - len(prefix))


def parse_ts(text: str) -> datetime:
    """A timezone-aware UTC datetime from 'YYYY-MM-DD' (midnight UTC) or an ISO datetime
    ('Z', an offset, or none = UTC). Raises OutreachError on anything else."""
    raw = (text or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw)
    except ValueError:
        raise OutreachError(f"{text!r} is not an ISO-8601 date or datetime")
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def when_arg(arg, now: datetime = None) -> str:
    """The event time: --at/--date if given, else now. Always 'YYYY-MM-DDTHH:MM:SSZ' UTC."""
    if arg:
        return iso(parse_ts(arg))
    return iso(now or datetime.now(timezone.utc))


def kind_for(source: str) -> str:
    """`channel_post` for a forum thread (a public post, not a human), else `person`."""
    return "channel_post" if (source or "").strip() == "forum" else "person"


def parse_reply_type(raw: str, allow_no_reply: bool = False) -> str:
    """The canonical upper-case reply type for `raw`. Case-insensitive; the old words
    (interested, question, not_interested, auto, hostile) are accepted as aliases.
    Raises OutreachError naming the valid types. NO_REPLY is derived, so it is refused
    here unless the caller asks for it."""
    key = re.sub(r"[\s-]+", "_", (raw or "").strip()).upper()
    key = TYPE_ALIASES.get(key.lower(), key)
    if key not in REPLY_TYPES or (key == "NO_REPLY" and not allow_no_reply):
        valid = [t for t in REPLY_TYPES if t != "NO_REPLY"]
        extra = ("; NO_REPLY is worked out by itself (sent, no answer after "
                 f"{NO_REPLY_DAYS} days) and cannot be typed" if key == "NO_REPLY" else "")
        raise OutreachError(f"type must be one of {', '.join(valid)}; got {raw!r}{extra}")
    return key


def _migrate_type(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return parse_reply_type(raw)
    except OutreachError:
        return raw     # a hand-edited value: keep it visible rather than invent a type


def migrate_row(old: dict) -> dict:
    """A v1 queue row as a v2 row: person = person_channel, channel = source,
    campaign = batch_NN, kind from the source, reply_type = reply_classification (old
    words mapped), would_pay = yes when a would_pay_at was logged. lead_id is untouched:
    it is the utm_source in links that are already live."""
    row = {f: "" for f in QUEUE_FIELDS}
    source = (old.get("source") or "").strip()
    batch = (old.get("batch") or "").strip()
    for field in ("lead_id", "sport_interest", "message_version", "sent_at", "reply_at", "signup_at",
                  "activated_at", "payment_at", "next_followup", "notes", "would_pay_at"):
        row[field] = old.get(field) or ""
    row.update({"kind": kind_for(source), "person": old.get("person_channel") or "", "channel": source,
                "campaign": f"batch_{int(batch):02d}" if batch.isdigit() else "", "batch": batch,
                "reply_type": _migrate_type(old.get("reply_classification")),
                "would_pay": "yes" if (old.get("would_pay_at") or "").strip() else ""})
    return row


def read_queue(path: Path, must_exist: bool = True) -> list:
    """The queue rows, always in v2 shape. A missing file is a refusal unless `must_exist`
    is False. A file with the v1 header is migrated on read (nothing is written until a
    command saves the queue, which always writes v2). Any other header is a refusal: it
    was hand-edited. So is a `kind` that is not channel_post or person."""
    if not path.exists() or path.stat().st_size == 0:
        if must_exist:
            raise OutreachError(f"{path.name} not found; run `scripts/outreach_batch.py seed` first")
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, restval="")
        header = list(reader.fieldnames or [])
        rows = [{k: (v or "") for k, v in r.items() if k} for r in reader]
    if header == OLD_QUEUE_FIELDS:
        return [migrate_row(r) for r in rows]
    if header != QUEUE_FIELDS:
        raise OutreachError(f"{path.name}: header is not the queue schema {QUEUE_FIELDS}")
    for r in rows:
        if r.get("kind") not in KINDS:
            raise OutreachError(f"{path.name}: lead {r.get('lead_id')!r} has kind {r.get('kind')!r}; "
                                f"it must be one of {', '.join(KINDS)}")
    return rows


def write_queue(path: Path, rows: list) -> None:
    """Rewrite the queue (it is an entity store, updated in place) via a temp file and a
    rename, so a crash never leaves half a queue. Always the v2 header. LF endings."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=QUEUE_FIELDS, lineterminator="\n", restval="")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in QUEUE_FIELDS})
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(buf.getvalue().encode("utf-8"))
    tmp.replace(path)


def _row_people(row: dict) -> set:
    return people({"name": row.get("person") or ""})


def find_lead(rows: list, ref: str) -> dict:
    """The one row whose lead_id is `ref`, or failing that whose normalised name is. Refuses unknown."""
    ref = (ref or "").strip()
    if not ref:
        raise OutreachError("--lead is required")
    for row in rows:
        if row["lead_id"] == ref:
            return row
    hits = [r for r in rows if norm_name(r["person"]) == norm_name(ref)]
    if len(hits) == 1:
        return hits[0]
    raise OutreachError(f"unknown lead {ref!r}" if not hits else f"{ref!r} matches several leads")


def _campaign(batch) -> str:
    return f"batch_{int(batch):02d}" if str(batch).isdigit() else ""


def _top_number(rows: list) -> int:
    return max([int(m.group(1)) for r in rows if (m := re.match(r"l(\d+)-", r["lead_id"]))] or [0])


def add_leads(rows: list, specs: list) -> list:
    """Rows plus one new lead per spec ({name, type, sport, batch, [lead_id]}).

    One person is ONE lead, however many channels reach them: a spec whose
    normalised name, or whose people() key (a name inside brackets, a
    possessive first name), matches an existing lead or an earlier spec is
    refused, and nothing is added. A person found by two channels is a second
    way to reach the same lead, never a second lead."""
    out = [dict(r) for r in rows]
    taken_names = {norm_name(r["person"]): r["lead_id"] for r in out}
    taken_people = {}
    for r in out:
        for key in _row_people(r):
            taken_people.setdefault(key, r["lead_id"])
    taken_ids = {r["lead_id"] for r in out}
    top = _top_number(out)
    for spec in specs:
        name = (spec.get("name") or "").strip()
        if not name:
            raise OutreachError("a lead needs a name")
        if norm_name(name) in taken_names:
            raise OutreachError(f"{name!r} is already lead {taken_names[norm_name(name)]}; "
                                "one person is one lead; nothing was written")
        for key in people({"name": name}):
            if key in taken_people:
                raise OutreachError(f"{name!r} is the same person as lead {taken_people[key]} "
                                    f"(shared name {key!r}); one person is one lead; nothing was written")
        lead_id = spec.get("lead_id")
        if lead_id:
            if not LEAD_ID_RE.match(lead_id):
                raise OutreachError(f"lead id {lead_id!r} is not lowercase letters, digits and hyphens (max 40)")
            if lead_id in taken_ids:
                raise OutreachError(f"lead id {lead_id!r} is already used; nothing was written")
        else:
            top += 1
            lead_id = make_lead_id(top, name)
        row = {f: "" for f in QUEUE_FIELDS}
        row.update({"lead_id": lead_id, "kind": kind_for(spec.get("type", "")), "person": name,
                    "channel": spec.get("type", ""), "campaign": _campaign(spec.get("batch", "")),
                    "sport_interest": spec.get("sport", ""),
                    "message_version": VARIANT_BY_TYPE.get(spec.get("type", ""), ""),
                    "batch": str(spec.get("batch", ""))})
        out.append(row)
        taken_ids.add(lead_id)
        taken_names[norm_name(name)] = lead_id
        for key in people({"name": name}):
            taken_people.setdefault(key, lead_id)
    return out


def ensure_leads(rows: list, specs: list) -> tuple:
    """(rows, leads): the lead for each spec, in order. An existing lead (same lead_id or
    same name) is reused; a new one goes through add_leads and its duplicate-person refusal."""
    out = list(rows)
    leads = []
    for spec in specs:
        hit = None
        if spec.get("lead_id"):
            hit = next((r for r in out if r["lead_id"] == spec["lead_id"]), None)
        if hit is None:
            hit = next((r for r in out if norm_name(r["person"]) == norm_name(spec["name"])), None)
        if hit is not None:
            if spec.get("lead_id") and hit["lead_id"] != spec["lead_id"]:
                raise OutreachError(f"{spec['name']!r} is lead {hit['lead_id']} in the queue but "
                                    f"{spec['lead_id']} in the batch file; fix one by hand")
            if norm_name(hit["person"]) != norm_name(spec["name"]):
                raise OutreachError(f"lead {hit['lead_id']} is {hit['person']!r} in the queue "
                                    f"but {spec['name']!r} in the batch file; fix one by hand")
            leads.append(hit)
            continue
        out = add_leads(out, [spec])
        leads.append(out[-1])
    return out, leads


# --------------------------------------------------------------------------- private store

def private_path(root: Path, override=None) -> Path:
    """Where verbatim text and identities live: the argument, else $LINEHOUND_OUTREACH_PRIVATE,
    else data/private/outreach_private.jsonl under `root` (gitignored: the repo is public).
    Tests pass a temp root or an override, so none of them can touch the real file."""
    if override:
        return Path(override)
    env = os.environ.get(PRIVATE_ENV)
    return Path(env) if env else root / PRIVATE_REL


def norm_handle(text: str) -> str:
    """The comparison form of a handle or email: lower case, no spaces, no leading @."""
    return re.sub(r"\s+", "", (text or "").casefold()).lstrip("@")


def private_entry(lead_id: str, at: str, kind: str, text: str, by: str = "owner") -> dict:
    if kind not in PRIVATE_TYPES:
        raise OutreachError(f"private entry type must be one of {', '.join(PRIVATE_TYPES)}; got {kind!r}")
    if by not in PRIVATE_BY:
        raise OutreachError(f"--by must be one of {', '.join(PRIVATE_BY)}; got {by!r}")
    return {"lead_id": lead_id, "at": at, "type": kind, "text": text, "by": by}


def read_private(path: Path) -> list:
    """Every entry, oldest first. A missing file is an empty store. A line that is not a JSON
    object with the five fields is a refusal naming its line number: the store is never
    silently skipped over, because a skipped identity would let a duplicate human in."""
    if not path.exists():
        return []
    entries = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        if not isinstance(entry, dict) or set(entry) != set(PRIVATE_FIELDS):
            raise OutreachError(f"{path.name}: line {number} is not a private-store entry; "
                                "fix or remove that line by hand (the store is append-only)")
        entries.append(entry)
    return entries


def append_private(path: Path, entries: list) -> None:
    """Append only. Earlier bytes are never read back, rewritten or replaced."""
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data = "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in entries).encode("utf-8")
    prior = path.read_bytes() if path.exists() else b""
    if prior and not prior.endswith(b"\n"):
        data = b"\n" + data
    with path.open("ab") as handle:
        handle.write(data)


def public_handles(rows: list) -> dict:
    """Handles already public in the queue's `person` column (for example '(@12Xpert)'):
    normalised handle -> lead_id. A person who is already a lead under one of these is the
    same human."""
    out = {}
    for r in rows:
        for m in re.finditer(r"@([A-Za-z0-9_.]+)", r.get("person") or ""):
            out.setdefault(norm_handle(m.group(1)), r["lead_id"])
    return out


def handle_owner(handle: str, entries: list, rows: list) -> str:
    """The lead_id that already has this handle (private identities first, then the handles
    public in the queue), or ''."""
    key = norm_handle(handle)
    if not key:
        return ""
    for e in entries:
        if e["type"] == "identity" and norm_handle(e["text"]) == key:
            return e["lead_id"]
    return public_handles(rows).get(key, "")


def check_public_text(text: str, flag: str, entries: list) -> str:
    """`text` for a field that lands in a tracked file (--note, --sport). A handle, an email,
    a link, or any identity already in the private store is refused: those belong in
    --handle / --said, which go to the private file."""
    text = (text or "").strip()
    squashed = norm_handle(text)
    known = [norm_handle(e["text"]) for e in entries if e["type"] == "identity"]
    if "@" in text or re.search(r"https?://|www\.", text, re.IGNORECASE) \
            or any(len(k) >= 4 and k in squashed for k in known):
        raise OutreachError(f"{flag} is written to a tracked file in a public repo, so it cannot hold "
                            "a handle, an email, a link or a name from the private store; put them in "
                            "--handle or --said, which go to the private file; nothing was written")
    return text


# --------------------------------------------------------------------------- events

# Event -> the queue field it stamps and the pipeline stage it logs. `reply` stamps
# reply_at once (the first reply) and keeps updating reply_type; `would_pay` keeps the
# CURRENT answer and when it was given; `feedback` keeps the first time.
EVENT_FIELDS = {"sent": "sent_at", "reply": "reply_at", "signup": "signup_at",
                "tester_access": "tester_access_at", "activated": "activated_at",
                "feedback": "feedback_at", "would_pay": "would_pay_at", "paid": "payment_at"}
EVENT_STAGE = {"sent": "sent", "reply": "replied", "signup": "signup", "tester_access": "tester_access",
               "activated": "active", "feedback": "feedback", "would_pay": "would_pay", "paid": "paid",
               "followup": "followup"}
# Things only a human can do. A channel_post (a public thread) cannot do any of them.
HUMAN_EVENTS = ("reply", "signup", "tester_access", "activated", "feedback", "would_pay", "paid")


def _join_note(old: str, new: str) -> str:
    return f"{old} | {new}" if old and new else (old or new)


def _contacted(row: dict) -> bool:
    """We reached them (sent_at) or they reached us (a person added via a channel post, or
    one who wrote in on their own: reply_at)."""
    return any((row.get(f) or "").strip() for f in ("sent_at", "via_lead", "reply_at"))


def apply_event(rows: list, lead_id: str, event: str, when: str, reply_type: str = "",
                revenue: float = None, on: str = "", note: str = "", would_pay: str = "",
                price: float = None) -> tuple:
    """(new_rows, detail): the queue after one event on one lead. Never mutates `rows`.

    A timestamp is set ONCE and never overwritten: a second signup is refused, not
    silently re-dated. A human event needs a person row (a channel post is a public thread,
    not a human) that was sent a message or was added via a post, activation needs a
    signup, and nothing can predate the send. Three events can still move: a reply keeps
    its FIRST reply_at but its reply_type follows the latest classification; a would-pay
    answer replaces the earlier answer and its time (a person can change their mind);
    feedback keeps its first time. A refusal (OutreachError) leaves the caller with nothing
    to write."""
    idx = next((i for i, r in enumerate(rows) if r["lead_id"] == lead_id), None)
    if idx is None:
        raise OutreachError(f"unknown lead {lead_id!r}")
    row = dict(rows[idx])
    when_dt = parse_ts(when)
    if event in HUMAN_EVENTS and row.get("kind") == "channel_post":
        raise OutreachError(f"{lead_id} is a channel post (a public thread), not a person. Log the human who "
                            f"answered it with `add --via {lead_id} --channel <platform> ...`; nothing was written")
    if event == "activated":
        if not row.get("signup_at"):
            raise OutreachError(f"{lead_id}: cannot record {event} before signup; nothing was written")
    elif event != "sent" and not _contacted(row):
        raise OutreachError(f"{lead_id}: cannot record {event} before sent; nothing was written")
    if event not in ("sent", "followup"):    # a follow-up date is a plan, not something that happened
        floor = row.get("sent_at") if event != "activated" else row.get("signup_at")
        if floor and when_dt < parse_ts(floor):
            raise OutreachError(f"{lead_id}: {event} at {when} is earlier than {floor}; nothing was written")
    detail = ""
    if event == "followup":
        try:
            day = date.fromisoformat((on or "").strip())
        except ValueError:
            raise OutreachError(f"--date must be YYYY-MM-DD; got {on!r}")
        row["next_followup"] = day.isoformat()
        detail = f"next_followup={day.isoformat()}"
    elif event == "reply":
        rtype = parse_reply_type(reply_type)
        cur = row.get("reply_type", "")
        if not row.get("reply_at"):
            row["reply_at"], row["reply_type"] = when, rtype
            detail = f"reply_type={rtype}"
        elif rtype == cur:
            detail = f"reply_type={rtype} (unchanged)"
        else:
            row["reply_type"] = rtype
            detail = f"reply_type={cur or 'unset'}->{rtype}"
    elif event == "would_pay":
        answer = (would_pay or "").strip().lower()
        if answer not in ("yes", "no"):
            raise OutreachError(f"would_pay must be yes or no; got {would_pay!r}")
        if price is not None and not (price >= 0 and math.isfinite(price)):
            raise OutreachError(f"--price must be a non-negative number; got {price!r}")
        cur = (row.get("would_pay") or "").strip().lower()
        if cur != answer:
            row["would_pay"], row["would_pay_at"] = answer, when
            detail = f"would_pay={cur}->{answer}" if cur else f"would_pay={answer}"
        else:
            detail = f"would_pay={answer} (unchanged)"
        if price is not None:
            note = _join_note(f"price_signal={price:g}", note)
    elif event == "feedback":
        if not row.get("feedback_at"):
            row["feedback_at"] = when
        else:
            detail = "further feedback (first time kept)"
    else:
        field = EVENT_FIELDS[event]
        if row.get(field):
            raise OutreachError(f"{lead_id}: {event} already recorded at {row[field]}; nothing was written")
        if event == "paid" and revenue is not None and not (revenue >= 0 and math.isfinite(revenue)):
            raise OutreachError(f"--revenue must be a non-negative number; got {revenue!r}")
        row[field] = when
        if event == "sent":
            row["next_followup"] = (when_dt.date() + timedelta(days=FOLLOWUP_DAYS)).isoformat()
        if event == "paid" and revenue is not None:
            detail = f"revenue={revenue:g}"
    if note:
        row["notes"] = _join_note(row.get("notes", ""), note)
    out = list(rows)
    out[idx] = row
    return out, detail


def event_row(lead: dict, event: str, when: str, history: list, revenue: float = None,
              detail: str = "", note: str = "") -> dict:
    """The pipeline.csv event for one command. The audit trail: one row per change, never edited.
    It carries ids, types and timestamps only: no verbatim text and no handle."""
    last = [h for h in history if norm_name(h.get("target")) == norm_name(lead["person"])]
    contact = last[-1].get("contact_path", "") if last else ""
    day = when[:10]
    batch = int(lead["batch"]) if str(lead.get("batch", "")).isdigit() else 0
    nxt = {"sent": f"follow up {lead.get('next_followup', '')}".strip(),
           "reply": REPLY_NEXT["replied"], "paid": REPLY_NEXT["paid"]}.get(event, "")
    notes = f"lead_id={lead['lead_id']}"
    for part in (detail, note):
        notes = _join_note(notes, part)
    return {"date": day, "source": lead.get("channel", ""), "campaign": lead.get("campaign") or f"batch_{batch:02d}",
            "target": lead["person"], "contact_path": contact,
            "message_variant": lead.get("message_version", ""), "stage": EVENT_STAGE[event],
            "last_touch": day, "next_action": nxt,
            "revenue": f"{revenue:g}" if event == "paid" and revenue else "", "notes": notes}


# --------------------------------------------------------------------------- counts

def merge_leads(rows: list) -> tuple:
    """(leads, duplicate_rows): one dict per distinct lead_id, first non-empty value per field.
    Every count is read from this, so a hand-edited queue with a repeated lead_id still
    counts that lead once."""
    merged, order, dup = {}, [], 0
    for r in rows:
        lid = (r.get("lead_id") or "").strip()
        if not lid:
            continue
        if lid not in merged:
            merged[lid] = dict(r)
            order.append(lid)
            continue
        dup += 1
        for k, v in r.items():
            if v and not merged[lid].get(k):
                merged[lid][k] = v
    return [merged[i] for i in order], dup


def _set(row: dict, field: str) -> bool:
    return bool((row.get(field) or "").strip())


def _ts(value) -> datetime:
    """parse_ts, or None for an empty or unreadable value (a count must not crash on a bad cell)."""
    try:
        return parse_ts(value) if (value or "").strip() else None
    except OutreachError:
        return None


def is_person(row: dict) -> bool:
    return (row.get("kind") or "person") != "channel_post"


def effective_reply_type(row: dict, now: datetime) -> str:
    """The reply type to REPORT: the stored one, else NO_REPLY for a person who was sent a
    message, never answered, and was sent it more than NO_REPLY_DAYS days ago. Nobody types it."""
    stored = (row.get("reply_type") or "").strip()
    if stored or not is_person(row) or _set(row, "reply_at"):
        return stored
    sent = _ts(row.get("sent_at"))
    if sent and now - sent > timedelta(days=NO_REPLY_DAYS):
        return "NO_REPLY"
    return ""


def queue_counts(rows: list, now: datetime = None, window: timedelta = TESTER_WINDOW) -> dict:
    """Counts of DISTINCT leads (see the dashboard for the definitions).

    `leads` are person rows with a message sent, a reply or a signup; a queued person nobody
    has contacted (`queued`) and a channel post (`channel_posts_made`) are not leads. A
    channel_post row is a public thread, so only `sent` ever looks at it. `active_testers` are
    persons whose tester access was granted less than `window` before `now`."""
    now = now or datetime.now(timezone.utc)
    merged, dup = merge_leads(rows)
    persons = [r for r in merged if is_person(r)]
    posts = [r for r in merged if not is_person(r)]
    touched = [r for r in persons if any(_set(r, f) for f in ("sent_at", "reply_at", "signup_at"))]
    answer = lambda r: (r.get("would_pay") or "").strip().lower()
    n = lambda seq: sum(1 for _ in seq)
    active = 0
    for r in persons:
        granted = _ts(r.get("tester_access_at"))
        if granted and granted <= now < granted + window:
            active += 1
    replied = [r for r in persons if _set(r, "reply_at")]
    return {"leads": len(touched), "queued": len(persons) - len(touched),
            "channel_posts_made": n(r for r in posts if _set(r, "sent_at")),
            "sent": n(r for r in merged if _set(r, "sent_at")),
            "sent_persons": n(r for r in persons if _set(r, "sent_at")),
            "replies": len(replied),
            "replies_spam": n(r for r in replied if (r.get("reply_type") or "") == "SPAM_OR_IRRELEVANT"),
            "replied_after_sent": n(r for r in persons if _set(r, "sent_at") and _set(r, "reply_at")),
            "positive": n(r for r in persons if (r.get("reply_type") or "") in POSITIVE_TYPES),
            "signups": n(r for r in persons if _set(r, "signup_at")),
            "active_testers": active,
            "activated": n(r for r in persons if _set(r, "activated_at")),
            "would_pay_yes": n(r for r in persons if answer(r) == "yes"),
            "would_pay_no": n(r for r in persons if answer(r) == "no"),
            "paid": n(r for r in persons if _set(r, "payment_at")),
            "duplicate_rows": dup}


def reply_type_counts(rows: list, now: datetime = None) -> dict:
    """Person rows by the reply type reported for them (NO_REPLY derived), every type present
    with its zero, plus UNCLASSIFIED: replied but no type yet."""
    now = now or datetime.now(timezone.utc)
    counts = {t: 0 for t in REPLY_TYPES}
    counts["UNCLASSIFIED"] = 0
    for r in merge_leads(rows)[0]:
        if not is_person(r):
            continue
        kind = effective_reply_type(r, now)
        if kind in counts:
            counts[kind] += 1
        elif kind:
            counts[kind] = counts.get(kind, 0) + 1
        elif _set(r, "reply_at"):
            counts["UNCLASSIFIED"] += 1
    return counts


MILESTONES = (("first_sent", "First message sent"), ("first_reply", "First reply"),
              ("first_positive", "First positive reply (the time of that lead's first reply)"),
              ("first_signup", "First signup"), ("first_tester_access", "First tester access"),
              ("first_active", "First active tester"), ("first_feedback", "First feedback"),
              ("first_would_pay", "First would-pay (yes)"), ("first_payment", "First payment"))


def milestones(rows: list) -> dict:
    """key -> (earliest timestamp, lead_id) of each funnel step, or None. Only person rows count,
    except the first send, which any row can be."""
    leads, _ = merge_leads(rows)

    def first(field, keep=lambda l: is_person(l)):
        stamps = [(_ts(l[field]), l["lead_id"], l[field]) for l in leads
                  if _set(l, field) and keep(l) and _ts(l[field])]
        if not stamps:
            return None
        _, lead_id, text = min(stamps, key=lambda s: (s[0], s[1]))
        return (text, lead_id)
    return {"first_sent": first("sent_at", lambda l: True),
            "first_reply": first("reply_at"),
            "first_positive": first("reply_at", lambda l: is_person(l) and (l.get("reply_type") or "") in POSITIVE_TYPES),
            "first_signup": first("signup_at"), "first_tester_access": first("tester_access_at"),
            "first_active": first("activated_at"), "first_feedback": first("feedback_at"),
            "first_would_pay": first("would_pay_at", lambda l: is_person(l) and (l.get("would_pay") or "").lower() == "yes"),
            "first_payment": first("payment_at")}


def _event_lead_id(event_row_: dict) -> str:
    m = re.search(r"lead_id=([a-z0-9-]+)", event_row_.get("notes") or "")
    return m.group(1) if m else ""


def queue_revenue(rows: list, pipeline_rows: list) -> tuple:
    """(total, unknown): revenue the pipeline's `paid` events recorded for leads that have a
    payment_at, and how many such leads have no revenue figure. Nothing is estimated. An event
    is matched to its lead by the lead_id in its notes, else by the target name."""
    leads, _ = merge_leads(rows)
    paid_events = {}
    for h in pipeline_rows:
        if (h.get("stage") or "").strip().lower() == "paid":
            paid_events[_event_lead_id(h) or "name:" + norm_name(h.get("target"))] = h
    total, unknown = 0.0, 0
    for lead in leads:
        if not _set(lead, "payment_at"):
            continue
        event = paid_events.get(lead["lead_id"]) or paid_events.get("name:" + norm_name(lead["person"])) or {}
        try:
            amount = float(event.get("revenue") or 0)
        except ValueError:
            amount = 0.0
        if amount > 0:
            total += amount
        else:
            unknown += 1
    return total, unknown


def milestone_lines(rows: list) -> list:
    found = milestones(rows)
    return [f"{label}: {found[key][0]} ({found[key][1]})" if found[key] else f"{label}: not yet"
            for key, label in MILESTONES]


def status_lines(rows: list, now: datetime = None) -> list:
    """One line per lead with any activity, then the counts by reply type (zeros shown)."""
    now = now or datetime.now(timezone.utc)
    leads, _ = merge_leads(rows)
    fields = ("sent_at", "reply_at", "signup_at", "tester_access_at", "activated_at", "feedback_at",
              "would_pay", "payment_at")
    day = lambda value: (value or "-")[:10] if (value or "").strip() else "-"
    out = []
    for r in leads:
        if not any(_set(r, f) for f in fields):
            continue
        kind = effective_reply_type(r, now) or ("unclassified" if _set(r, "reply_at") else "-")
        out.append(" | ".join([
            r["lead_id"], r.get("kind", ""), r.get("channel", ""),
            f"group {r.get('send_group') or '-'}", f"sent {day(r.get('sent_at'))}",
            f"reply {kind}" + (f" {day(r.get('reply_at'))}" if _set(r, "reply_at") else ""),
            f"signup {day(r.get('signup_at'))}", f"access {day(r.get('tester_access_at'))}",
            f"active {day(r.get('activated_at'))}", f"feedback {day(r.get('feedback_at'))}",
            f"would_pay {(r.get('would_pay') or '-')}", f"paid {day(r.get('payment_at'))}"]))
    if not out:
        out.append("no lead has any activity yet")
    out.append("")
    out.append("Reply types (people; NO_REPLY is worked out from a send more than "
               f"{NO_REPLY_DAYS} days old with no answer):")
    out.extend(f"  {name}: {count}" for name, count in reply_type_counts(rows, now).items())
    return out


# --------------------------------------------------------------------------- disk

def _read(path: Path, what: str) -> str:
    if not path.exists():
        raise OutreachError(f"{what} not found: {path}")
    return path.read_text(encoding="utf-8")


def _live_record() -> dict:
    from src.report import effective_record
    return effective_record.build()["sports"]["mlb"]["current"]


def _other_batch_names(sales: Path, batch: int) -> set:
    names = set()
    for path in sales.glob("batch_*.md"):
        if path.name == f"batch_{batch:02d}.md":
            continue
        for item in parse_batch(path.read_text(encoding="utf-8")):
            names.add(norm_name(item["name"]))
    return names


def _other_batch_people(sales: Path, batch: int) -> set:
    """`people()` keys for every item in the other batch files."""
    keys = set()
    for path in sales.glob("batch_*.md"):
        if path.name == f"batch_{batch:02d}.md":
            continue
        for item in parse_batch(path.read_text(encoding="utf-8")):
            keys |= people({"name": item["name"]})
    return keys


def _targets(sales: Path) -> list:
    path = sales / "targets.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _spec(row: dict, batch: int, lead_id: str = "") -> dict:
    spec = {"name": row["name"], "type": row.get("type", ""), "sport": row.get("sport_focus", ""),
            "batch": batch}
    if lead_id:
        spec["lead_id"] = lead_id
    return spec


def _context(args, root: Path, record_fn) -> dict:
    """What build and rebuild share: parsed scripts, the guard's allowed phrases, the
    record, and the record URL BASE from config (the only place a base URL comes from)."""
    sales = root / SALES
    scripts_text = _read(sales / "scripts.md", "scripts.md")
    config = json.loads(_read(root / "config" / "business.json", "business.json"))
    base_url = ((config.get("public_urls") or {}).get("record") or "").strip()
    if not base_url:
        raise OutreachError("config/business.json has no public_urls.record")
    record = record_fn()
    mlb_record = record_phrase(record)
    span = record.get("date_span") or {}
    record_line = (f"MLB counted record: {mlb_record} ({span.get('first')} to {span.get('last')}); "
                   "every record-page link below is tagged with the lead (utm_source) and the batch "
                   "(utm_campaign)")
    return {"sales": sales, "scripts": parse_scripts(scripts_text),
            "allowed_edge": allowed_edge_forms(scripts_text),
            "channels_text": _read(sales / "channels.md", "channels.md"),
            "base_url": base_url, "mlb_record": mlb_record, "record_line": record_line,
            "read_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}


def _items_for(ctx: dict, batch: int, rows: list, leads: list) -> list:
    """Build and GUARD every item; any guard hit refuses the whole batch (nothing written)."""
    items = []
    for row, lead in zip(rows, leads):
        link = tag_url(ctx["base_url"], lead["lead_id"], row["type"], batch)
        item = build_item(row, ctx["scripts"], ctx["mlb_record"], link)
        item["lead_id"] = lead["lead_id"]
        items.append(item)
    bad = False
    for n, item in enumerate(items, start=1):
        for problem in guard_item(item, ctx["allowed_edge"]):
            bad = True
            print(f"GUARD item {n} ({item['row']['name']}): {problem}", file=sys.stderr)
            for msg in item["messages"]:
                print(f"  [{msg['label']}] {msg['text']}", file=sys.stderr)
    if bad:
        raise OutreachError("guard hit; batch file not written")
    return items


def cmd_build(args, root: Path, record_fn) -> int:
    sales = root / SALES
    when = date.fromisoformat(args.date) if args.date else date.today()
    ctx = _context(args, root, record_fn)
    targets = _targets(sales)
    out_path = sales / f"batch_{args.batch:02d}.md"
    if out_path.exists():
        raise OutreachError(f"{out_path.name} already exists; use `rebuild --batch {args.batch}` to "
                            "regenerate it with the same leads, or delete it to start over")
    qpath = sales / QUEUE_NAME
    queue = read_queue(qpath, must_exist=False)
    if any(r.get("batch") == str(args.batch) for r in queue):
        raise OutreachError(f"the queue already has leads for batch {args.batch}; "
                            f"use `rebuild --batch {args.batch}`")
    _, history = read_pipeline(sales / "pipeline.csv")
    contacted = pipeline_names(history) | {norm_name(r["person"]) for r in queue}
    met_before = _other_batch_people(sales, args.batch)
    for past in history:
        met_before |= people({"name": past.get("target") or ""})
    for lead in queue:
        met_before |= _row_people(lead)
    chosen = select_targets(targets, contacted, args.size, _other_batch_names(sales, args.batch),
                            exclude_people=met_before)
    new_queue = add_leads(queue, [_spec(r, args.batch) for r in chosen])
    leads = new_queue[len(queue):]
    items = _items_for(ctx, args.batch, chosen, leads)
    text = render_batch(args.batch, items, when, ctx["record_line"], ctx["read_at"], ctx["channels_text"])
    write_queue(qpath, new_queue)
    out_path.write_text(text, encoding="utf-8", newline="\n")
    counts = {}
    for item in items:
        counts[item["row"]["type"]] = counts.get(item["row"]["type"], 0) + 1
    print(f"wrote {out_path.relative_to(root)}: {len(items)} items {counts}; "
          f"{len(leads)} lead(s) added to {qpath.relative_to(root)}")
    return 0


def cmd_rebuild(args, root: Path, record_fn) -> int:
    """Same leads, same order, fresh text and tagged links. It never reselects: the
    names come from the existing batch file, the lead ids from the queue."""
    sales = root / SALES
    out_path = sales / f"batch_{args.batch:02d}.md"
    old_text = _read(out_path, out_path.name)
    old = parse_batch(old_text)
    if not old:
        raise OutreachError(f"{out_path.name} has no items to rebuild")
    if args.date:
        when = date.fromisoformat(args.date)
    else:
        m = re.search(r"\bon (\d{4}-\d{2}-\d{2})\.", old_text)
        when = date.fromisoformat(m.group(1)) if m else date.today()
    qpath = sales / QUEUE_NAME
    queue = read_queue(qpath, must_exist=False)
    _, history = read_pipeline(sales / "pipeline.csv")
    logged = pipeline_names(history)
    by_name = {norm_name(r["name"]): r for r in _targets(sales)}
    rows = []
    for item in old:
        row = by_name.get(norm_name(item["name"]))
        if row is None:
            raise OutreachError(f"{item['name']!r} is in {out_path.name} but not in targets.csv; "
                                "cannot rebuild without reselecting")
        rows.append(row)
    new_queue, leads = ensure_leads(queue, [_spec(r, args.batch, i.get("lead_id", ""))
                                            for r, i in zip(rows, old)])
    sent = [l["person"] for l in leads if l.get("sent_at")]
    sent += [i["name"] for i in old if norm_name(i["name"]) in logged and i["name"] not in sent]
    if sent:
        raise OutreachError(f"{out_path.name} has items already marked sent ({', '.join(sent)}); "
                            "refusing to rebuild a batch that was partly sent")
    ctx = _context(args, root, record_fn)
    items = _items_for(ctx, args.batch, rows, leads)
    text = render_batch(args.batch, items, when, ctx["record_line"], ctx["read_at"],
                        ctx["channels_text"], verb="rebuild")
    if new_queue != queue:
        write_queue(qpath, new_queue)
    out_path.write_text(text, encoding="utf-8", newline="\n")
    print(f"rebuilt {out_path.relative_to(root)}: {len(items)} items, same leads, same order")
    return 0


def cmd_seed(args, root: Path) -> int:
    """A queue row for every item already in a batch file, in file order. Idempotent."""
    sales = root / SALES
    qpath = sales / QUEUE_NAME
    queue = read_queue(qpath, must_exist=False)
    by_name = {norm_name(r["name"]): r for r in _targets(sales)}
    added = 0
    for path in sorted(sales.glob("batch_*.md")):
        m = re.fullmatch(r"batch_(\d+)\.md", path.name)
        if not m:
            continue
        batch = int(m.group(1))
        for item in parse_batch(path.read_text(encoding="utf-8")):
            row = by_name.get(norm_name(item["name"]), {"name": item["name"], "type": item["type"]})
            before = len(queue)
            queue, _ = ensure_leads(queue, [_spec(row, batch, item.get("lead_id", ""))])
            added += len(queue) - before
    if added or not qpath.exists():
        write_queue(qpath, queue)
    print(f"{qpath.relative_to(root)}: {added} lead(s) added, {len(queue)} in total")
    return 0


def _lead_for_item(queue: list, item: dict) -> dict:
    try:
        return find_lead(queue, item.get("lead_id") or item["name"])
    except OutreachError:
        raise OutreachError(f"{item['name']!r} has no lead in the queue; run `seed` or `rebuild` first")


def cmd_sent(args, root: Path, private: Path, now: datetime) -> int:
    sales = root / SALES
    batch_path = sales / f"batch_{args.batch:02d}.md"
    items = parse_batch(_read(batch_path, batch_path.name))
    by_num = {i["n"]: i for i in items}
    nums = parse_items_arg(args.items, set(by_num))
    when = when_arg(args.at, now)
    pipe = sales / "pipeline.csv"
    fields, history = read_pipeline(pipe)
    chosen = [by_num[n] for n in nums]
    check_new_targets([i["name"] for i in chosen], pipeline_names(history))
    qpath = sales / QUEUE_NAME
    queue = read_queue(qpath)
    note = check_public_text(args.note or "", "--note", read_private(private)) if args.note else ""
    tagged = []
    for item in chosen:
        lead = _lead_for_item(queue, item)
        queue, _ = apply_event(queue, lead["lead_id"], "sent", when)
        tagged.append(dict(item, lead_id=lead["lead_id"]))
    new = sent_rows(tagged, args.batch, parse_ts(when).date(), note)
    write_queue(qpath, queue)
    written = append_rows(pipe, fields, new)
    print(f"marked {len(new)} lead(s) sent at {when}; appended {len(new)} row(s) to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    return 0


def _by(args) -> str:
    by = getattr(args, "by", None) or "owner"
    if by not in PRIVATE_BY:
        raise OutreachError(f"--by must be one of {', '.join(PRIVATE_BY)}; got {by!r}")
    return by


def cmd_event(args, root: Path, event: str, private: Path, now: datetime) -> int:
    """reply / signup / tester_access / activated / feedback / would_pay / paid / followup on
    ONE existing lead. Verbatim text (--said) goes to the private store only; the queue and
    pipeline.csv get ids, types and timestamps. Order of writes: private store, queue,
    pipeline, so a failure never loses a verbatim message the queue already shows."""
    sales = root / SALES
    qpath, pipe = sales / QUEUE_NAME, sales / "pipeline.csv"
    queue = read_queue(qpath)
    lead = find_lead(queue, args.lead or args.target)
    lead_id = lead["lead_id"]
    when = when_arg(getattr(args, "at", None), now)
    revenue = getattr(args, "revenue", None)
    on = getattr(args, "on", "") or ""
    said = (getattr(args, "said", None) or "").strip()
    by = _by(args)
    note = args.note or ""
    if note:
        note = check_public_text(note, "--note", read_private(private))
    would_pay = ("no" if getattr(args, "no", False) else "yes") if event == "would_pay" else ""
    new_queue, detail = apply_event(queue, lead_id, event, when,
                                    reply_type=getattr(args, "type", "") or "", revenue=revenue, on=on,
                                    note=note, would_pay=would_pay, price=getattr(args, "price", None))
    updated = next(r for r in new_queue if r["lead_id"] == lead_id)
    if updated == lead and not said:
        raise OutreachError(f"{lead_id}: {event} already recorded; nothing was written")
    lines = []
    if event == "reply":
        if said:
            lines.append(private_entry(lead_id, when, "reply", said, by))
        lines.append(private_entry(lead_id, when, "classification", updated["reply_type"], by))
    elif event in ("feedback", "would_pay") and said:
        lines.append(private_entry(lead_id, when, "feedback", said, by))
    fields, history = read_pipeline(pipe)
    row = event_row(updated, event, when, history, revenue, detail, note)
    append_private(private, lines)
    write_queue(qpath, new_queue)
    written = append_rows(pipe, fields, [row])
    print(f"updated lead {lead_id}: {event} at {when}"
          + (f" ({detail})" if detail else "") + f"; appended 1 event row to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    if lines:
        print(f"private store: {len(lines)} line(s) appended (not shown, not tracked)")
    return 0


def cmd_reply(args, root: Path, private: Path, now: datetime) -> int:
    if args.type and args.stage:
        raise OutreachError("give --type (queue) or --stage (legacy pipeline), not both")
    if args.type:
        return cmd_event(args, root, "reply", private, now)
    if not args.stage:
        raise OutreachError("reply needs --type (or the legacy --stage)")
    if args.said:
        raise OutreachError("--said is saved only with --type; the legacy --stage form writes no private text")
    # Legacy: a pipeline-only stage row. The queue is not touched, so use the
    # --type form (and signup / paid) for anything the dashboard should count.
    sales = root / SALES
    pipe = sales / "pipeline.csv"
    fields, history = read_pipeline(pipe)
    target = args.target or args.lead
    if not target:
        raise OutreachError("--target is required")
    when = date.fromisoformat(args.at[:10]) if args.at else now.date()
    revenue = "0" if args.revenue is None else f"{args.revenue:g}"
    note = check_public_text(args.note or "", "--note", read_private(private)) if args.note else ""
    row = reply_row(history, target, args.stage, when, revenue, note)
    written = append_rows(pipe, fields, [row])
    print(f"appended 1 row to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    print("note: the legacy --stage form writes pipeline.csv only; the outreach queue (which the "
          "dashboard counts) was NOT updated. Use `reply --lead <id> --type ...`.")
    return 0


def _channel(raw: str) -> str:
    """A platform name (discord, x, email, forum_reply), never a handle."""
    channel = re.sub(r"\s+", "_", (raw or "").strip().lower())
    if not re.fullmatch(r"[a-z0-9_]{1,24}", channel):
        raise OutreachError(f"--channel is the platform (for example discord, x, email), up to 24 lower-case "
                            f"letters, digits or underscores; got {raw!r}. Their handle goes in --handle")
    return channel


def cmd_add(args, root: Path, private: Path, now: datetime) -> int:
    """A new human who answered a channel post, or wrote in on their own. The id carries no
    personal data (l041-p); the handle goes to the private store, and is compared with every
    identity already there (and with handles public in the queue) BEFORE anything is created,
    so the same human cannot become two rows."""
    sales = root / SALES
    qpath, pipe = sales / QUEUE_NAME, sales / "pipeline.csv"
    queue = read_queue(qpath)
    via = find_lead(queue, args.via) if args.via else None
    when = when_arg(args.at, now)
    channel = _channel(args.channel)
    rtype = parse_reply_type(args.type) if args.type else ""
    said = (args.said or "").strip()
    by = _by(args)
    entries = read_private(private)
    sport = check_public_text(args.sport or "", "--sport", entries)
    note = check_public_text(args.note or "", "--note", entries)
    handle = (args.handle or "").strip()
    if args.handle is not None and not norm_handle(handle):
        raise OutreachError("--handle is empty")
    if handle:
        owner = handle_owner(handle, entries, queue)
        if owner:
            raise OutreachError(f"that handle already belongs to lead {owner}; that human is already in the "
                                f"queue, so no new row was made. Use `alias --lead {owner} --handle ...` to "
                                f"give them another identity, and log what they did against {owner}")
    lead_id = f"l{_top_number(queue) + 1:03d}-p"
    if any(r["lead_id"] == lead_id for r in queue):
        raise OutreachError(f"lead id {lead_id!r} is already used; nothing was written")
    row = {f: "" for f in QUEUE_FIELDS}
    row.update({"lead_id": lead_id, "kind": "person", "person": lead_id, "channel": channel,
                "campaign": (via or {}).get("campaign") or "organic", "sport_interest": sport,
                "reply_at": when, "reply_type": rtype, "via_lead": (via or {}).get("lead_id", ""),
                "batch": (via or {}).get("batch", ""), "notes": note})
    lines = []
    if handle:
        lines.append(private_entry(lead_id, when, "identity", handle, by))
    if said:
        lines.append(private_entry(lead_id, when, "reply", said, by))
    if rtype:
        lines.append(private_entry(lead_id, when, "classification", rtype, by))
    fields, history = read_pipeline(pipe)
    detail = f"added via {row['via_lead'] or 'own message'}" + (f"; reply_type={rtype}" if rtype else "")
    event = event_row(row, "reply", when, history, detail=detail, note="")
    append_private(private, lines)
    write_queue(qpath, queue + [row])
    written = append_rows(pipe, fields, [event])
    print(f"added lead {lead_id} ({channel}, via {row['via_lead'] or 'nobody: wrote in on their own'}, "
          f"campaign {row['campaign']}); appended 1 event row to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    if lines:
        print(f"private store: {len(lines)} line(s) appended (not shown, not tracked)")
    if not handle:
        print("note: no --handle given, so the duplicate-human check could not run for this person; "
              f"add one later with `alias --lead {lead_id} --handle ...`")
    if not rtype:
        print(f"note: no --type given; classify the reply with `reply --lead {lead_id} --type TYPE`")
    return 0


def cmd_alias(args, root: Path, private: Path, now: datetime) -> int:
    """Another identity (a second platform, an email) for a lead that already exists."""
    queue = read_queue(root / SALES / QUEUE_NAME)
    lead = find_lead(queue, args.lead)
    if not is_person(lead):
        raise OutreachError(f"{lead['lead_id']} is a channel post, not a person; identities belong to people")
    handle = (args.handle or "").strip()
    if not norm_handle(handle):
        raise OutreachError("--handle is empty")
    owner = handle_owner(handle, read_private(private), queue)
    if owner == lead["lead_id"]:
        raise OutreachError(f"that handle is already an identity of {owner}; nothing was written")
    if owner:
        raise OutreachError(f"that handle already belongs to lead {owner}, a different lead; if they are the "
                            f"same human, keep one row and log everything against it; nothing was written")
    append_private(private, [private_entry(lead["lead_id"], when_arg(getattr(args, "at", None), now),
                                           "identity", handle, _by(args))])
    print(f"private store: 1 identity added to {lead['lead_id']} (not shown, not tracked)")
    return 0


def cmd_set_group(args, root: Path) -> int:
    qpath = root / SALES / QUEUE_NAME
    queue = read_queue(qpath)
    ids = [part.strip() for part in (args.leads or "").split(",") if part.strip()]
    if not ids:
        raise OutreachError("--leads is empty; give lead ids like l012-unit-circle,l013-337picks")
    if len(set(ids)) != len(ids):
        raise OutreachError("--leads lists a lead twice; nothing was written")
    if args.group < 1:
        raise OutreachError(f"--group must be a whole number from 1 up; got {args.group}")
    known = {r["lead_id"]: r for r in queue}
    missing = [i for i in ids if i not in known]
    if missing:
        raise OutreachError(f"unknown lead(s) {', '.join(missing)}; nothing was written")
    new = [dict(r, send_group=str(args.group)) if r["lead_id"] in ids else r for r in queue]
    write_queue(qpath, new)
    print(f"send group {args.group}: {len(ids)} lead(s): {', '.join(ids)}")
    return 0


def batch_positions(sales: Path) -> dict:
    """lead_id -> (batch file name, batch number, item number) over every batch file."""
    out = {}
    for path in sorted(sales.glob("batch_*.md")):
        m = re.fullmatch(r"batch_(\d+)\.md", path.name)
        if not m:
            continue
        for item in parse_batch(path.read_text(encoding="utf-8")):
            if item.get("lead_id"):
                out.setdefault(item["lead_id"], (path.name, int(m.group(1)), item["n"]))
    return out


def next_group_lines(rows: list, positions: dict) -> list:
    leads, _ = merge_leads(rows)
    groups = {}
    for r in leads:
        if (r.get("send_group") or "").strip().isdigit():
            groups.setdefault(int(r["send_group"]), []).append(r)
    if not groups:
        return ["No send groups assigned. Assign one with "
                "`python scripts/outreach_batch.py set-group --leads ID,ID,... --group 1`."]
    pending = {g: [r for r in rs if not _set(r, "sent_at")] for g, rs in groups.items()}
    open_groups = sorted(g for g, rs in pending.items() if rs)
    if not open_groups:
        return [f"Every lead in send groups {', '.join(str(g) for g in sorted(groups))} has been sent."]
    g = open_groups[0]
    todo = pending[g]
    out = [f"Send group {g}: {len(todo)} of {len(groups[g])} lead(s) still to send", ""]
    batches = {}
    for r in todo:
        where = positions.get(r["lead_id"])
        out.append(f"- {r['lead_id']} | {r.get('person', '')} | {r.get('channel', '')}")
        if where:
            name, batch, n = where
            out.append(f"    message: docs/sales/{name}, item {n}")
            out.append(f"    after you send it: python scripts/outreach_batch.py sent --batch {batch} --items {n}")
            batches.setdefault(batch, []).append(n)
        else:
            out.append("    (no batch file lists this lead, so there is no `sent` command for it)")
    for batch, nums in sorted(batches.items()):
        if len(nums) > 1:
            out.append("")
            out.append(f"All of batch {batch} in this group, once every one is sent: "
                       f"python scripts/outreach_batch.py sent --batch {batch} --items "
                       + ",".join(str(n) for n in sorted(nums)))
    return out


def cmd_next_group(args, root: Path) -> int:
    rows = read_queue(root / SALES / QUEUE_NAME)
    print("\n".join(next_group_lines(rows, batch_positions(root / SALES))))
    return 0


def cmd_status(args, root: Path, now: datetime) -> int:
    print("\n".join(status_lines(read_queue(root / SALES / QUEUE_NAME), now)))
    return 0


def cmd_milestones(args, root: Path) -> int:
    rows = read_queue(root / SALES / QUEUE_NAME)
    print("\n".join(milestone_lines(rows)))
    return 0


def main(argv=None, root: Path = ROOT, record_fn=None, private_path_override=None, now_fn=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def when_flags(p):
        p.add_argument("--at", "--date", dest="at", default=None,
                       help="UTC time override: YYYY-MM-DD (midnight) or an ISO-8601 datetime")

    def said_flags(p):
        p.add_argument("--said", default=None,
                       help="what they wrote, word for word; goes to the private local file only")
        p.add_argument("--by", default=None, choices=PRIVATE_BY,
                       help="who classified or typed it (default owner)")

    b = sub.add_parser("build")
    b.add_argument("--batch", type=int, required=True)
    b.add_argument("--size", type=int, default=BASE_SIZE)
    b.add_argument("--date", default=None)
    rb = sub.add_parser("rebuild")
    rb.add_argument("--batch", type=int, required=True)
    rb.add_argument("--date", default=None)
    sub.add_parser("seed")
    s = sub.add_parser("sent")
    s.add_argument("--batch", type=int, required=True)
    s.add_argument("--items", required=True)
    s.add_argument("--note", default=None)
    when_flags(s)
    r = sub.add_parser("reply")
    r.add_argument("--lead", default=None)
    r.add_argument("--target", default=None)
    r.add_argument("--type", "--classification", dest="type", default=None,
                   help="one of " + ", ".join(t for t in REPLY_TYPES if t != "NO_REPLY")
                        + " (any case; the old words interested, question, not_interested, hostile, auto work)")
    r.add_argument("--stage", default=None, choices=REPLY_STAGES)
    r.add_argument("--revenue", type=float, default=None)
    r.add_argument("--note", default=None)
    said_flags(r)
    when_flags(r)
    for name in ("signup", "tester-access", "activated", "feedback", "would-pay", "paid"):
        e = sub.add_parser(name)
        e.add_argument("--lead", default=None)
        e.add_argument("--target", default=None)
        e.add_argument("--note", default=None)
        if name == "paid":
            e.add_argument("--revenue", type=float, default=None)
        if name in ("feedback", "would-pay"):
            said_flags(e)
        if name == "would-pay":
            e.add_argument("--no", action="store_true", help="they said they would NOT pay")
            e.add_argument("--price", type=float, default=None, help="the price they named; kept as price_signal=N")
        when_flags(e)
    ad = sub.add_parser("add", help="a new human who answered a channel post or wrote in on their own")
    ad.add_argument("--via", default=None, help="lead id of the channel post they answered")
    ad.add_argument("--channel", required=True, help="the platform: discord, x, email, ...")
    ad.add_argument("--handle", default=None, help="their handle or email; private store only")
    ad.add_argument("--sport", default=None)
    ad.add_argument("--type", "--classification", dest="type", default=None)
    ad.add_argument("--note", default=None)
    said_flags(ad)
    when_flags(ad)
    al = sub.add_parser("alias", help="another identity for a lead that already exists")
    al.add_argument("--lead", required=True)
    al.add_argument("--handle", required=True)
    al.add_argument("--by", default=None, choices=PRIVATE_BY)
    when_flags(al)
    f = sub.add_parser("followup")
    f.add_argument("--lead", default=None)
    f.add_argument("--target", default=None)
    f.add_argument("--date", "--on", dest="on", required=True, help="the next follow-up day, YYYY-MM-DD")
    f.add_argument("--note", default=None)
    sg = sub.add_parser("set-group")
    sg.add_argument("--leads", required=True, help="comma-separated lead ids")
    sg.add_argument("--group", type=int, required=True)
    sub.add_parser("next-group")
    sub.add_parser("status")
    sub.add_parser("milestones")
    args = parser.parse_args(argv)
    now = (now_fn or (lambda: datetime.now(timezone.utc)))()
    private = private_path(root, private_path_override)
    try:
        if args.cmd == "build":
            return cmd_build(args, root, record_fn or _live_record)
        if args.cmd == "rebuild":
            return cmd_rebuild(args, root, record_fn or _live_record)
        if args.cmd == "seed":
            return cmd_seed(args, root)
        if args.cmd == "sent":
            return cmd_sent(args, root, private, now)
        if args.cmd == "reply":
            return cmd_reply(args, root, private, now)
        if args.cmd == "add":
            return cmd_add(args, root, private, now)
        if args.cmd == "alias":
            return cmd_alias(args, root, private, now)
        if args.cmd == "set-group":
            return cmd_set_group(args, root)
        if args.cmd == "next-group":
            return cmd_next_group(args, root)
        if args.cmd == "status":
            return cmd_status(args, root, now)
        if args.cmd == "milestones":
            return cmd_milestones(args, root)
        return cmd_event(args, root, args.cmd.replace("-", "_"), private, now)
    except (OutreachError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
