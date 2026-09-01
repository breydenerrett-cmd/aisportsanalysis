# Design request — Track 2 screens (for the Claude Design session)

2026-09-01. The forensic audit of the frozen v1 handoff confirmed the
SCREEN INVENTORY covers 9 screens (Landing d/m, Gameday d/m, Bet Check
d/m, Game Quick, Game Advanced, Game mobile). Four customer surfaces the
product ships were NEVER designed and are currently blocked from
implementation until full desktop + 390px artboards exist, using the
existing frozen design system (tokens, type ramp, chamfer geometry,
reserved-color rule, state primitives, content rules) and product
vocabulary. Nothing here re-opens the frozen system; these are additions
inside it.

## 1. Odds / Market Board  (route #/odds)

What the data supports (docs/API_CONTRACTS.md, GET /odds/{date}): per
game, per market (moneyline; spreads/totals captured), one row per book
(8–11 US books), each with price + book_last_update; freshness metadata
(observed_utc, stale/age_seconds); MARKET-IMPLIED CONSENSUS per side;
best-available flagged. Design needs: the whole-slate board (game rows ×
books), per-game expansion, the best-price treatment under the
reserved-color rule (hot red ONLY where a better price exists), staleness
display, empty/error/loading states per the spec's per-screen-states
pattern. No EV/edge language; price improvement is line-shopping value.

## 2. My Bets  (route #/mybets)

Data: user-saved bets (game, side, price, saved_at), settlement
(won/lost/push + settlement_reason + settled_at, or honestly unsettled),
and the paper-trail idea from the Landing ("every check leaves a paper
trail"). Design needs: save-a-bet entry (game/side/price — today a raw
form), the list with settlement states, empty state for a new user. No
ROI/record aggregation claims beyond what settlement data supports.

## 3. Signup / conversion  (route #/signup, arrival from Landing CTA)

Flow (already built and tested backend-side): email → POST /signup →
either Stripe Checkout redirect (checkout_url) or "waitlisted"; after
Stripe returns, GET /signup/complete surfaces a ONE-TIME activation
token the customer must copy (second retrieval refused — that urgency
must be designed, not buried); then into the app. Price $19.99/mo
Founding Access; 3 free Bet Checks total (lifetime) as the free path;
21+ / responsible-gambling presence per docs/legal drafts. Design needs:
signup page d/m, waitlisted state, the activation-token handoff screen,
and the checkout-return error state.

## 4. Sign-in / auth / unauthenticated states  (interim #/signin exists,
undesigned)

Mechanics that must survive: a customer holds a bearer token (invite or
activation); enter/save/clear; 401 state on any app screen (currently
raw API text — must become designed customer copy with technical detail
demoted); 402 subscription-expired state linking to billing/reactivate.
Design needs: sign-in screen d/m, the in-view signed-out state, the
expired-subscription state.

## Binding constraints for all four

- Frozen system only: tokens/type/chamfers/motion/states from
  "LINEHOUND Design System Handoff.dc.html"; rail already contains ODDS
  and BETS items.
- Content rules: every rate carries its sample size; NOT YET AVAILABLE
  over estimates; never a row of zeros — a sentence instead; six-word
  label ceiling; no picks implied anywhere; in-app COMPARE only, no
  external sportsbook links in beta.
- Deliverable per screen: full high-fidelity desktop + 390px artboards
  plus empty/error/loading states and motion notes, added to the frozen
  handoff files (or a v1.1 sibling), so implementation can trace, not
  interpret.
