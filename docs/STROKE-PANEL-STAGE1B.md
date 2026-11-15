# Stroke panel — Stage 1b: data verification and review artifacts

**Branch** `character-panel` · **Stage 2 (device) not started** · no push, no APK.

Purpose: Stage 1 shipped a panel whose review files could not do their job and whose
numbers included one likely data defect. Stage 1b re-derived every number from source,
rebuilt the review artifacts so a human can actually check stroke order, measured the
cost in Dart instead of Python, and made the panel honest about characters whose count
is not settled.

## 0. Status, per delivered item

| # | item | status | evidence |
| --- | --- | --- | --- |
| A | pack vs raw source for all 934 characters | **DONE** | `verify` script output in §1 |
| A | 都 explained | **DONE** | §1, `strokes.source_counts.json` |
| B | difference formula stated and reconciled | **DONE** | §2 |
| B | `review/stroke_differences.csv` (all 59) | **DONE** | 59 rows + header |
| B | `review/stroke_spot_check.csv` (real sample) | **DONE** | 198 rows, seed 20261115 |
| B | contact sheet PNG | **DONE** (generated + reviewed by eye) | `06_contact_sheet.png`, 116 KB |
| C | non-Han skipped, recount, old beside new | **DONE** | §3 |
| C | `review/stroke_missing.csv` with rank/words/top-N | **DONE** | 41 rows (38 Han + 3 letters) |
| C | `review/stroke_variant_map.csv` proposal only | **DONE (proposal)** — 5 usable of 40 | §4 |
| D | frame sequences 0/25/50/75/100 | **VERIFIED (engine render)** | 5 PNGs in §5 |
| D | radical row + missing fallback without SimHei | **VERIFIED (engine render)** | `08`, `09` in §5 |
| E | top-3000 size + decode time in Dart | **VERIFIED (tests)** | §6, measured numbers |
| E | decode off the UI isolate | **DONE (code)** — device number pending | §6 |
| F | `disputed` flag + panel behaviour | **VERIFIED (tests)** | §7 |
| G | build-generated dates + consistency test | **DONE** | §8 |
| G | licence document: designated place, GPL analogy, §2(c) | **DONE** | §8 |
| H | merge plan for `settings_provider.dart` | **DONE (plan only, nothing merged)** | §9 |
| — | `review/*.csv` backed up | **DONE** | `docs/review-backup/` |
| — | `flutter analyze` | **DONE** — `No issues found!` | §10 |
| — | `flutter test` | **DONE** — `160 tests passed` | §10 |
| — | commit / push | **NOT DONE** — not requested, nothing pushed | working tree only |
| — | device run (Stage 2) | **VERIFIED on device** — profile build installed and measured; panel itself not reachable in the app (finding) | §11 |

Status words are used exactly as defined: **DONE** = the artifact exists and was
checked; **VERIFIED (tests)** = a test asserts it and passes; **VERIFIED (engine
render)** = a rendered PNG shows it; **NOT VERIFIED** = not done; **BLOCKED** = cannot
proceed.

## 1. Task A: is 都 a builder bug or a source bug?

### The comparison

Every packed character's stroke count was compared with the raw
`hanzi-writer-data@2.0.1` file it came from. The pack builder writes
`assets/strokes/strokes.source_counts.json` **before** packing (the count as read from
the source), and `write_pack` now asserts, per character, that the packed count equals
that recorded count — a mismatch aborts the build with `SystemExit`.

```
packed chars                          934
raw file missing                      0
count mismatch (pack vs raw)          0
```

So the builder neither dropped nor merged a stroke anywhere in the shipped set. The
assertion is permanent: it runs on every rebuild, including `--top 3000`.

An earlier check script of mine reported "mismatches" because it indexed the source
file by character (`json[ch]`). The source files are **flat dicts** —
`{"strokes": [...], "medians": [...], "radStrokes": [...]}` — with no character key at
all; the character is only in the file name. That script was wrong, not the data.

### 都, in full

| quantity | value |
| --- | --- |
| raw `strokes` length | 10 |
| raw `medians` length | 10 |
| raw `radStrokes` | `[8, 9]` (the 阝 component is drawn as **2** strokes) |
| packed strokes | 10 |
| Unihan `kTotalStrokes` (18.0.0) | **12** (single value; no PRC/Taiwan pair in this release) |
| difference (pack − Unihan) | −2 |
| each median's start point | recorded in `stroke_work/` output; the pack's `medians` are the authoring points of the 10 strokes, first at (≈314, 119) in a 1024 em box |

