# LINEHOUND — where we are, 2026-09-21

*Written overnight 2026-09-20 → 21 for Brey. Every number cites where it came
from. Anything not verified says so. An independent fact-check checked 129 of
this report's claims against the code, the ledgers, the CI logs and the live
site. It found 61 that were wrong, overstated or unverifiable, and every one
has been corrected in this version. Items marked **[10:00Z]** depend on the
3am-PT daily run and are filled in by section 11.*

---

## 1. TL;DR

- **For six days the capture pipeline threw away most of what it paid to
  capture, and the warnings that it was going wrong were ignored.** From
  2026-09-15 04:27Z to 2026-09-21 04:14Z, one line in the capture script staged
  nothing. Its own error was silenced. The damage it caused was not silent:
  ESCALATE lines and red afternoon runs appeared every day from 09-16, but
  nothing acted on them. Fixed, tested, and **proven in production at 04:14Z**.
  A failed save now also turns the job red. *(Section 2.)*
- **The afternoon MLB board had a second, separate blocker, now also fixed.**
  From 09-18 a CI cache kept feeding it pitch data four days stale. My first
  fix for that went to the wrong branch and did nothing. The real fix went to
  the branch the schedule actually runs from at about 06:00Z. **[10:00Z/afternoon]**
  confirmation pending.
- **Sunday proved your −200 rule.** The old NFL favourites card went **5-3 and
  lost 1.03 units** (settled 10:16Z). Its 49ers win at −950 earned 0.11u, and
  each of its three losses at −295, −420 and −380 cost a full unit. Winning
  62.5% of bets lost money.
- **NFL no longer picks favourites.** The old rule took the favourite in every
  game it picked, down to San Francisco −950. The new rule (NFL_CARD_V2) only
  publishes a price that beats the other books' consensus under three standard
  ways of removing the vig. It never takes −200 or worse. It will pick rarely,
  often not at all. **Monday night's card is still the old rule's (Rams −300)**,
  published before V2 went live and labelled as the old rule. **V2's first
  possible card is Thursday 09-24.**
- **All three sports are on the staging preview site** (production isn't
  live). MLB has picks. NFL has the new rule. Tennis has a research page, and
  **tennis prices were captured for the first time ever this morning** (WTA
  Singapore Open) once the blocked probe was fixed. **Tennis still can't
  grade picks:** even with your new BALLDONTLIE key, tennis results return
  **HTTP 401**. That key does not include ATP/WTA results.
- **MLB's record is positive, but every single game pick has been a
  favourite.** Game picks are 57-31 (+5.58u) over 10 settled days. Props are
  57-28 (+1.41u) over 6 settled days. All 88 game picks were favourites, and
  38 of the 85 props were bought at −200 or worse. That breaks your own rule.
  Hits Unders lost money despite winning 61%.
- **MLB's regular season ends 09-27.** That changes what's urgent: NFL is the
  sport that runs through the winter.
- **Credits look under control after the fix, but watch today.** Every day
  from 09-15 to 09-20 spent 1,400–4,100 credits against a 900 budget. Today
  (09-21) had spent **280 by 10:20Z**, about 24 an hour overnight since the
  fix, with a checkpoint every slot. The balance is 9,534 against a 5,000
  floor. Daytime MLB prop buying is the heavy part, so the real test is
  whether today stays under 900.
- **New bug found and being fixed: the MLB engine bets NFL games.** On 09-20
  its baseline strategies placed 84 paper bets on NFL games, because the
  engine doesn't filter the shared odds store by sport. So 09-20's MLB paper
  record can't settle. It is not from tonight's changes (09-17 had one), and
  the fix is in progress for the 13:31Z retry *(section 4.3)*.
- **Four decisions are yours** *(section 10)*.

---

## 2. The incident, and the fix

### What happened

