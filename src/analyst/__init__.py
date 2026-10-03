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
"""

LABEL = ("Written by an AI model from the data on this page. Unproven. "
         "Analysis, not advice.")
