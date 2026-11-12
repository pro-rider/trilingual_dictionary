"""Tests for the operational logging / alerting hooks (Phase 10).

The point of these tests is the privacy invariant: these records are written to
stdout of a shared server, so they must never be able to carry user text. A
regression here is a privacy incident, not a formatting nit.
"""

from __future__ import annotations

from app.core import obs


def setup_function() -> None:
    obs.reset_for_tests()
    obs.set_alert_hook(None)


def test_unknown_fields_are_dropped_not_logged(capsys):
    record = obs.log_event("http_request", route="/api/v1/search", status=200,
                           duration_ms=12, text="秘密の文章", query="hello",
                           body="user sentence")
    assert set(record) == {"ts", "event", "route", "status", "duration_ms"}
    out = capsys.readouterr().out
    assert "秘密の文章" not in out
    assert "hello" not in out
    assert "user sentence" not in out


def test_long_values_are_clipped():
    record = obs.log_event("ai_attempt", endpoint="x" * 500, status="ok")
    assert len(record["endpoint"]) == 64


def test_failure_rate_and_snapshot():
    for _ in range(8):
        obs.note_ai_attempt(True)
    for _ in range(2):
        obs.note_ai_attempt(False, kind="rate_limit")
    snap = obs.snapshot()
    assert snap["attempts"] == 10
    assert snap["ok"] == 8 and snap["failed"] == 2
    assert abs(obs.ai_failure_rate() - 0.2) < 1e-9


def test_alert_fires_only_past_threshold_and_minimum():
    alerts: list[dict] = []
    obs.set_alert_hook(alerts.append)
    for _ in range(5):
        obs.note_ai_attempt(False, kind="auth")
    assert alerts == []            # below the minimum attempt count
    for _ in range(10):
        obs.note_ai_attempt(False, kind="auth")
    assert obs.maybe_alert() is True
    assert alerts and alerts[-1]["event"] == "ai_failure_rate_alert"


def test_healthy_chain_never_alerts():
    alerts: list[dict] = []
    obs.set_alert_hook(alerts.append)
    for _ in range(20):
        obs.note_ai_attempt(True)
    assert obs.maybe_alert() is False
    assert alerts == []


def test_broken_hook_does_not_break_the_request():
    def boom(_payload):
        raise RuntimeError("webhook down")

    obs.set_alert_hook(boom)
    for _ in range(12):
        obs.note_ai_attempt(False, kind="timeout")
    assert obs.maybe_alert() is True   # logged anyway, exception swallowed
