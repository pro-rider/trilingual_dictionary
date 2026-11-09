"""Translation store schema — version 1.

Lives in its own file (``data/build/translations.db``) next to the shipped
dictionary, never inside ``dictionary.sqlite``: the dictionary file is replaced
whenever ``assetVersion`` changes, and reviewed content must survive that.

Two rules are enforced by the database itself, not by callers:

* ``verified`` and ``reviewed`` rows are immutable. An import or the agent may
  only `insert` a new proposal row that points at the old one through
  ``supersedes_id``; ``update`` and ``delete`` are aborted by triggers.
* A ``sense_key`` identifies a meaning, not a row. Row ids are rebuilt whenever
  the dictionary is rebuilt; the key is ``simplified + pinyin + gloss_en`` and
  is the only thing that may be written to by content jobs.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 1
DB_FILENAME = "translations.db"

STATUSES = ("verified", "reviewed", "ai_checked", "ai_unverified", "quarantined")
SOURCE_TYPES = ("human", "dict", "ai", "import")
EVIDENCE_CATEGORIES = ("A", "B", "C", "D")
KEY_SEPARATOR = "\x1f"

_DDL = [
    """
    create table if not exists versions(
        version_id   integer primary key autoincrement,
        component    text not null,      -- schema | dictionary | prompt | model | termbase | evidence
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
        data_version text not null,      -- dictionary version this mapping was built from
        primary key (sense_id, data_version)
    )
    """,
    """
    create table if not exists evidence(
        evidence_id  text primary key,    -- sha1(source|source_ref|fetched_at)
        sense_key    text not null,
        category     text not null check (category in ('A','B','C','D')),
        source       text not null,      -- wiktionary | kaikki | tatoeba | wikidata | wikipedia | commons | llm
        source_ref   text not null,      -- page title / sentence id / QID
        url          text,
        license      text,
        license_url  text,
        snippet      text,
        match_method text,               -- gloss_exact | gloss_normalized | sentence_contains | qid | none
        match_score  real,
        fetched_at   text not null,
        data_version text,
        unique(sense_key, source, source_ref)
    )
    """,
    """
    create table if not exists translations(
        translation_id    integer primary key autoincrement,
        sense_key         text not null,
        entry_key         text not null,
        language          text not null check (language in ('ne','zh','en')),
        text              text not null,
        status            text not null check (status in ('verified','reviewed','ai_checked','ai_unverified','quarantined')),
        source_type       text not null check (source_type in ('human','dict','ai','import')),
        evidence_ids      text,          -- JSON array of evidence_id
        evidence_category text check (evidence_category in ('A','B','C','D')),
        model_version     text,
        prompt_version    text,
        source_data_version text,
        confidence        real,
        flags             text,          -- JSON object of validator flags
        reviewer          text,
        reviewed_at       text,
        reviewer_note     text,
        supersedes_id     integer references translations(translation_id),
        created_at        text not null
    )
    """,
    """
    create index if not exists translations_by_sense
        on translations(sense_key, language, status)
    """,
    """
    create unique index if not exists translations_unique_active_value
        on translations(sense_key, language, text)
        where status in ('verified','reviewed','ai_checked')
    """,
    """
    create index if not exists translations_by_supersedes
        on translations(supersedes_id)
    """,
    """
    create trigger if not exists translations_immutable_update
    before update on translations
    when old.status in ('verified','reviewed')
    begin
        select raise(abort,
            'verified/reviewed rows are immutable; insert a superseding proposal instead');
    end
    """,
    """
    create trigger if not exists translations_immutable_delete
    before delete on translations
    when old.status in ('verified','reviewed')
    begin
        select raise(abort,
            'verified/reviewed rows are immutable; insert a superseding proposal instead');
    end
    """,
    """
    create trigger if not exists translations_review_requires_reviewer
    before insert on translations
    when new.status in ('verified','reviewed') and (new.reviewer is null or trim(new.reviewer) = '')
    begin
        select raise(abort, 'verified/reviewed rows need a reviewer');
    end
    """,
]


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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


def backup(path):
    """Copy the database next to itself, and return the backup path.

    The copy is made with SQLite's own backup API so a live WAL is included.
    A plain file copy of a WAL database can be torn; this cannot.

    Note: the backup carries the same *content* but not necessarily the same
    bytes — SQLite may rewrite page order and the freelist. Compare backups by
    schema version and row counts, never by file hash.
    """
    if not os.path.exists(path):
        return None
    dest = "%s.bak-%s" % (path, utc_stamp())
    src_conn = sqlite3.connect(path)
    dst_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    return dest


def migrate(path, dry_run=False, data_version=None):
    """Create or upgrade the translation store. Returns a report dict."""
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
        if report["from_version"] >= SCHEMA_VERSION:
            report["actions"].append("already at version %d, nothing to do" % SCHEMA_VERSION)
            return report
        if not dry_run:
            report["backup"] = backup(path)
            report["actions"].append("backup %s (sha256 %s)" % (report["backup"], sha256_of(report["backup"])))
        else:
            report["actions"].append("would back up before migrating from %s" % report["from_version"])

    if dry_run:
        report["actions"].append("would create schema version %d" % SCHEMA_VERSION)
        return report

    conn = connect(path)
    try:
        with conn:
            for stmt in _DDL:
                conn.execute(stmt)
            conn.execute("pragma user_version = %d" % SCHEMA_VERSION)
            if report["from_version"] is None:
                conn.execute(
                    "insert or ignore into versions(component, version, content_hash, note, created_at) "
                    "values('schema', ?, ?, 'initial schema: translations, evidence, versions, id_map', ?)",
                    (str(SCHEMA_VERSION), _schema_hash(), utc_stamp()),
                )
            if data_version:
                conn.execute(
                    "insert or ignore into versions(component, version, note, created_at) "
                    "values('dictionary', ?, 'recorded by the migration', ?)",
                    (str(data_version), utc_stamp()),
                )
    finally:
        conn.close()
    report["actions"].append("schema version %d applied" % SCHEMA_VERSION)
    return report


def rollback(path, backup_path, dry_run=False):
    """Restore `path` from `backup_path`. Refuses anything outside the same dir."""
    if not os.path.exists(backup_path):
        raise FileNotFoundError(backup_path)
    target_dir = os.path.dirname(os.path.abspath(path))
    source_dir = os.path.dirname(os.path.abspath(backup_path))
    if os.path.abspath(source_dir) != os.path.abspath(target_dir):
        raise ValueError("backup must live beside the database, in %s" % target_dir)
    if dry_run:
        return {"dry_run": True, "would_restore": backup_path, "into": path}
    # Move the current file aside rather than deleting it: a failed rollback is
    # reversible, and the operator can still inspect what was replaced.
    aside = None
    if os.path.exists(path):
        aside = "%s.rollback-%s" % (path, utc_stamp())
        shutil.move(path, aside)
    for suffix in ("-wal", "-shm"):
        side = path + suffix
        if os.path.exists(side):
            os.remove(side)
    shutil.copy2(backup_path, path)
    return {
        "restored": path,
        "from": backup_path,
        "previous_moved_to": aside,
        "sha256": sha256_of(path),
    }


def _schema_hash():
    payload = "\n".join(_DDL).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def snapshot(path):
    """Logical fingerprint of a database: schema version + table inventory.

    Used to prove a rollback restored the previous *content*; file hashes are
    not a reliable signal because SQLite may rewrite page layout.
    """
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    try:
        return {
            "user_version": conn.execute("pragma user_version").fetchone()[0],
            "tables": table_names(conn),
            "counts": {
                name: conn.execute("select count(*) from %s" % name).fetchone()[0]
                for name in table_names(conn)
            },
        }
    finally:
        conn.close()


def table_names(conn):
    return [r[0] for r in conn.execute("select name from sqlite_master where type='table' order by name")]
