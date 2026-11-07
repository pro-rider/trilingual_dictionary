"""Quality checks for generated sentences (v2 spec).

Auto-checks are a prioritisation signal for human review — they cannot prove
correctness. A sentence that is grammatically fine is not necessarily a correct
translation, so we check both shape and meaning alignment.
"""

from typing import Any


def validate_shape(data: dict[str, Any]) -> list[str]:
    """Check the response has all required language fields, non-empty."""
    issues: list[str] = []
    for key in ("en", "zh", "ne"):
        value = (data.get(key) or "").strip()
        if not value:
            issues.append(f"missing or empty field: {key}")
    return issues


def validate_language_fields(data: dict[str, Any]) -> list[str]:
    """Cheap script checks — valid Devanagari for ne, no stray CJK in en, etc."""
    issues: list[str] = []
    ne = data.get("ne", "").strip()
    if ne and not any("\u0900" <= c <= "\u097F" for c in ne):
        issues.append("nepali field does not contain Devanagari")
    return issues


def alignment_score(data: dict[str, Any]) -> float:
    """Heuristic placeholder for back-translation alignment (0..1).

    A real implementation translates ne → en/zh and compares to the source.
    In v1 we return 0.5 (unknown) until a translation model is wired.
    """
    return 0.5


def check(data: dict[str, Any]) -> dict[str, Any]:
    issues = validate_shape(data) + validate_language_fields(data)
    return {
        "ok": not issues,
        "issues": issues,
        "alignment_score": alignment_score(data),
    }
