# Capability reconciliation for V2 design (vs CURRENT HEAD)

2026-09-01/02. Requested by Brey after the Design lane's 10-agent audit
(performed against 3dca767 — a capture commit that PREDATES the entire
Track 1 canvas-first rebuild, the entitlement work, and the free-check
tier, so stale findings are expected). NOTE: the audit's own artifacts
(v2/CAPABILITY_LEDGER.md and siblings) are NOT present on any reachable
remote branch as of this writing — this document is the ground-truth
half, built from CURRENT HEAD's code, live API contracts, and real
stores. UPDATE 2026-09-02: the ledger landed (design/linehound-v2/,
commit f0bc637); the authoritative per-finding adjudication is
design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md, which
supersedes this file where they differ.

Classes: A available now on the customer API · B exists internally,
not exposed · C safe deterministic presentation derivation · D not
available, must not be shown as live · E demo/sample only, must be
labeled · F audit finding stale, already fixed since 3dca767.

## THE PRIMARY BEHAVIORAL FACT (Design must build around this)

**`verdict: no_play` is the dominant real product state — 93%.**
Forward ledger, all recommendation entries since forward tracking began
(n=129, through 2026-09-01): no_play 120 (93.0%), flagged 3 (2.3%),
market_unavailable 6 (4.7%). Bet Check findings arrays are likewise
usually empty and blocks 05/06/08/09 usually NOT YET AVAILABLE on a
real game. This is not an edge case or a data problem: it is the
honesty engine working (27 pre-registered hypotheses, zero survivors).
V2 must design no_play/quiet as the HERO state — the canvas's own
"quiet slate keeps the hero geometry" rule generalized everywhere —
with price context (always real) carrying the visual weight.

## Capability matrix

