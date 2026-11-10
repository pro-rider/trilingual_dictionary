"""P0.5 tests — runtime guards on the AI endpoints.

Each test pins one promise from the P0.5 task:
  * oversize input is rejected with 422, control characters are stripped;
  * the shared secret is enforced when configured, and absent (current behaviour)
    when not;
  * the limiter returns 429 and does not leak the client's text;
  * the kill switch takes effect without restarting the process.

No test may call a real provider: AI is disabled by default and every case that
would reach a provider runs with the kill switch off or a mocked batch function.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.core import ai_guard
from app.main import app


@pytest.fixture()
def client():
    ai_guard.limiter.reset()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AI_SHARED_SECRET", raising=False)
    monkeypatch.delenv("AI_RATE_LIMIT_PER_MIN", raising=False)
    monkeypatch.delenv("AI_DAILY_CAP", raising=False)
    monkeypatch.delenv("AI_RUNTIME_ENABLED", raising=False)
    monkeypatch.delenv("AI_ENABLED_FILE", raising=False)
    yield
    ai_guard.limiter.reset()


# --- 1. request size -------------------------------------------------------------


def test_enrich_rejects_oversize_key(client):
    r = client.post("/api/v1/dictionary/enrich", json={"items": [{"key": "a" * 65}]})
    assert r.status_code == 422


def test_enrich_rejects_oversize_gloss(client):
    r = client.post(
        "/api/v1/dictionary/enrich",
        json={"items": [{"key": "数据库", "zh": "数" * 201}]},
    )
    assert r.status_code == 422


def test_analyze_rejects_oversize_text(client):
    r = client.post("/api/v1/analyze/text", json={"text": "a" * 4001})
    assert r.status_code == 422


def test_enrich_strips_control_characters():
    from app.schemas.dictionary import EnrichItem

    item = EnrichItem(key="data\x00base\x01", zh="数\x1f据库", en="da\ttabase")
    assert "\x00" not in item.key and "\x01" not in item.key
    assert item.key == "database"
    assert item.zh == "数据库"
    assert item.en == "database"


# --- 2. shared secret ------------------------------------------------------------


def test_no_secret_configured_keeps_current_behaviour(client):
    # No AI_SHARED_SECRET → the route must behave exactly as before P0.5.
    r = client.post("/api/v1/analyze/text", json={"text": "company", "lang": "en"})
    assert r.status_code == 200


def test_missing_secret_header_is_rejected(client, monkeypatch):
    monkeypatch.setenv("AI_SHARED_SECRET", "s3cret")
    r = client.post("/api/v1/analyze/text", json={"text": "company", "lang": "en"})
    assert r.status_code == 401


def test_wrong_secret_header_is_rejected(client, monkeypatch):
    monkeypatch.setenv("AI_SHARED_SECRET", "s3cret")
    r = client.post(
        "/api/v1/search",
        json={"q": "company", "lang": "en"},
        headers={"X-AI-Token": "nope"},
    )
    assert r.status_code == 401


def test_correct_secret_header_passes(client, monkeypatch):
    monkeypatch.setenv("AI_SHARED_SECRET", "s3cret")
    r = client.post(
        "/api/v1/search",
        json={"q": "company", "lang": "en"},
        headers={"X-AI-Token": "s3cret"},
    )
    assert r.status_code == 200


# --- 3. limits -------------------------------------------------------------------


def test_rate_limit_returns_429_and_logs_no_user_text(client, monkeypatch, caplog):
    monkeypatch.setenv("AI_RATE_LIMIT_PER_MIN", "2")
    body = {"q": "confidentialphrase", "lang": "en"}
    for _ in range(2):
        assert client.post("/api/v1/search", json=body).status_code == 200

    with caplog.at_level(logging.INFO):
        r = client.post("/api/v1/search", json=body)

    assert r.status_code == 429
    assert "try again later" in r.json()["detail"].lower()
    assert "confidentialphrase" not in caplog.text


def test_daily_cap_returns_429(client, monkeypatch):
    monkeypatch.setenv("AI_DAILY_CAP", "2")
    for _ in range(2):
        assert client.post("/api/v1/search", json={"q": "water", "lang": "en"}).status_code == 200
    assert client.post("/api/v1/search", json={"q": "water", "lang": "en"}).status_code == 429


# --- 4. kill switch without restart ----------------------------------------------


def test_kill_switch_off_blocks_provider_calls(client, monkeypatch):
    """Disabled → the endpoint still answers 200, but nothing reaches a provider."""
    monkeypatch.setenv("AI_RUNTIME_ENABLED", "0")
    monkeypatch.setattr("app.core.config.settings.ai_enabled", True)

    def _boom(*args, **kwargs):
        raise AssertionError("a provider was called while the kill switch was off")

    monkeypatch.setattr("app.ai.provider._service.complete", _boom)

    r = client.post(
        "/api/v1/dictionary/enrich",
        json={"items": [{"key": "k", "zh": "词", "en": "word"}]},
    )
    assert r.status_code == 200
    assert all(item["ne"] == "" for item in r.json()["items"])


def test_kill_switch_on_allows_the_call(client, monkeypatch):
    """Enabled + a fake provider answer → the batch function is reached once."""
    monkeypatch.setenv("AI_RUNTIME_ENABLED", "1")

    called = {"n": 0}

    def _fake(items):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.api.v1.dictionary.enrich_senses_batch", _fake)

    r = client.post(
        "/api/v1/dictionary/enrich",
        json={"items": [{"key": "k", "zh": "词", "en": "word"}]},
    )
    assert r.status_code == 200
    assert called["n"] == 1


def test_prompt_gate_reports_disabled(monkeypatch):
    """ai_enabled() is the single gate the provider functions consult."""
    from app.ai import provider

    monkeypatch.setattr("app.core.config.settings.ai_enabled", True)
    monkeypatch.setattr(provider._service, "active_providers", lambda: ["fake"])

    monkeypatch.setenv("AI_RUNTIME_ENABLED", "1")
    assert provider.ai_enabled() is True

    monkeypatch.setenv("AI_RUNTIME_ENABLED", "0")
    assert provider.ai_enabled() is False


def test_flag_file_toggles_without_relaunch(client, monkeypatch, tmp_path):
    flag = tmp_path / ".ai_enabled"
    monkeypatch.setenv("AI_ENABLED_FILE", str(flag))
    monkeypatch.delenv("AI_RUNTIME_ENABLED", raising=False)

    monkeypatch.setattr("app.core.config.settings.ai_enabled", False)
    assert ai_guard.ai_runtime_enabled() is False

    flag.write_text("1", encoding="utf-8")           # operator creates the file
    assert ai_guard.ai_runtime_enabled() is True

    flag.unlink()                                     # operator deletes it
    assert ai_guard.ai_runtime_enabled() is False


# --- 5. startup exposure warning -------------------------------------------------


def test_exposure_warning_fires_for_public_host(monkeypatch, caplog):
    import app.main as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["uvicorn", "--host", "0.0.0.0"])
    monkeypatch.delenv("AI_SHARED_SECRET", raising=False)
    monkeypatch.setattr("app.core.config.settings.ai_shared_secret", "")

    with caplog.at_level(logging.WARNING, logger="app.main"):
        main_mod.warn_if_exposed()

    assert "reachable beyond loopback" in caplog.text


def test_exposure_warning_quiet_on_loopback(monkeypatch, caplog):
    import app.main as main_mod

    monkeypatch.setattr(main_mod.sys, "argv", ["uvicorn", "--host", "127.0.0.1"])
    monkeypatch.delenv("AI_SHARED_SECRET", raising=False)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        main_mod.warn_if_exposed()

    assert "reachable beyond loopback" not in caplog.text
