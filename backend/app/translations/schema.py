"""Translation store — schema 2 (see ``docs/PHASE2-SCHEMA-CONTRACT.md``).

Lives in its own file (``data/build/translations.db``) next to the shipped
dictionary, never inside ``dictionary.sqlite``: the dictionary file is replaced
whenever ``assetVersion`` changes and reviewed content must survive that.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone

from .schema_v2_tables import (  # noqa: F401  (re-exported for callers)
    EVIDENCE_CATEGORIES,
    GENERATION_METHODS,
    HUMAN_VERIFICATION,
    KEY_SEPARATOR,
    LEGACY_EVIDENCE_MAP,
    LEGACY_STATUS_MAP,
    LEGACY_STATUSES,
    PUBLICATION_STATUSES,
    SCHEMA_VERSION,
    VALIDATION_STATUSES,
    EVIDENCE_STRENGTHS,
    _INDEXES_V2,
    _TABLES_V1,
    _TABLES_V2,
    _TRIGGERS_V2,
    _V3_ALTERS,
)

DB_FILENAME = "translations.db"

#: Tables that schema 1 and 2 share, unchanged.
_TABLES_SHARED = [
    """
    create table if not exists versions(
        version_id   integer primary key autoincrement,
        component    text not null,
        version      text not null,
        content_hash text,
        note         text,
        created_at   text not null,
        unique(component, version)
    )
    """,
    """
    create table if not exists id_map(
        entry_id     integer not null,
        entry_key    text not null,
        sense_id     integer not null,
        sense_key    text not null,
        data_version text not null,
        primary key (sense_id, data_version)
    )
    """,
    """
    create table if not exists evidence(
        evidence_id  text primary key,
        sense_key    text not null,
        category     text not null check (category in ('A','B','C','D')),
        source       text not null,
        source_ref   text not null,
        url          text,
        license      text,
        license_url  text,
        snippet      text,
        language     text,
        match_method text,
        match_score  real,
        fetched_at   text not null,
        data_version text,
        unique(sense_key, source, source_ref)
    )
    """,
]

_V1_TRIGGER_NAMES = (
    "translations_immutable_update",
    "translations_immutable_delete",
    "translations_review_requires_reviewer",
)


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(value):
    return " ".join((value or "").strip().split()).lower()


def entry_key(simplified, pinyin):
    return "%s%s%s" % (normalize(simplified), KEY_SEPARATOR, normalize(pinyin))


def sense_key(simplified, pinyin, gloss_en):
    return "%s%s%s" % (entry_key(simplified, pinyin), KEY_SEPARATOR, normalize(gloss_en))


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    return conn


def user_version(conn):
    return conn.execute("pragma user_version").fetchone()[0]


def table_names(conn):
    return [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table' order by name")]


def trigger_names(conn):
    return [r[0] for r in conn.execute(
        "select name from sqlite_master where type='trigger' order by name")]


def snapshot(path):
    """Logical fingerprint: schema version + table inventory + row counts.

    Used to prove a rollback restored the previous *content*; file hashes are
    not reliable because SQLite may rewrite page layout when copying.
    """
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    try:
        tables = table_names(conn)
        return {
            "user_version": user_version(conn),
            "tables": tables,
            "counts": {t: conn.execute("select count(*) from %s" % t).fetchone()[0] for t in tables},
        }
    finally:
        conn.close()


def content_fingerprint(path):
    """Deterministic content hash of every table, ordered by primary key.

    Row counts alone cannot tell two different datasets apart. This hashes the
    canonical text of every row (one line per row, ``\\x1e`` between fields,
    ``\\x1d`` between rows) per table, so a backup can be compared by content:
    equal fingerprints mean equal values, not just equal sizes. Page layout,
    WAL state and file bytes are deliberately not part of the hash.
    """
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    try:
        per_table = {}
        for table in table_names(conn):
            if table.startswith("sqlite_"):
                continue
            pk = [r[1] for r in conn.execute("pragma table_info(%s)" % table) if r[5]]
            order = " order by " + ", ".join(pk) if pk else ""
            chunk = hashlib.sha256()
            rows = 0
            for row in conn.execute("select * from %s%s" % (table, order)):
                chunk.update("\x1e".join("" if v is None else str(v) for v in row).encode("utf-8"))
                chunk.update(b"\x1d")
                rows += 1
            per_table[table] = {"rows": rows, "sha256": chunk.hexdigest()}
        combined = hashlib.sha256(
            "\n".join("%s|%s|%s" % (t, per_table[t]["rows"], per_table[t]["sha256"])
                      for t in sorted(per_table)).encode("utf-8")
        ).hexdigest()
        return {"tables": per_table, "content_sha256": combined,
                "integrity": integrity_check(conn)}
    finally:
        conn.close()


def integrity_check(conn):
    return conn.execute("pragma quick_check").fetchone()[0]


def backup(path):
    """Copy the database beside itself with SQLite's backup API.

    A plain file copy of a WAL database can be torn; the backup API cannot.
    The copy carries the same content but not necessarily the same bytes.
    """
    if not os.path.exists(path):
        return None
    dest = "%s.bak-%s" % (path, utc_stamp())
    src = sqlite3.connect(path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


def _log_event(conn, actor, action, table_name, record_key=None, before=None, after=None, note=None):
    conn.execute(
        "insert into event_log(occurred_at, actor, action, table_name, record_key, "
        "before_json, after_json, note) values(?,?,?,?,?,?,?,?)",
        (utc_now(), actor, action, table_name, record_key,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None,
         note),
    )


def _translations_ddl_v2():
    for stmt in _TABLES_V2:
        if "create table if not exists translations(" in stmt:
            return stmt
    raise RuntimeError("v2 translations DDL not found")


def _create_v2(conn):
    for stmt in _TABLES_SHARED + _TABLES_V2:
        conn.execute(stmt)
    for stmt in _INDEXES_V2:
        conn.execute(stmt)
    for stmt in _TRIGGERS_V2:
        conn.execute(stmt)


def _migrate_v1_to_v2(conn):
    """Rebuild ``translations`` with the dimension fields and map every row.

    Rows are preserved one-for-one (same translation_id), the legacy status is
    kept verbatim in ``legacy_status``, and every row lands on
    ``human_verification = 'not_verified'``: an old status name is not proof of
    human verification. Each migrated row gets an event-log entry saying so.
    """
    for name in _V1_TRIGGER_NAMES:
        conn.execute("drop trigger if exists %s" % name)
    conn.execute("drop index if exists translations_unique_active_value")

    conn.execute("alter table translations rename to translations_v1")
    conn.execute(_translations_ddl_v2())
    for stmt in _INDEXES_V2:
        if "translations" in stmt:
            conn.execute(stmt)
    for stmt in _TRIGGERS_V2:
        if "translations" in stmt:
            conn.execute(stmt)

    rows = conn.execute("select * from translations_v1").fetchall()
    columns = [d[0] for d in conn.execute("select * from translations_v1 limit 1").description]
    index = {name: i for i, name in enumerate(columns)}

    migrated = []
    for row in rows:
        legacy = row[index["status"]]
        method, strength, validation, publication, verification = LEGACY_STATUS_MAP[legacy]
        category = row[index["evidence_category"]]
        if category in LEGACY_EVIDENCE_MAP:
            strength = LEGACY_EVIDENCE_MAP[category]
            if method == "legacy_unknown":
                method = "source_import"
        source_type = row[index["source_type"]]
        origin_method = {
            "ai": "llm", "dict": "source_import", "import": "source_import", "human": "human",
        }.get(source_type, "legacy_unknown")
        # A legacy quarantine carried no reason field; record that honestly rather
        # than inventing one. The original text stays recoverable in quarantine_records.
        q_reason = q_rule = q_batch = q_at = None
        if legacy == "quarantined":
            q_reason = "legacy status 'quarantined' from schema 1; reason not recorded"
            q_rule, q_batch, q_at = "legacy_status", "migration:v1->v2", utc_now()
        migrated.append((
            row[index["translation_id"]], row[index["sense_key"]], row[index["entry_key"]],
            row[index["language"]], row[index["text"]], legacy,
            method, strength, validation, publication, verification,
            None,                                   # verification_authority_id
            None, None, None, None, None,           # origin_source..origin_retrieved_at
            origin_methods_note(origin_method),
            None,                                   # sense_match_confidence
            row[index["evidence_ids"]], category,
            row[index["model_version"]], row[index["prompt_version"]],
            row[index["source_data_version"]], None,
            row[index["confidence"]], row[index["flags"]],
            row[index["reviewer"]], row[index["reviewed_at"]], row[index["reviewer_note"]],
            q_reason, q_rule, q_batch, q_at,
            row[index["supersedes_id"]], row[index["created_at"]], utc_now(),
        ))
        _log_event(
            conn, actor="migration:v1->v2", action="map_legacy_status",
            table_name="translations", record_key=str(row[index["translation_id"]]),
            before={"status": legacy, "source_type": source_type},
            after={"generation_method": method, "evidence_strength": strength,
                   "validation_status": validation, "publication_status": publication,
                   "human_verification": "not_verified"},
            note="legacy status name is not evidence of human verification",
        )

    insert_sql = """
        insert into translations(
            translation_id, sense_key, entry_key, language, text, legacy_status,
            generation_method, evidence_strength, validation_status,
            publication_status, human_verification, verification_authority_id,
            origin_source, origin_source_url, origin_source_version,
            origin_record_id, origin_retrieved_at, origin_method,
            sense_match_confidence, evidence_ids, evidence_category,
            model_version, prompt_version, source_data_version, validator_version,
            confidence, flags, reviewer, reviewed_at, reviewer_note,
            quarantine_reason, quarantine_rule, quarantine_batch, quarantined_at,
            supersedes_id, created_at, updated_at)
        values(%s)
    """ % ",".join(["?"] * 37)
    if migrated:
        conn.executemany(insert_sql, migrated)

    # Preserve the original text of every legacy quarantine, so it can be restored.
    for row in rows:
        if row[index["status"]] != "quarantined":
            continue
        conn.execute(
            "insert into quarantine_records(translation_id, sense_key, original_text, reason, "
            "rule, batch_id, quarantined_at, note) values(?,?,?,?,?,?,?,?)",
            (row[index["translation_id"]], row[index["sense_key"]], row[index["text"]],
             "legacy status 'quarantined' from schema 1; reason not recorded",
             "legacy_status", "migration:v1->v2", utc_now(),
             "text preserved so the row can be restored or re-reviewed"),
        )

    conn.execute("drop table translations_v1")
    return {"migrated_rows": len(migrated)}


def migrate(path, dry_run=False, data_version=None):
    """Create the store or upgrade it to ``SCHEMA_VERSION``. Returns a report."""
    report = {
        "path": path,
        "dry_run": bool(dry_run),
        "existed": os.path.exists(path),
        "from_version": None,
        "to_version": SCHEMA_VERSION,
        "backup": None,
        "actions": [],
    }
    if report["existed"]:
        conn = sqlite3.connect(path)
        report["from_version"] = user_version(conn)
        conn.close()
        if report["from_version"] > SCHEMA_VERSION:
            raise RuntimeError(
                "store is at schema %s, newer than this release (%s); refusing to touch it"
                % (report["from_version"], SCHEMA_VERSION))
        if report["from_version"] == SCHEMA_VERSION:
            report["actions"].append("already at version %d, nothing to do" % SCHEMA_VERSION)
            return report
        if not dry_run:
            report["backup"] = backup(path)
            report["actions"].append("backup %s" % report["backup"])
        else:
            report["actions"].append("would back up before migrating from %s" % report["from_version"])

    if dry_run:
        report["actions"].append(
            "would create schema version %d" % SCHEMA_VERSION
            if report["from_version"] is None
            else "would upgrade %d -> %d" % (report["from_version"], SCHEMA_VERSION))
        return report

    conn = connect(path)
    # A table rebuild needs foreign-key enforcement off (SQLite's documented
    # procedure); the PRAGMA is a no-op inside a transaction, so it goes first.
    rebuild = report["from_version"] == 1
    if rebuild:
        conn.execute("pragma foreign_keys = off")
    try:
        with conn:
            if report["from_version"] is None:
                _create_v2(conn)
                conn.execute(
                    "insert or ignore into versions(component, version, content_hash, note, created_at) "
                    "values('schema', ?, ?, 'schema 3: dimensions, provenance, governance, import batches', ?)",
                    (str(SCHEMA_VERSION), _schema_hash(), utc_now()),
                )
            elif report["from_version"] == 1:
                for stmt in _TABLES_SHARED:
                    conn.execute(stmt)
                for stmt in _TABLES_V2:
                    if "create table if not exists translations(" in stmt:
                        continue          # created inside the rebuild, after the rename
                    conn.execute(stmt)
                _migrate_v1_to_v2(conn)
                for stmt in _TRIGGERS_V2:
                    conn.execute(stmt)
                for stmt in _INDEXES_V2:
                    if "translations" not in stmt:
                        conn.execute(stmt)
                conn.execute(
                    "insert or ignore into versions(component, version, content_hash, note, created_at) "
                    "values('schema', ?, ?, 'upgraded from schema 1', ?)",
                    (str(SCHEMA_VERSION), _schema_hash(), utc_now()),
                )
            elif report["from_version"] == 2:
                # Schema 2 -> 3: the import-batch and sense-match columns.
                existing = [r[1] for r in conn.execute("pragma table_info(translations)")]
                evidence_cols = [r[1] for r in conn.execute("pragma table_info(evidence)")]
                for stmt in _V3_ALTERS:
                    if "add column" in stmt:
                        table = stmt.split("alter table")[1].split()[0]
                        col = stmt.split("add column")[1].split()[0]
                        if col in (existing if table == "translations" else evidence_cols):
                            continue
                    conn.execute(stmt)
                for stmt in _TRIGGERS_V2:
                    conn.execute(stmt)
                for stmt in _INDEXES_V2:
                    conn.execute(stmt)
                conn.execute(
                    "insert or ignore into versions(component, version, content_hash, note, created_at) "
                    "values('schema', ?, ?, 'upgraded from schema 2: import batch, sense match method', ?)",
                    (str(SCHEMA_VERSION), _schema_hash(), utc_now()),
                )
            else:
                raise RuntimeError("no migration path from schema %s" % report["from_version"])
            # Schema 2 -> 3: add the import/sense-match columns to an existing store.
            if report["from_version"] == 2:
                existing = [r[1] for r in conn.execute("pragma table_info(translations)")]
                evidence_cols = [r[1] for r in conn.execute("pragma table_info(evidence)")]
                for stmt in _V3_ALTERS:
                    col = stmt.split("add column")[1].split()[0] if "add column" in stmt else None
                    table = stmt.split("alter table")[1].split()[0] if "add column" in stmt else None
                    if col:
                        cols = existing if table == "translations" else evidence_cols
                        if col in cols:
                            continue
                    conn.execute(stmt)
                for stmt in _TRIGGERS_V2:
                    conn.execute(stmt)
                conn.execute(
                    "insert or ignore into versions(component, version, content_hash, note, created_at) "
                    "values('schema', ?, ?, 'upgraded from schema 2: import batch, sense match method', ?)",
                    (str(SCHEMA_VERSION), _schema_hash(), utc_now()),
                )
            conn.execute("pragma user_version = %d" % SCHEMA_VERSION)
            if data_version:
                conn.execute(
                    "insert or ignore into versions(component, version, note, created_at) "
                    "values('dictionary', ?, 'recorded by the migration', ?)",
                    (str(data_version), utc_now()),
                )
    finally:
        conn.close()
    if rebuild:
        conn = connect(path)
        try:
            violations = conn.execute("pragma foreign_key_check").fetchall()
            report["foreign_key_violations"] = len(violations)
        finally:
            conn.close()
    report["actions"].append("schema version %d applied" % SCHEMA_VERSION)
    return report


def origin_methods_note(origin_method):
    """Provenance is unknown on legacy rows; keep the hint rather than dropping it."""
    return origin_method if origin_method != "legacy_unknown" else None


def rollback(path, backup_path, dry_run=False):
    """Restore ``path`` from ``backup_path`` (same directory only)."""
    if not os.path.exists(backup_path):
        raise FileNotFoundError(backup_path)
    target_dir = os.path.dirname(os.path.abspath(path))
    source_dir = os.path.dirname(os.path.abspath(backup_path))
    if os.path.abspath(source_dir) != os.path.abspath(target_dir):
        raise ValueError("backup must live beside the database, in %s" % target_dir)
    if dry_run:
        return {"dry_run": True, "would_restore": backup_path, "into": path}
    aside = None
    if os.path.exists(path):
        aside = "%s.rollback-%s" % (path, utc_stamp())
        os.replace(path, aside)
    for suffix in ("-wal", "-shm"):
        side = path + suffix
        if os.path.exists(side):
            os.remove(side)
    shutil.copy2(backup_path, path)
    restored = content_fingerprint(path)
    expected = content_fingerprint(backup_path)
    return {"restored": path, "from": backup_path, "previous_moved_to": aside,
            "snapshot": snapshot(path),
            "content_matches_backup": restored == expected,
            "content_sha256": restored["content_sha256"],
            "integrity": restored["integrity"]}


def _schema_hash():
    payload = ("\n".join(_TABLES_SHARED + _TABLES_V2 + _INDEXES_V2 + _TRIGGERS_V2)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
