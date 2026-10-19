"""The Zapier translator: what is sent, and how the answer is checked.

THE ROUND TRIP
--------------
  1. The parser could not read all of a person's text and `ZAPIER_TRANSLATE_HOOK_URL` is set. A job is
     created (jobs.py) and `{job_id, text, menu, callback_url}` is POSTed to that Catch Hook with a
     10 second timeout, from a background thread so the request that created the job returns at once.
     The body holds the person's own words and the public menu; no account id, no email, no token.
  2. The owner's Zap runs "AI by Zapier" on it and POSTs `{job_id, spec_json}` to the callback URL with
     the shared secret in `X-Zap-Secret` (docs/ZAPS.md, "5. Strategy translator").
  3. `complete` checks the answer and closes the job. The person then sees it as sentences and rule
     cards, to confirm and edit; nothing is saved without that.

THE ANSWER IS UNTRUSTED TEXT
----------------------------
Whatever comes back is data from outside this program, produced by a model that read a stranger's
sentence. `clean_model_spec` therefore (a) parses it as JSON only (code fences tolerated), (b) keeps
ONLY the fields on the menu and silently drops every other key, at every level, (c) discards free text
altogether (rule labels, names, taglines and colours are never taken from a model), and (d) hands the
remainder to the same `user_spec.validate_spec` every form post goes through. An out-of-bounds or
off-menu value is REFUSED with the menu's own reason, never clamped or repaired: a model's idea of a
better number is not the person's rule.

No Anthropic API is called anywhere in this package.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.english import jobs, render

ENV_HOOK = "ZAPIER_TRANSLATE_HOOK_URL"
ENV_SECRET = "ZAPIER_CALLBACK_SECRET"
ENV_BASE = "PUBLIC_BASE_URL"
DEFAULT_BASE = "https://linehound.app"
CALLBACK_PATH = "/hounds/english/callback"
HOOK_TIMEOUT_S = 10
MAX_SPEC_JSON = 20_000

# Keys a model may set. Everything else is dropped.
TOP_KEYS = ("rules", "lock_minutes", "max_bets_per_day", "stake_units", "rank_by")
RULE_KEYS = ("sports", "markets", "side", "price_min", "price_max", "line_min", "line_max", "min_books", "when")


def hook_url(env: Optional[Mapping] = None) -> Optional[str]:
    url = ((env if env is not None else os.environ).get(ENV_HOOK) or "").strip()
    return url if url.startswith("https://") else None


def callback_secret(env: Optional[Mapping] = None) -> Optional[str]:
    return ((env if env is not None else os.environ).get(ENV_SECRET) or "").strip() or None


def callback_url(env: Optional[Mapping] = None) -> str:
    base = ((env if env is not None else os.environ).get(ENV_BASE) or DEFAULT_BASE).strip().rstrip("/")
    return base + CALLBACK_PATH


def translation_menu() -> dict:
    """The menu as the Zap's prompt needs it: ids, parameter names and their bounds, nothing decorative."""
    full = user_spec.builder_menu()
    conditions = []
    for c in full["conditions"]:
        if not c["available"]:
            continue
        params = {}
        for p in c["params"]:
            if p["kind"] in ("choice", "multi"):
                params[p["name"]] = {"kind": p["kind"], "choices": [x["value"] for x in p["choices"]]}
            elif p["kind"] in ("int", "number"):
                params[p["name"]] = {"kind": p["kind"], "min": p["min"], "max": p["max"]}
            else:
                params[p["name"]] = {"kind": p["kind"]}
        conditions.append({"id": c["id"], "kinds": c["kinds"], "sports": c["sports"], "params": params})
    return {
        "spec_version": 2,
        "rules": {"max": full["limits"]["max_rules"], "fields": list(RULE_KEYS)},
        "sports": [s["value"] for s in full["sports"]],
        "markets": {m["value"]: {"kind": m["kind"], "sports": m["sports"]} for m in full["markets"]},
        "sides": full["side_by_kind"],
        "price": {"min": full["price"]["lowest"], "max": full["price"]["highest"],
                  "never": f"{user_spec.MAX_FAVOURITE_PRICE} or worse"},
        "line": full["line"], "min_books": {"min": full["min_books"]["min"], "max": full["min_books"]["max"]},
        "max_bets_per_day": {"min": full["max_bets_per_day"]["min"], "max": full["max_bets_per_day"]["max"]},
        "stake_units": full["stake_units"]["choices"], "lock_minutes": full["lock_minutes"]["choices"],
        "rank_by": [r["value"] for r in full["rank_by"]],
        "teams": [t["value"] for t in full["teams"]],
        "conditions": conditions,
        "when": 'a group {"op": "all"|"any", "items": [condition or group]}; a condition is {"id": ..., <its params>}',
    }


