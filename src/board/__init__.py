"""The universal record: market identity, canonical shapes, settlement rules.

Everything in this package is pure data and pure functions -- no I/O, no
clock, no network. It exists so that a probability (what a system believes)
and a price-derived quantity (what the market is offering) are represented as
distinct, non-interchangeable types from the moment a line is captured.
Conflating them upstream is how a research system quietly turns into a
price-chasing one; see docs/planning/design-data-first.md and
docs/ARCHITECTURE_BETTING_ENGINE.md sections 3-4 for the contracts this
package implements verbatim from synthesis-judge.md section 4.2.
"""