Every ~13 minutes a GitHub job captures odds, prop prices, weather and the
credit balance, then commits them. It staged everything with one command
naming **seven paths** (six folders and one file). On 2026-09-15 04:27Z
(`db30367f`) that list gained `data/live`, a folder that almost never exists on
a fresh runner. When any path in that command is missing, git refuses the
whole command and stages nothing (reproduced directly: `fatal: pathspec`, exit
128, 0 files). The error was sent to `/dev/null`.

So each capture run either reported "no data changes" or committed only
`data/historical/*` (staged by a separate command), and every run finished
green.

**What was lost:**

- Morning data never survived. Each runner starts fresh and dies after its
  run. A slot's processed data was saved only if the *same* runner then ran
  the lineup-gated slate pass, which commits `data/processed`. On 09-19 that
  first happened at about 15:40Z.
- Everything captured before then was lost for good.
- Raw odds files and watch files were never staged by that path, so they were
  lost for **every** slot.

**It was not silent.** The git error was hidden, but its effects were
reported:

- Green capture runs printed `ESCALATE: live-capture envelope tripped` from
  09-16 (e.g. run 35094443781) and on 09-19.
- The afternoon slate went red every evening from 09-16.

None of it was acted on.

### What it broke

1. **Credits.** Checkpoints of the credit balance were lost with each runner,
   so the budget check kept reading an understated "spent today". The
   daily-envelope refusal fired late or not at all. Daily spend:

   | Day | Credits | Note |
   |---|---|---|
   | 09-15 | 1,411 | |
   | 09-16 | 4,120 | |
   | 09-17 | 1,474 | |
   | 09-18 | 1,650 | |
   | 09-19 | 1,575 | no checkpoint at all from 03:57Z to 15:36Z |
   | 09-20 | 1,426 | |

   The budget is 900. *(The committed log cannot say which capture family
   spent what inside those gaps, because a lost checkpoint folds its spend
   into the next caller that was saved.)*
2. **Stale prices.** Once the envelope finally tripped on 09-19 (about 06:06Z),
   game-odds and prop-listing capture were skipped from about 06:56Z. Batter
   props kept spending. By the evening the afternoon slate refused because
   its prices were hours old.
3. **Afternoon MLB board refusals.** The pre-slate guard refused the
   lineup-gated afternoon passes rather than stake on stale inputs. That guard
   worked as designed. *The morning engine slate and the public MLB card kept
   publishing every day.*
4. **Green runs that did nothing.** The afternoon "too early" guard checked
   for captures before the store it reads had been built. It always saw zero,
   called it "too early" and went green. That happened in **six** runs on
   09-19, and on every earlier day since the guard was added on 09-16.
5. **A second, unrelated blocker from 09-18: stale pitch data.** The afternoon
   slate re-saved a shared CI cache about every 30 minutes and buried the daily
   loop's fresher copy. The slate kept reading pitch data ending **09-14**
   while the daily loop's store reached **09-18**. The board refused on that
   too.
6. **Tennis has never captured a price.** The tennis price probe was never
   successfully measured. On 09-16 it tested the Australian Open, which was out
   of season, got an empty response and recorded a "degenerate" measurement.
   Capture refuses degenerate measurements, and the daily loop never re-probed.
   Tennis capture was also refused by the blown envelope on 09-16 and 09-19.
7. **The live-game window never saved a file.** It had the same
   one-missing-path bug.

### What was fixed

