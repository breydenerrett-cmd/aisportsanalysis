"""Every system text the desk and persona hounds send, the stages they run in, and the hound definitions.

WHY ONE FILE
------------
The prompt IS the strategy for a model-written hound, so it is a pre-registered artifact
(docs/PREREG_DESK_HOUNDS.md): `config/desk_hounds.json` carries each hound's prompt version and
sha256, every ledger row repeats them, and `publish` refuses a game prepared under a different
prompt. Keeping every system text, the stage graph and the plain-English `rule_text` side by side
means one diff shows everything that changed, and a test regenerates the config from this file so the
copy a visitor reads cannot drift from the prompt a model was given.

THE STAGES
----------
The Desk is seven requests in three waves, each a Sonnet subagent answering one request file:

    wave 1   analyst_stats, analyst_situation, analyst_market, analyst_injury   (the data only)
    wave 2   bull, bear                       (the data and the four checked reports)
    wave 3   head                             (the data, the four reports, the bull and the bear)

Each persona is a single request on the data alone and can run in wave 1. The four analysts are
lenses on the SAME data, not four sources: the point of the structure is to make a model argue
both ways before it decides, as the open-source TradingAgents project does with a bull and a bear, not
to add information. Nothing here is borrowed from that project but the shape of the idea.

WHAT EVERY ROLE IS TOLD, AND WHY IT IS THE ANALYST'S OWN RULES
-------------------------------------------------------------
`_COMMON` restates the analyst prompt's discipline (src/analyst/analyst.py, rules 1 to 4, 14, 14a and
15): the data is the only source, every claim carries packet paths, every number is a packet number or a
declared calculation the checker recomputes, banned words and the project's internal words are struck.
The checker that enforces them is the analyst's own (src/analyst/critic.py), so a role that breaks them is
rejected by the same code that rejects the analyst. The decision roles are also told the code risk rules
(section 3 of the pre-registration) so a model does not spend a TAKE on something code will strike; telling it
changes nothing about what code does.

"edge" AND "packet": the checker strikes "packet" and "repo" in any prose a reader may see and "edge" unless
negated. The roles say "the data" and never claim an advantage. These texts are not scanned (they are
instructions, not published prose), but a test pins that none of them tells a model to claim a profit.

Pure data and string building: no I/O, no clock, no network, no FastAPI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from src.hounds.desk import schemas
from src.hounds.desk.personas import DESK_PERSONAS

PROMPT_VERSION = "desk_prompt_v1"

KIND_REPORT = "report"
KIND_DECISION = "decision"

SPORTS = ("mlb", "nfl")

_COMMON = """\
THE DATA IS YOUR ONLY SOURCE
1. Reason only from the data in the request: one JSON object. Use no outside knowledge of any team, player, injury, weather, standing, price or result, even if you are sure of it. If something matters and is not in the data, say it is missing. You have no tools and no memory of other games.
2. A claim without a data path is forbidden. Every finding and every reason has evidence: a list of {path, value}. A path names one value in the data and starts at the data's own top-level key, with dots between keys and [n] for list items. Examples of real paths: markets.moneyline.options[0].best.price and sections.starters.values.home_sp_era. The value is copied exactly. Never start a path with data. or packet.
3. Every number you write in prose must appear in the data, or be a probability you are yourself giving, or be a calculation you declare. Do no arithmetic of your own in prose. A calculation you declare goes in the `derived` list of the item that uses it, as {value, unit, op, inputs, note}. `op` is one of difference, sum, ratio, percent_change, days_between, implied_probability, count, mean. `inputs` are data paths, in order: difference is the first minus the second, ratio is the first over the second, percent_change is the change from the first to the second as a percent of the first, days_between is the calendar days between two dates in UTC (later minus earlier), implied_probability takes one American price, count takes one list. `unit` is what the value is measured in (runs, points, days, percent, probability and so on). The checker recomputes every declared value from the data and a wrong one rejects the item. An item with no calculated number has an empty `derived`. A number written in another analyst's report is not in the data: if you use it, work it out again and declare it yourself. Do not write clock times.
4. `missing` in the data lists what is absent, stale or thin. Weigh it. Never fill a gap with a guess.