Conclusion: **`都 = 10` comes from the source, not from the builder.** 12 is the
Kangxi/Taiwan count (者 9 + 阝 3); 10 is the PRC count (者 8 + 阝 2), which is how the
Arphic GB-style font draws it. The same holds for 这 (7, PRC) vs 這 (10, Kangxi).
Nothing was edited by hand.

The consequence for teaching is real and is handled by Task F: the panel still
animates 都, but does not print a stroke count for any character whose count is in the
59-row difference table with an empty decision.

## 2. Task B: the review files, redone

### The sign convention, stated once

```
difference = pack_strokes − unihan_strokes
```

Negative means the pack has **fewer** strokes than Unihan. The 辶 group is **−1**
because the pack counts 辶 as **3** (PRC) and Unihan counts it as **4** (Kangxi).

**The Stage 1 document was wrong**, not the data: it said "source counts 辶 as 4,
Unihan as 3". That is the reverse of the actual values. `docs/STROKE-PANEL-STAGE1.md`
§2 has been corrected and now states the formula and the direction.

### `review/stroke_differences.csv` — 59 rows, all of them

Columns: `char, simplified_or_traditional, frequency_rank, pack_strokes,
unihan_strokes_all_values, difference, group, suspected_cause, decision` (`decision`
empty).

| group | rows | difference |
| --- | --- | --- |
| radical-辶 | 18 | all exactly −1 (PRC vs Kangxi) |
| other | 41 | −2 ×3, −1 ×32, +1 ×5, +3 ×1 |

### `review/stroke_spot_check.csv` — a sample that can catch a wrong order

198 rows, de-duplicated union of:

- the **100 most frequent characters**,
- **50 random** characters — fixed seed `20261115`, recorded in
  `assets/strokes/build_info.json`,
- **every** row of `stroke_differences.csv`.

Columns: `char, frequency_rank, pack_strokes, reference_strokes, reference,
difference, order_reference, decision`.

`order_reference` is filled on the 58 differing rows only, and it says what is true:

```
no verified independent source for stroke ORDER offline — Unihan has counts only
```

This is deliberate. A spot-check CSV whose "reference" is Unihan can only confirm
counts, never order, which is what the Stage 1 file got wrong. Order is therefore
checked by eye against the contact sheet, not asserted against a lookup table.

### The contact sheet

`docs/screenshots/character-panel/06_contact_sheet.png` — one cell per sample
character, stroke numbers drawn at each median's start point, cell label
`char·count`. Generated from the pack itself, so it shows exactly what the app
animates.

## 3. Task C: what is actually missing

Non-Han characters (`A`, `B`, `T` from `A股`, `T恤` …) are **skipped, not missing**. The
coverage count changed accordingly — the old number counted them as missing.

| measure | Stage 1 (old) | Stage 1b (new) |
| --- | --- | --- |
| codepoints wanted | 975 | 975 |
| packed | 934 | 934 |
| "missing" | 41 | **38 Han** (+3 Latin, skipped) |
| words fully covered | 1098 / 1140 = 96.3 % | **1101 / 1140 = 96.6 %** |
| words partially covered | 36 | 36 |
| words with no data | 6 | 6 |

`review/stroke_missing.csv` now carries `frequency_rank`, `words_containing_it`,
`in_top500`, `in_top1000`, `han` per row, so "is any of these in the top 500?" is
answerable without opening a database. The three Latin rows are kept in the file with
`han=false` for traceability, and are excluded from every ratio above.

## 4. Task C: variant mapping is a proposal, and a thin one

`review/stroke_variant_map.csv` — 40 rows, `decision` empty, **not applied anywhere**.

Source: `Unihan_Variants.txt` from the same UCD 18.0.0 zip used for the stroke counts
(`Unihan.zip` sha256 `4c93ea9c1f636451729a840978f1667a53886af37ba854fdcce109721c63d43e`,
matching the checksum recorded in Stage 1). Tool: `tools/propose_variants.py`.

| outcome | rows |
| --- | --- |
| usable candidate **that has stroke data** | **5** — 曏→向(6), 爲→为(4), 綫→线(8), 説→说(9), 説→說(14), 齣→出(5) |
| no candidate recorded in Unihan | 34 |
| candidate without stroke data | 1 |

