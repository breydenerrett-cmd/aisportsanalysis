"""Persist the refreshed MLB display stores to git WITHOUT losing a row (2026-10-04).

THE PROBLEM
-----------
`data/historical/` holds the stores the site's computed pages read
(`mlb_results.csv`, `pitcher_logs.jsonl`, `bullpen_log.jsonl`, `standings.jsonl`,
...). `src.pipeline.display_refresh` brings them current from MLB's free Stats
API, but nothing committed the result, so every consumer (each image build, each
container, each runner, each local run) started from the committed copy that
ends weeks ago and re-fetched the whole gap: 632 requests, about 3.5 minutes,
about 57 times a day (docs/audit/2026-10-04/COLLECTION.md).

`scripts/daily_loop.sh` deliberately did not `git add` them. On a runner the
copy on disk is the ACTIONS CACHE's copy (restored after the checkout), and a
blind add makes git converge on the cache by deleting rows only git holds (the
2023-25 postseason backfill). The fix its comment asked for is a UNION first.

THE UNION
---------
`union_stores` merges the copy on disk with the copy in `HEAD`, record by
record, using the same keys and identities as the refresh's own per-key
promotion (`display_refresh.KEYED_STORES`), so there is one definition of "a
record" in the codebase:

  * a record held by only one side SURVIVES (a row present only in git is kept;
    so is a row present only in the cache copy);
  * a record held by both takes the PRIMARY side's version. `prefer="disk"`
    (what the loop uses just before it commits: the disk copy was refreshed
    from the API minutes ago, so a provider correction there wins);
    `prefer="head"` (seeding a runner from git: git is the durable copy and a
    cache restore may be old, so an old cache can never overwrite what git
    already knows);
  * the two Savant arsenal leaderboards are snapshots of one moment, not sets
    of records (a union would double-count): the snapshot with the later
    `as_of` wins whole, the primary on a tie.

A result that would still be missing a record the other side holds is NOT
written ("refused"); a file that does not parse is not written; the disk copy
is replaced atomically and only when the merge differs from it. Nothing here
fetches anything, and nothing here ever shrinks a store.

THE CLI (never fails the caller; exit 0 on every soft outcome)
-------------------------------------------------------------
  python -m src.pipeline.store_persist union   --prefer head|disk   merge into disk
  python -m src.pipeline.store_persist persist                      union (disk wins),
        then print, one per line, the repo-relative path of every store whose
        merged copy differs from HEAD: the list `daily_loop.sh` stages BY NAME
        and runs through `guard_staged_no_shrink`.

`reader` (how a committed copy is read) is injectable, so the tests need no git.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from src import paths
from src.pipeline import display_refresh as dr
from src.pipeline import history, store_freshness

Reader = Callable[[str], Optional[bytes]]


def store_names(season: str) -> list:
    """The stores the refresh maintains, destination names relative to
    `data/historical/`."""
    seen: list = []
    for files in dr.STEP_FILES.values():
        for _, dest, _ in files:
            dest = dest.replace("{season}", season)
            if dest not in seen:
                seen.append(dest)
    return seen


def git_reader(repo_root: Path, base_rel: str = "data/historical", ref: str = "HEAD") -> Reader:
    """Reads `<ref>:<base_rel>/<name>` through `git show` (HEAD unless a ref such
    as `origin/main` is given); None when the ref has no such file or git is
    unavailable."""
    def read(name: str) -> Optional[bytes]:
        try:
            done = subprocess.run(["git", "show", f"{ref}:{base_rel}/{name}"], cwd=str(repo_root),
                                  capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout if done.returncode == 0 else None
    return read


def _norm(data: bytes) -> bytes:
    """Line endings do not make two copies different (a Windows checkout)."""
    return data.replace(b"\r\n", b"\n")


def _digest(data: bytes) -> str:
    return hashlib.sha256(_norm(data)).hexdigest()


def _as_of(path: Path) -> str:
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("as_of") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def _is_arsenal(name: str) -> bool:
    return name.startswith("arsenals/") and name.endswith(".json")


def _csv_columns(path: Path) -> list:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle), [])


def _extra_columns(*paths: Path) -> list:
    """Columns the results CSVs carry that this code does not know, in the order
    first met. `history.write_results` writes only RESULT_COLUMNS, so rewriting
    such a file through it would narrow every row (a committed file written by
    newer code); a merge carries the extra columns instead (its values from the
    side the row came from), and `_loses_nothing` refuses a merge without them."""
    out: list = []
    for path in paths:
        for column in _csv_columns(path):
            if column not in history.RESULT_COLUMNS and column not in out:
                out.append(column)
    return out


def _write_results_wide(rows: dict, path: Path, extras: list) -> None:
    """`history.write_results` (same order, same file discipline) plus `extras`."""
    if not extras:
        history.write_results(rows, path)
        return
    ordered = sorted(rows.values(), key=lambda r: (r.get("date") or "", str(r.get("game_pk") or "")))
    columns = list(history.RESULT_COLUMNS) + list(extras)

    def render(handle):
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in ordered:
            writer.writerow({c: row.get(c) for c in columns})

    history._atomic_write(path, render)


def _carry_extra_columns(work: Path, primary: Path, secondary: Path) -> None:
    """After a merge that went through `history.write_results`, put back any
    column the committed or disk copy carries that the code does not know."""
    extras = _extra_columns(secondary, primary)
    if not extras or set(extras) <= set(_csv_columns(work)):
        return
    rows = history.read_results(work)
    first, second = history.read_results(primary), history.read_results(secondary)
    for pk, row in rows.items():
        for column in extras:
            if row.get(column) in (None, ""):
                row[column] = (first.get(pk) or {}).get(column) or (second.get(pk) or {}).get(column)
    _write_results_wide(rows, work, extras)


def _loses_nothing(name: str, merged: Path, other: Path, scratch: Path) -> bool:
    """True when `merged` holds every record `other` holds (the repair finds
    nothing to put back), counting a record as many times as `other` holds it
    (a pitcher's two relief outings on one date are two), and, for the results
    CSV, every column `other` carries."""
    if name == "mlb_results.csv" and not set(_csv_columns(other)) <= set(_csv_columns(merged)):
        return False
    repair = dr._keyed_repair(Path(name))
    if repair is None:
        return True
    probe = scratch / "probe" / Path(name).name
    probe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(merged, probe)
    return repair(probe, other) is None


# -- the sealed window --------------------------------------------------------------------------------------

def _sealed(value) -> bool:
    try:
        return bool(dr._in_sealed_window(value))
    except (ValueError, TypeError):
        return False


_ROW_DATE = {
    "pitcher_logs.jsonl": lambda r: r.get("date"),
    "bullpen_log.jsonl": lambda r: r.get("date"),
    "standings.jsonl": lambda r: r.get("date"),
    "transactions.jsonl": lambda r: r.get("filed_date") or r.get("date"),
}


def _sealed_sig(row: dict, line: str, spec) -> tuple:
    key_fn, ident, is_marker = spec
    key = key_fn(row)
    if key is None:
        return ("raw", line.strip())
    return (key, "\0marker" if is_marker(row) else ident(row))


def _jsonl_sealed_lines(path: Path, name: str) -> dict:
    spec, day_of, out = dr.JSONL_SPECS[name], _ROW_DATE[name], {}
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and _sealed(day_of(row)):
                out.setdefault(_sealed_sig(row, raw, spec), []).append(raw if raw.endswith("\n") else raw + "\n")
    return out


def without_disk_only_sealed(name: str, disk: Path, head_path: Path, scratch: Path) -> Optional[Path]:
    """A copy of the disk store from which every row dated in the sealed window
    (2026-01-01..2026-08-27) that git does not already hold is gone, and in which
    a sealed-window row git DOES hold is git's own, in place: the union must
    never newly commit one, nor change one. Returns the path of the cleaned copy,
    or None when the disk copy needed nothing. Counts and dates only; no outcome
    is read for anything but the identity and the date. Never raises past the
    caller's guard."""
    clean = scratch / "clean" / name
    clean.parent.mkdir(parents=True, exist_ok=True)
    if name in dr.JSONL_SPECS:
        spec, day_of = dr.JSONL_SPECS[name], _ROW_DATE[name]
        held, seen, lines = _jsonl_sealed_lines(head_path, name), {}, []
        with disk.open(encoding="utf-8") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                line = raw if raw.endswith("\n") else raw + "\n"
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    lines.append(line)
                    continue
                if not (isinstance(row, dict) and _sealed(day_of(row))):
                    lines.append(line)
                    continue
                sig = _sealed_sig(row, raw, spec)
                n = seen.get(sig, 0)
                seen[sig] = n + 1
                if n < len(held.get(sig, ())):
                    lines.append(held[sig][n])
                # else: only the cache holds it; it does not go into the commit
        text = "".join(lines)
        if text == disk.read_text(encoding="utf-8"):
            return None
        clean.write_text(text, encoding="utf-8", newline="")
        return clean
    if name == "mlb_results.csv":
        rows, head_rows, out = history.read_results(disk), history.read_results(head_path), {}
        changed = False
        for pk, row in rows.items():
            if _sealed(row.get("date")):
                changed = True if pk not in head_rows or head_rows[pk] != row else changed
                if pk in head_rows:
                    out[pk] = head_rows[pk]
            else:
                out[pk] = row
        if not changed:
            return None
        _write_results_wide(out, clean, _extra_columns(head_path, disk))
        return clean
    if name == "mlb_results.manifest.json":
        data = json.loads(disk.read_text(encoding="utf-8"))
        inner = data.get("dates") if isinstance(data, dict) else None
        if not isinstance(inner, dict):
            return None
        head_data = json.loads(head_path.read_text(encoding="utf-8"))
        head_inner = head_data.get("dates") if isinstance(head_data, dict) else None
        head_inner = head_inner if isinstance(head_inner, dict) else {}
        changed = False
        for day in list(inner):
            if _sealed(day):
                if day not in head_inner or head_inner[day] != inner[day]:
                    changed = True
                if day in head_inner:
                    inner[day] = head_inner[day]
                else:
                    del inner[day]
        if not changed:
            return None
        clean.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        return clean
    return None


def union_one(name: str, base: Path, reader: Reader, prefer: str, scratch: Path) -> dict:
    """Merge one store. Returns {"file", "action", ...}; never raises."""
    out: dict = {"file": name}
    disk = base / name
    try:
        head = reader(name)
        if head is None:
            return {**out, "action": "no committed copy"}
        head_path = scratch / "head" / name
        head_path.parent.mkdir(parents=True, exist_ok=True)
        head_path.write_bytes(head)
        if dr._validate(head_path) is not None:
            return {**out, "action": "refused", "reason": "the committed copy does not parse"}
        if not disk.exists():
            dr._atomic_replace(head_path, disk)
            return {**out, "action": "restored from committed copy"}
        if dr._validate(disk) is not None:
            dr._atomic_replace(head_path, disk)
            return {**out, "action": "restored from committed copy",
                    "reason": "the disk copy did not parse"}
        if _digest(disk.read_bytes()) == _digest(head):
            return {**out, "action": "unchanged"}

        # The sealed window: nothing the cache alone holds for 2026-01-01..08-27 may reach
        # the commit; a row git holds there is kept exactly as git has it.
        cleaned = without_disk_only_sealed(name, disk, head_path, scratch)
        mine = cleaned if cleaned is not None else disk
        primary, secondary = (mine, head_path) if prefer == "disk" else (head_path, mine)
        work = scratch / "work" / name
        work.parent.mkdir(parents=True, exist_ok=True)
        if _is_arsenal(name):
            # snapshots: the later one wins whole, the primary on a tie
            pick = secondary if _as_of(secondary) > _as_of(primary) else primary
            shutil.copyfile(pick, work)
            info = None
            out["snapshot"] = "disk" if pick == mine else "committed"
        else:
            repair = dr._keyed_repair(Path(name))
            if repair is None:
                return {**out, "action": "refused", "reason": "no merge rule for this file"}
            shutil.copyfile(primary, work)
            info = repair(work, secondary)
            if name == "mlb_results.csv":
                _carry_extra_columns(work, primary, secondary)
        if dr._validate(work) is not None:
            return {**out, "action": "refused", "reason": "the merged copy does not parse"}
        if not _is_arsenal(name):
            # `mine` rather than `disk`: the cache-only sealed rows were left out on purpose
            for other in (head_path, mine):
                if not _loses_nothing(name, work, other, scratch):
                    return {**out, "action": "refused",
                            "reason": "the merged copy would still lose a record"}
        if cleaned is not None:
            out["sealed_cache_only_rows_left_out"] = True
        out["records_from_other_side"] = (info or {}).get("rows", 0)
        if info:
            out["keys_from_other_side"] = len(info["keys"])
        if _digest(work.read_bytes()) == _digest(disk.read_bytes()):
            return {**out, "action": "unchanged"}
        dr._atomic_replace(work, disk)
        return {**out, "action": "merged"}
    except Exception as exc:  # noqa: BLE001 -- persisting is best effort; the caller carries on
        return {**out, "action": "refused", "reason": f"{type(exc).__name__}: {exc}"}


def union_stores(root=None, *, reader: Reader, prefer: str = "disk", season: Optional[str] = None,
                 names: Optional[list] = None, now=None) -> dict:
    """Merge every store with its committed copy. See the module docstring."""
    if prefer not in ("disk", "head"):
        raise ValueError("prefer must be 'disk' or 'head'")
    data_root = Path(root) if root is not None else paths.data_root()
    base = data_root / "historical"
    season = season or store_freshness.baseball_date(now)[:4]
    scratch = data_root / ".union_work"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        results = [union_one(n, base, reader, prefer, scratch)
                   for n in (names or store_names(season))]
        # A column the code does not know survives the round trip (it is carried,
        # never narrowed) but is not a model input. Say so, so a person sees it.
        for r in results:
            if r["file"] == "mlb_results.csv" and (base / r["file"]).exists():
                try:
                    unknown = _extra_columns(base / r["file"])
                except (OSError, csv.Error, UnicodeDecodeError):
                    unknown = []
                if unknown:
                    r["unknown_columns"] = unknown
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"prefer": prefer, "stores": results,
            "merged": [r["file"] for r in results if r["action"] in ("merged", "restored from committed copy")],
            "refused": [r["file"] for r in results if r["action"] == "refused"]}


