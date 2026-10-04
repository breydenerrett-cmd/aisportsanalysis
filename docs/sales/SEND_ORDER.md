# Batch 1 sending order

## Send these five first (2026-10-04): an invitation to read a real brief

Five people, MLB fit first, each with a finished message: no brackets, no LINK, nothing to fill in. Copy, paste, send by hand. Every message links to the sample brief at https://linehound.app/web/sample.html, which shows the latest published game (on 2026-10-04, Padres at Brewers) and that game's graded result once it has one. So the messages say "the latest one", never "today's". Version label for all five: `v3e-ready`. A send, a reply, a signup, real use and a payment are logged separately.

Facts every message keeps: AI analysis, not advice; no edge claimed; not on sale yet, planned price $19.99 a month; first 20 testers, 7 days free, no card. No profit or win-rate claim.

### Before you send (two minutes)

1. Open one of the links yourself. It should show a game and, after the final, its graded result. If it says there is no sample brief, do not send until it shows one.
2. Open the person's profile (the `Where` line). The opener makes one claim about them, listed in the table below. If the profile no longer fits it, delete the first sentence and send the rest.
3. X: send both parts as DMs one after the other (part 1, then part 2). If DMs are closed, post the short public reply under one of their recent baseball posts instead. Never post the link in a group chat.
4. Then tell me "sent 9" (the item number) and I log it, or run the command under the message.

### What each opener claims, and the evidence (checked 2026-10-04)

| Item | Claim in the opener | Evidence | Status |
|---|---|---|---|
| 9 Tommy Lorenzo | He talks MLB betting in public | `targets.csv` bio (hosts the Cover The Weekend podcast, bets CFB and MLB); a web search lists him as a guest on a betting show discussing MLB wagers. X profile is behind a login wall | VERIFIED (bio and a secondary source; not the X page) |
| 3 Peter Appel | His "Auditing Myself" series covers his own MLB betting results | https://www.justbaseball.com/betting/ lists "Auditing Myself: Worst Start to MLB Gambling I've Ever Had", 2026-05-17 | VERIFIED on the public page. The old line "you publish the losing numbers" is REMOVED: the listing did not show the numbers (the 25-37-1 figure is from the queue research notes only) |
| 8 Tyler Shoemaker | None about him. Old claim "shares every bet and keeps his own ratings" | Only the X bio via `targets.csv` (2026-10-01); X returned a login wall today and a web search found no T Shoe Index page | REMOVED, replaced with "I found your account while looking for people who follow MLB betting closely" (true of how he was found) |
| 11 Picks with the Professor | He publishes betting picks under that name | A public Spotify podcast page for "professorsides" with betting picks episodes. Old claim "works from player-level data" is a bio phrase only; X is behind a login wall | VERIFIED for picks. "Player-level data" is REMOVED (UNVERIFIED) |
| 12 Unit Circle | None. Old claim "built on transparent results" | Only the Disboard listing via `targets.csv` (2026-10-01); Disboard returned 403 to a plain fetch today and I did not try to pass it | REMOVED, replaced with "I found Unit Circle on Disboard while looking for MLB betting communities" |

The old line "today's brief had too few prop prices to call any" is gone from item 11: it described one game on one day and is not true of the page you are linking.

Why these five (all from the existing queue; nobody appears twice): item 9 bets MLB and talks about it in public; item 3 writes about his own MLB results (the JustBaseball entry and his X account are one lead); item 8 covers MLB and NFL betting; item 11 is the smallest account, so the likeliest to answer; item 12 is the one Discord server that lists MLB. Spare, if one cannot be reached: item 13 (337picks, Discord), which has no finished message yet: do not use it without writing one.

### Item 9, Tommy Lorenzo (LEAD `l009-tommy-lorenzo`, CHANNEL `x_account`)

Where: https://x.com/sportsbooktom

Tagged link inside the message: `https://linehound.app/web/sample.html?utm_source=l009-tommy-lorenzo&utm_medium=x_account&utm_campaign=brief_01`

DM, part 1 (451 characters including the link):

