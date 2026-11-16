# Phase 1 — Settings overhaul + theme: proposed plan (for review, no code yet)

Branch: `settings-features` (branched from `auth-system` @ `4a5b1f1`). Nothing committed, nothing pushed.
Phase 1 only. Phase 2/3/4 are referenced where a Phase 1 decision locks something in.

Status legend used throughout: DONE / VERIFIED (tests) / VERIFIED (device) / NOT VERIFIED / BLOCKED.

---

## 0. What the codebase already has (read, not assumed)

| Fact | Evidence |
| --- | --- |
| Dark theme does not exist | `lib/app/app.dart:18-19` — `theme: AppTheme.light, darkTheme: AppTheme.light`; `lib/app/theme/app_theme.dart` only defines `light` |
| 86 hard-coded colours in 14 files | counted with `Select-String -Pattern "Color(0x"` per file |
| `uiLanguage` is stored but never read | grep `uiLanguage` in `lib/**` → 0 hits outside `settings_provider.dart` / `settings_screen.dart` |
| No l10n infrastructure | `pubspec.yaml`: no `flutter_localizations`, no `generate: true`, no `.arb` files |
| No `nepali_enabled` flag | grep `nepali_enabled|nepaliEnabled` across `lib`, `docs`, `backend` → 0 hits |
| No stroke-order data | `assets/` = images + `dictionary.sqlite.gz` only; `characters(char, radical, strokes INTEGER, pinyin, definition_en)` has a count, not a path |
| No flashcards / training | grep `flashcard|training` in `lib/**` → 0 hits |
| Pinyin is already in the DB | `entries` has `pinyin_num`, `pinyin_marked`, `pinyin_plain`, `pinyin_search`; `characters` has `pinyin` |
| Settings persist in shared_preferences with stable keys | `lib/features/settings/settings_provider.dart:45-52` (`SettingsKeys`, prefix `settings.`) |
| `user.db` has a `prefs(k,v)` table, currently unused for these settings | `lib/data/local/user_store.dart:163` |
| Theme choice is already wired to `themeMode` | `app.dart:20` — so only `ThemeData` for dark is missing |
| Existing test pins the current layout | `test/settings_screen_test.dart` expects 'Settings', 'Text size', one Slider, and scrolls to 'TTS diagnosis' |

Consequences for the spec:

- **1C (stroke animation)** → not buildable. Report as "not available: no stroke-order data in the packaged DB or assets". No paid typeface added.
- **1E (level / training modes / strictness / flexible training / notes / existing cards)** → not buildable. Report as "no training feature exists".
- **1B (Zhuyin + numeric tones)** → buildable purely from stored `pinyin_marked` / `pinyin_num`; no new data needed.
- **Rule 7 (nepali_enabled)** → the flag must be created in Phase 1 (it does not exist yet).

---

## 1. Proposed Settings layout

One scrollable `ListView` of grouped cards. Group header = small caps label; each card = `Card`-like surface with rows.
Order top → bottom. "Account" stays at the very top as today.

### Group 0 — Account (kept, not redesigned)
| Control | Type | Behaviour |
| --- | --- | --- |
| Account | tile → `/auth` | subtitle still driven by `authTokenProvider` (signed-in / signed-out) |
| My favorites | tile → `/favorites` | unchanged |

### Group A — Appearance
| Control | Type | Options | Storage key | Default |
| --- | --- | --- | --- | --- |
| Theme | 3-way segmented | Follow system / Light / Dark | `settings.themeMode` (existing key, values `system`/`light`/`dark`) | **`system`** (was `light`) |
| Text size | slider 0.8–1.4, live `%` label | — | `settings.textScale` (existing) | `1.0` |
| App language | 3-way segmented | English / 中文 / नेपाली | `settings.uiLanguage` (existing, `english`/`chinese`/`nepali`) | `english` |
| Show Nepali | switch + ⓘ | on/off | **`settings.nepaliEnabled`** (new) | `true` |
| Chinese characters | 4-way radio group + ⓘ | Simplified only / Traditional only / Both, simplified first / Both, traditional first | **`settings.chineseVariant`**: `simp` / `trad` / `both_simp` / `both_trad` | `both_simp` |
| Default input language | 2-way segmented | EN / 中文 | `settings.defaultInputLang` (existing) | `english` |
| Offline-first search | switch | — | `settings.offlineFirst` (existing) | `true` |

