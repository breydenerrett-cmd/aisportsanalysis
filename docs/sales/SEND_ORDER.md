# Batch 1 sending order

## Send these five first (2026-10-04): an invitation to review the next brief

This section replaces "Group 1" below as the next thing to send. Five people, MLB fit first. Each
message is an honest invitation to look at the NEXT completed brief. It promises only what exists
today: paid plans are not open, so it says "not on sale yet" and never "then $19.99 if you keep it"; it does not say a sample is
already up, and it carries no link. When someone says yes, send them the link below once a brief is
posted. Version label for all five: `v3c-invite-not-on-sale`. Send by hand, then tell me "sent 9"
(the item number) and I log it. A send, a reply, a signup, real use and a payment are logged
separately.

Why these five (all from the existing queue; nobody appears twice):

| Item | Lead | Why this person |
|---|---|---|
| 9 | Tommy Lorenzo, X | Bets MLB and hosts a betting podcast; judges other people's reasoning for a living. |
| 3 | Peter Appel, JustBaseball, X | Publishes his own losing MLB audit; the brief argues against its own bets. The JustBaseball entry and his X account are one lead. |
| 8 | Tyler Shoemaker, X | Runs his own MLB and NFL ratings and shares every bet; will compare our numbers with his. |
| 11 | Picks with the Professor, X | Player-level data is his pitch; the brief calls player props. Smallest account, so the likeliest to answer. |
| 12 | Unit Circle, Discord | A server sold on "transparent results" that posts matchups and props daily. |

Spare, if one cannot be reached: item 13 (337picks, Discord).

Link to send only AFTER they say yes and a brief is posted (replace LEAD and CHANNEL):

```
https://linehound.app/web/sample.html?utm_source=LEAD&utm_medium=CHANNEL&utm_campaign=brief_01
```

On X: DM if his DMs are open. If not, reply to a recent baseball post with the short public reply.
Replace a bracket with one thing you actually read in his recent post; if you cannot find one
honestly, skip him and use the spare.

### Item 9, Tommy Lorenzo (LEAD `l009-tommy-lorenzo`, CHANNEL `x_account`)

Where: https://x.com/sportsbooktom

```
Tommy, [one thing from his recent baseball post]. I am building a matchup brief for the MLB playoffs: for each game it makes a call on every priced market, writes the strongest case against its own bet, lists what it could not know, and is graded in public afterward. It is posted before first pitch. May I send you the next one when it is posted, and would you tell me whether it helps you decide what to examine or skip? AI analysis, not advice, and I claim no edge. If it turns out useful, I am hand-picking the first 20 testers: 7 days free, no card. It is not on sale yet; the planned price is $19.99 a month.
```

Public reply if DMs are closed:

```
[One thing from his post]. I am building a playoff matchup brief that argues the case against its own bet and is graded in public. May I send you the next one and hear what is missing?
```

When he says yes, once a brief is posted:

```
Here it is, frozen before first pitch: LINK. What would you want it to show that it does not?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 9 --version v3c-invite-not-on-sale`

### Item 3, Peter Appel (LEAD `l003-justbaseball-betting`, CHANNEL `creator`)

Where: https://x.com/peterappel23

```
Peter, your "Auditing Myself" log is the reason I am writing: you publish the losing numbers. I am building a matchup brief for the MLB playoffs: for each game it makes a call on every priced market, writes the strongest case against its own bet, lists what it could not know, and is graded in public afterward. It is posted before first pitch. May I send you the next one when it is posted, and would you tell me whether it helps you decide what to examine or skip? AI analysis, not advice, and I claim no edge. If it turns out useful, I am hand-picking the first 20 testers: 7 days free, no card. It is not on sale yet; the planned price is $19.99 a month.
```

Public reply if DMs are closed:

```
[One thing from his post]. I am building a playoff matchup brief that argues the case against its own bet and is graded in public. May I send you the next one and hear what is missing?
```

When he says yes, once a brief is posted:

```
Here it is, frozen before first pitch: LINK. What would you want it to show that it does not?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 3 --version v3c-invite-not-on-sale`

### Item 8, Tyler Shoemaker (LEAD `l008-tyler-shoemaker`, CHANNEL `x_account`)

Where: https://x.com/tshoeindex

```
Tyler, you share every bet and keep your own ratings, so you can check this faster than most. I am building a matchup brief for the MLB playoffs: for each game it makes a call on every priced market, writes the strongest case against its own bet, lists what it could not know, and is graded in public afterward. It is posted before first pitch. May I send you the next one when it is posted, and would you tell me whether it helps you decide what to examine or skip? AI analysis, not advice, and I claim no edge. If it turns out useful, I am hand-picking the first 20 testers: 7 days free, no card. It is not on sale yet; the planned price is $19.99 a month.
```

Public reply if DMs are closed:

```
[One thing from his post]. I am building a playoff matchup brief that argues the case against its own bet and is graded in public. May I send you the next one and hear what is missing?
```

When he says yes, once a brief is posted:

```
Here it is, frozen before first pitch: LINK. What would you want it to show that it does not?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 8 --version v3c-invite-not-on-sale`

### Item 11, Picks with the Professor (LEAD `l011-picks-with-the-professor`, CHANNEL `x_account`)

Where: https://x.com/professorsides

```
Professor, you work from player-level data, so the props half of this is yours to judge. I am building a matchup brief for the MLB playoffs: for each game it makes a call on every priced market, writes the strongest case against its own bet, lists what it could not know, and is graded in public afterward. It is posted before first pitch. May I send you the next one when it is posted, and would you tell me whether it helps you decide what to examine or skip? AI analysis, not advice, and I claim no edge. If it turns out useful, I am hand-picking the first 20 testers: 7 days free, no card. It is not on sale yet; the planned price is $19.99 a month.
```

Public reply if DMs are closed:

```
[One thing from his post]. I am building a playoff matchup brief that argues the case against its own bet and is graded in public. May I send you the next one and hear what is missing?
```

When he says yes, once a brief is posted:

```
Here it is, frozen before first pitch: LINK. What would you want it to show that it does not?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 11 --version v3c-invite-not-on-sale`

### Item 12, Unit Circle (Discord) (LEAD `l012-unit-circle`, CHANNEL `discord`)

Where: join https://disboard.org/server/1369099482997723208 as a member, read the rules, then the ticket or mod-contact channel

```
Hi [Name], Unit Circle is built on transparent results, so I would value your read. I am building a matchup brief for the MLB playoffs: for each game it makes a call on every priced market, writes the strongest case against its own bet, lists what it could not know, and is graded in public afterward. It is posted before first pitch. May I send you the next one when it is posted, and would you tell me whether it helps you decide what to examine or skip? AI analysis, not advice, and I claim no edge. If it turns out useful, I am hand-picking the first 20 testers: 7 days free, no card. It is not on sale yet; the planned price is $19.99 a month.
```

When he says yes, once a brief is posted:

```
Here it is, frozen before first pitch: LINK. What would you want it to show that it does not?
```

Log: `python scripts/outreach_batch.py sent --batch 1 --items 12 --version v3c-invite-not-on-sale`

After someone uses it, ask what `docs/sales/DISCOVERY_GUIDE.md` lists: what decision it helped, what
was missing, whether they came back, and whether they will pay $19.99 for it.

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
