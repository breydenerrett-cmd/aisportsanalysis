"""The AI analyst: a model-written analysis of every game, frozen before first
pitch and graded in public.

Four steps, one module each, run in this order and never skipped:

    packet.py   freeze every fact the model may use into one hashable packet
    analyst.py  ask the model for a call on every market the packet prices
    critic.py   strike or downgrade any call the packet does not support
    ledger.py   publish what survived (hash-chained) and grade it afterwards

The analyst's record is its own. It is never merged into the card record and it
changes no card rule, gate, pick or published result. Nothing in this package
places a bet or can.
"""

LABEL = ("Written by an AI model from the data on this page. Unproven. "
         "Analysis, not advice.")