`Show Nepali ⓘ` text: "When off, Nepali translations are hidden everywhere and the daily word shows English + Chinese only." When `uiLanguage == nepali` and the switch is turned off, the UI language falls back to English (and the segmented control shows English selected) — no Nepali rendering anywhere, per rule 7.

### Group B — Pinyin & tones
| Control | Type | Options | Storage key | Default |
| --- | --- | --- | --- | --- |
| Romanisation | 3-way radio + ⓘ | Pinyin with tone marks / Pinyin with numbers / Zhuyin (Bopomofo) | **`settings.romanisation`**: `marks` / `numbers` / `zhuyin` | `marks` |
| Tone colours | 2-way radio + ⓘ | Off / Regular / Colour-blind-safe (3rd option, see below) | **`settings.toneColors`**: `off` / `regular` / `safe` | `off` |
| Live preview | read-only text row | `mā má mǎ mà ma` rendered in the chosen palette + romanisation | — | — |
| Apply tone colours in lists | switch, only enabled when tone colours ≠ Off | — | **`settings.toneColorsInLists`**: bool | `false` |

Colour-blind-safe mode: tone is distinguished by **both** hue and an added mark/diacritic weight (never colour alone), palette chosen to stay distinguishable under deuteranopia/protanopia simulation; also verified at WCAG AA (4.5:1) on both themes. Regular mode keeps hue only but still passes AA.

### Group C — Writing
**Omitted.** No stroke-order data. Nothing rendered in the UI; listed as `NOT AVAILABLE` in the final report (as the spec instructs).

### Group D — Sounds & notifications
| Control | Type | Options | Storage key | Default |
| --- | --- | --- | --- | --- |
| Sound | switch (existing) | — | `settings.soundEnabled` (existing) | `false` |
| Silent mode | switch + ⓘ | — | **`settings.silentMode`** (new) | `false` |
| Daily word | switch + time picker | time default 09:00 | `settings.dailyWordEnabled` / `settings.dailyWordTime` (`HH:mm`) | `false` / `09:00` |
| Notification permission state | inline banner (Phase 3 wiring) | "Permission needed → Open settings" | — | — |
| Send test notification | button, debug / About→Developer only | — | — | — |

Semantics proposed (needs your OK): `soundEnabled` = the audio subsystem master (already exists, do not rename, so nothing resets). `silentMode` = "do not auto-play audio"; manual tap-to-play still works while `soundEnabled` is on. Two switches, no overlap.

The Daily-word group ships **disabled** in Phase 1 with helper text "Available after the notification phase" unless you prefer it hidden until Phase 3 — see question 2.

### Group E — Data & quality
| Control | Type | Target |
| --- | --- | --- |
| About data quality | tile | `/data-quality` (existing) |
| Credits & licences | tile | `/credits` (existing) |
| Privacy policy | tile | existing inline dialog (unchanged content in Phase 1; Phase 4 rewrites it) |
| TTS diagnosis | tile, debug builds only | `/tts-debug` (keep for now; the existing widget test scrolls to it) |

### Group F — About
| Control | Type | Content |
| --- | --- | --- |
| App version | read-only row | `Trilingual Dictionary v0.1.0` (from `pubspec` via a small constant; no `package_info_plus` dependency unless you allow it) |
| Dictionary version | read-only row | `Dataset v${AppConstants.datasetVersion}` + `assetVersion` once Phase 2 regenerates it |
| Contact | tile | `mailto:` to the address currently `[CONTACT_EMAIL]` in `docs/PRIVACY_POLICY.md` — shown as a copyable text only until you give a real address |
| Developer | collapsible, debug only | "Send test notification now" (Phase 3) |

