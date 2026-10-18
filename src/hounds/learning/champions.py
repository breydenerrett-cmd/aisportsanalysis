"""Which version of each pack hound is the champion, as the pack runner needs to know it.

``pack_run.run`` asks ``champion_versions(PACK, events_path)`` for the hounds it should run. With no
promotion on record (every hound today) the answer is the PACK unchanged, the very same objects.
After a promotion, the promoted hound is returned wrapped (``tunables.VersionedHound``) with its new
knob values, its own id, and ``hound_version`` / ``params`` stamped on every row it writes, so each
bet carries the version that made it and the record can be split by version afterwards.

The registry file sits beside the ledger being written (``evidence/hounds_house_v1.jsonl`` ->
``evidence/hounds_learning_v1.jsonl``), so a test that points the runner at a temp ledger reads a
temp (absent) registry and never the repository's.

READING MUST NEVER STOP CAPTURE. A forward bet is worth only what it is worth at its lock. If the
registry cannot be read (a bad line, a missing directory), this returns the PACK as it is and says so
on stdout; the bet rows then carry no ``hound_version`` (they are version 1 rows, honestly, and a
broken chain is reported by ``python -m src.hounds.learning verify`` and the scorecard, which is
where a person looks). The promotion's effective time (``effective_utc``) is the lock-time floor of
the new version: a game whose lock came before the promotion is not bet by it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from src.hounds.learning import ledger as L
from src.hounds.learning import tunables


def events_path_beside(pack_ledger_path) -> Path:
    return Path(pack_ledger_path).parent / L.HOUSE_EVENTS


def champion_versions(hounds: Sequence, events_path) -> tuple:
    path = Path(events_path)
    if not path.exists():
        return tuple(hounds)
    try:
        state = L.fold(L.EventLog(path).read())
        tun = tunables.load()
    except Exception as exc:  # noqa: BLE001 -- capture outranks the registry; see the module docstring
        print(f"learning registry unreadable ({type(exc).__name__}: {exc}); running the pack as is")
        return tuple(hounds)
    out = []
    for h in hounds:
        t = tun.get(h.id)
        version = state.champion_version(h.id)
        if t is None or version <= 1:
            out.append(h)
            continue
        promo = max((p for p in state.promotions_for(h.id)), key=lambda p: int(p["to_version"]))
        values = tunables.full_values(t, state.champion_params(h.id))
        out.append(tunables.VersionedHound(
            h, t, values, row_extra={"hound_version": version, "params": values},
            min_lock=L.parse(promo.get("effective_utc") or promo.get("utc"))))
    return tuple(out)
