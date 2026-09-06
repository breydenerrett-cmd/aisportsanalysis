#!/usr/bin/env bash
# scripts/foundry_beat.sh -- sourceable helper for THE FOUNDRY's Phase 4B
# heartbeat contract (see /home/user/thefoundry/PHASE4_HEARTBEAT_CONTRACT.md).
#
# Appends one JSON line per event to `<repo>/.foundry/events.jsonl`. Foundry
# is read-only; this only ever emits. Never write secrets, prompts, PII, raw
# API payloads, URLs with tokens, or transcript content into `artifact`/
# `error` -- short descriptive strings only.
#
# Usage: foundry_beat component event status [artifact] [error]
#   component: short stable id (forward_capture, daily_loop, monitor_remote, test_runner)
#   event:     start | end | status | escalate
#   status:    ok | degraded | down | escalate
#   artifact:  optional short string (truncated to 200 chars)
#   error:     optional one-line string (truncated to 200 chars, newlines stripped)
#
# Must NEVER fail the caller or change its exit code/output: everything runs
# in a subshell with its own errors swallowed. Safe under `set -u`.

foundry_beat() {
    (
        _fb_component="${1:-}"
        _fb_event="${2:-}"
        _fb_status="${3:-}"
        _fb_artifact="${4:-}"
        _fb_error="${5:-}"

        _fb_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
        if [ -z "$_fb_root" ]; then
            _fb_root="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd)"
        fi
        [ -z "$_fb_root" ] && exit 0

        mkdir -p "$_fb_root/.foundry" 2>/dev/null || exit 0
        _fb_file="$_fb_root/.foundry/events.jsonl"

        # Truncate to 200 chars and strip newlines from free-text fields.
        _fb_artifact="$(printf '%s' "$_fb_artifact" | tr '\n\r' '  ' | cut -c1-200)"
        _fb_error="$(printf '%s' "$_fb_error" | tr '\n\r' '  ' | cut -c1-200)"

        if command -v python3 >/dev/null 2>&1; then
            python3 - "$_fb_component" "$_fb_event" "$_fb_status" "$_fb_artifact" "$_fb_error" \
                >>"$_fb_file" 2>/dev/null <<'PY' || true
import json, sys, datetime
c, e, s, a, err = (sys.argv[1:6] + ["", "", "", "", ""])[:5]
rec = {"component": c, "event": e, "status": s,
       "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
if a:
    rec["artifact"] = a
if err:
    rec["error"] = err
print(json.dumps(rec))
PY
        else
            # Pure-bash fallback JSON escaper: backslash and double-quote only.
            _fb_esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
            _fb_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            _fb_line="{\"component\":\"$(_fb_esc "$_fb_component")\",\"event\":\"$(_fb_esc "$_fb_event")\",\"status\":\"$(_fb_esc "$_fb_status")\",\"ts\":\"$_fb_ts\""
            [ -n "$_fb_artifact" ] && _fb_line="${_fb_line},\"artifact\":\"$(_fb_esc "$_fb_artifact")\""
            [ -n "$_fb_error" ] && _fb_line="${_fb_line},\"error\":\"$(_fb_esc "$_fb_error")\""
            _fb_line="${_fb_line}}"
            printf '%s\n' "$_fb_line" >>"$_fb_file" 2>/dev/null || true
        fi
        exit 0
    ) || true
}
