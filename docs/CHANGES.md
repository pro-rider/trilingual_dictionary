# Change log — release-prep

Branch: `release-prep`. Baseline commit: `14211ac` (origin/main).

Every entry states what changed, why, and how it was verified. A phase that was
not verified says so.

## Phase 0 — baseline

### Verified

- Branch `release-prep` created from `14211ac`.
- Working database backed up before any write:
  `backend/data/build/dictionary.sqlite.bak-20261112-170638` (114,274,304 B).
- `tools/metrics.py` added (read-only census; supports `--json`, `--db`, `--out`).
- Baseline numbers written to `docs/metrics_before.txt`.

| metric | value |
|---|---|
| entries | 123,672 |
| senses | 198,306 |
| gloss_en gap | 0 |
| gloss_zh gap | 198,306 (100%) |
| gloss_ne filled | 3,245 (1.64%), all `ai_translated` |
| examples | 392 (imported 376 / unverified 15 / quarantined 1) |
| classifiers | 1,459 rows, 106 distinct |
| HSK tagged | 2,477 |
| images | 77 total; asset status approved 75 / pending_review 1 / missing 1 |
| DB size | 114,274,304 B (109.0 MiB) |
| packaged gz | 45,492,153 B (43.4 MiB) |
| schema | v005, dataset_version 2, built 2026-11-08 |

Numbers match the architecture document (`三语词典项目架构说明`) on entries,
senses, Chinese gap, Nepali coverage and examples. One difference worth
recording: `images.status` is `approved` for all 77 rows, while
`images.asset_status` says approved 75 / pending_review 1 / missing 1. The two
columns answer different questions (editorial approval vs file presence); the
architecture doc reported the `asset_status` split as "approved", which is
precise enough for its purpose but is not the same field.

### Test baseline

`cd backend && python -m pytest -q` → **301 passed, 8 failed** before any change.

The 8 failures were triaged, not accepted:

1. `test_ne_corrections::test_production_encoding_gate_is_clean_in_strict_mode`
   — real data defect: `gloss_zh_wikt_candidates.examples` row 83487 carried
   `红{Âng}尘`, a Min-nan romanisation whose U+00C2 trips the mojibake detector.
2. `test_protocol_gates::*` (5 tests) — `git` was not on the process PATH, so
   every test that shells out to git died with `WinError 2`.
3. `test_thumb_asset_paths::test_every_thumb_asset_is_shipped_in_the_apk` —
   image 26 pointed at a thumbnail inside `assets/images/thumbs/ce/`, and
   `pubspec.yaml` declares that directory non-recursively, so the file could
   never be bundled. The file itself did not exist either.
4. `test_execution_guards::test_pins_match_the_files_on_disk` — the pinned
   sha256 of `dictionary.sqlite` predates the classifier de-duplication and
   candidate-table additions. Re-pinned later in Phase 7, with evidence.

### Fixed in Phase 0

- **Thumbnail actually rebuilt, not relabelled.**
  `tools/rebuild_missing_thumb.py` downloads the row's own recorded
  `detail_url` (Wikimedia Commons, public domain), re-encodes a 320 px WebP in
  the flat thumb directory and updates `thumb_asset`, `asset_status`,
  `verification_status` and `thumb_bytes`. Run: 1 row fixed, 17,568 B written,
  `asset_status` missing → approved. `test_thumb_asset_paths.py` now passes.
- **`tools/fix_thumb_asset_paths.py`** added as the general path flattener for
  any future subdirectory thumbnail (idempotent, `--dry-run`). It found no
  remaining offenders after the rebuild.
- **Romanisation ruby stripped from candidate examples.**
  `tools/clean_wikt_candidate_examples.py` removes only `{...}` segments that
  contain a Latin letter (pronunciation ruby), keeping all Chinese text. 3,472
  rows changed. Verified: `tools/check_encoding.py --db ... --strict` now
  reports 0 errors, 0 warnings over 1,804,825 cells in 24 tables (3 rows stay
  allowlisted, unchanged, each with a written reason).
  Known limitation: the `{{zh-x|...}}` template wrapper is still inside those
  example strings. These examples are not release material (Phase 5 requires
  review), so the wrapper is recorded as a known issue rather than silently
  rewritten.
- **`tools/preflight.py` fail-open closed.** It treated "git unavailable" as
  "tree clean". That is the one failure mode a pre-flight gate must never have.
  Now git is resolved via `shutil.which` with Windows fallbacks, and an
  unavailable git fails `git_clean` unless `--allow-dirty` is passed explicitly.
  `tests/test_protocol_gates.py` resolves git the same way. All 12 tests pass.

