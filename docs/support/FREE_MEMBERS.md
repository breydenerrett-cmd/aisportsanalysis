# Free members and sign-in

This file is shared by two features. Each keeps its own section.

## Free members: give someone full access, free, forever

A free member (a "comp") has full access with no card and no end date, until you
revoke it. It is not a tester (no 7-day clock, no slot of the 20) and it is not
revenue (the revenue view counts subscriptions only). The policy lives in
`src/appstate/comps.py`; this page is the clicks.

Admin page: <https://linehound.app/web/admin.html>
Where they sign in: <https://linehound.app/web/index.html#/signin>

## Give someone free access

1. Open <https://linehound.app/web/admin.html>.
2. In the **Admin token** box paste your admin token, press **Save token**. The
   sections load. (The token is kept for this tab only.)
3. Scroll to **Free members**.
4. **Email**: the person's email. A new address creates the account. An address
   that is already waitlisted, an expired tester or an existing user keeps its
   account and is simply made active.
5. **Why**: one line for your own log, for example `early-access signup, friend of
   the project`. It is required. Never paste a token or key into it; the page
   refuses one.
6. Press **Give free access forever**.
7. The page shows the access token once, in a box. Press **Copy** (the token) or
   **Copy the message to send** (a ready-to-send note that names the sign-in page
   and holds the token).
8. Send it to them yourself, by email or DM. The token is not stored and cannot be
   shown again. Do not paste it into a ticket or any chat that keeps history.

They open <https://linehound.app/web/index.html#/signin>, paste the token into the
box, press **Save token**, and they are in. Their Billing page says **Free
member**, and nothing asks them to pay.

## Approve someone who is on the waitlist (one click)

1. Same admin page, scroll to **Users**.
2. Find the row whose status is `waitlisted`.
3. Press **Approve as free member** in that row.
4. A box asks why. Type a line and confirm. Cancel, or an empty answer, sends
   nothing.
5. The token appears in the **Free members** section above. Copy and send it as in
   steps 7 and 8 above. The row now shows `yes` under **free member**.

## What can be refused (the page prints the reason)

| Message | Meaning | What to do |
| --- | --- | --- |
| this account is suspended | You suspended them | Lift the suspension first, or leave it |
| a live paid subscription | They are paying right now | Nothing: they already have access |
| a checkout is open | Status `pending_payment` | Let it finish or lapse, then try again |
| already a free member | They have it | Use **New token** if they lost theirs |

A person whose subscription has lapsed or been cancelled is not refused.

## They lost their token

Verify it is them first: write to the address on the account and wait for a reply
FROM that mailbox (the Get help form proves nothing, anyone can type an address).
Then in **Free members**, on their row: type a reason (what you verified, which
ticket) and press **New token**. The old token stops working, the new one is shown
once. Send it as above.

## Take it away

1. **Free members**, on their row, type a reason in the box.
2. Press **Revoke**.

The access and every token end at once, and the row stays in the list as `revoked`
with the date and your reason. To give it back later, use **Give free access
forever** again with the same email.

## What is recorded

- The list keeps who, when, why and whether they have signed in. It never holds a
  token.
- Each grant and revoke writes one analytics event (`comp_access_granted`,
  `comp_access_revoked`) in the same step as the change. It records what the
  account was before and how many tokens were revoked, never the token, the email
  or your reason.
- The access token lasts 10 years. That is "forever" for this product; New token
  gives another 10.

## Free accounts: anyone can sign up (2026-10-19, "yes open signups")

