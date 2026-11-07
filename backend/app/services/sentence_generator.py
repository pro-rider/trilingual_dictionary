from app.ai.provider import generate_draft
from app.schemas.search import SentenceResponse
from app.services.dataset import load_entries
from app.services.fallback_templates import fallback_for
from app.services import quality


def generate_sentence(sense_id: str, word: str) -> SentenceResponse:
    """Pipeline: reviewed dataset example → AI draft → template fallback.

    Priority (v2 spec): reviewed examples first, AI only when missing, and
    offline templates as the reliable fallback.
    """
    reviewed = _reviewed_example(sense_id, word)
    if reviewed is not None:
        return SentenceResponse(
            sense_id=sense_id,
            word=word,
            en=reviewed["en"],
            zh=reviewed["zh"],
            ne=reviewed["ne"],
            source="reviewed",
            review_status="approved",
        )

    draft = generate_draft(word, _detect_lang(word))
    if draft is not None and draft["example_en"] and draft["example_zh"] and draft["example_ne"]:
        sentence = {
            "en": draft["example_en"],
            "zh": draft["example_zh"],
            "ne": draft["example_ne"],
        }
        checks = quality.check(sentence)
        status = "approved" if checks["ok"] else "unreviewed"
        return SentenceResponse(
            sense_id=sense_id,
            word=word,
            en=draft["example_en"],
            zh=draft["example_zh"],
            ne=draft["example_ne"],
            source="ai",
            review_status=status,
        )

    fb = fallback_for(word)
    return SentenceResponse(
        sense_id=sense_id,
        word=word,
        en=fb["en"],
        zh=fb["zh"],
        ne=fb["ne"],
        source="fallback",
        review_status="unreviewed",
    )


def _detect_lang(word: str) -> str:
    return "zh" if any("\u4e00" <= c <= "\u9fff" for c in word) else "en"


def _reviewed_example(sense_id: str, word: str) -> dict | None:
    for e in load_entries():
        if sense_id and any(
            s.get("sense_id") == sense_id for s in e.get("senses", [])
        ):
            for s in e.get("senses", []):
                if s.get("sense_id") == sense_id:
                    for x in s.get("examples", []):
                        if x.get("review_status") == "approved":
                            return x
        if word and e.get("word_en", "").strip().lower() == word.lower():
            for s in e.get("senses", []):
                for x in s.get("examples", []):
                    if x.get("review_status") == "approved":
                        return x
    return None
