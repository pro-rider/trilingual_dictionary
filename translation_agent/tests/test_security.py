"""Security surface: production refusal, secret redaction, export gating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from translation_agent.audit.raw_response_store import prepare_response, redact
from translation_agent.config import (
    AgentConfig,
    ProductionDatabaseRefused,
    assert_not_production,
)
from translation_agent.domain.models import SenseRef
from translation_agent.export.candidate_export import ExportRefused, export_approved
from translation_agent.generation.pipeline import TranslationPipeline
from translation_agent.ledger.sqlite_ledger import REVIEWER, SqliteLedger, LedgerSchemaMismatch
from translation_agent.providers.fake_provider import FakeProvider


SENSE = SenseRef("fixture:1001", 1001, "水", "shui3", "water")


@pytest.mark.parametrize(
    "path",
    [
        "backend/data/build/dictionary.sqlite",
        "backend/data/build/translations.db",
        "/srv/app/backend/data/build/candidates.db",
        "assets/data/dictionary.sqlite",
    ],
)
def test_production_paths_are_refused(path):
    with pytest.raises(ProductionDatabaseRefused):
        assert_not_production(path)


def test_ledger_opens_only_its_own_file(tmp_path):
    path = str(tmp_path / "candidates.db")
    assert assert_not_production(path) == path
    with SqliteLedger(path) as ledger:
        assert ledger.path == path


def test_schema_mismatch_fails_closed(tmp_path):
    path = str(tmp_path / "candidates.db")
    SqliteLedger(path).close()
    # Simulate a foreign/legacy file: wipe the ledger tables.
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE candidates")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerSchemaMismatch):
        SqliteLedger(path, create=False)


def test_secrets_are_redacted_before_storage():
    payload = '{"translation":"पानी","debug":"Bearer abcdefghijklmnop sk-ABCDEF1234567890"}'
    cleaned = redact(payload)
    assert "sk-ABCDEF1234567890" not in cleaned
    assert "abcdefghijklmnop" not in cleaned
    assert "[REDACTED]" in cleaned


def test_raw_payload_is_size_capped():
    row = prepare_response(
        request_id="req_x",
        payload="पानी " * 5000,
        max_bytes=1024,
        retention_days=30,
    )
    assert row["truncated"] == 1
    assert row["bytes"] <= 1024


def test_pipeline_stores_redacted_raw_only(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch([SENSE], batch_id="b1")
        rows = ledger._conn.execute("SELECT payload FROM raw_responses").fetchall()
        assert rows, "raw response should be retained for audit"
        assert "sk-" not in rows[0]["payload"]


def test_export_refuses_when_nothing_is_approved(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch([SENSE], batch_id="b1")
        with pytest.raises(ExportRefused):
            export_approved(ledger, str(tmp_path / "out.json"))


def test_export_contains_only_approved(tmp_path):
    with SqliteLedger(str(tmp_path / "c.db")) as ledger:
        cfg = AgentConfig(ledger_path=ledger.path)
        pipeline = TranslationPipeline(ledger, FakeProvider(), cfg)
        pipeline.run_batch([SENSE], batch_id="b1")
        candidate = next(iter(ledger.iter_candidates()))
        ledger.transition(candidate["candidate_id"], "approved", REVIEWER, "looks correct")
        payload = export_approved(ledger, str(tmp_path / "out.json"))
        assert payload["candidate_count"] == 1
        written = json.loads(Path(tmp_path / "out.json").read_text(encoding="utf-8"))
        assert written["export_checksum"] == payload["export_checksum"]
        assert all(c["sense_key"] == "fixture:1001" for c in written["candidates"])
