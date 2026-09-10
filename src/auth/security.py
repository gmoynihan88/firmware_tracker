"""Password hashing and signed session tokens, using only the standard library.

Nothing here needs passlib, itsdangerous or python-jose. scrypt, hmac and
compare_digest cover it, and for a single-user self-hosted app that is a better
trade than three dependencies to keep patched in a container.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

# Cost parameters. n=2**14 keeps a verification around 50ms on modest hardware:
# slow enough to make guessing expensive, fast enough that a login is not noticeable.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a password for storage in .env. Format: scrypt$<salt_b64>$<hash_b64>."""
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return "scrypt${}${}".format(
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored hash, in constant time.

    Returns False rather than raising on a malformed hash: a broken value in .env
    should deny access, not crash every request.
    """
    try:
        scheme, salt_b64, digest_b64 = stored.split("$", 2)
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except Exception:
        return False

    candidate = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return hmac.compare_digest(candidate, expected)


def _sign(payload: bytes, secret: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    ).decode().rstrip("=")


def issue_token(secret: str, lifetime_seconds: int, subject: str = "owner") -> str:
    """Mint a signed session token carrying its own expiry."""
    payload = json.dumps(
        {"sub": subject, "exp": int(time.time()) + lifetime_seconds}, separators=(",", ":")
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{body}.{_sign(payload, secret)}"


def read_token(token: str, secret: str) -> Optional[dict]:
    """Return the token's claims, or None if it is malformed, forged or expired."""
    if not token or not secret or "." not in token:
        return None

    body, signature = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except Exception:
        return None

    # Compare in constant time, and verify before parsing anything from the payload.
    if not hmac.compare_digest(_sign(payload, secret), signature):
        return None

    try:
        claims = json.loads(payload)
    except Exception:
        return None

    if not isinstance(claims, dict) or claims.get("exp", 0) < time.time():
        return None

    return claims


def generate_secret_key() -> str:
    return secrets.token_urlsafe(48)
