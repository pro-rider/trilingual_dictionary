# Image coverage — measured plan (not a promise)

Status: read-only analysis + live probe. **No dictionary written, nothing bundled,
nothing installed on the phone.**

## 1. Where the pictures actually stand

| Measure | Value |
| --- | --- |
| Entries in the release DB | 123,672 |
| Approved images | 109 |
| Entries that can show a picture | 235 (**0.19%**) |
| Top-1,000 frequent words with a picture | 62 |
| Top-3,000 frequent words with a picture | 104 |
| Existing match methods | `sibling` 123, `zh-title` 49, `wikidata-p18` 45, `en-gloss` 14, `concept-label` 6, other 2 |

The pipeline is not the problem: `tools/fetch_images.py` already searches Commons
and Wikipedia with an CC0 / PD / CC BY / CC BY-SA licence gate, stores attribution,
and rejects NC/ND/unknown. The unit of work is the problem — one image per *word*
cannot scale to 123k entries.

## 2. The concept idea, measured (not assumed)

`tools/image_concept_plan.py` (new, read-only) joins the top-3,000 entries (first
English gloss + Chinese headword) against a 131-entry concrete-concept lexicon and
writes `review/image_concepts.csv` / `review/image_concepts_unmapped.csv`.

Result on the top 3,000 words that have no picture yet:

| | |
| --- | --- |
| Entries examined | 3,000 |
| With a concrete visual concept | **144 (4.8%)** |
| Without one (function words, pronouns, classifiers, variants) | **2,770** |
| Concepts that fire | 68 of 131 |

The unmapped head shows why: 的 `of`, 是 `to be`, 在 `to exist`, 了 `(completed
action marker)`, 和 `and`, 不 `no; not so`, 个 `classifier`, 可以 `can; may`.
A photograph of these is meaningless. Also, 221 of the top-3,000 rows are
duplicate headwords (CC-CEDICT variant rows carrying their own `freq_rank`),
so the band is ~10% inflated.

**This contradicts my earlier estimate that 800 concept images could reach 60–70%
of the top 3,000.** They cannot: most high-frequency Chinese vocabulary is
abstract or functional, and the ceiling for photo-able words inside the top 3,000
is a few hundred, not two thousand. The realistic target is:

- concrete noun/verb slice: **≈150–400 entries in the top 3,000**, ~2,000–4,000
  across the whole dictionary — coverable at close to 100%;
- everything else keeps the honest "No verified picture yet" placeholder.

## 3. Can Commons actually deliver? (live probe, this machine)

`tools/image_concept_probe.py` (new) queries
`generator=search&gsrsearch="<concept> filetype:bitmap"&gsrnamespace=6&prop=imageinfo&iiprop=url|size|mime|extmetadata`,
applies the licence allowlist and quality gates, downloads the 640 px thumbnail,
and writes `review/image_concepts_probe.csv`.

| Measure | Value |
| --- | --- |
| Concepts tested | 14 (`cat water tree mountain book chair hand car train apple doctor umbrella pig hospital`) |
| Concepts with a usable licence-clean image | **14 / 14 (100%)** |
| Time per concept | 2.5–3.3 s, 4.8 s including throttling backoff |
| Licence refusals among top-4 hits | 0–1 per concept |
| Output | thumbnails in `data/images/_probe/`, attribution per concept in the CSV |

Operational fact found the hard way: Commons rate-limits per IP through an envoy
front and answers **HTTP 429 with `retry-after`**, not silently. The probe honours
`retry-after` and retries up to 4 times; without that, 2 of 12 concepts failed
while 10 succeeded. Any bulk run needs that backoff plus ≥1 s spacing and a real
contact string in the User-Agent.

### 3.1 Licence is not the problem — relevance is

Read the chosen file per concept and the precision is about half:

| Concept | Commons search picked | Right for a dictionary? |
| --- | --- | --- |
| cat | `Cat playing with a lizard.jpg` | yes |
| tree | `Flame tree mali.jpg` | yes |
| mountain | `Everest, Himalayas.jpg` | yes |
| pig | `Domesticated farm pig lying in the mud…` | yes |
| umbrella | `Beige and brown oil-paper umbrella…` | yes |
| train | `CP GE AC4400CW 8608 Morant's Curve.jpg` | yes |
| water | `Drop of water on water-resistant textile (100% polyester)` | no |
| apple | `Apple II at Musée Bolo` (the computer) | no |
| chair | `Grand bassin octogonal Jardin des Tuileries 003` (a fountain) | no |
| hand | `Ambigram Escher and tessellation background` | no |
| car | `Abandoned car in Marine Park` (a wreck) | no |
| book | `13-11-02-olb-by-RalfR-03` (unclear museum shot) | no |
| hospital | `Doctors Hospital from the Southwest` (a building with that name) | partial |
| doctor | `Covid-19 San Salvatore 01` (a ward scene) | partial |

