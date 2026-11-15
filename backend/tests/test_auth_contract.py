"""The contract file and the router must agree, in both directions.

`docs/auth-contract.yaml` is the mobile client's spec. A route that exists but
is undocumented is unreviewed surface; a documented route that does not exist is
a client crash. This test reads the YAML without a YAML dependency (PyYAML is
not in requirements) by scanning for `method:` / `path:` pairs.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.api.v1 import auth as auth_module
from app.main import app

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "auth-contract.yaml"


def contract_endpoints() -> set[tuple[str, str]]:
    text = CONTRACT.read_text(encoding="utf-8")
    pairs: set[tuple[str, str]] = set()
    method = None
    for line in text.splitlines():
        stripped = line.strip()
        match_method = re.match(r"- method: ([A-Z]+)$", stripped)
        if match_method:
            method = match_method.group(1)
            continue
        match_path = re.match(r"path: (\S+?)(?:\s*#.*)?$", stripped)
        if match_path and method:
            pairs.add((method, match_path.group(1)))
            method = None
    return pairs


def router_endpoints() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for route in auth_module.router.routes:
        for method in route.methods - {"HEAD", "OPTIONS"}:
            pairs.add((method, f"/api/v1{route.path}"))
    return pairs


def test_contract_file_is_readable():
    assert CONTRACT.exists(), "docs/auth-contract.yaml is missing"
    assert contract_endpoints(), "no endpoints parsed from the contract"


def test_every_documented_endpoint_exists():
    missing = contract_endpoints() - router_endpoints()
    assert not missing, f"documented but not implemented: {sorted(missing)}"


def test_every_router_endpoint_is_documented():
    undocumented = router_endpoints() - contract_endpoints()
    assert not undocumented, f"implemented but not documented: {sorted(undocumented)}"


def test_the_app_serves_every_contract_path():
    assert contract_endpoints() <= router_endpoints()
