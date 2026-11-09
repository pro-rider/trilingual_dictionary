"""Contract test: Python resolution matches the shared golden vectors.

The same committed file is read by `test/translation_resolution_test.dart`. One
contract, two implementations, no private copies.
"""
from __future__ import annotations

import json
import os

import pytest

from app.translations import resolve

GOLDEN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "shared",
    "translation_resolution_golden.json",
)


def cases():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", cases(), ids=[c["name"] for c in cases()])
def test_resolution_matches_golden(case):
    gov = case.get("governance") or {}
    got = resolve.resolve_values(
        dictionary_text=case.get("dictionary"),
        governance=gov,
        has_successor=bool(gov.get("has_successor")),
    )
    expected = case["expected"]
    assert got["text"] == expected["text"], case["name"]
    assert got["source"] == expected["source"], case["name"]
    assert got["status"] == expected["status"], case["name"]
    assert got["visible"] == expected["visible"], case["name"]
    assert got["attribution"] == expected["attribution"], case["name"]


def test_quarantine_is_not_recovered_from_the_dictionary():
    got = resolve.resolve_values(
        dictionary_text="बatti",
        governance={"text": "बatti", "publication_status": "quarantined"},
    )
    assert got["text"] == ""
    assert got["visible"] is False


def test_identical_text_is_one_meaning():
    got = resolve.resolve_values(
        dictionary_text="पानी",
        governance={"text": "पानी", "generation_method": "llm"},
    )
    assert got["source"] == "dictionary"
    assert got["text"] == "पानी"
