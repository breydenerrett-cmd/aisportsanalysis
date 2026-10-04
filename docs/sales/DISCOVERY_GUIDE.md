# Customer discovery guide

Batch 1 exists to learn, not to sell. This is what we need to learn, how to
ask without interrogating anyone, how to label what comes back, and who gets
one of the 20 tester spots.

## The rule for asking

One question per message. Two at most, and only in a public thread. Never ask
the next question until they have answered the last one. Ask about them and
what they do, not about whether they like LineHound. Write down their exact
words.

## What we need to learn, and the question that gets it

Ask in this order. Each stage starts only when the one before it has happened.

**Stage 1: their first reply. They have not looked yet.**

| We need to know | Ask |
|---|---|
| What they use today | "What do you look at before you place a bet today?" |
| Sport and markets they bet | "What do you mostly bet: sides, totals or props? Which sports?" |

**Stage 2: they have looked at the record page or the site.**

| We need to know | Ask |
|---|---|
| What they distrust about betting services | "What made you doubt it, if anything?" |
| Whether the public record matters | "Did the public record change how you read the picks, or is it just nice to have?" |
| What they want before placing a bet | "What was missing that you'd want to see before you'd actually bet one of these?" |

**Stage 3: they are a tester and have had it for two nights.**

| We need to know | Ask |
|---|---|
| Whether deep matchup analysis matters | "Did you open any of the game breakdowns? Useful, or too much?" |
| Props or moneylines | "Which did you look at more, the props or the game picks?" |
| What brings them back | "What would make you open it again tomorrow?" |

**Stage 4: day five to seven of their week.**

| We need to know | Ask |
|---|---|
| Whether they pay for analysis now | "Do you pay for any picks or tools right now? What, and roughly how much?" |
| Whether they would pay | "If this cost money after the free week, would you keep it?" |
| What price feels reasonable | "What price would feel fair to you?" Let them name a number first. Say the planned $19.99 a month only if they ask. |
| What would stop them | "What would stop you from paying?" |

The product itself answers some of this without asking: the admin page shows
which features each tester actually opened.

## Labelling a reply

Use exactly one of these. Their words go in with the label and are never
edited or replaced; if a label turns out wrong, it is changed and the old
label stays in the history.

| Type | Use it when they | What to do next |
|---|---|---|
| POSITIVE_INTEREST | want to see it, want a spot, or say it sounds useful | Send their tagged link. Ask the next stage's question. |
| CURIOUS | ask a question without showing which way they lean | Answer it plainly. Then ask one stage 1 question. |
| SIGNED_UP | tell you they requested access | Check the admin page. Decide on a tester spot (below). |
| ACTIVE_TESTER | are using it and talking to you about it | Ask the stage 3 questions, one at a time. |
| WOULD_PAY | say they would pay, at any price | Log the price they named. Ask what would stop them. |
| PRICE_OBJECTION | like it but not at that price, or not for money | Ask what price would feel fair. Do not discount on the spot. |
| TRUST_OBJECTION | doubt the record, the method or the motive | Ask what would change their mind. This is the most useful reply there is. |
| PRODUCT_CONFUSION | misread what it is (a tipster, a sportsbook, a bot) | Note which words confused them. Explain in one sentence. |
| NOT_INTERESTED | say no | Thank them. No follow-up. A no ends the thread. |
| NO_REPLY | have not answered seven days after the send | Set automatically. Nothing to do after the second follow-up. |
| SPAM_OR_IRRELEVANT | are a bot, an ad, or off topic | Ignore. |

Logging (their words stay on this computer, not in the public repository):

```
python scripts/outreach_batch.py reply --lead <id> --type TRUST_OBJECTION --said "their exact words"
```

A person who answers a forum thread is a new lead of their own:

```
python scripts/outreach_batch.py add --via l001-covers-website-promotions-forum --channel forum --handle "their handle" --type CURIOUS --said "their exact words"
```

If the same person turns up on a second platform, the tool refuses to make a
second record and tells you which lead they already are. Attach the new
handle to that lead with `alias`.

## First 20 testers

The spots are scarce on purpose. A signup is not a tester.

Grant a spot only when all three are true:

