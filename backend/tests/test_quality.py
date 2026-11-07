from app.services import quality
from app.utils.romanize_ne import romanize_ne


def test_validate_shape_catches_missing():
    issues = quality.validate_shape({"en": "hi", "zh": "", "ne": ""})
    assert any("zh" in i for i in issues)
    assert any("ne" in i for i in issues)


def test_validate_language_needs_devanagari():
    issues = quality.validate_language_fields({"ne": "not devanagari"})
    assert issues


def test_romanize_ne_deterministic():
    assert romanize_ne("व्यापार") == romanize_ne("व्यापार")
    assert romanize_ne("प्रकाश") == "prakāś"
