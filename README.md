# AI Sports Analysis

An AI-generated sports-betting brief product: model-derived edges explained
in plain language, with a public, honest record of results.

## Origin

This repo starts from a Cowork session that produced a hand-assembled MLB
game brief and then honestly audited it. The audit is the actual product
spec — see:

- [`docs/product-teardown-and-build-plan.md`](docs/product-teardown-and-build-plan.md) —
  what worked, what's a blocker, the five-layer architecture (data → model →
  edge → narrative → ledger), competitive landscape, pricing, legal
  considerations, and a 90-day build plan.
- [`docs/sample-brief-dodgers-braves-2026-08-27.md`](docs/sample-brief-dodgers-braves-2026-08-27.md) —
  the reference example of the target output format that the teardown
  critiques.

**Key takeaway from the teardown:** the sample brief was a well-written
argument, not a model — no projection engine, no fair price, no closing-line
tracking. The actual product is the join of a real edge (Monte Carlo
simulation + licensed odds) and a narrative layer that explains it plainly,
backed by a public CLV ledger. Build order: data + model + ledger first,
prove the model beats the closing line for 4–6 weeks with no UI, before
building any customer-facing surface.