def build_request(job_id: str, text: str, env: Optional[Mapping] = None) -> dict:
    return {"job_id": job_id, "text": text, "menu": translation_menu(), "callback_url": callback_url(env)}


def post_hook(url: str, payload: Mapping, *, timeout: float = HOOK_TIMEOUT_S,
              opener: Callable = urllib.request.urlopen) -> int:
    """POST the request to the Catch Hook. Returns the HTTP status; raises on a transport error."""
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "linehound-translate/1"})
    with opener(req, timeout=timeout) as resp:
        return int(getattr(resp, "status", 200))


def start(job_id: str, text: str, *, env: Optional[Mapping] = None, poster: Optional[Callable] = None,
          background: bool = True, db=None) -> Optional[threading.Thread]:
    """Send the request for a job. A failure marks the job `failed` (the person is told and can finish
    by hand); it never raises into the request that created the job. `poster` is looked up at call time
    so a test can replace `post_hook` on the module."""
    poster = poster or post_hook
    url = hook_url(env)
    if url is None:
        jobs.finish(job_id, jobs.STATUS_FAILED, error="the translator is not configured", db=db)
        return None
    payload = build_request(job_id, text, env)

    def run():
        try:
            status = poster(url, payload)
            if not 200 <= int(status) < 300:
                jobs.finish(job_id, jobs.STATUS_FAILED, error=f"the translator answered HTTP {status}", db=db)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            jobs.finish(job_id, jobs.STATUS_FAILED, error=f"the translator could not be reached ({type(exc).__name__})", db=db)
        except Exception as exc:  # noqa: BLE001
            jobs.finish(job_id, jobs.STATUS_FAILED, error=f"the translator failed ({type(exc).__name__})", db=db)

    if not background:
        run()
        return None
    thread = threading.Thread(target=run, daemon=True, name=f"translate-{job_id}")
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# the answer
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def _load(spec_json: Any) -> Any:
    if isinstance(spec_json, (dict, list)):
        return spec_json
    if not isinstance(spec_json, str) or not spec_json.strip():
        raise ValueError("spec_json is empty")
    if len(spec_json) > MAX_SPEC_JSON:
        raise ValueError("spec_json is too large")
    text = spec_json.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    return json.loads(text)


def _clean_tree(raw: Any, dropped: list, depth: int = 0) -> Any:
    """Keep only group and condition keys that exist on the menu. A condition with an id the menu does
    not know is kept as-is so that validation refuses it by name; its other keys are not interpreted."""
    if not isinstance(raw, Mapping) or depth > R.MAX_DEPTH + 1:
        return raw if not isinstance(raw, (dict, list)) else None
    if "id" in raw:
        cond = R.BY_ID.get(raw.get("id")) if isinstance(raw.get("id"), str) else None
        if cond is None:
            return {"id": raw.get("id") if isinstance(raw.get("id"), str) else None}
        allowed = {"id"} | {p.name for p in cond.params}
        dropped.extend(sorted(str(k)[:20] for k in raw if k not in allowed))
        return {k: v for k, v in raw.items() if k in allowed}
    allowed = {"op", "items"}
    dropped.extend(sorted(str(k)[:20] for k in raw if k not in allowed))
    items = raw.get("items")
    return {"op": raw.get("op", "all"),
            "items": [_clean_tree(i, dropped, depth + 1) for i in items] if isinstance(items, list) else items}


