"""Rewrite every web page's static navigation block to the kennel-first shape (owner ruling 2026-10-20).

    python scripts/apply_kennel_nav_block.py [--check]

web/js/nav.js rebuilds the `<header class="lh-nav">` block when it runs, so the markup below is what a visitor sees with
scripts off and what tests/test_kennel_page.py pins. It is the SIGNED-OUT shape: Leaderboard, Live, Sign in and one primary
"Find your hound" button (docs/design/KENNEL_FIRST_BRIEF.md). Idempotent: running it twice changes nothing. A page keeps its
own `data-hook`, `data-bottom` and (renamed) `data-current`; the landing page keeps its `data-nav-extra` button and funnel hook;
the quiz and the builder carry no button (that is where it leads). Re-run it after merging a branch that added or edited a
page's nav block. `--check` prints the pages that are not canonical and exits 1.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
OLD_KEYS = {"build": "create", "camp": "mykennel", "kennels": "leaderboard"}
NO_CTA_PAGES = {"quiz.html", "build-a-hound.html"}
BLOCK = re.compile(r'<header class="lh-nav"([^>]*)>.*?</header>', re.S)


def _attrs(opening: str) -> dict:
    return dict(re.findall(r'([\w-]+)="([^"]*)"', opening))


def block_for(name: str, old_opening: str, old_block: str) -> str:
    attrs = _attrs(old_opening)
    raw_current = attrs.get("data-current")          # kept as the page wrote it (the old keys still work: nav.js ALIASES)
    current = OLD_KEYS.get(raw_current, raw_current) if raw_current is not None else None
    opening = ['class="lh-nav"', 'aria-label="primary"']
    if "data-hook" in attrs:
        opening.append(f'data-hook="{attrs["data-hook"]}"')
    if raw_current is not None:
        opening.append(f'data-current="{raw_current}"')
    if "data-bottom" in attrs:
        opening.append(f'data-bottom="{attrs["data-bottom"]}"')
    open_tag = "<header " + " ".join(opening) + ">"

    def link(href, key, label):
        cur = ' aria-current="page"' if current == key else ""
        return f'      <a href="{href}" data-nav="{key}"{cur}>{label}</a>'

    cta = ""
    if "data-nav-extra" in old_block:
        # the landing page's own button keeps its funnel hook and its place in the bar
        cta = '\n      <a class="lh-btn lh-btn--solid" href="quiz.html" data-hook="cta-primary" data-nav-extra>Find your hound</a>'
    elif name not in NO_CTA_PAGES:
        cta = '\n      <a class="lh-btn lh-btn--solid" href="quiz.html" data-hook="nav-cta">Find your hound</a>'
    return (
        f'{open_tag}\n'
        '  <div class="lh-nav__bar">\n'
        '    <a class="lh-nav__brand ps-page__home" href="landing.html" aria-label="LINEHOUND home">\n'
        '      <span class="wordmark" data-hook="brand-mark">\n'
        '        <span class="wordmark__mark"><span></span></span>\n'
        '        <span class="wordmark__text" data-hook="product-name">LINEHOUND</span>\n'
        '      </span>\n'
        '    </a>\n'
        '    <nav class="lh-nav__links" aria-label="Sections" data-hook="nav-links">\n'
        f'{link("hounds.html", "leaderboard", "Leaderboard")}\n'
        f'{link("live.html", "live", "Live")}\n'
        '    </nav>\n'
        '    <div class="lh-nav__account" data-hook="nav-account-area" data-signed-in="false">\n'
        '      <a class="lh-btn lh-btn--soft" href="index.html#/signin" data-hook="nav-signin">Sign in</a>'
        f'{cta}\n'
        '    </div>\n'
        '  </div>\n'
        '</header>'
    )


def main(argv) -> int:
    check = "--check" in argv
    off = []
    for path in sorted(WEB.glob("*.html")):
        text = path.read_bytes().decode("utf-8")
        m = BLOCK.search(text)
        if not m:
            continue
        new = block_for(path.name, m.group(1), m.group(0))
        # keep the file's own line endings (the repo has CRLF checkouts)
        eol = "\r\n" if "\r\n" in m.group(0) else "\n"
        new = new.replace("\n", eol)
        if new == m.group(0):
            continue
        off.append(path.name)
        if not check:
            path.write_bytes((text[:m.start()] + new + text[m.end():]).encode("utf-8"))
    print(("not canonical: " if check else "rewrote: ") + (", ".join(off) or "none"))
    return 1 if (check and off) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
