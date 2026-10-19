"""Interacting with a dog: fire it now, ask it questions, rate its calls, dress it, drill it.

Everything here is COMPUTED FROM DATA, never generated: no model is called, no network is touched. A dog's
answer is built from its own tickets, its rule, its record and the stored boards. Paper only; nothing in this
package places or suggests a real bet.

Modules (none of them imports FastAPI, so the CI harness that hides it can import them all):

  common    resolving a dog id to a user dog or a house dog, and reading its public numbers
  store     the two small tables this package adds to the app database: looks and feedback
  look      the locker room: the whitelist a dog's look is validated against
  fire      "What would you bet right now?": the dog's current rule over the latest stored boards, read only
  manual    the owner's manual pick: its own ledger, never counted in the dog's rule record
  ask       "Ask your dog": an intent matcher and answer builders over the dog's own data
  drill     the hindsight drill: a dog's rule replayed over the last 7/14/30 days, never counted
  camp      what the Training camp page shows a signed-in owner
"""
