"""A spec back into plain sentences, and the difference between two specs in plain sentences.

`rule_text(spec)` is what every surface shows as "the rules" of a version-2 hound. Like the version-1
text it is a pure function of the validated spec, so the published rule is exactly what the engine
runs: there is no second place for the two to drift apart (a test walks every condition on the menu
through it).
"""

from __future__ import annotations

from typing import Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec

_STAKE = lambda s: f"{s:g} paper unit{'' if s == 1 else 's'}"          # noqa: E731
_RANK_PHRASE = {
    "earliest_lock": "the earliest games",
    "longest_price": "the longest prices first",
    "shortest_price": "the shortest prices first",
    "most_books": "the picks the most books are quoting first",
    "biggest_steam": "the picks the market has moved toward the most first",
}


def fmt_price(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


def _join(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _markets_phrase(rule: Mapping) -> str:
    sports = rule["sports"]
    names = []
    for m in rule["markets"]:
        if m == "moneyline":
            names.append("moneylines")
        elif m == "spread":
            names.append("run lines" if sports == ["MLB"] else "point spreads" if sports == ["NFL"]
                         else "run lines and point spreads" if set(sports) <= set(user_spec.LEGACY_SPORTS)
                         else "spreads")
        elif m == "total":
            names.append("game totals")
        else:
            names.append(R.MARKET_LABELS[m].lower() + " props" if m != "pitcher_strikeouts"
                         else "pitcher strikeout props")
    return _join(names)


def _side_phrase(rule: Mapping) -> str:
    kind = R.market_kind(rule["markets"][0])
    side = rule["side"]
    if kind == "ml_spread":
        return {"either": "either side", "home": "the home side", "away": "the away side"}[side]
    return {"either": "the over or the under", "over": "the over", "under": "the under"}[side]


def _line_phrase(rule: Mapping) -> str:
    lo, hi = rule.get("line_min"), rule.get("line_max")
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is not None:
        if lo == hi:
            return f", on a line of {lo:g}"
        return f", on a line from {lo:g} to {hi:g}"
    if lo is not None:
        return f", on a line of {lo:g} or higher"
    return f", on a line of {hi:g} or lower"


def _price_phrase(rule: Mapping) -> str:
    lo, hi = rule["price_min"], rule["price_max"]
    if lo == user_spec.SHORTEST_ALLOWED_PRICE and hi == user_spec.LONGEST_ALLOWED_PRICE:
        return f", at any average price (never {user_spec.MAX_FAVOURITE_PRICE} or worse)"
    if lo == user_spec.SHORTEST_ALLOWED_PRICE:
        return f", at an average price of {fmt_price(hi)} or shorter (never {user_spec.MAX_FAVOURITE_PRICE} or worse)"
    if hi == user_spec.LONGEST_ALLOWED_PRICE:
        return f", at an average price of {fmt_price(lo)} or longer"
    return (f", at an average price between {fmt_price(lo)} and {fmt_price(hi)} "
            f"(never {user_spec.MAX_FAVOURITE_PRICE} or worse)")


def rule_sentence(rule: Mapping) -> str:
    """One rule as a sentence (no disclaimer)."""
    kind = R.market_kind(rule["markets"][0])
    head = f"{user_spec.sports_phrase(rule['sports'])} {_markets_phrase(rule)}: it backs {_side_phrase(rule)}"
    when = R.tree_text(rule.get("when"), kind)
    out = head
    if when:
        out += f" when {when}"
    out += _line_phrase(rule) + _price_phrase(rule)
    books = rule["min_books"]
    out += f", with at least {books} {'book' if books == 1 else 'books'} quoting it."
    label = (rule.get("label") or "").strip()
    return f"{label}: {out}" if label else out


def global_sentences(spec: Mapping) -> list:
    bets = spec["max_bets_per_day"]
    # A draft (an upgraded classic spec, a parser draft) has no derived `sports`; read them off the rules.
    sports = spec.get("sports") or [s for s in user_spec.SPORTS if any(s in r["sports"] for r in spec["rules"])]
    words = {user_spec.sports_catalog.start_word(c) for c in sports}
    start = ("first pitch" if sports == ["MLB"] else "kickoff" if sports == ["NFL"]
             else "first pitch or kickoff" if set(sports) <= set(user_spec.LEGACY_SPORTS)
             else words.pop() if len(words) == 1 else "the start")
    return [
        f"{spec['lock_minutes']} minutes before {start} it checks each rule against the board as it stood then "
        f"(nothing newer).",
        f"At most {bets} {'bet' if bets == 1 else 'bets'} a day; if more qualify it takes "
        f"{_RANK_PHRASE[spec['rank_by']]}.",
        f"Each bet is {_STAKE(spec['stake_units'])}, graded at the average price.",
    ]


def rule_sentences(spec: Mapping) -> list:
    rules = spec["rules"]
    if len(rules) == 1:
        return [rule_sentence(rules[0])]
    return [f"Rule {i + 1}. {rule_sentence(r)}" for i, r in enumerate(rules)]


def rule_text(spec: Mapping) -> str:
    """The whole published rule of a version-2 hound, as one paragraph, ending with the paper notice."""
    return " ".join(rule_sentences(spec) + global_sentences(spec) + [user_spec.NOT_ADVICE])


# ---------------------------------------------------------------------------
# the difference between two specs
# ---------------------------------------------------------------------------

def _as_v2(spec: Mapping) -> dict:
    return dict(spec) if user_spec.is_v2(spec) else user_spec.upgrade_v1(spec)


def diff_specs(old: Mapping, new: Mapping) -> list:
    """[{'what', 'before', 'after'}] in plain words, empty when nothing a reader would care about
    changed. A version-1 `old` is compared as its version-2 equivalent, so editing a classic dog
    shows exactly what the new version does differently."""
    a, b = _as_v2(old), _as_v2(new)
    out: list = []

    def change(what, before, after):
        if before != after:
            out.append({"what": what, "before": before, "after": after})

    change("Name", a.get("name"), b.get("name"))
    change("Catchphrase", a.get("tagline") or "", b.get("tagline") or "")
    change("Colour", a.get("color", "ember"), b.get("color", "ember"))
    change("Badge", a.get("badge", "bone"), b.get("badge", "bone"))
    change("Lock time", f"{a['lock_minutes']} minutes before the start", f"{b['lock_minutes']} minutes before the start")
    change("Most bets a day", str(a["max_bets_per_day"]), str(b["max_bets_per_day"]))
    change("Stake", _STAKE(a.get("stake_units", 1.0)), _STAKE(b.get("stake_units", 1.0)))
    change("If more qualify", _RANK_PHRASE[a.get("rank_by", "earliest_lock")], _RANK_PHRASE[b.get("rank_by", "earliest_lock")])
    ra, rb = a.get("rules") or [], b.get("rules") or []
    for i in range(max(len(ra), len(rb))):
        before = _safe_sentence(ra[i]) if i < len(ra) else None
        after = _safe_sentence(rb[i]) if i < len(rb) else None
        label = f"Rule {i + 1}"
        if before is None:
            out.append({"what": f"{label} added", "before": None, "after": after})
        elif after is None:
            out.append({"what": f"{label} removed", "before": before, "after": None})
        else:
            change(f"{label} changed", before, after)
    return out


def _safe_sentence(rule: Mapping) -> Optional[str]:
    try:
        return rule_sentence(rule)
    except (KeyError, TypeError, IndexError):
        return None
