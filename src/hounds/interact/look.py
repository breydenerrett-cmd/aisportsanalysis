"""The locker room: a dog's look, validated against a fixed whitelist.

A look is a small JSON of CHOICES, never colours or markup: ``{"coat": "tan", "eyes": "brown", "bg": "navy",
"head": "cap", "face": "sunglasses", "neck": "chain", "body": "jersey", "number": 23}``. Every value must be a
key of a table in this file, so nothing a user sends can reach a page as a colour string, a URL or SVG. The
page turns the keys into colours (web/js/dog-avatar.js keeps the same tables; a test holds the two together).

The accessories are the owner's list: cap, headband, visor (one head piece), sunglasses, chain, jersey with a
number, hoodie (one body piece). The look is cosmetic. It changes no rule, no ticket, no record.
"""

from __future__ import annotations

from typing import Any, Mapping

LOOK_VERSION = 1

COATS = ("tan", "black", "white", "grey", "brown", "golden", "red", "merle")
EYES = ("brown", "amber", "blue", "green", "hazel")
BACKGROUNDS = ("navy", "slate", "charcoal", "forest", "maroon", "teal", "violet", "sand")
HEAD = ("none", "cap", "headband", "visor")
FACE = ("none", "sunglasses")
NECK = ("none", "chain")
BODY = ("none", "hoodie", "jersey")
NUMBER_MAX = 99

DEFAULT_LOOK = {"v": LOOK_VERSION, "coat": "tan", "eyes": "brown", "bg": "navy", "head": "none",
                "face": "none", "neck": "none", "body": "none", "number": None}

CHOICES = {"coat": COATS, "eyes": EYES, "bg": BACKGROUNDS, "head": HEAD, "face": FACE, "neck": NECK,
           "body": BODY}
FIELDS = tuple(CHOICES) + ("number",)


class LookError(ValueError):
    """A look the whitelist refuses. ``errors`` is {field: message}, every problem at once."""

    def __init__(self, errors: Mapping[str, str]):
        self.errors = dict(errors)
        super().__init__("; ".join(f"{k}: {v}" for k, v in self.errors.items()))


def validate_look(raw: Any) -> dict:
    """The look as stored, or raise ``LookError``. Missing fields take the default; unknown fields, wrong
    types and values off the whitelist are refused, all at once."""
    errors: dict = {}
    if not isinstance(raw, Mapping):
        raise LookError({"look": "send the look as an object"})
    for key in raw:
        if key not in FIELDS and key != "v":
            errors[str(key)[:30]] = "not a part of a look"
    out = dict(DEFAULT_LOOK)
    for key, allowed in CHOICES.items():
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str) or value not in allowed:
            errors[key] = "choose one of: " + ", ".join(allowed)
        else:
            out[key] = value
    if "number" in raw and raw["number"] is not None:
        number = raw["number"]
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= NUMBER_MAX:
            errors["number"] = f"a whole number from 0 to {NUMBER_MAX}, or none"
        else:
            out["number"] = number
    if out["number"] is not None and out["body"] != "jersey" and "number" not in errors:
        errors["number"] = "a number goes on the jersey: pick the jersey first"
    if errors:
        raise LookError(errors)
    out["v"] = LOOK_VERSION
    return out


def menu() -> dict:
    """What the locker room offers, for the page and for the tests."""
    return {"coat": list(COATS), "eyes": list(EYES), "bg": list(BACKGROUNDS), "head": list(HEAD),
            "face": list(FACE), "neck": list(NECK), "body": list(BODY), "number_max": NUMBER_MAX,
            "default": dict(DEFAULT_LOOK)}
