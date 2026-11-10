# PERFORMANCE-BUDGET.md — Performance & Resource Budgets

Budgets are **targets**; the "Measured" column is what was actually observed on
the dev machine (Windows desktop, local loopback backend, 6-entry dataset). Never
copy a measured number as a guarantee for a phone, and never quote a target as if
it had been measured.

Measured on 2026‑11‑07, backend `127.0.0.1:8000`, AI via Groq:

| Path | Measured |
|---|---|
| `POST /search` (dataset hit), 10 runs | **min 3 ms · max 73 ms · avg 10.3 ms** |
| `POST /analyze/text` Chinese sentence, AI on | **≈4220 ms** (one network round trip to the LLM) |
| jieba dictionary load (first Chinese analysis in a process) | **≈390 ms** (one-off) |
| `pytest -q` (35 tests) | ~1–2 s |
| `flutter analyze` | ~5–7 s |
| `flutter test` (5 tests) | <1 s |
| Flutter cold start / memory / frame timing | **not measured** |

`POST /search` is in-process JSON lookup; the 73 ms outlier is the largest seen and
came from a cold first call.

---

## 1. Budget table

| Dimension | Target (must hold) | Stretch | Notes |
|---|---|---|---|
| App cold start → first frame (mid-tier Android) | ≤ 2.5 s | ≤ 1.5 s | splash deliberately holds 1400 ms before `/home`; that is *perceived* startup and must be counted |
| Home screen interactive after launch | ≤ 3.5 s | ≤ 2 s | includes 1400 ms splash |
| Offline single-word lookup (warm) | ≤ 60 ms | ≤ 30 ms | asset is 5.7 KB; measured backend equivalent is 10 ms |
| Offline dataset parse at startup | ≤ 120 ms | ≤ 60 ms | 6 entries; scales with file size |
| Backend `POST /search` p95 (no AI) | ≤ 150 ms | ≤ 60 ms | measured avg 10 ms locally |
| Backend `/health` p95 | ≤ 20 ms | — | no dependency probes |
| Analysis without AI (dataset + phrase DB only) | ≤ 100 ms | ≤ 50 ms | must not regress when the LLM is down |
| Analysis with AI p95 (single provider) | ≤ 6 s | ≤ 4 s | measured 4.2 s; third-party latency dominates |
| Analysis worst case (client gives up) | 25 s | — | `ApiConfig.timeout`; beyond this the UI must show an error, not spin forever |
| Sentence generation (`/search/sentence`) from dataset | ≤ 100 ms | — | no AI in the reviewed path |
| Scroll / list rendering | 60 fps; ≤ 1 % frames > 16 ms | 120 Hz capable | no frame > 32 ms while scrolling results/history |
| Text-scale 1.4 layout | 0 overflow errors | — | mandatory check |
| App resident memory (mid-tier, after browsing) | ≤ 180 MB | ≤ 120 MB | not yet measured; measure before claiming |
| Backend process RSS (idle, AI on) | ≤ 250 MB | ≤ 150 MB | jieba dictionary ~ tens of MB once loaded |
| APK/AAB size | ≤ 40 MB | ≤ 25 MB | not yet measured |
| Postgres favorites query | ≤ 10 ms local | ≤ 5 ms | single indexed `user_id` lookup |

Only the rows marked "measured" above have evidence. Treat the rest as gates to
verify on the first device build.

---

## 2. Where time actually goes

### 2.1 Search

```
[Flutter] Dio call ──▶ [FastAPI] pydantic validate ──▶ dataset JSON read ──▶ match ──▶ serialize
                                                        ▲
                                    reads the whole 5.7 KB file on EVERY request
```

- Today: file read + parse per call is cheap at 6 entries.
- **Scaling rule:** cache the parsed index once it exceeds ~1 000 entries or when
  p95 search passes 100 ms, whichever comes first. Invalidate on
  `dataset_version` change.
- Any accidental AI call on a dataset hit would move p95 from 10 ms to seconds —
  keep the "dataset first, AI only on miss" order.

### 2.2 Analysis

```
[jieba load 390 ms (once per process)]
  → segment (~ms)
  → phrase/dataset lookups (~ms)
  → ONE LLM call (seconds)            ← 97 %+ of wall time in practice
  → span merge + classify (~ms)
```

- The AI call is a single batched request (`_MAX_AI_SURFACES = 60`); latency is
  the provider's, not ours. Raising the surface cap increases prompt size and
  latency roughly linearly — measure before changing it.
- **First request penalty:** the first Chinese analysis after a backend restart
  pays ~390 ms extra. Warm the segmenter at startup (or accept the spike); do not
  let the app's 25 s timeout absorb repeated cold starts.
