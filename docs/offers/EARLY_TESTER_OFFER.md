# Early tester offer and the outreach loop (owner's guide)

## The offer (owner decision, 2026-10-02)

The first 20 qualified testers get 7 days of early access. No card. Extended
only when useful feedback justifies it. Brey decides who is qualified.

Wherever it is described, five things are said plainly:

1. It is early access.
2. Performance is not proven.
3. The analysis is informational, not advice.
4. Every result stays on the public record, losses included.
5. Tester access is temporary.

Never said: profit, an edge, winning picks.

What LineHound is, in one line, for any message: AI sports analysis, a
transparent track record, and market and price context. Not "a proven edge".
Not "a line-price checker".

## Granting access (admin page, Testers section)

1. `https://linehound.app/web/admin.html`, paste the admin token.
2. Testers: type their email, "Grant 7-day tester access". The page shows
   "N of 20 granted".
3. The access token appears ONCE. Copy it and send it yourself, over the
   channel they wrote from. It is not stored and cannot be shown again; if it
   is lost, "Extend 7 days" (with a reason) issues a fresh one and does not
   use another of the 20 places.
4. Log it: `python scripts/outreach_batch.py signup --lead <id>` when they
   sign up, `activated --lead <id>` when the Testers table shows them as
   activated (they used the token).

Message to send with the token (edit freely, keep the five facts):

```
You're in: 7 days of early access to LineHound, no card.

Sign in here: https://linehound.app/web/index.html#/signin
Paste this token: <token>

What it is: tonight's card before the game (the bet, the best price and
where to find it, and why), plus matchups, odds and props. Every card is
graded in public afterwards.

What to know: this is early access and performance is not proven. The
current MLB record is negative and it's on the record page with every loss.
It's analysis, not advice. Access ends after 7 days.

The one thing I'd ask: after a couple of nights, tell me what was useful,
what was confusing, and whether you'd pay for it.
```

## The outreach loop

Send by hand, one at a time, from `docs/sales/batch_01.md`. After each:

| What happened | Command | Status it becomes |
|---|---|---|
| (nothing yet) | | NOT_SENT |
| You sent it | `python scripts/outreach_batch.py sent --batch 1 --items 3` | SENT |
| They replied | `... reply --lead <id> --classification question` (or `interested`, `not_interested`, `hostile`, `auto`) | REPLIED / INTERESTED / NOT_INTERESTED |
| They signed up on the site | `... signup --lead <id>` | SIGNED_UP |
| They used their tester token | `... activated --lead <id>` | ACTIVATED |
| They said they would pay | `... would-pay --lead <id>` | WOULD_PAY |
| They paid | `... paid --lead <id> --revenue 19.99` | PAID |
| You owe them a follow-up | `... followup --lead <id> --date 2026-10-09` | FOLLOW_UP |

`python scripts/outreach_batch.py milestones` prints the first time each of
these happened: first reply, first interested person, first signup, first
active tester, first "I would pay", first payment. The survival dashboard
shows the same counts, one row per lead: a second message, a repeat visit or
a second channel for the same person never adds a lead.

How you know a lead signed up: the admin page's funnel has a "By source"
table. Each outreach link carries the lead's id, so the row is named after
the lead (for example `l012-unit-circle`).

Order for batch 1: the two forums first (items 1 and 2: promotion is allowed
there), then the four creators, then the five X replies (replace the bracket
with something specific from their post; about 55 characters fit), then at
most five Discord notes a day. No copy-paste to several people at once, no
automation.

## Not yet (before billing opens)

A tester whose 7 days ran out cannot buy from the signup form today: the
form reports their account as "invited" and does not open a checkout. That
must be fixed before production billing is switched on.
