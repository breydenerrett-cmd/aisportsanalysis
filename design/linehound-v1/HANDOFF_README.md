# LINEHOUND v1 — Frozen Design Handoff

These three `.dc.html` files are the FROZEN visual source of truth for the
LINEHOUND customer product, exported byte-for-byte from the finished Claude
Design project (2026-09-01) and verified identical to the originals at copy
time. Visual exploration is OVER. Engineering's job is to IMPLEMENT this
design, not to re-derive, reinterpret, simplify, or "improve" it.

The files are VISUAL REFERENCE, not production source. Do not copy their
markup wholesale into the app; build the real `web/` client to match what
they show, using the design-system spec below as the contract.

## What is in which file

| File | Contains |
|---|---|
| `LINEHOUND Gameday.dc.html` | Gameday desktop · Gameday 390px mobile · Bet Check desktop/mobile · Game Quick · Game Advanced · Game mobile |
| `LINEHOUND Landing.dc.html` | Landing desktop · Landing 390px mobile · final funnel structure · compliance/footer · $19.99 Founding Access presentation |
| `LINEHOUND Design System Handoff.dc.html` | 12-section implementation spec: 9-screen inventory, tokens, typography, spacing/geometry, components, nav, responsive behavior, motion, interaction states, screen states, content rules, implementation notes |

## Commercial facts the design encodes (do not drift)

- Launch price: **$19.99/month — Founding Access, cancel anytime.**
- Free offer: **3 introductory Bet Checks TOTAL** (lifetime — NOT per day).
- Launch sport: **MLB only.** No multi-sport UI yet.
- **LINEHOUND is the working brand**, pending final legal/trademark
  clearance — keep brand strings centralized and swappable.

## Implementation rules (verbatim, non-negotiable)

- Advanced APPENDS beneath Quick; never replaces it.
- Any displayed rate requires its sample size.
- WATCH OUT must never fabricate a negative finding; empty-state honestly
  when none exists.
- unsupported/missing data renders NOT YET AVAILABLE rather than
  estimated/faked.
- sample/demo data must be visibly labeled when applicable.
- price-improvement claims must remain mathematically verifiable.

These rules are product-integrity constraints, not styling suggestions: the
backend already behaves this way (honest 404s, `stale`/`age_seconds`
freshness metadata, empty counterarguments stated as such), and the UI must
preserve that honesty rather than paper over it.

## Viewing

Open any `.dc.html` file directly in a browser; each is a self-contained
multi-artboard canvas. `design/` is excluded from the Docker build context
(`.dockerignore`) — these files never ship in the staging image.