1. They bet, or seriously follow, MLB, NFL or UFC. They said so, or it is
   plain from where you met them.
2. They say they will actually use it during the week.
3. They agree to tell you what was useful and what was not.

Anyone else stays on the list. Tell them plainly: "Spots are limited right
now; you're on the list and I'll write when one opens."

Terms, said every time: one week, no card, not free forever, performance not
proven, analysis not advice.

To grant: admin page, Testers section, their email, "Grant 7-day tester
access". The token shows once. Then log it:

```
python scripts/outreach_batch.py tester-access --lead <id>
```

### The message to send with the token

```
You're in: one week of early access to LineHound, no card. It ends on <date>.

Sign in: https://linehound.app/web/index.html#/signin
Paste this token: <token>

Where to start: open one playoff game you care about. Each game page has the matchup brief, posted before first pitch, with the strongest reason against every call. Tonight's card is on the first screen.

What's there: the playoff matchup brief on each game page, tonight's card (some nights it has few picks or none, and that is on purpose), the odds and props pages, and the public record of every pick.

What's experimental: all of it is unproven. The MLB record is negative so far, and NFL has only a handful of graded picks. UFC picks are paused right now. The card and the brief on a game page are two separate methods, graded separately, and they can differ for the same game. It is analysis, not advice.

How to tell me what you think: just reply here. After two nights I'd like to know what was useful, what was confusing and what was missing.
```

### Keep your own test account out of the customer numbers

The funnel report and the tester activity report leave out our own traffic by
one rule, and only by this rule: the account's signup carried a `utm_source`
that is exactly `internal` or starts with `internal-` (for example
`internal-brey`). Anything else counts as a customer, so do this before you
grant your own email:

1. Use an email that has never requested access. A signup that is already on
   file keeps its first source, and a later signup cannot change a tester's.
2. In a fresh private window (the first source is stored once per browser and
   the first one wins), open
   `https://linehound.app/web/index.html?utm_source=internal-brey#/signup`
   and request early access with that email.
3. Then grant it from the admin page like any tester. Granting an email with no
   earlier signup leaves no tag, and your own page views would count as a
   customer's.
4. Check: the activity section of the admin page shows "Our own test accounts
   left out: 1" (it counts up by one), and the granted and activated numbers do
   not include you.

### A tester who lost the token

The token is never stored and cannot be shown again, so send a new one. The
subscriber re-issue route refuses testers; the only door is the extend call.
On the admin page, Testers section, find their row, type a reason in the box
("lost the token" is enough) and press "Extend 7 days". That is
`POST /admin/testers/extend` with the header `X-Admin-Token: <admin token>` and
the body `{"user_id": <their id>, "reason": "lost the token"}`. It needs the
user id (not the email) and a reason; without a reason it answers 400
`reason_required`. It uses no extra tester spot. The answer carries a new token,
shown once: send it the same way as the first (paste it into a message yourself;
nothing emails it).

Read "Known limits" below before you do this for someone who is mid-week.

### Known limits

- The lost-token route always gives a fresh 7 days from the moment you press
  it, however many days the tester had left. Re-sending a token to someone with
  four days left hands out a week from now.
- It does not revoke the old token. The lost token keeps working until its own
  expiry, so a lost token that someone else found is not shut off by sending a
  new one.
- Every use is recorded as an extension with its reason. That log is meant to
  show which extensions were earned by feedback; a lost-token reason is
  honest, but it is not feedback.

## Activated means used, not signed up

A tester counts as activated the first time they open real product content
while signed in: tonight's card, a game breakdown, the props, an NFL or UFC
card. Signing in alone does not count. Returning means they came back at
least 12 hours after that first time. The admin page shows both for every
tester, with the hours from signup to first use.

If a tester has not activated two days after getting the token, send one
nudge ("Did the token work? Tonight's card is up.") and nothing more.

## After five real conversations

Stop and read them together before changing anything. The synthesis covers:
what people asked for, what confused them, what they ignored, what made them
interested, what caused distrust, sports and markets requested, would-pay
signals, price signals and repeated themes. It ends with no more than three
product changes. One person's opinion does not change the product; a theme
that repeats does.
