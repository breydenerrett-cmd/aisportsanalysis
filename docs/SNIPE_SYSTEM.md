# SNIPE: a private in-play watcher for tennis, NBA and NFL

**Written:** 2026-09-16, against branch `claude/sports-betting-analysis-review-g1o0co`.
**Status: design only.** Nothing below is registered, nothing has been built,
and no number in it is a measurement unless it names a file or an agent that
made it. This document sits inside `docs/LIVE_BETTING_SYSTEM.md` (the live v0
design, the defect list D1 to D12, and the R16-L build queue), not beside it.
Every evidence rule there applies here: pre-registration before any
evaluation, every loser published, no promotion without the full gate, no
rescue by threshold change, point-in-time data only, and nothing from this
system reaches a customer surface.

**Owner request this answers, 2026-09-16, in his words:** a Claude-built system
watching live tennis and NBA, managing a simulated paper account, sniping
situations like a heavy favourite losing the first set, with per-player
pre-determined prices and a formula that produces them, because "everyone is
different".

---

## 0. WHAT THE OWNER MUST DECIDE

Three decisions. Each has a default that applies if nothing is said. Each must
be answered and dated inside the pre-registration that relies on it, before the
first observation, never after rows exist.

| # | Decision | Default if unanswered |
|---|---|---|
| 1 | **Start the API-Tennis Business trial?** ($80 a month after a 14-day trial.) It is the only vendor found that documents live set-level odds with a suspension flag. The Odds API carries tennis match-winner only, with no set-winner and no next-set market. **Without this trial the owner's exact second-set bet has no reachable licensed source, and the tennis rule can only buy the match winner, which is a different and worse bet.** The trial has never been run, and the vendor's betting-licence terms are unanswered in writing. | **No.** Tennis is built on match-winner only, or not at all, and that substitution is recorded on the face of the rule. |
| 2 | **Which price floor binds?** The registered live band is no worse than -150 (`docs/LIVE_BETTING_SYSTEM.md` section 4.2). The owner's instinct, 2026-09-16, is that "-200 or higher should be considered". Section 4 shows -200 clears the value formula only when the model's own estimate, after markdown, is about 0.75 or better. These are two separate objections and both have to be answered: one says -200 is sometimes mathematically fine, the other says the project has already committed to not taking it. | **-150 stands.** A trigger priced worse than -150 is recorded with status `OUTSIDE_BAND` and is not a candidate. |
| 3 | **Does `conviction` stay a label, or is a shadow staked account run alongside?** The evidence ledger stakes flat 1 unit and cannot do otherwise (section 3). A shadow account sized by conviction can run off the same rows, shows what the drawdown of the instinct would have felt like, and never feeds the gate. | **Label only.** No shadow account. |

---

## 1. WHAT IT IS

A program that watches live tennis matches and live basketball and football
games, and waits for a small number of situations written down in advance. The
owner's example, a pre-match favourite losing the first set, is one of them.
When one happens, it looks up the in-play price for the bet declared in
advance for that situation, compares it to a price threshold computed for that
specific player or team from that player's or team's own numbers, and if the
price is good enough it writes a simulated ticket into a ledger file and sends
one push notification. **It places no bet, it contains no code that could place
a bet, and it never touches a real account.** The repo's own rule is "no
real-money betting and no bet-placement code, ever" (`docs/DEBRIEF.md`), and
that is a design input here, not a disclaimer. **It proves nothing yet, and
will not for a long time.** The live pipeline in this repo has never run once
(`live-window.yml`: 0 runs ever; `evidence/live_candidates_v1.jsonl` does not
exist), and on trigger rates already counted, the rules that are registered
cannot reach their evidence floor before 2027 or 2028. Until a family passes
the full promotion gate, every row it writes is a record of a guess, and the
honest description of the whole thing is "an instrument that measures whether
the idea is any good", not "a system that finds bets".

---

## 2. ARCHITECTURE

### 2.1 The process model

A snipe needs to go from "the feed says Alcaraz lost set one" to "the owner is
looking at a price" in well under a minute, because an in-play match-winner
price reprices within seconds of a set ending and is suspended for part of
that time. The repo's current delivery path cannot do it, and
`docs/LIVE_BETTING_SYSTEM.md` section 3.1 already says so: the window runs on a
GitHub Actions runner, publishes by `git push` every 5 minutes
(`live_window.run(commit_every_minutes=5)`), and the web app reads those rows
from `raw.githubusercontent.com` through a 60-second cache
(`src/pipeline/live_remote.py:9,31,63`), so capture to screen is up to about
360 seconds.

**Decision: the watcher runs on the owner's always-on Windows desktop, the
machine this repo is already checked out on.** That machine already holds the
repo, the `gh` credentials and the API keys, so nothing new has to be
provisioned and no key has to be copied to a second box. It costs nothing. It
is the recommended host.

**How it runs there.** One process per sport, started as a Windows service (via
NSSM, `nssm install snipe-tennis`) or, if a service is not wanted, a Scheduled
Task with trigger "At startup" plus "On failure, restart every 1 minute,
up to 999 times". Either form must satisfy three properties:

- **Restarts at boot**, so a reboot costs minutes, not a night.
- **Restarts on failure**, so an unhandled exception costs one poll interval.
- **Writes a heartbeat row on every poll** to `data/live/heartbeat.jsonl`,
  whether or not anything is live. This is the part that cannot be skipped.
  Without it, a machine that was asleep and a night on which nothing triggered
  produce byte-identical evidence, and coverage becomes a function of the
  owner's power settings. Uncovered minutes are written as `WINDOW_GAP` rows by
  the next poll after a gap, so downtime is counted, never silent.

Ledger rows are written locally to `evidence/live_candidates_v1.jsonl`
(hash-chained, append-only, isolated from the card ledger, exactly as today)
and pushed to the branch on a 60-second timer. Grading, settlement and the
daily reporting stay in GitHub Actions on the existing daily loop. Nothing
about the evidence architecture changes. Only the watching moves off Actions.

**The three ways the home machine fails, and the specific mitigation for each.**

