"""Password policy.

No composition rules (the brief forbids them). What is checked instead:

* length 8-128;
* not equal to the username or the email, ignoring case;
* not a known-breached password, via HaveIBeenPwned's k-anonymity range API:
  only the first five hex characters of the SHA-1 leave the server, the rest is
  compared locally. If the service is slow or down, the check **fails open** —
  an unreachable API must not stop a real person from signing up.
"""

from __future__ import annotations

import hashlib
import re

from app.core.config import settings

HIBP_RANGE = "https://api.pwnedpasswords.com/range/"

_COMPOSITION_FREE = re.compile(r"^[\s\S]{8,128}$")


def policy_errors(password: str, *, username: str | None = None, email: str | None = None) -> list[str]:
    problems: list[str] = []
    if len(password) < settings.auth_password_min_length:
        problems.append(f"password must be at least {settings.auth_password_min_length} characters")
    if len(password) > settings.auth_password_max_length:
        problems.append(f"password must be at most {settings.auth_password_max_length} characters")
    if username and password.strip().lower() == username.strip().lower():
        problems.append("choose a password that is not your username")
    if email and password.strip().lower() == email.strip().lower():
        problems.append("choose a password that is not your email address")
    return problems


def is_breached(password: str, timeout: float = 3.0) -> bool:
    """Return True only when HIBP positively lists the password."""
    try:
        import httpx

        digest = hashlib.sha1(password.encode()).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        response = httpx.get(f"{HIBP_RANGE}{prefix}", timeout=timeout)
        if response.status_code != 200:
            return False
        for line in response.text.splitlines():
            candidate, _, _count = line.partition(":")
            if candidate.strip().upper() == suffix:
                return True
        return False
    except Exception:
        # Fail open by design: an outage at HIBP must not block signups.
        return False
