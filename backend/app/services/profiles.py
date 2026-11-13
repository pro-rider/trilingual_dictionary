"""Profile rules that must hold no matter which endpoint calls them.

Two things are enforced here rather than in each route:

* **Column limits.** The service role can write every column of `profiles`, so a
  bug or an over-permissive request model would let a caller flip `status` to
  `active`, rewrite `username` to someone else's, or change `email`. The writable
  set is an allow-list, and every key outside it is a hard error rather than a
  silent drop — a silent drop hides the attempt.
* **Identifier shapes.** Username and email are normalised in exactly one place,
  so the "case-insensitive unique" index cannot be bypassed by a route that
  forgot to lower-case.
"""

from __future__ import annotations

import re

USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,20}$")

# Columns a signed-in user may change through the API. Everything else on the
# table is either identity (user_id, email, username), lifecycle (status,
# activated_at) or agent/ops-owned.
WRITABLE_PROFILE_COLUMNS = frozenset({"display_name", "locale", "ui_language"})

READ_ONLY_PROFILE_COLUMNS = frozenset(
    {
        "user_id",
        "email",
        "username",
        "status",
        "activated_at",
        "created_at",
        "updated_at",
    }
)


class ProfileWriteRejected(ValueError):
    """A profile update tried to touch a column it may not touch."""

    def __init__(self, columns: list[str]) -> None:
        self.columns = columns
        super().__init__(f"columns not writable via API: {', '.join(sorted(columns))}")


def normalize_email(email: str) -> str:
    return email.strip().lower()


RESERVED_USERNAMES = frozenset((
    "admin",
    "administrator",
    "root",
    "sysadmin",
    "system",
    "support",
    "help",
    "helpdesk",
    "staff",
    "moderator",
    "mod",
    "official",
    "security",
    "billing",
    "sales",
    "api",
    "www",
    "mail",
    "ftp",
    "null",
    "undefined",
    "anonymous",
    "guest",
    "user",
    "test",
    "demo",
    "trilingual",
    "dictionary",
    "nepali",
    "ceo",
    "founder",
))


def normalize_username(username: str) -> str:
    """Lower-case and strip. The client may show the original casing later."""
    return username.strip().lower()


def username_shape_errors(username: str) -> list[str]:
    """Return human-readable rule violations; empty means valid."""
    problems: list[str] = []
    if not USERNAME_RE.match(username):
        problems.append("use 3-20 characters: a-z, 0-9, underscore or dot")
    if username != username.lower():
        problems.append("username must be lower-case")
    return problems


def validate_profile_update(fields: dict[str, object]) -> dict[str, object]:
    """Return the fields that may be written, or raise.

    Unknown keys are rejected as a group so the caller learns every offending
    column in one response instead of one per attempt.
    """
    rejected = [key for key in fields if key not in WRITABLE_PROFILE_COLUMNS]
    if rejected:
        raise ProfileWriteRejected(rejected)
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if isinstance(value, str):
            cleaned[key] = value.strip()
        else:
            cleaned[key] = value
    return cleaned


def is_reserved(username: str) -> bool:
    """Mirror of `reserved_usernames` (migration 04).

    The table is the operational source of truth; this copy keeps the check
    testable without Postgres and fails closed if they ever drift apart.
    """
    return normalize_username(username) in RESERVED_USERNAMES
