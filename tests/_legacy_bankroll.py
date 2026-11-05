"""Pins the reference account these older tests were written against ($1,000 start, $10 unit).

Since 2026-11-05 the product's reference account is $2,500 / $25 (config/bankroll.json, src/hounds/unit_size.py START_USD).
The arithmetic these tests hold does not depend on the numbers, and re-deriving hundreds of hand-worked dollar figures
would prove nothing new, so each module pins the old constants for itself with ``pin()``/``unpin()`` from
setUpModule/tearDownModule. tests/test_unit_size.py holds the real $2,500 / $25 lock.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

from src.hounds import bankroll as bk

_state = {}


def pin():
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "bankroll.json"
    path.write_text(json.dumps({"currency": "USD", "paper": True, "starting_bankroll": 1000, "unit_pct": 1.0,
                                "small_sample_min_settled": 20, "fallback_settle_hours_after_slate_start": 30}), encoding="utf-8")
    patcher = mock.patch.object(bk, "config_path", lambda: path)
    patcher.start()
    _state["tmp"], _state["patcher"] = tmp, patcher


def unpin():
    _state["patcher"].stop()
    _state["tmp"].cleanup()
