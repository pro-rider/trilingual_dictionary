# DATA-GOVERNANCE.md — Dictionary Data & Dataset Management

Everything linguistic that ships with this project is a single JSON file with two
byte-identical copies:

| Copy | Path | Consumer |
|---|---|---|
| App | `trilingual_dictionary/assets/data/en_zh_ne.json` | `DictionaryRepository` (offline) |
| Backend | `backend/data/seed/en_zh_ne.json` | `services/dataset.py` (API) |

Verified hash (SHA‑256) of both files on 2026‑11‑07:
`1C0DD349DB7DA9F9B50C56C922994F4A713C8C812B9FB9028675200958941F89`

There is **no database of record** for dictionary content. Postgres holds only
`favorites` and `feedback`; the `words`/`senses`/`example_sentences` tables and
`scripts/seed_database.py` exist but no endpoint reads them yet.

---

## 1. Current inventory (be honest with it)

| Metric | Value |
|---|---|
| `dataset_version` | 1 |
| Entries | **6** — `light`, `trade`, `mountain`, `water`, `book`, `teacher` |
| Senses | 7 (`light` has two: noun "illumination", adjective "not heavy") |
| Example sets | 7 (one per sense) |
| `meaning_ne_status` values present | `published` only |
| `review_status` values present | `approved` only |
| File size | ~5.7 KB |

**This is a curated demo seed, not a dictionary.** Product gap: a usable v1 needs
roughly 300–500 reviewed headwords. Do not describe the app as having a large
dictionary, and do not quote the 6 entries as coverage.

---

## 2. Schema (contract)

