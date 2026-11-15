"""Trusted-proxy handling.

The point of these tests is the *negative* one: a request from an untrusted peer
that carries `X-Forwarded-For: 1.2.3.4, 5.6.7.8` must be counted against the peer
address, not against a number the attacker typed. Without that, per-IP lockouts
and per-IP quotas are decorative.

`settings.trusted_proxies` is read through a cached parser, so each test patches
the cache rather than the settings object.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core import net
from app.core.config import settings


def make_request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/login",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_cache():
    net._parse_networks.cache_clear()
    yield
    net._parse_networks.cache_clear()


def trust(*cidrs: str, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ",".join(cidrs))
    net._parse_networks.cache_clear()


def test_spoofed_forwarded_for_is_ignored_from_an_untrusted_peer(monkeypatch):
    trust("10.0.0.0/8", monkeypatch=monkeypatch)
    request = make_request("203.0.113.50", {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    assert net.client_ip(request) == "203.0.113.50"


def test_forwarded_for_is_honoured_from_a_trusted_proxy(monkeypatch):
    trust("10.0.0.0/8", monkeypatch=monkeypatch)
    request = make_request("10.0.0.5", {"X-Forwarded-For": "198.51.100.7"})
    assert net.client_ip(request) == "198.51.100.7"


def test_the_rightmost_untrusted_hop_wins_in_a_chain(monkeypatch):
    """Left entries are whatever the client sent; ours are on the right."""
    trust("10.0.0.0/8", monkeypatch=monkeypatch)
    request = make_request(
        "10.0.0.5", {"X-Forwarded-For": "203.0.113.9, 10.0.0.6"}
    )
    assert net.client_ip(request) == "203.0.113.9"

    # An attacker prepending a fake hop must not change the answer.
    request = make_request(
        "10.0.0.5", {"X-Forwarded-For": "1.2.3.4, 203.0.113.9, 10.0.0.6"}
    )
    assert net.client_ip(request) == "203.0.113.9"


def test_garbage_in_the_header_falls_back_to_the_peer(monkeypatch):
    trust("10.0.0.0/8", monkeypatch=monkeypatch)
    request = make_request("10.0.0.5", {"X-Forwarded-For": "not-an-ip"})
    assert net.client_ip(request) == "10.0.0.5"
    assert net.client_ip(make_request("10.0.0.5")) == "10.0.0.5"


def test_no_trusted_proxies_configured_means_no_header_trust():
    request = make_request("10.0.0.5", {"X-Forwarded-For": "198.51.100.7"})
    assert net.client_ip(request) == "10.0.0.5"


def test_country_is_only_read_from_a_trusted_peer(monkeypatch):
    trust("10.0.0.0/8", monkeypatch=monkeypatch)
    spoofed = make_request("203.0.113.50", {"CF-IPCountry": "US"})
    assert net.country_code(spoofed) is None

    trusted = make_request("10.0.0.5", {"CF-IPCountry": "np"})
    assert net.country_code(trusted) == "NP"

    junk = make_request("10.0.0.5", {"CF-IPCountry": "United States"})
    assert net.country_code(junk) is None

    assert net.country_code(make_request("10.0.0.5")) is None