| Failure | What it looks like in the data | Mitigation, specifically |
|---|---|---|
| **Power or internet loss** | Heartbeat stops mid-session; a `WINDOW_GAP` row appears when the machine returns. | Nothing prevents it. The mitigation is that it is measured: the session page reports gap minutes beside every count, and any read whose coverage was under 90% of live minutes is reported with that number attached. A UPS turns a brownout into a clean shutdown; router or ISP loss is simply accepted and counted. |
| **Windows Update reboots** | A gap of 10 to 40 minutes, often in the small hours, sometimes mid-evening. | Set Active Hours to cover the watching window (Settings, Windows Update, Advanced options, Active hours; or `HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings` `ActiveHoursStart` / `ActiveHoursEnd`), and pause updates during a measurement run. The service's "start at boot" property is what makes a reboot cost minutes instead of the rest of the night. Check monthly: `Get-WinEvent -FilterHashtable @{LogName='System'; ID=1074} -MaxEvents 10` lists recent reboot causes. |
| **Sleep or hibernate** | The most dangerous one, because the machine looks healthy afterwards and the missing hours look like a quiet night. | `powercfg /change standby-timeout-ac 0`, `powercfg /change hibernate-timeout-ac 0`, `powercfg /change disk-timeout-ac 0`, and confirm with `powercfg /a` and `powercfg /requests`. Verify empirically, not by reading the setting: the heartbeat count for a span must equal the expected poll count for that span within 1 percent (acceptance check in section 7, item 2). |

**Documented fallback: a small always-on cloud host.** Hetzner CX22 about 4
euros a month, Fly.io shared-1x about 2 to 5 dollars a month, DigitalOcean 6
dollars a month. It removes all three failure modes above, restarts under
systemd, and has an independent clock. Its costs are a second place where an
API key lives and a second writer to `data/processed/credit_log.jsonl`, which
is defect D7 in the existing doc and is already solved by R16-L4 (the live path
writes `data/live/credit_log_live.jsonl` and budget reads both logs merged).
Move to it only if the heartbeat record shows the home machine losing more than
about 10 percent of live minutes over a measured month.

**Retained but not used for the snipe:** GitHub Actions. The 350-minute job
cap, the 13-minute dispatch granularity and the documented 15 to 30 minute
handoff gaps (`docs/LIVE_BETTING_SYSTEM.md` section 3.2, "Window handoffs")
make it unusable for a seconds-scale trigger. It stays the right home for MLB,
for settlement and for anything that does not need seconds.

### 2.2 Components

```
                 +--------------+
  sport feeds -> | state poller |  one per sport, own cadence
                 +------+-------+
                        | state rows -> data/live/<sport>/<date>.jsonl, every poll
                        | heartbeat  -> data/live/heartbeat.jsonl, every poll
                        v
                 +--------------+
                 |   trigger    |  reads config/triggers.yaml and the alpha registry
                 |  evaluator   |  fires only on registered, non-retired rules
                 +------+-------+
                        | T0
                        v
                 +--------------+        +-------------+
                 | odds poller  |<-------| price model |  computes p_hat and the
                 | (on trigger) |        | (per side)  |  threshold price P*
                 +------+-------+        +-------------+
                        | fresh median quote plus per-book last_update
                        v
                 +--------------+
                 | paper ledger |  -> evidence/live_candidates_v1.jsonl (hash chain)
                 |    writer    |  -> data/paper_accounts/<system_id>.jsonl (FLAT_1U)
                 +------+-------+
                        v
                 +--------------+
                 |   alerter    |  -> push notification, owner only
                 +--------------+
```

- **State poller, per sport.**
  - *Tennis:* BALLDONTLIE ATP and WTA `/matches` carry live game and set score
    with a `server` field, and **no point-by-point**. The account is being
    served about 5 requests a minute (measured 2026-09-15,
    `docs/LIVE_BETTING_SYSTEM.md` section 2.2), which **forces a 30 to 60
    second poll**. A set ending is therefore detected up to 60 seconds late on
    this feed. API-Tennis Business, if decision 1 is yes, replaces it with a
    point log.
  - *NBA:* `BALLDONTLIE /nba/v1/games?dates=today` returns the whole slate in
    one request, so a 15-second poll is 4 requests a minute, which fits inside
    the ~5 a minute actually being served. This is the one place the rate limit
    is not binding.
  - *NFL:* The Odds API `/scores`, 1 credit a call, as today.
- **Odds poller.** Rule-gated, never any-change. One featured `/odds` call
  prices the whole slate for that sport, so a capture for one game prices the
  rest at no extra cost. Captures at T0, T0 + 45 s and T0 + 90 s (spanning two
  40-second vendor refreshes), plus one descriptive follow-up at T0 + 5 minutes
  that is the closing-line stand-in (section 6).
- **Trigger evaluator.** A pure function of (pre-game context, state row,
  triggers file). It refuses any rule whose `data/research/alpha_registry.jsonl`
  status is not `registered` or forward-testing. That kill switch does not exist
  today: no live code reads the registry (R16-L5 adds it).
- **Paper ledger writer.** Two writes per fire: the evidence row (section 6) and
  a `PaperBet` through `src/accounts/paper.py` at **FLAT_1U**. Note for the
  owner directly: `paper.kelly_stake()` raises by construction
  (`kelly_registered_disabled`), so "huge heavy bets on the likely bet" cannot
  be a stake in the evidence ledger. Section 3 says how conviction is recorded
  instead.
- **Alerter.** One HTTP POST to a push channel (ntfy topic or a Telegram bot),
  about 1 to 3 seconds. Owner only. Never a customer surface, never the public
  site.
- **Kill switches**, in order of blast radius: `SNIPE_ENABLED=0` (host
  environment, the watcher exits at the next poll), `LIVE_SPORTS=tennis,nba`
  (per sport), `LIVE_ODDS` not 1 (no paid in-play call anywhere, already
  shipped), the per-sport daily caps inside `LIVE_ODDS_DAILY_CAP = 300`,
  `CREDIT_FLOOR = 5000` (already shipped, refuses every paid call below it),
  per-rule registry status, and stopping the Windows service.
