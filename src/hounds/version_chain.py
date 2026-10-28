"""A hound's LINEAGE: every version it has been, oldest first.

Used by the lineage-wide Deep reviews (``src/ai/deep_review.py``), the "all versions" spreadsheet (``api/hounds_postmortems.py``) and the
coaching and chat feed (``src/ai/hindsight_feed.py``), so the three agree on what "the same hound across versions" means.

TWO SHAPES MEET HERE. A MEMBER hound's versions are rows of the ``hounds`` table that share a ``root_id`` (``user_store``): each version
is a hound with its own id and its own ledger rows. A PACK hound's earlier versions are the stats book's ``<id>@v<n>`` archives and its
current version keeps the base id (``src/hounds/learning/lineage.py``). Anything else in the book is a lineage of one version.

Pure: the book's hounds and the member rows are passed in, so a test needs neither a database nor the app. ``load_user_rows`` is the one
function that reads the database, lazily, and it never raises. Nothing here changes a record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

ARCHIVE_SEP = "@v"                         # the same separator as src/hounds/learning/lineage.py (a test pins it)
SUPERSEDED_PREFIX = "superseded by"        # how user_store words a version a later one replaced


@dataclass(frozen=True)
class Member:
    hound_id: str
    version_no: int
    status: str                            # running | benched | retired | buried (or the stats book's own word)
    name: str = ""
    replaced: bool = False                 # an earlier version a later one replaced (an edit, a training, a promotion)

    @property
    def label(self) -> str:
        return f"v{self.version_no}"

    @property
    def status_text(self) -> str:
        """The version's status in plain words, for the spreadsheet's Version status column."""
        if self.replaced:
            return "replaced by a later version"
        return {"retired": "retired", "buried": "buried"}.get(self.status, self.status or "running")


@dataclass
class Chain:
    key: str                               # the lineage key: a member hound's root id, a pack hound's base id
    members: List[Member] = field(default_factory=list)       # oldest first

    @property
    def ids(self) -> List[str]:
        return [m.hound_id for m in self.members]

    @property
    def current(self) -> Optional[Member]:
        return self.members[-1] if self.members else None


def _split_archive(hound_id: str) -> Optional[tuple]:
    """``(base id, n)`` for ``<base>@v<n>``, else None."""
    base, sep, tail = str(hound_id).rpartition(ARCHIVE_SEP)
    return (base, int(tail)) if sep and base and tail.isdigit() else None


def _user_member(row: Mapping) -> Member:
    status = str(row.get("status") or "running")
    replaced = status == "retired" and str(row.get("retire_reason") or "").startswith(SUPERSEDED_PREFIX)
    return Member(hound_id=str(row["id"]), version_no=int(row.get("version_no") or 1), status=status, name=str(row.get("name") or ""),
                  replaced=replaced)


def build_chains(book_hounds: Mapping[str, Any], user_rows: Sequence[Mapping] = ()) -> Dict[str, Chain]:
    """{lineage key: Chain} for every hound in ``book_hounds`` ({hound id: HoundData}) and every member-hound version row in
    ``user_rows``. A member hound's chain is keyed by its root id and holds every version row (a retired or buried one too, whether or
    not the book has it); everything else is keyed by its base id."""
    chains: Dict[str, Chain] = {}
    user_ids = set()
    for row in sorted(user_rows, key=lambda r: (int(r.get("version_no") or 1), str(r.get("created_at") or ""), str(r["id"]))):
        user_ids.add(str(row["id"]))
        chains.setdefault(str(row.get("root_id") or row["id"]), Chain(str(row.get("root_id") or row["id"]))).members.append(_user_member(row))
    archived: Dict[str, List[tuple]] = {}
    current: Dict[str, str] = {}
    for hid in book_hounds:
        if hid in user_ids:
            continue
        split = _split_archive(hid)
        if split is not None:
            archived.setdefault(split[0], []).append((split[1], hid))
        else:
            current[hid] = hid
    for base in sorted(set(archived) | set(current)):
        chain = Chain(base)
        versions = sorted(archived.get(base, ()))
        for n, hid in versions:
            data = book_hounds.get(hid)
            chain.members.append(Member(hound_id=hid, version_no=n, status="retired", name=_name_of(data), replaced=True))
        if base in current:
            data = book_hounds.get(base)
            status = str(getattr(getattr(data, "summary", None), "status", "") or "running")
            chain.members.append(Member(hound_id=base, version_no=(versions[-1][0] + 1) if versions else 1, status=status,
                                        name=_name_of(data)))
        chains[base] = chain
    return chains


def _name_of(data: Any) -> str:
    return str(getattr(getattr(data, "summary", None), "name", "") or "")


def chain_for(hound_id: str, chains: Mapping[str, Chain]) -> Optional[Chain]:
    """The chain that holds this hound id (any version of it), or None."""
    for chain in chains.values():
        if hound_id in chain.ids:
            return chain
    return None


def version_of(hound_id: str, chains: Mapping[str, Chain]) -> Optional[Member]:
    chain = chain_for(hound_id, chains)
    return next((m for m in chain.members if m.hound_id == hound_id), None) if chain else None


def lineage_key_of(hound_id: str, root_id: Optional[str] = None) -> str:
    """The lineage key of a hound id without scanning anything: a member hound's root id when the caller has it, a pack archive's base
    id, else the id itself."""
    if root_id:
        return str(root_id)
    split = _split_archive(hound_id)
    return split[0] if split else str(hound_id)


def load_user_rows() -> List[dict]:
    """Every member-hound version row from the app database (retired and buried ones too), or [] when there is no database or it cannot
    be read. A public read must never be what makes the database appear, so a missing file is "no member hounds"."""
    try:
        from src.hounds import user_defs
        if not user_defs.db_exists():
            return []
        from src.hounds import user_store
        return list(user_store.list_all())
    except Exception:  # noqa: BLE001 -- a lineage view degrades to "no versions known", it never takes a page or a tick down
        return []


def member_ids(hound_id: str, book_hounds: Optional[Mapping[str, Any]] = None, user_rows: Optional[Iterable[Mapping]] = None) -> List[str]:
    """Every version id of the hound's lineage, oldest first; just ``[hound_id]`` when nothing more is known."""
    rows = list(user_rows) if user_rows is not None else load_user_rows()
    chain = chain_for(hound_id, build_chains(book_hounds or {}, rows))
    return chain.ids if chain is not None and chain.ids else [hound_id]
