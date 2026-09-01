# Customer help copy — cancel, refunds, account & token (private beta)

Working brand: Linehound (temporary, pending trademark/domain clearance —
Brey 2026-09-01, same as every other content doc). Text only, no HTML/visual
design (same split `docs/CONTENT_LANDING.md`/`docs/RETENTION_EMAILS.md` make).
This is the customer-facing copy for a static help page or a canned support
reply — nothing here is wired to a real page yet; that is a `web/` task, not
this doc's.

Vocabulary rules apply absolutely: no plus-sign EV framing, no "true"
price/line, no "edge" as a customer noun, no guaranteed outcome, no invented
win probability, `late_move` is never "CLV." Every factual claim below is
cited to the doc/decision it comes from; nothing here states a policy that
isn't already decided somewhere in the repo.

---

## 1. Cancellation

**Decided, not a draft** — `docs/LAUNCH_DECISIONS.md` "Decision (2026-09-01,
Brey, final): cancellation = stop future renewal."

> **Cancel anytime.** Cancelling stops your subscription from renewing — you
> keep full access through the end of the billing period you already paid
> for, and you will not be charged again after that. There's no phone call,
> no "are you sure" screen, and no retention offer standing between you and
> cancelling.

<!-- source: docs/LAUNCH_DECISIONS.md ("cancellation = stop future renewal");
docs/PRICING_OFFER_VALIDATION.md §1's cancel draft (self-serve, no retention
flow) -->

**Known implementation gap, disclosed honestly rather than hidden:** as of
this writing, enforcement of "access ends at period end" is not fully wired
— `docs/LAUNCH_DECISIONS.md` flags that a canceled subscriber currently keeps
access past `current_period_end` until the engineering lane closes that gap.
Do not publish this help copy's cancellation section as a live page until
that gap is closed and verified (a regression test pinning both halves:
canceled-but-inside-period keeps access, canceled-and-past-period is
refused honestly) — see that doc's "Implementation notes for the engineering
lane." Support replies can state the policy as written above regardless,
since the *policy* is decided; only the enforcement is pending.

## 2. Refunds

**Not decided — flagged for Brey, not promised here.** A specific refund
policy (a 7-day, no-questions-asked, once-per-customer window) exists only
as a *draft* inside `docs/PRICING_OFFER_VALIDATION.md` §1, itself part of a
still-open BREY DECISION BLOCK (pricing lock + refund-policy publication are
named there as bundled decisions, both pending before Stage 4 entry per
`docs/COMMERCIAL_READINESS.md`). Per this task's own instruction, this file
does not invent or publish a refund promise ahead of that decision landing.

**What to say to a customer today, until Brey decides:**

> If you were charged and think it was a mistake, email support
> (`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §3's P1 billing path) — refund
> requests are reviewed individually right now while we finalize a written
> refund policy. We'll get back to you the same day.

Do not tell a customer a refund is automatic, guaranteed, or bound to a
specific window (e.g. "7 days, no questions asked") until Brey approves a
policy and it is published here. Once decided, this section replaces the
paragraph above with the approved policy verbatim — do not draft a second,
independent version.

## 3. Account & token help

**Lost or expired invite/access token:**

> Invite and activation tokens expire after 14 days if unused
> (`src/appstate/users.py`). If yours expired or you lost it, email support
> and we'll send a fresh one — this is quick to fix on our end.

<!-- source: docs/ONBOARDING_SUPPORT_PLAYBOOK.md §1, §5 canned response -->

**Paid but never got a token (self-serve signup):**

> If you completed checkout but never got your access token, first check
> whether the confirmation tab is still open in your browser — the token
> is shown there once. If you've closed it, email support with the email
> you used to sign up; there's no automated resend yet, so a real person
> looks up your payment and sends you access directly.

<!-- source: docs/ONBOARDING_SUPPORT_PLAYBOOK.md §1b ("no automated invite-
email sender exists yet"); src/appstate/customers.py (one-time activation
token) -->

**Where's my data / can I delete it:**

> Your saved bets and account data are kept for 30 days after cancellation
> in case you resubscribe, then deleted. You can ask for deletion sooner by
> emailing support.

<!-- source: docs/PRICING_OFFER_VALIDATION.md §1 ("What happens to your data
if you cancel") -->

**"Why can't I see my old support messages in the app":**

> There's no in-app support history yet in this beta — your only record of
> a support exchange today is the email reply. That's a real, deliberate
> scope cut for a two-person team, not a bug.

<!-- source: docs/ONBOARDING_SUPPORT_PLAYBOOK.md §9 -->

**"What should I bet" / any picks question:** use
`docs/ONBOARDING_SUPPORT_PLAYBOOK.md` §5's canned answer verbatim — this
file does not restate it a third time.

## 4. Beta honesty disclaimer (belongs on the same help page)

> This is a private paid beta. Nothing here is a guarantee, a prediction, or
> financial advice — the `recommendation` field is permanently empty by
> design (Ranker Engine 2 stays gated). We publish our research record,
> including the ideas that failed, because that's the actual evidence this
> product offers instead of a track record.

<!-- source: docs/API_CONTRACTS.md ("recommendation" permanently null);
docs/FIRST_CUSTOMER_PLAYBOOK.md §3's demo-script honesty story -->

---

## Open items for Brey (not resolved by this doc)

- **Refund policy decision** — see §2. Nothing here promises a window or
  terms; publish the real policy the moment `docs/PRICING_OFFER_VALIDATION.md`'s
  BREY DECISION BLOCK closes, replacing §2's interim copy in place.
- **Cancellation enforcement gap** — see §1's disclosed gap. Confirm the
  engineering lane has closed it (regression-tested) before this page goes
  live to a real customer who might actually test it by cancelling.
- Product name (`LINEHOUND`) is a working placeholder — same global
  find/replace open item every other content doc carries.
