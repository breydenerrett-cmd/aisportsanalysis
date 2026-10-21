"""LineHound's AI layer: one router, strict JSON out, a hard spend cap, and nothing that can fabricate.

WHAT IS HERE
------------
  router.py    the provider router: config, adapters, the append-only usage store hookup, the paid
               cap, quota cooldowns, the "no answer" outcome. ``Router.ask`` is the one door.
  usage.py     the append-only usage store (one JSON line per call) and the aggregates read from it.
  schema.py    a small JSON-schema checker and the one function that pulls a JSON object out of a
               model's text. Stdlib only; no ``jsonschema`` dependency.
  decision.py  the bet/pass answer a hound asks for: its schema, its semantic checks, its prompt rules.

OWNER DECISION, 2026-10-20 (the stance this package is built around)
--------------------------------------------------------------------
Claude Haiku 5.5 (``claude-haiku-5-5``) is the one enabled model, under a hard monthly dollar cap in
code (``AI_PAID_CAP_USD``, default 5). The router is written for several providers (an ordered list,
per-provider daily caps, cooldowns) so a second model is a config entry plus one adapter class, not a
rewrite; the free-tier adapters (Gemini, Groq, OpenRouter) and the local one (Ollama) were deliberately
NOT written until the owner switches a second model on. Nothing here is imported by the capture
slot, the card, or any page: the only caller is the AI hound runner (``src/hounds/ai_runner.py``).

WHAT THE LAYER NEVER DOES
-------------------------
  * send anything about a person: a prompt carries game and market data and rule text only, and the
    router refuses a prompt that looks like it holds an email, a phone number or a secret;
  * invent an answer: a provider that fails, times out, is over quota or returns something that does
    not validate produces "no answer", and the caller passes;
  * spend past the cap: the check runs before the call, on the worst case the call could cost;
  * touch the network in a test: transports and the Anthropic client are injected.
"""
