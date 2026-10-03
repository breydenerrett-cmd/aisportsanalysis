"""JSONL files with stable ordering, atomic writes and a manifest.

Every dataset is one JSONL file, one record per line, sorted by its key, with keys
inside each record sorted too. The same data therefore always produces the same
bytes, so a daily update shows up in git as the rows that changed and nothing else.
Writes go to a temporary file first and replace the real one in one step, so a
crash never leaves half a file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence, Tuple, Union

Key = Union[str, Sequence[str]]


def _key_fields(key: Key) -> Tuple[str, ...]:
    return (key,) if isinstance(key, str) else tuple(key)


def key_of(record: dict, key: Key) -> tuple:
    fields = _key_fields(key)
    missing = [f for f in fields if record.get(f) in (None, "")]
    if missing:
        raise ValueError(f"record is missing key field(s) {missing}: {str(record)[:200]}")
    return tuple(str(record[f]) for f in fields)


def read_jsonl(path: Path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: not JSON: {exc}") from None
    return out


def write_jsonl(path: Path, records: Iterable[dict], *, key: Key) -> int:
    """Write `records` sorted by `key`. Duplicate keys are an error, not a silent overwrite."""
    path = Path(path)
    rows = list(records)
    seen = {}
    for row in rows:
        k = key_of(row, key)
        if k in seen:
            raise ValueError(f"duplicate key {k} in {path.name}")
        seen[k] = row
    ordered = [seen[k] for k in sorted(seen)]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in ordered:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)
    return len(ordered)


def upsert(path: Path, records: Iterable[dict], *, key: Key) -> dict:
    """Merge `records` into the file by key; a newer record replaces the older one whole.

    Returns counts: added, updated (content changed), unchanged, total."""
    existing = {key_of(r, key): r for r in read_jsonl(path)}
    added = updated = unchanged = 0
    for row in records:
        k = key_of(row, key)
        old = existing.get(k)
        if old is None:
            added += 1
        elif _content(old) != _content(row):
            updated += 1
        else:
            unchanged += 1
        existing[k] = row
    total = write_jsonl(path, existing.values(), key=key)
    return {"added": added, "updated": updated, "unchanged": unchanged, "total": total}


def _content(record: dict) -> str:
    """A record's identity for change detection: everything except its fetch time."""
    return json.dumps({k: v for k, v in record.items() if k != "fetched_utc"},
                      ensure_ascii=False, sort_keys=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(directory: Path, datasets: dict, *, extra: dict = None) -> dict:
    """MANIFEST.json for a dataset directory.

    `datasets` maps a file name to {"records": int, "newest": str or None}; the sha256
    and byte size are read from disk here, so the manifest always matches the files."""
    directory = Path(directory)
    files = {}
    for name, info in sorted(datasets.items()):
        path = directory / name
        if not path.exists():
            continue
        files[name] = {"records": info.get("records"), "newest": info.get("newest"),
                       "bytes": path.stat().st_size, "sha256": file_sha256(path)}
    manifest = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "files": files}
    if extra:
        manifest.update(extra)
    tmp = directory / "MANIFEST.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(directory / "MANIFEST.json")
    return manifest
