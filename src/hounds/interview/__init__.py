"""Interview a bettor, build a hound: a structured conversation that ends in a user_spec-valid paper hound.

THE SHAPE
---------
  topics      the eleven questions, their order, and the form controls each one carries
  privacy     emails, phone numbers and keys are removed from text BEFORE it is stored or sent to a model
  classify    phrases the hound language cannot run (live bets, injuries, parlays ...), found by rule
  fields      every candidate value checked against the user_spec menu, never repaired
  conditions  a "skip when ..." clause turned into the exact opposite condition, or refused
  extract     the Haiku extractor (strict JSON, via src/ai/router) and the deterministic form fallback
  derive      answers -> clarifications, can't-automate list, rules and a validated spec (a pure function)
  machine     the state machine: apply an answer, apply a clarification, say what comes next
  record      the strategy record, its canonical JSON and freeze_hash, and the confirmation summary
  history     optional dated history, kept as "claimed, unverified" and nothing more
  store       the three sqlite tables (sessions, records, claimed history), additive only
  service     the operations the API calls: start, answer, resolve, review, confirm

THE ORDER OF TRUST (the same as src/hounds/english)
---------------------------------------------------
A model may PHRASE a question and PROPOSE candidate fields. It never builds a rule: its candidates are
checked field by field against the menu, its restated triggers are read by the deterministic English parser,
and the spec that results goes through `user_spec.validate_spec` like any form post. When the model is capped,
cooling down or wrong, the same questions are asked as a plain form and the same spec comes out.

NOTHING SAVES UNTIL THE PERSON CONFIRMS. Confirming creates one hound through the existing create path
(`user_store.create_hound`, free-tier limit included). It is a paper hound that bets forward only, like every
hound; the strategy record calls that status `shadow`.

PAPER ONLY. Nothing here places or suggests a real bet, and nothing here says a described strategy wins.
"""
