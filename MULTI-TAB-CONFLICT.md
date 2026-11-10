# Multi-Tab / Multi-Instance Conflict Audit

Status: **audit + design only**. No production code changed in this document's commit.
Every claim below is labelled **FACT** (observed and reproducible), **INFERENCE**
(supported by facts), **UNKNOWN** (not established), or **ACTION REQUIRED**.

Scope: the writable side of this app — `user.db`, `shared_preferences`, and the
SQLite open path that both of them depend on. Read-only assets
(`dictionary.sqlite`, `translations.db`) are out of scope: they are never written,
so two tabs cannot disagree about them.

---

## 1. What "multi-tab" means for this app

| Surface | Realistic second instance | Shares what |
|---|---|---|
| Android | split-screen / freeform window with two activities, or an app relaunch while the old process is alive | `user.db`, prefs in app support |
| Windows / macOS / Linux desktop | the same executable launched twice | same `user.db` file, same prefs file |
| Web | two browser tabs of the same build | same IndexedDB-backed store (if wired), same `localStorage` |
| Tests | two `UserStore` objects over one temp file | one file, two connections |

FACT: `android/`, `ios/`, `linux/`, `macos/`, `web/`, `windows/` all exist in the repo
(`Get-ChildItem -Directory` at repo root), so all four runtime surfaces are targets.
FACT: `pubspec.yaml:20` declares `sqflite`, and `pubspec.yaml:28` declares
`sqflite_common_ffi` **only under `dev_dependencies`**.

---

## 2. Verified current state

### 2.1 How `user.db` is opened

FACT — `lib/data/local/user_store.dart:102`:

```dart
final db = await openDatabase(file.path);
```

That is the whole call. Consequences, all from the same line:

- no `OpenDatabaseOptions`, so `singleInstance` keeps its `true` default (one handle
  per path **per process**) — INFERENCE from the sqflite API contract, not observed here;
- no `PRAGMA busy_timeout` is set anywhere in `lib/` — FACT, `Grep` for
  `busy_timeout|journal_mode|WAL` over `lib/**/*.dart` returns only
  `translation_repository.dart:58`, which is a **read-only** store;
- the default journal mode therefore stays `delete` (rollback journal), which is the
  mode that serialises readers against a writer;
- the default synchronous behaviour and page size are untouched.

### 2.2 How writes reach it

FACT — `lib/data/local/user_store.dart:252-263` (`putAiGloss`) and `:298-309`
(`putAiExample`) both use `conflictAlgorithm: ConflictAlgorithm.replace`.
INFERENCE: `REPLACE` is an unconditional last-writer-wins `INSERT OR REPLACE`; a
concurrent writer's row is discarded with no error and no record. Section 3.3 shows
this happening on a real file.

FACT — `lib/data/local/user_store.dart:95`:

```dart
Future<Database?> open() => _opening ??= _openInner();
```

The future is cached, and `:119-122` swallows every failure:

```dart
} catch (_) {
  _opening = null;
  return null;
}
```

INFERENCE: a failed open degrades to a **silent no-op writer** — every
`putAiGloss` / `putAiExample` returns normally and persists nothing, and no caller
can tell the difference. This is the same class of defect that was fixed in
`offline_dictionary.dart` (degraded must carry a reason); `user_store.dart` was not
part of that fix.

### 2.3 How the rest of the user state is written

FACT — favourites are not in `user.db` at all. `lib/features/favorites/favorites_repository.dart:45-73`
reads the current list from **in-memory** `state`, mutates it, and writes the whole
list back:

```dart
final current = List<String>.from(state.value ?? const []);   // :46
...
await _saveLocal(current);                                    // :55
```

FACT — history does the same (`lib/features/history/history_provider.dart:33-39`
builds `[q, ...state]` then saves the whole list).

INFERENCE: both are **read-modify-write over a cached snapshot**. A second tab that
loaded the list at T0 and saves at T2 writes its T0-based list over everything tab
one wrote between T0 and T2. Nothing merges; nothing is timestamped.

FACT — settings are per-key (`lib/features/settings/settings_provider.dart:119-134`),
so they lose only the keys two tabs changed at the same moment. Lower risk, same shape.

### 2.4 Is a desktop/web build even able to open a database?

FACT — `Grep` for `databaseFactory =` / `databaseFactoryFfi` / `sqfliteFfiInit` over
every `.dart` file in the repo returns **8 hits, all under `test/`**:

