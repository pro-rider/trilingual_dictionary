# Issue register — open items only

Resolved work is not listed here; it lives in the acceptance reports. An entry
leaves this file only when it is closed with evidence, or is explicitly
superseded by a decision. Severity: **High** (user-visible or blocks a gate),
**Medium** (evidence or process gap), **Low** (hygiene).

| id | severity | item | state | owner gate | evidence / next step |
| --- | --- | --- | --- | --- | --- |
| S-01 | High | `sentence_section.dart` still shows the legacy sense badge; the repository is not consumed yet | open | Phase 1.5 §9 | `lib/features/search/widgets/sentence_section.dart`; repository + 13 Dart tests ready, wiring not started |
| S-02 | High | Shipped `dictionary.sqlite` has 76 missing `fts_zh` ids (123,597–123,672) | awaiting approval | asset replacement (§5) | `tools/validate_fts.py` exit 1; asset pinned in `docs/ASSET-PINS.json`; untouched |
| S-03 | High | 5 values are `intra_token_mix` and are not yet in `quarantine_records` | **go/no-go pending** | Phase 1.5 §2 | `tools/classify_script_mix.py`: sense 59001, 66092, 112935, 112963, 170710 |
| S-04 | Medium | Remote CI has never run: workflow committed, not executed on GitHub | open — **cannot be closed from this machine** | CI | no `gh` CLI; API returns 404 (private repo). Needs a run on the pushed sha by whoever holds repo access |
| S-05 | Medium | Legacy provenance stops at "written by the AI enrichment script" (no model, prompt, validation, review) | open, unfixable | — | `data/build/dictionary.sqlite.enrich.report.json` (100/75), single `ai_cache` row |
| S-06 | Medium | POS source undecided; CC-CEDICT `CL:`/`surname` labels are not a POS dataset | open | user decision | contract §7; nothing backfilled |
| S-07 | Medium | HSK standard/source/version/licence undecided; 2,477 HSK rows overlap the 3,245 Nepali rows | open | user decision | contract §8; counts in `docs/PHASE2.1-COUNTS.md` |
| S-08 | Medium | 40 shared Nepali values across different glosses unclassified | open | Phase 1.5 §4 | needs the shared-translation investigation |
| S-09 | Low | The 2 legitimate `foreign_token` strings have no attribution note yet | open | Phase 1.5 | keep visible; add source note when provenance UI lands |
| S-10 | Low | Old nested thumbs directories still on disk (`a2 a8 …`) | open | hygiene | gitignored, not referenced |
| S-11 | Low | `ApiConfig.baseUrl` defaults to `127.0.0.1:8000`; the Analyze page waits 25 s before failing on a real device | open | Phase 3 pre-work | not a Phase 2.1 blocker |

Closed in this phase (traceability lines): empty-store production migration (3,245
rows imported and verified), row-count-only restore checks (content fingerprint
v1), soft FTS completeness (exact-ID gate), non-atomic import (`BEGIN IMMEDIATE`),
unauditable rollback (batch-scoped + audit-preserving), Python-only golden vectors
(shared and CI-gated), concurrency "deferred" (single-writer, tested), and
"hard stop is advisory" (gates now run inside the test suite, plus an asset pin).