The 34 are the disappointing part and it is not fixable by cleverness: Unihan simply
does not record `爲→為`, `眞→真`, `箇→個` as `kTraditionalVariant`/`kSimplifiedVariant`
in this release. So a variant map can rescue **5 of 38** missing characters, not most
of them.

**How the panel would show an approved mapping** (not implemented): the animation plays
for the standard form and the label reads `Stroke order of the standard form 為`; the
headword itself is never rewritten, never silently swapped, and the note stays visible
for the whole playback. Without your approval, those headwords keep
"Stroke order not available".

## 5. Task D: the animation, not just the end state

`docs/screenshots/character-panel/`:

| file | content |
| --- | --- |
| `07_frames_我.png` | 我 at 0 / 25 / 50 / 75 / 100 %, stroke numbers, count label |
| `07_frames_永.png` | 永 — the eight basic strokes |
| `07_frames_都.png` | 都 — labelled `(disputed: Unihan disagrees…)` |
| `07_frames_學.png` | 學 — dense character, 16 strokes |
| `07_frames_这.png` | 这 — the 辶 case |
| `08_radical_no_font.png` | radical row **without** the SimHei override |
| `09_missing_no_font.png` | missing-data fallback **without** the SimHei override |

**Why the no-font renders look half-broken, and why that is the point.** A
`flutter test` engine render has no CJK font: every glyph falls back to Ahem, which
draws boxes. The character body is **vector paths** and is unaffected — so in `08` the
character 我 is perfect while every surrounding label is a block of black squares.
That is the honest demonstration that (a) the stroke rendering does not depend on any
font, and (b) every piece of *text* in the panel does. A device screenshot cannot show
this, because the device has fonts; an engine render can, precisely because it does not.

**A defect this stage caught, and fixed.** While assembling the frames it became
visible that the in-flight stroke (the pen) was painted 74 **device** pixels wide on
any canvas: `stroke_painter.dart` wrote `strokeWidth = 74 / scale` inside an already
scaled canvas, which cancelled the transform. At 100 % (the only state Stage 1
captured) the pen is not drawn at all, so it never showed. Now the width is `74`
**glyph units** (74/1024 em, the width Hanzi Writer draws with), so it scales with the
panel: ~11 px at a 160 px frame, ~17 px at the 240 px panel.

## 6. Task E: performance, measured in Dart

Built with `python tools/build_stroke_pack.py --top 3000 --out stroke_work/top3000`
(the `--out` flag writes the whole set outside `assets/`, so the shipped pack is
untouched).

| top-3000 | value |
| --- | --- |
| words | 3270 |
| wanted / packed / absent | 1921 / 1835 / 86 |
| raw payload | 5,099,681 B |
| gzipped payload | 2,073,302 B (2024.7 KB) |
| index | 60,372 B |
| word coverage | 3189 / 3270 = 97.5 % |
| words partial / none | 73 / 8 |

Dart numbers, from `test/stroke_pack_perf_test.dart` (this machine, not a phone):

```
top-3000: gunzip              22 ms
top-3000: index parse         19.188 ms  (1835 entries)
top-3000: first draw per char 我 9.67 · 的 0.64 · 學 1.03 · 醫 1.54 · 都 1.69 · 这 0.32 ms
top-3000: every char, paths   238 ms for 1835 chars, 36902 paths built
top-1000: StrokePack.load     29 ms, 934 chars   (assets → background isolate)
```

**These are desktop numbers and are labelled as such.** They replace the Stage 1
"index load 0.8 ms", which was a Python `json.loads` measurement and had no bearing on
the app. The phone number comes in Stage 2, in profile mode.

**How the panel loads the pack.** `StrokePack.load` is a memoised `Future`: it reads
both assets on first use, gunzips the payload and parses the 32 KB index **inside
`compute`**, i.e. on a background isolate, and returns immutable tables. Per-character
glyph parsing stays on the calling isolate because it is 0.3–1.7 ms per character
(`StrokeGlyph` is parsed lazily from the payload slice, only for the character being
shown). `CharacterPanel` never blocks on the heavy decode: it shows its frame, then
fills in.

One testing consequence, which was a **real failure** and is documented rather than
hidden: `flutter test` drives widgets under fake async, where an isolate's future never
completes inside `pumpAndSettle` — 22 panel tests timed out. `StrokePack` therefore
decodes inline when `Platform.environment['FLUTTER_TEST'] == 'true'`
(`debugDecodeInline` exposes the switch), with a comment in the source explaining why.
The app itself never takes that branch; the isolate path is what ships.