def clean_model_spec(obj: Any) -> tuple:
    """(draft dict, [dropped key names]). Never raises on shape; a non-object becomes an empty draft."""
    dropped: list = []
    if not isinstance(obj, Mapping):
        return {}, ["<not an object>"]
    dropped.extend(sorted(str(k)[:20] for k in obj if k not in TOP_KEYS))
    draft: dict = {"version": user_spec.SPEC_VERSION_V2}
    for key in TOP_KEYS:
        if key in obj and key != "rules":
            draft[key] = obj[key]
    rules = obj.get("rules")
    if isinstance(rules, list):
        clean_rules = []
        for r in rules[:R.MAX_RULES + 1]:
            if not isinstance(r, Mapping):
                clean_rules.append(r)
                continue
            dropped.extend(sorted(str(k)[:20] for k in r if k not in RULE_KEYS))
            rule = {k: v for k, v in r.items() if k in RULE_KEYS}
            if "when" in rule:
                rule["when"] = _clean_tree(rule["when"], dropped)
            clean_rules.append(rule)
        draft["rules"] = clean_rules
    else:
        draft["rules"] = rules
    return draft, sorted(set(dropped))


def validate_answer(spec_json: Any) -> dict:
    """{'ok': bool, 'spec', 'sentences', 'reasons': {field: why}, 'dropped': [...]} for one answer."""
    try:
        obj = _load(spec_json)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "spec": None, "sentences": [], "dropped": [],
                "reasons": {"spec_json": f"is not usable JSON ({str(exc)[:80]})"}}
    draft, dropped = clean_model_spec(obj)
    try:
        spec = user_spec.validate_spec({**draft, "name": "Draft Dog"})
    except user_spec.SpecError as exc:
        return {"ok": False, "spec": None, "sentences": [], "dropped": dropped,
                "reasons": {k: v for k, v in exc.errors.items() if k != "name"}}
    spec["name"] = ""
    return {"ok": True, "spec": spec, "sentences": render.rule_sentences(spec) + render.global_sentences(spec),
            "reasons": {}, "dropped": dropped}


def complete(job_id: str, spec_json: Any, *, now: Optional[datetime] = None, db=None) -> tuple:
    """Apply a callback. Returns (http_status, body). 404 unknown job, 409 already finished or expired."""
    job = jobs.get_job(job_id, db=db)
    if job is None:
        return 404, {"error": "not_found"}
    if job["status"] != jobs.STATUS_TRANSLATING:
        return 409, {"error": "already_finished", "status": job["status"]}
    if jobs.is_expired(job, now):
        jobs.finish(job_id, jobs.STATUS_FAILED, error="the translation took too long and was dropped", db=db)
        return 409, {"error": "expired"}
    outcome = validate_answer(spec_json)
    if outcome["ok"]:
        jobs.finish(job_id, jobs.STATUS_DONE, db=db, result={
            "spec": outcome["spec"], "sentences": outcome["sentences"], "dropped": outcome["dropped"]})
        return 200, {"ok": True, "status": jobs.STATUS_DONE}
    jobs.finish(job_id, jobs.STATUS_REFUSED, db=db, result={
        "reasons": outcome["reasons"], "dropped": outcome["dropped"]}, error="the answer was refused by the menu")
    return 200, {"ok": True, "status": jobs.STATUS_REFUSED, "reasons": outcome["reasons"]}


def poll_payload(job: Mapping) -> dict:
    """What the owner of a job sees."""
    result = job.get("result") or {}
    partial = result.get("partial") or {}
    return {"job_id": job["id"], "status": job["status"], "error": job.get("error"),
            "spec": result.get("spec"), "sentences": result.get("sentences") or [],
            "reasons": result.get("reasons") or {}, "dropped": result.get("dropped") or [],
            "understood": partial.get("understood") or [], "not_understood": partial.get("not_understood") or [],
            "paper_only": True, "not_advice": user_spec.NOT_ADVICE}
