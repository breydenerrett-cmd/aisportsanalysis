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
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from src import paths
from src.pipeline import display_refresh as dr
from src.pipeline import store_freshness

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


def git_reader(repo_root: Path, base_rel: str = "data/historical") -> Reader:
    """Reads `HEAD:<base_rel>/<name>` through `git show`; None when HEAD has no
    such file or git is unavailable."""
    def read(name: str) -> Optional[bytes]:
        try:
            done = subprocess.run(["git", "show", f"HEAD:{base_rel}/{name}"], cwd=str(repo_root),
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


def _loses_nothing(name: str, merged: Path, other: Path, scratch: Path) -> bool:
    """True when `merged` holds every record `other` holds (the repair finds
    nothing to put back)."""
    repair = dr._keyed_repair(Path(name))
    if repair is None:
        return True
    probe = scratch / "probe" / Path(name).name
    probe.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(merged, probe)
    return repair(probe, other) is None


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

        primary, secondary = (disk, head_path) if prefer == "disk" else (head_path, disk)
        work = scratch / "work" / name
        work.parent.mkdir(parents=True, exist_ok=True)
        if _is_arsenal(name):
            # snapshots: the later one wins whole, the primary on a tie
            pick = secondary if _as_of(secondary) > _as_of(primary) else primary
            shutil.copyfile(pick, work)
            info = None
            out["snapshot"] = "disk" if pick == disk else "committed"
        else:
            repair = dr._keyed_repair(Path(name))
            if repair is None:
                return {**out, "action": "refused", "reason": "no merge rule for this file"}
            shutil.copyfile(primary, work)
            info = repair(work, secondary)
        if dr._validate(work) is not None:
            return {**out, "action": "refused", "reason": "the merged copy does not parse"}
        if not _is_arsenal(name):
            for other in (head_path, disk):
                if not _loses_nothing(name, work, other, scratch):
                    return {**out, "action": "refused",
                            "reason": "the merged copy would still lose a record"}
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("union", "persist"))
    parser.add_argument("--prefer", choices=("disk", "head"), default=None)
    parser.add_argument("--root", default=None, help="data root (default: the project's data/)")
    args = parser.parse_args(argv)
    repo = paths.repo_root()
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
    if args.command == "persist":
        refused = set(report["refused"])
        for name in differing_from_head(args.root, reader=reader):
            if name not in refused:
                print(f"data/historical/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
