#!/usr/bin/env bash
# Live window runner: poll, evaluate rules, capture odds, record candidates, commit.
set -uo pipefail
cd "$(dirname "$0")/.."

SPORT="${1:-}"
MAX_MINUTES="${2:-330}"

if [ -z "$SPORT" ]; then
    echo "Usage: $0 <sport> [max_minutes]" >&2
    echo "  sport: mlb or nfl" >&2
    echo "  max_minutes: default 330" >&2
    exit 1
fi

export LIVE_WINDOW_COMMIT=1
python3 -m src.pipeline.live_window --sport "$SPORT" --max-minutes "$MAX_MINUTES"
