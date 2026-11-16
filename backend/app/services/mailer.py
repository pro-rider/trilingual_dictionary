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


class FileSinkMailer:
    """Local development sink: one file per code, in a directory you chose.

    This exists so the whole signup/login flow can be exercised on a real phone
    before a sender domain is verified. It is not a log: the code goes into a
    file created 0600 (owner only), one message per file, and nothing is printed.
    ``get_mailer`` refuses it whenever ``AUTH_ENV`` is ``production``.
    """

    def __init__(self, directory: str):
        from pathlib import Path

        self._dir = Path(directory).expanduser()

    def send_code(self, to: str, code: str) -> None:
        import os
        import time

        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}-{time.time_ns() % 1_000_000:06d}.txt"
        path = self._dir / name
        body = (
            f"to: {to}\n"
            f"code: {code}\n"
            f"sent: {stamp}\n"
            "note: dev sink (AUTH_MAIL_SINK_DIR). Not an email.\n"
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)


def get_mailer() -> Mailer:
    sink_dir = settings.auth_mail_sink_dir.strip()
    if sink_dir:
        if settings.auth_env.strip().lower() == "production":
            raise MailerNotConfigured(
                "AUTH_MAIL_SINK_DIR is a development sink; refused when AUTH_ENV=production"
            )
        return FileSinkMailer(sink_dir)
    return ResendMailer()