- **Fail-safe direction, stated once.** Every failure writes a row and stops.
  None of them writes a ticket. Feed error gives `UNPRICED_FEED_ERROR`. No
  fresh quote gives `UNPRICED_NO_FRESH_QUOTE`. Credit refusal gives
  `UNPRICED_CREDIT_REFUSED`. A missing model input walks the degradation ladder
  of section 4 and records which rung it landed on; if the ladder bottoms out,
  `NO_MODEL` and no ticket. A watcher that is down leaves a missing heartbeat
  and a `WINDOW_GAP` row. This matters more than it sounds: silent gaps let the
  machine look better than it is.

### 2.3 The data path, with a latency budget

From "the feed says Alcaraz lost set one" to a paper ticket and an alert:

| Hop | What happens | Budget (s) | Basis |
|---|---|---|---|
| 0 | The point ends at the venue | n/a | n/a |
| 1 | Broadcast or umpire entry, then the vendor publishes the completed set | 1 to 8 | Vendor claim, **unmeasured by us**. For NFL through The Odds API `/scores` this hop behaves more like 10 to 60 s. |
| 2 | Our poller's next poll picks it up | tennis 0 to 60 on BALLDONTLIE (rate-forced), 0 to 5 on API-Tennis; NBA 0 to 15; NFL 0 to 60 | Poll interval, our choice inside the vendor's rate |
| 3 | Trigger evaluation | under 0.05 | Pure function |
| 4 | In-play odds fetch | 0.3 to 1.5 | HTTP round trip |
| 5 | Freshness test, median across at least 3 fresh books | under 0.05 | |
| 6 | Price model: p_hat and threshold P* | under 0.2 | Per-entity parameters loaded at match start |
| 7 | Ledger row and paper bet, hash-chained, flushed | under 0.05 | |
| 8 | Push alert to the owner's phone | 1 to 3 | |
| | **Total, tennis on API-Tennis, good case** | **about 3 to 13** | |
| | **Total, tennis on BALLDONTLIE, realistic** | **about 30 to 70** | Hop 2 dominates at a 30 to 60 second poll |
| | **Total, NFL today** | **about 15 to 75** | `/scores` cadence dominates |

Hops 2 through 8 are ours and total under 5 seconds once the poll fires. Hop 1
is the whole game and has never been measured here. **The single most valuable
early measurement in this plan is hop 1** (section 7, item 3). If the market's
own price has already moved before our feed publishes the event, there is no
snipe, only latency debt, and that should be known in week one rather than in
2028. The BALLDONTLIE tennis poll of 30 to 60 seconds makes this worse by
construction and is the strongest single argument for decision 1.

### 2.4 What the repo cannot do today, and the smallest fix

| Gap | Smallest change |
|---|---|
| **No NBA anything.** `src/providers/odds.py:46` is `SPORT_KEYS = {"mlb": "baseball_mlb", "nfl": "americanfootball_nfl"}`. There is no `basketball_nba` key, no NBA poller, no team ratings and no game-id map. | Add `"nba": "basketball_nba"` to `SPORT_KEYS`; add an `nba_h2h` family to `config/capture_families.json` and measure its cost with `budget.probe_family`; add `src/pipeline/livefeed_nba.py` over `BALLDONTLIE /nba/v1/games`. About a day. **Season note: the NBA does not tip off until late October 2026**, so there is a six-week runway and no urgency. |
| **No set-winner market anywhere reachable.** The Odds API carries tennis match-winner only, with no set-winner and no next-set market (checked 2026-09-16). The owner's exact bet, "second set ML", has no licensed source today. | API-Tennis Business (decision 1). Otherwise the tennis rule buys the match winner, which is a substitution and must be labelled one on the face of the rule. |
| **No live tennis price feed and no suspension flag.** BALLDONTLIE tennis carries state, not in-play prices with a suspension flag; its ALL-ACCESS trial ends about 2026-09-17 05:30Z and the account is served at about 5 requests a minute. | API-Tennis Business, $80 a month, 14-day trial, ten checks in `docs/TENNIS_FEED_DECISION_2026-09-15.md`, **none of which has been run**, and a betting-licence question that has no written answer. |
| **No serve or return statistics on disk.** `data/historical/balldontlie/tennis/` holds only `.cursor` files; every matches file stopped at 500 rows with HTTP 429. | Either a working BALLDONTLIE plan, or the free public alternative: Jeff Sackmann's `tennis_atp` and `tennis_wta` match files carry service points won and lost per match back to the 1990s. The free route is about a day's work and carries no vendor risk. Take it. |
| **No seconds-scale delivery path off Actions.** | The home-desktop watcher of section 2.1. |

---

## 3. THE TRIGGER LANGUAGE

A trigger is a row in `config/triggers.yaml`, loaded and validated at start. A
new trigger is data. Only a new predicate operator is code.

```yaml
- id: T1_fav_loses_first_set          # unique; appears on every ledger row
  prereg: PREREG_LIVE_T1#T1           # doc and entry; the watcher refuses a rule
                                       # whose prereg commit is not an ancestor
  status: registered                   # read from data/research/alpha_registry.jsonl
  sport: tennis
  entity:                              # who this applies to: a selector, not a list
    select: pregame_favourite
    where: {pregame_prob_devig: ">=0.70", tour: [atp, wta], tier: [slam, m1000, m500, m250]}
  when:                                # the state predicate, all of
    - sets_lost_by_entity: 1
    - sets_won_by_entity: 0
    - match_status: in_progress
    - first_occurrence_in_match: true  # one trigger per rule per match, always
  want:
    market: set_winner                 # set_winner needs API-Tennis; otherwise match_winner
    scope: set_2
    side: entity
  price:
    source: fresh_median               # at least 3 books fresh under the registered rule
    threshold: formula:v1              # section 4, computed per entity per state
    floor: -150                        # owner band, decision 2
    market_prob_min: 0.50              # "more than likely", owner 2026-09-11
  stake:
    rule: FLAT_1U                      # the only rule the evidence path allows
    conviction: high                   # a LABEL on the row, not a size (decision 3)
  expiry:
    capture_deadline_s: 120            # after which the row is UNPRICED, not delayed
    alert_ttl_s: 90                    # the alert says so on its face after this
  degrade_max: 2                       # highest model-degradation rung that may ticket
```

