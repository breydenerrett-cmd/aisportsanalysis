"""The official ``anthropic`` SDK client for the hound rebuild, built in ONE place outside ``src/hounds/interact``.

``src/hounds/interact`` is pinned by a test to import no model client at all (the Ask chat calls no model), so the rebuild's SDK
import lives here and the rebuild reaches it through ``build_client``. The import is lazy: the CI image may not have the package, and
a missing package means "unavailable right now", never a crash. Retries are limited to one (the rebuild owns its own spend guard).
"""

from __future__ import annotations

DEFAULT_TIMEOUT_S = 120.0
MAX_RETRIES = 1


def build_client(api_key: str, timeout_s: float = DEFAULT_TIMEOUT_S):
    import anthropic                     # noqa: PLC0415 -- lazy by design
    return anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=MAX_RETRIES)