```
Tommy, you talk MLB betting in public, so I want a bettor's read. I built an AI brief for each MLB playoff game: a take or pass on every market it has prices for, the strongest case against its own bets, what it could not know, graded in public afterward. The latest one: https://linehound.app/web/sample.html?utm_source=l009-tommy-lorenzo&utm_medium=x_account&utm_campaign=brief_01 Would you tell me whether it helps you decide what to check or skip?
```

DM, part 2, sent right after part 1 (207 characters):

```
Terms, so nothing is hidden: AI analysis, not advice, and I claim no edge. Not on sale yet; the planned price is $19.99 a month. If it is useful, I am hand-picking the first 20 testers: 7 days free, no card.
```

Public reply if DMs are closed (233 characters; X counts a link as 23):

```
Tommy, I built an AI brief for each MLB playoff game that argues against its own bets and is graded in public. Analysis, not advice; no edge claimed; not on sale. The latest: https://linehound.app/web/sample.html?utm_source=l009-tommy-lorenzo&utm_medium=x_account&utm_campaign=brief_01 Would you tell me what is missing?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 9 --version v3e-ready`

### Item 3, Peter Appel (LEAD `l003-justbaseball-betting`, CHANNEL `creator`)

Where: https://x.com/peterappel23

Tagged link inside the message: `https://linehound.app/web/sample.html?utm_source=l003-justbaseball-betting&utm_medium=creator&utm_campaign=brief_01`

DM, part 1 (485 characters including the link):

```
Peter, your "Auditing Myself" series covers your own MLB betting results, so I want your read. I built an AI brief for each MLB playoff game: a take or pass on every market it has prices for, the strongest case against its own bets, what it could not know, graded in public afterward. The latest one: https://linehound.app/web/sample.html?utm_source=l003-justbaseball-betting&utm_medium=creator&utm_campaign=brief_01 Would you tell me whether it helps you decide what to check or skip?
```

DM, part 2, sent right after part 1 (207 characters):

```
Terms, so nothing is hidden: AI analysis, not advice, and I claim no edge. Not on sale yet; the planned price is $19.99 a month. If it is useful, I am hand-picking the first 20 testers: 7 days free, no card.
```

Public reply if DMs are closed (233 characters; X counts a link as 23):

```
Peter, I built an AI brief for each MLB playoff game that argues against its own bets and is graded in public. Analysis, not advice; no edge claimed; not on sale. The latest: https://linehound.app/web/sample.html?utm_source=l003-justbaseball-betting&utm_medium=creator&utm_campaign=brief_01 Would you tell me what is missing?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 3 --version v3e-ready`

### Item 8, Tyler Shoemaker (LEAD `l008-tyler-shoemaker`, CHANNEL `x_account`)

Where: https://x.com/tshoeindex

Tagged link inside the message: `https://linehound.app/web/sample.html?utm_source=l008-tyler-shoemaker&utm_medium=x_account&utm_campaign=brief_01`

DM, part 1 (499 characters including the link):

```
Tyler, I found your account while looking for people who follow MLB betting closely, so I want a bettor's read. I built an AI brief for each MLB playoff game: a take or pass on every market it has prices for, the strongest case against its own bets, what it could not know, graded in public afterward. The latest one: https://linehound.app/web/sample.html?utm_source=l008-tyler-shoemaker&utm_medium=x_account&utm_campaign=brief_01 Would you tell me whether it helps you decide what to check or skip?
```

DM, part 2, sent right after part 1 (207 characters):

```
Terms, so nothing is hidden: AI analysis, not advice, and I claim no edge. Not on sale yet; the planned price is $19.99 a month. If it is useful, I am hand-picking the first 20 testers: 7 days free, no card.
```

Public reply if DMs are closed (233 characters; X counts a link as 23):

```
Tyler, I built an AI brief for each MLB playoff game that argues against its own bets and is graded in public. Analysis, not advice; no edge claimed; not on sale. The latest: https://linehound.app/web/sample.html?utm_source=l008-tyler-shoemaker&utm_medium=x_account&utm_campaign=brief_01 Would you tell me what is missing?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 8 --version v3e-ready`

### Item 11, Picks with the Professor (LEAD `l011-picks-with-the-professor`, CHANNEL `x_account`)

Where: https://x.com/professorsides

Tagged link inside the message: `https://linehound.app/web/sample.html?utm_source=l011-picks-with-the-professor&utm_medium=x_account&utm_campaign=brief_01`

