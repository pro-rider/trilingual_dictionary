# Dataset counts, with units and queries

Every number below states its unit and the exact SQL it came from. Nothing here mixes entries with senses or with translation records.

| metric | value | unit | database |
|---|---|---|---|
| `entries` | 123672 | entry | dictionary.sqlite |
| `entries_with_freq` | 116533 | entry | dictionary.sqlite |
| `senses` | 198306 | sense | dictionary.sqlite |
| `senses_with_nepali` | 3245 | sense (translation value in senses.gloss_ne) | dictionary.sqlite |
| `entries_with_nepali` | 2968 | entry (has >=1 Nepali sense) | dictionary.sqlite |
| `senses_nepali_status_ai_translated` | 3245 | sense (ne_status='ai_translated') | dictionary.sqlite |
| `senses_hsk_entry_total` | 7447 | sense (belongs to an entry with hsk_level) | dictionary.sqlite |
| `senses_nepali_inside_hsk_entries` | 2737 | sense (Nepali value, entry has hsk_level) | dictionary.sqlite |
| `entries_hsk_tagged` | 2477 | entry (hsk_level not null) | dictionary.sqlite |
| `entries_hsk_tagged_with_nepali` | 2477 | entry (hsk_level not null and has Nepali sense) | dictionary.sqlite |
| `examples_total` | 392 | example row | dictionary.sqlite |
| `examples_reviewed` | 0 | example row | dictionary.sqlite |
| `fts_rows` | 123672 | FTS row (search index, mirrors entries) | dictionary.sqlite |
| `fts_zh_rows` | 123596 | FTS row (trigram index, mirrors entries) | dictionary.sqlite |
| `translations_rows` | 3245 | translation record (translations.db) | translations.db |
| `translations_legacy_imported` | 3245 | translation record (origin dictionary.sqlite:senses.ne) | translations.db |
| `translations_verified` | 0 | translation record (human_verification='verified') | translations.db |
| `evidence_rows` | 0 | evidence record | translations.db |
| `id_map_rows` | 3245 | id_map row (sense_id -> sense_key, one per dictionary build) | translations.db |
| `sense_pos_rows` | 0 | POS record | translations.db |
| `sense_hsk_rows` | 0 | HSK record | translations.db |

## Queries

* `entries` — `select count(*) from entries`
* `entries_with_freq` — `select count(*) from entries where freq_rank is not null`
* `senses` — `select count(*) from senses`
* `senses_with_nepali` — `select count(*) from senses where trim(coalesce(gloss_ne,''))<>''`
* `entries_with_nepali` — `select count(distinct s.entry_id) from senses s where trim(coalesce(s.gloss_ne,''))<>''`
* `senses_nepali_status_ai_translated` — `select count(*) from senses where ne_status='ai_translated'`
* `senses_hsk_entry_total` — `select count(*) from senses s join entries e on e.entry_id=s.entry_id where e.hsk_level is not null`
* `senses_nepali_inside_hsk_entries` — `select count(*) from senses s join entries e on e.entry_id=s.entry_id where e.hsk_level is not null and trim(coalesce(s.gloss_ne,''))<>''`
* `entries_hsk_tagged` — `select count(*) from entries where hsk_level is not null`
* `entries_hsk_tagged_with_nepali` — `select count(*) from entries e where e.hsk_level is not null and exists(select 1 from senses s where s.entry_id=e.entry_id and trim(coalesce(s.gloss_ne,''))<>'')`
* `examples_total` — `select count(*) from examples`
* `examples_reviewed` — `select count(*) from examples where review_status='reviewed'`
* `fts_rows` — `select count(*) from fts`
* `fts_zh_rows` — `select count(*) from fts_zh`
* `translations_rows` — `select count(*) from translations`
* `translations_legacy_imported` — `select count(*) from translations where origin_source='dictionary.sqlite:senses.ne'`
* `translations_verified` — `select count(*) from translations where human_verification='verified'`
* `evidence_rows` — `select count(*) from evidence`
* `id_map_rows` — `select count(*) from id_map`
* `sense_pos_rows` — `select count(*) from sense_pos`
* `sense_hsk_rows` — `select count(*) from sense_hsk`

## How the overlap was calculated

Overlap is computed on `senses` rows joined to `entries` on `entry_id`; an entry counts as Nepali-bearing when at least one of its senses has a non-empty `gloss_ne`. Both sides therefore use the same identity (`entry_id` from the dictionary, and the derived `entry_key`/`sense_key` in `translations.db`), never a headword string match.
