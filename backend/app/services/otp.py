"""Email codes: generation, canonicalisation and hashing.

The code is generated here, not by Supabase, because the limits that make a code
safe (5 attempts, 10-minute expiry, one active code per address, 60-second
resend cooldown) have to be enforced in the same transaction that verifies it.
FastAPI owns the code; Supabase only creates the identity once a username and
password exist.

Only the hash is stored. A dump of `auth_challenges` therefore reveals nothing
that can be typed into the login form.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

CODE_LENGTH = 6
_MAX = 10**CODE_LENGTH


def issue_code() -> str:
    """A 6-digit code from `secrets`, zero-padded, leading zeros allowed."""
    return f"{secrets.randbelow(_MAX):0{CODE_LENGTH}d}"


def normalize_code(raw: str) -> str | None:
    """Strip spaces and dashes people paste from mail clients; reject the rest."""
    cleaned = "".join(ch for ch in raw if ch.isdigit())
    if len(cleaned) != CODE_LENGTH:
        return None
    return cleaned


def hash_code(code: str, pepper: str) -> str:
    """Domain-separated hash so a leaked row cannot be brute-forced cheaply."""
    material = f"auth-code:{code}".encode()
    return hmac.new(pepper.encode(), material, hashlib.sha256).hexdigest()


def code_matches(submitted: str, stored_hash: str, pepper: str) -> bool:
    return hmac.compare_digest(hash_code(submitted, pepper), stored_hash)


def hash_token(token: str) -> str:
    """Signup tokens are opaque, so a plain hash of the value is enough."""
    return hashlib.sha256(f"signup-token:{token}".encode()).hexdigest()


def issue_token() -> str:
    return secrets.token_urlsafe(32)