THE WORDS
5. Never write: lock, guaranteed, free money, sure thing, can't lose, +EV. Never claim a profit, an edge you have or certainty. No exclamation marks.
6. Everything you write is read by a customer who has never heard of a packet. Call the data "the data" or "what we have", never "the packet". Never write "repo", "repos" or "repository". Name no person or club that is not in the data. Evidence paths keep their own form.
7. Do not recommend a stake size and do not describe anything as a bet anyone placed. This is paper only: no money is staked.
8. You are an AI model and the reader knows it. Write like a sharp human analyst talking to a smart friend: plain words, a point of view, no hype.

"""

_REPORT_OUTPUT = """\
YOUR ANSWER
Reply with one JSON object that matches the schema and nothing else:
  text          your report: {lo} to {hi} words of plain prose, one or two paragraphs, no lists, no markdown.
  text_derived  the calculations the text relies on (empty list if none).
  findings      1 to 8 items, each {{claim, evidence, derived}}: one checkable statement with the data paths behind it.
  focus         the markets where your lens points to a side: a list of {{slot_id, selection}}, selection written exactly as the slot lists it. An empty list when your lens points nowhere.
A finding that fails the checker is struck and your whole answer may be asked for again, so keep every claim to what a path shows.
"""

_DECISION_OUTPUT = """\
YOUR ANSWER: THE MENU
For each market slot in the data your decision is one of two things: TAKE one of its selections, or PASS. PASS is the default and the usual answer; list only the slots you TAKE. A slot you do not list is a PASS. Listing nothing passes the whole game and is a good answer when the data does not support a bet.

Reply with one JSON object that matches the schema and nothing else:
  summary           {lo} to {hi} words of plain prose, one or two paragraphs, no lists, no markdown: where you would take a side and why, where you pass, and which missing inputs matter.
  summary_derived   the calculations the summary relies on (empty list if none).
  decisions         your TAKEs, at most 2, each {{slot_id, selection, verdict, price, book, probability, reasons, case_against, what_would_change_it}}.
    verdict         always "TAKE".
    selection       one of that slot's listed selections, written exactly as listed.
    price and book  the selection's best quote: copy `best.price` and `best.book` from its option in the data. Any other quote is struck.
    probability     your own probability that the selection wins, between 0.01 and 0.99.
    reasons         one or more {{claim, evidence, derived}}.
    case_against    the strongest reason from the data that this bet loses, as {{claim, evidence, derived}}: a specific weakness in this bet, such as a number in the data that points the other way, not general risk. Argue it as hard as you argued the bet.
    what_would_change_it  one sentence naming a specific new fact that would flip the call.

