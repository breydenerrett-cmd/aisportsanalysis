"""Feature matrix preparation and time-based splitting.

TWO DECISIONS HERE MATTER MORE THAN THEY LOOK
---------------------------------------------

1. HOW MISSING VALUES ARE HANDLED IS A SELECTION-BIAS DECISION, NOT A CHORE.

   In this dataset the only columns with gaps are the home/away split rates, which
   are undefined until a team has played enough games at each venue. Those gaps are
   not random -- they are concentrated entirely in EARLY SEASON rows.

   So "just drop incomplete rows" quietly deletes April. The model would then be
   trained on a league that has already sorted itself out, and asked to predict
   April games it has never seen the equivalent of. That is a subtle, permanent bias
   introduced by what looks like routine data cleaning.

   Dropping the sparse COLUMNS instead keeps every row and every date. It costs a
   few features and preserves the shape of the season. That is the default, and the
   report says exactly what each strategy would have cost.

2. SPLITTING MUST BE BY TIME, NEVER RANDOMLY.

   A random split puts games from the same week on both sides of the line. Those
   games share starting rotations, bullpen fatigue, injuries, and weather. The model
   effectively sees the answer key for the period it is being tested on, and the
   validation score comes back flattering and meaningless.

   Splitting by date mirrors how the system would actually be used: fit on the past,
   predict the future. It produces worse-looking numbers and truer ones.

Standardization statistics are computed on the TRAINING SPLIT ONLY and then applied
to validation and test. Computing them over the whole dataset leaks the future's
distribution into the past -- a smaller leak than sharing labels, but a real one.
"""

from __future__ import annotations

# Columns that identify a row rather than describe it. Never features.
IDENTITY_COLUMNS = ("game_pk", "date", "away_team", "home_team")
LABEL_COLUMN = "home_won"

# Booleans that describe data quality rather than baseball. Feeding these to the
# model lets it key on "this row is early season" instead of on the teams.
QUALITY_FLAG_COLUMNS = (
    "away_sample_is_thin", "home_sample_is_thin", "either_sample_thin",
)


class DatasetError(ValueError):
    """Raised when a feature matrix cannot be built from the given rows."""


def candidate_features(rows) -> list:
    """Every column that could be a feature, in stable order."""
    if not rows:
        raise DatasetError("no rows to build a feature matrix from")
    excluded = set(IDENTITY_COLUMNS) | {LABEL_COLUMN} | set(QUALITY_FLAG_COLUMNS)
    return [c for c in rows[0] if c not in excluded]


def missingness(rows, columns=None) -> dict:
    """Null count per column, plus how many rows are fully complete."""
    columns = columns or candidate_features(rows)
    per_column = {
        c: sum(1 for r in rows if r.get(c) is None) for c in columns
    }
    complete = sum(
        1 for r in rows if all(r.get(c) is not None for c in columns)
    )
    return {
        "per_column": per_column,
        "columns_with_gaps": sorted(c for c, n in per_column.items() if n),
        "complete_rows": complete,
        "total_rows": len(rows),
    }


def prepare(rows, strategy: str = "drop_columns") -> dict:
    """Build a numeric feature matrix from training rows.

    strategy:
      "drop_columns" (default) -- remove any feature column containing a gap.
          Keeps every row, so the season's shape is preserved.
      "drop_rows" -- remove any row containing a gap. Keeps every column, but in
          this dataset systematically deletes early-season games, so the report
          flags the temporal bias it introduces.

    Returns the matrix, labels, feature names, and a report of what each choice cost.
    """
    if not rows:
        raise DatasetError("no rows to build a feature matrix from")

    columns = candidate_features(rows)
    gaps = missingness(rows, columns)

    if strategy == "drop_columns":
        features = [c for c in columns if gaps["per_column"][c] == 0]
        kept = list(rows)
    elif strategy == "drop_rows":
        features = list(columns)
        kept = [r for r in rows if all(r.get(c) is not None for c in columns)]
    else:
        raise DatasetError(
            f"unknown strategy {strategy!r}; expected drop_columns or drop_rows"
        )

    if not features:
        raise DatasetError("every candidate feature column contains gaps")
    if not kept:
        raise DatasetError("no rows survived the missing-value strategy")

    matrix, labels, meta = [], [], []
    for row in kept:
        label = row.get(LABEL_COLUMN)
        if label is None:
            raise DatasetError(f"row {row.get('game_pk')!r} has no label")
        vector = []
        for column in features:
            value = row.get(column)
            if value is None:
                raise DatasetError(
                    f"row {row.get('game_pk')!r} still has a gap in {column!r} "
                    "after the missing-value strategy was applied"
                )
            vector.append(float(value))
        matrix.append(vector)
        labels.append(int(label))
        meta.append({k: row.get(k) for k in IDENTITY_COLUMNS})

    dropped_dates = _dropped_date_profile(rows, kept)

    return {
        "matrix": matrix,
        "labels": labels,
        "features": features,
        "meta": meta,
        "strategy": strategy,
        "report": {
            "rows_in": len(rows),
            "rows_kept": len(kept),
            "rows_dropped": len(rows) - len(kept),
            "columns_in": len(columns),
            "columns_kept": len(features),
            "columns_dropped": sorted(set(columns) - set(features)),
            "missingness": gaps,
            "dropped_date_profile": dropped_dates,
        },
    }


