# Project status — Trinity Dictionary (English · 中文 · नेपाली)

_Last updated 2026-11-08. Figures come from `backend/data/build/dictionary.sqlite`
(schema v005) on the development machine._

## What it is

An offline-first trilingual dictionary for Nepali speakers learning Chinese (and
the reverse): Flutter app, a bundled SQLite database, and a FastAPI backend used
only for things the bundle cannot answer.

## Capacity

| Thing | Count |
|---|---|
| Entries (词条) | 123,672 |
| Senses (义项) | 198,306 |
| Dictionary size | 96.1 MB → **43.38 MB** compressed asset |
| HSK-tagged entries | 2,477 |
| Senses with a Nepali gloss | 3,245 (~1.6%) |
| Example sentences | 392 (imported 376 · unverified 15 · quarantined 1) |
| Words carrying a visible example | 375 |
| Licensed images | 77 |
| Words with a bundled picture | 204 |
| Thumbnail bytes | 845,000 B total · 11.2 KB avg · 14,996 B max (0 over 15 KB) |

## Capability and features

* Search by English word, Chinese headword, or pinyin — all offline.
* Sense chips ("Choose a meaning") so a word's senses are separated, each with
  its own English gloss, Chinese + pinyin, and Nepali line.
* Three TTS buttons per page (English, 中文, नेपाली) with a diagnostics screen.
* Bundled pictures with attribution shown on the card and tap-to-enlarge.
* Example sentences gated deterministically; only reviewed/imported rows render,
  bad rows are quarantined with a reason.
* Analyze: paste a paragraph and get trilingual word cards — server first, local
  dictionary fallback, so the screen never dead-ends with "backend not reachable".
* Search box accepts 4,000 characters, truncating longer input with a notice.
* Favorites, search history, popular-word chips, theme / text size settings.
* FastAPI backend: AI enrichment fallback, whole-sentence translation, Nepali
  fill-in, TTS.

## How it works

1. `tools/build_dictionary.py` merges CC-CEDICT and friends into one SQLite file
   (`entries`, `senses`, `examples`, `images`, `concepts`, `corpus_hits`, FTS).
2. `tools/clean_examples.py` runs the example gate (R1–R6) and writes
   `review_status` / `quarantine_reason`.
3. `tools/build_image_index.py` fetches Wikimedia Commons candidates by concept
   (Wikidata P18, titles, sibling propagation), enforces licence/quality rules,
   and writes `images` + `entry_images`.
4. `tools/flatten_thumbs.py` flattens thumbnails (the `assets/` declaration in
   `pubspec.yaml` is not recursive) and marks missing files.
5. `tools/pack_asset.py` gzips deterministically (mtime 0, fixed inner name) into
   `assets/data/dictionary.sqlite.gz`.
6. The app copies that asset into app storage once, guarded by `assetVersion`
   (`lib/data/local/offline_dictionary.dart`), then reads it with `sqflite`.
7. Images resolve **by entry id, then by Chinese headword** — that second key is
   what makes `toy · 玩意` and `book · 书` show a real photo instead of
   "No picture yet".
8. Online, the app falls back to the FastAPI backend for words the bundle lacks
   and for AI translation; offline it stays on the bundle.

## Tests

```
test/image_lookup_test.dart       4 tests passing (image resolution by id and headword)
test/analyze_offline_test.dart    4 tests passing (local analyser, longest-match, budget)
flutter analyze lib test          No issues found
```

Both tests run against the real 96 MB database, so they need
`sqfliteFfiInit(); databaseFactory = databaseFactoryFfi;`.

## Not done yet

* Image coverage: 204 of 123,672 words. Frequency-ordered bulk fetching was
  measured and abandoned (rank order is populated by particles; every run
  accepted ~0 words). The planned route is the reverse: one WDQS query for
  entities that already have P18 plus a Chinese label, then label matching.
* On-demand high-resolution image download and its cache state machine.
* Personalization spec: query-aware sense ranking with `matched: <query>`,
  per-sense example scoring (HSK level, known-word share, domain, length),
  per-sense image selection with three-level fallback, a separate preferences
  database that dictionary updates never overwrite, and a settings toggle
  ("personalize examples").
* Example `review_status` is effectively empty — 376 rows are `imported`, almost
  no `reviewed`; 15 rows still `unverified`.
* Nepali coverage (3,245 senses) and review status for Nepali glosses.

## Repo notes

* `assets/data/dictionary.sqlite.gz` and `backend/data/` build outputs are
  **regenerated**, not committed — rebuild them with the scripts above.
* Nested thumbnail directories left by an older script are ignored; only the
  flat `assets/images/thumbs/*.webp` files are used by the app.
