"""Persistence for the auth flow.

Two implementations: an in-memory one used by the tests, and a PostgreSQL one
that writes the tables created by `supabase/migrations/`. Both satisfy the same
protocol, so the endpoints and the tests exercise identical logic.

`purpose` is `signup` or `reset`: they are separate challenges for the same
address and must not overwrite each other.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Challenge:
    email_hash: str
    code_hash: str
    expires_at: float
    purpose: str = "signup"
    attempts: int = 0
    sends_in_window: int = 0
    window_started_at: float = field(default_factory=time.time)


@dataclass
class ProfileRow:
    user_id: str
    email: str
    username: str | None
    status: str
    display_name: str | None = None
    locale: str | None = None
    nepali_enabled: bool = True


class AuthStore:
    def get_challenge(self, email_hash: str, purpose: str = "signup"): ...
    def put_challenge(self, challenge: Challenge): ...
    def delete_challenge(self, email_hash: str, purpose: str = "signup"): ...
    def bump_attempts(self, email_hash: str, purpose: str = "signup") -> int: ...
    def save_signup_token(self, token_hash: str, email: str, expires_at: float): ...
    def take_signup_token(self, token_hash: str) -> str | None: ...
    def profile_by_username(self, username: str): ...
    def profile_by_email(self, email: str): ...
    def profile_by_user_id(self, user_id: str): ...
    def create_profile(self, profile: ProfileRow): ...
    def update_profile(self, user_id: str, fields: dict[str, object]): ...
    def username_taken(self, username: str) -> bool: ...
    def create_session(self, session) -> None:
        self.sessions[session.session_id] = session

    def session_by_id(self, session_id: str):
        return self.sessions.get(session_id)

    def session_for_device(self, user_id: str, device_hash: str):
        for session in self.sessions.values():
            if session.user_id == user_id and session.device_hash == device_hash \
                    and session.revoked_at is None:
                return session
        return None

    def list_sessions(self, user_id: str):
        return [s for s in self.sessions.values() if s.user_id == user_id]

    def touch_session(self, session_id: str, now: float) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.last_seen = now

    def revoke_session(self, session_id: str, now: float) -> None:
        session = self.sessions.get(session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = now

    def revoke_all_sessions(self, user_id: str, now: float) -> int:
        count = 0
        for session in self.sessions.values():
            if session.user_id == user_id and session.revoked_at is None:
                session.revoked_at = now
                count += 1
        return count

    def purge_identity_traces(self, *, email: str, email_hash: str) -> int:
        """Remove every pre-account trace of this address (A29)."""
        removed = 0
        for key in [k for k in self.challenges if k[0] == email_hash]:
            self.challenges.pop(key, None)
            removed += 1
        for token, (stored_email, _exp) in list(self.signup_tokens.items()):
            if stored_email == email.strip().lower():
                self.signup_tokens.pop(token, None)
                removed += 1
        return removed

    def anonymize_events(self, user_id: str) -> int: ...
    def delete_profile(self, user_id: str): ...
    def create_session(self, session): ...
    def session_by_id(self, session_id: str): ...
    def session_for_device(self, user_id: str, device_hash: str): ...
    def list_sessions(self, user_id: str): ...
    def touch_session(self, session_id: str, now: float): ...
    def revoke_session(self, session_id: str, now: float): ...
    def revoke_all_sessions(self, user_id: str, now: float) -> int: ...
    def purge_identity_traces(self, *, email: str, email_hash: str) -> int: ...


class MemoryAuthStore(AuthStore):
    """Enough of the real store for a test to behave like production."""

    def __init__(self) -> None:
        self.challenges: dict[tuple[str, str], Challenge] = {}
        self.signup_tokens: dict[str, tuple[str, float]] = {}
        self.profiles: dict[str, ProfileRow] = {}
        self.events: list[dict[str, object]] = []
        self.sessions: dict[str, object] = {}

    def get_challenge(self, email_hash: str, purpose: str = "signup"):
        return self.challenges.get((email_hash, purpose))

    def put_challenge(self, challenge: Challenge) -> None:
        self.challenges[(challenge.email_hash, challenge.purpose)] = challenge

    def delete_challenge(self, email_hash: str, purpose: str = "signup") -> None:
        self.challenges.pop((email_hash, purpose), None)

    def bump_attempts(self, email_hash: str, purpose: str = "signup") -> int:
        challenge = self.challenges.get((email_hash, purpose))
        if challenge is None:
            return 0
        challenge.attempts += 1
        return challenge.attempts

    def save_signup_token(self, token_hash: str, email: str, expires_at: float) -> None:
        self.signup_tokens[token_hash] = (email, expires_at)

    def take_signup_token(self, token_hash: str) -> str | None:
        entry = self.signup_tokens.pop(token_hash, None)
        if entry is None or entry[1] < time.time():
            return None
        return entry[0]

    def profile_by_username(self, username: str):
        for profile in self.profiles.values():
            if (profile.username or "").lower() == username.lower():
                return profile
        return None

    def profile_by_email(self, email: str):
        for profile in self.profiles.values():
            if profile.email.lower() == email.lower():
                return profile
        return None

    def profile_by_user_id(self, user_id: str):
        return self.profiles.get(user_id)

    def create_profile(self, profile: ProfileRow) -> None:
        if self.profile_by_email(profile.email) is not None:
            raise ValueError("email already has a profile")
        if profile.username and self.username_taken(profile.username):
            raise ValueError("username taken")
        self.profiles[profile.user_id] = profile

    def update_profile(self, user_id: str, fields: dict[str, object]) -> None:
        profile = self.profiles.get(user_id)
        if profile is None:
            return
        for key, value in fields.items():
            setattr(profile, key, value)

    def username_taken(self, username: str) -> bool:
        return self.profile_by_username(username) is not None

    def delete_profile(self, user_id: str) -> None:
        self.profiles.pop(user_id, None)

    def create_session(self, session) -> None:
        self.sessions[session.session_id] = session

    def session_by_id(self, session_id: str):
        return self.sessions.get(session_id)

    def session_for_device(self, user_id: str, device_hash: str):
        for session in self.sessions.values():
            if session.user_id == user_id and session.device_hash == device_hash \
                    and session.revoked_at is None:
                return session
        return None

    def list_sessions(self, user_id: str):
        return [s for s in self.sessions.values() if s.user_id == user_id]

    def touch_session(self, session_id: str, now: float) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.last_seen = now

    def revoke_session(self, session_id: str, now: float) -> None:
        session = self.sessions.get(session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = now

    def revoke_all_sessions(self, user_id: str, now: float) -> int:
        count = 0
        for session in self.sessions.values():
            if session.user_id == user_id and session.revoked_at is None:
                session.revoked_at = now
                count += 1
        return count

    def purge_identity_traces(self, *, email: str, email_hash: str) -> int:
        """Remove every pre-account trace of this address (A29)."""
        removed = 0
        for key in [k for k in self.challenges if k[0] == email_hash]:
            self.challenges.pop(key, None)
            removed += 1
        for token, (stored_email, _exp) in list(self.signup_tokens.items()):
            if stored_email == email.strip().lower():
                self.signup_tokens.pop(token, None)
                removed += 1
        return removed

    def anonymize_events(self, user_id: str) -> int:
        """Null the identifiers that can still point at one person.

        `user_id` alone is not enough: a stable `device_id` links the remaining
        rows back to a single handset for the whole 30-day window, which is a
        pseudonym, not an anonymisation.
        """
        changed = 0
        for event in self.events:
            if event.get("user_id") == user_id:
                event["user_id"] = None
                event["device_id"] = None
                event["ip_hash"] = None
                changed += 1
        return changed


class PgAuthStore(AuthStore):
    """PostgreSQL implementation matching migrations 1 and 5.

    Not exercised against a live project in this environment (A23); the SQL
    matches the column names in `supabase/migrations/`.
    """

    def __init__(self, dsn: str | None = None) -> None:
        from app.core.config import settings

        self._dsn = (dsn if dsn is not None else settings.database_url).replace(
            "postgresql+psycopg://", "postgresql://"
        )

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn, autocommit=True)

    def get_challenge(self, email_hash: str, purpose: str = "signup"):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "select email_hash, coalesce(code_hash, ''), expires_at, attempts, "
                "sends_in_window, window_started_at, purpose "
                "from public.auth_challenges where email_hash = %s and purpose = %s "
                "and consumed_at is null",
                (email_hash, purpose),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Challenge(
            email_hash=row[0], code_hash=row[1], expires_at=row[2].timestamp(),
            purpose=row[6], attempts=row[3],
            sends_in_window=row[4], window_started_at=row[5].timestamp(),
        )

    def put_challenge(self, challenge: Challenge) -> None:
        from datetime import datetime

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into public.auth_challenges "
                "(email_hash, purpose, code_hash, expires_at, attempts, sends_in_window, window_started_at) "
                "values (%s, %s, %s, %s, %s, %s, %s) "
                "on conflict (email_hash, purpose) do update set "
                "code_hash = excluded.code_hash, expires_at = excluded.expires_at, "
                "attempts = excluded.attempts, consumed_at = null, "
                "sends_in_window = excluded.sends_in_window, "
                "window_started_at = excluded.window_started_at",
                (
                    challenge.email_hash, challenge.purpose, challenge.code_hash,
                    datetime.fromtimestamp(challenge.expires_at), challenge.attempts,
                    challenge.sends_in_window, datetime.fromtimestamp(challenge.window_started_at),
                ),
            )

    def delete_challenge(self, email_hash: str, purpose: str = "signup") -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from public.auth_challenges where email_hash = %s and purpose = %s",
                (email_hash, purpose),
            )

    def bump_attempts(self, email_hash: str, purpose: str = "signup") -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update public.auth_challenges set attempts = attempts + 1 "
                "where email_hash = %s and purpose = %s returning attempts",
                (email_hash, purpose),
            )
            row = cur.fetchone()
        return row[0] if row else 0

    def save_signup_token(self, token_hash: str, email: str, expires_at: float) -> None:
        from datetime import datetime

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into public.auth_signup_tokens (token_hash, email_hash, email, expires_at) "
                "values (%s, %s, %s) on conflict (token_hash) do nothing",
                (token_hash, email_hash(email), email, datetime.fromtimestamp(expires_at)),
            )

    def take_signup_token(self, token_hash: str) -> str | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "delete from public.auth_signup_tokens where token_hash = %s "
                "and expires_at > now() returning email",
                (token_hash,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    _PROFILE_COLUMNS = "user_id, email, username, status, display_name, locale, nepali_enabled"

    def profile_by_username(self, username: str):
        return self._profile(f"select {self._PROFILE_COLUMNS} from public.profiles "
                             "where lower(username) = lower(%s)", (username,))

    def profile_by_email(self, email: str):
        return self._profile(f"select {self._PROFILE_COLUMNS} from public.profiles "
                             "where lower(email) = lower(%s)", (email,))

    def profile_by_user_id(self, user_id: str):
        return self._profile(f"select {self._PROFILE_COLUMNS} from public.profiles where user_id = %s",
                             (user_id,))

    def _profile(self, sql: str, params: tuple):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        if row is None:
            return None
        return ProfileRow(
            user_id=str(row[0]), email=row[1], username=row[2], status=row[3],
            display_name=row[4], locale=row[5], nepali_enabled=row[6],
        )

    def create_profile(self, profile: ProfileRow) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into public.profiles "
                "(user_id, email, username, status, display_name, locale, nepali_enabled, activated_at) "
                "values (%s, %s, %s, %s, %s, %s, %s, "
                "case when %s = 'active' then now() else null end)",
                (
                    profile.user_id, profile.email, profile.username, profile.status,
                    profile.display_name, profile.locale, profile.nepali_enabled, profile.status,
                ),
            )

    def update_profile(self, user_id: str, fields: dict[str, object]) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{name} = %s" for name in fields)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"update public.profiles set {assignments} where user_id = %s",
                (*fields.values(), user_id),
            )

    def username_taken(self, username: str) -> bool:
        return self.profile_by_username(username) is not None

    def create_session(self, session) -> None:
        self.sessions[session.session_id] = session

    def session_by_id(self, session_id: str):
        return self.sessions.get(session_id)

    def session_for_device(self, user_id: str, device_hash: str):
        for session in self.sessions.values():
            if session.user_id == user_id and session.device_hash == device_hash \
                    and session.revoked_at is None:
                return session
        return None

    def list_sessions(self, user_id: str):
        return [s for s in self.sessions.values() if s.user_id == user_id]

    def touch_session(self, session_id: str, now: float) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            session.last_seen = now

    def revoke_session(self, session_id: str, now: float) -> None:
        session = self.sessions.get(session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = now

    def revoke_all_sessions(self, user_id: str, now: float) -> int:
        count = 0
        for session in self.sessions.values():
            if session.user_id == user_id and session.revoked_at is None:
                session.revoked_at = now
                count += 1
        return count

    def purge_identity_traces(self, *, email: str, email_hash: str) -> int:
        """Remove every pre-account trace of this address (A29)."""
        removed = 0
        for key in [k for k in self.challenges if k[0] == email_hash]:
            self.challenges.pop(key, None)
            removed += 1
        for token, (stored_email, _exp) in list(self.signup_tokens.items()):
            if stored_email == email.strip().lower():
                self.signup_tokens.pop(token, None)
                removed += 1
        return removed

    def anonymize_events(self, user_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update public.security_events "
                "set user_id = null, device_id = null, ip_hash = null "
                "where user_id = %s",
                (user_id,),
            )
            return cur.rowcount

    def delete_profile(self, user_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("delete from public.profiles where user_id = %s", (user_id,))

    # ------------------------------------------------------------------ sessions

    _SESSION_COLUMNS = (
        "session_id, user_id, family_id, device_hash, device_label, "
        "created_at, last_seen, absolute_expires_at, revoked_at"
    )

    def create_session(self, session) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into public.auth_sessions "
                "(session_id, user_id, family_id, device_hash, device_label, "
                " created_at, last_seen, absolute_expires_at) "
                "values (%s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), "
                "to_timestamp(%s))",
                (
                    session.session_id, session.user_id, session.family_id,
                    session.device_hash, session.device_label,
                    session.created_at, session.last_seen, session.absolute_expires_at,
                ),
            )

    def _session_row(self, cur):
        return self._row_to_session(cur.fetchone())

    def session_by_id(self, session_id: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"select {self._SESSION_COLUMNS} from public.auth_sessions "
                "where session_id = %s", (session_id,),
            )
            return self._session_row(cur)

    def session_for_device(self, user_id: str, device_hash: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"select {self._SESSION_COLUMNS} from public.auth_sessions "
                "where user_id = %s and device_hash = %s and revoked_at is null "
                "order by created_at desc limit 1",
                (user_id, device_hash),
            )
            return self._session_row(cur)

    def list_sessions(self, user_id: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"select {self._SESSION_COLUMNS} from public.auth_sessions "
                "where user_id = %s order by created_at desc", (user_id,),
            )
            return [self._row_to_session(row) for row in cur.fetchall()]

    @staticmethod
    def _row_to_session(row):
        from app.services.sessions import Session

        if row is None:
            return None
        return Session(
            session_id=row[0], user_id=str(row[1]), family_id=row[2],
            device_hash=row[3], device_label=row[4],
            created_at=row[5].timestamp(), last_seen=row[6].timestamp(),
            absolute_expires_at=row[7].timestamp(),
            revoked_at=row[8].timestamp() if row[8] else None,
        )

    def touch_session(self, session_id: str, now: float) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update public.auth_sessions set last_seen = to_timestamp(%s) "
                "where session_id = %s", (now, session_id),
            )

    def revoke_session(self, session_id: str, now: float) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update public.auth_sessions set revoked_at = coalesce(revoked_at, to_timestamp(%s)) "
                "where session_id = %s", (now, session_id),
            )

    def revoke_all_sessions(self, user_id: str, now: float) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "update public.auth_sessions set revoked_at = to_timestamp(%s) "
                "where user_id = %s and revoked_at is null", (now, user_id),
            )
            return cur.rowcount

    def purge_identity_traces(self, *, email: str, email_hash: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("delete from public.auth_challenges where email_hash = %s", (email_hash,))
            removed = cur.rowcount
            cur.execute(
                "delete from public.auth_signup_tokens where email = %s", (email.strip().lower(),)
            )
            return removed + cur.rowcount
