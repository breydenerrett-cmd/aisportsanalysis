"""The daily Good call / Bad call digest: what members said about the hounds in a day, per hound and per chip, a markdown
file for the owners, the flagged issues filed in docs/BACKLOG.md, and the resolution that tells the members a fix shipped.

    python -m src.cli hounds feedback-digest --date 2026-10-24 [--backlog]
    python -m src.cli hounds feedback-resolve --id FB-1A2B3C4D --note "Prices now use the average line."

WHY A CLI AND NOT A DASHBOARD (owner request 2026-10-25, docs/TODO_UNTIL_SUNDAY.md item 3): the owners read a file, and the
backlog is a file; a scheduled run (or a person) calls it once a day. It reads ONE table (``hound_feedback_current``, the
latest row per person and target) and calls NO model: nothing here costs money, and nothing here touches a hound.

THE DAY. ``--date D`` is the Pacific calendar day D (midnight to midnight, 24 hours but for the two clock-change days), since
the owners live in Pacific time. The window ends before D+1 begins, so a run the morning after sees a finished day. The
Pacific offset is computed from the US clock-change rule below rather than from tzdata, which a Windows box may not have.

WHERE THE FILE GOES. ``FEEDBACK_DIGEST_DIR``, else ``feedback/`` beside the app database (the Fly volume in production),
the same convention as Jarvis (``jarvis/``, src/jarvis/brief.py ``output_dir``). The file is ``digest-<date>.md``.

THE BACKLOG. With ``--backlog`` each NEW flagged issue is one line in docs/BACKLOG.md and one row in
``hound_feedback_issues``. An issue is a chip chosen on at least ``ISSUE_CHIP_MIN`` current Bad calls for the same hound in the
window, or any single vote that carries a note. Its id is stable (a hash of what makes it that issue), so a re-run adds nothing:
the id is looked for in the file before a line is written. A re-run still attaches votes that arrived since, so every member
who voted hears about the fix. The vote text is cleaned before it reaches the file (one line, no brackets or backticks, clipped).

THE EMAIL HOOK is OFF unless ``FEEDBACK_DIGEST_TO`` (comma-separated addresses) is set AND Resend is configured
(src/notify/email.py: ``RESEND_API_KEY``). Either missing, the file is all there is. No address or key is in the repo.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from src.hounds.interact import store

ISSUE_CHIP_MIN = 2                 # the same chip on this many current Bad calls for one hound, in the window
NOTES_PER_HOUND = 3
NOTE_CLIP = 120                    # a note as it appears in the digest and the backlog
ENV_DIR = "FEEDBACK_DIGEST_DIR"
ENV_TO = "FEEDBACK_DIGEST_TO"
BACKLOG_SECTION = "## Member feedback (flagged by the daily digest)"
BACKLOG_HEADER = (
    "# Backlog\n\n"
    "Parked owner requests and follow-ups. Highest priority first within each group. Move an item to a worker brief\n"
    "when it starts; strike it when it ships.\n"
)
_WEEK = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# ---------------------------------------------------------------------------
# Pacific time without tzdata
# ---------------------------------------------------------------------------

def _nth_sunday(year: int, month: int, n: int) -> date_cls:
    first = date_cls(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def _dst_bounds(year: int) -> tuple:
    """US clock change in UTC: 2 AM PST on the second Sunday of March (10:00Z) to 2 AM PDT on the first Sunday of November (09:00Z)."""
    start = _nth_sunday(year, 3, 2)
    end = _nth_sunday(year, 11, 1)
    return (datetime(start.year, start.month, start.day, 10, tzinfo=timezone.utc),
            datetime(end.year, end.month, end.day, 9, tzinfo=timezone.utc))


def pacific_offset_hours(moment: datetime) -> int:
    """-7 in daylight time, -8 otherwise, for a UTC moment."""
    start, end = _dst_bounds(moment.astimezone(timezone.utc).year)
    return -7 if start <= moment < end else -8


def pt_text(moment: datetime) -> str:
    """"Thu Oct 22 4:05 PM PT": a time as the owners read it."""
    local = moment.astimezone(timezone.utc) + timedelta(hours=pacific_offset_hours(moment))
    hour = local.hour % 12 or 12
    return f"{_WEEK[local.weekday()]} {_MONTH[local.month - 1]} {local.day} {hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} PT"


def pacific_midnight(day: date_cls) -> datetime:
    """The UTC moment a Pacific calendar day begins."""
    daylight = datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc)
    start, end = _dst_bounds(day.year)
    return daylight if start <= daylight < end else datetime(day.year, day.month, day.day, 8, tzinfo=timezone.utc)


def window_for(date: str) -> tuple:
    """``(start, end)`` in UTC for the Pacific day ``date`` (YYYY-MM-DD); ValueError for anything else."""
    day = date_cls.fromisoformat(date)
    return pacific_midnight(day), pacific_midnight(day + timedelta(days=1))


# ---------------------------------------------------------------------------
# building the digest
# ---------------------------------------------------------------------------

def clean_line(text, limit: int = NOTE_CLIP) -> str:
    """A member's words as one safe line for a markdown file the owners and the repo keep: whitespace folded, brackets, backticks
    and angle brackets removed (so a note cannot forge a ``[FB-...]`` id, a link or a tag), clipped."""
    one = " ".join(str(text or "").split())
    one = re.sub(r"[\[\]`<>]", "", one)
    return one if len(one) <= limit else one[: limit - 1].rstrip() + "…"


def _hound_name(hound_id: str) -> str:
    try:
        from src.hounds.interact import common
        dog = common.resolve(hound_id)
        if dog is not None and dog.name:
            return dog.name
    except Exception:  # noqa: BLE001 -- a name is a courtesy; the digest still reads with the id
        pass
    return hound_id


def _issue_id(*parts) -> str:
    return "FB-" + hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8].upper()


def build(date: str, *, db: Optional[Path] = None, name_of: Callable[[str], str] = _hound_name) -> dict:
    """The digest for the Pacific day ``date``: totals, one block per hound (Good and Bad calls, the chips, a few example notes)
    and one count per chip across every hound, plus the issues it would flag. Reads only."""
    start, end = window_for(date)
    votes = store.votes_between(start, end, db=db)
    hounds: dict = {}
    for v in votes:
        h = hounds.setdefault(v["root_id"], {"root_id": v["root_id"], "hound_id": v["hound_id"], "good": 0, "bad": 0,
                                             "chips": {}, "chip_votes": {}, "notes": [], "note_votes": []})
        h["hound_id"] = v["hound_id"]                        # the newest version's id (rows are oldest first)
        h[v["verdict"]] += 1
        if v["verdict"] == store.VERDICT_BAD:
            for chip in v["chips"]:
                h["chips"][chip] = h["chips"].get(chip, 0) + 1
                h["chip_votes"].setdefault(chip, []).append(v["id"])
        if v["note"]:
            h["note_votes"].append(v)
            if len(h["notes"]) < NOTES_PER_HOUND:
                h["notes"].append({"verdict": v["verdict"], "note": clean_line(v["note"]), "chips": list(v["chips"])})
    chip_totals: dict = {}
    for h in hounds.values():
        h["name"] = name_of(h["hound_id"])
        for chip, n in h["chips"].items():
            chip_totals[chip] = chip_totals.get(chip, 0) + n
    ordered = sorted(hounds.values(), key=lambda h: (-(h["bad"]), -(h["good"]), h["name"].lower()))
    issues = _issues(date, ordered)
    return {"date": date, "start": start, "end": end, "votes": len(votes),
            "good": sum(h["good"] for h in ordered), "bad": sum(h["bad"] for h in ordered),
            "hounds": ordered, "chips": dict(sorted(chip_totals.items(), key=lambda kv: (-kv[1], list(store.CHIPS).index(kv[0])))),
            "issues": issues}


def _issues(date: str, hounds: Sequence[Mapping]) -> list:
    """The flagged issues: a chip on at least ``ISSUE_CHIP_MIN`` Bad calls for one hound, and every vote that has a note."""
    out = []
    for h in hounds:
        for chip, n in h["chips"].items():
            if n >= ISSUE_CHIP_MIN:
                out.append({"feedback_id": _issue_id("chip", h["root_id"], chip, date), "kind": "chip", "chip": chip,
                            "root_id": h["root_id"], "hound_id": h["hound_id"], "name": h["name"], "count": n,
                            "vote_ids": list(h["chip_votes"][chip]),
                            "summary": f"{n} Bad calls said \"{store.CHIP_PHRASES[chip]}\""})
        for v in h["note_votes"]:
            word = "Bad call" if v["verdict"] == store.VERDICT_BAD else "Good call"
            why = (" (" + ", ".join(store.CHIP_PHRASES[c] for c in v["chips"]) + ")") if v["chips"] else ""
            out.append({"feedback_id": _issue_id("note", h["root_id"], v["user_id"], v["created_at"], v["target_kind"],
                                                 v["target_id"], v["note"]),
                        "kind": "note", "chip": None, "root_id": h["root_id"], "hound_id": h["hound_id"], "name": h["name"],
                        "count": 1, "vote_ids": [v["id"]],
                        "summary": f"{word} note{why}: \"{clean_line(v['note'])}\""})
    return out


def render(digest: Mapping) -> str:
    """The markdown file. Times are Pacific words; no member is named (the owners read the words, not the people)."""
    start, end = digest["start"], digest["end"]
    lines = [f"# Hound feedback digest for {pt_text(start).rsplit(' ', 3)[0]}", "",
             f"Window: {pt_text(start)} to {pt_text(end)}. {digest['votes']} current "
             f"{'vote' if digest['votes'] == 1 else 'votes'} on {len(digest['hounds'])} "
             f"{'hound' if len(digest['hounds']) == 1 else 'hounds'}: {digest['good']} Good call, {digest['bad']} Bad call.",
             "A person who changed their mind counts once, on their latest vote. Paper only; feedback never changes a hound by itself.",
             ""]
    if not digest["votes"]:
        lines += ["Nobody rated a hound in this window.", ""]
    for h in digest["hounds"]:
        lines += [f"## {h['name']}", "", f"- {store.votes_text(h['good'], h['bad'], h['chips']) or 'no votes'}"]
        if h["chips"]:
            lines.append("- What was wrong: " + ", ".join(f"{store.CHIP_PHRASES[c]} x{n}" for c, n in
                                                          sorted(h["chips"].items(), key=lambda kv: (-kv[1], list(store.CHIPS).index(kv[0])))))
        for n in h["notes"]:
            word = "Bad call" if n["verdict"] == store.VERDICT_BAD else "Good call"
            lines.append(f"- {word} note: \"{n['note']}\"")
        lines.append("")
    if digest["chips"]:
        lines += ["## By chip, all hounds", "", "| What was wrong | Bad calls |", "|---|---|"]
        lines += [f"| {store.CHIPS[c]} | {n} |" for c, n in digest["chips"].items()]
        lines.append("")
    flagged = digest["issues"]
    lines += ["## Flagged for the backlog", ""]
    lines += ([f"- {i['feedback_id']} {i['name']}: {i['summary']}" for i in flagged] if flagged
              else ["Nothing met the bar (the same chip twice on one hound, or any note)."])
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------

def output_dir() -> Path:
    override = (os.environ.get(ENV_DIR) or "").strip()
    if override:
        return Path(override)
    from src.appstate import users as users_store
    return users_store.db_path().parent / "feedback"


def save(digest: Mapping, folder: Optional[Path] = None) -> Path:
    folder = folder or output_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"digest-{digest['date']}.md"
    path.write_text(render(digest), encoding="utf-8")
    return path


def backlog_path() -> Path:
    from src import paths
    return paths.repo_root() / "docs" / "BACKLOG.md"


def backlog_line(issue: Mapping, date: str) -> str:
    return f"- [{issue['feedback_id']}] {date} {clean_line(issue['name'], 60)} ({clean_line(issue['hound_id'], 60)}): {issue['summary']}"


def file_issues(digest: Mapping, *, path: Optional[Path] = None, db: Optional[Path] = None,
                now: Optional[datetime] = None) -> dict:
    """Register each flagged issue (and attach its votes) and append one backlog line for each that is not already in the file.
    Creates the file with a header when it is missing, and the section heading when the file has none. Returns
    ``{"added": [ids], "skipped": [ids], "path": str}``."""
    target = path or backlog_path()
    text = target.read_text(encoding="utf-8") if target.exists() else None
    added, skipped, lines = [], [], []
    for issue in digest["issues"]:
        store.register_issue(feedback_id=issue["feedback_id"], root_id=issue["root_id"], hound_id=issue["hound_id"],
                             kind=issue["kind"], chip=issue["chip"], summary=issue["summary"], window_date=digest["date"],
                             vote_ids=issue["vote_ids"], now=now, db=db)
        marker = f"[{issue['feedback_id']}]"
        if (text is not None and marker in text) or any(marker in l for l in lines):
            skipped.append(issue["feedback_id"])
            continue
        lines.append(backlog_line(issue, digest["date"]))
        added.append(issue["feedback_id"])
    if not lines:
        return {"added": added, "skipped": skipped, "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    body = text if text is not None else BACKLOG_HEADER
    if BACKLOG_SECTION not in body:
        body = body.rstrip("\n") + "\n\n" + BACKLOG_SECTION + "\n\n"
    elif not body.endswith("\n"):
        body += "\n"
    # the section is the last thing in the file by construction (it is appended there), so a line goes at the end
    target.write_text(body + "\n".join(lines) + "\n", encoding="utf-8")
    return {"added": added, "skipped": skipped, "path": str(target)}


# ---------------------------------------------------------------------------
# the optional email
# ---------------------------------------------------------------------------

def recipients(env: Optional[Mapping] = None) -> list:
    raw = (env if env is not None else os.environ).get(ENV_TO) or ""
    return [a.strip() for a in raw.split(",") if "@" in a]


def email_digest(digest: Mapping, *, env: Optional[Mapping] = None, send: Optional[Callable] = None) -> list:
    """OFF unless FEEDBACK_DIGEST_TO names someone. Goes through src/notify/email.py, which is itself off without
    RESEND_API_KEY and sends at most once per (recipient, kind, date). Returns the per-recipient statuses ([] when off)."""
    to = recipients(env)
    if not to:
        return []
    if send is None:
        from src.notify import email as mail
        send = mail.send
    text = render(digest)
    subject = f"Hound feedback digest: {digest['good']} Good call, {digest['bad']} Bad call ({digest['date']})"
    out = []
    for address in to:
        key = "owner-" + hashlib.sha1(address.lower().encode("utf-8")).hexdigest()[:10]
        result = send({"to": address, "subject": subject, "text": text,
                       "html": "<pre style=\"font-family:inherit;white-space:pre-wrap\">" + html_lib.escape(text) + "</pre>"},
                      user_id=key, kind="feedback_digest", date=digest["date"])
        out.append(result.get("status") if isinstance(result, Mapping) else str(result))
    return out
