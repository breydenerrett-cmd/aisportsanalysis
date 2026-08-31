"""Analysis layer: derived, read-only views over the point-in-time stores.

Modules here consume the same audited inputs the research layer uses -- the
pitch store, the posted-lineup store, the handedness cache -- and reshape them
into plain-dict briefing sections. Nothing in this package touches the
network, writes a store, or fits anything: it observes, attaches the sample
behind every number, and says so explicitly when it cannot.
"""