Interaction rules: every row has a fixed-height trailing slot so the layout never jumps when a subtitle appears/disappears; every control gets an explicit `Semantics(label:, hint:)`; min touch target 48 dp; ⓘ opens an `AlertDialog` with the long explanation.

---

## 2. Storage keys (full list after Phase 1)

Existing, **unchanged names and value encoding** (so an upgrade resets nothing):

| Key | Type | Values |
| --- | --- | --- |
| `settings.themeMode` | String | `system` / `light` / `dark` |
| `settings.textScale` | double | 0.8 – 1.4 |
| `settings.uiLanguage` | String | `english` / `chinese` / `nepali` |
| `settings.defaultInputLang` | String | `english` / `chinese` |
| `settings.offlineFirst` | bool | — |
| `settings.soundEnabled` | bool | — |

New in Phase 1 (prefix `settings.`, same store):

| Key | Type | Values | Notes |
| --- | --- | --- | --- |
| `settings.nepaliEnabled` | bool | default `true` | rules 7 + Phase 3 |
| `settings.chineseVariant` | String | `simp` / `trad` / `both_simp` / `both_trad` | consumed in Phase 2 rendering |
| `settings.romanisation` | String | `marks` / `numbers` / `zhuyin` | converter lives in `lib/core/pinyin/` |
| `settings.toneColors` | String | `off` / `regular` / `safe` | token palette, not literal colours |
| `settings.toneColorsInLists` | bool | default `false` | search results, examples, breakdowns |
| `settings.silentMode` | bool | default `false` | — |

Reserved for Phase 2/3 (declared now so nobody invents a second spelling later):

| Key | Type | Values |
| --- | --- | --- |
| `settings.sentencePinyin` | String | `above` / `below` / `off` (Phase 2, default `above`) |
| `settings.dailyWordEnabled` | bool | Phase 3 |
| `settings.dailyWordTime` | String | `HH:mm`, Phase 3, default `09:00` |
| `settings.dailyWordCursor` | String (JSON) | Phase 3 rotation state, device-local |

Backwards compatibility: `_themeByName` currently maps anything unknown to `light`. It will map unknown/absent to **`system`**, but a stored `light`/`dark` keeps winning — so a user who already chose Light stays on Light. Same for every other key: absent → new default, present → kept. A migration test will assert this.

---

## 3. Theme approach

1. **Two real themes.** `AppTheme.light` and `AppTheme.dark`, both `ColorScheme.fromSeed(LanguageColors.brand, brightness: …)`, sharing one builder so component shapes/typography cannot drift. `app.dart` gets `darkTheme: AppTheme.dark` (today it reuses light).
2. **Semantic tokens instead of literals.** New `AppTokens` `ThemeExtension` carrying: `surface`, `surfaceElevated`, `border`, `textMuted`, `textStrong`, `brand`, `brandSoft`, `zh`, `zhSoft`, `ne`, `neSoft`, and the tone palette `tone1..tone4` (+ `safeTone1..4`). Both themes instantiate it; widgets read `Theme.of(context).extension<AppTokens>()!`. The 86 literal `Color(0x…)` sites migrate to these tokens group of file at a time, screen by screen, with `flutter analyze` + the existing widget tests after each screen.
3. **No theme-dependent logic in widgets.** Any `if (brightness == dark)` branch is a review failure; only tokens.
4. **Contrast gate.** A test computes relative luminance and asserts ≥ 4.5:1 for text-on-surface pairs and ≥ 3:1 for large text/icon pairs, in both themes, plus the tone palette in both themes. Numbers land in the report; failure fails the build.
5. **Font scaling vs the existing override.** Today `app.dart:21-26` replaces the platform `textScaler` with `TextScaler.linear(settings.textScale)`, which **discards the phone's font-size setting** — that will break the Phase 4 "200 % without clipping" requirement. Proposal: effective scale = `MediaQuery.textScalerOf(context).scale(1.0) * settings.textScale`, clamped to `2.0`. This is a behaviour change, so it is called out here rather than slipped in.
6. **Dark-mode proof on device.** With the phone in system dark: app set to Light must stay light; set to Dark must stay dark; Follow-system must follow. Screenshot + `uiautomator dump` text for each of the three, then the same with phone in light. That is the evidence for "in-app choice wins".

