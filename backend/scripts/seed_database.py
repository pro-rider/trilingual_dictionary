"""Seed PostgreSQL from the canonical JSON (used when Postgres is wired).

Run: python -m scripts.seed_database
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models.word import ExampleSentence, Sense, Word  # noqa: E402
from app.services.dataset import load_entries  # noqa: E402


def seed() -> int:
    entries = load_entries()
    db = SessionLocal()
    count = 0
    try:
        for raw in entries:
            word = Word(
                entry_id=raw["entry_id"],
                word_en=raw["word_en"],
                word_zh=raw["word_zh"],
            )
            for s in raw.get("senses", []):
                sense = Sense(
                    sense_key=s.get("sense_id", ""),
                    part_of_speech=s.get("part_of_speech", ""),
                    pinyin=s.get("pinyin", ""),
                    ipa_en=s.get("ipa_en", ""),
                    meaning_en=s.get("meaning_en", ""),
                    meaning_zh=s.get("meaning_zh", ""),
                    meaning_ne=s.get("meaning_ne", ""),
                    meaning_ne_status=s.get("meaning_ne_status", "published"),
                    meaning_ne_source=s.get("meaning_ne_source", "dictionary"),
                )
                for x in s.get("examples", []):
                    sense.examples.append(
                        ExampleSentence(
                            en=x.get("en", ""),
                            zh=x.get("zh", ""),
                            ne=x.get("ne", ""),
                            source=x.get("source", "reviewed"),
                            review_status=x.get("review_status", "approved"),
                        )
                    )
                word.senses.append(sense)
            db.add(word)
            count += 1
        db.commit()
    finally:
        db.close()
    return count


if __name__ == "__main__":
    print(f"Seeded {seed()} words.")