## 7. Task F: `disputed`

The index carries a `disputed` list: every character in `stroke_differences.csv` whose
`decision` is empty or `reject` — currently **all 59**.

- Undisputed character: `"7 strokes"`, semantics `"stroke count"`.
- Disputed character: italic `"Stroke order not reviewed"` instead of the number,
  semantics `"stroke count not reviewed"`. The animation still plays.
- Approving a row = putting a decision in the CSV and rebuilding; the note disappears
  for that character only.
- Token-themed like every other label, English only (`no_raw_colors_test` still
  passes; no Nepali anywhere in the panel).

## 8. Task G: licence follow-ups

1. **Dates come from the build.** `build_info.json` and the generated
   `lib/features/character/stroke_build_info.dart` carry the date, count and sha256;
   the Credits sentence interpolates them. `test/stroke_license_audit_test.dart` fails
   if the doc and the generated constant disagree, and also fails if the Credits source
   contains a hard-coded `YYYY-MM-DD`.
2. **"The repository is the designated place" is removed** from
   `docs/LICENSE-ARPHIC.md` §3. It is now two options with a recommendation: **A**
   make the main repo public (rejected — it would expose `backend/`, the Supabase
   schema and auth code); **B (recommended)** a small dedicated public repo or page
   holding only the pack, the index, the build script and `ARPHICPL.TXT`, linked from
   Credits. The main repository stays private.
3. **The GPL-libraries analogy is deleted**; the aggregation argument now rests on the
   APL aggregation clause alone. **APL §2(c)** (notice for programs that read commands
   interactively) and the "does option B need the pre-conversion JSON?" question are
   added to the lawyer list (§7 items 8 and 9).

## 9. Task H: the merge conflict in `settings_provider.dart`

Nothing was merged. The current uncommitted change to that file (7 hunks, one new key)
will collide with Phase 1b, which rewrites the same file to add six keys.

Current change (character panel, on `character-panel`):

| # | location | what it adds |
| --- | --- | --- |
| 1 | `AppSettings` fields | `final double strokeSpeed;` |
| 2 | constructor | `this.strokeSpeed = 1.0,` |
| 3 | `copyWith` | `double? strokeSpeed,` + `strokeSpeed: strokeSpeed ?? this.strokeSpeed,` |
| 4 | `SettingsKeys` | `static const strokeSpeed = 'settings.strokeSpeed';` |
| 5 | `_hydrate`/`load` | `strokeSpeed: _clampSpeed(prefs.getDouble(...)),` |
| 6 | `save` | `await prefs.setDouble(SettingsKeys.strokeSpeed, s.strokeSpeed);` |
| 7 | helpers | `setStrokeSpeed(double)` + `static double _clampSpeed(double?)` |

Phase 1b changes the same seven anchors to add `nepaliEnabled`, `chineseVariant`,
`romanisation`, `toneColors`, `toneColorsInLists`, `silentMode`.

**Conflict shape:** hunks 1, 2, 3, 5, 6 are *adjacent-line* edits in the same block —
git will report a conflict because both sides append to the same line range, but the
resolution is mechanical: **keep both**, ordered by key name.

**The one real semantic conflict is hunk 7:** Phase 1b adds
`static double _clampScale(double?)`-style helpers and my `_clampSpeed` sits next to
them; and Phase 1b's `romanisation` converter is a *string* setting with its own
validation, so it will want a `_romanisationByName` helper in the same tail block.

**Proposed merge order** (no action taken):

1. Land Phase 1b on `settings-features` first (it touches more of this file, and it has
   the migration test).
2. Rebase `character-panel` onto it.
3. Resolve by keeping both sides at hunks 1–3, 5–6; at hunk 7 keep `_clampSpeed` above
   the Phase 1b helpers, so validation helpers stay grouped.
4. Keep the panel's use of `settings.strokeSpeed` unchanged — one key, no second
   spelling.
5. Run `flutter test test/settings_provider_test.dart test/character_panel_test.dart`
   after the rebase; a missing key shows up as a failing round-trip.

Doing 1b first is the cheaper order: it is the bigger diff, and it already has the
migration test that would catch a lost key.

## 10. Verification commands and their output

