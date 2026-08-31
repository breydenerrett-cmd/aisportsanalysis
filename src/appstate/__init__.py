"""Provider-agnostic user/auth/billing state for the paid beta.

Everything here is stdlib-only (sqlite3 + secrets + hashlib), same as the
rest of src/ (tests/test_api_boundary.py enforces the stdlib-only rule for
all of src/, not just the pre-existing modules). No external auth or
billing provider is wired in yet -- see docs/LAUNCH_DECISIONS.md for the
decisions that unblock a real provider (Clerk for auth, Stripe for
billing). Until those land:

- users.py is the whole auth story: invite-token issuance, opaque bearer
  tokens hashed at rest, no passwords.
- savedbets.py is "My Bets" -- append-only per-user saved-bet records.
- billing.py is an ABSTRACTION only (Plan/Subscription/BillingProvider
  protocol + a NullBillingProvider stub) so the rest of the app can be
  written against a stable interface before Brey signs off on a provider.
"""
