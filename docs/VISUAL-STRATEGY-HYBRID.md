# Visual strategy: icons + selective photos + character-aid (measured)

Scope: decisions for Phase 1c/later image work. Everything below was measured on
this machine today; nothing is bundled, nothing written to the release DB.

## 0. Verdict

The hybrid you proposed is feasible, and one of its parts is far stronger than
photos can ever be. Measured:

| Layer | Source | Measured coverage | Cost |
| --- | --- | --- | --- |
| Character aid (stroke order + radical/parts) | hanzi-writer-data (Make Me a Hanzi) | **99.7% of top-3,000 headwords fully covered** (9,574 characters available) | data only, no photos, no fetching per word |
| Icons / emoji for concrete concepts | Unicode 15.1 emoji (rendered as text or bundled font) | **105 / 131 concepts (80%)** have a candidate glyph on a crude keyword match; hand-mapped it is higher | near zero |
| Real photos, selective | English Wikipedia lead image per concept | precision was 7/8 on the concepts Commons got wrong | ~3 s per concept + review |

Meanwhile photos as a universal answer remain capped: only **144 of the top 3,000
entries (4.8%)** carry a concrete visual concept at all (see
`docs/IMAGE-COVERAGE-PLAN.md`).

So the best answer to "how do we get pictures for 的/是/可以/会" is not pictures.
It is character structure.

## 1. Character aid — the biggest win, and it has data

`hanzi-writer-data` (npm, derived from Make Me a Hanzi) ships **9,574 single
characters**, each a JSON with stroke paths, stroke medians and the radical.

Coverage measured against this dictionary (`simplified`/`traditional`, entries with
`freq_rank`):

| Band | Headwords | Fully covered (every char has data) |
| --- | --- | --- |
| top 500 | 538 | **535 (99.4%)** |
| top 1,000 | 1,037 | **1,034 (99.7%)** |
| top 3,000 | 2,999 | **2,991 (99.7%)** |
| top 10,000 | 9,788 | **9,776 (99.9%)** |
| top 20,000 | 19,156 | **19,138 (99.9%)** |

That is the opposite profile from photos: photos are maximally useful exactly
where they are impossible (function words); stroke data is available almost
everywhere, including on those words.

**Licence — read this before building.** The data comes from Arphic fonts and is
distributed under the **Arphic Public License** (`ARPHICPL.TXT` is inside the
package). It is free for commercial use **but it is copyleft**: you must include
the licence text, keep attribution, and any derived stroke data you redistribute
stays under the same licence. Practically: fine for this app as long as the
credits screen lists it and you do not later try to make the stroke assets
proprietary. Not legal advice — worth one look from someone qualified if you ever
plan a paid/closed build.

**Size.** A per-character JSON is roughly 8–20 KB. Do not ship all 9,574. Ship the
characters the launch set actually needs (top-3,000 headwords touch ~5,340 distinct
characters); gzipped that is single-digit MB, and a subset of ~1,200 chars (top
1,000 words) is ~2–3 MB. Rendering: a `CustomPainter` over the stroke medians,
with a progress value for the animation — no video, no Lottie, no GIF.

## 2. Icons / emoji — cheap base layer, but it needs a hand map

Unicode 15.1 has **3,773 fully-qualified emoji**. Matching my 131-concept lexicon
by keyword found a candidate for **105 concepts (80%)**, but the picks show why
this cannot be automatic: `horse → horse racing`, `sheep → goat`,
`rice → sheaf of rice / rice cracker`, `monkey → see-no-evil monkey`. The
"misses" are mostly matching failure rather than gaps — 🏃 running, 🚶 walking,
🏊 swimming, 🍽️ eating, 😴 sleeping all exist.

Two ways to render, and they differ in licensing and look:

| Option | Licence | Asset size | Consistency |
| --- | --- | --- | --- |
| System emoji as text (no font bundled) | none needed | 0 | varies by OEM — Samsung, stock Android, Windows all draw differently |
| Bundle **Noto Emoji** (monochrome) | Apache-2.0 | small (~0.4–1 MB) | consistent, tintable, ideal for dark mode |
| Bundle **OpenMoji** (colour PNG/SVG or TTF) | CC BY-SA 4.0 | larger (~1.5 MB+) | consistent, colourful, needs attribution + share-alike |
| Bundle Noto **Color** Emoji | Apache-2.0 | ~10 MB+ | consistent but heavy for a dictionary APK |

Recommendation: monochrome **Noto Emoji** (Apache-2.0, small, tintable so it
follows our token palette in light and dark). Do not bundle the colour font.

## 3. Selective photos — keep, but only where they teach something

Keep the existing `images` / `entry_images` pipeline for a **50–100 concept**
set: real animals, Himalayan landscapes, Nepali food (momo, dal bhat), everyday
street scenes — the cases an emoji flattens. Method: concept → English Wikipedia
article → lead image, reject SVG/PDF, ≥500 px, licence allowlist, then one human
pass. That is what `docs/IMAGE-COVERAGE-PLAN.md` already lays out; the icon layer
removes the pressure to chase 3,000 photos.

## 4. What each layer looks like in the UI

- Detail screen: character panel (stroke animation + radical/parts + the word's
  characters) always; a concept visual (emoji or photo) when one exists.
- Result list: small emoji/icon only, no stroke animation (perf), no photo grid.
- Honest placeholder stays: "No picture for this word yet" — never a fake photo,
  never an emoji forced onto an abstract verb just to fill the slot.
- All three layers respect `nepaliEnabled`, theme tokens, 2.0× text, and dark mode;
  emoji is tinted by token, stroke paint uses `tokens.textPrimary`.

## 5. Order I would build it, each stopping for review

1. **Character panel** (highest value, data already measured): fetch
   hanzi-writer-data for the launch-set characters, store as a bundled asset +
   index table, `CustomPainter` animation, radical/parts row, tests for char
   coverage and fallback. Licence text into Credits.
2. **Emoji concept map** for the concrete slice: 68 firing concepts from
   `review/image_concepts.csv` + the missing everyday nouns, each mapped to one
   Noto Emoji codepoint by hand in `review/icon_map.csv`; render tinted.
3. **Selective photo set** (50–100 concepts) through the lead-image path, review
   CSV, then bundle.
4. **Later / optional**: the abstract-word extras that need data we do not have
   yet — example sentence with pinyin (Phase 2), word family (needs a new table).

## 6. Honest gaps

- `characters` table in the DB is empty and has only a `strokes INTEGER` column,
  so stroke assets are a new pipeline, not an existing feature being turned on.
- Arphic Public License is share-alike; the credits screen currently lists only
  CC BY-SA 4.0 sources and must be extended.
- Emoji glyph choice is editorial: 80% have a candidate, but "candidate" is not
  "correct", so the map needs your approval, exactly like the pinyin review file.
- Nothing here is installed or bundled; the app today still shows the placeholder.
