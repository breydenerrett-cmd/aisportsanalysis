"""Freeze (register) the confirmatory totals family -- the deliberate, reviewed act.

Preconditions (recorded in docs/PREREG_TOTALS_FAMILIES.md and
docs/WEEKEND_PROGRESS.md): universe manifest frozen and dry-run verified;
methodology review READY AS AMENDED; FINAL SPECIFICATION appended;
adversarial review PASS after the post-adversarial amendments. Refuses to
overwrite an existing record. Never reads an outcome.
"""
import json
import sys

from src.research import totals_eval


def main() -> int:
    rec = totals_eval.freeze_confirmatory_family()
    summary = {k: v for k, v in rec.items() if not isinstance(v, (list, dict))}
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    print("members:", rec.get("members"))
    print("frozen at:", totals_eval.CONFIRMATORY_FROZEN_FAMILY_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
