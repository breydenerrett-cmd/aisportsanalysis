"""What a shared dog's picture says: the card behind ``GET /d/{hound_id}/card.png`` (api/hounds_share.py).

THE PICTURE IS THE LINK. A chat app or a social site shows a pasted link as the page's ``og:image``; before this
module the dog link had none, so it unfurled as a line of grey text. This module decides WHAT the 1200x630 card
says (this file: standard library only, so it loads on the Linux CI image that has neither FastAPI nor Pillow) and
``share_render`` (Pillow) draws it.

A CARD NEVER SHOWS A PICK OR A PRICE. It carries the dog's art, name, kennel, personality line, sports, settled
W-L and paper bankroll against the shared $1,000 start, and the hard line at the bottom. The dog's own words (name,
kennel name, tagline) are text a stranger typed, so ``scrub`` strips anything shaped like an American price
(``-110``, ``+150``) before it can reach the image; ``has_price`` is the same test, run over every string the
renderer will draw, and a unit test pins it. Nothing here says "profit", "edge" or "winning": a bankroll is a
number, shown the same way up or down.

PUBLIC DOGS ONLY. A dog that is retired, unknown, malformed or not loaded yet gets the GENERIC card (the brand, no
numbers). The page and the picture agree because both come from ``spec_from_info``: the page links
``/d/<id>/card.png?v=<digest>`` where the digest is the hash of exactly what the picture will say, so a changed
record is a new URL and a scraper that cached the old one fetches the new one.

THE ART. The browser draws the hound with a 3,000-line procedural rig (web/js/dog-rig.js, 33 breeds). This module
does not port that rig. It reads the same whitelisted LOOK (coat, eyes, background, accessories, art style, breed)
with the same colour tables and the same breed choice (the look's override, then a word in the name, then the
persona vibe, then a hash of the id), and ``share_render`` draws a simpler hound from them: one head per ear and
muzzle family, not one per breed. tests/test_hounds_share_card.py holds the colour tables to dog-look.js.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from src.hounds.interact import look as look_mod

CARD_W = 1200
CARD_H = 630
STORY_W = 1080
STORY_H = 1920

#: The hard line on every image (owner wording, 2026-10-20). It leaves the site, so it travels with the picture.
FOOTER = "21+ · Paper bets · 1-800-GAMBLER"
WORDMARK = "LINEHOUND"
#: Bump when the drawing changes, so every cached card is a new hash.
RENDER_VERSION = 3

#: What a model needs to be "ranked in full", read from seasons so the card and the board never disagree.
try:  # pragma: no cover - the import cannot fail in the repo; the default keeps the card alive if it ever did
    from src.hounds.seasons import MIN_RANKED_BETS
except Exception:  # noqa: BLE001
    MIN_RANKED_BETS = 10
START_BANKROLL = 1000.0

REASON_PUBLIC = "public"
REASON_RETIRED = "retired"
REASON_UNKNOWN = "unknown"
REASON_WARMING = "warming"

# ---- the look tables: the same colours as web/js/dog-look.js (a test holds them together) --------------------------

COATS = {
    "tan": ("#C9A06B", "#9F7746", "#E2C79B"), "black": ("#2B2F36", "#14171B", "#4A515C"),
    "white": ("#E9ECF1", "#C3C9D3", "#FFFFFF"), "grey": ("#8C95A4", "#646C7A", "#B5BCC8"),
    "brown": ("#7A5638", "#573A24", "#9A7455"), "golden": ("#E0B24A", "#BC8B2A", "#F1D58F"),
    "red": ("#B4533C", "#8A3A29", "#D07C63"), "merle": ("#7E93B2", "#596C8A", "#A9B8CE"),
}
EYES = {"brown": "#5A3A1E", "amber": "#C98A1B", "blue": "#4A8FD8", "green": "#4BA36B", "hazel": "#8A6B2F"}
BACKGROUNDS = {
    "navy": ("#1B3157", "#0C1730"), "slate": ("#38465A", "#1B2330"), "charcoal": ("#3A3F48", "#181B20"),
    "forest": ("#1F5A40", "#0E2A1E"), "maroon": ("#63293A", "#2F121B"), "teal": ("#18646C", "#0A2F34"),
    "violet": ("#51397F", "#241A3E"), "sand": ("#8A7450", "#493C27"),
}
LEGACY_BREEDS = look_mod.BREEDS[:25]
VIBE_BREED = {"grinder": "bulldog", "nerd": "schnauzer", "degen": "husky", "chaos": "mutt", "psychic": "hound"}
NAME_BREED = {
    "chihuahua": "chihuahua", "collie": "collie", "corgi": "corgi", "dalmatian": "dalmatian", "greyhound": "greyhound",
    "bulldog": "bulldog", "husky": "husky", "schnauzer": "schnauzer", "basset": "basset", "bloodhound": "bloodhound",
    "beagle": "beagle", "setter": "setter", "spaniel": "spaniel", "terrier": "terrier", "pointer": "pointer",
    "whippet": "whippet", "kelpie": "kelpie", "lab": "labrador", "labrador": "labrador", "newfie": "newfoundland",
    "newfoundland": "newfoundland", "retriever": "retriever", "poodle": "poodle", "professor": "poodle",
    "shepherd": "shepherd", "leader": "shepherd", "jack": "jackrussell", "hank": "hound", "hound": "hound",
    "mutt": "mutt", "doberman": "doberman", "dobie": "doberman", "rottweiler": "rottweiler", "rottie": "rottweiler",
    "pitbull": "pitbull", "staffy": "pitbull", "wolfhound": "wolfhound", "boxer": "boxer", "mastiff": "mastiff",
    "shiba": "shiba", "malinois": "malinois",
}

# ---- strangers' words ------------------------------------------------------------------------------------------

#: An American price: a sign and three or four digits not glued to a word or another number ("-110", "+1500").
#: "1-800-GAMBLER" and "63-46" do not match (the sign follows a digit, or the digits are too few).
PRICE_RE = re.compile(r"(?<![\w$.,])[+\-−]\d{3,4}(?!\d)")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SPACE_RE = re.compile(r"\s+")


def has_price(text: Any) -> bool:
    return bool(PRICE_RE.search(str(text or "")))


def scrub(text: Any, limit: int = 120) -> str:
    """A stranger's text made safe for the picture: control characters gone, anything past Latin-1 gone (the shipped
    fonts are Latin subsets, and a box in place of an emoji is worse than no emoji), prices gone, one space between
    words, cut at ``limit``. Empty in, empty out."""
    s = _CTRL_RE.sub(" ", str(text if text is not None else ""))
    s = "".join(ch for ch in s if ord(ch) <= 0xFF)
    s = PRICE_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s[:limit].rstrip()


# ---- the look ---------------------------------------------------------------------------------------------------

def hash_str(text: Any) -> int:
    """FNV-1a over UTF-16 code units, 32 bit: web/js/dog-look.js hashStr."""
    x = 2166136261
    s = str(text if text is not None else "")
    data = s.encode("utf-16-le")
    for i in range(0, len(data), 2):
        x ^= data[i] | (data[i + 1] << 8)
        x = (x * 16777619) & 0xFFFFFFFF
    return x


def default_look(seed: Any) -> dict:
    """The look of a dog nobody has dressed (web/js/dog-look.js lookFor): coat, eyes and background by id hash."""
    x = hash_str(seed)
    coats, eyes, bgs = list(COATS), list(EYES), list(BACKGROUNDS)
    out = dict(look_mod.DEFAULT_LOOK)
    out.update(coat=coats[x % len(coats)], eyes=eyes[(x >> 5) % len(eyes)], bg=bgs[(x >> 9) % len(bgs)])
    out.pop("v", None)
    return out


def clean_look(raw: Any, seed: Any = None) -> dict:
    """The look with every key checked against the whitelist; anything unknown falls back to the default."""
    base = default_look(seed) if seed is not None else {k: v for k, v in look_mod.DEFAULT_LOOK.items() if k != "v"}
    if not isinstance(raw, Mapping):
        return base
    out = dict(base)
    for key, allowed in look_mod.CHOICES.items():
        value = raw.get(key)
        if isinstance(value, str) and value in allowed:
            out[key] = value
    number = raw.get("number")
    out["number"] = number if (isinstance(number, int) and not isinstance(number, bool) and 0 <= number <= 99
                               and out["body"] == "jersey") else None
    return out


def breed_for(look: Mapping, hound_id: str = "", name: str = "", vibe: str = "") -> str:
    """The breed a dog is drawn as (web/js/dog-rig.js breedFor): the look's override, else a word in its id or
    name, else its persona vibe, else a stable pick from its id over the original 25."""
    own = look.get("breed") if isinstance(look, Mapping) else ""
    if own and own != "auto" and own in look_mod.BREEDS:
        return own
    for word in re.split(r"[^a-z0-9]+", f"{hound_id} {name}".lower()):
        if word in NAME_BREED:
            return NAME_BREED[word]
    if vibe in VIBE_BREED:
        return VIBE_BREED[vibe]
    key = hound_id or name
    return LEGACY_BREEDS[hash_str(key) % len(LEGACY_BREEDS)] if key else "retriever"


# ---- the spec ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CardSpec:
    """Every word and number on a card, already scrubbed. ``generic`` cards carry the brand and no numbers."""
    name: str
    kennel: str
    tagline: str
    sports: tuple
    record: Optional[str]            # "63-46" (with pushes "63-46-2"), or None when the dog has no readable record
    bankroll: Optional[str]          # "$1,042", or None
    start: str                       # "$1,000"
    ranked_note: Optional[str]       # "Ranked in full at 10 settled bets" below the bar
    look: dict = field(default_factory=dict)
    breed: str = "retriever"
    generic: bool = False
    reason: str = REASON_PUBLIC

    def texts(self) -> list:
        """Every string the renderer draws (for the no-price guard and the tests)."""
        out = [WORDMARK, self.name, self.kennel, self.tagline, FOOTER, *self.sports]
        out += [t for t in (self.record, self.bankroll, self.ranked_note) if t]
        if self.record is not None or self.bankroll is not None:
            out += ["RECORD", "PAPER BANKROLL", f"start {self.start}"]
        if self.generic:
            out.append(GENERIC_LINE)
        return [t for t in out if t]

    def digest(self) -> str:
        """16 hex characters naming exactly what the picture says: the cache key, the ETag and the ``?v=``."""
        payload = json.dumps({"v": RENDER_VERSION, "w": CARD_W, "h": CARD_H, "name": self.name, "kennel": self.kennel,
                              "tagline": self.tagline, "sports": list(self.sports), "record": self.record,
                              "bankroll": self.bankroll, "start": self.start, "ranked": self.ranked_note,
                              "look": self.look, "breed": self.breed, "generic": self.generic},
                             sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


GENERIC_TAGLINE = "Build a hound with rules you can read. Every bet is graded, win or lose."
GENERIC_LINE = "Paper bets. Graded win or lose."


def generic_spec(reason: str = REASON_UNKNOWN) -> CardSpec:
    """The card for a dog that is not public (retired, unknown, not loaded): the brand and nothing about any dog.
    One look for all of them, so it is one image, one hash, one cached render."""
    look = clean_look({"coat": "golden", "eyes": "brown", "bg": "navy", "style": "mascot", "breed": "retriever"})
    return CardSpec(name="Find your hound", kennel="LINEHOUND kennel", tagline=GENERIC_TAGLINE, sports=(),
                    record=None, bankroll=None, start=money(START_BANKROLL), ranked_note=None, look=look,
                    breed="retriever", generic=True, reason=reason)


def money(value: float) -> str:
    return f"-${abs(round(value)):,}" if round(value) < 0 else f"${round(value):,}"


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _sport_label(raw: Any) -> str:
    text = scrub(raw, 12).upper()
    return text


def wl_text(record: Mapping) -> str:
    bets = _num(record.get("bets")) or 0
    if bets <= 0:
        return "0-0"
    pushes = int(record.get("pushes") or 0)
    return f"{int(record.get('wins') or 0)}-{int(record.get('losses') or 0)}" + (f"-{pushes}" if pushes else "")


def spec_from_info(hound_id: str, info: Optional[Mapping]) -> CardSpec:
    """The card for a dog described by ``share_page.lookup``'s info dict. Retired dogs and missing info give the
    generic card. Keys read (all optional): name, tagline, catchphrase, record, status, retired, kind,
    owner_display, sports, bankroll, settled, vibe, look."""
    if not isinstance(info, Mapping):
        return generic_spec(REASON_UNKNOWN)
    if str(info.get("status") or "") == "retired" or info.get("retired"):
        return generic_spec(REASON_RETIRED)
    name = scrub(info.get("name") or hound_id, 40) or "Hound"
    kennel = scrub(info.get("owner_display"), 40)
    if not kennel:
        kennel = "LINEHOUND house kennel" if str(info.get("kind") or "house") != "user" else "A LINEHOUND kennel"
    line = ""
    for candidate in (info.get("catchphrase"), info.get("tagline")):
        text = scrub(candidate, 140)
        if text and not has_price(text):
            line = text
            break
    sports = tuple(s for s in (_sport_label(x) for x in (info.get("sports") or [])[:4]) if s)
    record = info.get("record") if isinstance(info.get("record"), Mapping) and info.get("record") else None
    rec_text = wl_text(record) if record is not None else None
    bank = info.get("bankroll") if isinstance(info.get("bankroll"), Mapping) else None
    current = _num((bank or {}).get("current"))
    start = _num((bank or {}).get("start")) or START_BANKROLL
    bank_text = money(current) if current is not None else (money(start) if record is not None
                                                            and (_num(record.get("bets")) or 0) <= 0 else None)
    settled = _num(info.get("settled"))
    if settled is None and record is not None:
        settled = float(int(record.get("wins") or 0) + int(record.get("losses") or 0) + int(record.get("pushes") or 0))
    ranked = None
    if rec_text is not None and settled is not None and settled < MIN_RANKED_BETS:
        ranked = f"Ranked in full at {MIN_RANKED_BETS} settled bets"
    look = clean_look(info.get("look"), seed=hound_id or name)
    breed = breed_for(look, hound_id, name, str(info.get("vibe") or ""))
    return CardSpec(name=name, kennel=kennel, tagline=line, sports=sports, record=rec_text, bankroll=bank_text,
                    start=money(start), ranked_note=ranked, look=look, breed=breed)


def look_for(hound_id: str) -> Optional[dict]:
    """The saved look of a member's dog, or None (house dogs and dogs nobody dressed). Cosmetic: a failure is None."""
    try:
        from src.hounds.interact import common, store
        dog = common.resolve(hound_id)
        if dog is None or dog.kind != common.KIND_USER:
            return None
        return store.get_looks({dog.root_id}).get(dog.root_id)
    except Exception:  # noqa: BLE001 -- a look is decoration; its table never takes a card down
        return None


