# Resend integration plan (welcome email) -- DRAFT, not implemented

Working brand: LINEHOUND (temporary, pending trademark/domain clearance --
Brey 2026-09-01 decision, same caveat `docs/RETENTION_EMAILS.md` states).

**Scope of this document:** the ONE email this task is about -- the
welcome/activation email that hands a paying user their access token by
email instead of relying solely on the browser landing back on `GET
/signup/complete`. It is a plan only: no code in `src/` or `api/` is
touched by this task, no dependency is added, no Resend account exists
yet, and no network call to Resend happens anywhere in this repo today.
`docs/RETENTION_EMAILS.md`'s four templates (digest, day-3, cancel-save,
win-back) are a separate, later effort and are out of scope here --
though this plan's provider client is written so that work can reuse it
without re-deriving the transport pattern.

## Why this needs to exist at all

`api/signup.py`'s module docstring names the gap directly, under "THE
NO-EMAIL-SENDER ACTIVATION BRIDGE": there is no transactional email
sender wired into this app. `GET /signup/complete?session_id=...` is the
only way a paying user's one-time access token reaches them today -- it
works only if the browser tab that started Stripe Checkout survives the
redirect back. Close that tab, lose that token, and (per
`src.appstate.customers.take_activation_token`'s docstring) there is no
way to tell the user "you already used it" apart from "you never paid"
or "that session doesn't exist" -- all three collapse to the same 404.
An email is the safety net: it does not replace the redirect bridge, it
gives the same token a second path that survives a closed tab.

## Where the token actually gets minted (verified against current repo)

`src/appstate/billing.py`'s `apply_stripe_webhook_event` handles
`checkout.session.completed` by calling `_activate_signup(user_id,
obj.get("id"), db=db)` (billing.py line ~651). `_activate_signup`
(billing.py, immediately below `apply_stripe_webhook_event`) is where the
token is actually born:

```python
def _activate_signup(user_id: int, stripe_session_id: Optional[str], *,
                      db: Optional[Path] = None) -> None:
    user = users_store.get_user(user_id, db=db)
    if user is None:
        return
    if user.status == "pending_payment":
        users_store.set_user_status(user_id, "active", db=db)
    if not stripe_session_id or customers.has_activation_token(stripe_session_id, db=db):
        return
    raw_token = users_store.issue_invite_token(user_id, db=db)
    customers.record_activation_token(stripe_session_id, user_id, raw_token, db=db)
    events.record_event_safe(user_id, events.CHECKOUT_COMPLETED, db=db)
```

This is the one and only place in the codebase a fresh activation token
exists in plaintext (`raw_token`) alongside a known `user_id` and the
webhook event that proves payment succeeded. `users_store.get_user(user_id,
db=db)` (already called above) returns a `src.appstate.users.User` whose
`.email` field is the only recipient address this app has -- there is no
first/last name field anywhere in the `users` table (`users(id, email,
created_at, status, plan)`, per `src/appstate/users.py`'s own schema
docstring), so the welcome email's `[FIRST_NAME]`-shaped merge field from
`docs/RETENTION_EMAILS.md` does not apply here; this email addresses the
user by email only, same as every other transactional path in this app.

**This is where the send call attaches**: at the end of
`_activate_signup`, after `record_activation_token` succeeds and before
(or after -- order does not matter, see failure semantics below)
`events.record_event_safe`. Call it there, not from `api/signup.py`,
because `_activate_signup` is the only place that has the raw token,
the user row, and the confirmed-paid webhook event all at once in one
call frame -- `GET /signup/complete` only ever sees the token AFTER
someone (browser or, with this change, also the email) already has it,
via `take_activation_token`, which zeroes `raw_token` out of storage on
first read (see that function's docstring on why the three not-found
cases are deliberately indistinguishable). Sending from
`api/signup.py`'s `signup_complete` route instead would be wrong: that
route only fires when the token bridge is actually used, i.e. exactly
the case the email is supposed to be a fallback FOR.

## New module: `src/appstate/mail.py`

Mirrors the shape `src/appstate/billing.py` already established for an
external HTTPS JSON API behind a stdlib transport, so this reads as "the
same pattern, second vendor" rather than a new architecture:

- `ENV_RESEND_API_KEY = "RESEND_API_KEY"` -- unset means mail is not
  configured, same meaning `ENV_STRIPE_API_KEY` unset has for billing.
- `ENV_EMAIL_FROM = "EMAIL_FROM"` -- the Resend-verified sending address,
  e.g. `"LINEHOUND <hello@notifications.linehound.example>"`. Resend
  requires the domain in this address to have SPF/DKIM/DMARC records
  verified in the Resend dashboard before it will accept sends from it --
  that verification is Brey's account-creation-adjacent step, not
  something this module can do, and is called out explicitly in the "What
  this plan does NOT do" section below.
- `RESEND_API_BASE = "https://api.resend.com"` -- named the same way
  `billing.py`'s `STRIPE_API_BASE` is, for the same reason (a single
  named constant a test can monkeypatch instead of a string literal
  scattered through the module).
