# Free members and sign-in

This file is shared by two features. Each keeps its own section; do not edit the other's.

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
