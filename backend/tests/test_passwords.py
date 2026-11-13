"""Password policy and the HaveIBeenPwned range check.

The brief says: reject common/breached passwords, HIBP k-anonymity, **fail
open** if the API is down. Each of those is asserted here rather than assumed —
including that the request only ever carries the first five hex characters of
the digest, which is the whole point of the range API.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from app.services import passwords


def digest(password: str) -> str:
    return hashlib.sha1(password.encode()).hexdigest().upper()


def test_policy_is_length_only_plus_identity_collisions():
    assert passwords.policy_errors("short") == [
        "password must be at least 8 characters"
    ]
    assert passwords.policy_errors("x" * 129)[0].startswith("password must be at most")
    # Any characters allowed: no composition rules.
    assert passwords.policy_errors("12345678") == []
    assert passwords.policy_errors("密码密码密码密码") == []
    assert "choose a password that is not your username" in passwords.policy_errors(
        "Anna", username="anna"
    )
    assert "choose a password that is not your email address" in passwords.policy_errors(
        "a@b.c", email="A@B.C"
    )


def test_a_listed_password_is_breached_and_only_the_prefix_leaves(monkeypatch):
    password = "Correct-horse-9"
    prefix, suffix = digest(password)[:5], digest(password)[5:]
    seen: list[str] = []

    def fake_get(url, timeout=None):
        seen.append(url)
        return httpx.Response(200, text=f"AAAAA:3\r\n{suffix}:42\r\n")

    monkeypatch.setattr(httpx, "get", fake_get)
    assert passwords.is_breached(password) is True
    assert seen == [f"{passwords.HIBP_RANGE}{prefix}"]
    assert suffix not in seen[0]


def test_an_unlisted_password_passes(monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda url, timeout=None: httpx.Response(200, text="BBBBB:7\r\n")
    )
    assert passwords.is_breached("Correct-horse-9") is False


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503, text="maintenance"), httpx.Response(404)],
)
def test_a_broken_service_fails_open(monkeypatch, response):
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None: response)
    assert passwords.is_breached("Correct-horse-9") is False


def test_a_network_error_fails_open(monkeypatch):
    def boom(url, timeout=None):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", boom)
    assert passwords.is_breached("Correct-horse-9") is False
