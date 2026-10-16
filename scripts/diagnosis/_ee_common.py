"""Shared, sealed-guarded loaders and scoring helpers for the loss diagnosis.

Read-only research helpers for `scripts/diagnosis/estimate_error.py`. Nothing
here edits a store or imports a network client.

SEALED WINDOW. 2026-01-01 through 2026-08-27 is sealed. Every loader that can
see a dated outcome row drops a sealed row on its DATE FIELD before any other
field of that row is read, and the 2026 box-score store is asserted to hold
no sealed row at all (it raises if it does).
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import os
import random
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEALED_LO, SEALED_HI = "2026-01-01", "2026-08-27"
EPS = 1e-6
BOOT_N = 2000
BOOT_SEED = 20261016


class SealedError(RuntimeError):
    pass


def p(*parts):
    return os.path.join(ROOT, *parts)


def is_sealed(date) -> bool:
    d = str(date or "")[:10]
    return SEALED_LO <= d <= SEALED_HI


def guard(date) -> str:
    d = str(date or "")[:10]
    if is_sealed(d):
        raise SealedError(f"sealed date reached an analysis path: {d}")
    return d


def iter_jsonl(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_box_2026():
    """Forward-window 2026 box rows. Raises on any sealed row."""
    rows = []
    for r in iter_jsonl(p("data", "processed", "boxscores_2026.jsonl")):
        guard(r.get("date"))
        rows.append(r)
    return rows


def load_box_archive(season: int):
    if season not in (2023, 2024, 2025):
        raise ValueError(season)
    path = p("data", "archive", "historical", "boxscores", f"boxscores_{season}.jsonl.gz")
    return list(iter_jsonl(path))


def load_results():
    """{int game_pk: row}; sealed rows dropped on `date` first."""
    out = {}
    with open(p("data", "historical", "mlb_results.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if is_sealed(r.get("date")):
                continue
            try:
                out[int(r["game_pk"])] = r
            except (TypeError, ValueError):
                continue
    return out


def load_lineups():
    """[lineup rows]; sealed rows dropped on `date` first."""
    out = []
    for r in iter_jsonl(p("data", "historical", "lineups.jsonl")):
        if is_sealed(r.get("date")):
            continue
        if r.get("empty") or r.get("game_pk") is None:
            continue
        out.append(r)
    return out


def load_pitcher_logs(seasons):
    out = []
    for r in iter_jsonl(p("data", "historical", "pitcher_logs.jsonl")):
        d = str(r.get("date") or "")
        if not d or is_sealed(d):
            continue
        if d[:4] in {str(s) for s in seasons}:
            out.append(r)
    return out


def load_handedness():
    with open(p("data", "historical", "handedness.json"), encoding="utf-8") as fh:
        return json.load(fh)


def parse_utc(text):
    if not text:
        return None
    t = str(text).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def clip(x):
    return min(max(float(x), EPS), 1.0 - EPS)


def ll(prob, y):
    q = clip(prob)
    return -math.log(q) if y else -math.log(1.0 - q)


def brier(prob, y):
    return (float(prob) - y) ** 2


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def clustered_boot(rows, value, cluster="date", n=BOOT_N, seed=BOOT_SEED):
    """(mean, lo, hi) of `value(row)` with clusters resampled with replacement.

    The statistic is the pooled mean over resampled rows (sum/count of the
    resampled clusters), the same estimator as the point estimate.
    """
    groups = {}
    for r in rows:
        v = value(r)
        if v is None:
            continue
        g = groups.setdefault(r[cluster], [0.0, 0])
        g[0] += v
        g[1] += 1
    keys = sorted(groups)
    if not keys:
        return None, None, None
    tot = sum(groups[k][0] for k in keys)
    cnt = sum(groups[k][1] for k in keys)
    point = tot / cnt
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        s = c = 0
        for _k in range(len(keys)):
            g = groups[keys[rng.randrange(len(keys))]]
            s += g[0]
            c += g[1]
        stats.append(s / c)
    stats.sort()
    return point, stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def fmt(x, nd=3, signed=False):
    if x is None:
        return "n/a"
    if isinstance(x, int):
        return str(x)
    s = f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}"
    return s


def pts(x, nd=1):
    """Probability difference shown in percentage points, signed."""
    if x is None:
        return "n/a"
    return f"{100 * x:+.{nd}f}"