DM, part 1 (489 characters including the link):

```
Professor, you publish betting picks as Picks with the Professor, so I want a bettor's read. I built an AI brief for each MLB playoff game: a take or pass on every market it has prices for, the strongest case against its own bets, what it could not know, graded in public afterward. The latest one: https://linehound.app/web/sample.html?utm_source=l011-picks-with-the-professor&utm_medium=x_account&utm_campaign=brief_01 Would you tell me whether it helps you decide what to check or skip?
```

DM, part 2, sent right after part 1 (207 characters):

```
Terms, so nothing is hidden: AI analysis, not advice, and I claim no edge. Not on sale yet; the planned price is $19.99 a month. If it is useful, I am hand-picking the first 20 testers: 7 days free, no card.
```

Public reply if DMs are closed (237 characters; X counts a link as 23):

```
Professor, I built an AI brief for each MLB playoff game that argues against its own bets and is graded in public. Analysis, not advice; no edge claimed; not on sale. The latest: https://linehound.app/web/sample.html?utm_source=l011-picks-with-the-professor&utm_medium=x_account&utm_campaign=brief_01 Would you tell me what is missing?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 11 --version v3e-ready`

### Item 12, Unit Circle (LEAD `l012-unit-circle`, CHANNEL `discord`)

Where: join https://disboard.org/server/1369099482997723208 as a member, read the rules, then use the ticket or mod-contact channel only. Do not post in member channels. If the rules forbid this kind of contact, stop and log nothing.

Tagged link inside the message: `https://linehound.app/web/sample.html?utm_source=l012-unit-circle&utm_medium=discord&utm_campaign=brief_01`

One message (777 characters including the link):

```
Hello, I'm Brey. I found Unit Circle on Disboard while looking for MLB betting communities, so I am asking the mods first and not posting in the server. I built an AI brief for each MLB playoff game: a take or pass on every market it has prices for, the strongest case against its own bets, what it could not know, graded in public afterward. The latest one: https://linehound.app/web/sample.html?utm_source=l012-unit-circle&utm_medium=discord&utm_campaign=brief_01 Would you look at it and tell me whether it is something your members would want, or whether I should not share it here? It is AI analysis, not advice, and I claim no edge. It is not on sale yet; the planned price is $19.99 a month. If it is useful, I am hand-picking the first 20 testers: 7 days free, no card.
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 12 --version v3e-ready`

### If someone answers

If you used a public reply, the price and tester terms have not been said yet: send DM part 2 once they answer. Do not send the tester offer in your first reply. Ask the one question first:

```
Thank you. What would you want it to show that it does not?
```

Log the reply with the type from `docs/sales/DISCOVERY_GUIDE.md`: `python scripts/outreach_batch.py reply --lead <id> --type CURIOUS --said "their words"`.

### If they say yes to a tester spot (the onboarding messages)

Grant a spot only when the three conditions in the discovery guide hold (they follow or bet MLB, NFL or UFC; they say they will use it; they will tell you what was useful). Anyone else: "Spots are limited right now; you're on the list and I'll write when one opens."

Step 1, ask for the request (so the signup is tied to their link and their email):

```
Glad to. Two things: please request access with the email you want to use at https://linehound.app/web/index.html#/signup and tell me which email it was. Terms: one week, no card, not free forever, performance not proven, analysis not advice. In return I would like to hear what was useful and what was not.
```

Step 2, you grant it: admin page, Testers section, their email, "Grant 7-day tester access". The token shows once; copy it. Then log it: `python scripts/outreach_batch.py tester-access --lead <id>`. Send this, filling only the end date and the token (these two are the only blanks in this file, because they do not exist until you grant):

```
You're in: one week of early access to LineHound, no card. It ends on <end date>.

Sign in: https://linehound.app/web/index.html#/signin
Paste this token: <token>

What you will see: the matchup brief on each MLB playoff game page (posted before first pitch, with the strongest reason against each call and what it could not know), the day's card (some days it has few picks or none, on purpose), the odds and props pages, and the public record of every pick. The card and the game brief are two separate methods, graded separately, and they can differ for the same game.

What is experimental: all of it. The MLB record is negative so far and nothing here is proven. It is AI analysis, not advice.

One question for you, after you have opened a game or two: what did it help you decide to check or skip, and what was missing? Just reply here.
```

