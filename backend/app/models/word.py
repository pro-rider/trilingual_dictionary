from typing import List

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Word(Base):
    """One canonical entry per word (v2 spec)."""

    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    word_en: Mapped[str] = mapped_column(String(120), index=True)
    word_zh: Mapped[str] = mapped_column(String(120), index=True)
    dataset_version: Mapped[int] = mapped_column(default=1)

    senses: Mapped[List["Sense"]] = relationship(
        back_populates="word", cascade="all, delete-orphan"
    )


class Sense(Base):
    """One meaning; carries pronunciation + 3 translations per-sense."""

    __tablename__ = "senses"

    id: Mapped[int] = mapped_column(primary_key=True)
    word_id: Mapped[int] = mapped_column(index=True)
    sense_key: Mapped[str] = mapped_column(String(120), index=True)
    part_of_speech: Mapped[str] = mapped_column(String(40), default="")

    pinyin: Mapped[str] = mapped_column(String(120), default="")
    ipa_en: Mapped[str] = mapped_column(String(80), default="")

    meaning_en: Mapped[str] = mapped_column(Text)
    meaning_zh: Mapped[str] = mapped_column(Text)
    meaning_ne: Mapped[str] = mapped_column(Text)

    # Nepali review state machine (v2 spec)
    meaning_ne_status: Mapped[str] = mapped_column(
        String(30), default="ai_draft"
    )
    meaning_ne_source: Mapped[str] = mapped_column(String(60), default="")
    reviewed_by: Mapped[str] = mapped_column(String(120), default="")
    alignment_score: Mapped[float] = mapped_column(default=0.5)

    word: Mapped["Word"] = relationship(back_populates="senses")
    examples: Mapped[List["ExampleSentence"]] = relationship(
        back_populates="sense", cascade="all, delete-orphan"
    )


class ExampleSentence(Base):
    """One linked en/zh/ne example set per sense."""

    __tablename__ = "example_sentences"

    id: Mapped[int] = mapped_column(primary_key=True)
    sense_id: Mapped[int] = mapped_column(index=True)

    en: Mapped[str] = mapped_column(Text)
    zh: Mapped[str] = mapped_column(Text)
    ne: Mapped[str] = mapped_column(Text)

    ne_status: Mapped[str] = mapped_column(String(30), default="ai_draft")
    source: Mapped[str] = mapped_column(String(40), default="")
    review_status: Mapped[str] = mapped_column(String(30), default="unreviewed")
    reviewed_by: Mapped[str] = mapped_column(String(120), default="")
    alignment_score: Mapped[float] = mapped_column(default=0.5)

    sense: Mapped["Sense"] = relationship(back_populates="examples")
