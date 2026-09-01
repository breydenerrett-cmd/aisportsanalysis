> **AUDITED AT SHA `3dca767`. NOT CURRENT-PRODUCTION TRUTH.**
> Branch HEAD at push time was `cfe6bcb` (5 commits later, incl. a canvas-first frontend
> rebuild). Parent must reconcile against current HEAD before treating findings as
> authoritative. Two findings are already confirmed superseded — see
> `RECONCILIATION_REQUIRED.md`. No finding has been weakened or removed.

# LINEHOUND V2 — Master Design Plan

## 1. PRODUCT FEEL
"Opening a sports game built for bettors." Broadcast pregame energy, tactile controls,
team-color environments — carrying real, honest market intelligence. Premium and warm,
never neon-casino, never dark-SaaS. Usefulness always wins over spectacle.

## 2. VISUAL HIERARCHY (universal rule)
Every screen resolves in this order:
  1 WHERE AM I      → team environment / screen identity, largest element
  2 WHAT MATTERS    → the one thing worth knowing, stated as a sentence
  3 THE PRICE       → a price bug with real gravity, owned by a side
  4 WHAT CAN I DO   → one primary action, visually welded to the price
  5 WHAT CHANGED    → cyan, timestamped, always secondary until it isn't
  6 EVIDENCE        → icon + label + value + one sentence
  7 RAW DATA        → behind Advanced only

## 3. NAVIGATION
Desktop: left icon rail (TODAY · GAMES · CHECK · ODDS · BETS). Active item is an angled
slab that breaks the rail edge — a shape, not a tint. Back links read "← GAMEDAY", never
browser-back reliance. Date rail heads slate screens.
Mobile: bottom tab bar, same five, active carries a lit top edge and raised panel.
Sticky: on Bet Check and Game, the price+action bug pins to the bottom on scroll.

## 4. MOTION GRAMMAR  (all disabled under prefers-reduced-motion)
  seam-sweep        light travels the diagonal seam, 11s loop, ambient
  matchup-swap      outgoing environment wipes along the seam angle, 420ms, incoming
                    team colour blooms from its own edge — the signature transition
  price-arrival     price bug rises 16px + brightness .92→1, 340ms, lands last
  price-change      brief 2-beat pulse on the changed digit only, 220ms
  lean-reveal       comparison rows stagger 60ms, the LEAN chevron draws last
  advanced-expand   height + 12px rise, 380ms, Quick View stays put above
  rail-select       active slab slides between items, 240ms
  tile-focus        slate tile lifts 4px, team gradient bar brightens, 180ms
  chart-draw        movement curve draws its own path on entry, 900ms
  connector-cue     narrative connector labels fade in as the next section enters view
Easing: cubic-bezier(.16,.84,.3,1) for entrances, (.4,0,.2,1) for loops.

## 5. TYPOGRAPHY — four roles, no more
  DISPLAY/MATCHUP  condensed italic, very large, tight tracking — team names, screen titles
  PRICE/DATA       mono, tabular, large — every odds figure, every timestamp
  NAV/LABEL        small caps, wide letterspacing, low contrast
  BODY             humanist sans, readable, used for the one sentence per idea

## 6. COLOR
  ground     neutral warm-graphite near-black (no brown, no navy)
  team       supplies environmental light per matchup — the only large colour areas
  cyan       analytical / live / changed / freshness / the LEAN indicator
  hot red    RESERVED: a genuinely better price. Nothing else, ever.
  amber      caution / pending / not-yet-available — distinct from red
  no other accents. No rainbow status systems.

## 7. COMPONENT LANGUAGE
matchup hero · team seam · scorebug column · price bug (+ welded action tab) ·
book comparison rack · odds cell (tappable) · status chip · slate tile · date rail ·
wager ticket · evidence row · comparison row w/ LEAN · warning row · change timeline ·
bottom-line module · advanced stat block · nav rail · mobile tab bar · free-check meter ·
locked/member state · signup card · access-code entry · empty/loading/error primitives

## 8. SCREEN MAP
PUBLIC   Landing (d/m)
APP      Gameday (d/m) · Game Quick (d/m) · Game Advanced (d/m) · Bet Check (d/m) ·
         Odds Board (d/m) · My Bets (d/m)
ACCOUNT  Signup/Founding Access (d/m) · Sign In/Access Code (d/m) ·
         activation-code-shown-once · waitlisted · checkout-return-failed ·
         signed-out-in-view · access-paused (expired)
STATES   loading · empty · stale · unavailable · locked · free checks remaining ·
         free checks exhausted · data failure · no warning exists · no change exists

## 9. CUSTOMER LOOP
Landing → try a check → free check → Gameday → pick matchup/price → Game Quick →
(Advanced) → Bet Check → compare books → case/risk/change → save → My Bets → convert.
Every price everywhere is an entry point into Bet Check, pre-filled.

## 10. RESPONSIVE
390px designed on its own terms. Seam goes horizontal; halves stack; slate becomes a
horizontal rail with the next tile edge visible; comparison table keeps all three columns;
book rack goes 2-up; primary action goes full-width and sticky.

## 11. DESIGN ACCEPTANCE — I must be able to answer YES to all
- Does the screen answer where/what/next/changed on sight, without reading?
- Is there exactly one primary action, and is it attached to the thing it acts on?
- Does hot red appear ONLY on a genuinely better price?
- Does every rate carry its sample size?
- Is every unavailable thing stated, never estimated?
- Would a bettor call this a sports product, not a dashboard?
- Is the 390px version designed, not shrunk?
- Does motion direct attention, or merely decorate?