```json
{
  "dataset_version": 1,
  "entries": [
    {
      "entry_id": "light",
      "word_en": "light",
      "word_zh": "光",
      "senses": [
        {
          "sense_id": "light_noun_illumination",
          "word_en": "light",
          "word_zh": "光",
          "pinyin": "guāng",
          "ipa_en": "/laɪt/",
          "part_of_speech": "noun",
          "meaning_en": "…",
          "meaning_zh": "…",
          "meaning_ne": "प्रकाश",
          "meaning_ne_status": "published",
          "examples": [
            {"en": "…", "zh": "…", "ne": "…",
             "source": "reviewed", "review_status": "approved"}
          ]
        }
      ]
    }
  ]
}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `dataset_version` | int | yes | bump on any content change; mirrored in `AppConstants.datasetVersion`, `Settings.dataset_version` |
| `entry_id` | str | yes | unique, lowercase ASCII, stable forever (favorites store it) |
| `word_en` / `word_zh` | str | yes | headword; `word_zh` Simplified |
| `senses[]` | array | yes | ≥1 |
| `sense_id` | str | yes | unique within the entry, convention `<entry>_<pos>_<gloss>` |
| `pinyin` | str | recommended | tone-marked (`guāng`); matching strips marks |
| `ipa_en` | str | optional | slashes included |
| `part_of_speech` | str | recommended | `noun|verb|adj|adv|prep|conj|pron|num|phrase|idiom` |
| `meaning_en/zh/ne` | str | **yes** | non-empty; `ne` must be Devanagari |
| `meaning_ne_status` | str | yes | `ai_draft → machine_checked → human_reviewed → published` (+ `flagged`) |
| `examples[]` | array | yes | ≥1 with `review_status: approved` |
| `example.source` | str | yes | `reviewed` \| `ai` |
| `example.review_status` | str | yes | `approved` \| `unreviewed` \| `ai_generated` \| `flagged` |

Breaking these fields breaks `lib/data/models/dictionary_entry.dart`,
`backend/app/schemas/search.py`, and any saved favorite ids. See `IMPACT-MAP.md`.

---

## 3. Provenance, licensing, attribution — current state

**Honest status: not yet documented per entry.** No `source`, `license`, or
`contributor` field exists in the schema, and the repository has no `LICENSE`
file. The 7 senses were authored for this project as seed data; no third-party
corpus, scraped site, or commercial dictionary has been declared as an input.

Requirements before the dataset grows:

1. Every batch of new entries records where it came from (author, date, method:
   human / AI-draft-then-reviewed / licensed source).
2. Only public-domain or compatibly licensed sources may be imported. Do **not**
   copy from commercial dictionaries (Oxford, Longman, Wiktionary is CC BY‑SA and
   needs attribution + share-alike handling), and do not scrape.
3. Add a top-level `LICENSE` plus a `data/NOTICE` file listing source, licence,
   and attribution text if any external source is used.
4. Nepali content should be reviewed by a Nepali speaker; record the reviewer id
   in a new `reviewed_by` field rather than leaving it implicit. Today none is
   recorded — that is a **known review gap**, not proof of correctness.

---

## 4. Unicode & text rules

| Topic | Rule today | Requirement |
|---|---|---|
| Encoding | UTF‑8, no BOM | keep |
| Chinese | Simplified | Traditional is out of scope; convert before entry |
| Nepali | Devanagari, no romanisation in data | romanisation is computed (`romanize_ne`, deterministic) |
| Normalisation | none applied at load | store NFC; reject strings containing ZWJ/ZWNJ unless linguistically required |
| Pinyin | Latin letters + tone marks (`ā á ǎ à`) | one syllable per space-separated token |
| IPA | wrapped in `/…/` | consistent notation |
| Whitespace | single spaces, no trailing space | trim |
| Mixed script | not allowed inside a single field | validate |

`Normalizer.pinyinKey()` strips tone marks for matching only; the stored pinyin
keeps them for display.

---

## 5. Duplicate & conflict rules

- `entry_id` unique across the file; a new sense for an existing word goes into
  that entry, never a duplicate entry.
- `sense_id` unique globally in practice (it is used as a lookup key).
- Same English word with a different POS ⇒ separate senses (`light` noun /
  `light` adj), not separate entries.
- `word_zh` collisions across entries are allowed but must be checked manually
  (one Chinese surface can map to several English words).
- If two batches disagree on a translation, the **human-reviewed** value wins;
  the other is discarded, not merged.
- Before adding an entry, search both `word_en` and `word_zh` for an existing
  match (`grep -i` on the JSON is sufficient at this size).

---

## 6. Validation gate

```powershell
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend
.venv\Scripts\python.exe -m scripts.validate_dataset
# → "OK: dataset integrity valid."  (exit 0)
```

Checks performed by `scripts/validate_dataset.py`:

- dataset is not empty;
- every sense has non-empty `meaning_en`, `meaning_zh`, `meaning_ne`;
- every sense has at least one example with `review_status == "approved"`.

**Not checked** (do these manually or extend the script): unique ids, valid POS
enum, Devanagari presence in `ne`, pinyin format, IPA format, duplicate examples,
`dataset_version` consistency, and — important — the **app copy**. The validator
reads only the backend copy.

Recommended additions when the script is next touched: id uniqueness, Devanagari
check (reuse `quality.validate_language_fields`), NFC check, and a hash comparison
between the two copies.

---

## 7. Update workflow (mandatory order)

1. Edit `backend/data/seed/en_zh_ne.json` first.
2. Run the validator; fix everything it reports.
3. `Copy-Item` the file to
   `trilingual_dictionary/assets/data/en_zh_ne.json` (never hand-edit both).
4. Bump `dataset_version` in the JSON, `Settings.dataset_version`
   (`backend/app/core/config.py`) and `AppConstants.datasetVersion`
   (`lib/core/constants.dart`) together.
5. Verify hashes match:
   `Get-FileHash` on both paths.
6. `flutter test` (decoding), `pytest -q`, then search one changed word in the
   running app **and** the API.
7. Commit both files and the version bumps in one commit.

Rollback: git revert of that commit; because ids are stable, no migration is
needed.

---

## 8. AI-generated linguistic data

Never write model output into the dataset unreviewed.

| Stage | Marker | Allowed to ship in JSON? |
|---|---|---|
| raw model output | `meaning_ne_status: ai_draft`, `example.source: ai`, `review_status: ai_generated` | no |
| automated shape/script check passed | `machine_checked` | no |
| a human corrected and approved | `human_reviewed` → `published`, `review_status: approved` | **yes only at this stage** |

Promotion requires a human to read the Nepali, check the sense alignment, and fix
grammar. `quality.alignment_score()` returns a constant 0.5 and is **not** evidence
of quality (`MODEL-CONTRACTS.md` §5).

---

## 9. Private vs public data

| Data | Location | Public? |
|---|---|---|
| Dictionary JSON | repo | yes (ship it) |
| AI prompts / curated phrase DB | repo (`phrases.py`) | yes (no personal data) |
| User favorites | device prefs + Supabase table | **private**, per user |
| Feedback comments | Postgres `feedback` | **private**, review queue |
| Search history | device memory | **private** |
| Provider keys / `.env` | local only | never |

Rules: never copy user feedback text into the dataset verbatim without consent;
strip emails/uids when quoting a report; never commit a DB dump; never add a
user's personal word list to `en_zh_ne.json`.

---

## 10. Growth plan (when the dataset leaves demo size)

1. Target 300–500 headwords at v2, chosen by frequency (a published public
   frequency list, cited) rather than by convenience.
2. Split loading from lookup: cache the parsed index at process start once the
   file exceeds ~1k entries (`services/dataset.py` currently re-reads per request).
3. Add the `reviewed_by` / `source` fields **before** importing batches — adding
   provenance later is unrecoverable.
4. Move the JSON into Postgres for backend reads only after the schema is stable;
   keep the asset as the offline snapshot and keep the version number in sync.
5. Add a checksum line to the release notes so clients can verify which snapshot
   they ship.
