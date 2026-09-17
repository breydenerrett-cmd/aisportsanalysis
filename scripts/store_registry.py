#!/usr/bin/env python3
"""Python-side reader for scripts/append_only_stores.txt -- the single
declaration of append-only stores that scripts/lib_shrink_guard.sh's
read_append_only_stores() also reads (shell side; see that function's
docstring for why the format is a flat newline-delimited text file rather
than JSON/YAML). This module exists so the parsing rule lives in exactly
one place on the Python side too: tests/test_lib_shrink_guard.py's lint
imports it rather than re-implementing "skip blanks and #-comments".

Stdlib only, by the same constraint as everything else this repo's tooling
runs under (no PyYAML, no third-party parser).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DECLARATION_FILE = REPO_ROOT / "scripts" / "append_only_stores.txt"


def load_declared_stores(declaration_file: Path = DECLARATION_FILE) -> list[str]:
    """Return the declared repo-root-relative paths, in file order.

    Missing file -> empty list (matches the shell reader's tolerance: no
    declaration means nothing is protected, not a crash -- the caller
    decides whether that's an escalation).
    """
    if not declaration_file.exists():
        return []
    stores = []
    for raw_line in declaration_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            stores.append(line)
    return stores
