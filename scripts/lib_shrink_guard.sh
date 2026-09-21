# Shared by scripts/capture_slot.sh and scripts/forward_capture.sh.
#
# WHY THIS EXISTS (2026-09-16 incident, fully diagnosed before this was
# written): data/historical/lineups.jsonl was silently truncated NINE times.
# The writer (src/pipeline/lineup_store.py:198) was never the problem -- it
# opens in "a" (append) mode and never shrinks anything. The loss happened in
# CI: .github/workflows/forward-capture.yml:186-221 runs two
# actions/cache/restore@v4 steps against the same paths, and by that
# workflow's own comment "last restore wins" -- the second restore unpacks a
# STALE cached copy of the file over the freshly checked-out worktree.
# scripts/capture_slot.sh and scripts/forward_capture.sh then `git add`
# whatever bytes are on disk and commit them, no questions asked. A
# 4,993-row store became 119 rows this way, eleven minutes after a backfill
# had landed it.
#
# Nothing caught it. capture_slot.sh's only row-delta check (F5_BEFORE /
# F5_AFTER) watches data/processed/f5_close.jsonl, a different file, and
# only fires on absolute zero. scripts/publication_audit.py never looks at
# data/historical. src/pipeline/health.py's lineup section read
# data/watch/lineups_watch.jsonl -- also a different file, the poller's own
# fetch log -- which stayed healthy the whole time (see the companion fix in
# that module), so the product reported lineups fine while the store that
# api/games.py and enrichment.py actually read for batting orders emptied
# out from under it.
#
# WHAT THIS DOES NOT DO, ON PURPOSE
# ----------------------------------
# It does not touch the CI cache steps -- this guard has to hold even if the
# cache keeps clobbering the worktree, and un-poisoning the cache is a
# different, riskier fix than catching what it poisons.
# It does not add an absolute row floor -- any fixed number is wrong on some
# future date (an off day, a slow backfill), so the only safe comparison is
# against what this repo's own HEAD already has.
# It does not change the writer -- lineup_store.py's append-only behavior is
# already correct; the corruption happens after it, in git staging.
# H4 (2026-09-16): protection used to depend on capture_slot.sh and
# forward_capture.sh each carrying their own literal three-path list --
# a new append-only store was only protected if a future person remembered
# to edit both. read_append_only_stores replaces that hand-kept list with
# a single declaration (scripts/append_only_stores.txt) both scripts read.
# See that file's header for the format and why it's a flat text list.
#
# Prints one repo-root-relative path per line, comments and blanks
# stripped. Callers pass its output, unquoted, to git add / guard_staged_
# no_shrink exactly the way the old literal lists were passed -- none of
# these paths contain spaces, so word-splitting is safe and matches the
# rest of this file's style.
read_append_only_stores() {
    local declfile line
    declfile="$(dirname "${BASH_SOURCE[0]}")/append_only_stores.txt"
    if [ ! -f "$declfile" ]; then
        echo "ESCALATE: $declfile missing, no append-only stores declared" >&2
        return 0
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%#*}"                     # strip trailing comment
        line="${line#"${line%%[![:space:]]*}"}" # trim leading whitespace
        line="${line%"${line##*[![:space:]]}"}" # trim trailing whitespace
        [ -n "$line" ] && printf '%s\n' "$line"
    done < "$declfile"
}

guard_staged_no_shrink() {
    local path staged_blob head_blob staged_n head_n unit
    for path in "$@"; do
        # No HEAD version to compare against: a brand-new file cannot shrink.
        head_blob=$(git rev-parse "HEAD:$path" 2>/dev/null) || continue

        # Empty means nothing is staged at this path right now (git add found
        # nothing, or the path was deleted) -- treated as a shrink to zero
        # rather than skipped, since a vanished file is the extreme case of
        # the same failure.
        staged_blob=$(git rev-parse ":$path" 2>/dev/null) || staged_blob=""

        # jsonl stores are one row per line, so a line count IS a row count
        # and reads naturally in the escalation. matchup_pairs.json is a
        # single line of JSON: a line count there is always 1 -> 1 and would
        # protect nothing, so non-jsonl paths compare byte size instead. Two
        # different units, on purpose -- never pretend one rule covers both.
        case "$path" in
            *.jsonl)
                unit="rows"
                head_n=$(git cat-file -p "$head_blob" | wc -l | tr -d ' ')
                if [ -z "$staged_blob" ]; then
                    staged_n=0
                else
                    staged_n=$(git cat-file -p "$staged_blob" | wc -l | tr -d ' ')
                fi
                ;;
            *)
                unit="bytes"
                head_n=$(git cat-file -s "$head_blob")
                if [ -z "$staged_blob" ]; then
                    staged_n=0
                else
                    staged_n=$(git cat-file -s "$staged_blob")
                fi
                ;;
        esac

        if [ "$staged_n" -lt "$head_n" ]; then
            # Unstage AND restore the worktree copy from HEAD for this path
            # only -- the rest of whatever else is staged in this commit
            # must still land. One poisoned file must not block a whole
            # capture slot.
            git restore --staged --worktree -- "$path"
            # scripts/escalations.py:extract_escalate_lines matches any line
            # starting "ESCALATE:" (escalations.py:109-116) and cmd_check
            # exits non-zero for a NEW one -- this routes into the existing
            # alarm channel with no new state or constant.
            echo "ESCALATE: $path would shrink $head_n -> $staged_n $unit, refusing"
        fi
    done
}