So "the licence gate passes 100%" only means the files are *legally* usable. The
meaning problem is upstream of the licence check, and no amount of fetching fixes
it: a keyword search for a word is not a search for its concept.

### 3.2 The better fetching method, measured the same day

For the six wrong ones, the **English Wikipedia lead image of a named concept**
(`prop=pageimages&piprop=original|thumbnail&pithumbsize=640`) returned:

| Concept | Lead image file | Verdict |
| --- | --- | --- |
| Apple | `Pink_lady_and_cross_section.jpg` | a fruit — correct |
| Chair | `Set_of_fourteen_side_chairs_MET_DP110780.jpg` | a chair — correct |
| Hand | `Hand,_fingers_-_back.jpg` | a hand — correct |
| Car | `White_Toyota_Corolla_sedan_in_San_Jose_California…` | a car — correct |
| Book | `Gutenberg_Bible,_Lenox_Copy…` | a book, archaic but correct |
| Hospital | `Hospital-de-Bellvitge.jpg` | a hospital — correct |
| Water | `H2O_2D_labelled.svg` | a diagram — must be rejected by a raster filter |
| Tree | `Usamljeni_jasen_-_panoramio_(cropped).jpg` | a tree — correct |

The method to build on is therefore **concept → English Wikipedia article → lead
image (raster only, SVG/PDF rejected)**, with Commons search only as a fallback
that never auto-approves. This is exactly the `wikipedia-lead-image` tier already
in `fetch_images.py` — it currently accounts for 1 row in the DB because the
pipeline asks Wikipedia for the *word*, and most words have no article. Asking for
the *concept* instead is what makes it work.

## 4. What that means for the product

1. Photos are only worth showing where they are *relevant*. The placeholder is the
   correct outcome for 的/是/了, and a UI that always shows "no picture" is not
   broken — it is accurate. Consider making the placeholder quieter in list views
   and keeping the full card only on the detail screen.
2. The concept→image step must be **curated, not keyword-derived**. The probe
   shows supply is easy; the current automatic matching is what is noisy
   (`光 → lamp`, `负责 → bear` both came from gloss keywords). A hand-approved
   concept list of ~300–600 entries covers the concrete slice; each concept then
   inherits to every headword/synonym/compound it names.
3. Licence and attribution already work end-to-end: `LicenseShortName` +
   `Artist` + `descriptionurl` come back in the same call and land in the CSV, so
   the credits screen keeps working unchanged.
4. Unsplash/Pixabay stay out of the core. They supply aesthetic scenes rather
   than concept illustrations, and their terms/rate limits do not fit an offline
   dictionary; if used at all, it is an opt-in "download on demand" layer that
   caches bytes.

## 5. Recommended order (each step stops for review)

1. **Concept list** — take the 68 firing concepts from `review/image_concepts.csv`,
   replace the bad ones, add the missing concrete nouns a learner needs; approve
   ~300–600 concepts by hand. Deliverable: `review/image_concepts_approved.csv`.
2. **Fetch by concept, not by word** — for each approved concept resolve its
   English Wikipedia article, take the lead image, reject SVG/PDF and anything
   under 500 px, record `LicenseShortName` + `Artist` + `descriptionurl`; fall back
   to Commons search only when there is no article, and mark that row
   `needs_human=yes`. Bulk fetch runs on a DB **copy**
   (`data/build/_imgtest/dictionary.imgtest.sqlite`) writing
   `match_method='concept-approved'` / `'concept-lead-image'`, never the release DB.
3. **Human pass** — `review/image_review.csv` with one row per concept: image,
   licence, author, accept/replace/off. Rejected images drop out; nothing ships
   unreviewed. At the measured ~half precision of keyword search, this step is not
   optional.
4. **Coverage gate** — `python tools/image_coverage.py --db <candidate>` must
   report the concrete-slice coverage before anything is bundled; the top-3k
   headline number will stay low and that is expected, so read the band table.
5. **Bundle** — only after approval: rebuild thumbnails, `bundle_images.py`,
   rebuild the release DB, bump `assetVersion`, licence audit.
6. **Optional later** — on-demand network images behind a setting, Commons source,
   disk cache, placeholder as default.

## 6. Not done in this round

- No DB write anywhere; both tools open the dictionary `mode=ro`, the probe writes
  only thumbnails and CSVs.
- No concept list approved yet — that is your review, not mine.
- No relevance scoring (no CLIP/vision model), no watermark detection: the probe
  checks licence, size, aspect and title noise only, and says so per row.
- No device/bundle change: the app still shows the placeholder exactly as before.
