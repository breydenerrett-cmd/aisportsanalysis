"""The words of "THE SITUATION": what arm B's prompt adds to the analyst's.

WHY IT IS ITS OWN MODULE
------------------------
`analyst.py` and `ufc_analyst.py` each build arm B's prompt as their own prompt plus one
section, and both need the section's text. Putting the text here, with no imports, keeps the two
from importing each other and keeps the side-by-side test's whole difference in one file you can
read in a minute: arm A reads the statistics; arm B reads the same prompt, the same packet and
the same schema, plus the situation section of the packet and the rules below. Nothing else
differs (`docs/SITUATION_LAYER.md`, "The side-by-side test").

THE SECTION APPENDS, IT NEVER REWRITES
--------------------------------------
Every rule of arm A's prompt is arm B's, word for word, with the same numbers. The new rules take
the next numbers (MLB 17 to 20, UFC 23 to 26) and sit just before the closing line, so the
shared text is a prefix and a test can prove it. A prompt that changed in other ways between the
arms would make the comparison a comparison of two prompts.

WHAT THE RULES ASK, AND WHY
---------------------------
* Say where the facts are and what is missing (the packet lists its holes; a claim that rests on
  one is not made).
* Weigh situation next to the statistics, not above them, and read the sample: in the playoffs
  every sample is small, the statistics' included, so situation can carry more weight than in
  April, but a small sample is still small and the sentence says so. This is the owner's idea
  tested, not assumed.
* Cite and quote like any other fact (the critic strikes a claim that does not).
* The market may already price the story. A hot team and a club that just won a series are
  stories everyone has; the rule asks the model to say what its situation fact adds that the
  price does not already hold, or not to depart from the books on it.
"""

MLB_SITUATION_SECTION = """\
THE SITUATION
17. `sections.situation` is the situation around this game: rest and rhythm, form, stakes, how each club has fared in October, head to head, who started and who is available, and where the game is played. Each fact has a value, the sample behind it, its date and a sentence. It is drawn only from games before this one. `sections.situation.values.missing` lists what the data could not say; never make a claim that rests on something listed there, and never guess it.
18. Weigh the situation next to the statistics, not above them. A situation fact moves your estimate only when it is large and its sample is not thin, and the sample is in the fact. In the postseason every sample is small, the statistics' included, so the situation can matter more there than in April, but a small sample is still small: say how small. A stretch of five or ten games is a description, not a trend.
19. Every situation claim cites its path in the packet like any other claim, for example sections.situation.values.factors.form.last_10.home.value. Quote the numbers as the packet writes them and do no arithmetic on them. Do not name a streak, a series, a drought or a record that is not in the packet.
20. The price may already include the story the situation tells. A fact everyone knows (a hot club, a club that just won a series, a bye) is more likely to be in the price than a fact few look at. If your estimate departs from the books because of a situation fact, say what that fact adds that the price does not already hold; if you cannot, it is not a reason to depart."""

UFC_SITUATION_SECTION = """\
THE SITUATION
23. `sections.situation` is the situation around this bout: layoff and turnaround, form, the card slot, the record in main events and title fights, the previous meeting and weight class. Each fact has a value, the sample behind it, its date and a sentence, and is drawn only from fights before this one. `sections.situation.values.missing` lists what the data could not say. Short notice, missed weight, injuries, camp news and rankings are never in the packet: never claim one, and never make a claim that rests on something listed as missing.
24. Weigh the situation next to the statistics, not above them. Fighters have a handful of fights in the data, so a situation fact rests on very little: read its sample, and let a layoff, a streak or a card slot move your estimate only when it is large and the sample is not thin.
25. Every situation claim cites its path in the packet like any other claim, for example sections.situation.values.factors.rest_and_rhythm.days_since_last_fight.a.value. Quote the numbers as the packet writes them and do no arithmetic on them. Do not claim a streak, a meeting or a record that is not in the packet.
26. The price may already include the story the situation tells. A fact everyone knows (a long layoff, a title fight, a winning streak) is more likely to be in the price than a fact few look at. If you depart from the books because of a situation fact, say what that fact adds that the price does not already hold; if you cannot, it is not a reason to depart."""

# The line both prompts end on. The section goes immediately before it.
CLOSING_LINE = "Reply with one JSON object that matches the schema and nothing else."


def with_section(prompt: str, section: str) -> str:
    """`prompt` with `section` inserted just before its closing line. Raises if the prompt does not
    end on that line: the arms must differ by the section and by nothing else."""
    if not prompt.endswith(CLOSING_LINE):
        raise ValueError("the prompt does not end with the closing line, so the section cannot be placed")
    return prompt[: -len(CLOSING_LINE)] + section + "\n\n" + CLOSING_LINE
