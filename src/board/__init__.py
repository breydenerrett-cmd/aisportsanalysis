"""The universal record: market identity, canonical shapes, settlement rules.

Everything in this package is pure data and pure functions -- no I/O, no
clock, no network. It exists so that a probability (what a system believes)
and a price-derived quantity (what the market is offering) are represented as
distinct, non-interchangeable types from the moment a line is captured.
Conflating them upstream is how a research system quietly turns into a
price-chasing one; see docs/planning/design-data-first.md and
docs/ARCHITECTURE_BETTING_ENGINE.md sections 3-4 for the contracts this
package implements verbatim from synthesis-judge.md section 4.2.

Importing this package registers the player-prop settlement rules
(src.board.settle_props.register_all) into the shared registry owned by
src.board.settle, so that any catalogue lookup against
src.board.settle.SETTLEMENT_RULES sees a real callable for prop markets
without every caller having to remember to import settle_props itself.
register_all() is idempotent, so this is safe under repeated import and
under any other module calling it directly too.
"""

from src.board import settle_props as _settle_props

_settle_props.register_all()
