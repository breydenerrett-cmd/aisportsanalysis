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
