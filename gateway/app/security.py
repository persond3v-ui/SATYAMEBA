"""Cryptographic primitives: password hashing, JWT issue/verify, per-session
request signing (HMAC), and helpers.

Design notes
------------
* Access tokens are short-lived (15 min) RS256 JWTs. The gateway holds the
  private key; anything that needs to *verify* a token only needs the public
  key. This means a compromised verifier cannot mint tokens.
* Each login also issues a per-session ``signing_key``. The SPA signs every
  state-changing request with HMAC-SHA256 over a canonical string that includes
  method, path, body hash, a timestamp and a nonce. A token replayed from a
  capture (e.g. Burp) without a fresh, correctly-signed envelope is rejected,
  and the timestamp window kills replay. (It does NOT hide traffic from a user
  proxying their *own* live session — that is impossible in a browser — but it
  does defeat tampering and replay, which is the real threat model.)
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings

settings = get_settings()

_BCRYPT_ROUNDS = 12
# bcrypt only considers the first 72 bytes of the password; bcrypt >= 4.1 raises
# on longer inputs, so we truncate explicitly (the schema also caps length).
_MAX_PW_BYTES = 72


# --------------------------------------------------------------------------- #
# Passwords (bcrypt directly — passlib is unmaintained and breaks on bcrypt 4.1)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_MAX_PW_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        pw = password.encode("utf-8")[:_MAX_PW_BYTES]
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _signing_material() -> tuple[str, str]:
    """Return (key, algorithm) for signing."""
    if settings.jwt_algorithm == "RS256" and settings.jwt_private_key:
        return settings.jwt_private_key, "RS256"
    return settings.jwt_secret, "HS256"


def _verifying_material() -> tuple[str, str]:
    if settings.jwt_algorithm == "RS256" and settings.jwt_public_key:
        return settings.jwt_public_key, "RS256"
    return settings.jwt_secret, "HS256"


def create_access_token(*, sub: str, role: str, jti: str, extra: dict | None = None) -> str:
    key, alg = _signing_material()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "jti": jti,
        "type": "access",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "iss": "satyameba-gateway",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, key, algorithm=alg)


def decode_token(token: str) -> dict:
    key, alg = _verifying_material()
    return jwt.decode(
        token,
        key,
        algorithms=[alg],
        issuer="satyameba-gateway",
        options={"require": ["exp", "iat", "sub", "jti"]},
    )


def new_jti() -> str:
    return secrets.token_urlsafe(24)


def new_signing_key() -> str:
    return secrets.token_hex(32)


# --------------------------------------------------------------------------- #
# Request signing (HMAC)
# --------------------------------------------------------------------------- #
def canonical_string(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body or b"").hexdigest()
    return "\n".join([method.upper(), path, timestamp, nonce, body_hash])


def sign_request(signing_key: str, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    msg = canonical_string(method, path, timestamp, nonce, body).encode()
    return hmac.new(bytes.fromhex(signing_key), msg, hashlib.sha256).hexdigest()


def verify_signature(
    signing_key: str, signature: str, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> bool:
    expected = sign_request(signing_key, method, path, timestamp, nonce, body)
    return hmac.compare_digest(expected, signature or "")


# --------------------------------------------------------------------------- #
# Internal HMAC (gateway <-> jupyterhub authenticator)
# --------------------------------------------------------------------------- #
def internal_token(username: str) -> str:
    msg = f"{username}".encode()
    return hmac.new(settings.internal_shared_secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_internal_token(username: str, token: str) -> bool:
    return hmac.compare_digest(internal_token(username), token or "")
