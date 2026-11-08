"""The multibook store split by sport, so a replay reads one sport's lines instead of the whole store (2026-11-08).

WHY. The quiz's impact meter and pre-build check replay a week of boards on every answer. ``drill._window_rows`` scanned the
WHOLE multibook store (2.1 million lines, every sport) once per sport asked for: 3-6 s on a desktop, past the page's 20 s timeout
on the production machine (2 shared CPUs), where the scan also held the interpreter long enough that the quiz's own compose call
failed and the reveal said "Could not reach the quiz" (live check 2026-11-08 16:20Z).

WHAT. ``ensure(first, last)`` makes ONE streaming pass over the store and writes each raw line whose observation can fall in the
window to a per-sport file (routing by the same text marker ``snapshots`` uses; a line with no sport field is mlb, exactly
``snapshots.row_sport``; a line whose sport cannot be read from its text goes to ``_any`` and is read for every sport). Nothing is
held in memory but one line. ``path_for(sport, first, last)`` then names the sport's file, which ``snapshots.iter_multibook`` reads
with its usual exact filters (sport, window, corrupt lines), so a replay over the split sees exactly the rows a full scan would:
the split is a superset by construction (a wider ``since`` than any sport's own margin) and the reader re-checks everything.

The split is keyed by the window and by the store's own file sizes and mtimes, so a new capture or a deploy makes a new split. Old
splits are removed when a new one is written. ``ready``/``start`` let the quiz ask "is it there?" and start the pass in the
background without ever paying for it inside a request.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

ANY = "_any"                      # lines whose sport the text cannot prove; read for every sport
SINCE_SLACK_DAYS = 10             # wider than every sport's own since-margin (snapshots._since_margin_days), so the split is a superset
_DONE = "DONE"

_lock = threading.Lock()          # one split pass at a time
_running: set = set()             # keys being built in the background
_running_lock = threading.Lock()


def base_dir() -> Path:
    raw = os.environ.get("LH_BOARD_SPLIT_DIR")
    return Path(raw) if raw else Path(tempfile.gettempdir()) / "lh_board_split"


def _store_path():
    from src.pipeline import snapshots
    return snapshots.DEFAULT_MULTIBOOK_PATH


def _signature(store) -> str:
    """Sizes and mtimes of the hot file and every archive segment: any capture, rotation or deploy changes it."""
    from src.pipeline import store_archive
    parts = []
    for p in [Path(store), *store_archive.segments(store)]:
        try:
            st = os.stat(p)
        except OSError:
            continue
        parts.append(f"{p.name}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _key(first: str, last: str, store=None) -> str:
    return f"{first}_{last}_{_signature(store or _store_path())}"


def _dir_for(key: str) -> Path:
    return base_dir() / key


def ready(first: str, last: str, store=None) -> bool:
    return (_dir_for(_key(first, last, store)) / _DONE).exists()


def _sport_of(line: str) -> str:
    from src.pipeline import snapshots
    marker = snapshots._SPORT_MARKER
    idx = line.find(marker)
    if idx == -1:
        return snapshots.DEFAULT_SPORT if '"sport"' not in line else ANY      # a spaced-out key the marker misses: let the reader decide
    start = idx + len(marker)
    end = line.find('"', start)
    if end == -1:
        return ANY
    value = line[start:end]
    if not value or "/" in value or "\\" in value or value.startswith("."):
        return ANY
    return value


def ensure(first: str, last: str, store=None) -> Path:
    """Build the split for ``first..last`` (slate dates) if it is not there; return its directory. Blocking: callers in a request
    should use ``start`` and ``ready`` instead."""
    from src.pipeline import snapshots, store_archive
    store = store or _store_path()
    key = _key(first, last, store)
    out = _dir_for(key)
    if (out / _DONE).exists():
        return out
    with _lock:
        if (out / _DONE).exists():
            return out
        since = (datetime.fromisoformat(first) - timedelta(days=SINCE_SLACK_DAYS)).date().isoformat()
        until = snapshots.window_for_date(last, None)[1]
        tmp = base_dir() / (key + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        handles: dict = {}
        n = 0
        try:
            if store_archive.exists(store):
                for line in store_archive.iter_lines(store, since=since):
                    if not line.strip() or snapshots._line_probably_out_of_window(line, since, until):
                        continue
                    sport = _sport_of(line)
                    fh = handles.get(sport)
                    if fh is None:
                        fh = handles[sport] = open(tmp / f"{sport}.jsonl", "w", encoding="utf-8", newline="\n")
                    fh.write(line if line.endswith("\n") else line + "\n")
                    n += 1
        finally:
            for fh in handles.values():
                fh.close()
        (tmp / _DONE).write_text(str(n), encoding="utf-8")
        shutil.rmtree(out, ignore_errors=True)
        os.replace(tmp, out)
        for old in base_dir().iterdir():                  # one split at a time on disk
            if old.name != key and old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
        log.info("board split %s: %d lines in %d sports", key, n, len(handles))
        return out


def start(first: str, last: str, store=None) -> bool:
    """Start ``ensure`` in a background thread unless it is ready or already running. True when the split is ready now."""
    store = store or _store_path()
    try:
        key = _key(first, last, store)
    except Exception:  # noqa: BLE001
        return False
    if (_dir_for(key) / _DONE).exists():
        return True
    with _running_lock:
        if key in _running:
            return False
        _running.add(key)

    def run():
        try:
            ensure(first, last, store)
        except Exception:  # noqa: BLE001
            log.exception("board split %s failed", key)
        finally:
            _running.discard(key)
    threading.Thread(target=run, name="board-split", daemon=True).start()
    return False


def path_for(sport: str, first: str, last: str, store=None) -> Optional[list]:
    """The files to read for ``sport`` over ``first..last`` when the split is ready (the sport's own file, plus ``_any``), else
    None. A sport with no lines in the window gets an empty list: nothing to read, which is the truth."""
    d = _dir_for(_key(first, last, store))
    if not (d / _DONE).exists():
        return None
    return [p for p in (d / f"{sport}.jsonl", d / f"{ANY}.jsonl") if p.exists()]