| Defect | Fix | Where it runs | Proof |
|---|---|---|---|
| Capture staged nothing | stage only paths that exist; a failed add ESCALATEs **and turns the job red** | working branch (`efaf3239`, `33b1ae9e`) | **Production:** the 04:14Z slot (`dd40d351`) committed odds, credit log, props, weather, raw odds and watch files. Tests fail on the old line. |
| Live window saved nothing | same existence filter | working branch | source-level test only. **Not yet run in production**: the last window ran before the push. |
| "Too early" guard read an unbuilt store | guard refreshes the store first | working branch | 4 new tests, 1 updated |
| Cache buried the daily loop's pitch data | the afternoon slate no longer re-saves that cache | **default branch `805f48d7`**. My first push (`efaf3239`) changed only the working branch's copy, which the schedule never reads. Corrected at ~06:00Z. | pending: the afternoon board must stop citing "coverage ends 2026-09-14" |
| Tennis probe deadlock | the probe skips inactive tournaments; the daily loop re-probes degenerate measurements | working branch | 4 tests (2 fail pre-fix). **[10:00Z]** |
| Nobody acted for six days | health check flags missing checkpoints and oversized drops, and a failed save now fails the job | working branch | The health check is detection only: **nothing runs it automatically yet** (`scripts/capture_health.sh` is manual). The red-job change is automatic. |

---

## 3. Per-sport status

### 3.1 MLB — on the site, picks every day

- **The public card is V1** (`DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`). It
  ranks sides by how likely the market thinks they are. **All 88 settled game
  picks were favourites.** Its STRONG picks have a median price of −188.
- **Your value card, V2 (−160 to +250), has never run.** Its pre-registration
  (`docs/PREREG_CARD_V2.md`) is a draft waiting on your answers to questions
  12–14. Answering alone is not enough. Registration also needs a commit that
  records the parameter file's checksum and code fingerprints, plus wiring so
  the pipeline publishes V2. Plus-money V2 picks (the +100 to +250 underdogs
  you asked for) also wait for a registered read ("SR1") that hasn't run yet.
- **Your −200 rule and MLB.** V1 still publishes heavy favourites (Dodgers −375
  on 09-19) and props up to −275. I did not filter those off the page. In chat
  on 09-17 you said not to alter V1's rule midstream, and hiding picks would
  make the page disagree with its own record. V2 obeys your rule natively.
- **The season ends 09-27.** After that, MLB is postseason only. V2's own
  pre-registration grades postseason picks but doesn't count them, and puts
  its real sample in spring 2027. That makes decision 1 less urgent than it
  looks.
- **Board freshness.** The afternoon boards were blocked by the two causes in
  section 2. Both are fixed. **[afternoon 09-21]** The first lineup-gated pass
  after first pitch is the real test.

### 3.2 NFL — the new rule is live

- **Retired: NFL_CARD_V1.** It took the market favourite in every game it
  picked. It stopped at about 05:19Z on 09-21. Its picks stay in the ledger
  exactly as published, on a record of their own:
  - **Settled:** 1-0 (Bills −225, 09-17).
  - **Open:** the eight favourites from 09-20, and Rams −300 on 09-21.