**On "huge heavy bets".** The stake in the evidence ledger is flat 1 unit,
always. This is not timidity. It is the only way the value test in
`docs/LIVE_BETTING_SYSTEM.md` section 4.1 works: it computes the exact p-value
of total profit under the null that each bet wins at the rate its own price
implies, and variable staking breaks that null. `conviction` is recorded as a
label so that at the read the question "did the high-conviction subset do
better" can be asked as a descriptive split. Decision 3 governs whether a
shadow staked account runs alongside. If it does, it never feeds the gate, and
it exists to show what the drawdown of the instinct would have felt like. That
is worth having. It is not evidence.

### Three worked examples

**(a) The owner's: a tennis favourite drops the first set.** Exactly the
trigger above. In words: a pre-match de-vigged favourite at 0.70 or more loses
set one; we want set two's winner on him; we take it only if the price is no
worse than both the -150 floor and the threshold the formula computes for that
player, against that opponent, on that surface. **If decision 1 is no, the
`want` block becomes `market: match_winner, scope: full_match`, and the rule
records on its face that the registered bet is not the bet the owner
described.**

**(b) NBA: a favourite trailing at halftime.**

```yaml
- id: N1_fav_trails_half
  prereg: PREREG_LIVE_N1#N1
  status: proposed                     # NOT registered, so it cannot fire
  sport: nba
  entity: {select: pregame_favourite, where: {pregame_prob_devig: ">=0.65"}}
  when:
    - period: 2
    - period_state: end
    - margin_for_entity: {between: [-9, -1]}
    - first_occurrence_in_game: true
  want: {market: h2h, scope: full_game, side: entity}
  price: {source: fresh_median, threshold: formula:v1, floor: -150, market_prob_min: 0.50}
  stake: {rule: FLAT_1U, conviction: medium}
  expiry: {capture_deadline_s: 240, alert_ttl_s: 120}
  degrade_max: 2
```

**Halftime is the only plausible NBA trigger, and the rest are not snipeable
with obtainable data.** Halftime is a pause of minutes with the market open and
the clock stopped. The two other situations worth wanting, early foul trouble
and mid-quarter runs, are repriced by books within seconds, faster than any
feed found in this review. They are not proposed, and they should not be
proposed later without a feed that changes that fact.

**(c) NFL: the rule the repo already registered**
(`docs/PREREG_MULTI_SPORT_2026-09-14.md`, entry 4), expressed in this language
with no change of meaning:

```yaml
- id: nfl_favorite_trails_halftime
  prereg: PREREG_MULTI_SPORT_2026-09-14#4
  status: registered
  sport: nfl
  entity: {select: pregame_favourite, where: {pregame_prob_devig: ">=0.60"}}
  when:
    - minutes_since_kickoff: {between: [80, 100]}   # elapsed-time proxy; a real
    - game_completed: false                         # halftime marker needs a NEW
    - margin_for_entity: {between: [-7, -1]}        # registration, not an edit
    - first_occurrence_in_game: true
  want: {market: h2h, scope: full_game, side: entity}
  price: {source: fresh_median, threshold: none, floor: none, market_prob_min: none}
  stake: {rule: FLAT_1U, conviction: null}
  expiry: {capture_deadline_s: 300, alert_ttl_s: 300}
  degrade_max: 3                                    # records unconditionally
```

Note what is deliberately absent: no threshold, no floor, no band. The
registered text has no price band, so the snipe formula may be computed and
stored on this rule's rows but may not select them. Adding a band changes which
candidates are recorded, which is a new rule and a new registration. This is
the concrete shape of "no rescue by threshold change".

**NFL beyond halftime.** Halftime is genuinely workable because the pause is
minutes long. The turnover case (a favourite that just threw a pick six, say)
depends on beating a 20 to 60 second suspension-and-reopen window, and is
marginal. It is not proposed here.

---

## 4. THE PRICE FORMULA

### 4.1 The shape, once, for all three sports

Two steps, deliberately separated so a wrong answer can be traced to one of
them.

**Step 1: p_hat, the probability the bet wins, given the live state.**
Sport-specific, sections 4.2 to 4.4. Every p_hat carries `u`, its own standard
error, and `degrade_level`, the input tier that produced it.

**Step 2: the threshold price P\*, identical across sports.** Following the
house form of `docs/PREREG_CARD_V2.md` section 4:

```
q       = p_hat - M              where M = max(0.02, k * u), k = 1.0 registered
edge(d) = BASE_EDGE * d / 2      BASE_EDGE = 0.010, d = decimal price
interesting  <=>  q >= 1/d + edge(d)
```

Solving `0.005 d^2 - q d + 1 = 0` for the smaller root gives the threshold
decimal directly:

```
d* = ( q - sqrt(q^2 - 0.02) ) / 0.01        no solution if q < 0.1414
```

`P*` is `d*` converted to American. The bet fires only if the fresh median
price is no worse than `d*`, no worse than the -150 floor (decision 2), and the
in-play de-vigged market probability is above 0.50.

Worked, so the mechanism is visible:

| p_hat | u | M | q | d* | P* (American) | Read |
|---|---|---|---|---|---|---|
| 0.80 | 0.04 | 0.040 | 0.760 | 1.326 | **-307** | A genuine cakewalk justifies a heavy price |
| 0.75 | 0.05 | 0.050 | 0.700 | 1.441 | **-227** | -200 is interesting |
| 0.70 | 0.05 | 0.050 | 0.650 | 1.552 | **-181** | -200 is not; -175 is |
| 0.65 | 0.05 | 0.050 | 0.600 | 1.689 | **-145** | |
| 0.60 | 0.06 | 0.060 | 0.540 | 1.877 | **-114** | |
| 0.55 | 0.06 | 0.060 | 0.490 | 2.075 | **+108** | |

**This is the direct answer to the owner's question, and it is not the answer
he wanted.** He wrote that in the Alcaraz situation, "-200 or higher should be
considered". Under this formula, -200 clears only when the model's own honest
estimate of him winning that set is about 0.75 or better **after** the
markdown, and it is the markdown, not the raw estimate, that removes most of
these. Separately, the registered live band is no worse than -150, so -200 is
outside it entirely. Those are two different objections and decision 2 has to
answer both.

