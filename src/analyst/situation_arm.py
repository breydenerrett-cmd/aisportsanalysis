"""Arm A and arm B: the side-by-side test of the situation layer.

THE EXPERIMENT IN ONE PARAGRAPH
-------------------------------
Two analysts run on the same games. ARM A is the analyst that has always run: it reads the
matchup statistics. ARM B is the same analyst (same model, same schema, same critic, same
grading) given the same packet plus the situation layer (`sections.situation`) and the same
prompt plus four rules on weighing it (`situation_prompt.py`). Each arm freezes its calls before
the game into its OWN ledger, each is graded from the same results, and `analyst compare` says,
per sport and market family, how A and B did. After enough graded calls per family the record
says whether the situation layer helps; a layer that does not is reported as a loser and dropped.

WHAT STAYS EXACTLY AS IT WAS
----------------------------
Arm A. Its prompt, its packet (no `situation` key, same version, same hash), its ledger file
(`evidence/analyst_v1.jsonl`, `evidence/analyst_ufc_v1.jsonl`), its cost log and its row shape are
untouched, and tests pin all of that. The switch is off by default: `config/analyst.json`
`situation_arm.enabled` is false, and `analyst run` without `--arm` runs arm A only.

THE SWITCH
----------
`config/analyst.json`: `"situation_arm": {"enabled": true}` makes every `analyst run` run both
arms, game by game (A then B for the same game, so both are frozen minutes apart and a game that
starts between them is skipped by both, not just one). `--arm A`, `--arm B` and `--arm both`
override it for one run. Arm B costs about what arm A costs plus the situation section (see
`docs/SITUATION_LAYER.md` for the measured size): turning it on roughly doubles the analyst's
spend. The spend cap is shared, so a run still cannot pass it.

WHERE ARM B WRITES
------------------
`evidence/analyst_v1_situation.jsonl` (MLB) and `evidence/analyst_ufc_v1_situation.jsonl` (UFC),
with their own cost logs and packet directories beside them. A row carries `arm: "B"`, so the
comparison refuses a file that is not arm B's. Nothing here edits a card, a pick, a gate or a
published result, and nothing places a bet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from src import paths
from src.analyst import analyst as analyst_mod
from src.analyst import ledger as mlb_ledger
from src.analyst import ufc_analyst
from src.analyst import ufc_ledger
from src.situation import record as situation_record

ARM_A, ARM_B = "A", "B"
ARMS = (ARM_A, ARM_B)
ARM_CHOICES = ("A", "B", "both")

# Arm B's files, beside arm A's. Named in the brief; a documented equivalent would be a change
# the owner has to know about.
MLB_B_STORE = os.path.join("evidence", "analyst_v1_situation.jsonl")
MLB_B_USAGE = os.path.join("evidence", "analyst_usage_v1_situation.jsonl")
MLB_B_PACKETS = os.path.join("evidence", "analyst_packets_v1_situation")
UFC_B_STORE = os.path.join("evidence", "analyst_ufc_v1_situation.jsonl")
UFC_B_USAGE = os.path.join("evidence", "analyst_ufc_usage_v1_situation.jsonl")
UFC_B_PACKETS = os.path.join("evidence", "analyst_ufc_packets_v1_situation")


@dataclass(frozen=True)
class Arm:
    """One arm of the test for one sport: its prompt, its identity in a row, its files."""
    name: str
    sport: str
    situation: bool
    system_prompt: str
    prompt_version: Optional[str]          # None: the sport's own default (arm A)
    store: str                              # repo-relative default paths
    usage: str
    packet_dir: str
    extra: Optional[Mapping]               # fields written into every published row

    @property
    def tag(self) -> str:
        """What a log line says to name the arm. Arm A's lines are unchanged: no tag."""
        return "" if self.name == ARM_A else f"[arm {self.name}] "

    def abs_store(self) -> str:
        return str(paths.repo_root() / self.store)

    def abs_usage(self) -> str:
        return str(paths.repo_root() / self.usage)

    def abs_packet_dir(self) -> str:
        return str(paths.repo_root() / self.packet_dir)


def mlb_arm(name: str) -> Arm:
    if name == ARM_A:
        return Arm(ARM_A, "mlb", False, analyst_mod.SYSTEM_PROMPT, None, mlb_ledger.STORE,
                   mlb_ledger.USAGE_STORE, mlb_ledger.PACKET_DIR, None)
    if name == ARM_B:
        return Arm(ARM_B, "mlb", True, analyst_mod.SITUATION_SYSTEM_PROMPT,
                   analyst_mod.SITUATION_PROMPT_VERSION, MLB_B_STORE, MLB_B_USAGE, MLB_B_PACKETS,
                   {"arm": ARM_B, "situation_version": situation_record.VERSION})
    raise ValueError(f"no arm {name!r}")


def ufc_arm(name: str) -> Arm:
    if name == ARM_A:
        return Arm(ARM_A, "ufc", False, ufc_analyst.UFC_SYSTEM_PROMPT, None, ufc_ledger.STORE,
                   ufc_ledger.USAGE_STORE, ufc_ledger.PACKET_DIR, None)
    if name == ARM_B:
        return Arm(ARM_B, "ufc", True, ufc_analyst.UFC_SITUATION_SYSTEM_PROMPT,
                   ufc_analyst.UFC_SITUATION_PROMPT_VERSION, UFC_B_STORE, UFC_B_USAGE, UFC_B_PACKETS,
                   {"arm": ARM_B, "situation_version": situation_record.VERSION})
    raise ValueError(f"no arm {name!r}")


def selected_arms(choice: Optional[str], cfg: Mapping) -> Sequence[str]:
    """The arms a run should make: `choice` (A, B or both) when given, else the config switch
    (`situation_arm.enabled`: both arms; off: arm A only, which is what the analyst has always done)."""
    if choice is None:
        return (ARM_A, ARM_B) if (cfg.get("situation_arm") or {}).get("enabled") else (ARM_A,)
    if choice == "both":
        return (ARM_A, ARM_B)
    if choice in ARMS:
        return (choice,)
    raise ValueError(f"--arm must be one of {ARM_CHOICES}, got {choice!r}")


def b_store_exists(sport: str) -> bool:
    path = paths.repo_root() / (MLB_B_STORE if sport == "mlb" else UFC_B_STORE)
    return path.exists()
