# LineHound outreach channels: what the rules actually say

Research date: 2026-10-01. Research only; nothing was posted, joined, messaged, signed up, or logged into.
Every message is sent by hand by Brey from his own accounts.

## Read this first: what was and was NOT read first-hand

| Evidence tier | Meaning | Channels |
|---|---|---|
| FIRST-HAND | Page loaded and the rule text was read on 2026-10-01 | Discord (ToS, Community Guidelines, Platform Manipulation, Gambling explainer, Developer Policy, Community Server Guidelines), Disboard Guidelines, top.gg add-server page, X (help.x.com Authenticity / platform manipulation), Covers forum Guidelines, SBR forum FAQ, TheRX Site Promotions forum header |
| SECOND-HAND | Only a summary by a third party or a search-engine snippet | All Reddit communities (see below), Discord Discovery gambling exclusion, Discord server monetization policy |
| NOT READ | Page failed to load or rules not found | Reddit sidebars/wikis (blocked), top.gg server-listing terms (403), Disboard ToS (not opened), Wizard of Vegas forum (404 on the sports URL), Pregame forums (HTTP 500), TrustMyRecord forum rules (forum loads, rules not found) |

**Reddit gap (important).** reddit.com, old.reddit.com and redditinc.com are refused by my research tooling (WebFetch, browser pane and WebSearch all reject them). I therefore could NOT read any subreddit's rules. Every Reddit status below is PROVISIONAL and must be confirmed by Brey reading `reddit.com/r/<sub>/about/rules` before any post or modmail. That takes about 10 minutes for the ten subs in targets.csv. Rows for Reddit in targets.csv carry `checked = NOT_FETCHED` and do not count as verified.

## Summary

| Channel | Status | Compliant route | Main risk |
|---|---|---|---|
| Discord: DM a server owner | ALLOWED WITH CONDITIONS | One hand-written DM per owner, or the server's ticket/mod channel; never bulk | Report to Discord, DM-spam filter on a new account, owner annoyance, ban from the server |
| Discord: posting in a server's channels | NOT ALLOWED unless the server's rules or owner say so | Ask first via ticket/DM | Instant ban |
| Discord: bots or user-account automation for outreach | NOT ALLOWED | Do not do it | Account termination |
| Discord: our bot posting the card inside a server | ALLOWED WITH CONDITIONS | Server admin installs an official bot account; bot never DMs users, never advertises | Developer Policy removal if it DMs or markets |
| Disboard / top.gg / Discord Discovery as a lead source | ALLOWED (reading public pages) | Read listings; do not scrape; no auto-bump | Cloudflare rate limit (hit it myself, HTTP 429) |
| Disboard / top.gg / Discovery listing LineHound's own server | ALLOWED WITH CONDITIONS | Manual bumping only; list a real server | Auto-bump ban; Discovery may exclude gambling-adjacent servers (second-hand) |
| Reddit r/sportsbook, r/sportsbetting | UNVERIFIED, treat as NOT ALLOWED to promote | Participate; modmail to ask; no product posts | Removal, ban, site-wide shadowban |
| Reddit r/algobetting, r/EVbetting, r/NFLBETS, r/sportsgambling, r/baseballbetting | UNVERIFIED, ALLOWED WITH CONDITIONS at best | Modmail for permission first; feedback post without link | Removal, ban |
| Reddit r/mlb, r/baseball, r/nfl, r/fantasyfootball, r/dfsports, r/MMAbetting | UNVERIFIED, assume NOT ALLOWED | Do not post a product; comment normally only | Removal, ban |
| Reddit r/SideProject, r/alphaandbetausers, r/startups feedback thread | UNVERIFIED, likely ALLOWED WITH CONDITIONS | Maker-style post, disclosure, designated thread | Removal if rules differ; low audience fit |
| X: replies to betting accounts | ALLOWED WITH CONDITIONS | Individual, relevant, non-duplicative replies; no bulk | Spam enforcement, mute/block |
| X: DMs | ALLOWED WITH CONDITIONS | Only to open DMs; unique text each time | "bulk, aggressive" DM enforcement |
| Covers forum: Website Promotions | ALLOWED | Create a thread there (free account) | Moderator discretion |
| Covers forum: all other forums | NOT ALLOWED | Participate only | Suspension or ban |
| SBR forum | NOT ALLOWED | Do not promote, including PMs | Immediate ban |
| TheRX Site Promotions forum | ALLOWED WITH CONDITIONS | Post there | Hostile audience; records unverified by site |
| TrustMyRecord forum | UNKNOWN (rules not found) | Read rules, contact via footer link | Peer platform may see you as a competitor |

