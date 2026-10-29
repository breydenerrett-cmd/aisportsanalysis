# Ads, 2026-10-29 (DRAFT: nothing is bought, uploaded or launched)

Built from `docs/VOICE.md` (2026-10-20 positioning), `docs/PRICING_OFFER_VALIDATION.md` and the founding offer ($14.99/mo, first 50 seats, standard $19.99/mo), `docs/sales/channels.md`.

## Most consequential finding (from the creative-strategy review at the end)

Paid ads cannot cover costs by 10-31. At $5 to $20 a day, three days buys roughly 10 to 60 clicks per channel, with a conversion rate nobody has measured (0 messages, 0 signups, 0 sales on `docs/SURVIVAL_DASHBOARD.md`). Treat ads as a hypothesis lab that starts the data clock for November; the DMs and X plan are the 10-31 push. Also: all three platforms restrict gambling-related ads, and whether a paper-betting product counts is UNVERIFIED. Apply for approval or confirm the category before spending a dollar (see "Policy gate" below).

## Copy rules (all ads)

- Paper bets only; the record is public and shows losses. Never claim results of any kind; never imply a hound will do anything.
- No prices of picks. No -200 or worse anywhere. No Bet Check. No sportsbook links.
- Banned words: the owner's banned-word list in `tests/test_customer_language.py` plus the 2026-10-29 additions; grep this file's ad copy before use. The product calls them hounds.
- Every ad carries: `21+. Paper bets, not advice. Bet at your own risk. 1-800-GAMBLER.` (**[RG]**). Targeting 21+ only; no targeting that implies problem-gambling interest.
- Landing page: `https://linehound.app/web/...` with `utm_source`, `utm_medium=paid`, `utm_campaign=ads_1029_<id>`. The first thing the visitor sees must be what the ad promised (Pass 6): the ad headline's promise appears at the top of the page, and the first ask is "build a hound free," not the $14.99 checkout.

## The emotional job

Not "AI betting tool." The job: **stop arguing about who is right and see who is right, with the record in public.** The moment before the ad: a bettor has just watched someone post a screenshot of a hot streak and wondered if it was cherry-picked. The consequence they fear: trusting an invisible record. The unclaimed position: **the record is the product, losses included** (Pass 3, tag HYPOTHESIS: competitor ad libraries were not observed; see Verify).

## Five short-video scripts (15 seconds each; captions carry the argument with sound off)

Beat structure for each: 0-1.5s thumb-stop, 1.5-6s demo/recognition, 6-12s proof, 12-15s ask + [RG] on screen.

**V1. "One sentence" (tests: does showing the building act beat explaining the product?)**
- 0-1.5s: Close-up of hands typing on a phone: "home favourites after a night game, nothing pricier than -150." Caption: "I typed one sentence."
- 1.5-6s: Screen shows the sentence parsed back into plain English rules.
- 6-12s: A hound card appears with a record page, bet count visible. Caption: "It has a public record now. Paper bets only."
- 12-15s: "Build yours free." [RG] on screen.

**V2. "The graveyard" (tests: does leading with a failure beat leading with the build?)**
- 0-1.5s: A headstone on screen with a hound name and a record. Caption: "This hound lost. It's in public."
- 1.5-6s: Scroll the record: every bet, every loss, timestamps.
- 6-12s: Caption: "Take them out back. The record stays."
- 12-15s: "Build a hound that can lose in public." [RG].

**V3. "Hound vs coin" (tests: does the control framing beat the personality framing?)**
- 0-1.5s: A coin flips toward the camera. Caption: "Can your idea beat this?"
- 1.5-6s: Cut to Coin-Flip Collie's record page next to a member's hound.
- 6-12s: Caption: "Same bets. Same slate. Public. Paper."
- 12-15s: "Test your idea against a coin." [RG].

**V4. "Group chat" (tests: social-comparison hook vs solo-curiosity hook)**
- 0-1.5s: Over-the-shoulder shot of a phone group chat: "I'm the best at picks lol."
- 1.5-6s: Reply typed: "Prove it." Cut to a leaderboard.
- 6-12s: Three friends' hounds ranked, bet counts shown, one at the bottom.
- 12-15s: "Settle it in public. Fake money." [RG].

**V5. "Trash talk" (tests: character voice vs plain product voice)**
- 0-1.5s: Big text: "Chalk Chihuahua took the favourite. Again."
- 1.5-6s: Its record, bet count first, then its biggest loss, shown plainly.
- 6-12s: Caption: "It might lose. It will say so."
- 12-15s: "Meet the pack." [RG].

Production note: keep a person in frame (hands, back of head, a phone in a hand) rather than a pure UI recording; do not render faces with generative video; reject any cut where UI text morphs between frames.

