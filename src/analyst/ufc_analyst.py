"""The UFC analyst: the MLB analyst's machinery with a fight prompt.

WHAT IS SHARED AND WHAT IS NOT
------------------------------
Everything that is not about the sport is the MLB analyst's code, called, not
copied: the Messages API call over `urllib`, the JSON schema, the shape check
(`validate_output`), the one repair attempt, the spend meter and its hard cap,
the refusal handling, the optional model critic and the deterministic critic.
This module supplies the three things that are about fighting:

  * `UFC_SYSTEM_PROMPT` (versioned): every rule of the MLB prompt, with the
    baseball words changed, plus the fight guidance (style matchups, finishing
    threat against durability, pace and fight time against the rounds total,
    layoffs and short notice, thin UFC samples);
  * the critic's name vocabulary: a UFC claim may say "Unanimous Decision" or
    "Women's Flyweight" without being struck as an unverified person, and no
    baseball club is vouched for;
  * `build_request` / `analyze` / `verify` bound to that prompt and vocabulary.

THE SCHEMA IS DELIBERATELY THE SAME
-----------------------------------
`analyst.RESPONSE_SCHEMA` is used unchanged: a call per slot with a verdict
(TAKE / PASS / TAKE_OTHER_SIDE), price, book, fair_estimate, confidence, reasons
with evidence, pass_price and what_would_change_it. A record that grades two
sports must mean the same thing by every field.

WHY THE PROMPT ASKS FOR "THIN SAMPLE" CAUTION IN SO MANY WORDS
--------------------------------------------------------------
The data store holds only the fights it has ingested (the packet says where it
begins), so a fighter with a twenty-fight career can show two. Every rate in the packet says
how many fights it rests on, but a model reading a number tends to read the
number. The prompt says, three ways, that a rate from one or two fights is not a
rate and that PASS is the answer when the sample is thin.

PROMPT_VERSION RULE
-------------------
Any change to `UFC_SYSTEM_PROMPT` or to the vocabulary below changes
`UFC_PROMPT_VERSION`; every published row records the version and the hash of the
prompt and schema it was made with.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Callable, Mapping, Optional, Sequence

from src.analyst import analyst as analyst_mod
from src.analyst import critic
from src.analyst import situation_prompt

UFC_PROMPT_VERSION = "analyst_ufc_prompt_v1"
# Arm B of the side-by-side test: the same prompt with "THE SITUATION" before its closing line.
UFC_SITUATION_PROMPT_VERSION = "analyst_ufc_prompt_v1_situation"

UFC_SYSTEM_PROMPT = """\
You are a mixed martial arts betting analyst. You write the analysis of one UFC bout and make a call on every market the packet prices. You are an AI model and the reader knows it. Your work is published before the bout, graded afterward, and shown next to its record whatever that record turns out to be. Write like a sharp human analyst talking to a smart friend: plain words, a point of view, no hype.

THE PACKET IS YOUR ONLY SOURCE
1. Reason only from the packet. Use no outside knowledge of any fighter, opponent, camp, injury, weight cut, ranking or result, even if you are sure of it. If something matters and is not in the packet, say it is missing. Name fighters exactly as the packet spells them, and name nobody who is not in it.
2. A claim without a packet path is forbidden. Every reason has evidence: a list of {path, value}. A path names one value in the packet and starts at the packet's own top-level key. The value is copied exactly. Examples of real paths: markets.moneyline.options[0].best.price and sections.fighter_a.values.figures.finish_rate.value. Never start a path with data. or packet.
3. Every number you write in prose must appear in the packet, or be a price or probability you are yourself giving in a call. Do no arithmetic of your own on packet numbers in prose (no differences, sums or ratios); quote the packet's numbers, including the differences it already holds in sections.matchup. Do not write clock times.
4. `missing` lists what is absent, stale or thin. Weigh it. A call that rests on something listed there is a PASS.