```
flutter analyze
  No issues found!  (ran on the final tree)

flutter test --no-pub
  00:08 +160: All tests passed!
```

New or changed tests in this stage: `stroke_review_captures_test.dart` (contact sheet +
5 frame sequences + disputed label), `stroke_captures_no_font_test.dart` (Ahem control
renders), `stroke_pack_perf_test.dart` (the Dart numbers above), plus assertions added to
`stroke_pack_test.dart` (source-count agreement, disputed list),
`character_panel_test.dart` (disputed hides the count, undisputed prints it, 都's
radical is 邑) and `stroke_license_audit_test.dart` (generated date vs doc, no literal
date in Credits, `source_counts.json` covers every packed character).

Two test-side fixes found while verifying: the disputed test expected the radical row
to say `阝` — the app shows the unified ideograph 邑 (Kangxi radical 163), so the test
was wrong and the app was right; and the frame captures overflowed the default 800 px
test surface, so the surface is now sized to the row.

## 11. Stage 2: what running it on the phone actually showed

Device: SM-M166P (Samsung, Android 16 / API 36), profile build
`app-profile.apk`, installed with `adb install -r` only. Nothing was uninstalled and
`pm clear` was never run.

### 11.1 The blocker first: the panel is not reachable in the app

`CharacterPanel` is referenced by **no screen**. `grep CharacterPanel lib/**` returns
only its own file, and `StrokePack.load` is called only from inside it. So on the phone
there is no gesture, menu or page that opens the panel — Stage 1 built and tested the
component and wired only its licence text into Credits, but never mounted it.

That is why "run it on my device" cannot mean "tap it": there is nothing to tap. The
numbers below were therefore taken with test code that mounts the widget directly
(`integration_test/stroke_device_test.dart`, run with `flutter drive --profile`), which
exercises the shipping decode path and the real rasteriser without adding a feature.

**Wiring it in is a product change and I did not make it.** It needs your word: the
natural place is the word-detail page, one `CharacterPanel(characters: …)` under the
gloss cards, which is roughly 10 lines plus a test.

### 11.2 Measured on the device, profile mode

| measurement | value |
| --- | --- |
| `StrokePack.load` (assets → gunzip → index parse, background isolate) | **74 ms** (repeat run 181 ms, cold start with the test harness) |
| process RSS before / after the load | 187.1 → 209.6 MB, **delta 22.5 MB** (includes the whole test harness, not just the pack) |
| first glyph 我 (parse + path build) | **437 µs** (7 strokes) |
| 學, 16 paths | **427 µs** |
| animation frames collected | 93 |
| worst frame build / raster | **63.7 ms** (first frame) / **9.3 ms** |
| frames over 16.67 ms | **2 of 93** — both at the start, none during steady playback |

For comparison, the same load on this desktop was 29 ms, so the phone is **~2.5× the
desktop**. That is exactly why the Python "0.8 ms" figure in Stage 1 was meaningless.

**One honest caveat about the frame numbers.** The average interval reported by the
harness (6.8 ms, "147 fps") is not a real-world frame rate: `flutter drive` pumps frames
faster than the display consumes them. The numbers that mean something are the per-frame
**build** and **raster** costs and the count of frames over 16.67 ms — a 16.7 ms budget
with 63 ms spent on the very first frame, then nothing over budget for the remaining 91.

### 11.3 "Remove animations" could not be verified from adb

The panel does honour the flag: with `MediaQuery.disableAnimations` true it draws the
finished character, hides Play, and prints "Animation is off because reduced motion is
enabled in system settings." That branch is covered by widget tests.

On the device, setting `settings put secure accessibility_disable_animations 1` did
**not** reach the app — the panel still showed Play and still animated (93 frames again).
So the Android secure setting I can reach over adb is not the flag Flutter reads on this
build. **Status: NOT VERIFIED on device**, verified only in widget tests. Confirming it
by hand (Settings → Accessibility → Remove animations) needs a human tap; I left the
setting restored to `0`.

### 11.4 A second finding: two "Popular words" have no stroke data

The home screen lists `light · 光` and `mountain · 山`. Neither 光 nor 山 is in the
shipped top-1000 pack:

```
assets/strokes/strokes.index.json  →  光 False   山 False   我 True   水 True
stroke_work/top3000/…              →  光 True    山 True
```

