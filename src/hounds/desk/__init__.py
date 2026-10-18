"""The AI Desk and persona hounds: model-written hounds in the LineHound Hounds race.

Two families, both paper only, both forward only, both fed by the SAME frozen fact packet the AI analyst
uses (`src/analyst/packet.py`, `src/analyst/nfl_packet.py`):

* the Desk (`desk_ai`): four analysts (stats, situation and news, market, injuries and lineups), a bull and a
  bear who each read the four checked reports, and a desk head who reads everything and decides;
* six personas (`desk_sharp`, `desk_square`, `desk_fader`, `desk_weather`, `desk_grinder`,
  `desk_historian`): one request each, a fixed philosophy in the system text, the same menu.

Every answer is checked by the analyst's own checker (`src/analyst/critic.py`); code is the risk manager
(`risk.py`); the analyst pilot's publication rule (first answer is the candidate, at most three attempts, only
the checker's rejection lines as extra input) is enforced by the pilot's own attempt code. Pre-registered in
`docs/PREREG_DESK_HOUNDS.md`; how it works in `docs/DESK_HOUNDS.md`; the parent session's steps in
`docs/BRIEF_RUNBOOK.md`, "Desk and persona hounds".

No API key exists and none is used: the owner's scheduled Claude Code session spawns a Sonnet subagent per
request. Nothing in this package calls a model, opens a socket or places a bet, and nothing imports FastAPI
(`tests/test_desk_hounds_load.py` pins that).

Module map:

  roles      every system text, the stage graph, the hound definitions, the config document
  schemas    the report and decision answer shapes and their shape checks
  builder    the request file a subagent reads
  checks     one stage's answer through the shape check, the risk manager and the analyst's checker
  risk       the code risk manager (R1 to R5) and the persona rules
  state      a game's folder, attempts and stage states
  prepare    freeze a game (reuses the analyst packet builders)
  session    session-plan, session-check, session-status (the parent session's loop)
  publish    bets, transcript and disagreement table into the ledger
  ledger     evidence/hounds_desk_v1.jsonl rows
  grade      settle bets with the analyst's grading code
  disagree   the per-game "where they disagree" table
  cli        `python -m src.hounds.desk ...`
"""

PAPER_ONLY = True
