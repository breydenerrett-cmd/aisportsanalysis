"""Prepare outreach batches as paste-ready text, and log what was sent by hand.

Nothing here sends anything. Brey sends every message himself.

    python scripts/outreach_batch.py build --batch 1 [--size 20] [--date YYYY-MM-DD]
    python scripts/outreach_batch.py rebuild --batch 1 [--date YYYY-MM-DD]
    python scripts/outreach_batch.py seed
    python scripts/outreach_batch.py sent  --batch 1 --items 1,3,4 [--date|--at ...] [--note "..."]
    python scripts/outreach_batch.py reply --lead l012-unit-circle --classification interested
                                           [--at ...] [--note "..."]
    python scripts/outreach_batch.py signup|activated|would-pay --lead <id> [--at ...]
    python scripts/outreach_batch.py paid  --lead <id> [--revenue N] [--at ...]
    python scripts/outreach_batch.py followup --lead <id> --date YYYY-MM-DD
    python scripts/outreach_batch.py milestones
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
reply, signup, activated, would-pay, paid, followup
         each UPDATE one lead's row (a timestamp is set once and never overwritten)
         and append one event row to pipeline.csv. They never add a lead.
milestones  prints the first timestamp of each funnel step.

Exit code 2 means a refusal: a missing script section, a guard hit, a duplicate person,
an unknown lead, an illegal transition (reply before sent). A refusal writes nothing.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
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

# The canonical outreach queue: ONE row per lead (a person or community), the
# entity store every count and milestone is read from. `batch` and `would_pay_at`
# ride after the owner's thirteen fields. pipeline.csv stays the append-only
# event history beside it (one row per command, never edited).
QUEUE_NAME = "outreach_queue.csv"
QUEUE_FIELDS = ["lead_id", "person_channel", "source", "sport_interest", "message_version",
                "sent_at", "reply_at", "reply_classification", "signup_at", "activated_at",
                "payment_at", "next_followup", "notes", "batch", "would_pay_at"]
CLASSIFICATIONS = ("interested", "not_interested", "question", "hostile", "auto")
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
    out.append("When someone replies, signs up or pays, update that lead (ids are in each item below):")
    out.append("")
    out.append("```")
    out.append("python scripts/outreach_batch.py reply --lead <lead_id> "
               "--classification interested|not_interested|question|hostile|auto")
    out.append("python scripts/outreach_batch.py signup|activated|would-pay|paid --lead <lead_id>")
    out.append("```")
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


def read_queue(path: Path, must_exist: bool = True) -> list:
    """The queue rows. A missing file is a refusal unless `must_exist` is False; a file
    whose header is not exactly QUEUE_FIELDS is always a refusal (it was hand-edited)."""
    if not path.exists() or path.stat().st_size == 0:
        if must_exist:
            raise OutreachError(f"{path.name} not found; run `scripts/outreach_batch.py seed` first")
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if list(reader.fieldnames or []) != QUEUE_FIELDS:
            raise OutreachError(f"{path.name}: header is not the queue schema {QUEUE_FIELDS}")
        return [dict(r) for r in reader]


def write_queue(path: Path, rows: list) -> None:
    """Rewrite the queue (it is an entity store, updated in place) via a temp file and a
    rename, so a crash never leaves half a queue. LF endings."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=QUEUE_FIELDS, lineterminator="\n", restval="")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in QUEUE_FIELDS})
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(buf.getvalue().encode("utf-8"))
    tmp.replace(path)


def _row_people(row: dict) -> set:
    return people({"name": row.get("person_channel") or ""})


def find_lead(rows: list, ref: str) -> dict:
    """The one row whose lead_id is `ref`, or failing that whose normalised name is. Refuses unknown."""
    ref = (ref or "").strip()
    if not ref:
        raise OutreachError("--lead is required")
    for row in rows:
        if row["lead_id"] == ref:
            return row
    hits = [r for r in rows if norm_name(r["person_channel"]) == norm_name(ref)]
    if len(hits) == 1:
        return hits[0]
    raise OutreachError(f"unknown lead {ref!r}" if not hits else f"{ref!r} matches several leads")


