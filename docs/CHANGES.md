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