- Failover multiplies latency: worst case is 3 providers × (1 retry + 1) × 40 s
  provider timeout ≈ 240 s, which **exceeds the client's 25 s**. In practice the
  client aborts first and the user sees "not reachable". Before production,
  either lower `AI_MAX_RETRIES` / provider timeouts, or raise the client timeout
  deliberately — do not leave the mismatch implicit.

### 2.3 Startup

- `main()` does one Supabase init at most (skipped when unconfigured) — negligible.
- `SplashScreen` waits 1400 ms by design; reducing it is a product decision, not
  a performance fix.
- `popularProvider` triggers `DictionaryRepository.load()` (first asset decode) on
  the home screen; this is the real first-frame cost driver.

### 2.4 Rendering

- Long lists (`history`, suggestions, analysis segments) are short today. Use
  `ListView`/`CustomScrollView` when any list can exceed ~20 items; avoid building
  every segment card eagerly for 4000-char input.
- Avoid `Opacity`/`Blur` per card and per-frame `setState` in scroll handlers.

---

## 3. Caching policy (current: almost none)

| Layer | Cache | Status |
|---|---|---|
| Flutter dictionary asset | `_loaded` flag in `DictionaryRepository` | ✅ parsed once per app session |
| Flutter network results | Riverpod `FutureProvider.family` | ✅ per query key, for session |
| Flutter images/fonts | framework defaults | n/a |
| Backend dataset | none — re-read per request | ❌ add when size grows |
| Backend AI results | none — every unknown word hits the provider | ❌ a memo cache would cut cost and latency; must key on text+prompt version and expire |
| HTTP | none | no `Cache-Control` headers are set |

If you add caching, document eviction and staleness here; a stale translation cache
is a data-quality bug, not just a perf tweak.

---

## 4. Measuring (repeatable recipes)

### Backend latency

```powershell
$b = @{q='light';lang='en'} | ConvertTo-Json
$t = 1..10 | ForEach-Object {
  $sw=[Diagnostics.Stopwatch]::StartNew()
  Invoke-RestMethod http://127.0.0.1:8000/api/v1/search -Method Post -ContentType 'application/json' -Body $b | Out-Null
  $sw.ElapsedMilliseconds
}
$t | Measure-Object -Minimum -Maximum -Average
```

```powershell
Measure-Command {
  Invoke-RestMethod http://127.0.0.1:8000/api/v1/analyze/text -Method Post -ContentType 'application/json' `
    -Body (@{text='今天天气很好，我们去公园散步。';lang='zh'} | ConvertTo-Json)
} | Select-Object TotalMilliseconds
```

### App startup & frames (device only)

```powershell
cd trilingual_dictionary
flutter run --profile -d <device-id>
# then, in DevTools: Performance → frame chart, and
adb shell dumpsys gfxinfo com.example.trilingual_dictionary reset
# interact 10 s, then
adb shell dumpsys gfxinfo com.example.trilingual_dictionary
```

Use `flutter drive --profile --trace-startup` (or an `integration_test` with
`IntegrationTestWidgetsFlutterBinding.traceAction`) for startup timings. Record
device model, OS version, build mode, and dataset version next to the number.

### Memory

`adb shell dumpsys meminfo com.example.trilingual_dictionary` (PSS) after: launch
→ 5 searches → 1 analysis → 1 detail view. Backend: Task Manager / `psutil`.

---

## 5. Device tiers to test

| Tier | Reference class | Expectation |
|---|---|---|
| Low | 2 GB RAM, Android 9, 720p | app usable, offline search only; AI paths allowed to be slow but must time out cleanly |
| Mid | 4 GB RAM, Android 12, 1080p (typical test device) | all budgets above must hold |
| High | 8 GB RAM, Android 14, 120 Hz | no regressions; frame budget still 60 fps minimum |

Emulators are not a substitute for the low tier (they have host CPU and unlimited
memory); at least one physical low-end device is required before a release claim.
iOS: one simulator pass for layout/ATS is enough until a device is available.

---

## 6. Regression rules

1. Any change to search, analysis, or dataset loading re-runs the recipes in §4
   and records the numbers in the PR.
2. A p95 regression of **> 2×** or a budget breach blocks the change until
   justified in writing.
3. A dataset enlargement must come with the measured parse/search numbers for the
   new size and a caching decision.
4. Do not "optimise" without a measurement — and do not optimise the 10 ms path
   while the 4 s path is unowned.

## 7. Known performance risks (open)

- Backend re-reads the dataset per request (no cache).
- Worst-case failover latency (≈240 s) exceeds the app's 25 s timeout.
- First Chinese analysis after restart pays a ~390 ms jieba load.
- No AI result cache: repeated unknown words cost a full LLM call each time.
- Flutter startup/memory/frame budgets have never been measured on a device.
  Measure with `--profile` against an HTTPS backend (release blocks cleartext) or
  with a debug build for local HTTP.
