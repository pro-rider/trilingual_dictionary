"""Client identity for rate limiting — correct behind a proxy, and only then.

Two rules, both from the review:

* `X-Forwarded-For` is attacker-controlled unless it was appended by a proxy we
  run. If we believed it unconditionally, every request could claim a fresh IP
  and per-IP lockouts would never trigger. So the header is read **only** when
  the socket peer itself is inside `TRUSTED_PROXIES`; in that case we walk the
  chain from the right and take the first hop that is not a trusted proxy (the
  standard reading), because the leftmost entries are whatever the client sent.
* The country comes from `CF-IPCountry` (or `X-Country-Code` behind our own
  ingress), never from the IP itself, and the IP is never stored — only a hash
  the callers produce. `x-vercel-ip-country` is gone: mobile has no Vercel (A27).
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from fastapi import Request

from app.core.config import settings

_COUNTRY_HEADERS = ("cf-ipcountry", "x-country-code")


@lru_cache(maxsize=4)
def _parse_networks(raw: str) -> tuple:
    networks = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            networks.append(ipaddress.ip_network(piece, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def trusted_networks() -> tuple:
    return _parse_networks(settings.trusted_proxies or "")


def _is_trusted(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in trusted_networks())


def peer_ip(request: Request) -> str:
    """The socket peer, regardless of headers. Empty when unavailable."""
    client = request.client
    return client.host if client and client.host else ""


def client_ip(request: Request) -> str:
    """The address rate limiting should count against.

    Falls back to the socket peer on every path where the header cannot be
    trusted — including a malformed or missing chain.
    """
    peer = peer_ip(request)
    if not peer or not _is_trusted(peer):
        return peer

    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    valid: list[str] = []
    for hop in chain:
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            continue          # ignore garbage instead of trusting it
        valid.append(hop)

    for hop in reversed(valid):
        if not _is_trusted(hop):
            return hop
    # Every hop was one of ours (single-proxy deployments), so the leftmost
    # entry is the client as our edge saw it. No usable entry means the peer.
    return valid[0] if valid else peer


def country_code(request: Request) -> str | None:
    """Two-letter country, or None. Never derived from the IP by us."""
    if not _is_trusted(peer_ip(request)):
        return None
    for header in _COUNTRY_HEADERS:
        value = (request.headers.get(header) or "").strip().upper()
        if len(value) == 2 and value.isalpha():
            return value
    return None
