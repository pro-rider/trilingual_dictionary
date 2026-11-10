"""One canonical gloss normalizer for retrieval scoring.

Why this module exists
----------------------
Scoring used to read ``gloss.split("(")[0]`` — "everything before the first
bracket". That silently assumed a bracket can only appear *after* a definition,
as in ``"front (of a building)"``. CC-CEDICT does the opposite for 25% of its
senses: the bracket comes **first** and names a domain or register:

    "(computing) database"      → split("(")[0] == ""   → score 0, can never win
    "(lit. and fig.) to pollute; to contaminate"
    "(bird species of China) Nepal fulvetta"

Measured on the shipped dictionary: **17,908 senses (9.03%)** open with a
bracket, and 49,711 (25.1%) contain one anywhere. Every one of those was
unreachable through an English query. For **1,481** query words the bracketed
sense is the *only* correct answer, so the failure was not "wrong ranking", it
was "no result at all" — measured 1.0% accuracy on that stratum.

The fix is to *strip* parenthetical tags wherever they occur and keep the
definition text, instead of truncating at the first bracket. The tag itself is
still available to a caller that wants it (``extract_tags``), it simply no
longer decides whether a word is findable.

``lib/data/local/offline_dictionary.dart`` implements the same rules in
``normalizeGloss``; a parity test pins both against the same fixtures, because
these two copies drifting apart is what produced the bug in the first place.
"""

from __future__ import annotations

import re

# (...) full-width （...) and square [...] groups, innermost-first for the
# nested case. Unknown punctuation is left alone rather than guessed at.
_PARENS = re.compile(r"\([^()]*\)")
_WIDE_PARENS = re.compile(r"（[^（）]*）")
_BRACKETS = re.compile(r"\[[^\[\]]*\]")
_SPACES = re.compile(r"\s+")

# A definition part is split on these; the first piece is the head definition.
_SEGMENT_SPLIT = re.compile(r"[;,/、]")


def strip_tags(text: str) -> str:
    """Remove every parenthetical / bracketed tag, keeping the definition."""
    if not text:
        return ""
    out = text
    # Two passes so a nested "((a) b)" also collapses fully.
    for _ in range(2):
        out = _PARENS.sub(" ", out)
        out = _WIDE_PARENS.sub(" ", out)
        out = _BRACKETS.sub(" ", out)
    return _SPACES.sub(" ", out).strip()


def normalize_gloss(gloss: str) -> str:
    """Lower-cased, tag-free definition text — the string scoring looks at."""
    return strip_tags(gloss).lower()


def segments(gloss: str) -> list[str]:
    """Definition segments of a gloss, tags removed and empties dropped."""
    return [s.strip() for s in _SEGMENT_SPLIT.split(normalize_gloss(gloss)) if s.strip()]


def extract_tags(gloss: str) -> list[str]:
    """The tags that were stripped, for provenance / display. Never used to score."""
    return [m.strip() for m in re.findall(r"\(([^()]*)\)", gloss or "") if m.strip()]


# A leading tag that says *this head cannot stand alone* is not a domain label,
# so the definition after it describes a morpheme, not a word an English query
# can mean. 中 = "(bound form) China; Chinese" must never answer "China" — that
# is 中国. Two tags only, both semantic, both from the dictionary's own
# vocabulary; every other leading tag (computing, literary, fig., slang, …) is
# stripped and the definition stays reachable.
_HEAD_DISQUALIFIERS = ("bound form", "abbr")


def head_is_disqualified(gloss: str) -> bool:
    """True when the gloss opens with a tag that rules the head out as an answer."""
    m = re.match(r"\s*\(([^()]*)\)", gloss or "")
    if not m:
        return False
    tag = m.group(1).strip().lower()
    return tag.startswith(_HEAD_DISQUALIFIERS)
