# Stage 1 — minimal character stroke panel

Status of this document: **engineering report for review.** Everything below was
measured on this machine on 2026-11-15, on branch `character-panel`, with
nothing committed, no phone attached and no APK built.

Scope actually delivered: one gzipped stroke pack plus index for the top-1000
words, a licence reading, a Unihan stroke-count cross-check with a review CSV,
one panel widget, one setting key, tests, and engine-rendered screenshots.
Not delivered, by instruction: emoji work, photo work, Nepali glosses, any
device measurement, any integration into the result screen.

## 1. Data: what the pack contains

| item | value |
| --- | --- |
| words used to pick characters | top 1000 by `freq_rank` (1140 rows carry a rank) |
| distinct characters required | 975 |
| characters with stroke data | 934 |
| characters with no source data | 41 codepoints = **38 Han characters + 3 Latin letters** (`A B T` come from words such as `A股` and `T恤`; the 38 Han are `㕁 㕥 㝡 㧱 㨿 㳒 亁 卽 呌 咊 咲 喫 囙 嵗 幇 幚 拏 旹 昰 曏 朞 榦 灋 爲 眞 秊 秖 竝 箇 綫 翫 芲 蘤 説 諙 逥 齣 龢`) |
| raw payload | 2,457,029 B |
| gzipped payload | 1,001,505 B (978.0 KB) |
| index | 31,994 B (32,478 B after Stage 1b added the `disputed` list) |
| build wall time | 420 ms (whole tool run, including the Unihan check) |
| index cold load (Python `json.loads`) | 0.8 ms — **a Python number, not an app number**; the Dart figures are in §3a |
| single character load (Python) | 我 0.02 ms, 的 0.02 ms, 水 0.01 ms, 學 0.02 ms, 醫 0.11 ms |
| words whose every character is present | 1098 / 1140 = **96.3 %** (letters counted as missing; 1101 / 1140 = 96.6 % if they are skipped, which is what the app does — see `docs/STROKE-PANEL-STAGE1B.md`) |
| words with some characters missing | 36 |
| words with no character at all | 6 |

The 38 absent Han characters are almost entirely CC-CEDICT variant rows (`昰`,
`咊`, `龢`, `爲`, `眞`…), i.e. forms that exist as headwords but for which the
stroke source has nothing. They are shipped as-is: the panel shows the plain
character with "Stroke order not available". No fallback glyph and no guessed
stroke count is substituted.

The top-3000 set is one argument away: `python tools/build_stroke_pack.py --top 3000`
rebuilds the pack, the index, the README and the review files (measured numbers in
`docs/STROKE-PANEL-STAGE1B.md`).

## 2. Quality check against Unihan

Every packed character was compared against Unihan `kTotalStrokes`
(Unicode 18.0.0, UCD `Unihan_IRGSources.txt`). **`difference = pack_strokes −
unihan_strokes`** — the sign convention is stated here because an earlier version
of this document had it inverted.

| result | count |
| --- | --- |
| compared | 934 |
| agree | 875 (93.7 %) |
| differ by −2 | 3 |
| differ by −1 | 50 |
| differ by +1 | 5 |
| differ by +3 | 1 |

This is **not** 59 errors, and it is not a builder bug either: every packed
character's stroke count was compared against the raw
`hanzi-writer-data@2.0.1` file and **934 / 934 agree, 0 mismatches** (Stage 1b).

The −1 cluster is one systematic convention difference: the stroke source counts
辶 as **3** strokes (PRC writing convention), while Unihan counts it as **4**
(Kangxi/Taiwan convention). Because the formula is pack − Unihan, that gap shows
up as **−1**. 18 of the 59 rows are 辶-radical characters and every one of them is
exactly −1 (达, 过, 迎, 近, 还, 这, 连, 送, 选, 通, 造, 進, 運, 過, 道, 達, 那 …).
Note that in this Unihan release `kTotalStrokes` carries a **single** value for
every one of the 934 characters (no two-value "PRC Taiwan" lines), and that value
follows the Kangxi count — `都` = 12 (者 9 + 阝 3), `者` = 9, `之` = 4.

Every differing character is listed in `review/stroke_differences.csv` (59 rows,
`decision` blank), and the sample to eyeball is `review/stroke_spot_check.csv`
(198 rows: the 100 most frequent characters + 50 random with the seed recorded +
every differing character), with a numbered contact sheet at
`docs/screenshots/character-panel/06_contact_sheet.png`.

Consequence for the UI: stroke counts shown to the user come from the stroke data
itself (so the animation and the printed count always agree), not from Unihan. If
a PRC-convention count is required later, it has to be a deliberate mapping
decision, not a silent correction.

## 3. What the panel does

`lib/features/character/character_panel.dart`, painted by
`stroke_painter.dart`, fed by `stroke_pack.dart`.

- One character at a time; the characters of a word are tabs, and the drawing
  area also responds to a horizontal swipe.
- Play / Replay button; the animation walks the stroke medians and fills the
  stroke outlines as each stroke completes.
- Speed slider bound to `settings.strokeSpeed` (0.5×–2.0×, default 1.0×). This is
  the only settings key the panel adds; `SettingsNotifier.setStrokeSpeed`
  clamps it and persists it. The slider lives inside the panel because Phase 1b
  owns the Settings screen.