---

## 4. Files Phase 1 will touch (when you say go)

| File | Change |
| --- | --- |
| `lib/app/theme/app_theme.dart` | add `dark`, shared builder, `AppTokens` extension |
| `lib/app/app.dart` | `darkTheme`, combined text scaler |
| `lib/features/settings/settings_provider.dart` | new fields, keys, parse/save, migration-safe defaults |
| `lib/features/settings/settings_screen.dart` | full rebuild (grouped cards, ⓘ dialogs, semantics) |
| `lib/core/l10n/app_strings.dart` (new) | Settings strings in en/zh/ne + `nepaliEnabled` fallback |
| `lib/core/pinyin/romanisation.dart` (new) | `marked → numeric` and `marked → zhuyin` converters + tests |
| `lib/core/theme/tone_palette.dart` (new) | tone colours, both modes |
| ~10 screen/widget files | replace literal colours with tokens |
| `test/settings_screen_test.dart`, new `test/settings_*.dart` | keep the old assertions working, add per-control + persistence + contrast tests |
| `docs/SETTINGS-FEATURES-PLAN.md` | this file, updated with measured numbers |

Nothing in `backend/`, nothing in `supabase/`, no auth files.

---

## 5. Test plan for Phase 1 (what will back each DONE claim)

- Unit: defaults; `copyWith`; legacy-value hydration (`themeMode=light` stays light; absent → system); every new key round-trip; `romanisation` converter (`mā = ma1 = ㄇㄚ`, `lǜ = lv4 = ㄌㄩˋ`, neutral tone `ma = ma5`, er-hua, apostrophe `Xī'ān`).
- Widget: each control renders, is tappable, writes the expected key; ⓘ opens; TalkBack label present on every interactive node; no overflow at 1.0× / 1.4× / 2.0×; both themes.
- Contrast test: token pairs + tone palette, both themes.
- Persistence: set values → dispose → rebuild with the same mock store → values survive; and a "kill and relaunch" check on the device (force-stop + relaunch, read the UI back).
- Device: 3 screenshots × (phone dark on / off) for theme; screenshots + `uiautomator` text for each section; Settings first-frame latency measured (report the number, no estimate).
- Regression: `flutter analyze --no-pub`, full `flutter test`, and the existing `settings_screen_test.dart` must still pass unchanged.

---

## 6. Open decisions I need from you before coding

1. **Silent mode vs Sound.** Is "Sound = master audio switch" + "Silent mode = don't auto-play" the split you want, or should Silent mode simply reuse `soundEnabled` inverted (one switch, no new key)?
2. **Daily-word controls in Phase 1.** Ship them disabled with "available after the notification phase", or hide entirely until Phase 3 (cleaner, but then Phase 1D is empty)?
3. **Localisation scope.** Phase 1 localises **Settings only** (its rows, helper text, ⓘ dialogs) into en/zh/ne. The other ~12 screens stay English; making them trilingual is a separate phase and a large diff. Confirm that boundary is acceptable, or state that Phase 1 must go app-wide.
4. **Chinese variant default.** `Both, simplified first` (current visual order) — or `Simplified only` as the default for a learner-first app?
5. **App version source.** Read-only `v0.1.0` hard-coded constant, or add `package_info_plus` (one new dependency) so it can never lie?