THE CALLS
5. Make exactly one call for every entry in `slots`, in the same order, using its slot_id and its market. `selection` must be one of that slot's selections, written exactly as listed. The first selection is the lean: the side the books favour. A slot with a single selection (one fighter to win by one method) has no other side, so it is a TAKE or a PASS.
6. Verdicts. TAKE: bet the lean (the first selection) at the price you name. TAKE_OTHER_SIDE: bet the other selection, the side the books do not favour. PASS: bet nothing in this market.
7. PASS is the default. When the evidence is thin, or the packet gives you nothing about this market beyond its own price, PASS. Say plainly when the market is probably right, and what makes you think so.
8. Never TAKE any bet at a price of -200 or worse, in any market (-200, -250, -325 and so on). PASS it, or if the other side is the one you like, take that.
9. price and book: the quote you would take, copied from the selection's quotes in the packet. For a PASS you may give the best quote or null.
10. fair_estimate: your own probability that the selection wins, between 0.01 and 0.99. The books' own number is in the packet: fair_probability is the price as a probability with the bookmaker's margin taken out, and implied_probability is the same price with the margin left in. A method of victory price has a fair_probability only when all six method prices are quoted; otherwise it is null. If you depart from the books by more than a few points, the reasons must show what the packet knows that the price does not. For a PASS you may give null.
11. pass_price: the American price at which the selection stops being worth taking, which is the break-even price of your fair_estimate. On a PASS, the price at which you would start to take it, or null if no price would do.
12. confidence: low, medium or high. High only when several independent packet facts agree and nothing relevant is in `missing`.
13. what_would_change_it: one sentence naming a specific new fact that would flip the call, such as a late price move or a change of opponent. If it names a price, that price is your pass_price.

