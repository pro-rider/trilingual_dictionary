# TESTING.md — Test & Quality Strategy

Two suites, no CI. Everything below is runnable today on Windows.

```powershell
$env:Path = "C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"

# Flutter
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary
flutter analyze                 # 0 issues required
flutter test                    # 13 tests, < 2 s

# Backend
cd C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend
.venv\Scripts\python.exe -m pytest -q     # 42 tests, ~1.6 s
```

`flutter` commands require git on `PATH` (`Unable to find git in your PATH`
otherwise). No test needs the network, an API key, or Postgres.

---

## 1. Current coverage (honest inventory)

| Area | Flutter | Backend | Gap |
|---|---|---|---|
| Input language detection / normalisation | ✅ 5 tests (`test/widget_test.dart`) | — | no pinyin/mixed-script fuzz |
| Settings & history persistence (mock prefs, load/save/clamp/cap) | ✅ 5 tests (`settings_history_test.dart`) | — | no migration test from older key names |
| Favorites → detail navigation (go_router) | ✅ 1 widget test (`favorites_navigation_test.dart`) | — | no back-navigation assertion |
| TTS language mapping | ✅ 2 unit tests (`tts_service_test.dart`) | — | engine output not asserted (audio is not observable) |
| Health, search, sentence, popular, suggest | — | ✅ `test_api.py` (9) | no prefix/edge-case length tests |
| Auth (503/401/valid) | — | ✅ `test_auth.py` (3) | no favorites/feedback success path (needs DB) |
| Fallback sentence | — | ✅ in `test_api.py` | template wording not asserted |
| AI fallback (unknown word → AI, provenance flags, cache reuse, cache survives provider outage) | — | ✅ `test_ai_fallback.py` (4), stubbed — no network | real provider latency not asserted |
| Quality gate + romanisation | — | ✅ `test_quality.py` (3) | 0.5 placeholder is untested by design |
| Text analysis (zh/en, stopwords, degrade, AI shapes, span merge) | — | ✅ `test_text_analysis.py` (12) | no adversarial Unicode |
| Failover (retry/429/circuit/all-down/metrics) | — | ✅ `test_failover.py` (8) | no real-provider contract test |
| English→Chinese ranking (exact gloss > substring, primary sense wins, Nepali carried through) | — | ✅ `test_english_lookup.py` (3), temp DB | real 123k DB ranking spot-checked manually |
| Widgets / screens | partial (favorites screen) | — | other screens untested |
| Router / navigation | ✅ 1 (favorites → detail) | — | other routes untested |
| Repository / dataset decode | ❌ none | partial | no JSON-schema test |
| DB models / migrations | — | ❌ none | needs a Postgres fixture |
| Performance | ❌ | ❌ | manual measurements only |

Totals: **13 Dart tests, 42 Python tests**, all green on 2026‑11‑08.

---

## 2. Backend testing

### 2.1 Runner & isolation

`pyproject.toml` sets `testpaths = ["tests"]`, `pythonpath = ["."]`, so run pytest
from `backend/`.

`tests/conftest.py` has an **autouse** fixture that flips
`settings.ai_enabled = False` for every test and restores it afterwards. Consequences:

- tests never hit a paid API;
- a test that needs the AI path must re-enable it locally **and** stub the provider
  (never call the network);
- `settings` is a process-global singleton — mutate it inside a fixture, not inline
  at module import.

Each test module builds its own `TestClient(app)`; the app object is shared.

### 2.2 Fake LLM provider pattern

Use the existing pattern from `test_failover.py`:

```python
class FakeProvider(LLMProvider):
    def __init__(self, name, *, reply='{"ok": true}', fails=0, rate_limits=0):
        super().__init__(name=name, api_key="k", model="m", timeout=5, enabled=True)
        ...
    def complete(self, system_prompt: str) -> str | None:
        ...  # raise ProviderRateLimit for 429
```

`FakeProvider` covers: always-success, fail-N-times, rate-limit. Reuse it instead
of inventing new doubles. Build `FailoverLLMService(providers, order,
max_retries=…, retry_backoff=0.0, fail_threshold=…, cooldown_seconds=…)` with
backoff 0 so suites stay fast.

### 2.3 What to assert (not just status codes)

- **Search**: `entry is not None`, `len(senses) == 2` for `light`, all three
  meanings non-empty, unknown word ⇒ `entry is None` **with HTTP 200**.
- **Analysis**: `degraded` correctness is the contract — assert `False` for a
  sentence with only function words, `True` when a content word is unknown, and
  assert punctuation is preserved in `segments`.
- **AI spans**: merged surfaces (`很好`) must appear as one segment, and the parts
  must not be duplicated.
- **Auth**: 503 when `SUPABASE_JWT_SECRET` is empty, 401 for garbage token, 200 +
  `uid` for a valid HS256 token. Tests use a short key and PyJWT emits an
  `InsecureKeyLengthWarning` — expected, not a failure.
- **Quality**: `validate_shape` catches empty fields; `validate_language_fields`
  rejects Latin-only `ne`; `romanize_ne("प्रकाश") == "prakāś"` (determinism).