- **Live: NFL_CARD_V2**, pre-registered in `docs/PREREG_NFL_CARD_V2.md` before
  any V2 pick existed (`38ff7a19`). For every spread, total and moneyline it
  compares each book's price with the **other** books' consensus on the exact
  same number, with their margin removed. It publishes only when:
  - the price is at least 2% better than that consensus **under all three
    standard vig-removal methods** (the lowest of the three is what's shown);
  - at least 5 other books quote the number;
  - the newest price is under an hour old, and each compared book is within
    30 minutes of it.

  It never takes −200 or worse. One bet per game, held once locked, and at
  most 5 per date. **This is a price comparison, not evidence the bet wins.**
- **Why "all three methods" matters.** An independent review of my first
  version found that a single method over-rates long-shot underdogs. That
  version would have picked mostly long-shot moneylines like Jets +275.
  Replayed over every NFL price we hold:
  - **One method:** 17 candidate quotes across 7 games, 16 of them long-shot
    moneylines.
  - **All three methods:** 1 candidate, a game total.
- **So expect V2 to pick rarely.** Tonight it finds nothing. The page says so.
  Nothing was loosened to make picks.
- **NFL prices were only being saved from about midnight to 4am UTC**, the same
  data-loss bug. With it fixed, daytime NFL prices persist, so Sunday day
  games can finally be judged inside their lock window. **[10:00Z]**
- **Monday night is the old rule's card.** Rams −300 was published at 04:14Z
  and 04:53Z, before V2 went live. V2 refuses to write over or merge into
  another rule's date, so Monday stays V1. It is labelled on the page as the
  old rule, with its own notice that makes no price-value claim. **V2's first
  possible card is Thursday 09-24.**
- **Not yet built:** comparing *different* numbers (+3.5 against +3), which
  needs a model of how often games land on 3 and 7. That is a hypothesis to
  test, not a known source of value (section 9).
- **Review:** my NFL and web changes went through an adversarial review before
  shipping. Each finding was independently re-checked. 26 were confirmed and
  26 fixed, and each fix was verified. The fact-check then found more that the
  review missed, now fixed too (`bc75a94a`):
  - the old-rule card carried the new rule's "value" notice;
  - the card said "Locked" while its picks were still provisional;
  - the landing page claimed three to five bets a day (the card holds 7–13).

### 3.3 Tennis — a research page, no picks, no prices yet

- **Why no picks:** grading needs final results, and The Odds API has no
  tennis results. BALLDONTLIE returned HTTP 401 for tennis results on 09-18
  and 09-19, and **still returns 401 with the new key you set at 03:42Z**
  (10:16Z run). That key doesn't include ATP/WTA results. Tennis picks need a
  BALLDONTLIE plan that does, or another results source.
- **Prices: flowing for the first time.** The 10:16Z run re-probed a live
  tournament (WTA Singapore Open) and got a valid measurement, and the first
  tennis capture followed. The research board fills as captures continue.
  Until the next deploy it says "No tennis prices have been captured yet",
  which was true when written.

---

## 4. Scoreboard — what each strategy has done

*Sources: `evidence/cards_v1.jsonl` (game picks and `prop_picks`, origin copy);
`evidence/scorecards_v2.jsonl` (latest scorecard per system). Flat 1 unit per
bet. These are small samples: they show where to look, not what works.*

### 4.1 The MLB card

| Part | Days | W-L | Units | Note |
|---|---|---|---|---|
| Game picks, all | 10 | 57-31 | **+5.58** | all 88 are favourites |
| — STRONG | | 26-5 | +8.15 | median −188 |
| — LEAN | | 17-16 | −4.44 | |
| — SLIGHT | | 11-6 | +3.64 | |
| — SPLIT | | 3-4 | −1.77 | |
| Props, all | 6 | 57-28 | **+1.41** | 38 of 85 at −200 or worse |
| — Total bases Over | | 13-5 | +2.68 | median −172 |
| — Total bases Under | | 13-5 | +2.47 | median −182 |
| — Hits Over | | 9-4 | +1.19 | median −182 |
| — Hits Under | | 22-14 | **−4.93** | median **−246** |

A 61% hit rate on Hits Under still lost money, because at −246 you need about
71% just to break even. That is the −950 problem again, on props. Total bases
is the best prop market *so far*: 26-10, +5.15u. On 36 bets, and a category
picked after seeing results, that is a lead to test, not a finding.

### 4.2 Run lines

The engine paper-tests two run-line baselines. There are 34 settled bets on
31 games, the ~14% of games where enough books quoted a run line:

- **Always the home side** (−1.5 in 33 of 34): 10-24, **−7.94u**.
- **Always the away side** (+1.5 in 33 of 34): 24-10, **+2.35u**.

This is a small, filtered first read of the "no skill" line, not a strategy.

### 4.3 The strategy engine

- **Full-game baselines are running** (always-home, market consensus,
  always-under). "Totals over" is +45.5u on 273 and "totals under" is −53.6u:
  a hot stretch for overs, not a strategy. The first-five-innings baselines
  have been silent since 09-14.
- **52 real strategies are registered** (40 full-game, 12 first-five), and 41
  have ever decided. **None has made a decision since 09-14.** Every game
  returns NO_LINEUP, including 09-15 when the afternoon pass did run. **The
  root cause is not confirmed.** Tonight's fixes may help, but I am not
  claiming they will. **[afternoon 09-21]**
- Research registry: **0 of 37 tested hypotheses survived**, and 10 of 47 are
  still pending (staging `/meta`).

---

## 5. What the evidence does and does not show

- **Does show:** every MLB card pick was frozen before first pitch and graded
  win or lose, with the ledger chain intact. Game picks are 57-31 and props
  57-28.
- **Does not show:** that any of it beats the market. Ten days (props: six) is
  noise territory. Every game pick was a favourite. No research hypothesis has
  survived its test.
- **On "proven edge":** you asked for MLB to be described as the sport with a
  proven edge. The site's own legal disclaimer says "Nothing here is a betting
  edge", and the research count is 0 of 37. I haven't used the phrase. If you
  still want it after reading this, say so, but it's a claim the evidence
  doesn't support today.

---

## 6. Access, tokens and admin

- **The sign-in box** is the private-beta invite system (`api/auth.py`).
  - **Staging** (`APP_PUBLIC_DEMO=1`) needs no token for the read-only pages.
    Saved bets, digest, onboarding, admin and billing still need a token.
  - **Production** will need a token everywhere, but production doesn't exist
    yet.
- **Testing locally without a token:** the local `sports-api` config runs with
  `APP_PUBLIC_DEMO=1`. Open `http://localhost:8000/web/index.html`.
- **Staging's admin token is set,** but I don't know its value, so no one here
  can mint a staging invite. Staging doesn't need one for the pages you'd test.
- **Giving yourself access on the real site**, once production exists:
  1. Create the app (section 7).
  2. Set a long random admin secret on it:
     `fly secrets set APP_ADMIN_TOKEN=... --app linehound-prod`. Type it
     yourself; never paste it in chat.
  3. Create your invite:
     `curl -X POST "https://linehound.app/admin/invites?email=YOU" -H "X-Admin-Token: <that value>"`.
  4. Paste the returned token into the sign-in box.

  *Note:* the invite endpoint takes the email in the URL, so it ends up in
  access logs. It's worth changing to a request body before real customers use
  it.

---

## 7. Deployment

- **Staging** (`linehound-staging.fly.dev`): live, open demo mode, redeployed
  tonight. The last deploy was at about 05:19Z (run 35564172145) and includes
  NFL V2 and the web changes. Tonight's later honesty fixes redeploy
  automatically.
  - **Missed in the incident:** staging went **about 37 hours without a
    redeploy** (09-19 15:12Z to 09-21 04:03Z). It bakes data into its image,
    so on 09-20 it showed neither that day's MLB card nor the NFL card.
- **Production** (`linehound.app`): not live. The domain doesn't resolve yet.
  It takes several steps on your side, not one:
  1. `fly apps create linehound-prod`.
  2. Create a volume.
  3. Set `APP_ADMIN_TOKEN`.
  4. Provide a deploy token (or add `FLY_ORG_TOKEN` as a secret).

  There is also **no production deploy workflow yet**, and the runbook's
  legal-copy sign-off is still open. After that: `fly certs add linehound.app`
  and the two DNS records in `deploy/CLOUDFLARE.md`. **Never point the domain
  at staging.** Its open demo mode would give the paid product away free.

---

## 8. Subscriptions and credits

| Service | Status | Needed for |
|---|---|---|
| The Odds API (100k/month) | 9,634 left at 05:33Z; floor 5,000; reset **assumed** 10-01 | all odds capture, every sport |
| BALLDONTLIE | new key set 03:42Z; **tennis results still 401 with it** | tennis grading (needs a plan with ATP/WTA); NFL stats and props |
| API-Tennis | trial expired | not needed if BALLDONTLIE works |

**Credits.** About 4,600 are usable above the floor. At the floor, every paid
capture stops, for MLB and NFL alike.

- **If the old burn continues** (1,400–1,650/day): the floor arrives around
  **09-24**, before the last MLB weekend and NFL Sunday 09-27.
- **If the fix makes the 900/day budget actually bind:** around **09-26**.

Since the fix: **280 spent on 09-21 by 10:20Z**, about 24 an hour overnight,
with a checkpoint every slot so the 900 budget can now actually bind. The
daytime MLB prop buying that dominates spend has not happened yet. If 09-21
ends under 900, the floor is about 09-26, five days before the assumed
10-01 reset.

**BALLDONTLIE and the NFL** (from its published spec):

- NFL odds, player-prop odds and advanced stats need the **GOAT** tier
  ($39.99/mo) or the ALL-ACCESS bundle.
- NFL box scores and season stats need **ALL-STAR** or higher.

An MLB-only plan does not cover NFL.

---

## 9. What's next, ranked (with the season ending in mind)

1. **Confirm tonight's fixes held in production.** Three things to check:
   - the afternoon MLB board builds with fresh pitch data;
   - tennis captures its first prices;
   - the new 7-day settle window grades each date exactly once (MLB 09-20 and
     NFL 09-20 are unsettled; NFL 09-17 must not be graded twice).
2. **NFL, because it runs all winter.** Two things to test:
   - **NFL player props via BALLDONTLIE**, if you want the GOAT tier (decision
     4);
   - **the key-number hypothesis** (is +3.5 against +3 worth more than its
     price?), using historical NFL scores. It will be pre-registered as its
     own rule before any result is read.
3. **MLB shadow forward tests are live** (`MLB_VALUE_SHADOW_V1`, registered in
   `d1208df6`, merged `a179a233` at 07:37Z). There are four arms, each with its
   own record, never pooled and never on the public card:
   - total bases;
   - hits;
   - run line (±1.5);
   - game total.

   Each uses the NFL V2 method: a price must beat the other books' consensus
   on the same line by 2% under all three vig-removal methods, and never at
   −200 or worse. They went through two independent reviews (8 defects, then
   2 more, all fixed) before merging. **What to expect, stated before any
   result:**
   - **Total bases:** probably **nothing**. Across 18 days of stored prices,
     books agree to within 2% after removing their margin. That is a real
     finding about the market, not a bug.
   - **Hits:** at most 4 books ever quote a hits line both ways, so this arm
     compares against only 2 other books. It is labelled **THIN_CONSENSUS** on
     every row.
   - **Run line:** about 0.3 decisions a day. **Game total:** rarer.

   With the regular season ending 09-27, this is mostly a working harness for
   the postseason and next spring.
4. **MLB V2**, when you answer decision 1. There's little regular season left,
   so it mainly sets up next spring.
5. **Credits** (decision 2).
6. **Deferred:** the 11 "Algorithm Renaissance" research documents from the
   09-17 plan are **unwritten**. Their list is in the 09-17 plan, not in the
   repo.

---

## 10. Decisions that are yours

1. **MLB V2.** Accept the written defaults for `docs/PREREG_CARD_V2.md`
   questions 12–14?
   - 12: register the family as section 17 describes.
   - 13: the published card keeps the strict bar while the loose arm runs on
     paper.
   - 14: the layout experiment licenses a rendering change only.

   After a yes, I do the registration commit and pipeline wiring. Plus-money
   picks still wait for the SR1 read.
2. **Credits.** If the post-fix burn stays above 900/day: move to a higher Odds
   API tier, or accept a smaller daily budget that captures less?
3. **Production.** When you want linehound.app live, the steps in section 7
   are yours (app, volume, secrets, deploy token).
4. **BALLDONTLIE plan.** Your new key still gets HTTP 401 on tennis results.
   Pick what you want covered:
   - **ATP/WTA results**, to grade tennis picks at all;
   - **NFL GOAT** ($39.99/mo), for NFL player props and odds;
   - both.

   Without ATP/WTA results, tennis stays a research page with prices and no
   picks.

---

## 11. Overnight verification log

- [x] **The capture fix is pushed and proven in production.** The first slot
  on the new code (04:14Z, `dd40d351`) committed `data/processed/*`, raw odds
  and watch files. Before it, slots committed `data/historical` only.
- [x] **Credit checkpoints land every slot again.** 04:14Z to 05:33Z: every
  slot, all capture families, longest gap 12.8 minutes (on 09-19 there were
  none for 11.6 hours).
- [x] **NFL V2 and the web go-live shipped** (`38ff7a19` is the NFL_CARD_V2
  registration commit; `5792eebe` is the web change) after the 26 review
  findings were fixed and re-verified. **Staging was redeployed** (05:19Z) and
  checked live:
  - NFL, tennis and the new footer render;
  - all three sport tabs are visible on a 375px phone;
  - every API route returned 200.
- [x] **The fact-check's corrections are fixed:**
  - capture failures now turn the job red (`33b1ae9e`);
  - the site-honesty items (`bc75a94a`): no false pick count, no value claim
    on old-rule cards, no "Locked" while provisional;
  - the cache fix is on the branch the schedule actually runs (`805f48d7`).
- [x] **Tests.** Before tonight's last round, the local suite showed 49
  failures + 2 errors against a 54 + 2 baseline. The one new failure in that
  run (a lock-time assertion) was fixed and its module re-run clean. Every
  remaining failure is a pre-existing Windows-environment one.
- [x] **The CI test gate is green on all three Pythons** (run 35572479590),
  for the first time since 09-16. The last three failures were:
  - one test's module-cache surgery, which broke two others (`05a5ceab`);
  - a test that needed local-only data (`73e77e1e`).

  A red gate hid the very test that flagged this incident on 09-18. A new
  regression will now actually show.
- [x] **MLB shadow forward tests are merged and running in production**
  (`a179a233`, 07:37Z) after two independent reviews. The first capture slot
  on them (07:41Z, run 35574127485) ran all four arms cleanly and committed.
  No decisions yet, correctly: every game was more than 4 hours from first
  pitch. CI is green on the merge (run 35573833475).
- [x] **Tennis probe fixed, and capture started.** The 10:16Z daily loop
  (run 35587312001) probed WTA Singapore Open: 1 credit per event, a valid
  measurement. The credit log then shows the first-ever
  `tennis_capture.run`.
- [x] **Tennis results with your new BALLDONTLIE key are still HTTP 401.** The
  key does not cover ATP/WTA results, so tennis still can't grade picks.
- [x] **The new 7-day settle window worked the first time in production.**
  - MLB: 1 date checked, 1 settled (09-20). The card is now **66-34, +8.21u
    over 11 days**.
  - NFL: 1 date checked, 1 settled. The old rule's 09-20 card went 5-3,
    **−1.03u**.
  - NFL 09-17 was not re-graded.
- [x] **Credits so far today:** 280 by 10:20Z, about 24 an hour overnight
  since the fix. The daytime rate is still to come.
- [x] **Pitch data advanced to 09-20** in the daily loop. With the cache fix on
  the default branch, the afternoon slate should now read it.
- [ ] **New: the MLB engine placed 84 paper bets on NFL games on 09-20**, so
  engine settle refused 09-20 (a new ESCALATE; the job correctly went red).
  It is not from tonight's changes (09-17 had one). The engine reads the
  shared odds store without a sport filter. **Fix in progress** for the 13:31Z
  retry.
- [ ] **[afternoon 09-21, after you wake]** the afternoon MLB board builds
  without "coverage ends 2026-09-14", and the genomes decide.
- [x] **Monday's NFL card:** neither V2 nor empty. It is the old rule's Rams
  −300, published before V2 went live and labelled as such. V2 starts
  Thursday.
