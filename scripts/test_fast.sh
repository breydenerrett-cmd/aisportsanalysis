#!/usr/bin/env bash
# FAST tier: every tests/test_*.py module except the measured slow poles in
# tests/slow_modules.txt, run through scripts/test_parallel.py.
#
# WHAT THIS SKIPS AND WHY THAT'S A SAFE TRADE FOR DEVELOPMENT
# --------------------------------------------------------------
# tests/slow_modules.txt names ~13 modules (parameter sweeps over synthetic
# odds histories, a full replay, a real in-process HTTP app under test) that
# individually measured at >= 4 seconds -- see that file's header for the
# exact numbers and the list of what is deliberately NOT excluded. Skipping
# them here trades a small, known blind spot (their own coverage) for fast
# iteration; it is never a substitute for the full run declared done, which
# is exactly why every agent config that mentions testing says "fast tier
# while developing, full parallel run before declaring done" -- never fast
# tier as the last check.
#
# On this repo's own measured numbers (see scripts/module_timings.json), the
# fast tier finishes in well under a minute with 4 workers; the "<= 4
# minutes" budget in the name is deliberately generous headroom for a
# slower machine, a colder cache, or a checkout where some of the excluded
# modules' non-excluded siblings run slower than measured here -- not a
# number this script is meant to hug.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 scripts/test_parallel.py --exclude-file tests/slow_modules.txt "$@"