### Every channel where outreach is NOT allowed (consolidated)

1. Discord: automated or bulk DMs, self-bots/user-bots, auto-messaging (Discord ToS section 9; Community Guidelines 13 and 14).
2. Discord: posting promotion inside a server without the owner's permission (server rules; not Discord-wide, but near-universal).
3. Discord: our bot DMing members or marketing to them (Developer Policy items 5 and 6).
4. Reddit r/sportsbook and r/sportsbetting (provisional, second-hand: strict anti-tout enforcement; no product posts).
5. Reddit r/mlb, r/baseball, r/nfl, r/fantasyfootball, r/dfsports, r/MMAbetting (provisional: fan or app communities; assume no promotion).
6. Covers forum: every forum except Website Promotions (Guidelines).
7. SBR forum: everywhere, including private messages and user statuses (SBR FAQ).
8. Sportsbook or casino referral links anywhere in a post (SBR FAQ; Covers Guidelines bar pick-service and advertising links outside Website Promotions). LineHound should carry no affiliate links at all.
9. X: bulk, aggressive, high-volume unsolicited replies, mentions or DMs, and identical DMs (X platform rules).
10. Disboard: automated bumping or any scripted action on the site (Disboard Guidelines).

---

## 1. Discord

### 1a. Unsolicited DMs and automation: the ToS clauses (FIRST-HAND, read 2026-10-01)

Sources and quotes:

- **Terms of Service**, `https://discord.com/terms`, Effective September 29, 2025 / Last Updated August 29, 2025, section 9 "Restrictions on your use of Discord's services": "exploiting, harassing, bullying, spamming, auto-messaging, or auto-dialing people through our services". Same section: "scraping our services without our written consent, including by using any robot, spider, crawler, scraper, or other automatic device, process, or software".
- **Community Guidelines**, `https://discord.com/guidelines`, same effective date: item 13 "Do not send unsolicited bulk messages (or spam) to others." Item 14 "Do not use self-bots or user-bots. Each account must be associated with a human, not a bot." Item 26 "Do not coordinate or participate in illegal gambling. Users are responsible for complying with applicable gambling laws and regulation."
- **Platform Manipulation Policy Explainer**, `https://discord.com/safety/platform-manipulation-policy-explainer`: spam "can be sent by automated accounts designed for this purpose (spambots), normal user accounts that manually execute spammy actions, as well as by user accounts modified to perform automated actions (self-bots)". So hand-sent messages can still count as spam if they are spammy.
- **Gambling Policy Explainer**, `https://discord.com/safety/gambling-policy-explainer`, March 15, 2024: the policy targets illegal gambling (a real-money wager, real-world prizes, chance-determined outcome, prohibited by law). It says nothing against discussing picks or analysis. LineHound takes no bets, so it is outside that definition, but Brey remains responsible for local law.

**Is DMing a server owner against Discord ToS?** No clause bans one person sending one hand-written message to another person. The clauses that bite are "unsolicited bulk messages", "spamming", "auto-messaging" and self-bots. A script, a macro, a copy-paste blast to many owners, or DMing from a freshly made account is on the wrong side. This is my reading, not legal advice, and Discord decides what counts as spam.

**Compliant way (recommendation):**
1. Send from Brey's own long-lived account; no tools, no scripts, no second accounts.
2. One DM per owner. Never paste the identical text more than a handful of times a day; edit the first line for each server (targets.csv has a specific `first_line` per row).
3. No link in the first message (links in cold DMs are a classic spam signal). Offer to send one.
4. Prefer the server's own ticket, modmail or suggestions channel after joining as an ordinary member. Do not post promotion in general channels.
5. Do not send friend requests as a way around closed DMs.
6. One follow-up at day 3, one at day 7, then stop (see scripts.md).
7. Cap yourself at about five new owner DMs per day while the account has no sales history.

**Risk:** reports lead to a warning or account restriction; server owners can ban you; closed DMs make some owners unreachable.

### 1b. Our bot inside a customer's server (the $149 offer): Developer Policy (FIRST-HAND)

