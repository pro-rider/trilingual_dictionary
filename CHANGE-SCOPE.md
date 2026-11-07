# CHANGE-SCOPE.md — Modification Boundaries & Change Control

This file answers one question before any edit: **how much am I allowed to touch?**
The default answer is "the least that fixes the stated problem, in the layer where
the problem actually lives".

Non-negotiables:

1. One problem per change. No drive-by refactors, renames, or formatting sweeps.
2. No silent behaviour changes. If behaviour must change, say so and update docs.
3. Existing public contracts (HTTP shapes, provider names, file layout) survive
   unless the task explicitly changes them.
4. Anything architectural (new layer, new dependency, storage redesign, auth
   redesign) needs written approval **before** code.

---

## 1. Change classification

| Class | Examples | Approval | Review |
|---|---|---|---|
| **Trivial** | typo, log text, copy, one constant, this document | none | none |
| **Local** | fix one widget, one prompt line, one stopword, one test | none | 1 reviewer |
| **Feature-local** | new screen for an existing feature, new settings row, new endpoint following an existing pattern | none, but state the plan first | 1 reviewer |
| **Cross-cutting** | change wire format, change a provider's type, touch >3 features, change navigation table | **required** | 2 reviewers |
| **Architectural** | new layer, new dependency with native code, replace state management or router, move to a different DB, on-device model | **required (written)** | 2 reviewers + doc update |

---

## 2. Required sequence for any code change

1. **Locate** — reproduce/observe the problem. For a bug: exact file, exact line,
   exact input. For a feature: which existing pattern it follows.
2. **Read** the target file and grep every call site of the symbol you intend to
   touch (`IMPACT-MAP.md` §3 lists the co-change pairs).
3. **Decide the minimum diff**: the smallest set of files that makes the stated
   behaviour correct. Write it down (2–4 bullets) before editing.
4. **Change only that.** If you discover an unrelated defect on the way, note it
   (issue/`AGENTS.md` §9) — do not fix it in this change.
5. **Verify** — `flutter analyze`, `flutter test`, `pytest`, plus the specific
   manual check for the touched area (`IMPACT-MAP.md` §4).
6. **Document** — update the one contract document whose subject you changed.
7. **Report** — files, why, verified, not verified.

---

## 3. Boundaries per area

### 3.1 Flutter UI (`lib/features/**`, `lib/app/**`)

Allowed: fix layout, overflow, contrast, copy, empty states, error text; add a
widget inside an existing screen; add a settings row for an **existing** setting.

Not allowed without approval: new global theme, new color palette, reordering the
home layout, removing any screen/route, changing the smart-routing rule
(`_shouldAnalyze`), converting `MaterialApp.router` to `MaterialApp`.

Hard rules: no new `Color(0xFF…)` literals where a `LanguageColors` value exists;
layout must not overflow at `textScale = 1.4`; no `Navigator.pushNamed`.

### 3.2 Riverpod (`**/*_provider.dart`, `lib/data/providers.dart`)

Allowed: fix a provider body, add a derived provider, add a field to `AppSettings`
(+ `copyWith` + setter + UI).

Not allowed: change a provider's *type* (e.g. `FutureProvider` → `StreamProvider`)
without updating every consumer in the same diff and getting approval; introduce
`riverpod_generator`/codegen; add `ref.listen` chains that create cycles.

Mandatory: every `family` key class implements `==`/`hashCode`; `ref.read` in
callbacks, `ref.watch` in `build`; no `watch` inside `initState`.

### 3.3 GoRouter (`lib/app/router.dart`)

Allowed: fix a redirect, add a route that mirrors an existing one.