## Ten static ad concepts

Each: headline, body, image idea (the picture must make the argument with the copy covered), hypothesis tested. All include [RG] in the footer line.

| # | Headline | Body | Image (works with copy covered) | Tests |
|---|---|---|---|---|
| S1 | Type a betting idea. Watch it play out. | Build an AI hound from one sentence. It paper-bets in public. Losses included. | A thumb over a phone with a sentence in a text box and a hound card below it | Does "build" beat "track"? |
| S2 | The record you can't edit. | Every bet timestamped before the game. Wins, losses, the lot. Paper money. | A record table with a visible red loss row highlighted | Is honesty the unclaimed angle? |
| S3 | This hound lost 7 straight. It's still on the board. | Take them out back. The headstone keeps the record. (Replace "7" with a real number.) | A headstone card with a hound name and a streak | Does a failure-first creative stop the scroll? |
| S4 | Settle the group chat. | Everyone builds a hound. Same slate. Public leaderboard. Fake money. | Three phone screens side by side, ranked | Social-proof vs curiosity |
| S5 | Can your idea beat a coin flip? | Coin-Flip Collie is the control. Put your hound next to it. | A coin on a record sheet | Skeptic hook |
| S6 | 50 founding seats. $14.99/mo. | Build and own AI hounds. Paper bets, public record. Standard price is $19.99. | A "47 of 50" style seat counter graphic (only use a real seat count) | Scarcity: does a real cap lift conversion vs S1? |
| S7 | Trash talk, with receipts. | Our hounds call their shots before the game, then post the result. Even the bad ones. | A speech bubble over a record line | Voice test |
| S8 | Your sentence, graded. | "Totals only when both starters go deep." Typed it. Here's its record so far. (Use a real hound.) | A sentence above a mini record chart with bet count | Specificity vs generality |
| S9 | Meet the house pack. | 21 hounds, each with a rule, all paper-betting in public. Build one to run against them. | A row of hound avatars with W-L under each | Pack/collection appeal |
| S10 | Free to build. Nothing to bet. | No real money moves through us. 21+. Build a hound and see how your idea holds up. | A phone showing a build screen with a "$0" label | Risk-reversal wording |

Variation discipline (Pass 2): families vary one dimension only. Family A (message): S1, S2, S5, S10. Family B (proof type): S3, S8, S9. Family C (offer): S1 vs S6. Family D (voice): S7 vs S4. Do not run families against each other in the same ad set.

## Test campaign structure, $5 to $20 a day

Total proposed ceiling: $30 a day across channels for 7 days = $210 max. Owner approves any spend; none is authorised by this file.

| Channel | Budget/day | Structure | First creatives | Audience |
|---|---|---|---|---|
| Meta | $10 | 1 campaign (traffic to landing page, then switch to conversions after 50 events), 2 ad sets: A = interest in sports betting analysis/fantasy sports, B = lookalike off the founding list once n >= 100 (not before), 3 ads each: V1, S2, S4 | V1, S2, S4 | 21+ only; US states where you have confirmed it is lawful; exclude gambling-addiction interests per Meta's rules |
| X | $10 | 1 campaign (website traffic), 1 ad group per family, promote the best organic post from `X_PLAN.md` rather than building a separate ad | Day 1 and Day 7 build demos; the Day 3 record recap | Followers of sports-betting accounts you have lawfully identified, keywords, 21+ |
| Reddit | $5 | 1 campaign, 2 communities (a baseball and a stats-minded sub) as conversation placement, 1 ad each: S2, S5 | S2, S5 | 21+ if the platform allows; check r/ rules for ad exclusion |

