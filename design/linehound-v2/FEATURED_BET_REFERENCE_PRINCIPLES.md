# Featured-bet reference — principles extracted (nothing copied)

Reference: a premium player-prop card. Used for composition and hierarchy only.
Its branding, typography, colour system, graphics and photography are NOT adopted.

## TAKE — composition principles

1. **Featured hero, subject-as-environment.** The subject bleeds off the left edge at
   large scale and is treated as environment, not as an avatar in a circle. The card is a
   *poster for one wager*, not a row in a table.
2. **Spine label.** A rotated label down the left edge names the card type at a glance
   ("PLAYER PROP"). Cheap, distinctive, and it makes a stack of cards scannable.
3. **Spec strip — the bet's identity in one scannable row.** STAT | LINE | PICK as three
   columns with hairline dividers, the chosen side as a filled pill. A user reads *what
   the bet is* in under a second, separately from *how good it is*.
4. **The rating is the loudest single element.** Oversized numeral, right-aligned, with a
   track beneath it. Deliberately louder than the bet itself — the card's job is the read.
5. **State-driven accent.** The rating's value drives the whole card's colour — border,
   pill, icon, trend mark all shift together. One state, expressed everywhere.
6. **Trust strip.** Three icon + label + sub items across the footer.
7. **Ambient sport environment** behind the content — depth, not decoration.

## REFUSE — and why

| Element | Why refused |
|---|---|
| **"MODEL CONFIDENCE 57%"** | A literal probability. The contract's HARD PROHIBITIONS list confidence scores and win probabilities; `recommendation` is permanently null with a raising `__post_init__`. We have no calibrated model. |
| **"RECOMMENDED PICK"** | We never recommend. Structurally impossible to produce. |
| **COLD → HOT axis** | Frames the reading as *how much should I bet this* — a recommendation by another name. Our axis must describe evidence and price standing, not enthusiasm. |
| **"PROPRIETARY MODEL · Thousands of simulations"** | We do not have one. Claiming it would be the single most dishonest thing on the page. |
| Player photography | Likeness/rights. Team colour environments + abbreviations instead. |
| Its blue/orange system, type, graphics | Identity. LINEHOUND keeps warm graphite, reserved hot red, cyan, amber. |

## THE RATING — split into two tiers, honestly

### TIER A — shipping now, grounded in the reconciled contract
A **BET STANDING** reading composed only of countable, checkable inputs. **Not a
percentage. Not a probability.** Its components are individually verifiable by the user:

- **Price standing** — where the user's price sits against the board: better than N of M
  books; `your_price_beats_consensus` (bool, real); `price_improvement` points/return with
  its mandatory label (negative ~80% of the time — the normal case).
- **Board depth** — the real N behind the read (median 11, min 5, floor 6).
- **Support vs concern** — `thesis_support` count (usually 0) against
  `counterargument_lines` count (never empty).
- **Evidence tier** — `evidence_status`, "Observation" only today.
- **Verdict** — no_play (~93%) / flagged (~2%) / market_unavailable (~5%).

Rendered as a segmented standing with its inputs named beside it, so every segment traces
to something the user could check themselves. The axis is **THIN → WELL-SUPPORTED**,
describing evidence, never enthusiasm.

### TIER B — the future FLAGSHIP, blocked on validation (not prohibited)

**Framing correction.** The absence of a rating, a calibrated probability and a
recommendation is a **NOT-YET-EARNED** state, not a permanent product prohibition. The
research programme is expanding around earning exactly these: validated bet ratings,
calibrated probabilities where scientifically defensible, ranked best bets, recommended
picks, props, totals, F5, parlays, sport-specific predictive systems, large-scale
backtesting, forward validation, public performance tracking.

Tier B is therefore designed as the eventual **centrepiece**, so that when the research
earns a defensible result the only remaining work is binding real fields.

Illustrative shapes (the research architecture decides the real semantics — these are
**not** final field names):
- **BET RATING** as a huge numeral on a 0–100 scale, carried by an arc/ring.
- **MODEL WIN PROBABILITY vs MARKET IMPLIED**, side by side — **the gap between them is
  the story**, and the composition should make that gap the hero.
- A **rank badge** ("STRONGEST MLB BET #2 TODAY"), which implies a ranked daily board —
  a genuinely different screen from a slate, so that leaderboard state is designed too.

**The requirement that makes Tier B credible rather than tout-like:** a validated rating
carries its **provenance inline, as part of the component** — sample size behind the
rating, forward-tested window, calibration measure, last audited date. Every tout online
shows a big confident number with nothing behind it. Ours shows the number *and what
earned it*, in the same object. That is what will make a 91/100 believable when we have
one, and why the component is designed now rather than improvised later.

Tier A and Tier B are **the same object in two states**, not two designs — so a validated
pick later inherits the identical hero with no redesign.

### (superseded framing below, kept for the record)
The numeric **Support Score / Confidence Rating** primitive with a continuous track and a
large numeral. Designed so the system is ready, and marked in the handoff as **BLOCKED ON
VALIDATION**: it may not carry a number until engineering ships a calibrated, forward-
tested basis and Brey signs off. Until then it renders in its Tier A form.

**The handoff must label every featured-bet component A or B.** No Tier B element may
appear in an artboard without that label.

---

## LANGUAGE AUDIT — phrases that imply prediction where we only measure

My own earlier phrasing leaked predictive implication. Each is corrected:

| Banned phrasing | Why | Say instead (today) |
|---|---|---|
| "strongest current angle" | implies a predictive judgement about which angle is best | name what is measured — price gap, book disagreement, evidence count |
| "best available price standing" / "surface opportunity" | "opportunity" implies expected value | **price gap against consensus** — computable and checkable |
| Gameday featured slot as "best bet" / "top opportunity" / "strongest play" | all imply a pick | **largest price gap against consensus tonight**, or **widest book disagreement** — both real fields |

**Rule:** where the current system supports only price standing, *say price standing*.
The hero composition stays capable of carrying a genuine decisive recommendation later,
so a validated pick inherits the same component in its Tier B state.