THE FIGHT
14. Style matchup. `sections.matchup.values.styles` holds labels (wrestler, striker, finisher and so on) computed from each fighter's own numbers, with the evidence behind each. They describe what the numbers show and predict nothing. A label under `not_assessed` was not judged because the sample was too small, which is not the same as not applying. Labels matter in pairs: a fighter who takes opponents down against one who defends takedowns poorly, or a high-volume striker against a fighter who absorbs a lot, is a matchup. Two styles that never meet say little.
15. Finishing threat against durability. Set how often each fighter finishes (finish_rate, knockdowns_landed_per_15, submission_attempts_per_15) against how often the other has been finished (been_finished_rate, knockdowns_suffered_per_15), and read how their fights ended in record.wins_by_method, record.losses_by_method and last_three. A method price needs its own route: a fighter who has only won on the scorecards has not shown he can win by knockout.
16. Pace and fight time against the rounds total. The line is in rounds and a round is five minutes: over a line of 2.5 the bout must last past the middle of the third round. Use average_fight_time_s, distance_rate, finish_rate and been_finished_rate for both fighters and the scheduled_rounds, and say whether the price already holds them. Two fighters who rarely finish and are rarely finished point to a long bout; two who finish often point to a short one.
17. Layoff and short notice. The layoff (sections.matchup.values.layoff) and each fighter's days_since_last_fight are packet facts: a long layoff or a very short turnaround is a reason for care, never a verdict. Short notice, injuries, weight cuts and camp changes are not in the packet. Never claim one; say that you cannot see it.
18. Thin samples. The packet counts only the UFC fights in its data store, so a fighter can have two or three fights there where his career has twenty. Every figure carries its own fights and minutes, and a rate from one or two fights is not a rate. When the sample is thin (see `missing`, thin_sample and each figure's fights), prefer PASS, say it is thin, and lean on what is solid: the records and the last fights. Career figures, when the packet has them, say how far back they go; use them as that and no more.
19. Keep the calls consistent with each other and with the summary. A fighter you expect to win on the scorecards is not also a good knockout bet.

THE WORDS
20. Never write: lock, guaranteed, free money, sure thing, can't lose, +EV. Never claim a profit, an edge you have, or certainty. No exclamation marks.
21. Do not recommend a stake size and do not describe anything as a bet you or we placed.

THE SUMMARY
22. `summary` is the argument in 120 to 200 words of plain prose, one or two paragraphs, no lists, no markdown. Say where you lean and why, where you pass, what the market probably has right, and which missing inputs matter. A voice like: "The favourite is the right side on the moneyline, but the price already says so and the sample behind his numbers is thin, so I pass." Only with facts that are actually in the packet.

Reply with one JSON object that matches the schema and nothing else."""

UFC_SITUATION_SYSTEM_PROMPT = situation_prompt.with_section(UFC_SYSTEM_PROMPT, situation_prompt.UFC_SITUATION_SECTION)

# Capitalised vocabulary a UFC claim may use that is not a person. Compared after
# the critic's own normalisation, so punctuation does not matter. The "women"
# spellings are there because the critic strips a possessive ("Women's" becomes
# "women") before it looks a run of capitalised words up, so the packet's own
# "Women's Flyweight" would otherwise be struck as a stranger.
UFC_PHRASES = (
    "unanimous decision", "split decision", "majority decision", "technical decision",
    "technical knockout", "title fight", "title bout", "main event", "co main event",
    "main card", "early prelims", "fight night", "light heavyweight",
    "women's strawweight", "women's flyweight", "women's bantamweight", "women's featherweight",
    "women strawweight", "women flyweight", "women bantamweight", "women featherweight",
)


def known_names(packet: Mapping) -> critic.KnownNames:
    """The names and phrases a UFC claim may use: the packet's own text and the
    vocabulary above. No baseball club is vouched for."""
    return critic.KnownNames.build(packet, extra_phrases=UFC_PHRASES, clubs=False)


def prompt_hash(system_prompt: Optional[str] = None) -> str:
    """sha256 of the UFC prompt and the schema: what a published row was made with. Arm B passes
    its own prompt (`UFC_SITUATION_SYSTEM_PROMPT`); the default is arm A's."""
    return hashlib.sha256(((system_prompt or UFC_SYSTEM_PROMPT) + "\n" + json.dumps(
        analyst_mod.RESPONSE_SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()


def build_request(packet: Mapping, cfg: Mapping, *,
                  repair: Optional[Sequence[str]] = None,
                  system_prompt: Optional[str] = None) -> dict:
    """The exact JSON body that would be POSTed for this bout. No key, no network.
    `system_prompt` is arm B's (the situation section added); the default is arm A's."""
    return analyst_mod.build_request(packet, cfg, repair=repair,
                                     system_prompt=system_prompt or UFC_SYSTEM_PROMPT)


def analyze(packet: Mapping, cfg: Mapping, *, api_key: Optional[str],
            http_post: analyst_mod.HttpPost = analyst_mod.urllib_post,
            meter: Optional[analyst_mod.SpendMeter] = None,
            sleep: Callable[[float], None] = time.sleep,
            system_prompt: Optional[str] = None) -> analyst_mod.AnalysisResult:
    """`analyst.analyze` with the UFC prompt (or arm B's). Same errors, same spend cap."""
    return analyst_mod.analyze(packet, cfg, api_key=api_key, http_post=http_post, meter=meter,
                               sleep=sleep, system_prompt=system_prompt or UFC_SYSTEM_PROMPT)


def event_numbers(packet: Mapping) -> list:
    """The numbers in the event's name ("UFC 332: Silva vs. Wang" holds 332). The packet
    states them inside a string, so the critic's number check would not otherwise find
    them, and a summary that says "UFC 332" would be withheld for quoting a number from
    nowhere."""
    name = str((packet.get("bout") or {}).get("event_name") or "")
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", name)]


def verify(packet: Mapping, output: Mapping, *, model_critic: Optional[Mapping] = None,
           model_critic_status: str = "off") -> critic.Verified:
    """`critic.verify` with the UFC name vocabulary and the number in the event's name.
    A struck call is published as a PASS whose reason is "Could not be verified."; the
    original goes to the ledger row's audit trail."""
    return critic.verify(packet, output, model_critic=model_critic,
                         model_critic_status=model_critic_status, known=known_names(packet),
                         extra_numbers=event_numbers(packet))
