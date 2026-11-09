"""Translation store schema — version 2.

Schema 2 replaces the single overloaded ``status`` with independent
dimensions, because one field cannot honestly represent origin, evidence,
validation, publication and human verification at the same time:

    generation_method    source_import | llm | rule_based | legacy_unknown
    evidence_strength    direct | strong | weak | none
    validation_status    passed | failed | incomplete
    publication_status   published | labeled | quarantined
    human_verification   not_verified | verified

``legacy_status`` keeps the v1 value verbatim; the mapping from it is documented
in ``docs/PHASE2-SCHEMA-CONTRACT.md`` and implemented in ``migrate`` below.

Two invariants are enforced by triggers, not by callers:

* A human-verified row is immutable, its verification state can never be
  changed or removed by an UPDATE, and only an INSERT that names an authorised
  authority may set ``verified``. The translation pipeline therefore cannot
  promote its own output: it has no authority row.
* Reviewed/verified content is append-only; corrections arrive as a new row with
  ``supersedes_id`` pointing at the old one.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 4
DB_FILENAME = "translations.db"

LEGACY_STATUSES = ("verified", "reviewed", "ai_checked", "ai_unverified", "quarantined")
GENERATION_METHODS = ("source_import", "llm", "rule_based", "legacy_unknown")
EVIDENCE_STRENGTHS = ("direct", "strong", "weak", "none")
VALIDATION_STATUSES = ("passed", "failed", "incomplete")
PUBLICATION_STATUSES = ("published", "labeled", "quarantined")
HUMAN_VERIFICATION = ("not_verified", "verified")
EVIDENCE_CATEGORIES = ("A", "B", "C", "D")
KEY_SEPARATOR = "\x1f"

#: legacy status -> (generation_method, evidence_strength, validation_status,
#:                   publication_status, human_verification)
#: Human verification is never inferred from an old status name: every legacy
#: row lands on ``not_verified``, and the migration writes an event-log entry
#: saying so. Evidence strength from a legacy ``evidence_category`` is applied
#: afterwards, only when that column actually holds A–D.
LEGACY_STATUS_MAP = {
    "verified": ("legacy_unknown", "none", "incomplete", "labeled", "not_verified"),
    "reviewed": ("legacy_unknown", "none", "incomplete", "labeled", "not_verified"),
    "ai_checked": ("llm", "weak", "passed", "labeled", "not_verified"),
    "ai_unverified": ("llm", "none", "incomplete", "labeled", "not_verified"),
    "quarantined": ("legacy_unknown", "none", "failed", "quarantined", "not_verified"),
}

#: A -> direct, B/C -> strong, D -> weak, absent -> none.
LEGACY_EVIDENCE_MAP = {"A": "direct", "B": "strong", "C": "strong", "D": "weak"}

_TABLES_V2 = [
    """
    create table if not exists verification_authorities(
        authority_id integer primary key autoincrement,
        name         text not null,
        role         text not null default 'reviewer',
        authorized   integer not null default 0 check (authorized in (0,1)),
        created_at   text not null,
        note         text,
        unique(name, role)
    )
    """,
    """
    create table if not exists translations(
        translation_id          integer primary key autoincrement,
        sense_key               text not null,
        entry_key               text not null,
        language                text not null check (language in ('ne','zh','en')),
        text                    text not null,
        legacy_status           text,
        generation_method       text not null default 'legacy_unknown'
            check (generation_method in ('source_import','llm','rule_based','legacy_unknown')),
        evidence_strength       text not null default 'none'
            check (evidence_strength in ('direct','strong','weak','none')),
        validation_status       text not null default 'incomplete'
            check (validation_status in ('passed','failed','incomplete')),
        publication_status      text not null default 'labeled'
            check (publication_status in ('published','labeled','quarantined')),
        human_verification      text not null default 'not_verified'
            check (human_verification in ('not_verified','verified')),
        verification_authority_id integer references verification_authorities(authority_id),
        origin_source           text,
        origin_source_url       text,
        origin_source_version   text,
        origin_record_id        text,
        origin_retrieved_at     text,
        origin_method           text,
        sense_match_confidence  real,
        sense_match_method      text,           -- sense_gloss | sense_id | qid | article | headword | heuristic
        evidence_language       text,           -- language code of the evidence used ('ne' for direct lexical)
        import_batch            text,           -- batch id, so an import can be rolled back exactly
        evidence_ids            text,
        evidence_category       text check (evidence_category in ('A','B','C','D') or evidence_category is null),
        model_version           text,
        prompt_version          text,
        source_data_version     text,
        validator_version       text,
        confidence              real,
        flags                   text,
        reviewer                text,
        reviewed_at             text,
        reviewer_note           text,
        quarantine_reason       text,
        quarantine_rule         text,
        quarantine_batch        text,
        quarantined_at          text,
        supersedes_id           integer references translations(translation_id),
        created_at              text not null,
        updated_at              text
    )
    """,
    """
    create table if not exists sense_pos(
        pos_id        integer primary key autoincrement,
        sense_key     text not null,
        pos           text not null,
        pos_source    text not null,
        pos_source_type text not null check (pos_source_type in ('source_confirmed','predicted','unknown')),
        confidence    real,
        matched_by    text,           -- headword | headword+pinyin | sense+gloss | heuristic
        created_at    text not null
    )
    """,
    """
    create table if not exists sense_hsk(
        hsk_id       integer primary key autoincrement,
        entry_key    text not null,
        sense_key    text,
        hsk_standard text not null,   -- 'HSK2.0' | 'HSK3.0'
        hsk_level    integer not null,
        hsk_source   text not null,
        hsk_version  text,
        confidence   real,
        created_at   text not null
    )
    """,
    """
    create table if not exists entry_aliases(
        alias_key     text primary key,
        canonical_key text not null,
        reason        text,
        created_at    text not null
    )
    """,
    """
    create table if not exists sense_aliases(
        alias_key     text primary key,
        canonical_key text not null,
        reason        text,
        created_at    text not null
    )
    """,
    """
    create table if not exists id_collisions(
        collision_id integer primary key autoincrement,
        kind         text not null,      -- entry_key | sense_key
        key          text not null,
        members_json text not null,
        detected_at  text not null,
        data_version text,
        resolution   text                -- null until a human decides
    )
    """,
    """
    create table if not exists quarantine_records(
        quarantine_id  integer primary key autoincrement,
        translation_id integer references translations(translation_id),
        sense_key      text not null,
        original_text  text not null,
        reason         text not null,
        rule           text,
        batch_id       text,
        quarantined_at text not null,
        restored_at    text,
        restored_by    text,
        note           text
    )
    """,
    """
    create table if not exists user_corrections(
        correction_id  integer primary key autoincrement,
        sense_key      text not null,
        language       text not null default 'ne',
        reported_text  text,
        correct_text   text,
        reporter       text,
        reported_at    text not null,
        status         text not null default 'open' check (status in ('open','accepted','rejected','merged')),
        translation_id integer references translations(translation_id),
        note           text
    )
    """,
    """
    create table if not exists event_log(
        event_id    integer primary key autoincrement,
        occurred_at text not null,
        actor       text not null,
        action      text not null,
        table_name  text not null,
        record_key  text,
        before_json text,
        after_json  text,
        note        text
    )
    """,
]

_INDEXES_V2 = [
    "create index if not exists translations_by_sense on translations(sense_key, language, publication_status)",
    "create index if not exists translations_by_verification on translations(human_verification)",
    "create index if not exists translations_by_generation on translations(generation_method, validation_status)",
    "create index if not exists translations_by_supersedes on translations(supersedes_id)",
    "create unique index if not exists translations_unique_published_value "
    "on translations(sense_key, language, text) "
    "where human_verification = 'verified'",
    "create index if not exists sense_pos_by_sense on sense_pos(sense_key)",
    "create index if not exists sense_hsk_by_entry on sense_hsk(entry_key)",
    "create index if not exists sense_hsk_by_level on sense_hsk(hsk_standard, hsk_level)",
    "create index if not exists event_log_by_time on event_log(occurred_at)",
    "create index if not exists quarantine_by_sense on quarantine_records(sense_key)",
    "create index if not exists translations_by_import_batch on translations(import_batch)",
]

_TRIGGERS_V2 = [
    # A verified row is immutable, including its verification state.
    """
    create trigger if not exists translations_verified_immutable_update
    before update on translations
    when old.human_verification = 'verified'
    begin
        select raise(abort,
            'human-verified rows are immutable; insert a superseding row instead');
    end
    """,
    """
    create trigger if not exists translations_verified_immutable_delete
    before delete on translations
    when old.human_verification = 'verified'
    begin
        select raise(abort, 'human-verified rows cannot be deleted');
    end
    """,
    # Verification state can only be introduced by inserting a new row, never by
    # editing an existing one — that blocks "quietly flip it to verified".
    """
    create trigger if not exists translations_verification_is_append_only
    before update on translations
    when new.human_verification <> old.human_verification
    begin
        select raise(abort,
            'verification state is append-only: insert a new row with supersedes_id');
    end
    """,
    # ...and the new row must name an authority that is explicitly authorised.
    """
    create trigger if not exists translations_verification_requires_authority
    before insert on translations
    when new.human_verification = 'verified'
      and (new.verification_authority_id is null
           or not exists (select 1 from verification_authorities a
                          where a.authority_id = new.verification_authority_id
                            and a.authorized = 1))
    begin
        select raise(abort,
            'human verification needs an authorised reviewer authority');
    end
    """,
    """
    create trigger if not exists translations_verified_requires_reviewer
    before insert on translations
    when new.human_verification = 'verified'
      and (new.reviewer is null or trim(new.reviewer) = '')
    begin
        select raise(abort, 'verified rows need a reviewer');
    end
    """,
    # Quarantine must carry a reason, so it can be undone and explained.
    """
    create trigger if not exists translations_quarantine_needs_reason
    before insert on translations
    when new.publication_status = 'quarantined'
      and (new.quarantine_reason is null or trim(new.quarantine_reason) = '')
    begin
        select raise(abort, 'quarantined rows need a reason');
    end
    """,
    """
    create trigger if not exists quarantine_record_needs_text
    before insert on quarantine_records
    when new.original_text is null or trim(new.original_text) = ''
    begin
        select raise(abort, 'a quarantine record must keep the original text');
    end
    """,
    # A verification authority must be an identifiable human role. A pipeline
    # identity cannot be inserted here at all.
    """
    create trigger if not exists verification_authority_role_is_human
    before insert on verification_authorities
    when lower(new.role) not in ('reviewer','admin')
    begin
        select raise(abort, 'verification authorities must have role reviewer or admin');
    end
    """,
]

#: Schema 3 -> 4: supersession integrity. A chain is linear by construction:
#: translation ids are monotonic, so a new row can only point at an older one
#: (no cycle is possible), and the leaf guard stops a second successor from
#: branching it. A successor must stay inside the same sense and language, and a
#: verified row can only be superseded by another verified row.
_V4_TRIGGERS = [
    """
    create trigger if not exists translations_supersede_verified_needs_review
    before insert on translations
    when new.supersedes_id is not null
      and exists (select 1 from translations p
                  where p.translation_id = new.supersedes_id
                    and p.human_verification = 'verified')
      and new.human_verification <> 'verified'
    begin
        select raise(abort, 'a verified translation can only be superseded by a verified one');
    end
    """,
    # One successor per row: the old row must still be the leaf of its chain.
    """
    create trigger if not exists translations_supersede_must_target_leaf
    before insert on translations
    when new.supersedes_id is not null
      and exists (select 1 from translations s where s.supersedes_id = new.supersedes_id)
    begin
        select raise(abort, 'that translation already has a successor; supersede the leaf instead');
    end
    """,
    # A correction may not jump to another sense or another language.
    """
    create trigger if not exists translations_supersede_must_stay_in_sense
    before insert on translations
    when new.supersedes_id is not null
      and exists (select 1 from translations p
                  where p.translation_id = new.supersedes_id
                    and (p.sense_key <> new.sense_key or p.language <> new.language))
    begin
        select raise(abort, 'a successor must keep the same sense_key and language');
    end
    """,
    # The target has to exist at all.
    """
    create trigger if not exists translations_supersede_target_exists
    before insert on translations
    when new.supersedes_id is not null
      and not exists (select 1 from translations p where p.translation_id = new.supersedes_id)
    begin
        select raise(abort, 'supersedes_id does not name an existing translation');
    end
    """,
]

#: Schema 2 -> 3: the columns that make an import traceable and a
#: "source-supported" claim checkable. ``migrate`` applies these to a v2 store.
_V3_ALTERS = [
    "alter table translations add column sense_match_method text",
    "alter table translations add column evidence_language text",
    "alter table translations add column import_batch text",
    "alter table evidence add column language text",
    "create index if not exists translations_by_import_batch on translations(import_batch)",
]

#: The exact version-1 schema, kept so a real v1 store and the migration test can
#: both be built. Never edit this list.
_TABLES_V1 = [
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
        match_method text,
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
        evidence_ids      text,
        evidence_category text check (evidence_category in ('A','B','C','D')),
        model_version     text,
        prompt_version    text,
        source_data_version text,
        confidence        real,
        flags             text,
        reviewer          text,
        reviewed_at       text,
        reviewer_note     text,
        supersedes_id     integer references translations(translation_id),
        created_at        text not null
    )
    """,
    "create index if not exists translations_by_sense on translations(sense_key, language, status)",
    "create unique index if not exists translations_unique_active_value "
    "on translations(sense_key, language, text) "
    "where status in ('verified','reviewed','ai_checked')",
    "create index if not exists translations_by_supersedes on translations(supersedes_id)",
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
    when new.status in ('verified','reviewed')
      and (new.reviewer is null or trim(new.reviewer) = '')
    begin
        select raise(abort, 'verified/reviewed rows need a reviewer');
    end
    """,
]