- Radical row: Kangxi radical as an ordinary ideograph plus its official
  Unicode name, e.g. `Radical 戈 · halberd (62)`. Both values come from
  Unihan `kRSUnicode` and the Unicode Kangxi radical names; nothing was
  hand-written or translated.
- Missing data: the plain character at display size plus "Stroke order not
  available" and the reason. Never an error screen.
- Design tokens only (`context.tokens`), so `no_raw_colors_test` passes and the
  panel follows light/dark and the app's own theme choice.
- Accessibility: each character is one semantics node labelled
  `我, 7 strokes, Radical 戈 · halberd (62)`; the painter area is excluded from
   semantics so the label is not read twice; Play and the character tabs are at
  least 48 dp; when `MediaQuery.disableAnimations` is true the finished
  character is shown with no animation and Play is not offered.
- 2.0× text scale: the panel does not grow with the window (the drawing area is
  capped at 240 dp) and the surrounding page scrolls, so nothing overflows.

## 4. Licence

`docs/LICENSE-ARPHIC.md` records what is bundled, which licence covers which
file, the required notice, the redistribution question, how it coexists with the
CC BY-SA dictionary data, and the questions for a lawyer. Short version: we use
only the stroke layer, which is Arphic Public License; the radical/decomposition
layer of the same upstream project is LGPL and is **not** used. The licence text
ships verbatim at `assets/strokes/ARPHICPL.TXT`, the conversion is stated in
`assets/strokes/README.md`, and the Credits screen carries the attribution.

## 5. Tests

`flutter analyze`: no issues. `flutter test`: **143 passing** (37 of them new in
this stage).

| test file | what it pins |
| --- | --- |
| `stroke_pack_test.dart` | pack/index agreement, checksum, 934+ characters, 我 = 7 strokes, missing characters stay missing, radical number/name come from Unihan+Unicode, SVG parser handles M/L/Q/C/Z, relative coordinates, implicit pairs, `M 10-5`, and throws on unsupported commands |
| `stroke_painter_test.dart` | pixel counts at 0 %, 50 %, 100 % (0 ink, some ink, more ink), guides optional, `shouldRepaint` honest |
| `character_panel_test.dart` | light and dark, radical row, missing-data fallback, multi-character tabs, one combined semantics label, reduced motion, 2.0× with no overflow, slider reports upward, no Devanagari when Nepali is off, 48 dp targets |
| `stroke_speed_settings_test.dart` | `settings.strokeSpeed` persists, clamps to 0.5–2.0 |
| `stroke_license_audit_test.dart` | `assets/strokes/` ships the payload, index, `ARPHICPL.TXT` and README; the licence text is complete; README states source, checksum and conversion; Credits mentions the attribution; the licence doc exists and says it is not legal advice |
| `character_panel_screenshots_test.dart` | regenerates the screenshots below |

## 6. Evidence

`docs/screenshots/character-panel/`: engine renders of the widget tree at
360×720 @2×, generated by the test above.

| file | shows |
| --- | --- |
| `01_light.png` | light theme, 我, radical row, Play, speed |
| `02_dark.png` | same in dark |
| `03_missing_data_light.png` | 昰 — the honest fallback |
| `04_multi_char_dark.png` | 学 / 生 tabs, second character selected |
| `05_text_200_dark.png` | 2.0× text scale with reduced motion |

Caveat, stated because it matters: these are `flutter_test` renders. They show
the widget tree and the strokes, not the phone's compositing, status bar or
splash. Device evidence is Stage 2 and has not been taken.

## 7. Known gaps and open questions

1. **The key is stored but not yet read by a screen.** `settings.strokeSpeed` is
   persisted and tested; nothing calls `SettingsNotifier.setStrokeSpeed` from the
   Settings screen yet, and the panel takes `speed` as a parameter. Phase 1b
   wires that row. The panel is also not mounted in the result screen yet.
2. **Variant handling is the caller's job.** The panel draws exactly the
   characters it is given. There is no `chineseVariant` setting yet (it arrives
   in Phase 1b), so "show the chosen form, fall back gracefully" is implemented
   as "the caller passes the form it wants; a character with no data falls back
   to the honest message". Nothing silently swaps 學 for 学.
3. **No Nepali radical names.** None exist that were reviewed, so the panel
   shows none and a test asserts no Devanagari appears when `nepaliEnabled` is
   false. It also shows none when it is true, because there is no reviewed text.
4. **59 Unihan differences need your decision** — `review/stroke_spot_check.csv`,
   `decision` column blank.
5. **The 41 absent characters need your decision** — ship the fallback (current
   behaviour), or drop those headwords from the band, or source another data set
   (no free equivalent exists with the same licence).
6. **`settings_provider.dart` conflict risk.** Phase 1b rewrites this file;
   this branch adds seven lines to it. Merge `character-panel` first, or expect
   a small conflict.
7. **Package size.** 978 KB compressed will be inside the APK, uncompressed in
   memory as 2.4 MB once loaded. Whether that is acceptable for an offline-first
   app is a product call; the top-3000 build will be roughly three times the
   payload.

## 8. Rules honoured

No commit, no push, no `flutter build apk`, no `adb` command of any kind,
`backend/` and `supabase/` untouched, no auth files touched, one settings key
added, no invented stroke, radical or translation data.
