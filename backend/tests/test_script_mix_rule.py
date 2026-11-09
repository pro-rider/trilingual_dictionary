"""Decision rule for Latin/Cyrillic contamination in Nepali values.

Pins the verdicts for the values already audited, so "quarantine or keep" stops
being a judgement call each time the question comes up.
"""
from __future__ import annotations

import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import pytest  # noqa: E402

from app.translations import script_mix  # noqa: E402

# The audited values, with the verdict the rule must produce.
CASES = [
    ("बatti", "intra_token_mix", True),            # 灯 — Latin inside the word
    ("शuai उपनाम", "intra_token_mix", True),        # 帅 — Latin inside "शuai"
    ("पурсnu", "intra_token_mix", True),           # 追求 — Cyrillic inside
    ("केही आश्यर्य नै हoinu", "intra_token_mix", True),  # 怪不得
    ("सूची अक्षर C", "foreign_token", False),       # 丙 — "C" is a separate token
    ("Zhuge Liang को सम्मान नाम", "foreign_token", False),  # 孔明 — proper noun
]


@pytest.mark.parametrize("text,verdict,quarantine", CASES)
def test_audited_values_get_the_documented_verdict(text, verdict, quarantine):
    got = script_mix.classify(text)
    assert got["verdict"] == verdict
    assert got["quarantine_justified"] is quarantine


def test_a_clean_nepali_word_is_clean():
    assert script_mix.classify("पानी")["verdict"] == "clean"
    assert script_mix.classify("पानी")["quarantine_justified"] is False


def test_a_value_with_no_devanagari_is_escalated_not_quarantined():
    got = script_mix.classify("water")
    assert got["verdict"] == "no_devanagari"
    assert got["quarantine_justified"] is False


def test_digits_inside_a_word_do_not_count_as_script_mixing():
    assert script_mix.classify("२०७९ साल")["verdict"] == "clean"


def test_the_report_is_read_only_and_categorised():
    """The tool classifies; it must not open a writable handle."""
    from tools.classify_script_mix import scan

    report = scan(None, values=["बatti", "सूची अक्षर C", "पानी"])
    assert report["scanned"] == 3
    assert report["by_verdict"] == {"intra_token_mix": 1, "foreign_token": 1, "clean": 1}
    assert len(report["quarantine_candidates"]) == 1
    assert len(report["kept_visible"]) == 1
    assert "nothing was quarantined" in report["note"]
