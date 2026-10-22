"""The hound's voice in Ask: one or two short lines, canned, no model.

The hound page's card speaks through web/js/hound-lines.js; Ask speaks through this file so an answer arrives already worded
(the Training camp's small chat and every other reader of ``lines`` get the same short answer). The voice KEY is the one
``right_now.voice_for`` reads off the hound's persona or its own rule, so the card and the answer sound like the same hound.

A line never says a pick is safe or certain, never talks about edge, value or profit, and never uses the canine word. Every
number in a line is one the caller passes in (the selection, the price). Deterministic: the same hound on the same game always
says the same thing (a stable hash picks the variant), so asking twice never changes its mind.
"""

from __future__ import annotations

import zlib
from typing import Optional

PICK = {
    "underdog": ["Long price, loud upset energy. {sel} at {price} is my kind of trouble.",
                 "Everyone else is looking the other way. {sel} at {price}, and I like the view."],
    "chalk": ["Boring on purpose. {sel} at {price}: I like my games to behave.",
              "No drama, no gimmicks. {sel} at {price} and a quiet night."],
    "chaos": ["Vibes only. {sel} at {price}, and I'm not explaining it.",
              "The dartboard pointed at {sel}. {price}. Sure, why not."],
    "nerd": ["Ran it twice, got the same answer. {sel} at {price} fits my rule cleanest.",
             "My spreadsheet is blushing. {sel} at {price}."],
    "steam": ["The market's leaning, so I'm leaning. {sel} at {price}.",
              "The number moved, I noticed. {sel} at {price}."],
    "mystic": ["The signs are loud tonight. {sel} at {price}.",
               "The letters lined up, I just listened. {sel} at {price}."],
    "gematria": ["The letters add up. {sel} at {price}.",
                 "Every name is a number if you squint. {sel} at {price}."],
    "degen": ["Itching for this one. {sel} at {price}, let's ride.",
              "Pulse is up. {sel} at {price}, and no regrets yet."],
    "grinder": ["Quiet work. {sel} at {price}, no fireworks.",
                "Same routine, same rule. {sel} at {price}."],
    "generic": ["This one fits my rule best right now. {sel} at {price}.",
                "If I had to pick one, it's {sel} at {price}."],
}

NOTHING = {
    "underdog": "No long shots speaking to me yet.",
    "chalk": "Nothing safe-looking enough to bother with.",
    "chaos": "The dartboard is silent. Suspicious.",
    "nerd": "Nothing clears my rule yet. I'm not bending it.",
    "steam": "The market hasn't moved my way yet.",
    "mystic": "The signs are quiet.",
    "gematria": "No sums are lining up.",
    "degen": "Nothing's got me twitchy. Yet.",
    "grinder": "Nothing fits. That's part of the job.",
    "generic": "Nothing fits my rule right now.",
}

CANNOT_RUN = "I can't run my rule on demand, so I can't name a pick right now."


def _pick_index(seed: str, n: int) -> int:
    return zlib.crc32(seed.encode("utf-8")) % n if n else 0


def pick_line(voice: str, selection: str, price_text: str, seed: str = "") -> str:
    """One line in the hound's voice naming the pick (the selection and the price are the caller's)."""
    options = PICK.get(voice) or PICK["generic"]
    return options[_pick_index(f"{voice}|{seed}", len(options))].format(sel=selection, price=price_text)


def nothing_line(voice: str, next_game: Optional[str] = None, when_text: str = "") -> str:
    """The empty state in the hound's voice, naming the next game it will check and when (or that it will look again)."""
    first = NOTHING.get(voice) or NOTHING["generic"]
    if next_game:
        return f"{first} Next game I'll check: {next_game}{', ' + when_text if when_text else ''}."
    return f"{first} I'll look again when a new game hits the board."
