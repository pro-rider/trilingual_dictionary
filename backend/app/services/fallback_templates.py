"""Offline-safe template example sentences used as a fallback.

Real, reviewed sentences come from the dataset. Templates only appear when a
word has no reviewed example yet and AI generation is unavailable/offline.
"""


def fallback_for(word: str) -> dict[str, str]:
    return {
        "en": f"I learned the word “{word}” today.",
        "zh": f"我今天学了“{word}”这个词。",
        "ne": f"मैले आज “{word}” शब्द सिकेँ।",
    }