def differing_from_head(root=None, *, reader: Reader, season: Optional[str] = None,
                        names: Optional[list] = None, now=None) -> list:
    """Stores whose disk copy differs from the committed one (and exists), by
    destination name relative to `historical/`."""
    data_root = Path(root) if root is not None else paths.data_root()
    base = data_root / "historical"
    season = season or store_freshness.baseball_date(now)[:4]
    out = []
    for name in (names or store_names(season)):
        disk = base / name
        head = reader(name)
        if head is None or not disk.exists():
            continue
        if _digest(disk.read_bytes()) != _digest(head):
            out.append(name)
    return out


# -- the deferred-store ledger ------------------------------------------------------------------------------
#
# When `daily_loop.sh` has to leave a display store out of a commit (the rebase
# conflicted on it: another writer advanced the same store on origin), the
# refresh is re-derivable, so what is kept is a SMALL COMMITTED RECORD, not the
# store: one JSON line per event in data/watch/display_store_deferred.jsonl,
# appended and staged with the rest of the commit that does go out.
#
#   deferred  {at, event, store, rows_on_disk, rows_in_remote, rows_only_ours, reason}
#   resolved  {at, event, store, deferred_runs}   a persist of that store succeeded
#
# The next run retries the union and persist as normal. A store whose latest
# event is `deferred` is OUTSTANDING; one deferred on ESCALATE_AFTER consecutive
# runs with no `resolved` between is escalated, on every run, until it resolves.

