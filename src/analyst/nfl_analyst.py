"""The NFL analyst: the MLB analyst's machinery with a football prompt and a number-line check.

WHAT IS SHARED AND WHAT IS NOT
------------------------------
Everything that is not about the sport is the MLB analyst's code, called, not copied: the request
body, the JSON schema, the shape check (`validate_output`), the spend meter, the critic and the
ledger. This module supplies the three things that are about football:

  * `NFL_SYSTEM_PROMPT` (versioned): every rule of the MLB v5 prompt, with the baseball words
    changed, plus rules F1 to F8 for the spread, the total, the key numbers, quarterbacks and
    injuries, rest and travel, venue and weather, and the small samples of a 17-game season;
  * the critic's name vocabulary: an NFL claim may say "Sunday Night Football" or "Red Zone"
    without being struck as an unverified person, and no baseball club is vouched for;
  * `verify`: `critic.verify` with that vocabulary and one more rule, `line_problems` below.

THE SCHEMA IS THE MLB SCHEMA, BECAUSE THE PACKET IS THE MLB KIND
----------------------------------------------------------------
`analyst.schema_for(packet)` picks the schema by the packet, and an NFL packet carries a `game`
block and no `bout`, so it gets the schema with `case_against` and `derived`. The critic's MLB-only
behaviour follows the same test: a TAKE needs a verified case against, a calculated number must be
declared and recomputed, and the words "packet" and "repo" are struck from anything a reader sees.
That is the intent: a brief that is read by a customer has the same rules whatever the sport.

THE ONE NEW RULE: A NUMBER NAMED NEXT TO A TEAM MUST BE A QUOTED NUMBER
-----------------------------------------------------------------------
The generic number check passes any number that appears ANYWHERE in the packet. "LAC +4" passes it
when the spread is LAC +3.5, because a 4 sits in a games count two sections away. For a spread that
is the whole claim, so `line_problems` reads the prose itself: a team (its code, its nickname or its
city and nickname) written next to a signed number must name a number that team is quoted at, and
"Over" or "Under" next to a two-digit number must name the quoted total. The quoted numbers are the
options of the spread and total markets, plus the number each was first captured at when the packet
says so (a sentence about line movement is allowed to name where it started). A game with no spread
in the packet has no quoted number, so any such claim is struck.

It is a structural check and leans strict: "the Chiefs -1.5 on turnover margin" reads as a spread
claim and strikes the call. A false strike costs a PASS; a spread number nobody quoted costs a
published claim with no source. The prompt (rule F1) tells the writer how to avoid it.

PROMPT_VERSION RULE
-------------------
Any change to `NFL_SYSTEM_PROMPT` or to the vocabulary below changes `NFL_PROMPT_VERSION`; every
published row records the version and the hash of the prompt and schema it was made with.
"""

from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence

from src.analyst import analyst as analyst_mod
from src.analyst import critic, ledger
from src.sports import nfl_teams

NFL_PROMPT_VERSION = "analyst_prompt_nfl_v1"