def spec_for(hound_id: str) -> CardSpec:
    """The card for a dog id, from the same lookup the share page uses. Never raises, never waits for a build."""
    from src.hounds import share_page
    try:
        state, info = share_page.lookup(hound_id)
    except Exception:  # noqa: BLE001
        return generic_spec(REASON_UNKNOWN)
    if state == share_page.STATE_OK and info is not None:
        return spec_from_info(hound_id, info)
    return generic_spec(REASON_WARMING if state == share_page.STATE_WARMING else REASON_UNKNOWN)


# ---- rendering and the cache -------------------------------------------------------------------------------------

class RenderUnavailable(RuntimeError):
    """Pillow is not installed: the route answers 503 instead of a broken image."""


_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
CACHE_ENTRIES = 64                   # ~100 KB each: a few MB, and the generic card is always one of them


def png_for(spec: CardSpec) -> bytes:
    """The PNG for a spec, rendered once per digest."""
    key = spec.digest()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    try:
        from src.hounds import share_render
    except ImportError as exc:       # Pillow missing
        raise RenderUnavailable(str(exc)) from exc
    png = share_render.render_card(spec)
    with _CACHE_LOCK:
        _CACHE[key] = png
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_ENTRIES:
            _CACHE.popitem(last=False)
    return png


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def card_path(hound_id: str, digest: Optional[str] = None) -> str:
    from urllib.parse import quote
    base = f"/d/{quote(hound_id, safe='')}/card.png"
    return f"{base}?v={digest}" if digest else base