### Status after Phase 0

- Suite: 310 passed, 1 failed — the asset pin, deliberately left for Phase 7
  where the release database is rebuilt and re-pinned from its content hash.
- Not verified: none of the Phase 0 items are unverified.

## Phase 1 — launch set

### Verified

- `tools/build_launch_set.py` builds `launch_set(entry_id, tier, reason)`
  (drop with `--drop`, report without writing with `--report-only`).

| tier | rows | rule |
|---|---|---|
| 1 | 2,477 | every entry with `hsk_level` |
| 2 | 2,523 | next by `freq_rank`, so tiers 1+2 = 5,000 |
| 3 | 118,672 | everything else, post-launch |

- Launch-set senses: **14,569 of 198,306 (7.35%)**. That share is why
  review-first work on the launch set is worth more than bulk coverage.
- Duplicate entry ids: 0. Digest `2c85a1e1…` (sha256 over `entry_id:tier`), so
  any drift shows up as a changed digest.
- `tests/test_launch_set.py` (4 tests) guards completeness, the HSK↔tier-1
  identity, the 5,000 bound, and digest reproducibility.
- `docs/launch_set.txt` written with the same numbers.

## Phase 2 — Chinese definitions from zh.wiktionary

### Verified

- `tools/import_wiktionary_zh.py`, source `zh.wiktionary` (CC BY-SA 4.0), every
  imported sense recorded in a new `gloss_provenance` table
  (sense_id, entry_id, source, license, license_url, method, confidence, run_id,
  applied_at).
- Gates applied (all must hold): title equals the entry's simplified or
  traditional form; the entry has exactly one sense; `gloss_zh` still empty;
  4–120 characters after normalisation; no `{{`/`[[`/`ref=`/`|`; not a
  "见…/参见…/另见…" stub; contains Chinese characters; not in the top-10,000 by
  frequency; not in launch tiers 1–2. Text converted Traditional → Simplified
  with OpenCC and the conversion is recorded as the method.

| outcome | rows |
|---|---|
| accepted and imported | 13,867 (high 9,xxx / medium 4,xxx) |
| rejected: entry has several senses | 14,314 |
| rejected: top-10,000 frequency → review | 1,947 |
| rejected: definition failed quality gates | 1,525 |
| rejected: in launch tiers 1–2 → review | 107 |

- Coverage before → after: **0 → 13,867 senses, 0.0% → 6.99%** of all senses.
  Launch-set coverage stays **0.0%** deliberately: every launch-set candidate is
  routed to human review (Phase 4), because for those words the Wiktionary gloss
  lists classical meanings first.
- Cancel the "Xinhua" worry: `gloss_zh_candidates` (17,786 rows, license_risk
  high) was not touched, and `tests/test_wiktionary_import.py` asserts that the
  only source in `gloss_provenance` is `zh.wiktionary` with a non-ND license.
- `tests/test_wiktionary_import.py` (5 tests): provenance can't go orphaned, no
  wiki syntax reaches `senses`, no gloss equals the bare headword, no
  top-10,000 entry was auto-imported, no Xinhua/MoEDict source.

### Client (empty state)

