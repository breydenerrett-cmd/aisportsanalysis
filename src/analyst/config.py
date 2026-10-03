"""config/analyst.json, read and validated once.

WHY A FILE AND NOT CONSTANTS
----------------------------
The model id, the price per million tokens and the spend cap are the three
numbers that change without the code changing: a new model ships, a price
moves, the owner decides a day should cost less. They live in config so that
change is a one-line edit with a diff, not a code release. Defaults here are
the same values as the shipped file, so a missing file is never a missing cap:
the hard spend limit exists even if nobody wrote the config.

The API key is NOT config. It is read from the environment by name
(ANTHROPIC_API_KEY) at the moment of use and is never stored, logged or put
in a packet, a ledger row or an error message.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Optional

from src import paths

ENV_KEY = "ANTHROPIC_API_KEY"
CONFIG_PATH = os.path.join("config", "analyst.json")

DEFAULTS: dict = {
    "model": "claude-sonnet-5-5",
    "api_url": "https://api.anthropic.com/v1/messages",
    "anthropic_version": "2023-06-01",
    "effort": "medium",
    "max_output_tokens": 16000,
    "request_timeout_s": 600,
    "max_attempts": 2,
    # Estimates from the claude-api reference for claude-sonnet-5-5 ($2 in,
    # $10 out, $0.20 cache read per million tokens). The cost recorded per game
    # is computed from the usage the API returns times these prices, so a
    # price change is a config edit and the log says which price it used.
    "price_per_million_usd": {"input": 2.0, "output": 10.0, "cache_read": 0.2},
    "spend_cap": {"max_usd_per_run": 6.0, "max_tokens_per_run": 600000},
    "max_props_per_game": 16,
    "min_books_for_prop": 2,
    "stale_quote_minutes": 180,
    "lock_lead_minutes": 0,
    "model_critic": {"enabled": False, "model": "claude-sonnet-5-5",
                     "max_output_tokens": 4000},
    "min_graded_for_rates": 30,
}


class ConfigError(ValueError):
    pass


def _merge(base: Mapping, over: Mapping) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def validate(cfg: Mapping) -> dict:
    """The config with every number checked. A bad value is an error, never
    silently replaced by a default (a typo in a cap must not remove the cap)."""
    cfg = dict(cfg)
    if not isinstance(cfg.get("model"), str) or not cfg["model"]:
        raise ConfigError("model must be a non-empty string")
    # The key travels in a header to this URL, so it must be an https URL: a
    # typo here must not send the key over plain http or to a stranger.
    if not isinstance(cfg.get("api_url"), str) or not cfg["api_url"].startswith("https://"):
        raise ConfigError("api_url must be an https:// URL")
    price = cfg.get("price_per_million_usd") or {}
    for key in ("input", "output"):
        if not isinstance(price.get(key), (int, float)) or price[key] < 0:
            raise ConfigError(f"price_per_million_usd.{key} must be a number >= 0")
    cap = cfg.get("spend_cap") or {}
    for key in ("max_usd_per_run", "max_tokens_per_run"):
        if not isinstance(cap.get(key), (int, float)) or cap[key] <= 0:
            raise ConfigError(f"spend_cap.{key} must be a number > 0")
    for key in ("max_output_tokens", "max_attempts", "max_props_per_game",
                "min_books_for_prop", "min_graded_for_rates"):
        if not isinstance(cfg.get(key), int) or cfg[key] < 0:
            raise ConfigError(f"{key} must be an integer >= 0")
    if cfg["max_attempts"] < 1:
        raise ConfigError("max_attempts must be at least 1")
    return cfg


def load(path: Optional[str] = None) -> dict:
    """The validated config: defaults, overlaid by the file when it exists."""
    target = path or str(paths.repo_root() / CONFIG_PATH)
    cfg = dict(DEFAULTS)
    if os.path.exists(target):
        try:
            with open(target, encoding="utf-8") as fh:
                parsed: Any = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"{target}: {exc}") from exc
        if not isinstance(parsed, Mapping):
            raise ConfigError(f"{target}: expected a JSON object")
        cfg = _merge(cfg, parsed)
    return validate(cfg)


def api_key(env: Optional[Mapping] = None) -> Optional[str]:
    """The key from the environment, or None. Never logged."""
    value = ((env if env is not None else os.environ).get(ENV_KEY) or "").strip()
    return value or None