Two different things are called "free" here. A **free member** (above) is someone you approve by hand: full access,
including the daily picks board. A **free account** is what a visitor makes themselves on the sign-in page ("Create a
free account": email, password, optional kennel name). It is active at once, with a 30-day session that every sign-in
renews. Admin People shows it as **Free account**, plan **Free**.

- A free account opens the dogs: kennels, building, editing and backtesting their own dogs, Ask, the locker room,
  fire, fan tips, following. It does **not** open the daily picks board (Today, Games, Odds, Props, the digest and the
  rest): those answer 403 until you approve the person. To upgrade one, use **Approve as free member** or **Grant
  7-day tester** on that row; nothing else changes.
- **A comp grant or revoke clears the person's password** (any token revoke does, by design), so after either they
  sign in with the access code you send and set a new password.
- A signup for an email that already has any account creates nothing and says the same words as a new one; the
  person is told to sign in, or to use Get help if they lost the password.
- Abuse limits: 5 signups an hour per address, 30 an hour and 100 a day overall, a hidden honeypot field, all counted
  in the database. If real people are refused on a busy day, the ceilings are `IP_LIMITS` and `GLOBAL_LIMITS` in
  `src/appstate/free_members.py`. The event `signup_free_created` carries no email.

## Kennel names (a member's public name)

A member names their own kennel on **My kennel** ("Name your kennel", 2 to 30 characters, letters, numbers,
spaces, hyphens and apostrophes). Until they do, the kennel shows as its anonymous handle ("Handler 21E8").
The name appears on the kennels list, their public profile, the leaderboard ("by <name>") and each dog's
page. Two members cannot share a name (capitals, spaces and apostrophes do not make a different one).

Support can set or clear one: **People**, the row's menu, **Set kennel name (reason)**
(`POST /admin/users/kennel-name {user_id, kennel_name, reason}`). The same checks apply (language, protected
brand names, "Handler 1234"-style names, a name already taken); an empty name clears it and the kennel goes
back to its handle. The reason is kept beside the name and is never public. The response and every public
page carry the name only, never the member's email.

## If something looks wrong

- Section missing or empty after saving the admin token: the token was rejected, or
  `APP_ADMIN_TOKEN` is not set on that server. The page says which.
- They paste the token and are sent to a payment page: they were not made a free
  member (check the **Free members** list for their email) or the token was
  replaced by a newer one.

## Passwords

Members can sign in with an email and password instead of pasting an access code.
Tokens are still the session: a password login returns an ordinary token, ending
where that member's access ends (`src/appstate/access.py`, `access_token_end`).

### The member's side

1. Sign in once with the access code (sign-in page, "Have an access code?").
2. A one-time card offers "Set a password so you can sign in with your email next
   time". It can be skipped; "Change password" in the footer opens it again.
3. From then on: email + password. 10+ characters, not the email, not a common password.
4. "Sign out" revokes that device's token. Other devices stay signed in.

### Who can sign in with a password

| Account | Result | Token ends |
|---|---|---|
| Paying subscriber | signs in | the usual subscriber lifetime |
| Early-access tester, window open | signs in | the end of the tester window |
| Early-access tester, window ended | signs in to the "your access ended" screen, not the board | already past |
| Comp (free member) | signs in, once the comp code registers its source (below) | what the comp source returns |
| Waitlisted, pending payment, suspended, lapsed subscriber, admin-invited beta user | refused: "no active access" (only after the CORRECT password) | none |

A wrong password, an unknown email and an account with no password all get the same
answer: "That email and password do not match."

### Forgot password (there is no email sender, so this is manual)

1. Verify the person the same way as a lost access code: a reply from the account's
   own mailbox (`docs/billing/RECOVERY_PROCEDURE.md`). Nothing else proves it.
2. `POST /admin/users/password-reset` with `X-Admin-Token` and
   `{"user_id": 12, "reason": "mailbox reply, ticket 41"}` (or `"email"` instead of
   `user_id`). It deletes the stored password and returns no secret. The reason goes
   into the audit log (`support_password_reset`): never paste a token or a password
   into it (the route refuses one).
3. `POST /admin/users/reissue` for the same account. This also revokes every old
   token, so do both if a password may have leaked. Send the new access code to the
   account's address, never into a ticket or chat.
4. The member signs in with the access code and sets a new password on the card.

### Limits and lockouts

10 attempts per 15 minutes and 50 per day, per client address and per email, kept in
the database (a redeploy does not reset them). Over the limit: HTTP 429 with a
`Retry-After`. Someone typing a member's address repeatedly can lock out that
member's PASSWORD sign-in for the window; the access code is never affected, so tell a
locked-out member to use it or wait.

### For whoever wires the comp (free-member) code

Register one function so a comp can sign in by password:

```python
from src.appstate import access

def _comp_access_end(user, now):   # -> datetime | None
    ...                            # None = not a comp, or the comp was revoked

access.register_access_source("comp", _comp_access_end)
```

Import the module that does this from somewhere the app always loads (api/admin.py
already will). A comp's end must be a real date (a token needs one): use
`now + billing.SUBSCRIBER_TOKEN_TTL`; they get a fresh one at each sign-in.
`api/admin.py::_reissue_plan` (support re-issue) keeps its own copy of the access
rules; when comps are added there, make it call `access.access_token_end` so the two
cannot disagree.

### Security notes

- Hash: scrypt (n=2**14, r=8, p=1), 16-byte random salt, constant-time compare. The
  parameters are stored with each row, so the cost can be raised later.
- No cookies; the session is a bearer token. So there is no CSRF token: the reasoning
  and the tests that pin it are in `api/passwords.py` and `tests/test_api_passwords.py`.
- Events (`login_succeeded`, `login_failed`, `password_set`, `support_password_reset`)
  carry no email, password, hash or token. Failed logins are recorded under one
  anonymous id so an unknown address and a wrong password look identical.