### 4.2 Tennis: p_hat from a serve model

This is where a real per-player formula genuinely exists, because a tennis
score is generated by a repeated, near-independent unit: the service point.

```
spw_A = A's service points won %, surface-adjusted, trailing 52 weeks
rpw_B = B's return points won %, surface-adjusted, trailing 52 weeks
tour_avg_spw = the tour and surface baseline (about 0.645 ATP hard, about
               0.565 WTA hard: illustrative, must be computed, not assumed)

p_A_on_serve = clip( spw_A - rpw_B + tour_avg_spw , 0.45, 0.85 )   # Barnett-Clarke
p_B_on_serve = clip( spw_B - rpw_A + tour_avg_spw , 0.45, 0.85 )
```

Then closed-form Markov recursions, all exactly computable with no simulation:
`P(hold)` from `p_on_serve`, then `P(win a set from the current game score)`,
then `P(win the match | sets standing)`. For the owner's case the bet wants
`P(A wins set 2)`, which the set recursion returns directly.

**Losing set one does not change these inputs at all** unless the model is told
to update them, and that is the real question the idea poses. The market drops
a favourite after a lost set partly because it is being Bayesian about his
condition (injury, illness, a bad day) and partly because it must be. A naive
model says nothing happened. So the model needs an explicit, registered update
term:

```
p_A_on_serve <- p_A_on_serve - delta * (observed set-1 service shortfall)
delta = a registered constant, fitted on 2025 and earlier only, never refit
```

Without `delta` the model is guaranteed to think every trailing favourite is a
bargain, which is exactly how systems like this fool people.

| Input | Source | State today |
|---|---|---|
| spw and rpw by surface | Sackmann `tennis_atp` / `tennis_wta` match files (free, public, per-match service points), or BALLDONTLIE `atp_match_stats` | **Neither on disk.** The BDL harvest left only `.cursor` files. Sackmann is the recommended route. |
| Surface, tier, round | The same source; API-Tennis for live | Not on disk |
| Opponent quality | Implicit in rpw; Elo optional as a cross-check | Not on disk |
| Head to head | The same results feed | Small n, see below |
| Live set and game score, server | BALLDONTLIE ATP and WTA `/matches`, polled every 30 to 60 s | **Available, rate-forced, no point-by-point** |
| Live point log and set-level price with a suspension flag | API-Tennis Business only | **Does not exist here** (decision 1) |
| Pre-match de-vigged favourite | `src/pipeline/tennis_capture.py`, per-tournament keys, family `tennis_h2h` | **Exists and runs.** Cost per call unmeasured (`config/capture_families.json`: `"measured": false`). |

**Head to head is an estimate that should mostly be ignored.** Two players meet
3 to 8 times in a career; the standard error on a head-to-head rate at n = 5 is
about 0.22. Registering an H2H adjustment larger than a couple of points of
point-probability is fitting noise, and it is the most seductive input in
tennis. Cap its contribution or drop it. Either is defensible. Deciding after
seeing rows is not.

**Degradation ladder**, recorded on every row as `degrade_level`:

- **0** full: surface-specific spw and rpw on at least 500 service points each
  within 52 weeks. `u` about 0.03 to 0.04 on the set probability.
- **1** all-surface spw and rpw, or 200 to 500 points. `u` about 0.05.
- **2** ranking or Elo-implied spw gap only, no player stats. `u` about 0.07.
  **This is the bottom rung that may ticket.**
- **3** market-derived only: invert the pre-match de-vigged match price into an
  implied point edge and re-project onto set two. Records a row, never tickets.
  This rung can only detect internal inconsistency between the market's own set
  price and its own match price. It contains no information the market lacks,
  and must be labelled that way on the row and in every read.

### 4.3 NBA: p_hat from possessions

```
E[margin over remaining] = ((ORtg_A - DRtg_B) - (ORtg_B - DRtg_A)) / 100 * poss_remaining
poss_remaining           = pace * (seconds_remaining / 2880) * period_adjust
sigma                    = sigma_pp * sqrt(2 * poss_remaining)    sigma_pp about 1.05 pts/poss
p_hat                    = Phi( (current_margin_for_entity + E[margin]) / sigma )
```

Foul and minutes state enters as an adjustment to the rating terms: a starter
with 5 fouls at halftime lowers his team's rating by his on-off value times his
expected minutes loss. **That adjustment is an estimate, not a measurement.**
The repo has no NBA on-off data and building it is a project, not a field. Ship
NBA at degrade level 1 rather than inventing a number.

| Input | Source | State today |
|---|---|---|
| Team ORtg, DRtg, pace | BALLDONTLIE NBA teams and stats endpoints, or box scores aggregated | **Nothing. No NBA code exists.** |
| Live score, period, clock | `BALLDONTLIE /nba/v1/games`, whole slate in one request | Not built |
| Foul and minutes state | BALLDONTLIE box score | Not built, and rate-limited |
| In-play price | The Odds API `basketball_nba` h2h | **`basketball_nba` is not in `SPORT_KEYS`** |

Ladder: **0** full ratings plus foul state; **1** ratings only; **2** the
pre-game de-vigged price converted to an implied pre-game margin and propagated
forward with the clock. Rung 2 is the classic "live win probability from the
opening spread" model: honest, cheap, and carrying no information the market
had, so like tennis rung 3 it records but does not ticket.

### 4.4 NFL: p_hat from strength, time and score

The same Gaussian form as NBA with drives in place of possessions.
`src/analysis/nfl_strength.py` already exists and is the input, which makes NFL
the cheapest of the three to model and the most expensive to test: 272 games a
season means the registered halftime rule needs four to five seasons to reach
150 observations. Build it last and expect nothing from it soon.

### 4.5 Calibration without touching sealed data

Every constant (`k`, `BASE_EDGE`, `delta`, `sigma_pp`, the surface baselines,
any head-to-head cap) is fitted on 2025 and earlier only, written into one JSON
file, hashed with sha256, and that hash recorded in the pre-registration before
the first observation. The sealed window (2026-01-01 to 2026-08-27) is not
read. Forward data from 2026-08-28 onward is never folded back. A constant is
never refitted to rescue a family. If a constant is wrong, that is a finding,
published, and any replacement is a new family with a new floor.

