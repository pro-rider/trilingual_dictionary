"""Contract test: Python derivation matches the shared golden vectors.

The same committed file is read by `test/translation_status_test.dart`; neither
side may keep a private copy of the expectations.
"""
from __future__ import annotations

import json
import os

import pytest

from app.translations import status

GOLDEN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "shared",
    "translation_status_golden.json",
)


def load_golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


def cases():
    return load_golden()["cases"]


def test_golden_file_is_a_versioned_object():
    data = load_golden()
    assert os.path.exists(GOLDEN), "golden vectors must live in shared/"
    assert isinstance(data, dict), "golden file must be an object, not a bare array"
    assert data.get("version") == 1
    assert isinstance(data.get("cases"), list) and len(data["cases"]) >= 20
    for case in data["cases"]:
        assert set(case) == {"name", "input", "expected"}, case.get("name")
        assert set(case["expected"]) == {"code", "label", "visible", "needs_attribution",
                                         "attribution"}, case["name"]


def test_golden_names_are_unique():
    names = [c["name"] for c in cases()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("case", cases(), ids=[c["name"] for c in cases()])
def test_derivation_matches_golden(case):
    got = status.derive(case["input"])
    expected = case["expected"]
    assert got["code"] == expected["code"]
    assert got["label"] == expected["label"]
    assert got["visible"] == expected["visible"]
    assert got["needs_attribution"] == expected["needs_attribution"]
    assert got["attribution"] == expected["attribution"]


def test_legacy_status_name_never_produces_verified():
    for legacy in ("verified", "reviewed"):
        got = status.derive({"legacy_status": legacy})
        assert got["code"] == "unverified_legacy", legacy
        assert "Verified" not in got["label"]


def test_empty_record_is_unverified_and_visible():
    got = status.derive({})
    assert got["code"] == "unverified_legacy"
    assert got["visible"] is True


def test_every_rule_has_a_code_and_every_code_has_a_rule():
    for code in (status.QUARANTINED, status.SUPERSEDED, status.VERIFIED, status.FLAGGED,
                 status.SOURCE_SUPPORTED, status.AI_CHECKED, status.AI_UNVERIFIED,
                 status.SOURCE_SENSE_UNCONFIRMED, status.UNVERIFIED_LEGACY,
                 status.USER_CORRECTION):
        assert code in status.RULES


def test_every_golden_code_is_reachable():
    produced = {c["expected"]["code"] for c in cases()}
    for code in (status.QUARANTINED, status.SUPERSEDED, status.VERIFIED, status.FLAGGED,
                 status.SOURCE_SUPPORTED, status.AI_CHECKED, status.AI_UNVERIFIED,
                 status.SOURCE_SENSE_UNCONFIRMED, status.UNVERIFIED_LEGACY,
                 status.USER_CORRECTION):
        assert code in produced, "%s has no golden case" % code