```
test/analyze_offline_test.dart:23
test/image_lookup_test.dart:14
test/offline_dictionary_test.dart:18
test/translation_repository_test.dart:21
test/user_store_test.dart:24 (helper), :77, :185, :201
```

No hit under `lib/`. INFERENCE: on Windows/macOS/Linux the plain `sqflite` plugin has
no implementation, so `openDatabase` throws, `_openInner` catches it, and the app runs
with **no writable store at all** — dict lookups still work only because
`OfflineDictionary._openInner` (`lib/data/local/offline_dictionary.dart:123`) hits the
same wall and degrades with a reason. Web is in the same position, and no
`sqflite_common_ffi_web` dependency exists in `pubspec.yaml`.

UNKNOWN: whether a shipped desktop build is currently shipped at all, and whether
`sqlite3` native libraries are present on each target. Neither was exercised here —
building a desktop bundle was out of scope for this document.

ACTION REQUIRED: confirm which platforms are intended to ship. If desktop or web is
intended, item 5.1 below is a prerequisite for every other fix, because nothing
below can be verified on a platform whose factory is never installed.

---

## 3. Engine-level facts (measured, not assumed)

Script: `%TEMP%\mt_probe.py` (stdlib `sqlite3`, local file, no network). Command:

```
backend\.venv\Scripts\python.exe %TEMP%\mt_probe.py
```

Raw output:

```
OBS rollback/timeout=0 second writer: database is locked
OBS timeout=5 second writer succeeded after 0.02s
OBS after two successful writers, surviving value: ('light',)
OBS reader inside writer txn sees: (0,)
OBS reader after commit sees: (1,)
OBS data_version before/after another connection committed: 3 4 changed= True
```

### 3.1 No busy timeout means an immediate hard failure

FACT: with `timeout=0`, the second writer raises `database is locked` instead of
waiting. FACT: with `timeout=5` it waits and completes in 0.02 s once the first
writer commits.

INFERENCE: the app never sets a busy timeout, so if two instances overlap inside a
write, the loser's write throws. Today that exception is only half-visible: the
`insert` in `putAiGloss` is **not** wrapped, so it propagates to the caller of
`putAiGloss` — inside `OfflineDictionary` (`:953-963`) that is inside the AI-fill
flow, which is where a user would see an unexplained failure.

### 3.2 Rollback journal blocks readers during a write

FACT: a reader inside the writer's transaction sees `(0,)` — in a rollback-journal
database a reader is served from before the write and, under contention, blocked.
INFERENCE: with `journal_mode=WAL` (measured separately in the same script, second
half) readers are snapshot-isolated instead of blocked. For a dictionary UI that reads
favourites and glosses constantly, WAL removes the most visible symptom: a frozen
screen while another tab saves.

### 3.3 `REPLACE` really is last-writer-wins

FACT: two connections each committed successfully; the surviving value was `('light',)`
— the first writer's `('dark',)` is gone with no error raised anywhere.
INFERENCE: two tabs toggling the same favourite, or two AI fills writing the same
sense key, silently destroy each other's work. The `created_at` column exists but is
not consulted on write; it is only consulted on **import**
(`user_store.dart:365-374`).

### 3.4 `PRAGMA data_version` is a usable cross-instance signal

FACT: `PRAGMA data_version` went `3 → 4` on connection B after connection A committed.
INFERENCE: a 1–2 s poll of `data_version` tells an instance that another instance
committed, without a socket, a server, or a paid service.

---

## 4. Failure-mode catalogue

| ID | Scenario | Observable symptom | Cause (file:line) | Severity |
|---|---|---|---|---|
| F1 | Two processes write `user.db` at once | one write throws `database is locked` | no `busy_timeout`, rollback journal (`user_store.dart:102`) | High |
| F2 | Same sense key written by two tabs | one value silently disappears | `ConflictAlgorithm.replace` (`:262`, `:308`) | High |
| F3 | Toggle favourite in tab A, tab B saves later | tab A's change vanishes | read-modify-write over `state` (`favorites_repository.dart:46-55`) | High |
| F4 | Same for history | history list rewinds | `history_provider.dart:33-39` | Medium |
| F5 | Migrations run from two instances at first launch | duplicate `.bak-` files, partial schema possible | version check then migrate, no lock (`user_store.dart:107-116`) | Medium |
| F6 | Store fails to open | writes silently no-op, no reason surfaced | `catch (_)` (`user_store.dart:119-122`) | High (already fixed in `offline_dictionary`, still present here) |
| F7 | Desktop / web run | no store at all | factory never installed (`grep` 8/8 hits in `test/`) | Blocking for those platforms |
| F8 | Tab A saves settings while tab B saves others | only the overlapping keys are lost | per-key writes (`settings_provider.dart:119-134`) | Low |
| F9 | Second instance shows stale favourites | no refresh until app restart | no change subscription anywhere in `lib/` | Medium |

