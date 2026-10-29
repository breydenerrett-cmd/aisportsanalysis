# Lead ideas, ranked by cost and speed (2026-10-29, DRAFT: nothing launched)

Context: 0 of 50 founding seats sold, 0 messages sent, 0 leads logged (`docs/SURVIVAL_DASHBOARD.md`); cost-cover deadline 2026-10-31. Facts used: the owner can grant free access from https://linehound.app/web/admin.html (People, Add person, Give free access; `docs/owner/YOUR_STEPS_2026-10-28.md`); the referral loop is SPEC ONLY and not built (`docs/REFERRAL_LOOP_SPEC.md`); a Discord channel feed exists as a drafted offer ($149/server, `docs/sales/scripts.md`, `docs/offers/COMMUNITY_FEED_OFFER.md`); hound pages unfurl as share cards (`src/hounds/share_page.py`).

Every idea keeps the copy rules: paper bets only, no results claims, 21+ and responsible-gambling wording, no Bet Check, no -200 or worse, builder disclosed, send nothing without the owner.

Scoring: cost in dollars and owner time; speed to a first lead; what is UNKNOWN is said plainly. Nothing below has measured conversion.

## Ranked list

| Rank | Idea | Cost | Speed to first lead | Build needed | Biggest risk |
|---|---|---|---|---|---|
| 1 | Manual referral seats (friends and family first) | $0, about 1 hour | Hours | None (owner grants seats and codes by hand) | Small pool; relatives who don't bet |
| 2 | "Beat the house pack" contest, prize = one free month | $0 cash; one free month costs only the member's marginal cost (about $0 if no paid seat is displaced; UNKNOWN per-member AI cost) | 1 to 3 days to announce; results at 14 days | Light: a one-page rules post plus manual check of the board | Contest rules/legal; prize must not be money; run "no purchase necessary" |
| 3 | Creator-owned hound partnership ("[Name]'s Hound") | $0 cash, free seat; 1 to 2 hours per creator | 3 to 10 days | Small: hound with creator's name, a share link with UTM | Creators saying anything about results; we must not script claims |
| 4 | Public hound leaderboard challenge (members and friends vs each other) | $0; about 2 hours | 2 to 7 days | None if the existing public board is used | Needs a few initial participants to look alive |
| 5 | Discord channel feed for communities (bot posts record into one channel) | $0 to try; price is $149/mo per server (UNVERIFIED willingness) | 7 to 14 days (permission loops) | Exists in draft; verify the bot's current state | Discord rules: bot must never DM or advertise; Discovery may exclude gambling-adjacent servers |
| 6 | FiveM / gaming community tie-in (owner's own server first) | $0; owner time | 1 to 5 days | None | Under-21 members: only 21+ gated areas; owner's players are not all bettors |
| 7 | "Roast my take" content hook on X (reply with a hound built from the sentence) | $0; owner time per reply | Days | Light: per-reply hound build by hand | Looks like spam if overdone; X automation rules (hand-posted only) |
| 8 | Share-card links from member hounds (people post their own hound page) | $0 | Slow ramp | Exists (`share_page.py` unfurl) | Needs members first |
| 9 | Podcast / newsletter guest segments | $0; 1 to 3 hours per pitch | 1 to 3 weeks | None | Slow; deadline passes first |
| 10 | Paid ads (Meta, X, Reddit) | $5 to $20/day | 1 to 3 days to start, weeks to read | See `ADS.md` | Policy approval, no measured conversion, can't pay back by 10-31 |

Top 3 and why: rank by (a) no cash, (b) first lead inside the deadline, (c) honest with the record. Ranks 1 to 3 satisfy all three. Rank 5 pays the most per customer ($149/mo) but is slowest to start.

## The ideas in detail

### 1. Manual referral seats
- **What:** Skip the unbuilt referral system. The owner gives each of 10 close contacts a founding seat and asks each to bring two people. Track who came from whom in `docs/sales/outreach_queue.csv` (`via_lead` column exists).
- **Reward (decide before sending):** "+7 days free for each person who stays a month," which matches `REFERRAL_LOOP_SPEC.md`'s rule (7 days each, only after a paid month with no refund). Granting is manual: no automation exists.
- **Copy (X or text):** "Founding seats are $14.99/mo for the first 50. Bring two friends who like sports and you each get a week free once they've stayed a month. It's a paper-betting game with a public record, 21+." [RG]
- **Do not:** pay cash, promise results, or reward self-referrals. Counsel review of incentive terms is pending in the spec; flag it, do not skip it.

### 2. "Beat the house pack" contest
- **Mechanic:** members build a hound, it runs 14 days, and the hound that ranks above the house pack's median on the public board wins a free month. Ranking uses the platform's own rule ("Ranked in full at 20 settled bets"); a hound with fewer settled bets is shown as unranked.
- **Why it works for us:** it spends the product's honesty (public board) as the hook, and it makes no promise of results because the prize is a free month and the money is fake.
- **Copy:** "Build a hound. Run it 14 days. If its public record outranks the median house hound, you get a free month. Paper bets only. 21+. No purchase needed to enter: free accounts are eligible." [RG]
- **Rules to write (owner/counsel):** no purchase necessary, one entry per person, dates, ranking rule, how a tie is decided, void where prohibited. UNVERIFIED: sweepstakes/contest law varies by state; get one line from counsel before announcing publicly. Small prize and skill-based mechanics lower risk but do not remove it.
- **Honesty note:** a prize winner is chosen by who ranks highest over a short window; at 14 days luck dominates. Say so in the rules ("short samples reward luck").

### 3. Creator-owned hound partnership
- **Mechanic:** a creator describes one betting rule in a sentence. We build "[Name]'s Hound" and give them a share page with a tracked link. They report the record weekly, good or bad. They get a founding seat free; they pay nothing and receive no commission in this first version.
- **Disclosure:** creators must label the partnership per the platform's and FTC's rules. We do not script outcome claims.
- **Pitch:** see `DMS.md` Group 5.
- **Measure:** signups and paid seats by the tracked link only.

### 4. Public hound leaderboard challenge
- Create a "founding 50" board where each member's hound is listed with its bet count. People share their own hound page. Cost zero; needs the first 5 to 10 hounds so the board does not look empty.

### 5. Discord channel feed
- Offer a server owner a 7-day free trial of the daily record post in one channel (price $149/mo is the existing draft; unvalidated). A bot must be installed by the server admin; it must not DM or advertise. See `docs/sales/channels.md` for the rule text.
- **Better angle (HYPOTHESIS):** instead of selling the feed, offer a server its own "house league" leaderboard so members build hounds; the feed is the byproduct.

### 6. FiveM and gaming communities
- The owner runs LetsBeCops; start with its own staff and an adults-only channel. Offer a staff "build a hound night." Do not market to minors; 21+ gated channels only.

### 7. "Roast my take"
- Hand-write replies to public takes with a hound built from that take's sentence and a link to its record page. Hand only, a few per day, always labelled as the builder's account. No automation (X rules; see `docs/sales/channels.md`).

### Anything better, ranked as a candidate (HYPOTHESIS)
- **A free "hound for your handle" gift:** build a hound from a person's own public pick-style sentence and DM the record link before asking for anything. Highest personalisation, owner time heavy, no cash. Use for 10 targeted accounts, not 100.
- **Win-back from the 37 queued people** in `docs/sales/outreach_queue.csv`: none contacted yet, so start there before spending on anything.
- **Local sports bars or fantasy leagues:** offer a printed QR leaderboard for a league night, paper bets only, 21+. Slow, UNVERIFIED.

## What to do in the 3 days left

1. Day 1 (10-29): send Group 1 and Group 3 DMs (`DMS.md`); post X Day 1 posts (`X_PLAN.md`); start idea 1 with 10 people.
2. Day 2 (10-30): send Group 5 creator DMs; publish contest rules after one line from counsel; send Group 4 to FiveM staff.
3. Day 3 (10-31): the honest ask post, recap, count seats.
Expected result: UNKNOWN. A single paid seat is $14.99 in month 1; 50 seats would be $749.50/mo, against the stated gap of $278/month, so about 19 seats cover the planning-assumption burn if they stay. No conversion rate has been measured; do not forecast beyond that arithmetic.
