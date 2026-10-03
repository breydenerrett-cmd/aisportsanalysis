"""Rebuild the golden file behind tests/test_ufc_read_golden.py.

The file holds three cases, each as the SHEET the read was built from and the READ it produced:

  * vettori_v_naurdiev_upcoming   a real upcoming bout (UFC 332): real records, physical attributes and prices,
                                  and no earlier fights in the saved responses
  * rosas_v_barcelos_afterwards   the real 2026-09-26 main event as it stands afterwards: each fighter's one fight
                                  on file, with real statistics, a real result and a real closing price
  * synthetic_main_event          the data layer's synthetic world (five fighters, twelve fights), where every rule
                                  of the read has something to say

The first two are built from the real ESPN responses saved in tests/fixtures/espn_mma, run through the data layer's own
parsers (tests/_ufc_real_fixture_store.py); the third from tests/test_datasvc_ufc_features.build_store. Nothing here
touches the network, a deployed host, or the real backfill.

The golden test rebuilds each read from the stored sheet and compares, so any change to the read's wording or logic
shows up as a diff that a person has to look at and accept. A second test checks the stored sheets still equal what the
data layer builds, so a data-layer change is a different failure from a wording change. Run this only when one of them
changed on purpose:

    python3 scripts/regen_ufc_read_fixtures.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "tests" / "fixtures" / "ufc_read_golden.json"
SYNTHETIC_NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)


def build_sheets() -> dict:
    from src.datasvc.ufc import matchup
    from tests import _ufc_real_fixture_store as real
    from tests.test_datasvc_ufc_features import build_store

    with tempfile.TemporaryDirectory() as tmp:
        sheets = real.golden_sheets(real.build(Path(tmp) / "real"))
        synthetic = build_store(Path(tmp) / "synthetic")
        sheets["synthetic_main_event"] = matchup.matchup(synthetic, "101", "102", now=SYNTHETIC_NOW)
    return sheets


def build_cases() -> dict:
    from src.analysis import ufc_read
    return {name: {"sheet": sheet, "read": ufc_read.build_read(sheet)} for name, sheet in build_sheets().items()}


def main() -> None:
    cases = build_cases()
    GOLDEN.write_text(json.dumps({"cases": cases}, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {GOLDEN.relative_to(ROOT)}: {', '.join(cases)}")


if __name__ == "__main__":
    main()
