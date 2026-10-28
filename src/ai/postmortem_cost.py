"""What a hindsight review costs: real prices, the API's own ``usage``, and the worst case a request could add.

WHY ITS OWN FILE. The post-mortem budget (``postmortems.POSTMORTEM_MONTHLY_USD``) is a hard wall in code, and a wall is only as
good as its arithmetic. This module is pure (no clock, no network, no files) so every price rule can be tested to the cent.

PRICES (claude-api skill, ``shared/models.md`` and ``shared/model-migration.md``, read 2026-10-28), per million tokens:

  claude-haiku-5-5   $0.10 in / $0.50 out when the prompt is 100K tokens or fewer; $0.50 / $2.50 above that.
  claude-sonnet-5-5  $2.00 in / $10.00 out. Cache writes 1.25x the input price, cache reads 0.10x (the 5-minute rates).
  web search         $10 per 1,000 searches, i.e. $0.01 each, on top of the tokens the results add. Code execution is free when
                     it runs with a web search tool (``shared/tool-use-concepts.md``), so the Sonnet dynamic-filtering version
                     adds no container charge.
  Message Batches    50% of the token prices. The skill docs do not say the search fee is discounted, so it is NOT: a search
                     is charged in full in a batch. That errs toward spending less.

THE USAGE IS THE BILL. ``usage_cost`` prices what the response says it used (input, cache writes and reads, output, and
``server_tool_use.web_search_requests``), never a guess. A response with NO usage returns None and the caller charges the worst
case: a missing number is never a free call.

THE WORST CASE (``worst_case_cost``) is what the pre-check adds to the month's spend BEFORE a request goes out, so the cap holds
even for the request that would have crossed it. It is generous on purpose: the prompt's characters at 3 per token, every search
result the request may pull in at ``WORST_TOKENS_PER_SEARCH`` tokens, re-read ``WORST_REREAD_FACTOR`` times by the loop the server
runs between searches, every output token ``max_tokens`` allows, and every search ``max_uses`` allows.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"

#: model -> (input, output, input past LONG_PROMPT_TOKENS, output past LONG_PROMPT_TOKENS), dollars per million tokens
PRICES = {HAIKU: (0.10, 0.50, 0.50, 2.50), SONNET: (2.00, 10.00, 2.00, 10.00)}
LONG_PROMPT_TOKENS = 100_000
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.10
BATCH_DISCOUNT = 0.5
WEB_SEARCH_USD = 0.01                 # $10 per 1,000 searches
CHARS_PER_TOKEN_WORST = 3.0           # a prompt's token count is over-estimated, never under
WORST_TOKENS_PER_SEARCH = 10_000      # what one search's results can add to the context
WORST_REREAD_FACTOR = 2               # the server loop re-reads the growing context between searches


def prices(model: str, input_tokens: int) -> tuple:
    """``(input, output)`` dollars per million tokens for this prompt length. An unknown model is priced as the dearer one."""
    p_in, p_out, p_in_long, p_out_long = PRICES.get(model, PRICES[SONNET])
    return (p_in_long, p_out_long) if input_tokens > LONG_PROMPT_TOKENS else (p_in, p_out)


def _n(source: Any, key: str) -> int:
    value = source.get(key) if isinstance(source, Mapping) else getattr(source, key, 0)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def web_searches_in(usage: Any) -> int:
    """How many web searches the response says it ran (``usage.server_tool_use.web_search_requests``)."""
    if usage is None:
        return 0
    tool = usage.get("server_tool_use") if isinstance(usage, Mapping) else getattr(usage, "server_tool_use", None)
    return _n(tool, "web_search_requests") if tool is not None else 0


def usage_cost(model: str, usage: Any, *, batch: bool = False) -> Optional[float]:
    """Dollars for one response from its own ``usage``, or None when there is no usage (the caller then charges the worst case)."""
    if usage is None:
        return None
    fresh, written, read = _n(usage, "input_tokens"), _n(usage, "cache_creation_input_tokens"), _n(usage, "cache_read_input_tokens")
    p_in, p_out = prices(model, fresh + written + read)
    tokens = (fresh * p_in + written * p_in * CACHE_WRITE_FACTOR + read * p_in * CACHE_READ_FACTOR
              + _n(usage, "output_tokens") * p_out) / 1e6
    if batch:
        tokens *= BATCH_DISCOUNT
    return round(tokens + web_searches_in(usage) * WEB_SEARCH_USD, 8)


def worst_input_tokens(prompt_chars: int, max_searches: int) -> int:
    return (math.ceil(prompt_chars / CHARS_PER_TOKEN_WORST)
            + max_searches * WORST_TOKENS_PER_SEARCH * WORST_REREAD_FACTOR)


def worst_case_cost(model: str, prompt_chars: int, max_tokens: int, max_searches: int, *, batch: bool = False) -> float:
    """The most one request could cost (see the module docstring for what it assumes)."""
    tokens_in = worst_input_tokens(prompt_chars, max_searches)
    p_in, p_out = prices(model, tokens_in)
    tokens = (tokens_in * p_in + max_tokens * p_out) / 1e6
    if batch:
        tokens *= BATCH_DISCOUNT
    return round(tokens + max_searches * WEB_SEARCH_USD, 6)