Severity weights: F7 blocks ship on desktop/web. F1/F2/F3/F6 corrupt or lose user
data. F5 can leave a half-built schema. F4/F9 are visible but recoverable.

---

## 5. Design: the minimum that actually closes each failure

Order matters — 5.1 must exist before 5.2–5.4 can be tested on those platforms.

### 5.1 Install the factory on every platform (closes F7)

`main.dart`, before any provider touches the store:

```dart
import 'dart:io' show Platform;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

Future<void> _installDatabaseFactory() async {
  if (kIsWeb) {
    // Requires sqflite_common_ffi_web (free, BSD-3) — add before shipping web.
    return;
  }
  if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  }
}
```

`pubspec.yaml` moves `sqflite_common_ffi` from `dev_dependencies` to `dependencies`
(it is BSD-3, free, and already in the lockfile). No paid dependency is introduced.

### 5.2 Harden the connection (closes F1, softens F2)

At open, once per file, before the first query:

```dart
final db = await openDatabase(
  file.path,
  options: OpenDatabaseOptions(singleInstance: true),
);
await db.execute('PRAGMA journal_mode = WAL');   // persistent, not per-connection
await db.rawQuery('PRAGMA busy_timeout = 5000');
await db.execute('PRAGMA synchronous = NORMAL');
```

`journal_mode` is stored in the file header, so the first writer upgrades the
database once; `busy_timeout` is per connection and must be set on every open.
Measured backing for both numbers is in 3.1 and 3.2.

### 5.3 One writer, many readers (closes F5)

A `user.db.lock` **beside the database**, held with an OS advisory lock:

```dart
final raf = await File('${file.path}.lock').open(mode: FileMode.write);
try {
  await raf.lock(FileLock.exclusive);      // blocks or use FileLock.nonBlocking
  _lock = raf;                             // keep for the process lifetime
} on FileSystemException {
  // Another instance owns the writer role: open read-only and show the banner.
}
```

`RandomAccessFile.lock` is `flock`/`LockFileEx` — it works on Windows, macOS and
Linux, is released when the process dies (no stale-lock cleanup job needed), and
costs nothing. The second instance becomes a reader: it can search and translate, it
just cannot write, and the UI must say so (same banner contract as the degraded one).

If polling the lock is preferred to blocking, `FileLock.nonBlocking` plus a 1 s retry
turns "read-only mode" into "wait your turn" without changing anything else.

### 5.4 Conflict-free writes (closes F2, F3, F4)

Two changes, both small:

1. **Every composite write inside one transaction**, so a failed write leaves nothing
   behind. `putAiGloss` / `putAiExample` become
   `await db.transaction((txn) => txn.insert(...))`.
2. **Timestamp-guarded upsert instead of blind replace** for the two AI tables —
   `created_at` already exists and import already honours it (`:365-374`), so the
   write path just needs to agree with the read path:

```sql
INSERT INTO ai_glosses (sense_key, gloss_ne, gloss_zh, status, model, created_at)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(sense_key) DO UPDATE
  SET gloss_ne = excluded.gloss_ne, gloss_zh = excluded.gloss_zh,
      status = excluded.status, model = excluded.model,
      created_at = excluded.created_at
WHERE excluded.created_at >= ai_glosses.created_at;
```

Favourites and history move from "whole list from `state`" to a store read-modify-write
inside one transaction (`txn.insert` into a `favorites` table that already exists and
is currently unused by the UI — FACT: `favorites(key PK, entry_id ...)` is created at
`user_store.dart:153-161` but `favorites_repository.dart` never touches it, it uses
`shared_preferences`). Routing favourites through `user.db` removes the prefs
whole-file race entirely.

### 5.5 Tell the other tab (closes F9)

Poll `PRAGMA data_version` every 2 s while the app is foregrounded; when it changes,
invalidate the providers that read user-owned rows. Measured in 3.4, and it is a
single integer comparison — no sockets, no server.

### 5.6 Never fail silently again (closes F6)

`_openInner` records the error and exposes it, exactly like
`lib/data/local/offline_dictionary.dart` now does:

