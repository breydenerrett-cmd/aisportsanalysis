"""A prepared game's folder, and where every stage stands.

LAYOUT (one folder per game, `evidence/hounds_desk/<date>_<AWAY>-<HOME>/`, football `<date>_nfl_<A>-<H>`)

    packet.json            the frozen data, byte for byte what the analyst pipeline builds
    prepare.json           what was prepared: hashes, caps, token estimates, event id
    requests/<stage>_a<N>.json   the request for attempt N of a stage (the file a subagent reads)
    answers/<stage>_a<N>.json    the answer file a subagent writes
    stages/<stage>/attempts.jsonl, attempt_N.json   the publication rule's record (src/analyst/pilot.py)
    transcript.json        written at publish: every stage's every attempt, for the public page
    disagreement.json      written at publish: where the hounds disagree

THE PUBLICATION RULE IS THE PILOT'S CODE
----------------------------------------
Attempts are recorded and judged by `pilot.record_attempt` / `pilot.publication_refusal` /
`pilot.eligibility`, with the stage's folder as the "folder" and the hash of the stage's FIRST request as the
"packet hash" (the identity the attempts belong to). Nothing about the rule is re-implemented here.

STAGE STATES
------------
    blocked    an upstream stage is not final yet
    todo       waiting for attempt `next_attempt` (the first, or a re-answer after a rejection)
    clean      the latest attempt was not rejected: final
    exhausted  three attempts, the latest rejected: final (the latest attempt is still the one used)

`final` = clean or exhausted. A later stage is built only from FINAL upstream stages, and only from their
checked material.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from src import paths
from src.analyst import pilot
from src.ledger.chain import canonical_bytes
from src.hounds.desk import builder, checks, roles

EVIDENCE_DIR = os.path.join("evidence", "hounds_desk")

MAX_ATTEMPTS = pilot.MAX_ATTEMPTS
MAX_GAMES_PER_RUN = 2
MAX_ANSWERS_PER_RUN = 30

BLOCKED, TODO, CLEAN, EXHAUSTED = "blocked", "todo", "clean", "exhausted"
FINAL = (CLEAN, EXHAUSTED)


class DeskError(RuntimeError):
    """A refusal. The message is printed as is; nothing was changed."""


def root_of(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else paths.repo_root()


def desk_dir(root: Optional[Path] = None) -> Path:
    return root_of(root) / EVIDENCE_DIR


def game_folder(sport: str, date: str, away: str, home: str, root: Optional[Path] = None) -> Path:
    tag = "" if sport == "mlb" else f"{sport}_"
    return desk_dir(root) / f"{date}_{tag}{away.upper()}-{home.upper()}"


def read_json(target: Path, what: str):
    try:
        return json.loads(Path(target).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DeskError(f"{what} not found: {target}") from None
    except (OSError, ValueError) as exc:
        raise DeskError(f"{what} could not be read as JSON: {target} ({exc})") from None


def request_hash(body: Mapping) -> str:
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


@dataclass
class Game:
    folder: Path
    meta: dict
    packet: dict

    # --- paths -------------------------------------------------------------------------------
    def request_file(self, stage: str, attempt: int) -> Path:
        return self.folder / "requests" / f"{stage}_a{attempt}.json"

    def answer_file(self, stage: str, attempt: int) -> Path:
        return self.folder / "answers" / f"{stage}_a{attempt}.json"

    def stage_dir(self, stage: str) -> Path:
        return self.folder / "stages" / stage

    # --- identity ----------------------------------------------------------------------------
    @property
    def game_id(self) -> str:
        return self.meta["game_id"]

    @property
    def label(self) -> str:
        return f"{self.meta['away']}@{self.meta['home']} {self.meta['date']}" + \
            ("" if self.meta.get("sport", "mlb") == "mlb" else f" ({self.meta['sport']})")

    def stages(self) -> tuple:
        return roles.ALL_STAGES

    def first_request_hash(self, stage: str) -> Optional[str]:
        target = self.request_file(stage, 1)
        if not target.exists():
            return None
        return request_hash(read_json(target, f"{stage} request"))

    def attempts(self, stage: str) -> list:
        digest = self.first_request_hash(stage)
        if digest is None:
            return []
        return pilot.read_attempts(self.stage_dir(stage), digest)

    # --- state -------------------------------------------------------------------------------
    def state(self, stage: str) -> dict:
        """`{state, attempts, next_attempt, last, reason}` for one stage."""
        role = roles.ROLES[stage]
        attempts = self.attempts(stage)
        if attempts:
            last = attempts[-1]
            if not last.get("rejected"):
                return {"state": CLEAN, "attempts": len(attempts), "next_attempt": None, "last": last}
            if len(attempts) >= MAX_ATTEMPTS:
                return {"state": EXHAUSTED, "attempts": len(attempts), "next_attempt": None, "last": last}
            return {"state": TODO, "attempts": len(attempts), "next_attempt": len(attempts) + 1,
                    "last": last}
        for need in role.needs:
            if self.state(need)["state"] not in FINAL:
                return {"state": BLOCKED, "attempts": 0, "next_attempt": None, "last": None,
                        "waiting_for": need}
        return {"state": TODO, "attempts": 0, "next_attempt": 1, "last": None}

    def attempt_response(self, stage: str, number: int):
        """(raw bytes, parsed response) of a recorded attempt."""
        raw = pilot.read_response_bytes(str(pilot.attempt_file(self.stage_dir(stage), number)))
        return raw, pilot.parse_response(raw)

    def final_check(self, stage: str) -> Optional["checks.StageCheck"]:
        """The check of a FINAL stage's latest attempt, recomputed (the checker is deterministic), or None
        when the stage is not final or its latest attempt cannot be read."""
        st = self.state(stage)
        if st["state"] not in FINAL:
            return None
        try:
            _raw, response = self.attempt_response(stage, st["attempts"])
        except pilot.PilotError:
            return None
        return checks.check_stage(self.packet, response, roles.ROLES[stage])

    def upstream(self, stage: str) -> dict:
        """The checked material of the stages `stage` needs: {need: material or None}."""
        out = {}
        for need in roles.ROLES[stage].needs:
            result = self.final_check(need)
            out[need] = result.material if result is not None else None
        return out

    # --- requests ----------------------------------------------------------------------------
    def ensure_request(self, stage: str, cfg: Mapping) -> Optional[Path]:
        """The request file for the stage's next attempt, written if it is not on disk. None when the
        stage is blocked or final. A request file is never rewritten: it is what the writer was given."""
        st = self.state(stage)
        if st["state"] != TODO:
            return None
        n = st["next_attempt"]
        target = self.request_file(stage, n)
        if target.exists():
            return target
        role = roles.ROLES[stage]
        repair = (st["last"] or {}).get("rejection_lines") if n > 1 else None
        body = builder.build_request(self.packet, role, cfg, self.upstream(stage), repair)
        target.parent.mkdir(parents=True, exist_ok=True)
        pilot._write_json(target, body)
        return target


def load(folder) -> Game:
    base = Path(folder)
    meta = read_json(base / "prepare.json", "prepare.json")
    packet = read_json(base / "packet.json", "packet.json")
    if not isinstance(meta, Mapping) or not isinstance(packet, Mapping):
        raise DeskError(f"{base}: prepare.json and packet.json must be JSON objects")
    from src.analyst import packet as packet_mod
    digest = packet_mod.packet_hash(packet)
    if digest != meta.get("packet_hash"):
        raise DeskError(f"the packet in {base} is not the packet that was prepared "
                        f"(hash {digest[:12]}, prepare.json says {str(meta.get('packet_hash'))[:12]}); "
                        "move the folder aside and prepare the game again")
    return Game(base, dict(meta), dict(packet))


def games_for_date(date: str, root: Optional[Path] = None) -> list:
    """Every prepared game folder for `date`, loaded, earliest start first. A folder that cannot be loaded
    is reported by raising: a damaged record must not be skipped quietly."""
    base = desk_dir(root)
    if not base.is_dir():
        return []
    found = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name.startswith(f"{date}_") and (child / "prepare.json").exists():
            found.append(load(child))
    found.sort(key=lambda g: (g.meta.get("start_utc") or "", g.game_id))
    return found


def attempts_recorded(game: Game) -> int:
    return sum(game.state(s)["attempts"] for s in game.stages())


def has_work(game: Game) -> bool:
    """True once any answer has been recorded or the game published: its folder cannot be re-prepared."""
    return attempts_recorded(game) > 0 or (game.folder / "transcript.json").exists()