Hypothesis table (the same ID in the platform's ad name, e.g. `1029_M_V1_build`):

| Ad | Hypothesis (pre-registered; one sentence) |
|---|---|
| V1 | Showing the building act beats a product description on cost per signup |
| V2 / S3 | Leading with a loss earns more clicks per impression than leading with a build |
| V3 / S5 | A control framing ("beat a coin") attracts more skeptics who finish a hound |
| V4 / S4 | A social hook beats a solo hook on signups |
| V5 / S7 | Character voice beats plain voice |
| S2 | "The record you can't edit" is a stronger unclaimed angle than "build" |
| S6 | A real seat cap raises click-to-checkout vs S1 |
| S8 | A real example beats a general promise |
| S10 | "Nothing to bet" wording lowers click-through among bettors but raises signup completion |

### What a lead can cost (Pass 9)

- Revenue per customer in month 1: $14.99 (founding) or $19.99. Retention, refunds and months stayed are UNKNOWN (0 customers). Stripe fees and chat/AI costs per member: UNKNOWN; verify from `config/business.json`.
- Do not set a CPA ceiling from guessed lifetime value. Use this rule for the test only: a signup (free account) is worth $0 to the business today; a paid founding seat is worth $14.99 in month 1. A first-month payback target would cap CPA near $15. With unknown conversion from free signup to paid, assume it cannot be met by cold ads until measured. The binding constraint is probably signup-to-paid conversion on the page, not the creative (HYPOTHESIS).

### Kill rules (applied per ad, not per campaign)

Let N = impressions and C = clicks. Evidence is tiny at these budgets; these rules stop obvious waste, they do not declare winners.

1. **Disapproved or flagged for gambling policy:** stop that channel, do not appeal by changing wording to evade the review. Ask the owner.
2. **No clicks:** after 1,000 impressions with fewer than 5 clicks (under 0.5% CTR), kill the creative.
3. **Clicks, no signups:** after 30 landing-page visits with 0 free signups, kill the ad and check the landing page match first (Pass 6) before blaming the ad.
4. **Spend cap with no paid seat:** a channel that has spent $60 with 0 paid founding seats and fewer than 5 signups is paused; ask the owner before more spend.
5. **A "winner" needs repeat evidence:** at least 10 signups from the ad, and the same direction on a second day, before it gets more budget. One day of 3 signups is not a winner.
6. **Any complaint or a minor-targeting concern:** pause immediately.
7. **Hard stop:** total ads spend above $210 without a paid seat from ads = stop for a decision.

### Policy gate (UNVERIFIED; check before spending)

- Meta, X and Reddit each have gambling-ad rules that vary by country and by whether gambling is real-money. A paper-betting product that talks about "bets" may be classified as gambling. I did not fetch current policies in this task. Owner: read each platform's current gambling-advertising policy page and, where permission is required, apply before launching. Do not route around a rejection.
- 21+ only, US states you can lawfully serve. Do not target people by gambling problems or financial stress.

## Creative strategy review (applied to the above)

**Passes run:** 1 (job), 1b (image argument), 2 (variation), 5 (truth and exposure), 6 (promise survives the click), 8 (quality vs publishability), 9 (lead cost), 10 (evidence labels).
**Not run:** 0 (nothing was rendered: these are scripts and concepts, so every judgement is provisional), 3 (saturation: the Meta Ad Library and competitor ads were not observed; "unclaimed" is only a HYPOTHESIS), 4 (fit check against competitor mechanisms: no competitor tactic copied), 7 (no QA artifact to try to break).

- **Kill (invisible or risky):** S1 as the headline lead is close to generic AI-tool copy (`SECONDARY_EVIDENCE` only: no ad-library look). Rewrite it so it names the sentence (S8) rather than "AI hound." V3 relies on a coin image that can read as the product being a coin flip; keep it for X and Reddit only, where skeptics gather. Any "units up" creative is killed outright: it implies results and the record is not a selling point we can lead with.
- **Keep:** V1, V2, S2, S3, S4, S8. Each tests a single named hypothesis and each has a human, social, or specific hook. The failure-first angle (V2/S3) is the sharpest differentiator, because betting ads habitually show wins. It is also the riskiest on a thumb: test it, do not assume.
- **Open (ranked):** (1) public record with losses ("the record you can't edit": real capability behind it: hash-chained public record), (2) the hound graveyard ("take them out back": capability exists: culls, headstones), (3) one-sentence build (capability exists: English parser, `src/hounds/english/parser.py`). Rank 1 and 2 are labelled HYPOTHESIS until the ad library is read in a real browser (a plain fetch returns a shell with no ads).
- **Fix:** S6 and S3 contain placeholders (seat count, streak length): never run them with a made-up number. S10's "$0" label must match what the page shows (free account) before running. V1 and V4 show a UI; confirm the screenshot has a visible bet count so the "small sample" honesty is in the pixels, not only the caption.
- **Verify (claims that cannot run until someone confirms them):** how long the $14.99 founding price is held, the 50-seat count and live seats left, the platform gambling policies, which US states are lawful to target, that the 21+ and 1-800-GAMBLER lines render on the landing page footer, and the real record numbers for any ad that quotes them.
- **Spend:** $0 so far. Proposed cap $210 for 7 days; first-month revenue per founding seat is $14.99, so a paid seat from ads at over $15 is a month-1 loss and only pays back if members stay (retention UNKNOWN).
- **Quality vs publishability (Pass 8):** creative quality is decent on V1, V2, S2, S3; publishability is blocked on the policy gate, the live-number fills and the founding-price wording. Good work, blocked; not bad work.
