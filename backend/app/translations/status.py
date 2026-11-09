"""Single source of truth for the label shown next to a Nepali meaning.

The database stores dimensions, never labels. This function turns the stored
dimensions into exactly one display state, deterministically; the Dart twin in
``lib/core/translation_status.dart`` implements the same ladder, and both are
checked against ``shared/translation_status_golden.json``.

The ladder, first match wins — the order is part of the contract:

1. ``publication_status == 'quarantined'``            -> ``quarantined`` (hidden)
2. ``has_successor``                                  -> ``superseded`` (hidden)
3. ``human_verification == 'verified'``               -> ``verified``
4. ``validation_status == 'failed'``                  -> ``flagged``
5. ``origin_method == 'user_correction'``             -> ``user_correction``
6. imported from a source, direct **Nepali** lexical evidence, defensible
   sense match, source named, technical validation passed
                                                      -> ``source_supported``
7. ``generation_method == 'llm'`` + direct/strong + passed -> ``ai_checked``
8. ``generation_method == 'llm'``                     -> ``ai_unverified``
9. ``generation_method == 'source_import'`` + direct/strong + passed
                                                      -> ``source_sense_unconfirmed``
10. ``generation_method == 'legacy_unknown'`` or validation incomplete
                                                      -> ``unverified_legacy``
11. otherwise                                         -> ``source_sense_unconfirmed``

Rule 6 is deliberately narrow, and it requires ``generation_method ==
'source_import'``: an LLM-written value never becomes "source-supported" merely
because evidence exists for the sense — evidence makes it *checked* (rule 7), not
*source-supported*. A source URL alone is not enough either: the evidence has to
be lexical Nepali (``evidence_language == 'ne'``) and the sense correspondence
has to be defensible (``sense_match_method`` in ``DEFENSIBLE_SENSE_MATCHES``).
``headword``/``heuristic`` matching cannot qualify — that is what
"sense unconfirmed" means.

Consequences stated plainly: no valid Devanagari string ever becomes
``verified``; ``validation_status == 'passed'`` never yields more than
"checked"; a legacy ``reviewed``/``verified`` status renders as unverified; a
superseded row is hidden but keeps its attribution so history stays readable.
"""
from __future__ import annotations

QUARANTINED = "quarantined"
SUPERSEDED = "superseded"
VERIFIED = "verified"
FLAGGED = "flagged"
USER_CORRECTION = "user_correction"
SOURCE_SUPPORTED = "source_supported"
AI_CHECKED = "ai_checked"
AI_UNVERIFIED = "ai_unverified"
SOURCE_SENSE_UNCONFIRMED = "source_sense_unconfirmed"
UNVERIFIED_LEGACY = "unverified_legacy"

#: codes -> (label, visible in normal results, needs source attribution)
RULES = {
    QUARANTINED: ("Hidden from results", False, False),
    SUPERSEDED: ("Superseded", False, True),
    VERIFIED: ("Verified", True, False),
    FLAGGED: ("Flagged — failed checks", True, False),
    USER_CORRECTION: ("User correction — awaiting verification", True, False),
    SOURCE_SUPPORTED: ("Source-supported", True, True),
    AI_CHECKED: ("AI-translated, checked", True, False),
    AI_UNVERIFIED: ("AI-translated, unverified", True, False),
    SOURCE_SENSE_UNCONFIRMED: ("Source-recorded, sense unconfirmed", True, True),
    UNVERIFIED_LEGACY: ("Unverified — source unknown", True, False),
}

#: How the source record was tied to *this* sense. Only these count as
#: defensible; ``headword``/``heuristic``/``None`` do not.
DEFENSIBLE_SENSE_MATCHES = ("sense_gloss", "sense_id", "qid", "article")


def derive(record):
    """Return a dict: code, label, visible, needs_attribution, attribution.

    ``record`` may be a mapping with the dimension keys. Missing keys fall back
    to the column defaults (``not_verified``, ``incomplete``, ``labeled``), so
    an old row cannot read as verified by accident.
    """
    publication = record.get("publication_status") or "labeled"
    verification = record.get("human_verification") or "not_verified"
    validation = record.get("validation_status") or "incomplete"
    strength = record.get("evidence_strength") or "none"
    method = record.get("generation_method") or "legacy_unknown"
    origin_method = record.get("origin_method")
    source = record.get("origin_source")
    evidence_language = record.get("evidence_language")
    sense_match = record.get("sense_match_method")
    has_successor = bool(record.get("has_successor"))

    direct_and_defensible = (
        method == "source_import"
        and strength == "direct"
        and validation == "passed"
        and bool(source)
        and evidence_language == "ne"
        and sense_match in DEFENSIBLE_SENSE_MATCHES
    )

    if publication == "quarantined":
        code = QUARANTINED
    elif has_successor:
        code = SUPERSEDED
    elif verification == "verified":
        code = VERIFIED
    elif validation == "failed":
        code = FLAGGED
    elif origin_method == "user_correction":
        code = USER_CORRECTION
    elif direct_and_defensible:
        code = SOURCE_SUPPORTED
    elif method == "llm" and strength in ("direct", "strong") and validation == "passed":
        code = AI_CHECKED
    elif method == "llm":
        code = AI_UNVERIFIED
    elif method == "source_import" and strength in ("direct", "strong") and validation == "passed":
        code = SOURCE_SENSE_UNCONFIRMED
    elif method == "legacy_unknown" or validation == "incomplete":
        code = UNVERIFIED_LEGACY
    else:
        code = SOURCE_SENSE_UNCONFIRMED

    label, visible, needs_attribution = RULES[code]
    attribution = source if (needs_attribution and source) else None
    if attribution:
        label = "%s · %s" % (label, attribution)
    return {
        "code": code,
        "label": label,
        "visible": visible,
        "needs_attribution": needs_attribution,
        "attribution": attribution,
    }
