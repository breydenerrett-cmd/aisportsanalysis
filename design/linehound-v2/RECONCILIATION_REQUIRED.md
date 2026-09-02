# ⚠ RECONCILIATION REQUIRED — read before using anything in this folder

**Audited SHA: `3dca767` ("Forward capture 21:01Z", 2026-09-01 21:01:38 +0000).**
**Branch HEAD when these docs were pushed: `cfe6bcb` ("Forward capture 23:02Z", 23:02:00 +0000).**

The capability audit in `CAPABILITY_LEDGER.md` was performed by a 10-agent adversarial
read against `3dca767`. **Five commits landed after that point**, including a substantial
frontend rebuild:

```
cfe6bcb  Forward capture 23:02Z
6348590  Staging verification record: byte-identical build, live free check; browser pass open
042cc69  Forward capture 22:01Z
de8a582  Forward capture 21:16Z (recovered: self-commit raced concurrent work)
2947aa8  Canvas-first rebuild: Gameday, Bet Check, Game views, shell -- VISUAL PASS
```

**This ledger is NOT current-production truth. It is a point-in-time audit.**
Parent engineering must reconcile it against current HEAD before any finding is treated
as authoritative. Nothing in it has been weakened or deleted — findings are preserved
with their `file:line` evidence exactly as audited.

---

## Findings ALREADY CONFIRMED SUPERSEDED at `cfe6bcb`

I re-checked two disputed items myself before pushing. Both have changed. The original
findings are left intact in the ledger; these supersessions sit on top of them.

### 1. "`#/signin` does not exist" — SUPERSEDED ✗
Audited as: *"The screen does not exist. `grep -rn "signin" web/ api/` → zero hits."*
**At `cfe6bcb` it exists** as a deliberate interim screen:
- `web/js/signin.js` — INTERIM invite-token screen (its own docstring says it is not a
  designed screen)
- `web/css/app.css:336-357` — `.signin`, `.signin__panel`, `.signin__title`,
  `.signin__body`, `.signin__field`, with a 899px breakpoint
- `web/README.md:21-22, 53` — documents it as interim, holding the invite-token mechanics
  that previously lived in the topbar

**Design consequence:** the V2 Auth work should target this real interim screen rather than
the topbar-only mechanic the ledger describes. The *customer-language* translation in the
ledger (access code, LET ME IN, one honest 401 state) remains valid and still applies.

### 2. "`/betcheck/free` exists and no client calls it — largest commerce gap" — SUPERSEDED ✗
Audited as: *"`POST /betcheck/free` exists (`api/betcheck.py:283`) and no client calls it."*
**At `cfe6bcb` it is wired:**
- `web/js/betcheck.js:619` — `apiFetch("/betcheck/free", …)`
- `web/js/betcheck.js:37` — "…/betcheck/free, which is open and capped at three
  introductory checks"
- `web/js/api.js:51` and `web/README.md:56` — "POST /betcheck, or POST /betcheck/free
  when signed out"

**Design consequence:** the free-check path is real. The free-checks-remaining and
free-checks-exhausted states are now designable against a live mechanic.

### Spot-checked and still appears to HOLD at `cfe6bcb`
- **No display-name map.** `git grep -ln "TEAM_NAMES|BOOK_NAMES|displayName|bookLabel"
  FETCH_HEAD -- web/js` → zero hits. Teams are still abbreviations; books are still raw
  provider keys. This remains the cheapest, highest-value frontend gap.
- Nav rail is unchanged: TODAY · GAMES · CHECK · ODDS · BETS (`web/js/main.js:48-52`).

---

## What Parent should return

A reconciled contract stating, per finding, one of: **STILL TRUE** / **SUPERSEDED (with
the commit and file:line)** / **NEVER TRUE (with evidence)**. Priority order — these are
the findings that most change what gets built:

1. Are `findings: []` / `verdict: "no_play"` still universal on the live slate?
2. Are the 12 dossier gaps still gaps, or has enrichment been threaded into
   `briefing.build_slate`?
3. Are teams still abbreviation-only on the wire, and books still raw provider keys?
4. Does Bet Check still have no age/freshness field?
5. Is `DEFAULT_BILLING_PROVIDER` still `"null"` (i.e. does every signup still waitlist)?
6. Do the three odds board variants (full / thin-with-reason / absent-key) still hold?

---

## Artboard count reconciled: 38, not 35

`LINEHOUND V2 Full Product.dc.html`'s own footer (line 7896) states "38
ARTBOARDS · 10 FAMILIES · 2 VIEWPORTS"; the freeze commit's "35" undercounts
by 3. Both numbers are internally consistent once you know why: 35 is the
count of numbered artboard SLOTS (V2-01 through V2-35), but slot V2-01
(Gameday) alone contains FOUR physical canvas frames instead of one — the
carousel artboard (V2-01, line 1126) plus three dedicated verdict-state
artboards under its own "V2-01a · b · c · THE VERDICT FAMILY" heading (line
2090): V2-01a NO_PLAY · 93.0% (line 1674), V2-01b FLAGGED · 2.3% (line
1881), V2-01c MARKET_UNAVAILABLE · 4.7% (line 1982). No other numbered slot
carries a lettered variant. 35 slots + 3 extra lettered artboards under
slot 01 = 38 physical artboards, matching the canvas's own count exactly.
Full per-artboard detail (title, line range, viewport, fields, tier) is in
`IMPLEMENTATION_MANIFEST.json`; build order and file ownership is in
`IMPLEMENTATION_PLAN.md`.

## V2 design work continuing WITHOUT waiting on reconciliation
Valid regardless of the disputed capabilities: the visual system and tokens, navigation
and motion language, layout and composition, the zero-findings / no-play experience,
unavailable-data treatment, responsive behaviour, and customer-language translation.

**Held until the reconciled contract returns:** capability-dependent final copy and any
data module whose fields are in dispute.
