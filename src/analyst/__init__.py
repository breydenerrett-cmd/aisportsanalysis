"""The AI analyst: a model-written analysis of every game, frozen before first
pitch and graded in public.

Four steps, one module each, run in this order and never skipped:

    packet.py   freeze every fact the model may use into one hashable packet
    analyst.py  ask the model for a call on every market the packet prices
    critic.py   strike or downgrade any call the packet does not support
    ledger.py   publish what survived (hash-chained) and grade it afterwards

The UFC analyst is the same four steps for fights, sharing the model call, the spend
meter and the critic and adding its own packet, prompt, grader, ledger and CLI:

    ufc_packet.py   one fight packet from the UFC data layer's matchup sheet
    ufc_analyst.py  the fight prompt and vocabulary over analyst.py and critic.py
    ufc_grading.py  moneyline, method of victory and rounds total from bout results
    ufc_ledger.py   evidence/analyst_ufc_v1.jsonl, its own chain and record
    ufc_cli.py      `--sport ufc`

Each analyst's record is its own. None is merged into the card record or into another
analyst's, and none changes a card rule, gate, pick or published result. Nothing in this
package places a bet or can.

THE SIDE-BY-SIDE TEST OF THE SITUATION LAYER (docs/SITUATION_LAYER.md). Everything above is arm A,
the analyst that reads the matchup statistics, and is unchanged. Arm B is the same analyst plus the
situation layer (src/situation/), frozen into its own ledgers, off unless config/analyst.json says
`situation_arm.enabled`:

    situation_prompt.py   the four rules "THE SITUATION" adds to each prompt (no imports)
    situation_arm.py      the arms: prompts, files, the switch
    compare.py            `analyst compare`: arm A against arm B by sport and market family
"""

LABEL = ("Written by an AI model from the data on this page. Unproven. "
         "Analysis, not advice.")

# The label on a brief written in a supervised session (src/analyst/pilot.py): a person ran a Claude
# session, which wrote the answer from the exact request the API would have been sent, and the same
# validation, checker and ledger published it. The words say who wrote it and how, because the
# difference is the thing a reader should know. Served by the API; the page never writes its own.
PILOT_LABEL = ("Written by an AI model in a supervised session, from the data frozen before the game. "
               "Unproven. Analysis, not advice.")
