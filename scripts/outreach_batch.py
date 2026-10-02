"""Prepare outreach batches as paste-ready text, and log what was sent by hand.

Nothing here sends anything. Brey sends every message himself.

    python scripts/outreach_batch.py build --batch 1 [--size 20] [--date YYYY-MM-DD]
    python scripts/outreach_batch.py sent  --batch 1 --items 1,3,4 [--date ...] [--note "..."]
    python scripts/outreach_batch.py reply --target "<name>" --stage replied|demo|trial|paid|lost
                                           [--revenue N] [--note "..."] [--date ...]

build  writes docs/sales/batch_NN.md from docs/sales/targets.csv. Message text is
       PARSED from docs/sales/scripts.md at run time, never retyped here.
sent   appends one stage=sent row per item to docs/sales/pipeline.csv (append only).
reply  appends a NEW row for a target with its new stage (append-only history).

Exit code 2 means a refusal: a missing script section, a guard hit, a duplicate.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SALES = Path("docs") / "sales"
PIPELINE_FIELDS = ["date", "source", "campaign", "target", "contact_path", "message_variant",
                   "stage", "last_touch", "next_action", "revenue", "notes"]
REPLY_STAGES = ("replied", "demo", "trial", "paid", "lost")

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


def build_item(row: dict, scripts: dict, mlb_record: str, record_url: str) -> dict:
    """One batch item: the exact messages to paste, and what must be filled by hand."""
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
        variant = "first_line + Variant B"
    elif kind == "x_account":
        msgs.append({"label": "Reply (X reply template)", "cold": True,
                     "text": fill(scripts["x_reply"], mlb_record, record_url)})
        variant = "X reply template"
    elif kind == "forum":
        body = fill(scripts["post_body"], mlb_record, record_url)
        body = f"{body}\n\nRecord page: {record_url}"
        msgs.append({"label": "Thread title", "cold": False,
                     "text": fill(scripts["post_title"], mlb_record, record_url)})
        msgs.append({"label": "Thread body (ends with the one record link this forum allows)",
                     "cold": False, "text": body})
        variant = "feedback post + record link"
    else:
        raise OutreachError(f"{row['name']}: type {kind!r} has no message plan")
    notes = []
    for msg in msgs:
        for note in placeholder_notes(msg["text"]):
            if note not in notes:
                notes.append(note)
    return {"row": row, "messages": msgs, "variant": variant, "notes": notes}


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
                 channels_text: str) -> str:
    d3, d7 = followups(when)
    out = [f"# Outreach batch {batch:02d}", ""]
    out.append(f"Generated by `scripts/outreach_batch.py build --batch {batch}` on {when.isoformat()}. "
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
               "if it has moved, re-run `build` (nothing is lost) or edit the number by hand.")
    out.append("")
    out.append("## Log what you sent")
    out.append("")
    out.append("After sending, log it so the dashboard moves (item numbers from this file):")
    out.append("")
    out.append("```")
    out.append(f"python scripts/outreach_batch.py sent --batch {batch} --items 1,2,3")
    out.append("```")
    out.append("")
    out.append("When someone replies: "
               "`python scripts/outreach_batch.py reply --target \"<name>\" --stage replied` "
               "(stages: replied, demo, trial, paid, lost).")
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
        out.append("")
        out.append(f"<!--ITEM {json.dumps(meta, ensure_ascii=False)}-->")
        out.append(f"## {n}. {row['name']}")
        out.append("")
        out.append(f"- Type: {row['type']}; size: {row.get('size', '')}")
        out.append(f"- Send it here: {row.get('contact_path', '')} -- {row.get('url', '')}")
        rule = f"{row.get('rule_status', '')}"
        line = channel_rule(row, channels_text)
        out.append(f"- Rule first: {rule}" + (f" | channels.md: {line}" if line else ""))
        for note in item["notes"]:
            out.append(f"- Fill by hand: {note}")
        out.append(f"- Follow up: day 3 {d3.isoformat()}, day 7 {d7.isoformat()}")
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


def cmd_build(args, root: Path, record_fn) -> int:
    sales = root / SALES
    when = date.fromisoformat(args.date) if args.date else date.today()
    scripts_text = _read(sales / "scripts.md", "scripts.md")
    scripts = parse_scripts(scripts_text)
    allowed_edge = allowed_edge_forms(scripts_text)
    channels_text = _read(sales / "channels.md", "channels.md")
    with (sales / "targets.csv").open(encoding="utf-8", newline="") as handle:
        targets = list(csv.DictReader(handle))
    config = json.loads(_read(root / "config" / "business.json", "business.json"))
    record_url = ((config.get("public_urls") or {}).get("record") or "").strip()
    if not record_url:
        raise OutreachError("config/business.json has no public_urls.record")
    record = record_fn()
    mlb_record = record_phrase(record)
    span = record.get("date_span") or {}
    record_line = (f"MLB counted record: {mlb_record} ({span.get('first')} to {span.get('last')}); "
                   f"record page: {record_url}")
    read_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    _, history = read_pipeline(sales / "pipeline.csv")
    contacted = pipeline_names(history)
    out_path = sales / f"batch_{args.batch:02d}.md"
    if out_path.exists():
        already = [i["name"] for i in parse_batch(out_path.read_text(encoding="utf-8"))
                   if norm_name(i["name"]) in contacted]
        if already:
            raise OutreachError(f"{out_path.name} already has logged items ({', '.join(already)}); "
                                "refusing to overwrite a batch that was partly sent")
    met_before = _other_batch_people(sales, args.batch)
    for past in history:
        met_before |= people({"name": past.get("target") or ""})
    chosen = select_targets(targets, contacted, args.size, _other_batch_names(sales, args.batch),
                            exclude_people=met_before)
    items = [build_item(r, scripts, mlb_record, record_url) for r in chosen]
    bad = False
    for n, item in enumerate(items, start=1):
        for problem in guard_item(item, allowed_edge):
            bad = True
            print(f"GUARD item {n} ({item['row']['name']}): {problem}", file=sys.stderr)
            for msg in item["messages"]:
                print(f"  [{msg['label']}] {msg['text']}", file=sys.stderr)
    if bad:
        raise OutreachError("guard hit; batch file not written")
    text = render_batch(args.batch, items, when, record_line, read_at, channels_text)
    out_path.write_text(text, encoding="utf-8", newline="\n")
    counts = {}
    for item in items:
        counts[item["row"]["type"]] = counts.get(item["row"]["type"], 0) + 1
    print(f"wrote {out_path.relative_to(root)}: {len(items)} items {counts}")
    return 0


def cmd_sent(args, root: Path) -> int:
    sales = root / SALES
    batch_path = sales / f"batch_{args.batch:02d}.md"
    items = parse_batch(_read(batch_path, batch_path.name))
    by_num = {i["n"]: i for i in items}
    nums = parse_items_arg(args.items, set(by_num))
    when = date.fromisoformat(args.date) if args.date else date.today()
    pipe = sales / "pipeline.csv"
    fields, history = read_pipeline(pipe)
    chosen = [by_num[n] for n in nums]
    check_new_targets([i["name"] for i in chosen], pipeline_names(history))
    new = sent_rows(chosen, args.batch, when, args.note or "")
    written = append_rows(pipe, fields, new)
    print(f"appended {len(new)} row(s) to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    return 0


def cmd_reply(args, root: Path) -> int:
    sales = root / SALES
    pipe = sales / "pipeline.csv"
    fields, history = read_pipeline(pipe)
    when = date.fromisoformat(args.date) if args.date else date.today()
    revenue = "0" if args.revenue is None else f"{args.revenue:g}"
    row = reply_row(history, args.target, args.stage, when, revenue, args.note or "")
    written = append_rows(pipe, fields, [row])
    print(f"appended 1 row to {pipe.relative_to(root)}:")
    sys.stdout.write(written)
    print("note: survival_dashboard.pipeline_counts counts every row, so this target now adds one "
          "more to 'Leads contacted' until the dashboard counts distinct targets.")
    return 0


def main(argv=None, root: Path = ROOT, record_fn=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--batch", type=int, required=True)
    b.add_argument("--size", type=int, default=BASE_SIZE)
    b.add_argument("--date", default=None)
    s = sub.add_parser("sent")
    s.add_argument("--batch", type=int, required=True)
    s.add_argument("--items", required=True)
    s.add_argument("--date", default=None)
    s.add_argument("--note", default=None)
    r = sub.add_parser("reply")
    r.add_argument("--target", required=True)
    r.add_argument("--stage", required=True, choices=REPLY_STAGES)
    r.add_argument("--revenue", type=float, default=None)
    r.add_argument("--note", default=None)
    r.add_argument("--date", default=None)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "build":
            return cmd_build(args, root, record_fn or _live_record)
        if args.cmd == "sent":
            return cmd_sent(args, root)
        return cmd_reply(args, root)
    except (OutreachError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
