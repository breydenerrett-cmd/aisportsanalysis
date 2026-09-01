#!/usr/bin/env bash
# scripts/ci.sh -- the one command a paid-beta trust check runs: fail fast,
# on the first thing that's wrong, with a one-line summary at the end.
#
# WHY THESE STEPS, IN THIS ORDER
# --------------------------------
# 1. The full unit suite. Cheapest and broadest signal -- if a plain unit
#    test is red, nothing downstream is worth spending time on.
# 2. Two specific tests named explicitly, not just swept up by discover:
#    tests/test_api_boundary.py (the src/-is-stdlib-only gate -- src/ must
#    import with no third-party package on the path, and must never import
#    api/) and tests/test_customer_language.py (the banned-vocabulary
#    tripwire -- "+EV", "guaranteed", "win probability", etc. must never
#    reappear in a customer-facing string or field name). Both already run
#    under `discover` in step 1; naming them again here means a change that
#    silently excludes them from discovery (a renamed class, a stray
#    `__test__ = False`) still gets caught by name, not by hoping discovery
#    still finds them.
# 3. scripts/smoke_api.sh: a real uvicorn process taking a real HTTP
#    request over a real socket -- the one check in this whole sequence that
#    exercises the actual server process, not a function call in-process.
#
# set -e (not just -u) is what makes this fail-fast: the first non-zero exit
# stops the script right there, rather than running every remaining step
# against a codebase already known to be broken.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== [1/4] full unit suite (python3 -m unittest discover) =="
python3 -m unittest discover -s tests -q

echo
echo "== [2/4] src/-stdlib boundary gate (tests/test_api_boundary.py) =="
python3 -m unittest tests.test_api_boundary -q

echo
echo "== [3/4] banned-vocabulary tripwire (tests/test_customer_language.py) =="
python3 -m unittest tests.test_customer_language -q

echo
echo "== [4/4] live smoke test against a real uvicorn process =="
bash scripts/smoke_api.sh

echo
echo "== scripts/ci.sh: all checks passed =="
