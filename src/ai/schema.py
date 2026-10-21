"""A small JSON-schema checker, and the one function that turns a model's text into a JSON object.

WHY NOT ``jsonschema``. The Linux CI image has only the standard library plus what the tests install, and
the keywords a hound's answer needs are few. A checker this small can be read in one sitting and tested to
the line, which matters because it is the last gate before a model's words become a paper bet.

KEYWORDS SUPPORTED: ``type`` (a name or a list; ``integer`` means an int and never a bool or a float),
``enum``, ``properties``, ``required``, ``additionalProperties`` (false means: no extra keys),
``minimum``, ``maximum``, ``minLength``, ``maxLength``, ``maxWords`` (not standard JSON schema: the word
count of a string, for "at most 25 words"), ``items``, ``minItems``, ``maxItems``. Any other keyword is
ignored, so a schema must stay inside this list to mean what it says.

STRICT MEANS STRICT. ``validate`` returns every problem it finds; an empty list is the only "valid". It
never repairs a value (no truncating a long reason, no clamping a confidence): a repaired answer is an
answer the model did not give.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _type_ok(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    return False


def validate(value: Any, schema: dict, path: str = "$") -> List[str]:
    """Every way ``value`` fails ``schema`` (empty list = valid)."""
    problems: List[str] = []
    types = schema.get("type")
    if types is not None:
        names = [types] if isinstance(types, str) else list(types)
        if not any(_type_ok(value, n) for n in names):
            return [f"{path}: expected {'/'.join(names)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, bool):
        return problems
    if isinstance(value, (int, float)):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: {value} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: {value} is above {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value.strip()) < schema["minLength"]:
            problems.append(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(f"{path}: longer than {schema['maxLength']} characters")
        if "maxWords" in schema and len(value.split()) > schema["maxWords"]:
            problems.append(f"{path}: {len(value.split())} words, at most {schema['maxWords']}")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or ():
            if key not in value:
                problems.append(f"{path}: missing required key {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    problems.append(f"{path}: unexpected key {key!r}")
        for key, sub in props.items():
            if key in value:
                problems.extend(validate(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            problems.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                problems.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return problems


def extract_json_object(text: Any) -> Tuple[Optional[dict], Optional[str]]:
    """``(object, None)`` or ``(None, why)``. Accepts the model's whole text as one JSON object, after
    dropping a ``<think>`` block and one markdown fence; failing that, the outermost ``{...}`` slice.
    The value inside is never altered, and anything but a JSON object (a list, a bare string) is refused."""
    if not isinstance(text, str) or not text.strip():
        return None, "empty output"
    body = _THINK_RE.sub("", text).strip()
    fence = _FENCE_RE.match(body)
    if fence:
        body = fence.group(1).strip()
    candidates = [body]
    first, last = body.find("{"), body.rfind("}")
    if 0 <= first < last and (first, last) != (0, len(body) - 1):
        candidates.append(body[first:last + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj, None
        return None, f"output is a JSON {type(obj).__name__}, not an object"
    return None, "output is not valid JSON"