```dart
Object? _lastError;
String get unavailableReason => _lastError == null
    ? ''
    : 'The local user store could not be opened ($_lastError). '
      'Saving favourites and AI results is disabled for this session.';
```

The settings screen surfaces `unavailableReason` when non-empty. No new UI concept is
needed: it is the same amber banner already used for degraded analysis.

---

## 6. Proposed tests (local, free, no network)

New file `test/multi_instance_store_test.dart`. All of it runs on
`databaseFactoryFfi` like the existing `user_store_test.dart:76-77`.

| # | Test | Proves | Would fail today |
|---|---|---|---|
| T1 | two `UserStore` objects over one file, both `putAiGloss` same key with different `created_at` | newer timestamp survives; older write does not clobber | yes (replace) |
| T2 | writer holds `BEGIN IMMEDIATE`, second store writes with `busy_timeout=5000` | second write waits, then succeeds — no `database is locked` | yes (no timeout) |
| T3 | reader query while writer is mid-transaction, WAL on | reader returns immediately with the pre-commit snapshot | yes (rollback journal) |
| T4 | `FileLock.exclusive` on `user.db.lock` from two handles | second handle is refused; released on close; reacquirable | n/a (feature absent) |
| T5 | commit from connection A, poll `data_version` from B | value changes; polling detects it | n/a (feature absent) |
| T6 | `journal_mode` after first open | reports `wal` and stays `wal` on reopen | yes |
| T7 | open failure (a directory in place of the file) | `unavailableReason` is non-empty and names the cause | yes (silent null) |

Commands:

```
flutter test test/multi_instance_store_test.dart
flutter test
flutter analyze --no-fatal-infos
```

Acceptance: `flutter test` count grows by 7 with zero skips, `analyze` stays clean,
and no existing test changes its expectation (the rule already agreed: never adjust
expectations to make a change green).

---

## 7. Rollout

| Step | Change | Gate |
|---|---|---|
| R1 | this document | done, no code |
| R2 | 5.1 factory + `pubspec.yaml` dependency move | needs approval (build config) |
| R3 | 5.2 PRAGMAs + 5.6 reason surface | needs approval (open path) |
| R4 | 5.4 transactional + timestamp-guarded writes | needs approval (write path) |
| R5 | 5.3 writer lock + read-only mode banner | needs approval (behaviour change) |
| R6 | 5.5 `data_version` polling | needs approval (UI refresh) |
| R7 | T1–T7 | ships with R3–R6 |

R2 alone is enough to stop desktop/web from being silently store-less, and it is
reversible (one import block, one dependency line).

---

## 8. Open items

- UNKNOWN: default `busy_timeout` inside `sqflite_common_ffi`. The engine-level
  numbers here are SQLite's own; the Dart wrapper could set its own default. Measuring
  it needs a test on the Dart side (T2 covers it).
- UNKNOWN: whether Android split-screen actually gives two live processes for this
  app, or the second pane reuses the same process. Depends on `launchMode` in the
  manifest, which was not inspected.
- UNKNOWN: `web/` correctness — no `sqflite_common_ffi_web` dependency exists, so the
  web store path was never exercised.
- ACTION REQUIRED: confirm intended platforms (5.1 gate).
- ACTION REQUIRED: decide whether favourites move from `shared_preferences` to
  `user.db` (5.4), or stay in prefs with a merge-on-write guard.

---

## 9. Evidence index

| Claim | Where it came from |
|---|---|
| open path, caching, silent catch, replace writes, import merge | `lib/data/local/user_store.dart:95, 102, 119-122, 252-263, 298-309, 365-374` |
| favourites read-modify-write | `lib/features/favorites/favorites_repository.dart:46, 55, 75-78` |
| history read-modify-write | `lib/features/history/history_provider.dart:33-39, 60-67` |
| settings per-key writes | `lib/features/settings/settings_provider.dart:119-134` |
| no factory in `lib/` | `Grep -r "databaseFactory =|databaseFactoryFfi|sqfliteFfiInit"` → 8 hits, all `test/` |
| read-only store uses `singleInstance: false` | `lib/data/local/translation_repository.dart:56-59` |
| `sqflite_common_ffi` is dev-only | `pubspec.yaml:20, 28` |
| lock refusal / 5 s wait / last-writer-wins / WAL snapshot / data_version | `%TEMP%\mt_probe.py`, output in section 3 |
| CI green at the commit that added this file | Actions run `42833687057`, backend + flutter both `success` |