| Capability | Status | Evidence (current HEAD) | V2 design action | Eng action |
|---|---|---|---|---|
| Full club display names | **C** | Payload carries abbreviations (`game.away_team = "SD"`, verified live); MLB club abbrev→display-name is a fixed 30-row mapping | Design to full names freely | Ship static name map beside web/js/teamcolors.js when V2 wants it |
| Team colors | **C** (shipped) | web/js/teamcolors.js — static 30-club map, luminance-guarded accents | Keep | none |
| Team records | **A** | dossier `teams` section: `away_wins`/`away_games_played` (73/138 → "73-65"), plus last-5/last-10 splits, home/away win pct — all with samples | Show; every rate keeps its n | none |
| Probable starters | **A** | `game.away_probable`/`home_probable` (+ids) from the free schedule; absent when unannounced — design the absent state | Show w/ absent state | none |
| Starter handedness | **B** | handedness cache exists (src/analysis/matchup.py) but only reaches the payload inside matchup-depth when a lineup is posted; no standalone field | Only inside matchup context; else NOT YET AVAILABLE | Expose a field only if V2 needs it standalone |
| Lineups | **A** (when posted) | rosterwatch + `lineups_by_pk` → matchup depth; before posting: honest absence | Design both states; posting time ~hours pre-game | none |
| Bullpen context | **A** (when built) | bullpen log pipeline feeds dossier; absent → "bullpen workload not built" verbatim | Show with absence state | none |
| Weather | **D** (seam exists) | `build_slate(weather_by_pk=None)` — a seam, but NOTHING supplies it on the customer path; Advanced honestly renders "weather not fetched" | Remove live-weather claims or mark NOT YET AVAILABLE | Optional future provider |
| Venue | **A** | `game.venue` ("Great American Ball Park"), roof/altitude in context section | Show | none |
| Sportsbook count | **A** | multibook boards: 8–11 US books per game, real count per board (`n = 11 books`) | Always show the real N, never a fixed "11" | none |
| Consensus calc | **A** | src/analysis/prices.py de-vig; surfaced as probability + implied price | Label MARKET-IMPLIED CONSENSUS, never "true" | none |
| De-vigged consensus | **A** | same; the struck-through figure is de-vigged (NOT vig-inclusive — differs from the V1 canvas's implicit framing) | Note in copy if juxtaposed with raw prices | none |
| Best-price logic | **A** | per-side best across the board, book named | Show | none |
| Price-improvement calc | **A** | improvement_points / improvement_return_pct; genuinely-beats-consensus is RARE (money pill mostly absent) | Design pill-absent as default | none |
| Odds freshness/age | **A** | observed_utc, age_seconds, stale flag; board age in shell status | Show; stale styling | none |
| Line-movement timestamps | **B** | hourly+dense snapshot history exists in stores (movement CLI reads it) but NO customer endpoint serves a price series | Chart stays NOT YET AVAILABLE (V1 handled honestly) | Build a series endpoint only if V2 commits to the chart |
| Sportsbook outbound URLs | **D** (policy) | Brey ruling: beta is in-app COMPARE only; no compliant deep-link strategy | Remove OPEN AT BOOK from V2 | none |
| What Changed | **A** | relevance-scored roster events, tiers, timestamps, "not an edge" framing; market-reaction arrows NOT available (see line movement) | Keep; no reaction arrows | see series endpoint |
| Bet Check findings | **A**, usually empty | contract fields real; thesis/counterargument often the honest null lines; blocks 05/06/08/09 usually NOT YET AVAILABLE | Empty-first design (see PRIMARY FACT) | none |
| WATCH OUT | **D** as a distinct feed | no watch_out field exists; the role is served by counterargument_lines + gaps (real) | Rename/merge into counterargument+gaps; never a fabricated concern | none |
| Editorial Bottom Line | **A** | server-composed bottom_line from real facts (price delta, evidence status); never a pick, recommendation permanently null | Render verbatim; no client editorializing | none |
| Signup behavior | **A** | POST /signup → {checkout_url} or {waitlisted}; GET /signup/complete one-time activation token (second retrieval refused) | Design both branches + token urgency (Track 2 brief) | none |
| Stripe vs waitlist | **A** | Stripe TEST live on staging (Launch Ops); unset config → honest waitlist | Design waitlist state too | none |
| Auth/signin/access-code | **A** functional, **undesigned** | bearer invite/activation token; 401/402 structured; interim #/signin | Track 2 designs it | none |
| Free-check state | **A** (live-verified) | POST /betcheck/free: 3 lifetime, remaining/limit in every 200, 402 exhaustion → signup, X-Free-Check-Token; verified on staging (2 of 3 after QA spend) | Design counter + exhaustion wall | none |
| My Bets | **A** (narrow) | save {game, side, price}; auto-settlement vs finals (won/lost/push + reason); NO auto price attach, NO odds lookup at save time, record line derived from settlements only | Design to exactly this; no implied tracking beyond it | none |
| DEMO/SAMPLE chips | **E rule inverted** | staging runs LIVE captured data — sample chips would be a lie; they appear ONLY if data is actually sample | Chips conditional, not default | none |

## V1 data-honesty note (Track 1 baseline)

Visual fidelity and data honesty were graded separately. One shipped
data-honesty defect WAS found by the V2 audit and is fixed as of this
reconciliation: pricing/landing copy promised a 7-day refund (policy
forbids promising one), "one click" cancel (no in-app cancel UI), and
an instant confirmation email (no email system) — all three claims
removed. Beyond that, Track 1 as shipped is clean: it already renders
NOT YET AVAILABLE for the line-movement chart, omits absent records/
pitchers rather than inventing them, suppresses the money pill when no
side beats consensus, shows the real book count, and labels the
consensus MARKET-IMPLIED. The V1 CANVAS (not the implementation)
over-promised in three places, inherited by any audit of the artboards:
the movement chart (B), OPEN AT BOOK (D by policy), and sample-data
chips as default chrome (E rule). Those are design-contract corrections
for V2, not implementation regressions.

## For the Design lane

This file is the reconciled capability contract. Anything marked A can
be designed as live; C may be derived; B needs an engineering request
BEFORE the artboard commits to it; D/E must not appear as live data.
Push v2/CAPABILITY_LEDGER.md to the branch and the per-finding A–F
adjudication (incl. F/stale calls against 3dca767) will be appended.
