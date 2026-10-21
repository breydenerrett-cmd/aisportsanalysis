"""Interacting with a dog: unleash it, ask it questions, rate its calls, dress it, drill it, send it to training or
take it out back.

Everything here is COMPUTED FROM DATA, never generated: no model is called, and no network is touched but one
optional, fire-and-forget post of a training brief to the owner's own Zapier hook (``training.send_brief``). A dog's
answer is built from its own tickets, its rule, its record and the stored boards. Paper only; nothing in this
package places or suggests a real bet.

Modules (none of them imports FastAPI, so the CI harness that hides it can import them all):

  common    resolving a dog id to a user dog or a house dog, and reading its public numbers
  store     the two small tables this package adds to the app database: looks and feedback
  look      the locker room: the whitelist a dog's look is validated against
  fire      "What would you bet right now?" (the page calls it Unleash): the dog's current rule over the latest
            stored boards, read only
  manual    the owner's manual pick: its own ledger, never counted in the dog's rule record
  ask       "Ask your dog": an intent matcher and answer builders over the dog's own data
  drill     the hindsight drill: a dog's rule replayed over the last 7/14/30 days, never counted
  camp      what the Training camp page shows a signed-in owner
  rites     what the two owner rites share: who may do them and what the ledger says about open tickets
  outback   "Take them out back": the dog is buried, its record frozen and public, a headstone in the graveyard
  training  "Send to training": the dog studies its settled bets and comes back as a new version
"""