def add_leads(rows: list, specs: list) -> list:
    """Rows plus one new lead per spec ({name, type, sport, batch, [lead_id]}).

    One person is ONE lead, however many channels reach them: a spec whose
    normalised name, or whose people() key (a name inside brackets, a
    possessive first name), matches an existing lead or an earlier spec is
    refused, and nothing is added. A person found by two channels is a second
    way to reach the same lead, never a second lead."""
    out = [dict(r) for r in rows]
    taken_names = {norm_name(r["person_channel"]): r["lead_id"] for r in out}
    taken_people = {}
    for r in out:
        for key in _row_people(r):
            taken_people.setdefault(key, r["lead_id"])
    taken_ids = {r["lead_id"] for r in out}
    top = max([int(m.group(1)) for r in out if (m := re.match(r"l(\d+)-", r["lead_id"]))] or [0])
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
        row.update({"lead_id": lead_id, "person_channel": name, "source": spec.get("type", ""),
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
            hit = next((r for r in out if norm_name(r["person_channel"]) == norm_name(spec["name"])), None)
        if hit is not None:
            if spec.get("lead_id") and hit["lead_id"] != spec["lead_id"]:
                raise OutreachError(f"{spec['name']!r} is lead {hit['lead_id']} in the queue but "
                                    f"{spec['lead_id']} in the batch file; fix one by hand")
            if norm_name(hit["person_channel"]) != norm_name(spec["name"]):
                raise OutreachError(f"lead {hit['lead_id']} is {hit['person_channel']!r} in the queue "
                                    f"but {spec['name']!r} in the batch file; fix one by hand")
            leads.append(hit)
            continue
        out = add_leads(out, [spec])
        leads.append(out[-1])
    return out, leads


# Event -> the queue field it stamps, the field that must already be set, the pipeline stage it logs.
EVENT_FIELDS = {"sent": "sent_at", "reply": "reply_at", "signup": "signup_at",
                "activated": "activated_at", "would_pay": "would_pay_at", "paid": "payment_at"}
EVENT_NEEDS = {"reply": "sent_at", "signup": "sent_at", "activated": "signup_at",
               "would_pay": "sent_at", "paid": "sent_at", "followup": "sent_at"}
EVENT_STAGE = {"sent": "sent", "reply": "replied", "signup": "signup", "activated": "active",
               "would_pay": "would_pay", "paid": "paid", "followup": "followup"}


def _join_note(old: str, new: str) -> str:
    return f"{old} | {new}" if old and new else (old or new)


def apply_event(rows: list, lead_id: str, event: str, when: str, classification: str = "",
                revenue: float = None, on: str = "", note: str = "") -> tuple:
    """(new_rows, detail): the queue after one event on one lead. Never mutates `rows`.

    A timestamp is set ONCE and never overwritten: a second signup is refused,
    not silently re-dated. Events cannot happen before the lead was sent, and
    activation cannot precede signup. A reply is the one field that can still
    move: its classification may be corrected, but reply_at stays the first
    reply; the exception is an `auto` reply (an out-of-office or a bot), which
    is not a reply at all, so the first real one replaces it and its own time
    becomes reply_at. A refusal (OutreachError) leaves the caller with nothing to write."""
    idx = next((i for i, r in enumerate(rows) if r["lead_id"] == lead_id), None)
    if idx is None:
        raise OutreachError(f"unknown lead {lead_id!r}")
    row = dict(rows[idx])
    when_dt = parse_ts(when)
    need = EVENT_NEEDS.get(event)
    if need and not row.get(need):
        raise OutreachError(f"{lead_id}: cannot record {event} before {need[:-3]}; nothing was written")
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
        cls = (classification or "").strip().lower()
        if cls not in CLASSIFICATIONS:
            raise OutreachError(f"classification must be one of {', '.join(CLASSIFICATIONS)}; got {classification!r}")
        cur = row.get("reply_classification", "")
        if not row.get("reply_at") or (cur == "auto" and cls != "auto"):
            row["reply_at"], row["reply_classification"] = when, cls
        elif cls == cur or cls == "auto":
            raise OutreachError(f"{lead_id}: reply already recorded as {cur!r}; nothing was written")
        else:
            row["reply_classification"] = cls
            note = _join_note(f"classification {cur} -> {cls} at {when}", note)
        detail = f"classification={cls}"
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
    """The pipeline.csv event for one command. The audit trail: one row per change, never edited."""
    last = [h for h in history if norm_name(h.get("target")) == norm_name(lead["person_channel"])]
    contact = last[-1].get("contact_path", "") if last else ""
    day = when[:10]
    batch = int(lead["batch"]) if str(lead.get("batch", "")).isdigit() else 0
    nxt = {"sent": f"follow up {lead.get('next_followup', '')}".strip(),
           "reply": REPLY_NEXT["replied"], "paid": REPLY_NEXT["paid"]}.get(event, "")
    notes = f"lead_id={lead['lead_id']}"
    for part in (detail, note):
        notes = _join_note(notes, part)
    return {"date": day, "source": lead.get("source", ""), "campaign": f"batch_{batch:02d}",
            "target": lead["person_channel"], "contact_path": contact,
            "message_variant": lead.get("message_version", ""), "stage": EVENT_STAGE[event],
            "last_touch": day, "next_action": nxt,
            "revenue": f"{revenue:g}" if event == "paid" and revenue else "", "notes": notes}


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


def queue_counts(rows: list) -> dict:
    """Counts of DISTINCT leads. `replies` excludes auto-replies (`auto_replies` counts
    them apart); `replied_any` is both. `paid` is leads with a payment_at."""
    leads, dup = merge_leads(rows)
    has = lambda f: sum(1 for l in leads if (l.get(f) or "").strip())
    auto = sum(1 for l in leads if (l.get("reply_at") or "").strip()
               and (l.get("reply_classification") or "").strip() == "auto")
    any_reply = has("reply_at")
    return {"leads": len(leads), "sent": has("sent_at"), "replied_any": any_reply,
            "auto_replies": auto, "replies": any_reply - auto, "signups": has("signup_at"),
            "activated": has("activated_at"), "would_pay": has("would_pay_at"),
            "paid": has("payment_at"), "duplicate_rows": dup}


MILESTONES = (("first_sent", "First message sent"), ("first_reply", "First real reply (not auto)"),
              ("first_interested", "First interested reply"), ("first_signup", "First signup"),
              ("first_active", "First active user"), ("first_would_pay", "First would-pay"),
              ("first_payment", "First payment"))


def milestones(rows: list) -> dict:
    """key -> the earliest timestamp (string) of each funnel step, or None. 'First real reply'
    skips `auto`; 'first interested' is the reply_at of the earliest lead classified interested."""
    leads, _ = merge_leads(rows)

    def first(field, keep=lambda l: True):
        stamps = [(parse_ts(l[field]), l[field]) for l in leads if (l.get(field) or "").strip() and keep(l)]
        return min(stamps)[1] if stamps else None
    return {"first_sent": first("sent_at"),
            "first_reply": first("reply_at", lambda l: l.get("reply_classification") != "auto"),
            "first_interested": first("reply_at", lambda l: l.get("reply_classification") == "interested"),
            "first_signup": first("signup_at"), "first_active": first("activated_at"),
            "first_would_pay": first("would_pay_at"), "first_payment": first("payment_at")}


def queue_revenue(rows: list, pipeline_rows: list) -> tuple:
    """(total, unknown): revenue the pipeline's `paid` events recorded for leads that have a
    payment_at, and how many such leads have no revenue figure. Nothing is estimated."""
    leads, _ = merge_leads(rows)
    paid_events = {}
    for h in pipeline_rows:
        if (h.get("stage") or "").strip().lower() == "paid":
            paid_events[norm_name(h.get("target"))] = h
    total, unknown = 0.0, 0
    for lead in leads:
        if not (lead.get("payment_at") or "").strip():
            continue
        try:
            amount = float((paid_events.get(norm_name(lead["person_channel"])) or {}).get("revenue") or 0)
        except ValueError:
            amount = 0.0
        if amount > 0:
            total += amount
        else:
            unknown += 1
    return total, unknown


def milestone_lines(rows: list) -> list:
    found = milestones(rows)
    return [f"{label}: {found[key] or 'not yet'}" for key, label in MILESTONES]


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
    contacted = pipeline_names(history) | {norm_name(r["person_channel"]) for r in queue}
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
    sent = [l["person_channel"] for l in leads if l.get("sent_at")]
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


def cmd_sent(args, root: Path) -> int:
    sales = root / SALES
    batch_path = sales / f"batch_{args.batch:02d}.md"
    items = parse_batch(_read(batch_path, batch_path.name))
    by_num = {i["n"]: i for i in items}
    nums = parse_items_arg(args.items, set(by_num))
    when = when_arg(args.at)
    pipe = sales / "pipeline.csv"
    fields, history = read_pipeline(pipe)
    chosen = [by_num[n] for n in nums]
    check_new_targets([i["name"] for i in chosen], pipeline_names(history))
    qpath = sales / QUEUE_NAME
    queue = read_queue(qpath)
    tagged = []
    for item in chosen:
        lead = _lead_for_item(queue, item)
        queue, _ = apply_event(queue, lead["lead_id"], "sent", when)
        tagged.append(dict(item, lead_id=lead["lead_id"]))
    new = sent_rows(tagged, args.batch, parse_ts(when).date(), args.note or "")
    write_queue(qpath, queue)
    written = append_rows(pipe, fields, new)
    print(f"marked {len(new)} lead(s) sent at {when}; appended {len(new)} row(s) to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    return 0


def cmd_event(args, root: Path, event: str) -> int:
    """reply / signup / activated / would_pay / paid / followup on ONE existing lead."""
    sales = root / SALES
    qpath, pipe = sales / QUEUE_NAME, sales / "pipeline.csv"
    queue = read_queue(qpath)
    lead = find_lead(queue, args.lead or args.target)
    when = when_arg(getattr(args, "at", None))
    revenue = getattr(args, "revenue", None)
    on = getattr(args, "on", "") or ""
    queue, detail = apply_event(queue, lead["lead_id"], event, when,
                                classification=getattr(args, "classification", "") or "",
                                revenue=revenue, on=on, note=args.note or "")
    fields, history = read_pipeline(pipe)
    updated = next(r for r in queue if r["lead_id"] == lead["lead_id"])
    row = event_row(updated, event, when, history, revenue, detail, args.note or "")
    write_queue(qpath, queue)
    written = append_rows(pipe, fields, [row])
    print(f"updated lead {updated['lead_id']}: {event} at {when}"
          + (f" ({detail})" if detail else "") + f"; appended 1 event row to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    return 0


def cmd_reply(args, root: Path) -> int:
    if args.classification and args.stage:
        raise OutreachError("give --classification (queue) or --stage (legacy pipeline), not both")
    if args.classification:
        return cmd_event(args, root, "reply")
    if not args.stage:
        raise OutreachError("reply needs --classification (or the legacy --stage)")
    # Legacy: a pipeline-only stage row. The queue is not touched, so use the
    # classification form (and signup / paid) for anything the dashboard should count.
    sales = root / SALES
    pipe = sales / "pipeline.csv"
    fields, history = read_pipeline(pipe)
    target = args.target or args.lead
    if not target:
        raise OutreachError("--target is required")
    when = date.fromisoformat(args.at[:10]) if args.at else date.today()
    revenue = "0" if args.revenue is None else f"{args.revenue:g}"
    row = reply_row(history, target, args.stage, when, revenue, args.note or "")
    written = append_rows(pipe, fields, [row])
    print(f"appended 1 row to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    print("note: the legacy --stage form writes pipeline.csv only; the outreach queue (which the "
          "dashboard counts) was NOT updated. Use `reply --lead <id> --classification ...`.")
    return 0


def cmd_milestones(args, root: Path) -> int:
    rows = read_queue(root / SALES / QUEUE_NAME)
    print("\n".join(milestone_lines(rows)))
    return 0


def main(argv=None, root: Path = ROOT, record_fn=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def when_flags(p):
        p.add_argument("--at", "--date", dest="at", default=None,
                       help="UTC time override: YYYY-MM-DD (midnight) or an ISO-8601 datetime")

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
    r.add_argument("--classification", default=None)
    r.add_argument("--stage", default=None, choices=REPLY_STAGES)
    r.add_argument("--revenue", type=float, default=None)
    r.add_argument("--note", default=None)
    when_flags(r)
    for name in ("signup", "activated", "would-pay", "paid"):
        e = sub.add_parser(name)
        e.add_argument("--lead", default=None)
        e.add_argument("--target", default=None)
        e.add_argument("--note", default=None)
        if name == "paid":
            e.add_argument("--revenue", type=float, default=None)
        when_flags(e)
    f = sub.add_parser("followup")
    f.add_argument("--lead", default=None)
    f.add_argument("--target", default=None)
    f.add_argument("--date", "--on", dest="on", required=True, help="the next follow-up day, YYYY-MM-DD")
    f.add_argument("--note", default=None)
    sub.add_parser("milestones")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "build":
            return cmd_build(args, root, record_fn or _live_record)
        if args.cmd == "rebuild":
            return cmd_rebuild(args, root, record_fn or _live_record)
        if args.cmd == "seed":
            return cmd_seed(args, root)
        if args.cmd == "sent":
            return cmd_sent(args, root)
        if args.cmd == "reply":
            return cmd_reply(args, root)
        if args.cmd == "milestones":
            return cmd_milestones(args, root)
        return cmd_event(args, root, args.cmd.replace("-", "_"))
    except (OutreachError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