LEDGER_REL = "data/watch/display_store_deferred.jsonl"
ESCALATE_AFTER = 3


def ledger_path(root=None) -> Path:
    base = Path(root) if root is not None else paths.data_root()
    return base / "watch" / "display_store_deferred.jsonl"


def read_ledger(path: Path) -> list:
    out: list = []
    try:
        with path.open(encoding="utf-8") as handle:
            for raw in handle:
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("store") and row.get("event") in ("deferred", "resolved"):
                    out.append(row)
    except OSError:
        pass
    return out


def outstanding(events: list) -> dict:
    """{store: {"runs", "since", "last"}} for stores whose latest event is `deferred`;
    `runs` is the consecutive deferrals since the last `resolved`."""
    state: dict = {}
    for ev in events:
        slot = state.setdefault(ev["store"], {"runs": 0, "since": None, "last": None})
        if ev["event"] == "deferred":
            slot["runs"] += 1
            slot["since"] = slot["since"] or ev.get("at")
            slot["last"] = ev
        else:
            slot.update(runs=0, since=None, last=None)
    return {k: v for k, v in state.items() if v["runs"] > 0}


def _append_ledger(path: Path, rows: list) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _now_iso(now=None) -> str:
    from datetime import datetime, timezone
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _store_name(value: str) -> str:
    value = value.replace("\\", "/").strip()
    return value[len("data/historical/"):] if value.startswith("data/historical/") else value


