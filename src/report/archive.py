"""The season archive: every briefing artifact on disk, listed by date.

WHY THIS EXISTS
---------------
The Analyzer's record IS the product's credibility. Twenty-seven pre-registered
hypotheses have been measured and none cleared the bar, and the honest thing a
tool in that position can offer is a checkable trail: what did it say on the
night, before anyone knew the result. That trail was already being written --
one static HTML file per date -- and then left unlinked in a directory nobody
opens. This page is the index over it.

TWO RULES
---------
1. NOTHING IS INVENTED. Every figure on this page is read out of the file it
   describes. A file that cannot be read is listed by name with the reason,
   never dropped: an archive that silently omits what it could not parse is an
   archive that quietly overstates how complete it is.
2. IT IS STILL JUST A FILE. Same constraints as the briefing itself -- opens
   from file://, no server, no network, no script. The links are relative, so
   the index and the artifacts travel together.

HOW A FILE IS READ
------------------
Briefings written by `src/report/dashboard.py` carry a machine-readable HTML
comment (`dashboard.INDEX_MARKER`) holding the date, the counts, the finding
total and each game's headline. That is the preferred source.

Files written before that comment existed are read from their visible markup
instead -- the title, the count tiles, the finding rows. This fallback is
labelled as such on the page, because a count recovered by pattern-matching
rendered HTML deserves less trust than one the renderer wrote down, and the
reader should be able to see which they are looking at.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.report import dashboard

DEFAULT_DIR = "artifacts"
DEFAULT_OUT = "artifacts/archive.html"

# Files in the artifacts directory that are not a record of a slate and are
# therefore not indexed. Named here rather than filtered by a guess, so the
# page can state the exclusions out loud in its own footer.
EXCLUDED = {
    "archive.html": "this index itself",
    "demo_latest.html": "a demonstration page, not a briefing of a real date",
}

SOURCE_EMBEDDED = "embedded index"
SOURCE_MARKUP = "recovered from the page markup"

_MARKER_RE = re.compile(
    r"<!--" + re.escape(dashboard.INDEX_MARKER) + r"\s+(\{.*?\})-->", re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_COUNT_RE = re.compile(
    r'<div class="count"><b>(\d+)</b><span>([^<]*)</span></div>')
_FINDING_RE = re.compile(r'<div class="finding ')
_HEADLINE_RE = re.compile(r'<p class="synthhead">(.*?)</p>', re.S)
_ANCHOR_RE = re.compile(r'<details class="game [^"]*" id="([^"]+)"')
_GENERATED_RE = re.compile(r'generated ([0-9T:.+\-]+) ')


# ---------------------------------------------------------------------------
# Reading one file
# ---------------------------------------------------------------------------

def read_artifact(path) -> dict:
    """One row of the archive, or an honest failure.

    Never raises for a bad file. An unreadable or unrecognisable artifact comes
    back with `unparseable` set and a reason a person can act on, and the page
    prints it exactly as it is.
    """
    path = Path(path)
    record = {
        "file": path.name,
        "path": str(path),
        "kind": ("matchup card" if path.name.startswith("analyze_")
                 else "slate briefing"),
        "date": None,
        "generated_at": None,
        "games": None,
        "findings": None,
        "headlines": [],
        "anchors": [],
        "source": None,
        "unparseable": None,
    }
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        record["unparseable"] = f"could not be read: {exc}"
        return record

    embedded = _read_embedded(text)
    if embedded is not None:
        record.update(embedded)
        record["source"] = SOURCE_EMBEDDED
        return record

    recovered = _read_markup(text)
    if recovered is None:
        record["unparseable"] = (
            "no embedded index and no recognisable briefing markup -- this "
            "file was not written by this project's report layer, or it was "
            "written by a version too old to identify")
        return record
    record.update(recovered)
    record["source"] = SOURCE_MARKUP
    return record


def _read_embedded(text):
    match = _MARKER_RE.search(text)
    if not match:
        return None
    try:
        blob = json.loads(match.group(1))
    except (ValueError, TypeError):
        # The marker is there and its payload is not JSON. That is a real
        # defect worth naming, not a file to treat as merely old.
        return {"unparseable": "the embedded index is present but not valid "
                               "JSON", "source": SOURCE_EMBEDDED}
    if not isinstance(blob, dict):
        return {"unparseable": "the embedded index is not an object",
                "source": SOURCE_EMBEDDED}
    games = blob.get("games") or []
    counts = blob.get("counts") or {}
    return {
        "date": blob.get("date"),
        "generated_at": blob.get("generated_at"),
        "games": counts.get("games", len(games)),
        "findings": blob.get("findings"),
        "flagged": counts.get("flagged"),
        "candidates": counts.get("candidates"),
        "headlines": [g.get("headline") for g in games
                      if isinstance(g, dict) and g.get("headline")],
        "anchors": [(g.get("anchor"), g.get("away"), g.get("home"))
                    for g in games
                    if isinstance(g, dict) and g.get("anchor")],
    }


def _read_markup(text):
    """Recover what the rendered page still shows. Returns None if this is not
    one of our pages at all."""
    title = _TITLE_RE.search(text)
    tiles = dict((label.strip(), int(n)) for n, label in _COUNT_RE.findall(text))
    anchors = _ANCHOR_RE.findall(text)
    if not title and not tiles and not anchors:
        return None
    if title and "briefing" not in title.group(1).lower() and not tiles:
        return None
    date = None
    if title:
        found = _DATE_RE.search(title.group(1))
        date = found.group(1) if found else None
    generated = _GENERATED_RE.search(text)
    return {
        "date": date,
        "generated_at": generated.group(1) if generated else None,
        "games": tiles.get("games"),
        "findings": len(_FINDING_RE.findall(text)) or None,
        "flagged": tiles.get("flagged"),
        "candidates": tiles.get("candidates"),
        "headlines": [_untag(h) for h in _HEADLINE_RE.findall(text)],
        "anchors": [(a, None, None) for a in anchors],
    }


def _untag(fragment) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


# ---------------------------------------------------------------------------
# Scanning a directory
# ---------------------------------------------------------------------------

def scan(directory=DEFAULT_DIR, out_name=None) -> dict:
    """Every .html artifact in `directory`, newest slate date first.

    Files with no date sort last rather than being hidden: an artifact we could
    not date is still an artifact that exists.
    """
    directory = Path(directory)
    excluded = dict(EXCLUDED)
    if out_name:
        excluded.setdefault(Path(out_name).name, "this index itself")
    if not directory.is_dir():
        return {"directory": str(directory), "records": [], "skipped": [],
                "missing_directory": True}
    records, skipped = [], []
    for path in sorted(directory.glob("*.html")):
        if path.name in excluded:
            skipped.append((path.name, excluded[path.name]))
            continue
        records.append(read_artifact(path))
    records.sort(key=lambda r: (r.get("date") is None, r.get("date") or "",
                                r.get("file")), reverse=False)
    records.reverse()
    return {"directory": str(directory), "records": records,
            "skipped": sorted(skipped), "missing_directory": False}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _n(value) -> str:
    return "--" if value is None else str(value)


def _row(record) -> str:
    link = f'<a href="{_esc(record["file"])}">{_esc(record["file"])}</a>'
    if record.get("unparseable"):
        return (f'<tr class="bad"><td>{link}</td>'
                f'<td colspan="5" class="gap">unparseable: '
                f'{_esc(record["unparseable"])}</td></tr>')
    headlines = record.get("headlines") or []
    if headlines:
        shown = "".join(f"<li>{_esc(h)}</li>" for h in headlines[:3])
        extra = (f'<li class="gap">and {len(headlines) - 3} more on the page'
                 "</li>" if len(headlines) > 3 else "")
        summary = f'<ul class="heads">{shown}{extra}</ul>'
    else:
        summary = ('<p class="gap">no synthesis headline recorded for this '
                   "file</p>")
    return (
        f'<tr><td>{link}<div class="sub mono">{_esc(record["kind"])} &middot; '
        f'{_esc(record.get("source"))}</div></td>'
        f'<td class="mono">{_esc(record.get("date") or "no date in file")}</td>'
        f'<td class="n">{_n(record.get("games"))}</td>'
        f'<td class="n">{_n(record.get("findings"))}</td>'
        f'<td class="n">{_n(record.get("flagged"))}</td>'
        f'<td>{summary}</td></tr>')


def render(directory=DEFAULT_DIR, out_path=DEFAULT_OUT, generated_at=None) -> str:
    """Write the archive index. Returns the path written."""
    stamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result = scan(directory, out_name=out_path)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_document(result, stamp, directory), encoding="utf-8")
    return str(target)


def _document(result, stamp, directory) -> str:
    records = result["records"]
    good = [r for r in records if not r.get("unparseable")]
    bad = [r for r in records if r.get("unparseable")]
    dated = [r["date"] for r in good if r.get("date")]
    span = (f"{min(dated)} to {max(dated)}" if dated else "no dated file yet")

    if result.get("missing_directory"):
        body = (f'<p class="gap">There is no directory at '
                f'{_esc(directory)}, so there is nothing to index. This page '
                "is not claiming the record is empty; it is saying it could "
                "not look.</p>")
    elif not records:
        body = ('<p class="gap">No .html artifacts in this directory. Run '
                "<span class=\"mono\">brief</span> and this page will list "
                "what it wrote.</p>")
    else:
        body = ('<div class="tw"><table>'
                '<thead><tr><th>file</th><th>date</th><th class="n">games</th>'
                '<th class="n">findings</th><th class="n">flagged</th>'
                '<th>what it said</th></tr></thead><tbody>'
                + "".join(_row(r) for r in records)
                + "</tbody></table></div>")

    skipped = "".join(
        f"<li>{_esc(name)} &mdash; {_esc(reason)}</li>"
        for name, reason in result.get("skipped") or [])
    skipped_block = (f'<p class="gap">Not indexed, by name: </p>'
                     f'<ul class="heads">{skipped}</ul>' if skipped else "")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Briefing archive</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Briefing archive</h1>
<div class="sub mono">indexed {_esc(stamp.isoformat())} &middot;
{_esc(directory)} &middot; {len(records)} file(s), {len(bad)} unparseable</div>
<div class="counts">
<div class="count"><b>{len(good)}</b><span>readable</span></div>
<div class="count"><b>{len(bad)}</b><span>unparseable</span></div>
<div class="count"><b>{len(dated)}</b><span>dated</span></div>
</div>
<div class="standing"><b>This is a record, not a scoreboard.</b> Every row
below links to a page that was written before the games it describes were
played, and every number in that page carries the sample it rests on. None of
it is a proven edge: {_esc(dashboard.analysis.HYPOTHESES_TESTED_WORD)}
pre&ndash;registered hypotheses have been measured against outcomes and none
cleared the bar. What the archive shows is that the tool said the same kind of
thing on the nights it was wrong as on the nights it was right.</div>
<div class="sub">Slate dates covered: {_esc(span)}.</div>
</header>
{body}
<footer>
{skipped_block}
<div>Counts marked &ldquo;{_esc(SOURCE_MARKUP)}&rdquo; were read back out of
rendered HTML rather than from the index the renderer writes, and are only as
good as that recovery. Files listed as unparseable are listed on purpose: an
index that hid them would overstate how complete this record is.</div>
</footer>
</div>
</body>
</html>
"""