def _dropped_date_profile(rows, kept) -> dict:
    """Where in the calendar the dropped rows came from.

    If dropped rows cluster in one part of the season, the missing-value strategy
    introduced a temporal bias and the caller should know before fitting anything.
    """
    kept_ids = {r.get("game_pk") for r in kept}
    dropped = [r for r in rows if r.get("game_pk") not in kept_ids]
    if not dropped:
        return {"dropped": 0, "biased": False}
    dates = sorted(r["date"] for r in dropped if r.get("date"))
    all_dates = sorted(r["date"] for r in rows if r.get("date"))
    if not dates or not all_dates:
        return {"dropped": len(dropped), "biased": False}

    midpoint = all_dates[len(all_dates) // 2]
    early = sum(1 for d in dates if d < midpoint)
    share_early = early / len(dates)
    return {
        "dropped": len(dropped),
        "first_dropped": dates[0],
        "last_dropped": dates[-1],
        "share_in_first_half": round(share_early, 3),
        # Anything far from an even split means the drop was not random in time.
        "biased": share_early > 0.7 or share_early < 0.3,
    }


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def time_split(prepared, train_frac: float = 0.6, val_frac: float = 0.2) -> dict:
    """Split chronologically into train, validation, and test.

    Never random. Games from the same week share rotations, bullpen state, injuries,
    and weather; a random split puts them on both sides of the line and hands the
    model the answer key for the period it is tested on.

    The test split is returned but should be touched exactly once, at the very end,
    after the model is locked.
    """
    if not (0 < train_frac < 1) or not (0 < val_frac < 1):
        raise DatasetError("fractions must be between 0 and 1")
    if train_frac + val_frac >= 1.0:
        raise DatasetError("train_frac + val_frac must leave room for a test split")

    order = sorted(
        range(len(prepared["labels"])),
        key=lambda i: (prepared["meta"][i].get("date") or "",
                       str(prepared["meta"][i].get("game_pk") or "")),
    )
    n = len(order)
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)

    def take(indices):
        return {
            "matrix": [prepared["matrix"][i] for i in indices],
            "labels": [prepared["labels"][i] for i in indices],
            "meta": [prepared["meta"][i] for i in indices],
        }

    splits = {
        "train": take(order[:train_end]),
        "val": take(order[train_end:val_end]),
        "test": take(order[val_end:]),
    }

    for name, split in splits.items():
        if not split["labels"]:
            raise DatasetError(f"the {name} split is empty; adjust the fractions")
        dates = [m.get("date") for m in split["meta"] if m.get("date")]
        split["first_date"] = dates[0] if dates else None
        split["last_date"] = dates[-1] if dates else None
        split["n"] = len(split["labels"])
        split["base_rate"] = round(sum(split["labels"]) / len(split["labels"]), 4)

    # A boundary check that would catch an ordering bug immediately.
    if splits["train"]["last_date"] and splits["val"]["first_date"]:
        if splits["train"]["last_date"] > splits["val"]["first_date"]:
            raise DatasetError(
                "train split extends past the start of validation -- the ordering "
                "is wrong and the split would leak"
            )

    splits["features"] = prepared["features"]
    return splits


# ---------------------------------------------------------------------------
# Standardization
# ---------------------------------------------------------------------------

def fit_scaler(matrix) -> dict:
    """Compute per-column mean and standard deviation.

    Call this on the TRAINING split only. Fitting over the whole dataset lets the
    validation and test distributions influence the transform, which leaks the
    future into the past.
    """
    if not matrix:
        raise DatasetError("cannot fit a scaler on an empty matrix")
    width = len(matrix[0])
    means, stds = [], []
    for j in range(width):
        column = [row[j] for row in matrix]
        mean = sum(column) / len(column)
        variance = sum((v - mean) ** 2 for v in column) / len(column)
        std = variance ** 0.5
        means.append(mean)
        # A constant column has zero variance; dividing by it would produce inf.
        stds.append(std if std > 1e-12 else 1.0)
    return {"means": means, "stds": stds}


def apply_scaler(matrix, scaler) -> list:
    means, stds = scaler["means"], scaler["stds"]
    if matrix and len(matrix[0]) != len(means):
        raise DatasetError(
            f"scaler expects {len(means)} features, got {len(matrix[0])}"
        )
    return [
        [(value - means[j]) / stds[j] for j, value in enumerate(row)]
        for row in matrix
    ]
