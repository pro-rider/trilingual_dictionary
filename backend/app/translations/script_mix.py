"""Script-level triage for Nepali values — a decision rule, not a mutation.

The question this answers is narrow and answerable: *is the string written in
one script per word, or were Latin/Cyrillic letters typed **inside** a Nepali
word?* It says nothing about whether the Nepali is correct — a clean string can
still be a wrong translation.

Rule (deterministic, no model, no dictionary):

1. Split on whitespace and examine the letters of each token (Unicode ranges:
   Devanagari U+0900–097F and extended, Latin basic + Latin-1/Extended,
   Cyrillic U+0400–04FF, Han U+4E00–9FFF; digits and punctuation are neutral).
2. A token carrying letters from two different scripts → ``intra_token_mix``.
   This is unambiguous typographic corruption: a Latin or Cyrillic letter inside
   a Devanagari word cannot be legitimate.
3. A token that is pure in a non-Devanagari script, while the value also
   contains Devanagari → ``foreign_token``. Legitimate cases are acronyms and
   proper nouns ("सूची अक्षर C", "Zhuge Liang को सम्मान नाम"). Keep visible.
4. No Devanagari anywhere → ``no_devanagari``: not a Nepali string at all.
5. Otherwise ``clean``.

Consequences, per the governance contract:

* ``intra_token_mix`` is the **only** verdict that justifies quarantine, and the
  original text must be preserved in the quarantine record with rule + batch id.
* ``foreign_token`` stays visible with an attribution note; no quarantine.
* ``no_devanagari`` is escalated for a human decision; no automatic quarantine.
* Anything not covered here is *not* evidence of a wrong translation.
"""
from __future__ import annotations

import unicodedata

DEVANAGARI = "devanagari"
LATIN = "latin"
CYRILLIC = "cyrillic"
HAN = "han"
OTHER = "other"
NEUTRAL = "neutral"

QUARANTINE_VERDICTS = {"intra_token_mix"}


def script_of(ch):
    cp = ord(ch)
    if 0x0900 <= cp <= 0x097F or 0xA8E0 <= cp <= 0xA8FF:
        return DEVANAGARI
    if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
        return LATIN
    if 0x0400 <= cp <= 0x04FF:
        return CYRILLIC
    if 0x4E00 <= cp <= 0x9FFF:
        return HAN
    category = unicodedata.category(ch)
    if category[0] in ("N", "P", "Z", "S", "C", "M"):
        # combining marks may belong to a script; treat as neutral here so
        # Devanagari vowel signs do not read as a separate script
        return NEUTRAL
    return OTHER


def scripts_in(token):
    found = set()
    for ch in token:
        s = script_of(ch)
        if s not in (NEUTRAL, OTHER):
            found.add(s)
    return found


def classify(text):
    value = (text or "").strip()
    tokens = [t.strip(".,;:!?()[]\"'") for t in value.split()]
    tokens = [t for t in tokens if t]
    all_scripts = set()
    intra = []
    foreign = []
    for token in tokens:
        s = scripts_in(token)
        all_scripts |= s
        if len(s) >= 2:
            intra.append(token)
        elif s and DEVANAGARI not in s:
            foreign.append(token)

    if not value:
        verdict = "empty"
    elif intra:
        verdict = "intra_token_mix"
    elif DEVANAGARI in all_scripts and foreign:
        verdict = "foreign_token"
    elif all_scripts and DEVANAGARI not in all_scripts:
        verdict = "no_devanagari"
    else:
        verdict = "clean"

    return {
        "verdict": verdict,
        "scripts": sorted(all_scripts),
        "intra_tokens": intra,
        "foreign_tokens": foreign,
        "quarantine_justified": verdict in QUARANTINE_VERDICTS,
    }