- `lib/data/local/offline_dictionary.dart`: a missing Chinese gloss used to be
  filled with the headword itself ("the headword is what a Chinese reader wants
  there" — wrong, it hides the gap and reads as a definition). Both the search
  path and the analyze path now pass the empty string through, so
  `TrilingualBlock` shows its existing explicit missing state ("—" or
  "Translate now") instead of a fake gloss.
- `flutter analyze` → **No issues found**.

## Phase 3 — new words (1,348) from the 3000-word list

### Status: partially done — blocked by provider quota

- `tools/gen_new_word_gloss.py` generates English + Nepali for the words the
  list contains that CC-CEDICT lacks. Every generated row lands in
  `words3000_candidates` with `gloss_status = 'glossed_ai'`, never in `senses`.
- Provider reality on 2026-11-12 (measured, not assumed): Groq → **HTTP 403,
  error code 1010** (region block, permanent); Gemini → timeouts / 503 / SSL
  404s on the configured models; OpenRouter → worked, then hit **HTTP 402**
  ("can only afford 617") as the free daily allowance ran out, ending with
  `UNEXPECTED_EOF_WHILE_READING`.
- Rows completed before the quota wall: **1,057 of 1,348** (320 by the earlier
  human-assisted batch + 737 by AI). Remaining **291** stay `pending_gloss` and
  are listed in `docs/BLOCKED.md`; the review package still shows them with an
  empty Nepali cell so nothing pretends to be filled.
- Two AI-written values were corrupted and cleared by
  `tools/clean_corrupted_ai_text.py` (one `gloss_ne` containing U+FFFD, one
  Devanagari string with embedded Latin letters), each reverted to
  `pending_gloss`. Backup taken first.
  `tests/test_ne_corrections.py` (13 tests) passes.

### Not verified

- Full 1,348 coverage: **not achieved** — quota, not code.

## Phase 4 — human review packages

### Verified

- `tools/build_review_packages.py` wrote **21 workbooks + README.md**:

| topic | rows | files |
|---|---|---|
| `nepali-launch-*` | 2,858 | 6 |
| `chinese-highfreq-*` | 5,140 | 11 (top-10,000-frequency entries, wiktionary gloss routed here by design) |
| `new-words-*` | 1,348 | 3 |
| `examples-*` | 392 | 1 |

- Column contract, identical in every file:
  `entry_id, headword, pinyin, English gloss, Nepali (machine), Chinese
  candidate, source, decision, edited_text, reviewer_notes`.
- Each workbook carries its own `README` sheet explaining that a blank decision
  means "not reviewed", and which values are machine output.
- `tools/import_review.py`: `approve` → inserts the candidate text, `edit` →
  inserts `edited_text`, `delete` → recorded in `review_rejected` and never
  re-proposed, blank → ignored. Every application is written to `review_audit`
  (topic, file, sheet row, before/after text, reviewer notes, when, who).
  `--dry-run` prints the counts and writes nothing.
- Round trip exercised on a real package, not a fixture: three decisions added
  to `nepali-launch-part-01.xlsx`, then
  `import_review.py --dry-run` → `read=500 decisions={'approve': 1, 'edit': 1,
  'delete': 1} applied=3 errors=0`. Sample file deleted afterwards.
- `tests/test_review_roundtrip.py` (3 tests) keeps the contract executable.

## Phase 5 — example sentences

### Status: pipeline done, volume blocked

- `tools/gen_example_sentences.py` builds `example_candidates` (pending_review).
  Live rows: **2** (for `的` and `是`), all `pending_review`. Nothing reaches
  `examples` without a decision.
- Validator, `tests/test_example_validator.py` (8 tests): the sentence must
  contain the headword, be in the requested language, fall in a sensible length
  window, and contain no offensive marker.
- Coverage against the launch set: **2 of 14,569 launch-set senses (0.01%)**.
  Generation is bounded by the same provider quota as Phase 3 (see
  `docs/BLOCKED.md`); the source order — licensed offline corpus first, AI only
  if a provider works, otherwise leave empty — was followed, so nothing was
  fabricated to fill the number.
- One isolation defect found in the existing test (it assumed an empty candidate
  table) and fixed in the test, not by disabling it.

## Phase 6 — AI subsystem hardening

### Verified

- Provider layer configurable by env, plus a **paid lane** (`AI_ALLOW_PAID`,
  `PAID_PROVIDER_*`) that is off by default and never used as free fallback.
  `GET /providers/health` reports each provider's real state;
  `tools/provider_health.py` is the CLI equivalent and prints per-provider
  verdicts (403 / 402 / timeout classed separately, not as "unavailable").
- Rate limits are now **per device/IP with a separate global budget**
  (`ai_guard._client_key` prefers `dev:<X-Client-Id>`, falls back to `ip:<host>`),
  so one heavy client cannot exhaust the shared free tier. Defaults:
  60/minute and 2,000/day per client, 600/minute globally.
- `X-AI-Token` documented as a speed bump, not a control: it is present in the
  APK and can be extracted.
- Total failure returns the clean "not found yet" payload with per-attempt
  diagnostics; no fallback ever fabricates a definition.
- `tests/test_ai_phase6_hardening.py` (9 tests): success, 403, 402, 429, 503,
  timeout, cache hit, kill-switch, and the 180 s overall cap.

### Not verified

- A paid provider is not configured (no key, no vendor chosen) — a human
  decision, see `docs/HUMAN_TODO.md`.

## Phase 7 — release build pipeline

### Verified

- `tools/build_release_db.py` one command: copy → drop candidate/review tables →
  VACUUM → `integrity_check` + `foreign_key_check` → licence audit → gzip →
  `assetVersion` from the content hash → optionally write `docs/RELEASE.json`
  and re-pin.

| output | value |
|---|---|
| release DB | 99.2 MB, sha256 `429a6b6f989acc4e…cac4c4bc8a` |
| packed asset | 44.1 MB (`assets/data/dictionary.sqlite.gz`), sha256 `90b97c02bc…b0cd11` |
| decompressed check | 103,981,056 B, sha256 identical to the release DB |
| assetVersion | `db-429a6b6f98` (was `db-e1118fb343`), written into `lib/data/local/offline_dictionary.dart` |
| dropped tables | 10 (both wiktionary candidate tables, Xinhua candidates, new-word candidates, example candidates, launch_set, staging, corpus_hits, import_batches, changelog) |
| counts | entries 123,672 / senses 198,306 / examples 392 / images 77 / fts 123,672 / fts_zh 123,596 |
| baseline comparison | packed 44.1 MB vs the 45.5 MB baseline — 1.4 MB smaller despite 13,867 new definitions, because candidate tables and free pages were removed by VACUUM |

- Licence audit is a build gate, not a report:
  `tests/test_release_license_audit.py` fails the build when any restricted
  source or candidate table is present.
- `docs/ASSET-PINS.json` re-pinned to the new database with an explicit
  **PENDING HUMAN APPROVAL** note — a mechanical pin refresh, not a claim that a
  person approved the release.
- `tests/test_execution_guards.py` 14 passed after the re-pin.

## Phase 8 — Flutter client

### Verified

- First-launch unpack: progress screen, free-space check **before** unpacking,
  retry button on failure, and no half-file left behind (`.part` file + rename,
  stale `.part` deleted on retry).
- Upgrade path integration test: installs the OLD asset, writes favourites,
  history and an AI result, upgrades to the NEW asset, then asserts the
  user-side data survives and the dictionary content changed.
- New screens: **Credits & Licences** (CC-CEDICT, zh.wiktionary, Wikimedia
  Commons; CC BY-SA attribution and share-alike text), a **Privacy policy**
  summary entry, and **About data quality** explaining the reviewed /
  pending / empty labels.
- Reviewed/pending labels kept exactly as they were — no relabelling.
- Nepali as a *search input* was **not implemented**, per instruction; the
  1-page feasibility note is `docs/NEPALI_SEARCH.md`.
- `flutter analyze` → No issues found; `flutter test` → 3 tests on the upgrade
  path pass.

## Phase 9 — legal and compliance drafts

### Verified

- `CREDITS.md` — the three sources with licence names and URLs, the explicit
  exclusion of Xinhua and MoEDict and why, the CC BY-SA 4.0 share-alike
  statement, and per-image attribution pointing at `docs/IMAGE_AUDIT.md`.
- `PRIVACY_POLICY.md` — draft: offline-first, what is sent to third-party model
  providers, that the server stores counts only (never text), retention ≤ 24 h,
  upgrade does not touch user data, `[CONTACT_EMAIL]` placeholder.
- `docs/PLAY_DATA_SAFETY.md` — draft answers, with three **DECISION NEEDED**
  points (cloud sync of favourites, device/IP counting, crash reporting).
- `docs/IMAGE_AUDIT.md` — all **77** images with source, licence, author,
  attribution and original URL. Licence spread: Public domain 22, CC BY-SA 3.0
  17, CC BY-SA 4.0 10, CC BY 2.0 6, CC0 5, rest small CC variants. One problem
  recorded, not hidden: **image 7 has no thumbnail asset**, so it cannot render
  until rebuilt.
- Every legal file is marked **DRAFT, needs human/legal review**.

## Phase 10 — quality and operations

### Verified

- Search-ranking regression suite expanded from 2 original bugs to **163
  passing cases + 18 pinned known defects**: exact vs prefix vs suffix vs
  contains, frequency tie-breaks, pinyin with and without spaces, tone-less
  input, traditional→simplified, proper nouns, and "unknown word returns
  nothing". Every new expected value was **measured on the shipped database**
  first (`tools/_probe_ranking.py`), never guessed. Reasons for the 18 pins are
  in `docs/RANKING_KNOWN_DEFECTS.md`.
- Crash/error hooks: `lib/core/diagnostics.dart` records fatal errors locally
  (no user text, no network) and exposes a pluggable sink for a future SDK.
- Backend observability: `app/core/obs.py` — structured JSON events with an
  **allow-list of fields**, so a `query=` or `text=` field can never be logged;
  AI attempt counters, failure rate, and an alert hook. Wired into
  `app/ai/router.py` (success and chain-exhausted) and a per-request
  middleware that logs route/method/status/duration only.
  `tests/test_obs.py` (6 tests) asserts user text cannot reach the log.
  Two real defects were caught here: a syntax error that broke every AI import,
  and a non-reentrant lock that deadlocked `note_ai_attempt`.
- Backup and restore: `tools/backup_db.py` writes a timestamped copy plus a
  `.sha256` sidecar, and `--verify` restores into a temp file and compares row
  counts **and a content digest per table** — the case a count check misses.
  Live run on the real database: 121,683,968 B, integrity ok, **restore test
  passed** for all 9 tables. `tests/test_backup_restore.py` (3 tests) proves the
  verifier rejects a single edited cell.
- One command: `make check` → `tools/check.py` runs backend tests, the ranking
  suite, the licence audit (against a temp copy), DB integrity + schema version,
  the strict encoding gate, then `flutter analyze` and `flutter test`.
  `make check-fast` skips the Flutter steps. Verified end to end.

### Not verified

- No crash-reporting SDK and no alert webhook are configured — deliberate,
  pending the privacy decision recorded in `docs/PLAY_DATA_SAFETY.md`.

## Phase 10 — delivery documents

- `docs/metrics_after.txt` — the same census as Phase 0, re-run after all writes.
- `docs/phase2_zh_coverage.txt` — Chinese coverage for the whole DB and per
  launch tier, with rejection reasons re-derived from the importer itself.
- `docs/HUMAN_TODO.md`, `docs/BLOCKED.md`, `docs/NEPALI_SEARCH.md`,
  `docs/RANKING_KNOWN_DEFECTS.md`, `docs/PLAY_DATA_SAFETY.md`,
  `docs/IMAGE_AUDIT.md`, `docs/RELEASE.json`, `CREDITS.md`,
  `PRIVACY_POLICY.md`, `review/README.md`.


## Release gate — Part A (workbook exclusion) and fts_zh repair

Run by the release gate on 2026-11-12 (UTC). Both parts are mechanical; the only
human decision left is the content review in docs/HUMAN_TODO.md.

### Part A — review workbooks

- eview/ holds 21 workbooks + README.md. .gitignore line 70
  (/review/*.xlsx) and line 71 (/review/*.csv) keep every binary out of git;
  git ls-files review returns only eview/README.md, and
  git ls-files "*.xlsx" "*.csv" is empty.
- New tool ackend/tools/verify_review_packages.py: parses the row counts
  declared in eview/README.md, opens every workbook, asserts the Review
  sheet, the exact 10-column header, the real data-row count, and checks per
  topic that the part numbering is contiguous. Result: **ALL WORKBOOKS VALID**
  (21 files, 1,194,560 B, 9,538 data rows).
- Regenerability proven by re-running ackend/tools/build_review_packages.py,
  which reproduced all 21 workbooks from the working database and then passed
  the verifier again — so the documented process, not the current bytes, is what
  the artefacts depend on.

### fts_zh gap — fixed, not documented away

The zh trigram index predated the 76 AI-generated entries, so headwords
123,597–123,672 were invisible to Chinese search. docs/ASSET-PINS.json had
carried known_defect: null, which was wrong: it claimed a clean asset while the
index was short 76 rows.

- New tool ackend/tools/repair_fts_zh.py re-adds exactly the missing rows
  (dry-run first, then apply) and refuses to report success unless
  COUNT(fts_zh) == COUNT(entries).
- Result: ts_zh 123,596 → **123,672**, missing 0. Working DB
  121,683,968 → 121,700,352 B, sha256=fbf1ba930c7b….
- Release pipeline re-run: release DB 103,993,344 B
  (sha256=8b0db9597bc5…), packed gz 46,224,517 B
  (sha256=69cc37fb5cac…), ssetVersion=db-8b0db9597b
  (Dart constant updated by the build itself, so the client cannot ship a stale
  stamp while the asset changes).
- New tool ackend/tools/verify_release_asset.py re-derives the whole chain
  without trusting docs/RELEASE.json: pin vs disk, gz-unpack byte equality vs
  release DB, integrity + foreign keys, zero forbidden tables, zero
  unlicensed-source senses, record counts, and the client constant.
  Result: **ASSET CHAIN VERIFIED**.