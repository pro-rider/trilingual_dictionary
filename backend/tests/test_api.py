from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_search_english():
    r = client.post("/api/v1/search", json={"q": "light", "lang": "en"})
    assert r.status_code == 200
    data = r.json()["entry"]
    assert data is not None
    assert data["word_en"] == "light"
    assert len(data["senses"]) == 2  # multi-sense word


def test_search_chinese_returns_same_entry():
    r = client.post("/api/v1/search", json={"q": "光", "lang": "zh"})
    assert r.status_code == 200
    data = r.json()["entry"]
    assert data is not None
    assert data["entry_id"] == "light"


def test_search_has_three_meaning_languages():
    r = client.post("/api/v1/search", json={"q": "mountain", "lang": "en"})
    sense = r.json()["entry"]["senses"][0]
    assert sense["meaning_en"] and sense["meaning_zh"] and sense["meaning_ne"]


def test_search_missing_returns_null():
    r = client.post("/api/v1/search", json={"q": "zzznotaword", "lang": "en"})
    assert r.status_code == 200
    assert r.json()["entry"] is None


def test_sentence_from_reviewed_example():
    r = client.post(
        "/api/v1/search/sentence", json={"sense_id": "light_noun_illumination", "word": "light"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "reviewed"
    assert data["review_status"] == "approved"
    assert data["en"] and data["zh"] and data["ne"]


def test_sentence_fallback_for_unknown_word():
    r = client.post(
        "/api/v1/search/sentence", json={"sense_id": "", "word": "zzznotaword"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "fallback"
    assert data["en"] and data["zh"] and data["ne"]


def test_popular():
    r = client.get("/api/v1/popular")
    assert r.status_code == 200
    assert len(r.json()["words"]) > 0


def test_suggest():
    r = client.get("/api/v1/suggest", params={"q": "lig", "lang": "en"})
    assert r.status_code == 200
    assert any("light" in s for s in r.json()["suggestions"])
