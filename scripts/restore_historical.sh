#!/usr/bin/env bash
# scripts/restore_historical.sh -- restore the PAID historical odds purchase
# from data/archive/historical/ back into data/historical/. Companion to
# scripts/archive_historical.sh (read that script's header first).
#
# This is what a fresh container -- or a git clone that never ran the
# original ingest -- uses to get data/historical/odds_history/ and
# data/historical/odds_first_five/ back without re-buying anything.
#
# SAFETY: data/historical/ is a live, ephemeral-disk directory. Between an
# archive being made and a restore being run, the on-disk copy could have
# grown (more seasons ingested) or simply differ for reasons this script has
# no way to judge. So by default this refuses to touch any existing
# destination file whose content differs from what the archive holds --
# "differs" covers "newer" too, since a file that grew or was re-ingested
# will never hash-match the archive. Pass --force to overwrite anyway. A
# destination file that already matches the archive is left untouched
# either way (restoring is a no-op, not an error).
#
# Every restored file's sha256 is checked against
# data/archive/historical/SHA256SUMS BEFORE it is ever written to
# data/historical/ -- a corrupt archive is refused, never installed.
#
# Usage: scripts/restore_historical.sh [--force]
set -euo pipefail
cd "$(dirname "$0")/.."

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        *)
            echo "restore_historical.sh: unknown argument: $arg (only --force is accepted)" >&2
            exit 2
            ;;
    esac
done

SRC_ROOT="data/archive/historical"
DST_ROOT="data/historical"
SIDECAR="$SRC_ROOT/SHA256SUMS"

if [[ ! -f "$SIDECAR" ]]; then
    echo "restore_historical.sh: no sidecar at $SIDECAR -- nothing has been archived yet" >&2
    exit 1
fi

sha256_of() { sha256sum "$1" | cut -d' ' -f1; }

status=0

while read -r expected_hash rel_path; do
    [[ -n "${rel_path:-}" ]] || continue

    if [[ "$rel_path" == *.gz ]]; then
        dst_rel="${rel_path%.gz}"
        whole="$SRC_ROOT/$rel_path"
        tmp_out="$(mktemp)"
        if [[ -f "$whole" ]]; then
            gunzip -c "$whole" > "$tmp_out"
        else
            parts=("$SRC_ROOT/$rel_path.part-"*)
            if [[ ! -f "${parts[0]:-/nonexistent}" ]]; then
                echo "restore_historical.sh: no archive on disk for $rel_path (missing both the .gz and its split parts)" >&2
                rm -f "$tmp_out"
                status=1
                continue
            fi
            cat "$SRC_ROOT/$rel_path.part-"* | gunzip -c > "$tmp_out"
        fi
    else
        dst_rel="$rel_path"
        src_plain="$SRC_ROOT/$rel_path"
        if [[ ! -f "$src_plain" ]]; then
            echo "restore_historical.sh: no archive on disk for $rel_path" >&2
            status=1
            continue
        fi
        tmp_out="$(mktemp)"
        cp "$src_plain" "$tmp_out"
    fi

    actual_hash="$(sha256_of "$tmp_out")"
    if [[ "$actual_hash" != "$expected_hash" ]]; then
        echo "restore_historical.sh: SHA256 MISMATCH for $rel_path -- expected $expected_hash, got $actual_hash. Archive may be corrupt; refusing to restore it." >&2
        rm -f "$tmp_out"
        status=1
        continue
    fi

    dst_path="$DST_ROOT/$dst_rel"
    if [[ -e "$dst_path" ]]; then
        existing_hash="$(sha256_of "$dst_path")"
        if [[ "$existing_hash" == "$actual_hash" ]]; then
            rm -f "$tmp_out"
            echo "up to date: $dst_rel"
            continue
        fi
        if [[ "$FORCE" != 1 ]]; then
            echo "restore_historical.sh: refusing to overwrite existing, DIFFERENT $dst_path -- pass --force to overwrite" >&2
            rm -f "$tmp_out"
            status=1
            continue
        fi
    fi

    mkdir -p "$(dirname "$dst_path")"
    mv "$tmp_out" "$dst_path"
    echo "restored: $dst_rel"
done < "$SIDECAR"

exit "$status"