NFL_SYSTEM_PROMPT = """\
You are a football betting analyst. You write the analysis of one NFL game and make a call on every market the packet prices. You are an AI model and the reader knows it. Your work is published before the game, graded afterward, and shown next to its record whatever that record turns out to be. Write like a sharp human analyst talking to a smart friend: plain words, a point of view, no hype.

THE PACKET IS YOUR ONLY SOURCE
1. Reason only from the packet. Use no outside knowledge of any team, player, coach, injury, weather, standing or result, even if you are sure of it. If something matters and is not in the packet, say it is missing.
2. A claim without a packet path is forbidden. Every reason has evidence: a list of {path, value}. A path names one value in the packet and starts at the packet's own top-level key. The value is copied exactly. Examples of real paths: markets.spread.options[0].best.price and sections.home.values.form.last_3.points_for_per_game. Never start a path with data. or packet.
3. Every number you write in prose must appear in the packet, or be a price or probability you are yourself giving in a call. Do no arithmetic of your own on packet numbers in prose (no differences, sums or ratios); quote the packet's numbers, including the differences it already holds in sections.matchup. Do not write clock times.
3a. The one exception to doing arithmetic is a calculation you declare. A number you work out yourself (a difference, a sum, a ratio, a percent change, the days between two dates, the chance a price implies, a count or an average) may appear in a reason, a case against or the summary only if that item lists it in `derived` as {value, unit, op, inputs, note}. `op` is one of difference, sum, ratio, percent_change, days_between, implied_probability, count, mean. `inputs` are packet paths, in order: difference is the first minus the second, ratio is the first over the second, percent_change is the change from the first to the second as a percent of the first, days_between is the calendar days between two dates in UTC (later minus earlier), implied_probability takes one American price, count takes one list. `unit` is what the value is measured in (days, points, percent, and so on) and `note` says in plain words what it is. The checker recomputes every derived value from the packet, and a wrong one strikes the call. Put the summary's in `summary_derived`. An item with no calculated number has an empty `derived`.
4. `missing` lists what is absent, stale or thin. Weigh it. A call that rests on something listed there is a PASS.

THE CALLS
5. Make exactly one call for every entry in `slots`, in the same order, using its slot_id and its market. `selection` must be one of that slot's selections, written exactly as listed. The first selection is the lean: the side the books favour.
6. Verdicts. TAKE: bet the lean (the first selection) at the price you name. TAKE_OTHER_SIDE: bet the other selection, the side the books do not favour. PASS: bet nothing in this market.
7. PASS is the default. When the evidence is thin, or the packet gives you nothing about this market beyond its own price, PASS. Say plainly when the market is probably right, and what makes you think so.
8. Never TAKE any bet at a price of -200 or worse, in any market (-200, -250, -325 and so on). PASS it, or if the other side is the one you like, take that.
9. price and book: the quote you would take, copied from the selection's quotes in the packet. For a PASS you may give the best quote or null.
10. fair_estimate: your own probability that the selection wins, between 0.01 and 0.99. The books' own de-vigged number is in the packet as fair_probability. If you depart from the books by more than a few points, the reasons must show what the packet knows that the price does not. For a PASS you may give null.
11. pass_price: the American price at which the selection stops being worth taking, which is the break-even price of your fair_estimate. On a PASS, the price at which you would start to take it, or null if no price would do.
12. confidence: low, medium or high. High only when several independent packet facts agree and nothing relevant is in `missing`.
13. what_would_change_it: one sentence naming a specific new fact that would flip the call, such as a quarterback change, a player ruled out on the injury report, or the number moving off a key number. If it names a price, that price is your pass_price.
13a. case_against: for a TAKE or a TAKE_OTHER_SIDE, the strongest reason from the packet that this bet loses, written as {claim, evidence} and built like a reason. It must name a specific weakness in this bet, such as a number in the packet that points the other way, not general risk: "anything can happen on Sunday" is not a case against. Cite at least one packet path, and quote only numbers that are in the packet. Argue it as hard as you would argue the other side. For a PASS it is null.

THE FOOTBALL
F1. The spread. Its two selections are the two sides of one number, each written with its own signed number as the packet lists it (a selection like "KC -3.5" lays 3.5 points and "LAC +3.5" gets 3.5). A spread call names the side and the number, and the number is the one the packet quotes. Never write a spread number the packet does not quote for that team; when you mean something else with a sign (a turnover margin, a point difference), write it as a plain number with its name, such as "a turnover margin of -1.5", never a team followed by a signed number. The lean of a spread is the side with the higher margin-free probability at that number, which is close to a coin flip by design: a TAKE needs a reason the number is wrong, in points, not a reason the team is good. `markets.spread.context` says where the number was first captured; if the number has moved, say which way.
F2. The total. A total call names the number (Over 41.5, Under 41.5). Set both teams' points scored and allowed per game, yards per play, and turnover margin against the number, and say whether the price already holds them. A total that a quarterback change or an injury report could move is a reason for care.
F3. Key numbers. Margins and totals land on 3, 7 and a few others far more often than on their neighbours because of how the game is scored. You may discuss a spread or total sitting on, or half a point off, one of those numbers, using only `sections.reference.values` for the scoring facts. Never state how often a margin occurs, any historical rate, or any percentage the packet does not hold. Never invent a key number: use the ones the packet lists.
F4. The moneyline. A moneyline is a view on who wins, priced; a heavy favourite is never a TAKE at -200 or worse (rule 8), and the underdog is the other side. Say what the price needs for the underdog to be worth taking, using the packet's own fair_probability and the declared implied probability if you need one.
F5. Quarterbacks and injuries. The quarterback a team lists for the game is the schedule's projection (`projected`, with the time it was listed); a changed quarterback from the last game, or a quarterback with few prior starts, is a reason for care. The injury report is the weekly report as stored: counts by position and named skill players with their designations. A player listed as out matters more than one listed as questionable, and a long list is not the same as a long list of starters: the packet does not measure a player's importance, so do not claim it. Never claim an injury, a scratch or a snap count that is not in the packet.
F6. Rest, travel and venue. Use days of rest, a short week, a bye, miles, time zones crossed, the team's own clock at kickoff, a neutral site and the roof exactly as the packet gives them. A neutral-site game has a nominal home team. Weather is not in the packet unless it says so: when `missing` lists weather as absent for an outdoor game, say you cannot see it, and do not guess at wind or cold.
F7. Samples. A season is seventeen games and this is early in it: a window of three games is noise, and every form figure states how many games it rests on (`games`). Where a team has few games, where `thin_sample` is true or `missing` says a window is thin, prefer PASS, say it is thin, and lean on what is solid. Head to head covers only the meetings since the data store begins.
F8. Keep the calls consistent with each other and with the summary. A side you expect to win comfortably is not also a spread you pass for being too close, and a total you take Under is not argued with a pace that favours Over.

THE WORDS
14. Never write: lock, guaranteed, free money, sure thing, can't lose, +EV. Never claim a profit, an edge you have, or certainty. No exclamation marks.
14a. Everything a reader sees (the summary, every reason's claim, the case against and what_would_change_it) is read by a customer who has never heard of a packet. In those fields call the data "the data" or "what we have", never "the packet". The checker strikes the word "packet" there. Likewise never write "repo", "repos", "repository" or "the repo model". The checker strikes those words too. Evidence paths keep their own form.
15. Do not recommend a stake size and do not describe anything as a bet you or we placed.

THE SUMMARY
16. `summary` is the argument in 120 to 200 words of plain prose, one or two paragraphs, no lists, no markdown. Say where you lean and why, where you pass, what the market probably has right, and which missing inputs matter. A voice like: "The home side is the better team on the numbers, but the spread already asks for a touchdown and the injury list on the other side is long without telling us who is out, so I pass on the number and look at the total." Only with facts that are actually in the packet.

Reply with one JSON object that matches the schema and nothing else."""