Source: Discord Developer Policy, `https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy`, effective July 8, 2024.

- Item 5: "Do not contact users on Discord without their explicit permission. This includes frequently sending unsolicited direct messages and/or sending direct messages not directly related to maintaining or improving an Application's functionality."
- Item 6: "Do not target users with advertisements or marketing. Messaging to Discord users from any Application or developer team should be relevant to the function of the Application..."
- Item 8 forbids using an app for "dangerous or illegal activity", listing "Illegal online gambling".
- Item 13 forbids "automating messages to be sent for the purpose of maintaining activity in a Discord server" (fake activity). A nightly card posting that carries real content is not fake activity, but do not add filler posts.
- Item 20: "Do not mine or scrape any data, content, or information available on or through Discord services." The bot posts; it must not harvest member data.

Product implications: the bot must use an official bot account installed by the server admin through OAuth, post only to the channel the admin picks, never DM members, and never market to members.

### 1c. Directories and discovery

**Disboard** (`https://disboard.org`). FIRST-HAND: Guidelines at `https://disboard.org/site/guidelines`, "Last Modified: 2020-04-10". Relevant lines: "The use of bots or other scripts to automatically do actions in DISBOARD such as bumping a server ('auto-bump') is not allowed", and servers must not violate Discord Community Guidelines. Disboard does not publish an owner name, handle or contact link on listing pages. Listing pages show online counts; the member count is on the server detail page. Tag pages used: sports-betting, betting, sportsbook, sports-picks, free-picks, parlay, prizepicks, underdog, mlb, baseball, nfl, fantasy-football, fantasy-baseball, fantasy-sports, dfs, daily-fantasy. I pulled about 55 pages in a few minutes and then received HTTP 429 (Cloudflare) on the last two requests; I stopped. Brey should browse normally and not script it. Disboard ToS (`https://disboard.org/site/tos`) was not read.
Status: reading public listings ALLOWED; listing LineHound's own server ALLOWED WITH CONDITIONS (manual bumping only).

**top.gg** (`https://top.gg/discord/servers/add-your-server`). FIRST-HAND (read 2026-10-01): listing a server needs the Top.gg bot added, server details filled in, and ranking is driven by votes. No owner contact path is shown. Tag listing pages are script-rendered and returned no usable server list to my tools; top.gg's server terms returned HTTP 403 and were not read.
Status: ALLOWED WITH CONDITIONS (own listing only; no vote-trading).

