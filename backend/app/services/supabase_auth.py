"""The only places FastAPI talks to Supabase Auth.

The Flutter app talks to FastAPI and nothing else: no Supabase URL, no anon key,
no direct `/auth/v1` calls (A24). That removes the bypass the user called out —
with the anon key in an APK, anyone can hit `signInWithPassword` directly and
skip our lockouts, blocklist, Turnstile and security events entirely.

Signing in with a password still happens *at* Supabase (password hashing and
session issuance stay there, per the brief); it is just proxied by FastAPI.
"""

from __future__ import annotations

import httpx

from app.core.config import settings


class AuthClientError(RuntimeError):
    """Any non-2xx answer from the token or admin endpoint."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"supabase auth returned HTTP {status}")


class SupabaseAuthClient:
    def __init__(self, base_url: str | None = None, key: str | None = None,
                 client: httpx.Client | None = None, timeout: float = 10.0) -> None:
        self._base_url = (base_url if base_url is not None else settings.supabase_url).rstrip("/")
        # The service-role key stays server-side; it is also accepted by the
        # token endpoint, which keeps one key out of the deployment.
        self._key = key if key is not None else (
            settings.supabase_service_role_key or settings.supabase_anon_key
        )
        self._client = client
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._key)

    def _post(self, path: str, payload: dict) -> dict:
        if not self.configured:
            raise AuthClientError(503)
        headers = {"apikey": self._key, "Authorization": f"Bearer {self._key}"}
        url = f"{self._base_url}/auth/v1{path}"
        if self._client is not None:
            response = self._client.post(url, json=payload, headers=headers)
        else:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise AuthClientError(response.status_code)
        return response.json()

    def sign_in_with_password(self, email: str, password: str) -> dict:
        """Returns the Supabase session: access token, refresh token, user."""
        return self._post("/token?grant_type=password", {"email": email, "password": password})

    def refresh(self, refresh_token: str) -> dict:
        return self._post("/token?grant_type=refresh_token", {"refresh_token": refresh_token})

    def sign_out(self, access_token: str) -> None:
        if not self.configured:
            raise AuthClientError(503)
        headers = {"apikey": self._key, "Authorization": f"Bearer {access_token}"}
        url = f"{self._base_url}/auth/v1/logout"
        if self._client is not None:
            self._client.post(url, headers=headers)
            return
        with httpx.Client(timeout=self._timeout) as client:
            client.post(url, headers=headers)

    def set_password(self, uid: str, password: str) -> None:
        """Admin-side password change, used only after a reset code verified."""
        if not self.configured:
            raise AuthClientError(503)
        headers = {"apikey": self._key, "Authorization": f"Bearer {self._key}"}
        url = f"{self._base_url}/auth/v1/admin/users/{uid}"
        if self._client is not None:
            response = self._client.put(url, json={"password": password}, headers=headers)
        else:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.put(url, json={"password": password}, headers=headers)
        if response.status_code >= 400:
            raise AuthClientError(response.status_code)


class SupabaseAdminWrapper:
    """`create_user` on top of the admin client used by account deletion."""

    def __init__(self, admin) -> None:
        self._admin = admin

    def create_user(self, *, email: str, password: str) -> dict:
        return self._admin.create_user(email=email, password=password)