### 4.6 The honest uncertainty at the moment of the snipe

Three errors stack, and only the first is small.

1. **Parameter error.** spw estimated on about 1,500 service points has a
   standard error of about 0.012, which is roughly plus or minus 0.03 to 0.05
   on the set probability. Measurable, honest, and the smallest term.
2. **State error.** Our feed may be 1 to 8 seconds behind on API-Tennis, and 30
   to 60 seconds behind on the BALLDONTLIE poll the rate limit forces. A
   service game can end inside that window. We may be pricing a state that no
   longer exists. **Unmeasured. Potentially the largest term, and the cheapest
   to measure** (section 7, item 3).
3. **Model error.** Point independence is false (serve patterns, fatigue,
   injury, nerves). `delta` is one constant standing in for the entire space of
   "why is he losing". Unquantifiable in advance; the only handle on it is
   out-of-sample calibration at the read.

**Combined, `u` on p_hat at the moment of the snipe is 0.05 at best and
plausibly 0.08.** The effect being hunted is of order 0.03 to 0.05. **The
uncertainty is larger than the prize.** That is not a reason to abandon the
project. It is the reason the markdown `M = k * u` exists, the reason the
threshold is conservative, and the reason the honest expected outcome is that
most triggers do not clear the threshold and no ticket is written. A system
that tickets often is a system whose `u` is a lie.

---

## 5. WHY THIS COULD BE WRONG

The strongest version of the case against, stated without softening.

1. **The counterparty is better resourced at exactly this task.** In-play
   prices are set by models with full point-by-point history, court-side or
   near-court-side latency, and a live order-flow signal we do not have.
   Believing we can beat them in the seconds after a state change is believing
   we are faster or better informed at the one moment they have optimised
   hardest for. The five pre-game measurements in
   `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md` did not find that we beat the
   market pre-game. Live is the harder version of that problem.
2. **An obvious mispricing is usually not a mispricing.** The three ordinary
   explanations for "that price looks free" are: the quote is stale and will be
   voided on click; the market is about to suspend and the price is a ghost; or
   the book knows something (an injury, a medical timeout, a scratch) our feed
   has not published. All three produce exactly the pattern this system is
   built to detect.
3. **The latency chain is stacked against us.** Venue, official scorer, vendor,
   our poll, our decision, the owner's thumb. The book sits near hop 2. We sit
   at hop 5. Any price still available to us at hop 5 is, by construction, one
   the book has chosen not to move, which is information about us rather than
   about the bet. On BALLDONTLIE's rate-forced 30 to 60 second tennis poll this
   objection is at its strongest.
4. **The paper record will flatter us.** Paper tickets fill at the fresh median
   price, instantly, in unlimited size. Reality offers the price that can
   actually be clicked, after a suspension, in the size a book allows a winning
   account, and the size the owner described is exactly what triggers limits. A
   paper return of +4% can be a real return of -2% through fill realism alone.

**What would distinguish a real edge from those explanations:**

| Evidence | A real edge looks like | A stale or ghost quote looks like |
|---|---|---|
| Price at T0 + 5 min against the logged price | Moves toward us and stays | Snaps back past our price within 40 to 90 s |
| Fresh-book share at T0 | Most books fresh, prices agree | One or two books fresh, wide dispersion, ours the outlier |
| Book `last_update` against T0 | Books updated after T0 still offer it | Only books that have not updated since before T0 offer it |
| UNPRICED and suspended share | Low, the market stays open | High, the market suspends exactly when we want in |
| **A manual click-availability log** | The price is still displayed 15 s after the alert | Gone, suspended, or "price changed" on click |

The last one is not automatable and is the most important. **For the first 30
alerts, the owner should open the book, look, and record yes or no and the
price actually shown.** Thirty observations of "the price was gone" ends this
project in two weeks for the cost of his attention, which is an enormously good
trade against finding out in 2028.

**What the paper record has to show before anyone believes it:** the registered
floor (150 priced candidates) reached without any threshold change; a positive
result under the exact convolution test at the family's alpha; an UNPRICED plus
OUTSIDE_BAND share under 30%; the T0 + 5 min stand-in moving in our favour on
the same rows; and the click-availability log agreeing. Any one of those
failing means the number is not what it looks like. Even a full pass is
SUPPORTED at floor, not promoted: promotion needs the full G0 to G7 gate,
including at least 300 forward selections over at least 60 ledger days and the
owner's explicit, dated sign-off.

---

## 6. EVIDENCE PLAN

**Pre-registration.** One document per family, committed before the first
observation, adversarially reviewed, with a registry row in
`data/research/alpha_registry.jsonl`. It states: the trigger in the exact
language of section 3; the side and market; the price threshold formula version
and the sha256 of the frozen constants; the floor (150 priced candidates); the
family-wise alpha; one read at the floor; a stop date; which degradation rungs
may ticket; and the closing-line stand-in. The watcher refuses to fire a rule
whose prereg commit is not an ancestor of its own commit. That check does not
exist today and is the most important new piece of plumbing in this design.

**Ledger row.** Extends the schema in `docs/LIVE_BETTING_SYSTEM.md` section
3.1, which is already right. These are the additions the formula needs.

| Group | Fields |
|---|---|
| Identity | `schema_version`, `family`, `rule_id`, `rule_version`, `prereg_doc`, `prereg_commit`, `code_commit`, `constants_sha256` |
| Entity | `entity_id`, `entity_name`, `sport`, canonical `game_id` or `match_id` |
| Pre-game proof | `pregame_prob_devig`, `pregame_books`, `pregame_newest_observed_utc`, `commence_time`; the row is refused if any pre-game quote was observed at or after the start |
| Trigger | `t0_utc`, `state_row_id`, the exact state fields that satisfied the predicate, `feed_publish_utc` (for the hop-1 lag measurement) |
| Quote | `capture_observed_utc`, per book `{book, price, last_update}`, `fresh_books`, `logged_price`, `latency_s`, `max_quote_age_s`, `retries` |
| Model | `p_hat`, `u`, `degrade_level`, `inputs_vintage` (the as-of date of every parameter), `markdown_M`, `threshold_price`, `market_prob_devig_at_t0` |
| Decision | `DECISION` in {`TICKET`, `NO_TICKET_PRICE`, `NO_TICKET_BAND`, `NO_TICKET_MODEL`}, `conviction`, `stake_units: 1.0` |
| Status | `PRICED`, `UNPRICED_NO_FRESH_QUOTE`, `UNPRICED_NO_MARKET`, `UNPRICED_CREDIT_REFUSED`, `UNPRICED_FEED_ERROR`, `NO_MODEL`, `OUTSIDE_BAND` |
| Stand-in close | `followup_t0_plus_300_price`, `followup_fresh_books`, `followup_t0_plus_900_price` |
| Settle | `result`, `profit_units`, `settled_utc`, `settle_source`, `void_reason` |
| Surface | `customer_eligible: false`, fixed |

