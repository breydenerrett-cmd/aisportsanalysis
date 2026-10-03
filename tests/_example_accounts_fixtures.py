"""Shared set-up for the example-accounts tests: the REAL ledger rows, copied
into tests/fixtures/example_accounts/ on 2026-10-03, rebuilt as temporary
hash-chained ledgers and pointed at by patching the ledger module's paths.
No test that uses this reads evidence/ or any live data file.

What the fixtures are (all three were read from the checkout, not edited):
  mlb_v2_rows.json  the V2 ledger's newest `card_settled` row for each of its
                    nine settled dates (2026-09-22 .. 2026-10-01) and the
                    `card_published` row of 2026-10-03, which is not settled.
                    Hashes are dropped and the chain is rebuilt on write.
  nfl_cards.jsonl   evidence/cards_nfl_v1.jsonl, byte for byte.
  ufc_cards.jsonl   evidence/cards_mma_v1.jsonl, byte for byte.

The numbers the site published from these rows on that day, which the tests
pin: MLB counted 16-17, 5 voids, -5.0463u; MLB postseason (graded, not
counted) 0-2, -2.0u; NFL 1-0, +0.9259u; UFC 5-1, 1 void, +2.5027u.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from src.appstate import card_ledger
from src.ledger.chain import HashChainLedger

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "example_accounts"

PUBLISHED = {
    "mlb_counted": {"picks": 38, "wins": 16, "losses": 17, "pushes": 0, "voids": 5, "units": -5.0463},
    "mlb_postseason": {"picks": 2, "wins": 0, "losses": 2, "pushes": 0, "voids": 0, "units": -2.0},
    "nfl": {"picks": 1, "wins": 1, "losses": 0, "pushes": 0, "voids": 0, "units": 0.9259},
    "ufc": {"picks": 7, "wins": 5, "losses": 1, "pushes": 0, "voids": 1, "units": 2.5027},
}


def mlb_v2_payloads() -> list:
    return json.loads((FIXTURES / "mlb_v2_rows.json").read_text(encoding="utf-8"))


def ufc_text_with(mutate) -> str:
    """The UFC fixture with `mutate(row)` applied to every row and the chain
    rebuilt, so the result is a corrupted ledger whose chain still VERIFIES:
    the case a tamper check cannot catch and the reconciliation must. Rows that
    name another row by hash (`published_row_hash`, `supersedes_row_hash`) are
    pointed at the rebuilt hashes."""
    with tempfile.TemporaryDirectory() as tmp:
        ledger = HashChainLedger(os.path.join(tmp, "rechained.jsonl"))
        remap = {}
        for line in (FIXTURES / "ufc_cards.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            old = row.pop("row_hash")
            row.pop("prev_hash")
            for key in ("published_row_hash", "supersedes_row_hash"):
                if row.get(key) in remap:
                    row[key] = remap[row[key]]
            mutate(row)
            remap[old] = ledger.append(row)["row_hash"]
        return Path(ledger.path).read_text(encoding="utf-8")


def build_v2_ledger(path, payloads=None) -> None:
    ledger = HashChainLedger(path)
    for payload in (mlb_v2_payloads() if payloads is None else payloads):
        ledger.append(payload)


@contextlib.contextmanager
def fixture_ledgers(v2_payloads=None, ufc_text=None):
    """Temp ledgers built from the fixtures and the ledger module pointed at
    them (V2, the empty V1 file, NFL, UFC) for the length of the block. The
    results store is emptied, so which MLB games are postseason is decided by
    the ledger's own evidence alone (frozen game type and the season's
    calendar), never by a data file on this machine. Yields the paths."""
    with tempfile.TemporaryDirectory() as tmp:
        v2 = os.path.join(tmp, "cards_v2.jsonl")
        v1 = os.path.join(tmp, "cards_v1.jsonl")          # never written: V1 is not read
        nfl = os.path.join(tmp, "cards_nfl_v1.jsonl")
        ufc = os.path.join(tmp, "cards_mma_v1.jsonl")
        build_v2_ledger(v2, v2_payloads)
        shutil.copyfile(FIXTURES / "nfl_cards.jsonl", nfl)
        if ufc_text is None:
            shutil.copyfile(FIXTURES / "ufc_cards.jsonl", ufc)
        else:
            Path(ufc).write_text(ufc_text, encoding="utf-8")
        by_sport = {None: v1, "": v1, "mlb": v1, "nfl": nfl, "mma": ufc}

        def store_path(sport=None):
            return by_sport[sport]

        patches = [
            mock.patch.object(card_ledger, "CARD_STORE_V2", v2),
            mock.patch.object(card_ledger, "CARD_STORE", v1),
            mock.patch.object(card_ledger, "store_path", store_path),
            mock.patch("src.pipeline.history.read_results", lambda *a, **k: {}),
        ]
        for patch in patches:
            patch.start()
        try:
            yield {"v2": v2, "v1": v1, "nfl": nfl, "ufc": ufc, "dir": tmp}
        finally:
            for patch in reversed(patches):
                patch.stop()