Access is real, not a mockup: the token signs in through the sign-in page and opens the game pages and the analysis; without it those pages answer 401. The week ends by itself; if the token is lost see "A tester who lost the token" in the discovery guide. Do not name a night for the card, and do not promise UFC picks (paused).

### One follow-up for a non-reply (once, no more)

Send it in the same thread 3 days after the first message, only to someone who did not answer. If they still do not answer, stop: a no reply is a no.

```
One nudge, then I will leave it alone: if you have two minutes for the brief I sent, I would like to know whether it helps you decide what to check or skip. A no is a fine answer.
```

If they answer no, thank them and stop. Log: `python scripts/outreach_batch.py reply --lead <id> --type NOT_INTERESTED --said "their words"`.

### Keep your own checks out of the customer numbers

When you open or walk a link yourself, change `utm_source=<lead>` in it to `utm_source=internal-brey` first (a source of `internal` or `internal-...` is left out of the funnel and tester counts). Your own tester account needs the signup steps in the discovery guide. The sample page itself records no visit: only a signup shows that someone came through a link, so a reader who never signs up is invisible. Ask people.

After someone uses it, ask what `docs/sales/DISCOVERY_GUIDE.md` lists: what decision it helped, what was missing, whether they came back, and whether they will pay $19.99 for it.

---

## Earlier plan (kept for the remaining leads)

Batch 1 is a customer-discovery experiment, not a blast. Twenty leads go out
in five small groups, best fit first, so the message can be improved before
the rest are spent. You send every message by hand from your own accounts.

