"""AuthProvider seam: who verifies a bearer token, decided by AUTH_PROVIDER.

WHY A SEAM, NOW
---------------
docs/LAUNCH_DECISIONS.md ("DECIDED BY BREY -- 2026-09-01", Decision 1):
Clerk is the production auth direction; invite-token auth (src/appstate/
users.py) stays as the dev/fallback path. Rather than wait for Clerk
credentials to land before touching api/auth.py, get_current_user resolves
through this seam today -- swapping the active provider later is a one-line
env change (AUTH_PROVIDER=clerk), not a rewrite of every authed endpoint.
This mirrors src/appstate/billing.py's BillingProvider seam, built for the
same reason at the same time.

WHY CLERK IS KEY-LESS HERE
---------------------------
Verifying a Clerk session means verifying an RS256 JWT against Clerk's
JWKS -- fetching and caching a JWKS, matching `kid`, checking `exp`/`iss`/
`aud`, all correctly, none of it forgiving of a subtle bug. This repo does
not hand-roll JWT crypto in stdlib (the same reasoning src/appstate/
billing.py's module docstring gives for not hand-rolling payment
processing). ClerkProvider therefore always refuses -- via
AuthProviderNotConfigured, never a fake-verified user -- until a real JWT/
Clerk SDK dependency is reviewed and approved. That approval, plus Brey
creating the actual Clerk org and issuing CLERK_JWKS_URL/CLERK_ISSUER, is
the named Brey trigger; see ClerkProvider's docstring for the exact
conditions checked.

PROVIDER SELECTION
------------------
AUTH_PROVIDER chooses the active provider; unset defaults to "invite_token"
(today's only working path). An unrecognized value is a hard error at
selection time -- silently falling back to invite-token auth because someone
mistyped "clark" would be a security regression that looks like nothing
happened.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol

from src.appstate import users as users_store

ENV_AUTH_PROVIDER = "AUTH_PROVIDER"
ENV_CLERK_JWKS_URL = "CLERK_JWKS_URL"
ENV_CLERK_ISSUER = "CLERK_ISSUER"

DEFAULT_AUTH_PROVIDER = "invite_token"

# What an AuthProvider resolves a bearer token to. Concretely this is
# users_store.User today (the only provider that actually authenticates
# anyone) -- kept as an alias rather than a new dataclass so InviteTokenProvider
# needs no translation layer and every existing consumer of get_current_user's
# return value (api/mybets.py, api/betcheck.py, ...) keeps working unchanged.
# A future provider that authenticates against an identity it does not
# itself store as a users_store.User row (Clerk) would need to map into one
# (or extend this alias) before it could return real users -- not yet done,
# since ClerkProvider never gets that far (see class docstring).
AuthedUser = users_store.User


class AuthProviderNotConfigured(RuntimeError):
    """Raised by resolve() when the selected provider cannot verify
    anything right now for lack of configuration or an approved
    dependency -- distinct from "no matching user" (plain None), which
    means "this credential doesn't work." NotConfigured means "this
    provider cannot work at all yet," which callers (api/auth.py) turn
    into a loud 503 rather than a 401 that would look like the caller's
    fault.
    """


class AuthProvider(Protocol):
    """The interface every auth provider implements. api/auth.py's
    get_current_user programs against this, never against a concrete
    provider, so swapping InviteTokenProvider for ClerkProvider later is
    the AUTH_PROVIDER env change described in the module docstring, not a
    rewrite of every authed endpoint."""

    name: str

    def resolve(self, authorization: Optional[str]) -> Optional[AuthedUser]:
        """Resolve the raw `Authorization` header value (None if the
        header was absent) to a user, or None if the credential is
        missing/malformed/unknown/expired/revoked. Only the Authorization
        header is passed (not a full headers mapping) because that is all
        either provider here needs -- invite tokens and Clerk session
        JWTs both ride in `Authorization: Bearer <token>`; a future
        provider needing more than one header would take a broader
        parameter then, not a hypothetical dict no code exercises today.

        Raises AuthProviderNotConfigured if the provider cannot verify
        anything right now (see that exception's docstring) -- this is
        the one case that is not simply "no user."
        """
        ...


class InviteTokenProvider:
    """Wraps src.appstate.users' existing invite-token path. No behavior
    change from what api/auth.py's get_current_user did before this seam
    existed -- same header parsing, same call to users_store.authenticate.
    This is the DEFAULT_AUTH_PROVIDER and, until Clerk is approved and
    configured, the only provider that ever resolves anyone.
    """

    name = "invite_token"

    def resolve(self, authorization: Optional[str]) -> Optional[AuthedUser]:
        if not authorization:
            return None
        scheme, _, raw_token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not raw_token:
            return None
        return users_store.authenticate(raw_token)


class ClerkProvider:
    """Production auth direction (docs/LAUNCH_DECISIONS.md Decision 1).
    Always raises AuthProviderNotConfigured today -- see module docstring
    for why. Two distinct refusal reasons, both non-fatal to construct
    (the class instantiates fine; only resolve() refuses), so selecting
    AUTH_PROVIDER=clerk before Brey has acted fails loudly and safely at
    request time rather than crashing app startup or, worse, silently
    granting access:

    1. CLERK_JWKS_URL / CLERK_ISSUER unset: Brey has not created the
       Clerk org / issued these values yet.
    2. Both set, but JWT verification is still unimplemented: the `clerk`
       (or a JWT/JWKS) SDK dependency has not been reviewed and approved
       for this stdlib-only-in-src/ codebase (see BOUNDARIES in the task
       that added this file). Setting env vars alone cannot skip that
       approval step.

    EXACT BREY TRIGGER: both (a) approving and installing a JWT/Clerk
    verification dependency, and (b) Brey creating the Clerk org and
    providing CLERK_JWKS_URL/CLERK_ISSUER, are required before this class
    does anything but refuse. Neither alone is enough.
    """

    name = "clerk"

    def resolve(self, authorization: Optional[str]) -> Optional[AuthedUser]:
        jwks_url = (os.environ.get(ENV_CLERK_JWKS_URL) or "").strip()
        issuer = (os.environ.get(ENV_CLERK_ISSUER) or "").strip()
        if not jwks_url or not issuer:
            raise AuthProviderNotConfigured(
                f"Clerk auth is not configured: set {ENV_CLERK_JWKS_URL} and "
                f"{ENV_CLERK_ISSUER}. Until Brey provides these, "
                f"AUTH_PROVIDER must stay {DEFAULT_AUTH_PROVIDER!r} (the "
                "default).")
        raise AuthProviderNotConfigured(
            "Clerk env is set, but JWT verification is not yet "
            "implemented: this repo does not hand-roll JWT/JWKS crypto in "
            "stdlib (see src/appstate/authproviders.py module docstring). "
            "It activates once a JWT/Clerk SDK dependency is reviewed and "
            "approved -- a Brey trigger, not a config change.")


_PROVIDERS = {
    InviteTokenProvider.name: InviteTokenProvider,
    ClerkProvider.name: ClerkProvider,
}


def get_provider(name: Optional[str] = None) -> AuthProvider:
    """Construct the active AuthProvider. `name` overrides AUTH_PROVIDER
    for tests; production code always omits it. Unset env -> invite_token
    (today's only working path). An unrecognized value is a hard error --
    never a silent fallback to invite_token, since that would look like a
    successful, more-secure config while quietly running the old one."""
    selected = (name if name is not None else
                os.environ.get(ENV_AUTH_PROVIDER)) or DEFAULT_AUTH_PROVIDER
    selected = selected.strip()
    cls = _PROVIDERS.get(selected)
    if cls is None:
        raise RuntimeError(
            f"unknown {ENV_AUTH_PROVIDER}: {selected!r}; valid values: "
            f"{sorted(_PROVIDERS)}")
    return cls()
