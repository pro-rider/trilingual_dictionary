# G1 — user data must survive a dictionary update

Status: core implemented. Everything below was verified by running the code, not
by reading it.

## What the audit found

| Data | Where it lived | Survives a dictionary swap? |
|---|---|---|
| Favorites | `SharedPreferences` (`favorites` key), mirrored to Supabase | Yes — separate file |
| Search history | `SharedPreferences` (`history` key) | Yes |
| Settings (theme, text size, TTS voice) | `SharedPreferences` | Yes |
| **AI-translated Nepali glosses** | **`dictionary.sqlite` → `senses.gloss_ne`, `ne_status='ai_translated'`** | **No — deleted with the old file** |
| **AI example sentences** | **`dictionary.sqlite` → `examples` (inserted row)** | **No — same** |

`OfflineDictionary._openInner()` deletes `dictionary.sqlite` whenever
`assetVersion` changes; that is deliberate, because the APK ships a new
dictionary. The consequence was that every AI result a user paid for disappeared
on the next app update. That was the real defect in G1.

Second defect: favorites are stored by `entry_id` (`zh72162`), a row id that a
dictionary rebuild is free to renumber. The word could stay in the list while
the id now points at a different entry.

## What changed

**`lib/data/local/user_store.dart` — `user.db`, a sibling of the dictionary.**

* Tables: `ai_glosses`, `ai_examples`, `favorites`, `prefs`, `id_remap`,
  `migrations`.
* Every AI row is keyed by a **stable sense key**:
  `simplified + \u001f + pinyin + \u001f + gloss_en`, trimmed and
  case-folded. Identical across dictionary builds, distinct per sense, and
  readable in a bug report — no row ids, no hashes.
* `PRAGMA user_version` gates creation and migration; **any migration is
  preceded by a file copy** (`user.db.bak-<utc timestamp>`), so a failed upgrade
  is reversible.
* `exportJson()` / `importJson()` move the whole store as one file. Import merges
  row by row and keeps the **newer** `created_at`, so restoring an old backup
  cannot roll back fresher AI output.

**`lib/data/local/offline_dictionary.dart`.**

* `enrich()` now writes AI Nepali/Chinese glosses and AI examples into
  `user.db`, never into `senses` / `examples` of the dictionary file.
* `_toEntry()` and `_segmentFor()` overlay `user.db` on top of the dictionary
  read: a sense with no packaged Nepali gloss shows the AI one, marked
  `meaningNeSource = 'ai_translated'`; a sense with no packaged example shows the
  AI sentence labelled `AI · unverified` instead of pretending it is reviewed.
* Batch read: one query per entry for glosses and one for examples, not one per
  sense.

**`lib/features/search/widgets/sentence_section.dart`** — the status line is now
`✓ reviewed` / `AI · unverified` / `draft`, so an AI sentence can never be
mistaken for a checked one.

## Tests (`test/user_store_test.dart`, 5 passing)

```
a sense key depends on the word, not on a row id
AI Nepali gloss survives a dictionary rebuild
AI example is used only when the sense has none of its own
export and import keep AI rows, and an older file cannot win
opening an existing file migrates it and keeps a backup
```

The rebuild test writes an AI gloss, then opens a **second dictionary file**
where the same word has a different `entry_id` (900 instead of 1), and asserts
the Nepali text is still there. That is the exact failure an update used to
cause. The full suite is 35 tests, all passing; `flutter analyze lib test` is
clean.

## Still open in G1

1. **Favorites still keyed by `entry_id`.** The `favorites` table in `user.db`
   exists and is exported, but the Riverpod repository still writes the old
   `zh<id>` strings to `SharedPreferences`. Wiring it needs the dictionary at
   toggle time to resolve `zh<id>` → stable key, plus a one-time pass that
   rewrites existing favourites, with unmatched ids recorded in `id_remap`.
   Until that lands, a dictionary rebuild can move a favourite onto a different
   word.
2. **History and settings are safe but not exportable.** They sit in
   `SharedPreferences`; the `prefs` table in `user.db` is the intended home so
   the single export file carries them too.
3. **Crash reporting of migration.** A migration that throws currently leaves
   the store unopened (the app keeps working without AI overlays). It should
   surface a recoverable banner instead of silently degrading.