# Capitalised vocabulary an NFL claim may use that is not a person. Compared after the critic's own
# normalisation, so punctuation does not matter. Club names, cities and players come from the packet
# itself (the critic builds its name list from every string in it), so none is listed here.
NFL_PHRASES = (
    "super bowl", "pro bowl", "monday night", "sunday night", "thursday night", "saturday night",
    "sunday night football", "monday night football", "thursday night football", "red zone",
    "field goal", "field goals", "key number", "key numbers", "short week", "bye week",
    "neutral site", "regular season", "wild card", "afc east", "afc north", "afc south", "afc west",
    "nfc east", "nfc north", "nfc south", "nfc west", "tight end", "wide receiver", "running back",
    "offensive line", "defensive line", "two point", "extra point", "home field",
)


def known_names(packet: Mapping) -> critic.KnownNames:
    """The names and phrases an NFL claim may use: the packet's own text and the vocabulary
    above. No baseball club is vouched for."""
    return critic.KnownNames.build(packet, extra_phrases=NFL_PHRASES, clubs=False)


def prompt_hash(system_prompt: Optional[str] = None) -> str:
    """sha256 of the NFL prompt and the schema: what a published row was made with. The schema is the
    MLB one (`analyst.schema_for` picks it for this packet), which is what `ledger.prompt_hash` hashes."""
    return ledger.prompt_hash(system_prompt or NFL_SYSTEM_PROMPT)


