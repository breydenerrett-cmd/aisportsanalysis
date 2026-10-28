"""Talk to your hound (owner request 2026-10-28): a real conversation in the studio's Ask tab, with Claude Haiku 5.5, saved per
member and hound lineage, where the hound can PROPOSE changes to its own rules and nothing changes until the member taps Apply.

  store.py      the two tables (messages, usage) in the app database: history that survives a reload, and the counts the limits read
  facts.py      what the hound is allowed to know (its rule, record, bets) as one block of text, and the system prompt that wraps it
  proposals.py  the tools the model may call, the checks every proposed change passes, and the diff card the member sees
  service.py    who may chat, the limits, one turn end to end, Apply and Cancel

The model call itself lives in ``src/ai/hound_chat.py``: ``src/hounds/interact`` is pinned to import no model client, so the Ask
tab's computed answers stay computed and this package sits beside it, not inside it. Nothing here imports FastAPI (the Linux CI image
has none); ``api/hounds_chat.py`` is wiring.
"""
