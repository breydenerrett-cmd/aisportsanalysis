"""Web Push (RFC 8030) with VAPID (RFC 8292) and aes128gcm payload encryption (RFC 8291/8188), no push library.

WHY HAND-ROLLED. The app image carries five pinned packages; ``pywebpush`` would add six more. The protocol is
short: sign a JWT with the app's P-256 key, encrypt the payload to the browser's key with ECDH + HKDF + AES-GCM,
POST it to the endpoint the browser gave us. The one dependency is ``cryptography`` (api/requirements.txt), imported
LAZILY: a machine without it (the Linux CI image that has no FastAPI either) loads this module and simply reports
push as unavailable.

OFF UNLESS THE KEY IS SET. The only secret is ``VAPID_PRIVATE_KEY`` (url-safe base64 of the 32-byte P-256 scalar);
the public key the browser needs is DERIVED from it, so the two can never disagree. ``VAPID_SUBJECT`` (a mailto:
or https: contact the push service can reach; default ``mailto:hounds@linehound.app``) is public. With the key
missing, ``status()`` says why and ``send`` returns ``disabled`` without touching the network. docs/owner/ALERTS.md
has the owner's key step. The private key is never logged and never returned.

A push service answers 404 or 410 when a subscription is dead (the member cleared site data, uninstalled):
``send`` returns ``gone`` so the dispatcher deletes it.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Callable, Mapping, Optional
from urllib.parse import urlparse

ENV_PRIVATE = "VAPID_PRIVATE_KEY"
ENV_SUBJECT = "VAPID_SUBJECT"
DEFAULT_SUBJECT = "mailto:hounds@linehound.app"
TTL_S = 3600                   # an alert older than an hour is not worth showing
JWT_LIFETIME_S = 12 * 3600     # the spec caps a VAPID token at 24 hours
RECORD_SIZE = 4096
MAX_PAYLOAD = 3500             # one record: 4096 - 16 (tag) - 1 (delimiter) - header, with headroom

R_SENT, R_GONE, R_FAILED, R_DISABLED = "sent", "gone", "failed", "disabled"

Sender = Callable[[str, Mapping[str, str], bytes, float], "tuple[int, bytes]"]


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        return {"hashes": hashes, "serialization": serialization, "ec": ec, "AESGCM": AESGCM, "HKDF": HKDF,
                "decode_dss_signature": decode_dss_signature}
    except Exception:  # noqa: BLE001 -- not installed
        return None


def private_key_value(env: Optional[Mapping] = None) -> Optional[str]:
    source = env if env is not None else os.environ
    return str(source.get(ENV_PRIVATE) or "").strip() or None


def _load_private(env: Optional[Mapping] = None):
    c = _crypto()
    value = private_key_value(env)
    if c is None or value is None:
        return None
    try:
        scalar = int.from_bytes(b64u_decode(value), "big")
        return c["ec"].derive_private_key(scalar, c["ec"].SECP256R1())
    except Exception:  # noqa: BLE001 -- a malformed secret: disabled, not a crash, and never echoed
        return None


def public_key(env: Optional[Mapping] = None) -> Optional[str]:
    """The application server key the browser subscribes with (url-safe base64, 65-byte uncompressed point)."""
    key = _load_private(env)
    if key is None:
        return None
    c = _crypto()
    raw = key.public_key().public_bytes(c["serialization"].Encoding.X962,
                                        c["serialization"].PublicFormat.UncompressedPoint)
    return b64u(raw)


def status(env: Optional[Mapping] = None) -> dict:
    """{available, reason}: what the Alerts screen says about push."""
    if _crypto() is None:
        return {"available": False, "reason": "The push library is not installed on this server."}
    if private_key_value(env) is None:
        return {"available": False, "reason": "Push is not set up on this server yet (no VAPID key)."}
    if _load_private(env) is None:
        return {"available": False, "reason": "The VAPID key on this server is not valid."}
    return {"available": True, "reason": ""}


def generate_private_key() -> str:
    """A fresh VAPID private key in the form the env var wants (used by scripts/vapid_keys.py)."""
    c = _crypto()
    if c is None:
        raise RuntimeError("the 'cryptography' package is required")
    key = c["ec"].generate_private_key(c["ec"].SECP256R1())
    return b64u(key.private_numbers().private_value.to_bytes(32, "big"))


def vapid_headers(endpoint: str, env: Optional[Mapping] = None, *, now: Optional[float] = None) -> Optional[dict]:
    key = _load_private(env)
    if key is None:
        return None
    c = _crypto()
    parsed = urlparse(endpoint)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    source = env if env is not None else os.environ
    subject = str(source.get(ENV_SUBJECT) or "").strip() or DEFAULT_SUBJECT
    exp = int((now if now is not None else time.time()) + JWT_LIFETIME_S)
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": audience, "exp": exp, "sub": subject}, separators=(",", ":")).encode())
    signing_input = f"{head}.{claims}".encode("ascii")
    der = key.sign(signing_input, c["ec"].ECDSA(c["hashes"].SHA256()))
    r, s = c["decode_dss_signature"](der)
    token = f"{head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return {"Authorization": f"vapid t={token}, k={public_key(env)}"}


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: Optional[bytes] = None, ephemeral=None) -> bytes:
    """The aes128gcm request body for one browser (RFC 8291). ``salt`` and ``ephemeral`` are injectable for tests."""
    c = _crypto()
    if c is None:
        raise RuntimeError("the 'cryptography' package is required")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("push payload too large")
    ec, hashes, ser = c["ec"], c["hashes"], c["serialization"]
    ua_public_raw = b64u_decode(p256dh)
    auth_secret = b64u_decode(auth)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_raw)
    as_private = ephemeral or ec.generate_private_key(ec.SECP256R1())
    as_public_raw = as_private.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)
    shared = as_private.exchange(ec.ECDH(), ua_public)
    ikm = c["HKDF"](algorithm=hashes.SHA256(), length=32, salt=auth_secret,
                    info=b"WebPush: info\x00" + ua_public_raw + as_public_raw).derive(shared)
    salt = salt if salt is not None else os.urandom(16)
    cek = c["HKDF"](algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = c["HKDF"](algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    sealed = c["AESGCM"](cek).encrypt(nonce, payload + b"\x02", None)
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public_raw)]) + as_public_raw + sealed


def decrypt(body: bytes, ua_private, auth: str) -> bytes:
    """The inverse, for tests (what the browser does): proves the body is a valid RFC 8291 message."""
    c = _crypto()
    ec, hashes, ser = c["ec"], c["hashes"], c["serialization"]
    salt, idlen = body[:16], body[20]
    as_public_raw = body[21:21 + idlen]
    sealed = body[21 + idlen:]
    ua_public_raw = ua_private.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)
    shared = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public_raw))
    ikm = c["HKDF"](algorithm=hashes.SHA256(), length=32, salt=b64u_decode(auth),
                    info=b"WebPush: info\x00" + ua_public_raw + as_public_raw).derive(shared)
    cek = c["HKDF"](algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = c["HKDF"](algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    plain = c["AESGCM"](cek).decrypt(nonce, sealed, None)
    return plain.rstrip(b"\x00")[:-1]


def send(subscription: Mapping, payload: Mapping, *, http: Sender, env: Optional[Mapping] = None,
         timeout: float = 10.0) -> str:
    """Push ``payload`` (a dict, JSON-encoded) to one subscription. Returns sent | gone | failed | disabled.
    Never raises, never logs the endpoint or the body."""
    if status(env)["available"] is False:
        return R_DISABLED
    try:
        body = encrypt(json.dumps(dict(payload), separators=(",", ":")).encode("utf-8"),
                       subscription["p256dh"], subscription["auth"])
        headers = {"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                   "TTL": str(TTL_S), "Urgency": "high", **vapid_headers(subscription["endpoint"], env)}
        code, _ = http(subscription["endpoint"], headers, body, timeout)
    except Exception:  # noqa: BLE001
        return R_FAILED
    if 200 <= code < 300:
        return R_SENT
    if code in (404, 410):
        return R_GONE
    return R_FAILED
