"""Mail delivery for auth codes.

Resend is the sender in production. Tests never touch the network: they install
``RecordingMailer``, which is a *sink*, not a log — a code must never be written
to stdout, a logger or the database in clear.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from app.core.config import settings

RESEND_ENDPOINT = "https://api.resend.com/emails"


class MailerNotConfigured(RuntimeError):
    pass


class Mailer(Protocol):
    def send_code(self, to: str, code: str) -> None: ...


class ResendMailer:
    def __init__(self, api_key: str | None = None, sender: str | None = None, timeout: float = 10.0):
        self._api_key = api_key if api_key is not None else settings.resend_api_key
        self._sender = sender if sender is not None else settings.auth_mail_from
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._sender)

    def send_code(self, to: str, code: str) -> None:
        if not self.configured:
            raise MailerNotConfigured("RESEND_API_KEY / AUTH_MAIL_FROM not set")
        payload = {
            "from": self._sender,
            "to": [to],
            "subject": "Your sign-in code",
            # One template for signup and reset: the wording must not reveal
            # whether the address already has an account.
            "text": f"Your code is {code}. It expires in 10 minutes. "
                    "If you did not ask for it, ignore this email.",
        }
        response = httpx.post(
            RESEND_ENDPOINT,
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            raise MailerNotConfigured(f"resend rejected the message with HTTP {response.status_code}")


class RecordingMailer:
    """Test sink. Holds the codes in memory so a test can act like the recipient."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_code(self, to: str, code: str) -> None:
        self.sent.append((to, code))

    def last_code_for(self, address: str) -> str | None:
        for to, code in reversed(self.sent):
            if to == address:
                return code
        return None


def get_mailer() -> Mailer:
    return ResendMailer()
