"""Single source of truth for the label shown next to a Nepali meaning.

The database stores dimensions, never labels. This function turns the stored
dimensions into exactly one display state, deterministically, and the Dart twin
in ``lib/core/translation_status.dart`` implements the same ladder. Both are
checked against ``shared/translation_status_golden.json``.

The ladder, in order — the first matching rule wins:

1. ``publication_status == 'quarantined'``          → ``quarantined``  (hidden)
2. ``human_verification == 'verified'``             → ``verified``
3. ``validation_status == 'failed'``                → ``flagged``
4. ``evidence_strength == 'direct'`` and validated and a source is named
                                                    → ``source_supported``
5. ``generation_method == 'llm'`` and evidence is direct/strong and validated
                                                    → ``ai_checked``
6. ``generation_method == 'llm'``                   → ``ai_unverified``
7. ``generation_method == 'source_import'`` with direct/strong evidence
   and validated                                     → ``source_sense_unconfirmed``
8. ``generation_method == 'legacy_unknown'`` or validation incomplete
                                                    → ``unverified_legacy``
9. otherwise                                        → ``source_sense_unconfirmed``

Consequences worth stating out loud: a valid Devanagari string never becomes
``verified``; ``validation_status == 'passed'`` only ever produces "checked",
never "verified"; an old ``reviewed`` status is not human verification and now
renders as unverified.
"""
from __future__ import annotations

QUARANTINED = "quarantined"
VERIFIED = "verified"
FLAGGED = "flagged"
SOURCE_SUPPORTED = "source_supported"
AI_CHECKED = "ai_checked"
AI_UNVERIFIED = "ai_unverified"
SOURCE_SENSE_UNCONFIRMED = "source_sense_unconfirmed"
UNVERIFIED_LEGACY = "unverified_legacy"

#: code -> (label, visible in normal results, needs source attribution)
RULES = {
    QUARANTINED: ("Hidden from results", False, False),
    VERIFIED: ("Verified", True, False),
    FLAGGED: ("Flagged — failed checks", True, False),
    SOURCE_SUPPORTED: ("Source-supported", True, True),
    AI_CHECKED: ("AI-translated, checked", True, False),
    AI_UNVERIFIED: ("AI-translated, unverified", True, False),
    SOURCE_SENSE_UNCONFIRMED: ("Source-recorded, sense unconfirmed", True, True),
    UNVERIFIED_LEGACY: ("Unverified — source unknown", True, False),
}


def derive(record):
    """Return (code, label, visible, needs_attribution, attribution).

    ``record`` may be a dict or any mapping with the dimension keys. Missing
    keys fall back to the column defaults (``not_verified``, ``incomplete``,
    ``labeled``), so an old row cannot accidentally read as verified.
    """
    publication = record.get("publication_status") or "labeled"
    verification = record.get("human_verification") or "not_verified"
    validation = record.get("validation_status") or "incomplete"
    strength = record.get("evidence_strength") or "none"
    method = record.get("generation_method") or "legacy_unknown"
    source = record.get("origin_source")

    if publication == "quarantined":
        code = QUARANTINED
    elif verification == "verified":
        code = VERIFIED
    elif validation == "failed":
        code = FLAGGED
    elif strength == "direct" and validation == "passed" and source:
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