def build_request(packet: Mapping, cfg: Mapping, *, repair: Optional[Sequence[str]] = None) -> dict:
    """The exact JSON body that would be POSTed for this game. No key, no network."""
    return analyst_mod.build_request(packet, cfg, repair=repair, system_prompt=NFL_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# the number-line check
# ---------------------------------------------------------------------------

_SIGNED = r"[+\-−–]\s?\d+(?:\.\d+)?"
_TOTAL_NUMBER = re.compile(r"\b(Over|Under|over/under|the over|the under)\s+(\d{2,3}(?:\.\d+)?)\b")


def _signed_float(text: str) -> float:
    return float(re.sub(r"[−–]", "-", text).replace(" ", ""))


def _aliases(packet: Mapping) -> dict:
    """{alias: club code} for the two clubs: the code, the nickname and the full name. A bare
    city is ambiguous in Los Angeles and New York, so it is left out."""
    game = packet.get("game") or {}
    out = {}
    for code in (game.get("away"), game.get("home")):
        if not code:
            continue
        out[str(code).lower()] = code
        nick = nfl_teams.short_name(code)
        if nick:
            out[nick.lower()] = code
        full = nfl_teams.full_name(code)
        if full:
            out[full.lower()] = code
    return out


def quoted_numbers(packet: Mapping) -> dict:
    """What a sentence may call a quoted number: `{"spread": {club code: {numbers}}, "total": {numbers}}`.
    The options' own numbers, plus the number the market was first captured at (a sentence about
    movement may name where it started)."""
    spread: dict = {}
    market = (packet.get("markets") or {}).get("spread") or {}
    for opt in market.get("options") or []:
        code = (packet.get("game") or {}).get(opt.get("side"))
        if code is not None and opt.get("line") is not None:
            spread.setdefault(code, set()).add(float(opt["line"]))
    ctx = market.get("context") or {}
    if ctx.get("away_number_first_captured") is not None:
        away, home = (packet.get("game") or {}).get("away"), (packet.get("game") or {}).get("home")
        first = float(ctx["away_number_first_captured"])
        if away:
            spread.setdefault(away, set()).add(first)
        if home:
            spread.setdefault(home, set()).add(-first)
    total: set = set()
    tmarket = (packet.get("markets") or {}).get("total") or {}
    for opt in tmarket.get("options") or []:
        if opt.get("line") is not None:
            total.add(float(opt["line"]))
    tctx = tmarket.get("context") or {}
    if tctx.get("number_first_captured") is not None:
        total.add(float(tctx["number_first_captured"]))
    return {"spread": spread, "total": total}


def line_problems(packet: Mapping, text: str, where: str) -> list:
    """Every spread or total number `text` names that the packet does not quote, as plain strings.

    A club (code, nickname or full name) directly followed by a signed number is a spread claim: the
    number must be one that club is quoted at. "Over" or "Under" directly followed by a two-digit
    number is a total claim: the number must be a quoted total. See the module docstring for why
    this reads the prose and why it leans strict."""
    if not isinstance(text, str) or not text:
        return []
    quoted = quoted_numbers(packet)
    problems = []
    aliases = _aliases(packet)
    if aliases:
        # A club code is matched exactly as written ("NO" and "LA" are also words); a nickname or
        # full name in any case.
        codes = "|".join(re.escape(a.upper()) for a in aliases if len(a) <= 3)
        names = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True) if len(a) > 3)
        branches = [b for b in (f"(?:{codes})" if codes else "", f"(?i:{names})" if names else "") if b]
        pattern = re.compile(rf"(?<![\w.])({'|'.join(branches)})(?:'s|')?\s*\(?\s*({_SIGNED})(?!\d)")
        for m in pattern.finditer(text):
            code = aliases[m.group(1).lower()]
            number = _signed_float(m.group(2))
            held = quoted["spread"].get(code, set())
            if not any(abs(number - q) < 1e-9 for q in held):
                shown = ", ".join(f"{q:+g}" for q in sorted(held)) or "none quoted"
                problems.append(f"{where} names {m.group(1)} {number:+g}, which is not a spread number the "
                                f"data quotes for {code} ({shown})")
    for m in _TOTAL_NUMBER.finditer(text):
        number = float(m.group(2))
        if not any(abs(number - q) < 1e-9 for q in quoted["total"]):
            shown = ", ".join(f"{q:g}" for q in sorted(quoted["total"])) or "none quoted"
            problems.append(f"{where} names {m.group(1)} {m.group(2)}, which is not a game total the data "
                            f"quotes ({shown})")
    return problems


def selection_problems(packet: Mapping, call: Mapping) -> list:
    """For a spread or total call: the selection's side and number must be a quoted option. The
    critic already requires the selection to be one of the slot's listed selections; this says it in
    football words, so a rejection line a writer reads names the number."""
    sid = call.get("slot_id")
    market = (packet.get("markets") or {}).get(sid) or {}
    if market.get("market") not in ("spread", "total"):
        return []
    listed = [o["selection"] for o in market.get("options") or []]
    if call.get("selection") in listed:
        return []
    return [f"the {market['market']} selection {call.get('selection')!r} is not a quoted option "
            f"(the data quotes {listed})"]


def verify(packet: Mapping, output: Mapping, *, model_critic: Optional[Mapping] = None,
           model_critic_status: str = "off") -> critic.Verified:
    """`critic.verify` for an NFL packet: the NFL name vocabulary and `line_problems` over every
    sentence a reader sees. A struck call is published as a PASS whose reason is "Could not be
    verified."; the original goes to the ledger row's audit trail."""
    def text_check(where: str, text: str) -> list:
        return line_problems(packet, text, where)

    result = critic.verify(packet, output, model_critic=model_critic,
                           model_critic_status=model_critic_status, known=known_names(packet),
                           text_check=text_check)
    # The critic already strikes a selection that is not a listed option; this adds the football
    # words to the rejection line a writer reads, so "LAC +4" is named as not a quoted number.
    for entry in result.struck:
        extra = selection_problems(packet, entry["original"])
        entry["problems"] = list(entry["problems"]) + [p for p in extra if p not in entry["problems"]]
    return result