**Grading.** From an authoritative final only, never from the live poller.
Tennis from the results feed with the retirement rule registered before any
tennis grade (`src/providers/tennis_results.py` already encodes walkover to
VOID, and retired to VOID unless the set completed). NBA from BALLDONTLIE
finals, cross-checked the next day. NFL from The Odds API `/scores` completed
flag, cross-checked against the nflverse schedule. Unsettled rows retry daily.
VOID only after 7 days, always with a reason.

**The floor read.** One read, at 150 priced candidates, at the registered
alpha. Flat 1 unit at `logged_price`. Under the null each bet wins with
probability 1 / decimal price, so expected profit is zero; the p-value is the
exact one-sided upper tail of total profit by convolution. **Report the effect
size the floor can see, in words, every time:** at n = 150 and one-sided alpha
0.0167 with 80% power, the win rate must beat break-even by about 12 points. A
null at 150 rules out only a very large mispricing and must be stated that way.

**Retirement.** A family retires on a null at the floor read (`TESTED_NULL`,
published); on the stop date being reached without the floor (`UNDERPOWERED`,
published with no read); or on UNPRICED plus OUTSIDE_BAND exceeding 50% of
triggers after 60 triggers (`UNMEASURABLE_AT_THIS_FEED`, published, and not
re-banded). Every loser is published. There is no path that quietly shelves a
family.

**The closing-line problem.** An in-play bet has no settled close: the market
for "Alcaraz wins set 2" ceases to exist when set 2 ends, and nothing closes
it. So G6 cannot be met by any live family until a stand-in is registered.

**Proposed stand-in: the de-vigged in-play consensus at T0 + 300 seconds**,
under the same freshness rule. The defence: it is causally downstream of the
trigger, so it incorporates the information the bet claims to have; it is
independent of the outcome, so it cannot leak; it is capturable on the same
infrastructure for one credit; and it is the standard the in-play literature
uses. **Its weakness, stated plainly:** it is measured on the same feed with
the same latency, so if the whole apparent edge is latency debt, the stand-in
inherits the bias and will look fine. Mitigation, registered alongside: also
capture T0 + 900 seconds, and for markets that survive to game end, the last
pre-final price. If the T0 + 300 stand-in is positive but T0 + 900 is flat,
that is the signature of a stale quote rather than an edge, and it counts as
disconfirming.

---

## 7. BUILD ORDER

Smallest first. Tennis and NBA before NFL. Each item has a literal check.

1. **Fix the existing live plumbing first. It is broken in twelve documented
   ways.** Do R16-L2 through R16-L7 from `docs/LIVE_BETTING_SYSTEM.md` section
   6 before writing a line of snipe code. *Check:* `python -m unittest
   tests.test_live_window tests.test_live_rules tests.test_live_ledger
   tests.test_live_odds` green, with the new tests failing on the parent
   commit. Nothing below is worth building on code where `pregame_context()`
   returns a favourite of `None` for 10 of 10 games.
2. **Stand up the watcher on the home desktop.** Windows service or scheduled
   task, restart at boot and on failure, `SNIPE_ENABLED` in the environment,
   heartbeat row every poll, ledger pushed to the branch every 60 seconds.
   *Check:* the service reports running for 24 hours; `wc -l
   data/live/heartbeat.jsonl` equals the expected poll count for that span
   within 1 percent (this is the real sleep test, not reading the power
   setting); `powercfg /a` shows sleep and hibernate disabled on AC; kill the
   process and confirm the next session page reports a `WINDOW_GAP` whose
   minutes match.
3. **Measure hop 1 before building anything that depends on it.** For a week,
   for every set or score event we can observe, log our `feed_publish_utc`, our
   detection time, and the earliest book `last_update` that reflects the new
   state. *Check:* a table of at least 50 events with the three timestamps and
   a stated median of how far behind the first repricing book we were. **If
   that median is near zero or negative, continue. If we are consistently 10 or
   more seconds behind the first book, stop and say so.** The rest of the plan
   is then not worth building, and finding that out in week one is the
   highest-value outcome available here.
4. **Tennis feed decision (decision 1).** Run the ten checks in
   `docs/TENNIS_FEED_DECISION_2026-09-15.md` on the API-Tennis trial. *Check:*
   every check has a measured number and a pass or fail recorded in
   `docs/API_TENNIS_TRIAL_RESULTS.md`; a dated decision; the betting-licence
   question answered in writing or recorded as "no written answer". A skip is
   recorded as the decision, not left ambiguous, and it means the tennis rule
   buys the match winner rather than set two.
5. **Tennis parameters, offline.** Ingest the Sackmann ATP and WTA match files,
   compute surface-adjusted spw and rpw per player over a trailing 52 weeks,
   fit `delta` and the surface baselines on 2025 and earlier, freeze to
   `config/tennis_serve_params.json` with a sha256. *Check:* the fitting script
   prints the hash and asserts that no input row is dated 2026-01-01 or later;
   a holdout on 2024 shows the set-probability model calibrated within 3 points
   across five probability buckets.
6. **The trigger language and the evaluator.** `config/triggers.yaml`, a
   validator, the registry-status check, the prereg-ancestor check, and the
   one-trigger-per-rule-per-match rule. *Check:* a replay test feeding a
   recorded state sequence produces exactly the expected trigger rows and no
   more; a rule marked retired in a temporary registry fires nothing; a rule
   whose `prereg_commit` is not an ancestor raises.
