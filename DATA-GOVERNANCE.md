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
cd backend
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

---

## 11. Stage 2 build — merged SQLite dictionary (2026‑11‑07, measured)

The first real build exists: `backend/tools/build_dictionary.py` turns CC-CEDICT
into a normalised SQLite database. Every number below came from an actual run,
not an estimate.

```powershell
cd backend
.venv\Scripts\python.exe tools\build_dictionary.py `
  --cedict data\raw\cedict.txt.gz `
  --out data\build\dictionary.sqlite
```

| Measured | Value |
|---|---|
| Source lines parsed | 125,379 (0 malformed, 30 comment lines) |
| **Entries** (simplified + traditional + tone-less pinyin) | **123,596** |
| Senses | 198,230 (1.60 per entry) |
| Unique simplified / traditional / pinyin | 121,612 / 122,799 / 86,981 |
| Duplicate keys after merge | **0** |
| Empty glosses | 0 |
| Build time | 7.5 s (parse 0.9 s) |
| DB size / gzip size | 93.9 MB / 42.6 MB |
| FTS5 trigram available | yes (substring search works) |

Category coverage of the 10 requested buckets (rule-based keyword match on the
English gloss; unmatched stays `general` and is never hidden):

| Category | Entries | Category | Entries |
|---|---|---|---|
| general (unmatched) | 74,588 | nature | 4,761 |
| everyday | 9,410 | business | 3,463 |
| people_society | 6,923 | technology | 3,064 |
| geography_environment | 6,142 | science_medicine | 2,823 |
| language | 6,093 | tools_instruments | 1,025 |
| transport | 5,304 | | |

Flags: `is_proper` 17,060 (names kept out of default results), `is_chengyu`
5,169, `is_classifier` 85 (curated list of measure words), classifier rows 2,325.

