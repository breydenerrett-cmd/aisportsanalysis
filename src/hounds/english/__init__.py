"""Plain English in, plain English out, for user-built hounds.

  parser     free-text strategy  ->  a version-2 spec draft + which clauses were and were not understood
  render     any spec            ->  the plain sentences a stranger can read (and a diff between two specs)
  jobs       the translation-job table for phrasings the parser cannot fully read
  translate  the Zapier round trip: build the request, check what comes back

The order of trust is deliberate. The deterministic parser handles the common phrasings instantly and
for free. Whatever it cannot read goes (only when the owner has switched it on) to a model on the
owner's Zapier account, whose answer is UNTRUSTED text: it is cut down to the fields on the menu and
validated like a form post. Either way the result is shown back to the person as sentences and rule
cards to confirm and edit; nothing a parser or a model produced is saved without that.

No Anthropic API is called from here.
"""