7. **Pre-register T1.** `docs/PREREG_LIVE_T1.md`, adversarially reviewed, with
   the owner's dated answers to decisions 1, 2 and 3 quoted inside it. *Check:*
   `git log --format=%cI -1 -- docs/PREREG_LIVE_T1.md` is earlier than the
   first ledger row's `recorded_utc`; the registry rows are present.
8. **MILESTONE 1: one real match, watched end to end, one paper ticket written,
   nothing claimed.** *Check, literally:* pick one live ATP or WTA match; the
   watcher logs a state row for every game of that match with no gap longer
   than the poll interval plus 10 seconds; if the trigger fires,
   `evidence/live_candidates_v1.jsonl` gains exactly one row with a non-null
   `p_hat`, `threshold_price`, `logged_price` and `fresh_books` of at least 3;
   `python -c "from src.appstate import live_ledger; print(live_ledger.verify())"`
   reports a valid chain; one alert arrives on the owner's phone; `python -m
   src.cli budget` shows a `live_odds` spend under 10 for the day. **If the
   trigger does not fire, that is also a pass.** The milestone is that the
   machine watched, not that it found something. Nothing is claimed, computed
   or reported about whether the bet was good.
9. **Tennis at scale, plus the click-availability log.** Run every tour-level
   day. The owner records, for the first 30 alerts, whether the price was still
   there. *Check:* 30 rows in `evidence/click_availability.jsonl`, each with a
   yes or no and the price actually seen.
10. **NBA, from late October.** Add `basketball_nba` to `SPORT_KEYS`, measure
    the family cost with `budget.probe_family`, build `livefeed_nba.py` on the
    one-request-per-slate endpoint, and build the possession model at degrade
    level 1 (ratings only). Halftime only. Pre-register N1 only after counting
    its trigger rate on the 2025-26 season. *Check:* the poller lists tonight's
    slate in one request; `budget.family_cost("nba_h2h")` returns a measured
    integer, not `None`.
11. **NFL last.** Reuse `src/analysis/nfl_strength.py`, wire the
    already-registered halftime rule into the new language with no change of
    meaning, expect it to take four to five seasons, and spend no further
    engineering on it. The turnover case is not built.
12. **Only after a family passes the full gate:** any surface beyond the
    owner's own phone, against R16-L20's literal bar of p95 capture-to-render
    at or under 20 seconds over 20 captures.

### 7.1 What this costs

The odds plan is already paid for. Adding a BALLDONTLIE tier for state is
roughly $99 a month all-in, and the in-play calls fit inside the existing
300-a-day cap (`src/capture/budget.py:98`, `LIVE_ODDS_DAILY_CAP = 300`) because
capture is rule-gated: one featured `/odds` call prices a whole slate, and the
registered triggers fire a few times a day. Decision 1 adds $80 a month on top
if the owner takes API-Tennis.

**What does not fit:** watching spreads, totals and props in play across two
sports would exhaust the monthly credit allotment in about a week. In-play
markets beyond h2h are out of scope for this design, and adding one is a budget
decision before it is an engineering one.

---

## 8. WHAT THE OWNER SEES

Both artifacts exist, and they have different jobs. **The push notification is
the live artifact: it is what he sees while a match is running, and it is the
only thing fast enough to matter at the moment of a fire. The session page is
the review artifact: it is what he reads afterwards, and it never shows a
result before the registered read.**

**The push notification**, one per fire, one screen, no scrolling:

```
SNIPE . TENNIS . 19:42:07Z
Alcaraz lost set 1 (3-6) vs Struff . hard . R32

WANT   Alcaraz, set 2 winner
PRICE  -165   (median of 5 fresh books, oldest 11s)
MODEL  p 0.71 +/- 0.05 . degrade 0 (full serve stats)
BAR    -181   price clears the bar by 16 cents
BAND   -150 floor: FAILS . market 0.62: ok

DECISION  NO TICKET, outside the registered price floor
PAPER     no row staked, trigger recorded

Prices move in seconds; this one may already be gone.
Research record, not a pick. Nothing was bet.
```

Every field is there so the owner can disagree with it in real time. The `BAR`
line is the formula's answer, the price at which this becomes interesting for
this player in this situation, which is the thing he asked for. The `DECISION`
line is the only place the system says anything, and most of the time it will
say no.

**One honest warning about this alert.** A message that names a side, a price
and a deadline is functionally a pick, whatever it is labelled, and the repo's
rules about picks and customer surfaces protect customers, not the owner.
Nothing stops him acting on it with his own money, and the system cannot stop
him. What it can do is refuse to pretend: the alert always shows `p_hat` with
its uncertainty, always shows the degrade level, and during the research period
the session page never shows profit. If he finds himself betting these before
the floor read, that is worth naming out loud rather than discovering later in
the ledger.

**The session page**, read after a session, at a typed URL, internal, out of
the public chrome:

```
SESSION  2026-09-16 . tennis . 19:02Z to 23:48Z  (4h46m watched, 0 gap minutes)

MATCHES WATCHED        14
TRIGGERS FIRED          3      T1: 3
  ticketed              1
  no ticket, price      1
  unpriced              1      (no fresh quote within 120s)

ROWS                                                    T1: 7 of 150 tested
  19:42  Alcaraz   set 2   -165  bar -181  p 0.71+/-0.05   NO TICKET (band)
  20:58  Rune      set 2   +105  bar -114  p 0.55+/-0.06   TICKET
  22:15  Sabalenka set 2     -   bar -150  p 0.68+/-0.05   UNPRICED

FEED HEALTH
  detection lag vs first repricing book   median +6.2s  (n=19)
  fresh books at trigger                  median 5
  quote age at capture                    median 14s / p90 48s
  suspended or absent at trigger          1 of 3
  heartbeat coverage                      100% of live minutes

CREDITS  live_odds 6 of 150

No result is computed. Outcomes are published once, at the registered
read of 150, or at retirement, whichever comes first.
```

The feed-health block is deliberately as prominent as the rows, because for the
first several months it is the only part of this page that can tell the owner
something true.