**Discord Discovery.** FIRST-HAND: Community Server Guidelines, `https://support.discord.com/hc/en-us/articles/360035969312` (shown "6 years ago Updated"): a server needs an accurate title and description, clearly posted rules, a moderator team, and compliance with the Community Guidelines and ToS. SECOND-HAND (search-engine summary, not found on that page): servers whose purpose is gambling-adjacent may not be eligible. Treat Discovery as unlikely for a betting-analysis server; do not plan around it.
Also SECOND-HAND (search snippet of Discord's Server Monetization Policy): gambling-related servers cannot use Discord's own paid-subscription features. LineHound bills off-platform, so this should not matter, but confirm before routing payments through Discord.

---

## 2. Reddit (ALL STATUSES PROVISIONAL, rules not read first-hand)

Sources actually read:
- `https://sportsbooks.ag/reddit/` (page updated September 15, 2026; affiliate-run guide, tier-3): r/sportsbook (616,065 members) "Almost everything happens inside dated daily threads, and standalone posts get removed"; r/sportsbetting (580,826) is free-form but "has the toughest written rules on Reddit about selling picks"; r/arbitragebetting "bans referral links, affiliate links and promotion of external tools"; also gives member counts for r/algobetting (25,421), r/EVbetting (11,291), r/NFLBETS (13,900), r/MMAbetting (42,336), r/sportsgambling (22,451). Fetched 2026-10-01.
- `https://redship.io/blog/reddit-self-promotion-rules` (updated July 2, 2026; marketing blog, tier-3): Reddit's site-wide guidance is roughly 90 percent genuine participation and at most 10 percent promotion; subreddit rules override and are often stricter; enforcement escalates from comment removal to subreddit ban to site-wide shadowban to suspension; disclose "I built this"; designated "show your project" threads are the safe route. Fetched 2026-10-01.

| Subreddit | Provisional status | Basis | Compliant route | Risk |
|---|---|---|---|---|
| r/sportsbook | NOT ALLOWED to promote | sportsbooks.ag: daily threads only, strict anti-tout | Modmail to ask whether a link to a public record page is allowed anywhere; do not post | Removal, ban |
| r/sportsbetting | NOT ALLOWED to promote | sportsbooks.ag: toughest written rules on selling picks | Participate in discussion; modmail first | Removal, ban |
| r/SportsBettingPicks1 | UNKNOWN | sportsbooks.ag calls it the "working picks sub" (the version without the number was banned) | Modmail; read rules; an honest-record post may fit a picks sub but a paid offer likely will not | Removal, ban |
| r/algobetting | UNKNOWN, best audience fit | sportsbooks.ag: modeling and statistics community | Modmail first; a feedback post about how to present a model record, no link | Removal |
| r/EVbetting | UNKNOWN | sportsbooks.ag: +EV community; r/arbitragebetting next door bans external tools, so expect similar | Modmail first; ask a question, do not pitch | Removal |
| r/NFLBETS, r/sportsgambling, r/baseballbetting | UNKNOWN | no rule text seen | Modmail first | Removal |
| r/MMAbetting | UNKNOWN, poor sport fit (we cover MLB and NFL) | none | Skip | Wasted effort |
| r/mlb, r/baseball, r/nfl, r/fantasyfootball, r/dfsports | assume NOT ALLOWED | fan or fantasy communities; general norm is no commercial promotion | Comment as a fan only; never link the product | Removal, ban |
| r/SideProject | likely ALLOWED WITH CONDITIONS | redship names it a supportive showcase community | Maker post: what it is, "I built this", ask for criticism; no pricing push | Removal; audience is makers, not bettors |
| r/alphaandbetausers | likely ALLOWED WITH CONDITIONS | built for finding testers (background knowledge, not verified) | "Looking for testers" post | Same |
| r/startups | ALLOWED only in the designated feedback thread | redship: use designated threads in r/startups | Comment in the weekly feedback thread, not a top-level post | Removal |

Compliant way to participate, in order: (1) read the sidebar and rules yourself; (2) use modmail to ask permission, quoting your planned post, before posting anywhere that is not clearly a feedback thread; (3) disclose that you built it; (4) no link if links are banned; (5) one post per community, no cross-posting identical text; (6) answer every comment, including hostile ones, with the plain facts.
Risk summary: removal, subreddit ban, site-wide shadowban. Account age and karma matter and I could not check them.

---

## 3. X (Twitter)

FIRST-HAND. Source: `https://help.x.com/en/rules-and-policies/platform-manipulation` (redirects to the "Authenticity" policy page), read 2026-10-01. Quotes:
- "You may not share or post content in a bulk, duplicative, irrelevant or unsolicited manner that disrupts people's experience."
- Not allowed: "Sending bulk, aggressive, high-volume unsolicited replies, mentions, or direct messages; using trending or popular hashtags with an intent to subvert or manipulate a conversation or to drive traffic or attention to accounts, websites, products, services, or initiatives; ... repeatedly posting or sending direct messages consisting ..." and "sending identical direct messages".
- Not allowed: "engaging with posts aggressively or through the use of automation to drive traffic or attention to accounts, websites, products, services, or initiatives".
- Automated or scripted accounts that do not comply with the Developer Policy are barred.

Link policy: the policy text has no ban on including a link in a reply. The rule that matters is intent plus volume: bulk or duplicative replies that push a product are spam. Claims that X down-ranks posts containing links are community belief; I found no first-hand source, so treat it as unverified. X's gambling advertising rules are for paid ads and were not researched.

Status: replies and DMs ALLOWED WITH CONDITIONS.
Compliant way: reply to a specific post with something relevant to it; one reply per account; no hashtags; no copy-paste; no link in the first reply (offer it if asked); DM only accounts whose DMs are open; unique text per DM.
Norms for betting accounts (observation, not a rule): accounts that publish their own records tend to respond to people who engage with the record's contents. Accounts that sell picks will treat a pitch as a competitor ad. Profile headers (bio, followers) loaded without login; I could not read posts behind the login wall, so `why_fit` for X rows rests on bios and on one article for Peter Appel.
Risk: spam enforcement against the account, mute or block, public dunking. Keep claims to the facts on the record page.

---

## 4. Sports-betting forums

**Covers forum**: FIRST-HAND, `https://www.covers.com/forum/guidelines`, read 2026-10-01.
- "Touts / Advertising / Commerce: Our forum will not be used as a place to do your personal business ... If you are promoting a service in any forum (including that of a 'bookie') other than Website Promotions, your account may be suspended or banned at the discretion of our Moderators and Support team."
- Links: "links to personal sites ..., pick services, and sites solely designed for advertising/commerce are not permitted."
- "Any obvious site promotions will be assumed to be meant for the promotions area, and will be moved there if not deleted."
- One account per person.
Status: Website Promotions (`https://www.covers.com/forum/website-promotions-12`) ALLOWED; every other forum NOT ALLOWED for promotion. The promotions forum is busy (crypto-exchange ads dominate; recent threads include a "Spreadhound | 23-13 this season" post, "TopEV.app - Proven +EV and Arbitrage Betting" and "Free AI sports picks, every model tracked publicly", so competitors are already there). Risk: moderators may move or delete; the audience skews to tout threads, so a public-ledger angle is the differentiator.

**SBR (Sportsbook Review) forum**: FIRST-HAND, `https://www.sportsbookreview.com/forum/faq` (FAQ), read 2026-10-01. Quotes: "Spam and third-party solicitation of any kind are not permitted in the forum. This includes private messages and user statuses. Violation of this will result in an immediate ban." "users are not permitted to post referral links to sportsbooks or casinos." "links to websites for the purpose of advertising/promoting will result in an infraction." "The sharing of service plays and information from handicapper subscription picks is not permitted."
Status: NOT ALLOWED. Do not post, do not PM.

**TheRX forum**: FIRST-HAND (forum header, no formal rules page found), `https://www.therx.com/forums/site-promotions-forum.149/`, read 2026-10-01: "Post any Promotional or Sports Service information here. Warning - Records posted here are not verified by The Rx.com. Use Caution." Status: ALLOWED WITH CONDITIONS (post only in this forum). The unverified-records warning is the opening for a hash-chained ledger. Risk: the audience is tout-heavy and skeptical, and site rules elsewhere were not read.

**TrustMyRecord forum**: `https://trustmyrecord.com/forum/` loads; no rules page found. The platform (290 members, 70 pick makers per its home page) locks and auto-grades picks, so it is both a natural audience and a peer product. Status UNKNOWN: read its terms, then use the footer contact link.

Not usable right now: Wizard of Vegas sports-betting URL returned 404; Pregame forums returned HTTP 500; predictem.com/forum returned 404; betting-forum.com is soccer-focused.

---

## 5. Newsletters, podcasts, YouTube

No platform rule applies to emailing or DMing a creator; the norm is a short, specific, individual note. Substack comment or DM, or the contact route on the creator's page. Do not use any bulk tool. The five rows in targets.csv are individual targets, not a list to blast. Risk: low, but a copy-paste pitch will be ignored. Never offer money for a mention without asking whether it must be labeled as sponsored.

---

## 6. Competitors and exclusions found while researching

- **SharpCapper.com** Discord (`https://disboard.org/server/1520944359774883972`, 44 members) pitches almost exactly LineHound's honest claim ("public, graded record ... No tout, no locks"). Treat as a direct competitor, not a target.
- **TrustMyRecord**, **Juice Reel**, **Unabated** and **Sharp App** sell verification or +EV tooling. They are peers or partners, not customers; approach with that framing.
- Paid-tout servers skipped (claims like "profit an average of $1K-$10K a month", fixed win rates, premium slip tiers): KazuPicks, ParlaySensei, Lawy Locks, Parlay Payday, Winning Locks, JW Consultants, heavy locks, Bankroll Bandits, Bravo Six Picks, and similar.
- ProfessionalGambler.org sells subscription picks, so it was skipped as a creator target.
- Dinger Stats Substack was skipped: last post in May 2022.

## 7. Messaging rules for Brey (apply on every channel)

- Say "no edge is claimed". Never say profit, winning, sharp, lock, or a win rate.
- State that the current public MLB record is negative, with the number copied live from the record page on the day you send.
- Disclose "I built this" every time.
- 21+, bet responsibly; no sportsbook or casino referral links; no affiliate links.
- Do not claim the ledger proves skill. It proves the record was not edited.
