> **AUDITED AT SHA `3dca767`. NOT CURRENT-PRODUCTION TRUTH.**
> Branch HEAD at push time was `cfe6bcb` (5 commits later, incl. a canvas-first frontend
> rebuild). Parent must reconcile against current HEAD before treating findings as
> authoritative. Two findings are already confirmed superseded — see
> `RECONCILIATION_REQUIRED.md`. No finding has been weakened or removed.

# V2 CORRECTION — to paste into the Claude Design session

The engineering repo has been read end-to-end and adversarially verified at HEAD 3dca767.
A large part of what LINEHOUND v1 and my first V2 brief showed is NOT PRODUCIBLE by the
real system. Correct the V2 file against this. Designing the real system beautifully is
the job; inventing a better one is not.

## DELETE FROM EVERY SCREEN — these are fabrications
- Club names. "PITTSBURGH PIRATES" / "BREWERS" do not exist on the wire. Teams are
  ABBREVIATIONS ONLY — PIT, MIL, NYY. There is no display-name map and no logos.
  Make the abbreviation the display identity — it suits the HUD language.
- Team records (68-66). Not available.
- Starters (Skenes RHP), lineups, bullpen, weather, travel, splits, matchup history,
  arsenals, news. All 12 are NAMED GAPS on the API, each with its own reason string.
- "BEST OF 11 BOOKS" / any fixed book count. Measured range is 2–11; median 8;
  6.5% of instants sit below the 6-book consensus floor. Say the count you actually have.
- "UPDATED 32 SEC AGO" on Bet Check. That payload has NO age field at all. Capture is
  hourly; a live board measured 43 minutes old. Never show a freshness number there.
- "1.5 PTS BETTER" as a hero number. The cents delta is prose inside bottom_line only,
  not a field. Price improvement carries a MANDATORY label and is NEGATIVE ~80% of the time.
- "OPEN AT BETRIVERS" / any sportsbook link. No URL field exists on any price object.
  There is no bet-placement endpoint, ever.
- Book display names. Raw provider keys only: fanduel, williamhill_us, betonlineag,
  draftkings, betmgm, bovada, lowvig, fanatics, mybookieag, betrivers, betus.
- An editorial BOTTOM LINE. bottom_line is mechanically composed from a finding count,
  a price clause and a permanent disclaimer. "The pitching argument is real, the price
  is not" CANNOT be produced.
- LIMITED / MODERATE / STRONG historical support. Wrong word set AND unreachable —
  max reachable evidence tier is 1.
- Grouping evidence under a team. Side is a POINTER, not a subject: a sentence opening
  "NYY's starter…" can legitimately sit in the counterargument for an NYY bet.
  Group ONLY by thesis_support / counterargument arrays.
- A #/signin screen. The route does not exist. The entire mechanic is a topbar token
  field with Save / Clear.
- My Bets book pickers, game pickers, edit actions, record/ROI/units/win-rate.
- "No card required", "cancel in one click", refund promises.

## MAKE THESE THE PRODUCT — they are real and they are strong
1. ZERO FINDINGS IS THE PRIMARY STATE, NOT THE EMPTY STATE. All 15 games return
   verdict "no_play" and findings []. The real headline constant is:
   "Interesting matchup, but no demonstrated betting edge."
   Design the beautiful version of THIS. It is what the customer sees every day.
2. ODDS IS THE RICHEST SCREEN IN THE PRODUCT — make it the centrepiece. It genuinely has
   per-book board rows (book, away_price, home_price, captured_at), best price per side
   WITH AN ARRAY OF ALL TYING BOOKS, de-vigged consensus with implied_probability,
   spread_cents (cents of disagreement between books, NOT a point spread), staleness.
   Three first-class board variants, all of which must be designed:
     A full board, consensus present — 42% of instants
     B thin board 2–5 books, consensus null WITH a reason present — live on 3 of 27 games
     C no board — board_available false, and consensus_unavailable_reason KEY IS ABSENT
   Slate summary is real: games_count, widest_spread_game, books_disagree_on_favorite_count.
   "Books disagree on the favourite" is a genuinely great, honest headline number.
3. THE GAP LEDGER IS THE ADVANCED VIEW. 4 sections (park, price_improvement,
   multibook_board, what_changed) and 12 gaps, each with a reason. Design the ledger as
   the primary surface — an honest map of what we know and what we don't. Replace the
   stat-vs-stat comparison table with a BOOK-vs-BOOK price comparison, which is real.
4. BET CHECK's real ten blocks. counterargument_lines is NEVER EMPTY by constructor;
   thesis_support CAN be empty — design that asymmetry. evidence_status is "Observation",
   the only reachable value. recommendation is permanently null. Every quantitative claim
   carries sample_n + sample_unit or the constructor REFUSES it — that refusal is the
   product, so show the sample next to every number.
5. MONEYLINE ONLY. 19 other markets are refused BY NAME — so the refusal can name them.
6. SIGNUP'S DEFAULT OUTCOME IS WAITLISTED. Billing provider defaults to "null", so every
   signup waitlists out of the box. All four outcomes are HTTP 200. Design the waitlist
   as a real, dignified destination that promises nothing — no email is actually sent.
7. THE ACTIVATION CODE IS SHOWN ONCE with no copy button today and no reconciliation
   path — route failures to support.
8. ONE 401 COVERS missing / invalid / expired / revoked deliberately. The UI CANNOT tell
   the user which. Do not design a "your code expired" state — design one honest state.
   Token TTL is 14 days. "Log out" is client-side only.

## VOCABULARY — use these exact values
verdict: "no_play" → "No demonstrated edge" (never "pass"/"avoid")
settlement_status: won / lost / push / void-unmatchable / three-nulls = not settled yet
  push → "Game ended tied"; void-unmatchable → "Can't match this bet to a game";
  unsettled → "Not settled yet" and NOTHING MORE — no reason exists
relevance tier: LOW / MEDIUM / HIGH / UNKNOWN — UNKNOWN sits OUTSIDE the order, it means
  "cannot characterize" and must never render as lowest or average as zero
evidence: observed/unproven → "Observation" (no badge); tested_null → "Tested — did not
  hold up" (badge); blocked → "Not available with our data"
not_an_edge — a verbatim string attached to every changed item; surface it, don't paraphrase
your_price_beats_consensus: true = the customer's price is BETTER
market_consensus.implied_probability is a FRACTION in (0,1), not a percent

## STATE NOTES THAT CHANGE LAYOUT
- Gameday default = 15 cards whose entire price content is board_summary
  {books, observed_utc, age_seconds, has_board}. That's it. Design for that.
- has_board false also means "club name unmatched" — say "no price board recorded for
  this game", never "no odds".
- No server staleness verdict. If you draw a stale threshold, draw it client-side at
  1800s and LABEL IT AS OURS.
- Odds ties: best.{side}.books is an ARRAY — render every tying book, never just one.
