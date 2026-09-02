#!/usr/bin/env bash
# scripts/archive_historical.sh -- make the PAID historical odds purchase
# durable by gzipping it into a git-tracked archive.
#
# WHY THIS EXISTS
# ----------------
# data/historical/odds_history/ (~133MB: mlb_2023/2024/2025.jsonl + a
# manifest) and data/historical/odds_first_five/ (~1.6MB, same shape) are a
# one-time PAID purchase from the odds provider -- not a reproducible pull.
# Both directories are gitignored (data/historical/* in .gitignore) because
# they're large and, on the day that rule was written, everything under
# data/historical/ was assumed regenerable. It isn't: this data cost real
# money and this project runs on ephemeral containers whose disks get
# reclaimed. The same failure mode already happened once to forward odds
# captures (see .gitignore's FORWARD ODDS CAPTURES comment and
# tests/test_forward_evidence_tracked.py) -- this script is the fix for the
# purchased-data half of that same class of bug. JSONL gzips ~18x, so the
# ~133MB purchase becomes a handful of MB, small enough to live in git
# directly under data/archive/historical/ (see .gitignore for the negation
# that keeps that path tracked).
#
# WHY `gzip -n`
# --------------
# `-n` drops the embedded mtime/original-filename header gzip normally
# writes, so compressing byte-identical input twice (today, next month, on
# a different machine) produces a byte-identical .gz -- re-running this
# script never shows up as a diff for data that hasn't changed.
#
# WHY THE SIDECAR RECORDS THE *DECOMPRESSED* HASH
# -------------------------------------------------
# data/archive/historical/SHA256SUMS records the sha256 of each source
# file's original, uncompressed content (not of the .gz bytes). That makes
# one hash do two jobs: it's what scripts/restore_historical.sh checks a
# restored file against, and it's the cheap idempotency check below (hash
# the source, compare to the sidecar -- no need to gzip just to find out
# nothing changed).
#
# LAYOUT
# ------
#   data/archive/historical/<dir>/<file>.jsonl.gz   (or split, see below)
#   data/archive/historical/<dir>/manifest.json     (verbatim copy)
#   data/archive/historical/SHA256SUMS              ("<sha256>  <dir>/<file>")
#
# A .gz over SPLIT_THRESHOLD bytes (GitHub warns above 50MB per file) is
# split into SPLIT_CHUNK-sized parts named "<file>.jsonl.gz.part-NNN" and the
# unsplit .gz is removed; scripts/restore_historical.sh reassembles them.
# Nothing in the current purchase is anywhere near that size (~3-4MB
# compressed per season), but future seasons could get there.
#
# Usage: scripts/archive_historical.sh
set -euo pipefail
cd "$(dirname "$0")/.."

SRC_ROOT="data/historical"
DST_ROOT="data/archive/historical"
SIDECAR="$DST_ROOT/SHA256SUMS"
SRC_DIRS=(odds_history odds_first_five)
SPLIT_THRESHOLD=$((50 * 1024 * 1024))  # bytes; GitHub's per-file warning line
SPLIT_CHUNK="40M"                       # split -b unit; stays clear of the above

shopt -s nullglob

mkdir -p "$DST_ROOT"

sha256_of() { sha256sum "$1" | cut -d' ' -f1; }

# Prints the sha256 already recorded in the sidecar for a given archive-relative
# path (e.g. "odds_history/mlb_2023.jsonl.gz"), or nothing if there's no entry.
sidecar_hash_for() {
    local rel="$1"
    [[ -f "$SIDECAR" ]] || return 0
    awk -v p="$rel" '$2 == p { print $1 }' "$SIDECAR"
}

declare -a REL_PATHS
declare -a NEW_HASHES

for dir in "${SRC_DIRS[@]}"; do
    src_dir="$SRC_ROOT/$dir"
    dst_dir="$DST_ROOT/$dir"

    if [[ ! -d "$src_dir" ]]; then
        echo "archive_historical.sh: missing source dir $src_dir -- refusing to archive a partial purchase" >&2
        exit 1
    fi
    mkdir -p "$dst_dir"

    # manifest.json: verbatim copy, tracked under the same idempotency rule.
    if [[ -f "$src_dir/manifest.json" ]]; then
        rel="$dir/manifest.json"
        src_hash="$(sha256_of "$src_dir/manifest.json")"
        existing="$(sidecar_hash_for "$rel")"
        if [[ "$existing" == "$src_hash" && -f "$dst_dir/manifest.json" ]]; then
            echo "skip (unchanged): $rel"
        else
            cp "$src_dir/manifest.json" "$dst_dir/manifest.json"
            echo "copied: $rel"
        fi
        REL_PATHS+=("$rel")
        NEW_HASHES+=("$src_hash")
    fi

    for src_file in "$src_dir"/*.jsonl; do
        fname="$(basename "$src_file")"
        rel="$dir/$fname.gz"
        src_hash="$(sha256_of "$src_file")"
        existing="$(sidecar_hash_for "$rel")"

        have_whole=0
        [[ -f "$dst_dir/$fname.gz" ]] && have_whole=1
        have_parts=0
        for _ in "$dst_dir/$fname.gz.part-"*; do have_parts=1; done

        if [[ "$existing" == "$src_hash" && ( "$have_whole" == 1 || "$have_parts" == 1 ) ]]; then
            echo "skip (unchanged): $rel"
        else
            rm -f "$dst_dir/$fname.gz" "$dst_dir/$fname.gz.part-"*
            gzip -n -c "$src_file" > "$dst_dir/$fname.gz"
            gz_size="$(stat -c%s "$dst_dir/$fname.gz")"
            if (( gz_size > SPLIT_THRESHOLD )); then
                split -b "$SPLIT_CHUNK" -d -a 3 "$dst_dir/$fname.gz" "$dst_dir/$fname.gz.part-"
                rm -f "$dst_dir/$fname.gz"
                n_parts=$(ls "$dst_dir/$fname.gz.part-"* | wc -l)
                echo "archived (split, ${gz_size}B > $((SPLIT_THRESHOLD))B, $n_parts parts): $rel"
            else
                echo "archived (${gz_size}B): $rel"
            fi
        fi
        REL_PATHS+=("$rel")
        NEW_HASHES+=("$src_hash")
    done
done

# Rewrite the sidecar from scratch, sorted, so it's stable regardless of
# filesystem iteration order (important for gzip -n's determinism promise
# to also hold for THIS file's diffs).
tmp_sidecar="$(mktemp)"
for i in "${!REL_PATHS[@]}"; do
    printf '%s  %s\n' "${NEW_HASHES[$i]}" "${REL_PATHS[$i]}"
done | sort -k2 > "$tmp_sidecar"
mv "$tmp_sidecar" "$SIDECAR"

echo "archive_historical.sh: sidecar written to $SIDECAR (${#REL_PATHS[@]} entries)"
