"""Freeze (register) the F5 calibration family -- the deliberate, reviewed act.

Preconditions (all recorded in docs/PREREG_F5_FAMILIES.md and
docs/WEEKEND_PROGRESS.md before this runs): universe frozen and independently
re-verified; methodology review READY AS AMENDED; final specification
appended; adversarial review PASS with R1/R2 fixed. Refuses to overwrite an
existing record. Never reads an outcome.
"""
import json
import sys

from src.research import f5_eval


def main() -> int:
    rec = f5_eval.freeze_family()
    summary = {k: v for k, v in rec.items() if not isinstance(v, (list, dict))}
    print(json.dumps(summary, indent=1, sort_keys=True))
    print("members:", rec.get("members"))
    print("frozen at:", f5_eval.FROZEN_FAMILY_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