def _count_deferred(name: str, disk: Path, remote: Optional[bytes], scratch: Path) -> dict:
    """Rows on disk, rows in the remote copy, rows only we held. None for what
    cannot be counted; never raises."""
    out = {"rows_on_disk": None, "rows_in_remote": None, "rows_only_ours": None}
    try:
        out["rows_on_disk"] = dr._rows(disk) if disk.exists() else None
        if remote is not None and disk.exists():
            probe = scratch / "remote" / name
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(remote)
            out["rows_in_remote"] = dr._rows(probe)
            diff = dr.row_diff(name, disk, probe)
            out["rows_only_ours"] = diff["new"] if diff else None
    except Exception:  # noqa: BLE001 -- a count is a report line, never a reason to fail
        pass
    return out


def record_run(root=None, *, deferred: Optional[list] = None, kept: Optional[list] = None,
               reader: Optional[Reader] = None, reason: str = "", now=None) -> list:
    """Append this run's ledger lines and return the lines to print.

    `deferred`: stores left out of the commit (one `deferred` line each, with
    counts against `reader`'s copy, the remote's). `kept`: stores in the commit
    that goes out; one that was outstanding gets a `resolved` line. Then every
    outstanding store at or past ESCALATE_AFTER runs prints an ESCALATE line."""
    data_root = Path(root) if root is not None else paths.data_root()
    ledger = ledger_path(data_root)
    base = data_root / "historical"
    at = _now_iso(now)
    before = outstanding(read_ledger(ledger))
    lines, rows = [], []
    scratch = data_root / ".union_work"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        for raw in deferred or []:
            name = _store_name(raw)
            counts = _count_deferred(name, base / name, reader(name) if reader else None, scratch)
            rows.append({"at": at, "event": "deferred", "store": name, **counts, "reason": reason})
            lines.append(f"DISPLAY STORE NOT PERSISTED: data/historical/{name} "
                         f"rows_on_disk={counts['rows_on_disk']} rows_in_remote={counts['rows_in_remote']} "
                         f"rows_only_ours={counts['rows_only_ours']} reason={reason}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    skipped = {_store_name(s) for s in deferred or []}
    for raw in kept or []:
        name = _store_name(raw)
        if name in before and name not in skipped:
            rows.append({"at": at, "event": "resolved", "store": name, "deferred_runs": before[name]["runs"]})
            lines.append(f"display store persisted, deferral resolved: data/historical/{name} "
                         f"(had been deferred {before[name]['runs']} run(s))")
    _append_ledger(ledger, rows)
    for name, slot in sorted(outstanding(read_ledger(ledger)).items()):
        if slot["runs"] >= ESCALATE_AFTER:
            lines.append(f"ESCALATE: display store data/historical/{name} deferred on {slot['runs']} "
                         f"consecutive runs with no resolved (since {slot['since']}); its updates are not "
                         f"reaching origin -- reconcile it by hand")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("union", "persist", "record", "deferred"))
    parser.add_argument("--prefer", choices=("disk", "head"), default=None)
    parser.add_argument("--root", default=None, help="data root (default: the project's data/)")
    parser.add_argument("--deferred", nargs="*", default=[], help="record: stores left out of the commit")
    parser.add_argument("--kept", nargs="*", default=[], help="record: stores in the commit that goes out")
    parser.add_argument("--ref", default="HEAD", help="record: the remote copy to count against")
    parser.add_argument("--reason", default="", help="record: why the stores were left out")
    args = parser.parse_args(argv)
    repo = paths.repo_root()
    if args.command == "record":
        try:
            for line in record_run(args.root, deferred=args.deferred, kept=args.kept,
                                   reader=git_reader(repo, ref=args.ref), reason=args.reason):
                print(line)
        except Exception as exc:  # noqa: BLE001
            print(f"store_persist: record failed softly ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 0
    if args.command == "deferred":
        try:
            held = outstanding(read_ledger(ledger_path(args.root)))
        except Exception as exc:  # noqa: BLE001
            print(f"store_persist: deferred failed softly ({type(exc).__name__}: {exc})", file=sys.stderr)
            return 0
        if not held:
            print("no display store is deferred")
        for name, slot in sorted(held.items()):
            last = slot["last"] or {}
            print(f"data/historical/{name}: deferred {slot['runs']} consecutive run(s) since {slot['since']} "
                  f"(rows_on_disk={last.get('rows_on_disk')} rows_in_remote={last.get('rows_in_remote')} "
                  f"rows_only_ours={last.get('rows_only_ours')}; {last.get('reason')})")
        return 0
    reader = git_reader(repo)
    try:
        report = union_stores(args.root, reader=reader,
                              prefer=args.prefer or ("disk" if args.command == "persist" else "head"))
    except Exception as exc:  # noqa: BLE001
        print(f"store_persist: failed softly ({type(exc).__name__}: {exc}); nothing changed",
              file=sys.stderr)
        return 0
    for row in report["stores"]:
        extra = f" ({row['reason']})" if row.get("reason") else ""
        print(f"store_persist: {row['file']}: {row['action']}{extra}", file=sys.stderr)
        if row.get("unknown_columns"):
            print(f"store_persist: {row['file']}: carries column(s) this code does not know: "
                  f"{', '.join(row['unknown_columns'])} (kept in the file; not read as a model input)",
                  file=sys.stderr)
    if args.command == "persist":
        refused = set(report["refused"])
        for name in differing_from_head(args.root, reader=reader):
            if name not in refused:
                print(f"data/historical/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