- `_urllib_transport(method, url, headers, data) -> _TransportResponse` --
  copy of `billing.py`'s function of the same name, same signature, same
  `_TransportResponse` shape (`status_code: int`, `body: bytes`). Kept as
  its own copy in `mail.py` rather than imported from `billing.py`: the
  two modules talk to different vendors and should not develop a runtime
  coupling just because their lowest-level HTTP plumbing happens to be
  identical stdlib `urllib` boilerplate -- same reasoning
  `src/appstate/customers.py` and `src/appstate/users.py` already apply
  by each keeping their own small `_TransportResponse`-shaped helpers
  rather than sharing one "http utils" module. A future third HTTP-backed
  provider gets the same treatment, not a shared base class, until a
  third copy makes the duplication cost visible enough to refactor.
- `class ResendMailProvider`: constructor takes `api_key: Optional[str] =
  None` (defaults to `os.environ.get(ENV_RESEND_API_KEY)`, same pattern
  `StripeBillingProvider.__init__` uses for `ENV_STRIPE_API_KEY`) and
  `transport: Optional[Callable[...], _TransportResponse]] = None` (so
  every unit test injects a fake transport exactly the way every
  `StripeBillingProvider` test does -- `_urllib_transport` itself must
  never be called by a test, matching billing.py's own comment on that
  function: "Never called by a test").
  - `send_welcome_email(to_email: str, token: str) -> bool` -- POSTs to
    `{RESEND_API_BASE}/emails` with `Authorization: Bearer {api_key}` and
    a JSON body `{"from": EMAIL_FROM, "to": [to_email], "subject": ...,
    "text": ...}` (text-only, matching `docs/RETENTION_EMAILS.md`'s own
    "Text only, no HTML/visual design" rule -- there is no reason this one
    email breaks that convention while the other four templates keep it).
    Returns `True` on a 2xx response, `False` on anything else (4xx from
    Resend, timeout, connection error) -- **never raises**. This function
    is the one and only place a Resend failure is allowed to become a
    boolean instead of an exception; see failure semantics below for why
    that boundary sits here, not in `billing.py`.
  - Raises `MailProviderNotConfigured` (new exception, same naming
    convention as `billing.BillingProviderNotConfigured`) from
    `send_welcome_email` if `api_key` is empty -- callers distinguish
    "not configured yet" (expected, today's honest default) from "tried
    and failed" (a real Resend-side or network problem) the same way
    `_attempt_checkout` in `api/signup.py` distinguishes
    `BillingProviderNotConfigured` from a provider's `RuntimeError`.
- `get_mail_provider() -> "MailProvider"` -- module-level factory mirroring
  `billing.get_billing_provider()`: unset `RESEND_API_KEY` returns a
  `NullMailProvider` whose `send_welcome_email` always returns `False`
  without attempting a network call (the honest "no sender configured"
  default `docs/RETENTION_EMAILS.md`'s "SENDER INFRASTRUCTURE: NOT BUILT"
  section already documents as today's actual state). This keeps
  `_activate_signup` callable unconditionally, in every environment,
  including CI and every existing `tests/test_appstate_billing.py` case,
  with zero behavior change until `RESEND_API_KEY` is actually set.

## The one hard rule: email failure must never fail the webhook

`api/billing.py`'s webhook route returns success to Stripe once
`apply_stripe_webhook_event` returns without raising (Stripe retries a
webhook it did not get a 2xx for -- `apply_stripe_webhook_event`'s own
docstring already makes this point about unhandled event types: "a
webhook endpoint that 500s on a legitimate-but-unhandled event looks like
an outage to Stripe's retry logic"). The exact same argument applies to a
Resend outage: if sending the welcome email could raise out of
`_activate_signup`, a Resend hiccup would make Stripe believe the
*payment webhook itself* failed and retry it -- and a retried webhook
that fails at the same email step every time would make the payment
appear permanently stuck to Stripe's retry logic, even though
`has_activation_token` already correctly guards against minting a SECOND
token on that retry. The token bridge (`GET /signup/complete`) must
remain fully functional regardless of whether the email attempt
succeeded, failed, or was never configured.

Concretely, in `_activate_signup`:

```python
    raw_token = users_store.issue_invite_token(user_id, db=db)
    customers.record_activation_token(stripe_session_id, user_id, raw_token, db=db)
    try:
        mail.get_mail_provider().send_welcome_email(user.email, raw_token)
    except Exception as exc:  # noqa: BLE001 -- see docstring: must never
        # fail the webhook that already recorded a real payment
        print(f"billing: welcome email failed for user_id={user_id}: "
              f"{exc!r}", file=sys.stderr, flush=True)
    events.record_event_safe(user_id, events.CHECKOUT_COMPLETED, db=db)
```

This is the same swallow-and-log shape `events.record_event_safe` already
uses for analytics writes that must not become the caller's problem, and
the same shape `api/signup.py`'s `_attempt_checkout` uses to keep a raw
provider exception from surfacing as this endpoint's unhandled 500 (see
`_CheckoutProviderError`'s docstring). Note `send_welcome_email` is
designed to return `False` rather than raise on an ordinary HTTP failure
(see above), so this `try/except` is a second, redundant belt-and-braces
layer for anything even more unexpected (e.g. a bug in `mail.py` itself)
-- defense in depth, not the primary failure path.

No retry queue, no background job, no "try again in an hour": if the
send fails, the token bridge (`GET /signup/complete`) is still there and
still works, unaffected, exactly as it does today. Building a retry
mechanism is explicitly out of scope for this plan -- it would be new
infrastructure (a queue, a worker) to solve a problem the existing bridge
already solves adequately for a closed beta's volume.

## New event kind (optional but recommended)

`src/appstate/events.py` documents every `record_event_safe` call site in
its module docstring (see the "WIRED-IN CALL SITES" list). If this is
implemented, add one line there and one new kind constant (e.g.
`WELCOME_EMAIL_SENT`) recorded only on `send_welcome_email` returning
`True` -- so `GET /admin/*` (or whatever eventually reads this table) can
answer "did the email path or the redirect bridge actually deliver this
user's token" without grepping stderr logs. Not required for the email to
function; recommended because every other externally-visible transition
in this file already gets an event, and a silent one would be the
odd one out.

## What the welcome email must contain

Kept intentionally close to `GET /signup/complete`'s own response shape
(`{"user_id": ..., "token": ...}`) and to the tone
`docs/RETENTION_EMAILS.md`'s templates already establish (plain text, no
urgency/scarcity language, no HTML), plus the vocabulary rules
`tests/test_customer_language.py` and `tests/test_content_language.py`
enforce (no "+EV" framing, no "true price" claim, no guaranteed outcome):

**Merge fields:** `[EMAIL]` (the user's own address, for a "this was sent
because you signed up with this address" line -- no name field exists,
see above), `[TOKEN]`, `[APP_LINK]` (same `PUBLIC_BASE_URL`
`billing.py`'s `ENV_PUBLIC_BASE_URL` already resolves for Stripe's own
`success_url`/`cancel_url`, reused here rather than a new env var).

**Subject:** `Your LINEHOUND access`

```
Hi,

Thanks for subscribing to LINEHOUND. Your account is active.

Your access token:

    [TOKEN]

Use this token to sign in at [APP_LINK]. If you already saw this token on
the page after checkout, you can ignore this email -- it's a backup copy
in case that page closed before you copied it.

This token is shown once and won't be emailed or displayed again after
you first use it, so save it somewhere before you sign in.

-- LINEHOUND
```

The "shown once" line matters and must stay accurate: `take_activation_token`
zeroes the stored `raw_token` on first read via `GET /signup/complete`,
but sending the email does NOT itself consume the bridge token (email
send happens via `get_mail_provider()`, `take_activation_token` is only
ever called from `api/signup.py`'s `signup_complete` route) -- so a user
could still retrieve the same token from the browser redirect after also
receiving it by email, and either path exhausts it for the other. The
email copy above is written to be true in both orderings without
promising something this implementation doesn't guarantee (e.g. it must
NOT say "this token was already used" or "this is your only copy," since
both could be false depending on which path the user actually took).

## What this plan does NOT do (Brey's remaining steps, explicitly out of scope)

1. **Create the Resend account** and verify a sending domain
   (SPF/DKIM/DMARC records) -- this is the account-creation step this
   task is explicitly scoped to stop before, same category of one-way-door
   decision `docs/RETENTION_EMAILS.md`'s "SENDER INFRASTRUCTURE: NOT
   BUILT" section flags for any email provider choice.
2. **Generate and set `RESEND_API_KEY`** in whatever env/secrets store
   deploys this app (same mechanism `STRIPE_API_KEY` already uses --
   not discovered or specified by this plan).
3. **Set `EMAIL_FROM`** to the actual verified sending address once the
   domain above is verified.
4. **Write the actual code** in `src/appstate/mail.py` and the
   `_activate_signup` call site described above -- this document is the
   plan, not a diff; implementing it is separate work once account
   creation (step 1) is done, since there is nothing to test end-to-end
   against a real Resend account until then (unit tests below need no
   real account, but a true smoke test does).

## Test plan

All of this can be written and merged BEFORE Resend account creation,
the same way `StripeBillingProvider` was fully unit-tested against a
fake `transport` long before any real Stripe key existed
(`tests/test_appstate_billing.py`'s existing pattern):

- `tests/test_appstate_mail.py` (new file):
  - `ResendMailProvider(api_key="re_test_x", transport=fake)` with a fake
    transport asserting the exact `POST {RESEND_API_BASE}/emails` call
    shape (method, path, `Authorization` header, JSON body containing
    `to`/`from`/`subject`/`text`) -- same style
    `tests/test_appstate_billing.py` uses for `create_checkout`.
  - Fake transport returning a 2xx -> `send_welcome_email` returns
    `True`.
  - Fake transport returning 4xx/5xx -> `send_welcome_email` returns
    `False`, never raises.
  - Fake transport raising (simulating a `urllib` network error) ->
    caught inside `send_welcome_email`, returns `False`, never raises --
    this is the behavior the `_activate_signup` hard rule above depends
    on.
  - `api_key=""` (unset) -> raises `MailProviderNotConfigured` from
    `send_welcome_email`, and `get_mail_provider()` with `RESEND_API_KEY`
    unset in `os.environ` returns a `NullMailProvider` whose
    `send_welcome_email` returns `False` with zero calls to `transport`.
- `tests/test_appstate_billing.py` (extend, do not replace): add a case
  asserting `_activate_signup` still transitions `pending_payment` ->
  `active`, still calls `record_activation_token` exactly once, and still
  records `events.CHECKOUT_COMPLETED` when the injected mail provider's
  `send_welcome_email` raises an arbitrary exception -- i.e. pin the hard
  rule ("email failure must never fail the webhook") as a regression
  test, not just prose in this document. A second case pins the same
  three outcomes when `send_welcome_email` returns `False` (the ordinary,
  non-exceptional failure path).
- A future `scripts/funnel_smoke.sh` extension (not required for this
  plan, noted for whoever picks it up) could add a `RESEND_FAKE_TRANSPORT`
  analog to `billing.py`'s `STRIPE_FAKE_TRANSPORT` guarded fake, so the
  end-to-end funnel smoke test can assert an email "send" happened
  without a real Resend account -- same guarded-prefix pattern
  (`FAKE_TRANSPORT_KEY_PREFIX`) to make sure a forgotten flag can never
  mask a real key.
- **Real smoke test** (only possible after Brey completes account
  creation): one real `send_welcome_email` call against a real
  `RESEND_API_KEY` in Resend's own test/sandbox mode (Resend supports
  sending to `delivered@resend.dev` for exactly this) to prove the HTTP
  shape this plan describes actually matches Resend's live API -- not
  automated, a one-time manual check before flipping this on for real
  signups.
