"""The pre-build check ("will this hound be dumb?"): what the hound will do, and where it will sit idle or misfire.

``analyse(result, answers, windows)`` reads a composed hound (``compose.compose``'s result: the spec, its warnings) and, when there is
one, the 7-day replay + board counts the impact meter already made (``drill.impact_windows``: bets per rule, games a day, books per
game, prices). It returns

  will_do    two or three plain sentences: what it bets, what the last 7 days of boards would have made of it, and what to look at
  watch_out  findings, each ``{code, text, fix}``: one sentence and ONE fix action the page can run (or None when nothing can fix it)

The checks (all deterministic, no model calls, nothing written):

  personality_data   a style that reads data the sport lacks (Stats Nerd on NHL): says so in one line, offers a fitting style
  market_not_posted  a market the sport does not carry, from the composer's own notes or from 7 days of boards with none posted
  no_games           a sport with nothing on the board in the last 7 days (out of season)
  rule_never_fired   a rule that made no bet in the last 7 days although the boards had its games
  min_books_high     min_books above what the sport's games typically had
  price_band_empty   a price band that excludes every quote the sport offered
  tagline_blank      a catchphrase (or name) blanked by a reserved word: names the word
  cap_too_high       a bets-a-day cap above the most games the boards ever offered in a day

Nothing here blocks anything: Keep stays enabled. Fix actions the page understands: ``set_personality``, ``set_sports``, ``edit_field``,
``edit_rules``, ``go_back``. Copy rules: no beta, new, edge, lock (noun), CLV, "nothing cleared the bar"; no profit claim.
No FastAPI here: the route is api/hounds_quiz.py.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.quiz import boardstats
from src.hounds.quiz import choose as quiz_choose
from src.hounds.quiz import compose as quiz_compose_mod
from src.hounds.quiz import impact as quiz_impact
from src.hounds.quiz import library as lib_mod

MAX_FINDINGS = 6
_GAME_MARKETS = ("moneyline", "spread", "total")
_WORD = {"moneyline": "moneylines", "spread": "spreads", "total": "totals"}


def _price(value: Any) -> str:
    return "any price" if value is None else (f"+{int(value)}" if value > 0 else f"{int(value)}")


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def reserved_terms(text: Any) -> list:
    """The reserved words and protected book or league names in ``text``, as the validator reads them (src/hounds/user_spec.py).
    Language that is merely not allowed is NOT returned: it is not repeated back."""
    if not isinstance(text, str):
        return []
    found = [w for w in user_spec._words(text) if w in user_spec._RESERVED_WORDS]
    squashed = user_spec._fold(text)
    found += [b for b in user_spec._RESERVED_SUBSTRINGS if b in squashed]
    seen: list = []
    for t in found:
        if t not in seen:
            seen.append(t)
    return seen


def _rule_name(rule: Mapping) -> str:
    sports = lib_mod.sports_text(list(rule.get("sports") or []))
    markets = " and ".join(_WORD.get(m, "props") for m in dict.fromkeys(rule.get("markets") or []))
    return f"{rule.get('label') or 'A rule'} ({sports} {markets})"


def _fix_rules(label: str = "Open the rules") -> dict:
    return {"action": "edit_rules", "label": label}


def _fix_back(label: str = "Change the sports") -> dict:
    return {"action": "go_back", "label": label}


def _sides_for(rule_side: Any, market: str) -> tuple:
    pair = ("over", "under") if market == "total" else ("home", "away")
    side = str(rule_side or "either")
    return (side,) if side in pair else pair


def _style_findings(result: Mapping, answers: Mapping, lib: Mapping, out: list) -> None:
    spec = result.get("spec") or {}
    seen: set = set()
    for w in result.get("warnings") or []:
        if w.get("code") not in ("base_generic", "move_generic") or w["message"] in seen:
            continue
        seen.add(w["message"])
        fix = None
        current = answers.get("personality") if isinstance(answers, Mapping) else None
        sports = list(spec.get("sports") or [])
        if current and sports:
            best = quiz_choose.best_personality(lib, sports)
            if best and best["id"] != current and quiz_choose._style_fit(lib, best["id"], sports) < quiz_choose._style_fit(lib, current, sports):
                fix = {"action": "set_personality", "personality": best["id"], "label": f"Switch to {best['name']}"}
        out.append({"code": "personality_data", "text": w["message"], "fix": fix or _fix_rules("Keep it, or open the rules")})


def _market_findings(result: Mapping, out: list) -> None:
    covered = sorted({s for r in (result.get("spec") or {}).get("rules") or [] for s in r.get("sports") or []})
    for w in result.get("warnings") or []:
        if w.get("code") == "market_unavailable":
            out.append({"code": "market_not_posted", "text": w["message"], "fix": _fix_back()})
        elif w.get("code") == "base_narrowed":
            fix = {"action": "set_sports", "sports": covered, "label": f"Only bet {lib_mod.sports_text(covered)}"} if covered else _fix_back()
            out.append({"code": "market_not_posted", "text": w["message"], "fix": fix})


def _tagline_findings(result: Mapping, answers: Mapping, out: list) -> None:
    for w in result.get("warnings") or []:
        code = w.get("code")
        if code not in ("tagline_rejected", "name_rejected"):
            continue
        field = "tagline" if code == "tagline_rejected" else "name"
        noun = "catchphrase" if field == "tagline" else "name"
        typed = answers.get(field) if isinstance(answers, Mapping) else None
        terms = reserved_terms(typed)
        if field == "tagline":
            terms = [t for t in terms if t not in user_spec._LEAGUE_WORDS]      # a league name is fine in a catchphrase (user_spec)
        kept = ((result.get("spec") or {}).get("tagline") or "") if field == "tagline" else ""
        if terms:
            quoted = " and ".join(f'"{t}"' for t in terms[:2])
            after = (f"its style" + chr(39) + f"s line \"{kept}\" is used instead.") if kept else "it was left blank."
            text = (f"The {noun} uses {quoted}, which is reserved for the sites and leagues themselves, so {after}"
                    if field == "tagline" else f"The name uses {quoted}, which is reserved for the sites and leagues themselves, so a suggested name was used.")
        else:
            text = w["message"]
        out.append({"code": "tagline_blank", "text": text, "fix": {"action": "edit_field", "field": field, "label": f"Edit the {noun}"}})


def _board_findings(spec: Mapping, windows: Mapping, out: list) -> None:
    board = windows.get("board") or {}
    rule_bets = windows.get("rule_bets") or {}
    flagged_rules: set = set()
    quiet_sports: set = set()
    for i, rule in enumerate(spec.get("rules") or []):
        if not any(m in _GAME_MARKETS for m in rule.get("markets") or []):
            continue                                              # props are not on the replayed boards: no evidence either way
        for sport in rule.get("sports") or []:
            for market in [m for m in rule.get("markets") or [] if m in _GAME_MARKETS]:
                stat = board.get(f"{sport}|{market}")
                if not stat or not stat.get("games"):
                    other = any(k.startswith(f"{sport}|") for k in board)
                    if other:
                        out.append({"code": "market_not_posted", "fix": _fix_back(), "key": (sport, market),
                                    "text": f"{lib_mod.sports_text([sport])} {_WORD[market]} were not on the board at all in the last 7 days, "
                                            f"so {rule.get('label') or 'that rule'} had nothing to look at."})
                    elif sport not in quiet_sports:
                        quiet_sports.add(sport)
                        out.append({"code": "no_games", "fix": _fix_back(), "key": (sport,),
                                    "text": f"No {lib_mod.sports_text([sport])} games were on the board in the last 7 days, so it may be out of "
                                            "season. This hound has nothing to look at until they are back."})
                    flagged_rules.add(i)
                    continue
                need = rule.get("min_books")
                if isinstance(need, int) and need > stat["books_median"]:
                    typical = stat["books_median"]
                    out.append({"code": "min_books_high", "fix": _fix_rules("Lower the books it needs"), "key": (i, sport, market),
                                "text": (f"{_rule_name(rule)} wants {need} books quoting a price, but a typical {lib_mod.sports_text([sport])} "
                                         f"game had {typical}, so it skips most games." if stat["books_max"] >= need else
                                         f"{_rule_name(rule)} wants {need} books quoting a price, and no {lib_mod.sports_text([sport])} game "
                                         f"had more than {stat['books_max']} in the last 7 days, so it can never bet.")})
                    flagged_rules.add(i)
                sides = _sides_for(rule.get("side"), market)
                quotes = sum(sum(stat["prices"].get(s, {}).values()) for s in sides)
                inside = sum(boardstats.in_band(stat["prices"].get(s, {}), rule.get("price_min"), rule.get("price_max")) for s in sides)
                if quotes and not inside:
                    merged: dict = {}
                    for s in sides:
                        for p, n in stat["prices"].get(s, {}).items():
                            merged[p] = merged.get(p, 0) + n
                    mid = boardstats.median_price(merged)
                    out.append({"code": "price_band_empty", "fix": _fix_rules("Widen the prices"), "key": (i, sport, market),
                                "text": (f"{_rule_name(rule)} takes prices from {_price(rule.get('price_min'))} to {_price(rule.get('price_max'))}, "
                                         f"but {lib_mod.sports_text([sport])} {_WORD[market]} were priced around {_price(mid)}, so it can never bet.")})
                    flagged_rules.add(i)
        if (i not in flagged_rules and rule_bets is not None and windows.get("rule_bets") is not None and not rule_bets.get(i)):
            out.append({"code": "rule_never_fired", "fix": _fix_rules(), "key": (i,),
                        "text": f"{_rule_name(rule)} would not have made a single bet in the last 7 days, although its games were on the board."})
    # the daily cap against the most games any day offered
    cap = spec.get("max_bets_per_day")
    rules = spec.get("rules") or []
    if isinstance(cap, int) and rules and all(any(m in _GAME_MARKETS for m in r.get("markets") or []) for r in rules):
        per_sport: dict = {}
        for rule in rules:
            for sport in rule.get("sports") or []:
                for market in rule.get("markets") or []:
                    stat = board.get(f"{sport}|{market}")
                    if stat:
                        per_sport[sport] = max(per_sport.get(sport, 0), stat["max_per_day"])
        busiest = sum(per_sport.values())
        if busiest and cap > busiest:
            out.append({"code": "cap_too_high", "fix": _fix_rules("Lower the daily cap"), "key": ("cap",),
                        "text": f"It can make up to {_plural(cap, 'bet')} a day, but the busiest day in the last 7 days offered only "
                                f"{_plural(busiest, 'game')}, so the cap never comes into play."})


def will_do(result: Mapping, windows: Optional[Mapping], findings: list) -> list:
    spec = result.get("spec") or {}
    rules = spec.get("rules") or []
    sports = lib_mod.sports_text(list(spec.get("sports") or []))
    markets = ", ".join(_WORD.get(m, "player props") for m in dict.fromkeys(m for r in rules for m in r.get("markets") or []))
    cap, stake = spec.get("max_bets_per_day"), spec.get("stake_units")
    first = f"{spec.get('name') or 'Your hound'} looks at {sports} {markets}"
    if isinstance(cap, int) and isinstance(stake, (int, float)):
        first += f" and makes at most {_plural(cap, 'bet')} a day, {stake:g} {'unit' if stake == 1 else 'units'} each"
    sentences = [first + "."]
    if windows and windows.get(7) is not None:
        w = windows[7]
        if w["bets"] == 0:
            sentences.append("Over the last 7 days of boards it would not have bet.")
        else:
            sentences.append("Over the last 7 days of boards it would have made " + quiz_impact.window_line("x", w).split(": ", 1)[1]
                             + ", all on paper and in hindsight.")
    else:
        sentences.append("We could not replay the last 7 days just now, so these notes come from its rules alone.")
    if findings:
        sentences.append(f"{_plural(len(findings), 'thing')} to watch {'is' if len(findings) == 1 else 'are'} listed below. Nothing blocks you from keeping it.")
    else:
        sentences.append("We checked its sports, markets, prices, books and daily cap against the last 7 days of boards and found nothing off.")
    return sentences


def analyse(result: Mapping, answers: Any = None, windows: Optional[Mapping] = None, lib: Optional[Mapping] = None,
            replayed_spec: Optional[Mapping] = None) -> dict:
    """The check for one composed hound. ``windows`` is ``drill.impact_windows``' entry for its spec (or None when the replay was not
    available: the notes then come from the composer's own warnings alone). ``replayed_spec`` is the spec the replay actually ran when
    it was narrowed to the busiest sports (``impact.capped``): rule numbers in ``windows`` count that spec's rules."""
    lib = lib or lib_mod.load()
    ans = answers if isinstance(answers, Mapping) else {}
    spec = result.get("spec") or {}
    found: list = []
    _style_findings(result, ans, lib, found)
    _market_findings(result, found)
    _tagline_findings(result, ans, found)
    if windows:
        _board_findings(replayed_spec or spec, windows, found)
    deduped: list = []
    seen: set = set()
    for f in found:
        ident = (f["code"], f.get("key"), f["text"])
        if ident in seen:
            continue
        seen.add(ident)
        deduped.append({k: v for k, v in f.items() if k != "key"})
    watch = deduped[:MAX_FINDINGS]
    return {"will_do": will_do(result, windows, watch), "watch_out": watch, "replay": bool(windows),
            "more": max(0, len(deduped) - MAX_FINDINGS)}


def check(answers: Any, english_draft: Any = None, english_text: Any = None, *, now=None, lib: Optional[Mapping] = None, **inject) -> dict:
    """Compose the answers, replay the spec over the last 7 days (one pass, shared with the impact meter's cache) and analyse it.
    A busy or unreadable replay is not an error: the check then speaks from the composer's own notes and says the replay was missing."""
    from src.hounds.interact import drill
    result = quiz_compose_mod.compose(answers, taken_names=(), english_draft=english_draft, english_text=english_text)
    spec = result.get("spec") or {}
    windows, replayed = None, None
    if spec and not user_spec.is_gematria(spec):
        replayed, _note = quiz_impact.capped(spec)
        try:
            windows = drill.impact_windows([replayed], now=now, **inject)[0]
        except drill.DrillError:
            windows = None
        except Exception:  # noqa: BLE001 -- boards that cannot be read: the check goes on without them
            windows = None
    out = analyse(result, answers, windows, lib, replayed_spec=replayed)
    out["paper_only"] = True
    return out