Cause: these two characters sit at `freq_rank` 1503 and 1428, outside the top-1000 word
set the pack is built from — even though they are in the app's own Popular words. The
panel is honest about it ("This character is not in the stroke data set (top 1000
words)"), but the effect is that a user tapping the app's own featured word sees no
stroke order.

Both are covered by the **top-3000** pack already built in `stroke_work/top3000/`
(1835 characters, 2024.7 KB gzipped) — so the fix is switching the shipped pack to that
build, not new data.

**Resolved 2026-11-15: the shipped pack is now the top-3000 build.** Rebuilt with
`python tools/build_stroke_pack.py --top 3000`, which rewrites
`assets/strokes/*` and the generated `lib/features/character/stroke_build_info.dart`:

| | top-1000 (before) | top-3000 (shipped now) |
| --- | --- | --- |
| characters wanted / packed / absent | 975 / 934 / 41 | **1921 / 1835 / 86** |
| payload raw / gzipped | 2,457,029 B / 1,001,505 B (978.0 KB) | **5,099,681 B / 2,073,302 B (2024.7 KB)** |
| index | 32,478 B | **61,109 B** |
| words fully covered | 1101/1140 (96.6%) | **3189/3270 (97.5%)** |
| partial / none | 36 / 6 | **73 / 8** |
| disputed characters | 59 | **123** |
| 光 / 山 present | no | **yes** |

The asset grew by 1.05 MB (978.0 KB → 2024.7 KB gzipped), and the disputed set grew from
59 to 123 because a wider word set reaches more characters whose count disagrees with
Unihan. `test/stroke_pack_test.dart` now asserts `topWords == 3000` and
`characterCount > 1800`; the perf, capture and review-capture tests follow the shipped
pack rather than a hard-coded band.

## 12. Decisions I need from you

1. **Stroke-order standard.** Recommendation: **Simplified → mainland (PRC) counts and
   order; Traditional → Taiwan.** This is exactly what the pack contains (Arphic ships
   a GB-style and a Big5-style face), and it is why 这 = 7 while 這 = 10. Saying yes
   means the 18 辶 rows get `accept` and lose the disputed note.
2. **Variant mapping: yes or no.** Only 5 of 38 can be resolved from Unihan. Approving
   the labelled fallback ("Stroke order of the standard form 為", never a silent swap)
   covers those 5; the other 33 stay "not available".
3. **Where the public copy of the stroke data lives** (§8 option B — a small dedicated
   repo or page linked from Credits).
4. **Local WIP commit?** The whole stage is still only in the working tree. I can commit
   it locally on `character-panel` with explicit paths, no push.
5. **59 rows still need a `decision`.** Accepting the PRC 辶 convention clears 18 of
   them; 都 and 这 clear with the same decision if you take option 1.
6. **Mount the panel in the app?** It is not on any screen today (§11.1). One widget
   insertion on the word-detail page, ~10 lines plus a test. Without it there is nothing
   for a user (or you) to open on the phone.
7. **Ship top-1000 or top-3000?** Top-3000 fixes 光 and 山 and any other popular word
   outside the first 1000 (§11.4), at 2024.7 KB gzipped instead of 978 KB.

**What was done on the phone is reported in §11 and nothing beyond it**: one profile
build installed with `adb install -r`, one measurement run, one system setting changed
and restored. No uninstall, no `pm clear`, no push.

## 13. Decisions applied (2026-11-15)

- **Panel mounted.** `lib/features/detail/detail_screen.dart` now builds
  `CharacterPanel` under the image card, one tab per character of `wordZh`, seeded
  from `settings.strokeSpeed` and persisting through `setStrokeSpeed`. Panel is
  skipped when `wordZh` is blank. `test/detail_screen_stroke_panel_test.dart` guards
  it in both directions (panel present for 光, absent for a blank-Chinese entry) and
  the test loads the real pack, so a future un-mounting fails CI rather than being
  discovered on a phone weeks later.
- **Top-3000 shipped** (§11.4), which is what makes the mount useful: 光 and 山,
  the two words the home screen promotes, now have stroke data.
- **Licence decision reversed to option A** in `docs/LICENSE-ARPHIC.md`, because the
  repository is being made public: the repository itself is now the designated
  place under APL §2(b). Option B remains documented as the answer if the repository
  ever goes private again.

Still open from §12: items 1–5 (stroke-order standard, variant mapping, the 59/123
`decision` rows).

Ready for second render review.