# WHY THIS EXISTS (2026-09-21 incident): data/processed/odds_multibook.jsonl
# grew to 100.08 MB and GitHub started rejecting every push from the capture
# runners --
#
#   remote: error: File data/processed/odds_multibook.jsonl is 100.08 MB;
#   this exceeds GitHub's file size limit of 100.00 MB
#   ESCALATE: push failed after retries -- commit is local only, needs
#   manual push
#
# -- silently losing a 13-minute capture slot every time it fired, because
# the local commit that held it could never reach origin. src.pipeline.
# store_archive (`python3 -m src.cli store rotate`) is the fix for
# odds_multibook itself; this guard is the backstop for every OTHER store
# that grows toward the same 100MB wall before anyone adds it to rotation --
# derivative_markets.jsonl (63MB), evidence/decisions_v2.jsonl (57MB) and
# batter_props.jsonl (40MB) were all already headed there the day this was
# written (store_archive.py's own module docstring cites the same numbers).
#
# CHECKS THE STAGED BLOB, NOT THE WORKING-TREE FILE -- same distinction
# guard_staged_no_shrink makes above, for the same reason: what actually
# gets pushed is the staged blob, `git cat-file -s`, never a `wc -c` on the
# working copy, which could disagree with what is about to be committed.
#
# THRESHOLDS ARE MiB, MATCHING GITHUB'S OWN ERROR MESSAGE. GitHub states its
# limit as "100.00 MB" but a store measured exactly at the wall printed
# "100.08 MB" for a file `ls -l` also reports in binary units -- so this
# guard's MB is MiB (1,048,576 bytes) throughout, deliberately conservative
# against GitHub's own decimal-vs-binary ambiguity rather than risking a
# WARN or ESCALATE that fires a few MB later than the real limit does.
# "${VAR:-default}", not a plain assignment -- same convention
# scripts/capture_slot.sh's CHAIN_* constants use, so a test can override
# either threshold (tests/test_lib_shrink_guard.py does, to prove the gate
# fires without writing genuinely 75-95MB files into a throwaway repo on
# every run of the fast suite) without touching this file.
GUARD_SIZE_ESCALATE_MIB="${GUARD_SIZE_ESCALATE_MIB:-95}"
GUARD_SIZE_WARN_MIB="${GUARD_SIZE_WARN_MIB:-75}"

# Checks EVERY currently staged path, not a fixed list: an oversized blob
# can arrive from any committing script and any store (see the incident
# note above), and the whole point of this guard is to catch the NEXT store
# that grows into the wall, not only the one already fixed. Callers run this
# after staging and before `git commit` -- exactly like guard_staged_no_
# shrink, this only ever prints; it never unstages or blocks a commit, so
# one oversized-but-otherwise-fine file never costs the rest of a capture
# slot (the ESCALATE line is what a human, or scripts/escalations.py, acts
# on). MUST NEVER print file contents -- only sizes, via `git cat-file -s`.
guard_staged_size() {
    local path blob size_bytes size_mib
    for path in $(git diff --cached --name-only); do
        blob=$(git rev-parse ":$path" 2>/dev/null) || continue
        size_bytes=$(git cat-file -s "$blob" 2>/dev/null) || continue
        size_mib=$((size_bytes / 1048576))
        if [ "$size_mib" -ge "$GUARD_SIZE_ESCALATE_MIB" ]; then
            echo "ESCALATE: $path is ${size_mib} MB staged; GitHub rejects files over 100 MB -- this push will fail"
        elif [ "$size_mib" -ge "$GUARD_SIZE_WARN_MIB" ]; then
            echo "WARN: $path is ${size_mib} MB; add it to store rotation before it reaches 100 MB"
        fi
    done
}