**De-duplication rule (this is the answer to "don't extract the same word
twice"):** an entry is the triple (simplified, traditional, tone-less pinyin).
Lines from any source that agree on all three merge into one entry; their glosses
are appended and exact duplicates dropped in case-insensitive comparison. Different
readings of one character (行 xíng vs 行 háng) stay as separate entries because
pinyin differs — that is a second word, not a duplicate. Running the same rule with
more sources added cannot produce duplicate entries; it can only add senses.

**Known limits of this build (stated, not hidden):**

- Chinese-side definitions (`senses.gloss_zh`) and Nepali (`gloss_ne`) are empty —
  CC-CEDICT ships English glosses only. `ne_status = 'none'` for every row.
- `rarity` / `freq_rank` / `hsk_level` are NULL: no frequency list is imported yet,
  so nothing is filtered out of default results.
- `characters` table is empty (Unihan stage not run).
- No examples yet (Tatoeba stage not run).
- Category rules are keyword-based, so 60% fall into `general`; that is a
  coverage figure, not a failure — those entries are still searchable.

**Nepali translation budget, measured from this DB** (the Prompt‑4 run): 198,230
senses, 805,499 English gloss words → ≈6.04 M input + 1.29 M output tokens,
≈9,912 requests at 20 senses per request. Cost: **≈$2.6 on a cheap flash-class
model, ≈$28 on GPT-class pricing**. This must be run after the Chinese definitions
are filled, otherwise sense selection happens without context.

---

## 12. Image pipeline (Prompt 38–46): what is built, what is measured

**Code:** `backend/tools/fetch_images.py` (collect → licence gate → quality gate →
match → store) and `GET /api/v1/images`, `/api/v1/images/batch`.

**Sources wired:** Wikimedia Commons only (MediaWiki API, official endpoint,
descriptive User-Agent, retry with exponential backoff on 429/503). The `Source`
interface exists so Wikidata/Openverse/Flickr/Open-Images plugins can be added
without touching the pipeline. No scraper for a platform whose terms forbid it.

**Licence gate (measured on real calls):** allow-list `CC0 | Public domain |
CC BY | CC BY-SA`; NC / ND / unknown / missing author are rejected with a stored
reason. The licence is read from the source's own `extmetadata`, not from a cache.
Because attribution is mandatory under CC BY / CC BY-SA, an image whose author
cannot be resolved is rejected even when the licence itself is fine.

**Quality gate implemented:** mime ∈ jpeg/png/webp, width ≥ 400 px, aspect ratio
0.4–2.5, dimensions present. **Not implemented and explicitly reported as
`not_run` in `data/images/report.json`:** watermark/text-overlay detection,
blur/contrast scoring, NSFW/violence classifier, identifiable-person detection,
CLIP relevance scoring, pHash near-duplicate removal. These need vision models;
pretending otherwise would ship unverified pictures.

**Matching — the honest result.** Four high-confidence tiers were specified
(QID → Wikipedia langlinks → WordNet/CLIP). Only one is built: *Wikipedia
article lead image* (`pageimages` + Commons `extmetadata`), with the article
title required to equal the term. A looser Commons file-title search exists
behind `--allow-commons` but is off by default, because measurement showed it
produces nonsense at dictionary scale: with title search on, `干巴巴 / dry`
matched a village sign and `中辣 / hot` matched a hot-air balloon. Requiring an
exact article title raises precision and cuts yield — which is the correct
trade: no image is better than a wrong image for a learner.

**Yield observed (60-word probe, `--limit 60`, exact-title mode):** 5 entries got
an approved image (≈8%) because the probe starts from the shortest glosses,
which are mostly abstract (`two`, `dry`, `ace`). Concrete-noun categories must be
walked separately (`--category nature`, `--category everyday`) for usable
coverage. Every accepted row stores `match_method` + `confidence` (0.85 for the
article tier) so a wrong picture is identifiable later.

**Storage:** 800 px detail + 256 px thumb, both requested from the source's own
thumbnailer (no local resizing, no Pillow dependency), named by sha1 of
(source URL + word), written under `backend/data/images/<2 hex>/`. Never bundled
in the app: the app gets URLs. Measured: 5 images ≈ 3.5 MB, i.e. ~0.7 MB/entry
at both sizes — 5 M images at these sizes is ≈500 GB at the 800 px tier and
≈100 GB for thumbs alone, matching the budget in the plan. This is why the CDN
step (R2/B2/Supabase) and the slim 200k-row image index for the app are still
open items, not done.

**Schema (created by the pipeline, SQLite side only):** `images`, `entry_images`,
`best_image_per_entry` view, indexes on `(entry_id, rank)` and `content_hash`.
Postgres-side schema, `review_queue`, `missing_image_requests`, migration
versioning and VACUUM reporting are **not built**.

**Serving:** `GET /api/v1/images?entry_id=` returns best image + attribution +
licence + up to 5 ranked items, and a `category` icon key when the entry has no
picture (no error). Verified live: `zh4360` → thumb 80,308 bytes, licence
`CC BY-SA 3.0`, attribution
`Modern_bra_fullcup.jpg — Steifer with help of Gytha — CC BY-SA 3.0 via Wikimedia Commons`; unknown entry returns `items: []` + `icon` rather than a 404.
Batch endpoint accepts ≤50 ids. Redis caching and CDN cache headers are open.

**Client behaviour:** image loads after the meaning, never before it; shimmer
while decoding, fade-in on first frame, tap-to-open viewer with `InteractiveViewer`
zoom, attribution + licence + confidence line under the image, and a per-category
material icon when there is none. The 300 MB LRU disk cache, prefetch of the first
10 results, and the offline image index are **not** implemented — Flutter's default
in-memory image cache is what runs today.

---

## 13. HSK5 word list + HSK5 past paper (2026‑11‑08, measured)

Two teacher-supplied PDFs were imported into the merged database. Neither PDF is
committed (course material); the tools and the extracted exam corpus are.

### 13.1 `新HSK5词汇表（汉英）.pdf` → `backend/tools/import_hsk5.py`

Layout is three columns per entry: `N．` / pinyin / headword. `pypdf` extracts the
text in stream order, so the parser reads three lines per record. Measured:

| Fact | Value |
|---|---|
| Pages / extractable text | 39 / yes (≈1,067 chars per page) |
| Numbered records in the PDF | 2,500 |
| Records parsed | **2,499** (`2499`+`2473` unique headwords) |
| Source typo | No. 321 is written twice (331 missing), `大夫` repeated — not fixed, reported |
| English glosses in the PDF | **none** — the file has pinyin + characters only, "汉英" describes the list, not its content |
| Headwords already in CC‑CEDICT | **2,499 of 2,499** |
| New entries created | **0** — the import tags + translates, it does not duplicate |
| Entries tagged `hsk_level = 5` | **2,477** |
| Nepali glosses written | **2,370** (`ne_failed = 33`, rerunnable) |
| Senses translated | 2,403 (primary sense only) |
| Runtime | **313.8 s** (`--batch 30 --threads 4`) |

Rules baked into the tool: pinyin is matched tone-exact after converting tone
marks to numerals (`ü`→`v`), so multi-reading characters resolve to the right
entry (`大夫 dàfū` vs `dàifu`, `绿 lǜ` vs `lù`, `得 dé` vs `děi`). `--all-senses`
translates every sense instead of `sense_order = 0` (≈7,447 rows, ≈2 h).

### 13.2 `H51007.pdf` (HSK5 past paper) → `backend/tools/import_exam_words.py`

The PDF is a scan: `extract_text()` returns 0 characters, and this machine has
no Chinese OCR model (`tesseract` is installed with `eng`/`osd` only; the
`chi_sim` download failed). So the **reading passages were transcribed by hand**
into `backend/data/exam/h51007_passages.txt` (~20 paragraphs: 顾恺之画母, 宠物安全,
匆忙生活, 沉默是金, 平遥古城, 百家姓, 孔明灯, 葡萄干, 河流走弯路, 茶的历史, …) — that
directory is gitignored, since the passages are copyrighted course material. The
listening sections (Q1–45) are multiple-choice options and were ignored on purpose;
the handwriting section (Q91–98) and the essay prompts (Q99–100) contributed word
lists only.

`jieba` splits the corpus, keeps tokens of ≥2 CJK characters, drops a stop-word
list, then:

| Stage | Result |
|---|---|
| Distinct tokens | 762 |
| Already in the dictionary | 634 → recorded in `corpus_hits` (provenance) |
| Not found | 128 |
| Created as new entries | **76** (e.g. 刮目相看, 孔明灯, 葡萄干, 平遥, 九霄云外) |
| Rejected as segmentation fragments | **43** (`要笔`, `画张`, `两天`, …) — the model is asked for `is_word` and answers `false` |
| Nepali glosses added | **346** |
| Runtime | **86.7 s** |

### 13.3 State of the database after both imports

| Measured | Value |
|---|---|
| Entries | **123,672** (was 123,596) |
| Senses | 198,306 |
| `hsk_level = 5` entries | 2,477 |
| Senses with `gloss_ne` | 3,032 / 198,306 |
| `corpus_hits` rows (word → source text) | 710 |

Live checks after both imports (`POST /api/v1/search`): `安排` → zh31619, `to arrange`,
`व्यवस्था गर्नु`, `source = dictionary`; `葡萄干` → `raisin`, `किशमिश`; `孔明灯` →
`sky lantern`, `आकाश बल्ब`; English `arrange` → 安排, `raisin` → 葡萄干.

**Cost note:** every AI-generated gloss sits in `senses.gloss_ne` with
`ne_status = 'pending'`, so the client labels it unverified. The 33 missing HSK5
translations are blank rows, not bad data — rerun the tool to fill them.

**Rebuild warning:** `tools/build_dictionary.py` recreates the schema from CC‑CEDICT
and therefore drops `hsk_level`, `ai_cache` and `corpus_hits`. After a rebuild,
rerun `import_hsk5.py`, `import_exam_words.py` and re-warm `ai_cache`.

## 14. Nepali + example-sentence coverage (2026‑11‑08, measured)

CC-CEDICT ships Chinese + English only, so after the Stage 2 build the
database had `gloss_zh` 0 / 198,306, `gloss_ne` 3,032 / 198,306 and
`examples` 0 rows. That is why the phone showed an empty पिंक 中文 box and an
empty नेपाली box for almost every word.

Two mechanisms fill them, and neither one invents text:

1. **On demand (live, free).** `POST /api/v1/dictionary/enrich` → the app writes
   `gloss_ne` + one trilingual example into its own copy of the database
   (`offline_dictionary.enrich`). Verified on the phone: Nepal → नेपाली
   "हिमालयको देश" + 3-language sentence, China → "चीन देश" + sentence. Second
   lookup is served from disk, offline included.
2. **Bulk (background).** `backend/tools/enrich_dictionary.py` walks every sense
   that still needs work and writes it back into `dictionary.sqlite`, so a
   rebuilt asset ships pre-filled.

Measured bulk throughput: **batch 25, threads 6 → 0.4 senses/s** (75 of 100 in
174 s), limited by free-tier Gemini HTTP 429, not by our code. At that rate
195,274 pending senses ≈ 135 h; `--primary-only` cuts it to 123,672 ≈ 85 h. So
bulk is an overnight/overnight×n job, not a 10-minute one — run it when the
machine can stay awake:

```powershell
cd ...\backend
.venv\Scripts\python.exe tools\enrich_dictionary.py --db data\build\dictionary.sqlite --dry-run
.venv\Scripts\python.exe tools\enrich_dictionary.py --db data\build\dictionary.sqlite --primary-only --batch 25 --threads 6
```

It is resumable (only empty senses are selected) and writes progress to
`dictionary.sqlite.enrich.report.json` every minute. `ne_status` is set to
`ai_translated` (never `reviewed`), so machine output stays distinguishable
from reviewed entries.

English lookup correctness (the "Nepal → 白眶雀鹛" class of bug): the glossary
score in `backend/app/services/sqlite_dataset.py::_gloss_score` and its Dart
twin in `lib/data/local/offline_dictionary.dart` both refuse a match inside a
parenthetical, fetch every singular/plural form, and tie-break by main sense,
non-proper, HSK, then the shortest gloss and shortest headword. Regression
tests: `test/offline_dictionary_test.dart` (Nepal→尼泊尔, China→中国,
behaviors→"behavior").

### 14.1 Why "water" used to open on a surname (2026‑11‑08, second pass)

Three data-shape problems were fixed, and each is now a repeatable tool run
rather than a hand edit:

1. **Sense 0 was not the main meaning.** CC-CEDICT frequently lists
   `surname Shui` (水), `abbr. for …` (书), `variant of …` (那) or a brand
   (`Apple (American tech company)` for 苹果) as sense 0, so opening a word
   showed the surname. `backend/tools/reorder_senses.py` demotes those senses
   to the end of the entry (temporary negative range first, so the
   `(entry_id, sense_order)` unique index cannot collide). It touched
   **1,353 entries / 1,523 senses** and is idempotent (second run: 0 / 0).
   `sense_id` never changes, so Nepali glosses and examples stay on their sense.
2. **Headword frequency was missing.** Without it `四大 #4,622` beat `水 #653`
   and `册 #4,264` beat `书 #539`. `backend/tools/add_frequency.py` fills
   `entries.freq_rank` from `wordfreq` (MIT): 116,533 / 123,672 entries in 3.8 s.
3. **Scoring ranked phrases over words.** `middle age` counted as a hit for
   `middle`, `in total there are …` for `in total`. A segment that merely
   *starts with* the query now scores 60 (same as one that ends with it) instead
   of 90, so a real definition (100) or an exact later alternative (85) wins.

Final rank order, identical in both implementations:
`(score_tier, sense_order, freq_rank IS NULL, freq_rank, len(gloss), len(headword), entry_id)`.

Self-check tool `backend/tools/audit_roundtrip.py` takes each HSK5 word's own
first English gloss as a query and requires the lookup to lead back to that
word: **2,273 queries, 1,584 exact (69.7%)**. Mismatches are mostly harmless
synonyms (`one` → 一个, `before` → 之前), so the number is a regression gauge
that must not decrease. Report: `backend/data/build/audit.roundtrip.json`.

Known remaining defects (documented, not fixed): a rare-but-valid compound can
still win when its sense 0 is an exact match (`worse` → 禽兽不如,
`mice` → 会奖旅游/MICE tourism), and a very frequent single character carrying
an obscure sense can beat the everyday word (`beautiful` → 那). Both need
curated overrides, which is the natural next data task.