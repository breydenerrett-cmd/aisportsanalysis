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
4. Log it: `python scripts/outreach_batch.py tester-access --lead <id>` when
   you grant access (it counts as an active tester for 7 days), `signup --lead
   <id>` when they sign up, `activated --lead <id>` when the Testers table
   shows them as activated (they used the token).

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

Send by hand, one at a time, from `docs/sales/batch_01.md`. After each (every
command starts `python scripts/outreach_batch.py`, written `...` below; add
`--at 2026-10-04T18:30:00Z` to any of them to log something that happened earlier):

| What happened | Command | Where it shows |
|---|---|---|
| Plan the order | `... set-group --leads <id>,<id> --group 1`, then `... next-group` | `next-group` prints the lowest group still to send: each lead, its batch file and item number, and the exact `sent` command |
| You sent it | `... sent --batch 1 --items 3` | MESSAGES SENT; with no answer for more than 7 days it reads as NO_REPLY on its own |
| They replied | `... reply --lead <id> --type CURIOUS --said "what they wrote"` | REPLIES; POSITIVE REPLIES for the four positive types |
| They changed their mind | the same `reply` with a new `--type` | the first reply time stays; only the type moves |
| A person answered a forum thread, or wrote in on their own | `... add --via <thread_id> --channel discord --handle "their handle" --type CURIOUS --said "what they wrote"` | a new person row with an id like `l041-p`; a lead as soon as it is added |
| The same human on a second platform | `... alias --lead <id> --handle "their email"` | nothing public; stops a duplicate row |
| You granted tester access | `... tester-access --lead <id>` | ACTIVE TESTERS for 7 days |
| They signed up on the site | `... signup --lead <id>` | SIGNUPS |
| They used their tester token | `... activated --lead <id>` | ACTIVATED USERS |
| They gave feedback | `... feedback --lead <id> --said "what they said"` | the "First feedback" milestone |
| They said whether they would pay | `... would-pay --lead <id> --price 15 --said "..."` (or `--no`) | WOULD PAY; the price is kept as `price_signal=15` in notes |
| They paid | `... paid --lead <id> --revenue 19.99` | PAID USERS and REVENUE |
| You owe them a follow-up | `... followup --lead <id> --date 2026-10-09` | the follow-up date |

Reply types (`--type`, any capitals): POSITIVE_INTEREST, CURIOUS, SIGNED_UP,
ACTIVE_TESTER, WOULD_PAY, PRICE_OBJECTION, TRUST_OBJECTION, PRODUCT_CONFUSION,
NOT_INTERESTED, SPAM_OR_IRRELEVANT. POSITIVE_INTEREST, SIGNED_UP, ACTIVE_TESTER
and WOULD_PAY count as positive replies. NO_REPLY is never typed. The old words still work: `interested`,
`question`, `not_interested`, `hostile`, `auto`.

Look at the state any time: `... status` (one line per lead with activity, and
the count for every reply type, zeros included), `... milestones` (the first
reply, first positive reply, first signup, first tester access, first active
tester, first feedback, first "I would pay" and first payment, each with its
time and lead id), `... next-group`.

Who counts as a lead: a person (not a forum thread) who was sent a message,
replied or signed up. A forum thread is a post, not a human: when someone
answers it, use `add --via <thread_id>`, never `reply` on the thread. If `add`
says the handle already belongs to a lead, that human is already in the queue:
use `alias` and log against the existing id. Reply rate, signup rate, activation
rate, would-pay rate and paid conversion all print as `n of d (pct)`, say "no
rate yet" from a zero denominator and "small sample" under 30.

The repository is public. The queue and `pipeline.csv` hold ids, channels,
times and reply types only. Everything a person wrote (`--said`) and who they
are (`--handle`, `alias`) goes to `data/private/outreach_private.jsonl`, which
is gitignored, append-only and never edited. Never put a name, handle, email,
link or quote in `--note`; the command refuses it. Back that file up yourself:
it exists on this machine only.

Product numbers for the dashboard: paste the Testers table totals into
`config/business.json` under `tester_activity` (`as_of`, `testers_granted`,
`testers_in_window`, `activated`, `returning`, `median_hours_signup_to_activation`,
and `feature_users`, a `{feature: testers who used it}` object), then run
`python scripts/survival_dashboard.py`. Without it the dashboard counts
ACTIVATED USERS from this log and prints RETURNING USERS as not measured yet.

`python scripts/survival_dashboard.py` shows the same counts, one row per
person: a second message, a repeat visit or a second channel for the same
person never adds a lead.

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