Not allowed: rename existing paths, change `initialLocation`, change the query
parameter names `q`/`lang`, introduce shell routes/nested navigators without
approval (that changes every screen's back behaviour).

Every routing change requires a manual walk: splash → home → result → detail →
favorites → history → settings → auth.

### 3.4 Repositories & services (Dart and Python)

Allowed: fix matching/normalisation, add a method, cache a read.

Not allowed: change a method signature used by a provider/screen without updating
all call sites; introduce a second source of truth (a new cache/store) without
approval.

Mandatory: offline path keeps working; `null` (Dart) / graceful degradation
(Python) instead of exceptions reaching the UI.

### 3.5 Database schema (`backend/app/models/**`, `alembic/**`)

Allowed: add a nullable column with a default; add an index.

Not allowed without approval: rename/drop columns or tables, change types,
introduce a NOT NULL column without a backfill. Every accepted change needs an
alembic revision **and** an update to `scripts/seed_database.py` if the seed
shape changes.

Remember: favorites/feedback are the only DB-backed features; a schema mistake
takes them down while the dictionary keeps working — that asymmetry hides bugs.

### 3.6 Dictionary data (`*.json`)

Allowed: fix a translation, add an entry/sense/example, fix pinyin/IPA.

Not allowed without approval: change the JSON envelope (`dataset_version`,
`entries`), change field names, delete existing senses, or edit only one of the
two copies.

Mandatory per edit: both copies identical (hash check), version bumped, no
duplicate `entry_id`/`sense_id`, Devanagari valid, no mixed Simplified/Traditional
in the same field, examples aligned across three languages. See `DATA-GOVERNANCE.md`.

### 3.7 Language processing (`backend/app/text_analysis/**`, `backend/app/ai/**`)

Allowed: extend the curated phrase DB, extend stopword lists, fix a regex/merge
rule with a test.

Not allowed without approval: change the prompt/JSON contract, change segment
kinds/sources, change `degraded` semantics, change failover thresholds/order,
introduce a local model.

Mandatory: run `pytest` **and** one live request; confirm `degraded` on a sentence
that genuinely has unknowns and `false` on one that does not.

### 3.8 Backend integrations & configuration

Allowed: add an optional field, add a provider entry that follows the existing
adapter, add a config item with a safe default.

Not allowed: hardcode a URL/key in Dart, change `API_BASE_URL`'s default, edit
`.env` semantics, add CORS wildcard widening without approval, change endpoint
paths.

### 3.9 Platform files

`android/**`, `ios/**` changes are release-affecting and require a built artefact
to verify. Adding a permission needs a sentence in `SECURITY.md` explaining why.
Never relax ATS/cleartext globally for production.

---

## 4. What "minimum" means in practice

| Situation | Correct scope | Wrong scope |
|---|---|---|
| Tapping a favorite crashes | replace `Navigator.pushNamed` with `context.push` in `favorites_screen.dart` | rewriting favorites to use the backend |
| Nepali missing on a dataset word | fix that dataset entry in both copies | editing the AI prompt |
| Chinese split into single characters | segmenter fix + test | rewriting the analyzer |
| Settings reset on restart | persist in `settings_provider` | introducing Hive/Isar |
| `degraded` banner on "the" | stopword classification + test | hiding the banner in UI |
| Slow analysis | measure, then tune `_MAX_AI_SURFACES`/timeout | swapping LLM providers |

---

## 5. Known, approved-for-later work (do not "fix" opportunistically)

These are real defects. Each needs its own change with the listed companion updates:

| Item | Scope of a correct fix | Risk if done carelessly |
|---|---|---|
| Favorites tap failure | 1 line + manual walk | none |
| Release `INTERNET` permission + dev cleartext policy | manifest(s) + `SECURITY.md` §6 + release build test | security regression if cleartext is enabled globally |
| Persist settings/history | provider + `shared_preferences` + load-on-start | race at startup; tests must run with a temp store |
| Single favorites implementation | decide Supabase-table vs backend; remove the other; migrate existing ids | data loss |
| Cache dictionary JSON | `services/dataset.py` + invalidation on version change | stale data after deploy |
| `GEMINI_MODEL` example vs default | align `.env.example` with `config.py` (or vice versa) + `ENV-CONTRACTS.md` | silent provider failures |
| Dark theme | real `AppTheme.dark` + contrast audit | unreadable text |

---

## 6. Approval request template

```
Change:            <one sentence>
Class:             cross-cutting | architectural
Files:             <list>
Contract impact:   none | API field | provider type | schema | dataset | prompt
Why this shape:    <why the minimum cannot work>
Alternatives:      <what else was considered>
Verification plan: <commands + manual checks>
Rollback:          <revert commit / feature flag / data restore>
```

Approval is recorded in the PR description. Without it, keep the change in Local
class.

---

## 7. Diff hygiene

- No reformatting of untouched lines; no `dart format` on a whole directory.
- No commented-out code; no `TODO` without an owner.
- No dead files (temporary diagnostics scripts must be removed before commit).
- Keep commits single-purpose with a message shaped
  `area: imperative summary` (e.g. `text_analysis: real Chinese segmentation`).
- If a change needs more than ~400 changed lines outside data files, split it.