_CSS = """
:root {
  --paper:#EBEEEA; --surface:#F7F9F5; --sunk:#E0E5DC; --ink:#151A16;
  --muted:#525E52; --faint:#84907F; --rule:#CBD2C6;
  --accent:#2B5F44; --clay:#A0522A;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper:#0C100D; --surface:#141A15; --sunk:#1A211B; --ink:#DCE4DA;
    --muted:#8C9789; --faint:#67725F; --rule:#232B24;
    --accent:#79C298; --clay:#DE9463;
  }
}
* { box-sizing:border-box; }
body {
  margin:0; padding:0 18px 80px; background:var(--paper); color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:1080px; margin:0 auto; }
header { padding:40px 0 22px; border-bottom:2px solid var(--ink); margin-bottom:26px; }
h1 { margin:0 0 6px; font-size:30px; letter-spacing:-.02em; }
.sub { color:var(--muted); font-size:14px; margin-top:6px; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.counts { display:flex; gap:22px; margin-top:16px; flex-wrap:wrap; }
.count b { display:block; font-size:26px; line-height:1.1; }
.count span { font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:var(--faint); }
.standing { margin:18px 0 0; padding:12px 14px; border-left:3px solid var(--clay);
  background:var(--sunk); font-size:13px; line-height:1.5; color:var(--muted); }
.standing b { color:var(--ink); }
table { border-collapse:collapse; width:100%; font-size:14px; }
td,th { text-align:left; padding:9px 12px 9px 0; border-bottom:1px solid var(--rule); vertical-align:top; }
th { font-size:10px; letter-spacing:.09em; text-transform:uppercase; color:var(--faint); font-weight:600; }
td.n, th.n { text-align:right; padding-right:0; font-variant-numeric:tabular-nums;
       font-family:ui-monospace,monospace; white-space:nowrap; }
td a { color:var(--accent); text-decoration:none; word-break:break-all; }
td a:hover { text-decoration:underline; }
tr.bad { background:var(--sunk); }
ul.heads { margin:0; padding-left:18px; }
ul.heads li { font-size:13px; color:var(--muted); line-height:1.45; margin-bottom:4px; }
.gap { color:var(--clay); font-size:13px; margin:4px 0 0; }
.tw { overflow-x:auto; }
footer { margin-top:34px; padding-top:14px; border-top:1px solid var(--rule);
         font-size:11.5px; color:var(--faint); line-height:1.8; }
"""
