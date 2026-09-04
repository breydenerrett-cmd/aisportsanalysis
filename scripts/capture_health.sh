#!/usr/bin/env bash
# One-line capture-health check: `src.capture.health.assess()` on the real
# repo state, printed and turned into an exit code so this is usable
# straight from a shell, a cron mail, or a session's own tool call without
# anyone having to parse Python. Prints exactly one `CAPTURE_HEALTH: ...`
# line (HealthReport.summary()) and exits 0 for RUNNING/HEALTHY_IDLE, 2 for
# OVERDUE/FAILED/UNKNOWN -- so `scripts/capture_health.sh || alert` works.
set -uo pipefail
cd "$(dirname "$0")/.."

python3 - "$@" <<'PYEOF'
import sys
from src.capture.health import assess, RUNNING, HEALTHY_IDLE

report = assess()
print(report.summary())
sys.exit(0 if report.state in (RUNNING, HEALTHY_IDLE) else 2)
PYEOF