How fit was judged, in this order: the audience bets MLB, NFL or UFC right
now; the message reaches bettors directly (not a gatekeeper who doesn't bet);
the channel allows a trackable link or a real conversation; a reply is likely
(small, active, owner-led beats large and anonymous).

| Group | When | Leads | Why this group |
|---|---|---|---|
| 1 | Now | l001 Covers thread, l013 337picks, l012 Unit Circle, l009 Tommy Lorenzo | One of each channel type, each the best fit of its type. Tells us which channel answers at all. |
| 2 | 48 hours after group 1, or sooner if replies come in | l002 TheRX thread, l018 CASH COUNTER, l020 Xploit Wagers, l003 JustBaseball | Second forum gets the thread text as improved by Covers replies. Two NFL and small-community servers. One MLB creator while the playoffs are on. |
| 3 | After group 2 | l011 ProfessorSides, l008 Tyler Shoemaker, l014 Presidential Props, l017 BMB Picks | Small X accounts that track their own bets; two props servers (pick'em apps, so a weaker match). |
| 4 | After group 3 | l019 SBPICKS, l004 MonotoneBetting, l005 Farley, l010 Kyle Kirms | Broader or less certain fit. |
| 5 | Last | l006 Closing Line Podcast, l007 Joseph Buchdahl, l015 Fantasy Football Addicts, l016 Dynasty Fantasy Baseball | Press and a professional sceptic (worth more once the message is sharp and there is more record to show), then two fantasy servers that may not bet at all. |

Groups 2 to 5 are not written yet on purpose. Their wording waits for what
group 1 teaches.

---

## Group 1: four sends

Record used below, read from the live site on 2026-10-03: MLB 16-17, -5.05
units over 6 regular-season nights; postseason 0-2 (graded, not counted);
NFL 1-0; UFC 5-1. Open the record page before you send and check the MLB
number still matches.

After each send, log it (or just tell me "sent 1" and I will). The version
label records which wording went out, so the versions can be compared:

```
python scripts/outreach_batch.py sent --batch 1 --items 1 --version v2-thread-offer-two-questions
python scripts/outreach_batch.py sent --batch 1 --items 13 --version v2a-discovery-question
python scripts/outreach_batch.py sent --batch 1 --items 12 --version v2b-tester-offer
python scripts/outreach_batch.py sent --batch 1 --items 9 --version v2-x-question-only
```

The text to send is the text in this file, not the older wording in
`batch_01.md` (that file still holds each lead's tagged record link).

### 1. Covers, Website Promotions forum (item 1, lead l001)

Where: https://www.covers.com/forum/website-promotions-12 , Create Thread,
from your own account. This is the one Covers forum where promoting a site
is allowed. If a new account is not allowed to start a thread yet, stop and
say so; TheRX moves up.

Title:

```
AI betting analysis that grades every pick in public. The record is negative so far. Looking for 20 testers to tear it apart
```

Shorter title if that one is too long for the box:

```
Public graded record, losses included. Looking for 20 testers to tear it apart
```

Body:

```
I'm the builder, so read this as a disclosure, not a recommendation.

What it is: LineHound is AI sports analysis for MLB, NFL and UFC. Before the games it posts the bets it likes, with the reasoning, the matchup breakdown and where the price stands across the books. After the games every pick is graded on a public record page, losses included, and past results can't be edited.

What it is not: proven. The MLB record is 16-17, -5.05 units over 6 regular-season nights, plus 0-2 in the postseason. NFL and UFC have a handful of graded picks, which means nothing yet. I'm not claiming an edge, and this is analysis, not advice.

Why I'm posting: I'm giving the first 20 testers one week of full access, free, no card. Access is temporary and nothing is for sale yet. I want people who actually bet these sports and will tell me what's useless.

Two questions, even if you don't want a spot:
1. What do you look at before you place a bet today, and do you pay for any of it?
2. What would make you distrust a site like this on sight?

The record is free to read, no signup:
https://linehound.app/web/index.html?utm_source=l001-covers-website-promotions-forum&utm_medium=forum&utm_campaign=batch_01#/record-card

For a tester spot, use "Request early access" on that page, or reply here.

21+. Please bet responsibly. Harsh replies welcome.
```

Message version: `v2-thread-offer-two-questions`

### 2. 337picks, Discord (item 13, lead l013)

Where: join https://disboard.org/server/1357930952684474439 as a member,
read the server rules, then use its ticket or mod-contact channel. Do not
post in member channels. If the rules forbid this kind of contact, skip it
and log nothing. Replace [Name] with the mod's handle.

```
Hi [Name], I'm Brey. I built LineHound: AI analysis for MLB, NFL and UFC that posts its bets before the game and grades every one in public, losses included. Not proven (MLB is 16-17, -5.05 units; no edge claimed). I won't post links in your server. One question: what do your members check before they tail a pick?
```

Message version: `v2a-discovery-question`

### 3. Unit Circle, Discord (item 12, lead l012)

Where: join https://disboard.org/server/1369099482997723208 as a member,
read the rules, then the ticket or mod-contact channel. Same care as above.

```
Hi [Name], Unit Circle is built on transparent results, so I'd value your read. I built LineHound: AI analysis for MLB, NFL and UFC, posted before the game and graded in public, losses included. Not proven (MLB is 16-17, -5.05 units; no edge claimed). I have 20 free one-week tester spots, no card. Want one, to pull it apart?
```

Message version: `v2b-tester-offer`

(The two Discord notes end on different asks on purpose: one asks about
them, one offers a spot. Two sends cannot prove which is better; they can
show whether either gets an answer at all.)

### 4. Tommy Lorenzo, X (item 9, lead l009)

Where: https://x.com/sportsbooktom . Open a recent post of his about
baseball or the playoffs. Reply to that post. Replace the bracket with one
specific thing you actually read in it (about 75 characters fit). No link,
no hashtag. If there is no recent post you can honestly respond to, skip
him for now.

```
[One specific thing from his post]. I built an AI card that posts MLB bets before the game and grades every one in public: 16-17, -5.05u so far, no edge claimed. Builder's question: what do you check before you trust anyone's record?
```

Message version: `v2-x-question-only` (no offer in a public reply; the tester
spot is offered only if he engages)

---

## When someone answers

1. Paste the reply to me, or log it yourself (see
   `docs/sales/DISCOVERY_GUIDE.md` for the types):
   `python scripts/outreach_batch.py reply --lead <id> --type CURIOUS --said "their words"`
2. Their exact words are kept on this computer only, never in the public
   repository.
3. If they ask where to look, send the tagged record link for that lead (it
   is in `docs/sales/batch_01.md` under their item).
4. If they want a tester spot: ask them to press "Request early access" on
   the site with the email they want to use, so the signup is tied to them.
   Then follow "First 20 testers" in the discovery guide before you grant.
