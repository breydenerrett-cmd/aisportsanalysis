"""No customer-facing page promises "three to five" picks a day.

The landing page's headline and meta description, the signup card and the
matchup page all said the card holds three to five bets a day. The card's
final publish held 7 to 13 picks a day from 2026-09-14 to 09-20 (game picks
plus props; evidence/cards_v1.jsonl), so the count was false on the page that
sells the subscription. Found by the 2026-09-21 fact-check. Comments that
explain the history may still mention it; rendered copy may not.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
PATTERN = re.compile(r"three to five|3\s*(?:-|to)\s*5 (?:bets|picks)", re.IGNORECASE)


def _rendered_text(path: Path) -> str:
    """The file minus its comments -- only what can reach a reader."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(line.split("//", 1)[0] if not line.lstrip().startswith("//") else ""
                     for line in text.splitlines())


class NoFalsePickCount(unittest.TestCase):
    def test_no_rendered_copy_promises_three_to_five(self):
        offenders = []
        for path in [WEB / "landing.html", *sorted((WEB / "js").glob("*.js"))]:
            for match in PATTERN.finditer(_rendered_text(path)):
                offenders.append(f"{path.name}: {match.group(0)!r}")
        self.assertEqual(offenders, [], "a page promises a pick count the card does not keep")


if __name__ == "__main__":
    unittest.main()
