"""Contract test: Python derivation matches shared golden vectors."""
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


def test_golden_file_exists():
    assert os.path.exists(GOLDEN), "golden vectors must live in shared/"


@pytest.mark.parametrize("case", load_golden(), ids=[c["name"] for c in load_golden()])
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


def test_every_code_has_a_rule():
    for code in (status.QUARANTINED, status.VERIFIED, status.FLAGGED,
                 status.SOURCE_SUPPORTED, status.AI_CHECKED, status.AI_UNVERIFIED,
                 status.SOURCE_SENSE_UNCONFIRMED, status.UNVERIFIED_LEGACY):
        assert code in status.RULES