### 2.4 DB-backed endpoints

There is no DB fixture yet. To add one: spin Postgres
(`docker compose up -d db`), set `DATABASE_URL` to a **test** database, create
tables from `Base.metadata`, and override the `get_db` dependency with a
transaction that rolls back. Never run DB tests against the dev database.

### 2.5 Adding a test — checklist

1. Put it in the module matching the area; module-level `TestClient` is fine.
2. Prefer asserting **domain facts** (meaning text, degraded flag) over exact JSON.
3. Avoid fixed sleeps; failover backoff is configurable.
4. Clean up global state you mutate (`settings.*`), or use the fixture pattern.

---

## 3. Flutter testing

### 3.1 Existing

`test/widget_test.dart` tests `Normalizer` only: language detection (incl. mixed
`mountain 山` ⇒ Chinese), lowercase/trim, pinyin tone-mark stripping, prefix match
both directions.

### 3.2 Adding a widget test

```dart
await tester.pumpWidget(
  ProviderScope(
    overrides: [
      dictionaryRepositoryProvider.overrideWithValue(FakeRepository()),
      settingsProvider.overrideWith((ref) => SettingsNotifier(...)),
    ],
    child: MaterialApp(home: ResultScreen(query: 'light')),
  ),
);
await tester.pumpAndSettle();
expect(find.text('प्रकाश'), findsOneWidget);
```

Rules:
- override providers — never let a widget test reach `Dio` or `rootBundle`;
- `tester.pumpAndSettle()` after async loads; for the splash timer use
  `pump(Duration(milliseconds: 1400))`;
- assert on stable text/keys, not on colors or exact pixel layout;
- every screen test must run at default and at `textScale 1.4`
  (`MediaQuery(data: MediaQueryData(textScaler: TextScaler.linear(1.4)))`).

### 3.3 Required cases before a UI change ships

| Case | Why |
|---|---|
| Empty search → empty-state widget, no crash | `entry == null` is the normal offline path |
| Unknown word + backend down | silent fallback must be visible, not a spinner forever |
| Long text at 1.4× scale | overflow regressions |
| Devanagari rendering | font fallback; assert the glyph string is present |
| `AnalyzeScreen` with `degraded: true` | banner text appears |
| Navigation: favorites tap | covered by `favorites_navigation_test.dart` |

---

## 4. Language / Unicode edge cases (must be exercised manually or by test)

| Input | Expected |
|---|---|
| `zh` traditional characters (`光` vs `光`, `老師`) | Simplified only; Traditional is out of scope — document, do not silently "fix" |
| Half-width vs full-width punctuation | `,` and `，` both treated as punctuation |
| Mixed `mountain 山` | detected as Chinese (CJK presence wins) |
| Emoji / combining marks | must not throw; may end up `unresolved` |
| Zero-width space / NBSP | trimmed or ignored, never splits a word |
| Very long single token (>80 chars) | `/search` rejects at validation (422) |
| 4000+ chars analysis | 422, not a timeout |
| Nepali as input | no results; Nepali is output-only |
| ASCII inside `meaning_ne` | quality gate should reject (currently only checks "has Devanagari") |
| RTL / ZWJ inside Nepali | out of scope; keep bytes intact |

---

## 5. Offline / failure testing

Run these by stopping the backend (`kill` the uvicorn process) — no mocking needed:

| Scenario | Expected |
|---|---|
| backend down, search a dataset word | result renders from asset |
| backend down, search unknown word | "not found" empty state |
| backend down, `/analyze` | "Backend not reachable" message |
| backend up, AI disabled | search unknown ⇒ null; analyze ⇒ `degraded: true` + banner |
| Supabase unconfigured | account section hidden/disabled; no crash |
| Postgres down | favorites local-only; nothing else breaks |

---

## 6. Performance checks (manual, repeatable)

```powershell
# 10 searches, wall clock
$b = @{q='light';lang='en'} | ConvertTo-Json
1..10 | ForEach-Object {
  $sw=[Diagnostics.Stopwatch]::StartNew()
  Invoke-RestMethod http://127.0.0.1:8000/api/v1/search -Method Post -ContentType 'application/json' -Body $b | Out-Null
  $sw.ElapsedMilliseconds
}

# analysis (AI) — expect a few seconds
Measure-Command { Invoke-RestMethod http://127.0.0.1:8000/api/v1/analyze/text -Method Post -ContentType 'application/json' -Body (@{text='今天天气很好，我们去公园散步。';lang='zh'} | ConvertTo-Json) }
```

Budgets and thresholds live in `PERFORMANCE-BUDGET.md`. Re-measure, don't reuse
old numbers in a report.

---

## 7. Definition of done

A change is done when **all** of these hold:

1. `flutter analyze` → `No issues found!`
2. `flutter test` → all pass
3. `pytest -q` → all pass
4. The touched endpoint/screen was exercised once, manually or by test, with the
   observed result recorded.
5. New behaviour has at least one test that fails without the change.
6. The relevant contract document is updated.

No tests are currently red. Defects that remain (sense selection, favorites dual
write) are not yet observable from the suite; add tests when they are fixed.