THE RULES CODE APPLIES TO YOUR TAKES, WHATEVER YOU WRITE
A. A TAKE at a price of -200 or worse is struck. So is one whose board average price is -200 or worse. Never TAKE one.
B. A TAKE whose price is not the selection's best quote in the data is struck.
C. A TAKE is struck unless your probability is higher than the selection's fair_probability in the data (the books' own de-vigged number) AND higher than the break-even probability of the average of the prices the books quote for that selection. The break-even probability of a price is what that price implies with the margin left in. If you cannot show a reason your probability is higher, PASS.
D. Only the two TAKEs with the largest gap between your probability and that break-even are kept.
{persona_rule}Weigh the books' fair_probability seriously: it is the starting point, and a reason to depart from it must show what the data knows that the price does not.
"""


def _report_system(title: str, lens: str, words: tuple) -> str:
    return (f"You are {title} on an AI betting desk for LineHound Hounds, a public, paper-only race of "
            f"betting strategies. You read one game's frozen data and write a short report from one "
            f"lens. Your work is checked, published before the game and shown next to its record "
            f"whatever that turns out to be.\n\nYOUR LENS\n{lens}\n\n"
            + _COMMON + _REPORT_OUTPUT.format(lo=words[0], hi=words[1]))


def _decision_system(title: str, mission: str, words: tuple, persona_rule: str = "") -> str:
    return (f"You are {title} for LineHound Hounds, a public, paper-only race of betting strategies. "
            f"You read one game's frozen data and decide what, if anything, to take from the fixed menu "
            f"below. Your decision is checked by code, recorded before the game, graded afterward and "
            f"shown next to its record whatever that turns out to be.\n\n{mission}\n\n"
            + _COMMON + _DECISION_OUTPUT.format(lo=words[0], hi=words[1], persona_rule=persona_rule))


_STAT_WORDS = (80, 200)
_CASE_WORDS = (100, 220)
_HEAD_WORDS = (100, 220)
_PERSONA_WORDS = (60, 160)

_STATS_LENS = (
    "You are the stats analyst. Read only the numbers about the teams and players: team records and "
    "season numbers, recent-form windows, starting pitchers and their splits, bullpens, pitch "
    "arsenals and lineups' numbers against them for baseball; form windows, record, scoring and "
    "yards numbers, the quarterback and the home-minus-away differences for football. Say which side "
    "those numbers favour in each market where they speak, how big the sample behind each number is, "
    "and where a number is thin (a short form window, a handful of starts). Do not argue from prices, "
    "news, travel or weather; the other analysts have those.")

_SITUATION_LENS = (
    "You are the situation and news analyst. Use only facts that are in the data: rest and travel, "
    "the schedule, the park and the weather (or that no weather is stored), the standings and what the "
    "date implies, and the transactions and notes in the news section. A fact from your own memory "
    "about what a club 'needs' or how a venue 'plays' is not in the data and is forbidden. Say which "
    "side, or which total, those facts lean toward in each market where they speak, and say plainly "
    "when the data holds nothing about the situation. Do not argue from team statistics or prices.")

_MARKET_LENS = (
    "You are the market analyst. Read the prices in `markets`: how many books quote each selection, "
    "how far the best quote is from the others, the books' de-vigged fair_probability, how old each "
    "quote is (captured_utc and as_of), what `missing` says about stale or absent prices, and whether "
    "the markets agree with each other (a moneyline, a run line or spread and a total that tell the "
    "same story or different ones). The data holds only the newest quote from each book, captured at the "
    "time shown; it holds no history of how a price moved. Never describe a line moving, steaming or "
    "being bet down unless a value in the data shows it; say that no movement history is stored. Do not "
    "argue from team statistics, news or weather. Say where the market looks thin or inconsistent, and "
    "which side the prices lean to in each market.")

_INJURY_LENS = (
    "You are the injury and lineup analyst. Read what the data says about who is playing: the "
    "probable starters, the lineups posted (or that they are not posted), the injury and transaction "
    "notes, and for football the injury report and the quarterback. Say who is confirmed, who is "
    "listed, who is missing, what that means for each side, and which markets it touches (a starter "
    "or quarterback change moves the moneyline and the total; a missing player moves his own props). "
    "Do not infer a player's importance from memory; use what the data shows about him. Do not argue "
    "from prices or team statistics.")

_BULL_MISSION = (
    "You are the bull researcher on an AI betting desk. You have the data and four checked reports "
    "(stats, situation and news, market, injuries and lineups). Build the strongest honest case FOR "
    "taking the one or two bets, at most, that the data and the reports best support, naming the "
    "market slot, the selection and the best price. Use the reports as leads and check each fact you "
    "rely on against the data yourself, citing its path. If nothing is supported well enough to take, "
    "say so plainly and name the closest call. You argue one side; a bear researcher is arguing the "
    "other and a desk head will weigh both. Do not soften your case, and do not invent support.")

_BEAR_MISSION = (
    "You are the bear researcher on an AI betting desk. You have the data and four checked reports "
    "(stats, situation and news, market, injuries and lineups). Build the strongest honest case that "
    "the market is right and that a bet here loses: where a report's lean is outweighed by another, "
    "where a number rests on a thin sample, where an input is missing or stale (`missing`), where the "
    "price already reflects what the reports found, and where the books' fair_probability is the best "
    "estimate in the data. Cover every market where a report leans to a side. A bull researcher is "
    "arguing the other way and a desk head will weigh both. Do not soften your case, and do not invent "
    "support.")

_HEAD_MISSION = (
    "You are the desk head, the portfolio manager of an AI betting desk. You have the data, four "
    "checked analyst reports (stats, situation and news, market, injuries and lineups), the bull "
    "researcher's case and the bear researcher's case. Decide. PASS the whole game unless the data "
    "and the argument support a bet clearly: the market is hard to beat and a pass is a fine answer. "
    "A TAKE needs a reason you can point to in the data that the price does not already reflect, and "
    "you must answer the bear's strongest point in your case_against. Do not follow the bull or the "
    "bear because of how well it is written; weigh what each shows. Report whether you took the "
    "bull's or the bear's side in your summary.")


@dataclass(frozen=True)
class Role:
    stage: str
    kind: str                  # KIND_REPORT | KIND_DECISION
    title: str
    system: str
    needs: tuple = ()          # stages whose checked material this stage reads
    hound_id: Optional[str] = None   # the hound a decision stage decides for
    words: tuple = (0, 0)      # prose word limits (text/summary)

    def schema(self) -> dict:
        return schemas.REPORT_SCHEMA if self.kind == KIND_REPORT else schemas.DECISION_SCHEMA

    def prompt_hash(self) -> str:
        """sha256 of the system text and the schema: what a row was made with."""
        return hashlib.sha256((self.system + "\n" + json.dumps(self.schema(), sort_keys=True))
                              .encode("utf-8")).hexdigest()


def _report(stage, title, lens, words=_STAT_WORDS):
    return Role(stage, KIND_REPORT, title, _report_system(title, lens, words), words=words)


def _case(stage, title, mission, needs):
    return Role(stage, KIND_REPORT, title,
                _decision_free_case_system(title, mission, _CASE_WORDS), needs=needs, words=_CASE_WORDS)


def _decision_free_case_system(title: str, mission: str, words: tuple) -> str:
    return (f"{mission}\n\nYour name on the desk is {title}. This is a public, paper-only race of "
            f"betting strategies called LineHound Hounds. Your work is checked, published before the "
            f"game and shown next to its record whatever that turns out to be.\n\n"
            + _COMMON + _REPORT_OUTPUT.format(lo=words[0], hi=words[1]))


# ---------------------------------------------------------------------------
# the personas: philosophy in the system text, checkable parts also enforced by code (risk.py)
# ---------------------------------------------------------------------------

_SHARP = (
    "You are the Sharp. Your philosophy is price. You ignore narratives, momentum, names and "
    "storylines entirely. You TAKE a selection only when the best quote in the data is a better price "
    "than the books' own de-vigged number: the break-even probability of the best quote must be below "
    "the selection's fair_probability. When no best quote clears that, you PASS the whole game, and "
    "most games you will. Your probability is the books' fair_probability plus only what a path in the "
    "data justifies. Use the market numbers; do not argue stories.")
_SHARP_RULE = ("E. The Sharp's own rule: a TAKE is struck unless the break-even probability of the best quote "
               "is below the selection's fair_probability.\n")

_SQUARE = (
    "You are the Square, the deliberate control. You like what a casual bettor likes: the favourite to "
    "win and the game to go over. You TAKE only the moneyline favourite (the lean of the moneyline "
    "slot) or the Over on the game total. You never take an underdog, an under, a spread or run "
    "line, a team total or a prop. If neither the favourite nor the over has a reason in the data "
    "that you can state, you PASS. You are here so the other hounds are measured against a plain "
    "taste, not because it is a good one.")
_SQUARE_RULE = ("E. The Square's own rule: only the moneyline favourite or the Over on the game total; "
                "anything else is struck.\n")

_FADER = (
    "You are the Fader. Your philosophy is to take the other side of what the favourite and the over "
    "suggest, because the side a casual bettor likes is priced for it. You TAKE only a moneyline "
    "underdog, a side that gets points on the run line or point spread (a positive number), or an Under "
    "(a game total, a team total or a prop). You never take a favourite, an over, or a side that lays "
    "points. The data holds no betting percentages and, for baseball, no line-movement history, so you "
    "use the favourite and the over as your stand-in for the popular side and say so; where the "
    "data shows how a line has moved you may use that. If the contrarian side has no reason in the data "
    "that you can state, you PASS.")
_FADER_RULE = ("E. The Fader's own rule: only a moneyline underdog, a side that gets points, or an Under; "
               "anything else is struck.\n")

_WEATHER = (
    "You are the Weather Nerd. You bet totals and only totals: the game total and the team totals. "
    "You read the weather, the park, the starters and bullpens (baseball) or the stadium, the roof and "
    "the quarterbacks and pace of scoring (football) for what they imply about runs or points. When the "
    "data holds no weather, or says it is missing, you say so and weigh that: a total with no weather "
    "read is usually a PASS. You never take a side, a spread, a run line or a prop.")
_WEATHER_RULE = ("E. The Weather Nerd's own rule: only the game total and the team totals; anything else is "
                 "struck.\n")

_GRINDER = (
    "You are the Grinder. You want small, repeatable gaps between your read and the market, and you distrust big ones. You TAKE only an Under "
    "(a game total, a team total or a prop), or a moneyline favourite whose best price is -150 or "
    "shorter (nearer to even money). Your probability may be at most 5 percentage points above the "
    "selection's fair_probability: a bigger claimed gap is more likely your mistake than a finding, and "
    "code strikes it. If the market is right, you say so and PASS.")
_GRINDER_RULE = ("E. The Grinder's own rules: only an Under, or a moneyline favourite whose best price is -150 or "
                 "shorter; and your probability may exceed the selection's fair_probability by at most "
                 "0.05. Anything else is struck.\n")

_HISTORIAN = (
    "You are the Historian. You believe the past between these two clubs is the best guide. You use "
    "head-to-head and series history only (the matchup history section for baseball, the "
    "head-to-head section for football), plus the prices you take it against. Every reason behind a "
    "TAKE must cite either that history, a price path (markets.) or the game block (game.), and at "
    "least one must cite the history. A TAKE with no history behind it is struck. If the history is "
    "absent, thin or says nothing, you PASS. You do not argue form, injuries, weather or "
    "narratives.")
_HISTORIAN_RULE = ("E. The Historian's own rule: every path cited in a TAKE's reasons must be markets., game. or "
                   "the head-to-head / matchup history section, and at least one must be in that section; "
                   "anything else is struck.\n")


def _persona_role(stage, hound_id, title, mission, rule):
    return Role(stage, KIND_DECISION, title, _decision_system(title, mission, _PERSONA_WORDS, rule),
                hound_id=hound_id, words=_PERSONA_WORDS)


ANALYST_STAGES = ("analyst_stats", "analyst_situation", "analyst_market", "analyst_injury")
DESK_STAGES = ANALYST_STAGES + ("bull", "bear", "head")
PERSONA_STAGES = ("persona_sharp", "persona_square", "persona_fader", "persona_weather",
                  "persona_grinder", "persona_historian")

ROLES: dict = {
    "analyst_stats": _report("analyst_stats", "the stats analyst", _STATS_LENS),
    "analyst_situation": _report("analyst_situation", "the situation and news analyst", _SITUATION_LENS),
    "analyst_market": _report("analyst_market", "the market analyst", _MARKET_LENS),
    "analyst_injury": _report("analyst_injury", "the injury and lineup analyst", _INJURY_LENS),
    "bull": _case("bull", "the bull researcher", _BULL_MISSION, ANALYST_STAGES),
    "bear": _case("bear", "the bear researcher", _BEAR_MISSION, ANALYST_STAGES),
    "head": Role("head", KIND_DECISION, "the desk head",
                 _decision_system("the desk head", _HEAD_MISSION, _HEAD_WORDS),
                 needs=ANALYST_STAGES + ("bull", "bear"), hound_id="desk_ai", words=_HEAD_WORDS),
    "persona_sharp": _persona_role("persona_sharp", "desk_sharp", "the Sharp", _SHARP, _SHARP_RULE),
    "persona_square": _persona_role("persona_square", "desk_square", "the Square", _SQUARE, _SQUARE_RULE),
    "persona_fader": _persona_role("persona_fader", "desk_fader", "the Fader", _FADER, _FADER_RULE),
    "persona_weather": _persona_role("persona_weather", "desk_weather", "the Weather Nerd", _WEATHER,
                                     _WEATHER_RULE),
    "persona_grinder": _persona_role("persona_grinder", "desk_grinder", "the Grinder", _GRINDER,
                                     _GRINDER_RULE),
    "persona_historian": _persona_role("persona_historian", "desk_historian", "the Historian",
                                       _HISTORIAN, _HISTORIAN_RULE),
}

ALL_STAGES = DESK_STAGES + PERSONA_STAGES

# Ask-order: the first wave first. Used by session-plan to cut a run at the answer cap.
WAVE_ORDER = ANALYST_STAGES + PERSONA_STAGES + ("bull", "bear", "head")


# ---------------------------------------------------------------------------
# the hounds
# ---------------------------------------------------------------------------

MARKETS = ["moneyline", "run_line", "spread", "total", "team_total", "prop"]

HOUNDS: tuple = (
    {
        "id": "desk_ai", "name": "The Desk",
        "tagline": "Four analysts, a bull, a bear and a desk head argue every game in the open.",
        "category": "ai-desk", "style": "AI desk: analysts, bull and bear, desk head",
        "stages": DESK_STAGES, "decision_stage": "head",
        "rule_text": (
            "Four AI analysts (stats, situation and news, market, injuries and lineups) each write a "
            "checked report from the same frozen data. A bull and a bear then argue from those "
            "reports, and a desk head reads everything and may take at most two bets at the best "
            "quoted price, or pass the whole game. Code strikes any bet at -200 or worse, any price "
            "not in the data, and any bet whose stated probability does not beat both the books' own "
            "de-vigged number and the break-even of the average price. Every claim is checked against "
            "the data. One model reading, unproven; paper only."),
    },
    {
        "id": "desk_sharp", "name": "The Sharp",
        "tagline": "Only bets when the best price beats the books' own number.",
        "category": "persona", "style": "persona: price only",
        "stages": ("persona_sharp",), "decision_stage": "persona_sharp",
        "rule_text": (
            "An AI persona that ignores narratives. It takes a selection only when the break-even "
            "probability of the best quoted price is below the books' de-vigged fair probability, with "
            "a stated probability that beats the market's number and the average price, at most two "
            "bets a game. Code strikes any bet at -200 or worse or at a price not in the data. One "
            "model reading, unproven; paper only."),
    },
    {
        "id": "desk_square", "name": "The Square",
        "tagline": "Favourites and overs. The control for what a casual bettor takes.",
        "category": "persona", "style": "persona: control",
        "stages": ("persona_square",), "decision_stage": "persona_square",
        "rule_text": (
            "A deliberate control. An AI persona that takes only the moneyline favourite or the Over "
            "on the game total, never an underdog, an under, a spread, a team total or a prop, with a "
            "stated probability that beats the market's number and the average price, at most two bets "
            "a game. Code strikes any bet at -200 or worse. One model reading, unproven; paper only."),
    },
    {
        "id": "desk_fader", "name": "The Fader",
        "tagline": "Takes the other side of what the favourite and the over suggest.",
        "category": "persona", "style": "persona: contrarian",
        "stages": ("persona_fader",), "decision_stage": "persona_fader",
        "rule_text": (
            "An AI persona that fades the popular side, using the favourite and the over as its "
            "stand-in because the data holds no betting percentages. It takes only a moneyline "
            "underdog, a side that gets points, or an Under, with a stated probability that beats the "
            "market's number and the average price, at most two bets a game. Code strikes any bet at "
            "-200 or worse. One model reading, unproven; paper only."),
    },
    {
        "id": "desk_weather", "name": "The Weather Nerd",
        "tagline": "Totals only: weather, park, and the conditions of the game.",
        "category": "persona", "style": "persona: totals",
        "stages": ("persona_weather",), "decision_stage": "persona_weather",
        "rule_text": (
            "An AI persona that bets the game total and team totals only, reading weather, park and "
            "the scoring conditions in the data. It says so when the data holds no weather. Stated "
            "probability must beat the market's number and the average price, at most two bets a "
            "game. Code strikes any bet at -200 or worse. One model reading, unproven; paper only."),
    },
    {
        "id": "desk_grinder", "name": "The Grinder",
        "tagline": "Unders and short favourites, never a big claim.",
        "category": "persona", "style": "persona: small gaps",
        "stages": ("persona_grinder",), "decision_stage": "persona_grinder",
        "rule_text": (
            "An AI persona that takes only an Under, or a moneyline favourite priced -150 or shorter. "
            "Its stated probability must beat the market's number and the average price but may exceed "
            "the books' fair probability by at most 5 percentage points; a larger claimed gap is "
            "struck by code. At most two bets a game; any bet at -200 or worse is struck. One model "
            "reading, unproven; paper only."),
    },
    {
        "id": "desk_historian", "name": "The Historian",
        "tagline": "Head-to-head and series history, nothing else.",
        "category": "persona", "style": "persona: history",
        "stages": ("persona_historian",), "decision_stage": "persona_historian",
        "rule_text": (
            "An AI persona that argues only from head-to-head and series history. Every reason behind "
            "a bet must cite that history (or a price or the game block), and at least one must cite "
            "the history; code strikes any bet that does not. Stated probability must beat the "
            "market's number and the average price, at most two bets a game; any bet at -200 or worse "
            "is struck. One model reading, unproven; paper only."),
    },
)

HOUND_BY_ID: dict = {h["id"]: h for h in HOUNDS}
STAGE_HOUND: dict = {h["decision_stage"]: h["id"] for h in HOUNDS}


def hound_prompt_hash(hound_id: str) -> str:
    """sha256 over the prompt hashes of every stage the hound runs, in stage order."""
    hound = HOUND_BY_ID[hound_id]
    blob = "\n".join(f"{s}:{ROLES[s].prompt_hash()}" for s in hound["stages"])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def role_hashes() -> dict:
    return {stage: role.prompt_hash() for stage, role in ROLES.items()}


def config_document() -> dict:
    """The exact content of config/desk_hounds.json, generated from this file. A test regenerates it and
    compares, so the copy a visitor reads cannot drift from the prompt a model was given."""
    return {
        "version": 1,
        "prompt_version": PROMPT_VERSION,
        "ledger": "evidence/hounds_desk_v1.jsonl",
        "paper_only": True,
        "note": ("Generated by `python -m src.hounds.desk config --write` from src/hounds/desk/roles.py; "
                 "do not edit by hand. Pre-registered in docs/PREREG_DESK_HOUNDS.md."),
        "hounds": [
            {"id": h["id"], "name": h["name"], "tagline": h["tagline"], "category": h["category"],
             "style": h["style"], "rule_text": h["rule_text"], "sports": list(SPORTS),
             "markets": list(MARKETS), "who_decided": "model", "stages": list(h["stages"]),
             "prompt_version": PROMPT_VERSION, "prompt_hash": hound_prompt_hash(h["id"]),
             "persona": DESK_PERSONAS[h["id"]]}
            for h in HOUNDS],
    }
