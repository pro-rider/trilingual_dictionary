"""Admin-side calls to Supabase Auth.

Only the FastAPI process ever holds the service-role key, and only this module
uses it. Everything a client can do (sign up, receive a code, log in, refresh,
reset a password) goes through Supabase's own endpoints from the client with the
*anon* key; nothing here re-implements password hashing or token issuance.

Why admin calls at all: deleting an account has to remove the identity, and the
only correct way to remove a Supabase identity is the Admin API. Deleting the
row directly in `auth.users` works too, but it bypasses Supabase's own cleanup
and is treated as a last resort in `docs/AUTH-SCHEMA.md`.
"""

from __future__ import annotations

import httpx

from app.core.config import settings


class SupabaseAdminError(RuntimeError):
    """Base class for admin-call failures."""


class SupabaseAdminNotConfigured(SupabaseAdminError):
    """Raised when the URL or service-role key is missing."""


class SupabaseUserNotFound(SupabaseAdminError):
    """The user is already gone. Callers treat this as success."""


class SupabaseAdmin:
    """Minimal wrapper over the two Admin endpoints this project needs."""

    def __init__(
        self,
        base_url: str | None = None,
        service_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = (base_url if base_url is not None else settings.supabase_url).rstrip("/")
        self._service_key = service_key if service_key is not None else settings.supabase_service_role_key
        self._client = client
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._service_key)

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
        }

    def _request(self, method: str, path: str) -> httpx.Response:
        if not self.configured:
            raise SupabaseAdminNotConfigured("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
        url = f"{self._base_url}/auth/v1{path}"
        if self._client is not None:
            return self._client.request(method, url, headers=self._headers())
        with httpx.Client(timeout=self._timeout) as client:
            return client.request(method, url, headers=self._headers())

    def delete_user(self, uid: str) -> None:
        """Delete an identity. Raises ``SupabaseUserNotFound`` if it is already gone.

        Deleting the identity removes the profile row (FK ``on delete cascade``)
        and invalidates every refresh token for that user, which is what makes
        "delete my account" also mean "log out everywhere".
        """
        response = self._request("DELETE", f"/admin/users/{uid}")
        if response.status_code == 404:
            raise SupabaseUserNotFound(uid)
        if response.status_code >= 400:
            # The body can contain an email address; log only the status.
            raise SupabaseAdminError(f"delete_user failed with HTTP {response.status_code}")

    def user_exists(self, uid: str) -> bool:
        response = self._request("GET", f"/admin/users/{uid}")
        return response.status_code == 200
