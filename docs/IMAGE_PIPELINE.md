# Image pipeline: inheritance, integrity and acquisition

Last measured: 2026-11-12 (UTC-8 build), `db-f6008049a2`.

Scope: how a headword reaches a picture, why some pictures silently failed to
render, what now fails a build instead, and what a 70% target really costs.

## 1. Why a word showed no picture

Four different failures all look identical in the UI, because
`word_image_card.dart` turns every one of them into the same grey icon:

| Failure | Evidence in this repo |
|---|---|
| No row in `entry_images` for the entry | 123,426 of 123,672 entries (99.8%) have no picture at all |
| `thumb_asset` points at a file that is not in the APK | fixed for image 7 (regenerated, 8,288 B) |
| `thumb_asset` is nested (`thumbs/de/dee11….webp`) | **proven**: a previous `build/flutter_assets/assets/images/thumbs/` held 84 files and **zero subdirectories**, while 35 rows pointed into `thumbs/<xx>/`. Those 35 were on disk, in git-ignored territory, and absent from the bundle |
| Image row not `approved` / `asset_status` not `approved` / no thumbnail | 0 rows today |

The nested case is the important one: it explains "the image exists in the
database but never appears", and it cannot be seen from the database alone. It
is now impossible to ship — see §3.

## 2. Lookup order (client and server)

`imageForEntry(pk)`
1. `entry_images` for that exact entry, `ORDER BY rank` (direct evidence:
   wikidata-p18, zh-title, en-gloss).
2. **Concept family** — `entry_concepts → concept_images → images`, ordered by
   `is_primary DESC, relevance DESC, confidence DESC`. One curated photograph
   serves every member of the family (玩具/玩意, 椅/椅子, 月球/月亮).

`imageForWord(word)`
1. `entry_images` joined on `simplified`/`traditional` (a bundled seed word or an
   AI answer with id `seed:book` has no entry id but still has a headword).
2. Concept family of up to five entries carrying that headword, tried in
   frequency order.

Server (`GET /images`, `/images/batch`) mirrors the same order:
`_query(entry_id)` then `_concept_query(entry_id)`; `word=` resolves the headword
to an entry id first, so the seed/AI path gets the same family fallback. Only
rows that satisfy the client's own filter (approved image, approved asset,
non-empty thumbnail) are ever returned, so a network answer can never be
something the offline client would have hidden.

## 3. Build integrity (Phase 2)

`backend/tools/verify_image_assets.py` fails the build (exit 1) on any of:

- `thumb_asset` missing from disk;
- `thumb_asset` outside `assets/images/thumbs/`;
- `thumb_asset` nested one level below that prefix (Flutter will not bundle it);
- an approved image with no `thumb_asset`;
- an orphan thumbnail file that no row references.

It is called from `build_release_db.py` (after `db_sha` is computed, before the
record is written) and from `check.py` (`image_assets()` step), so neither a
release build nor the ordinary check suite can pass with a broken reference.

Current state: **113 images / 113 referenced / 113 files / 0 orphans /
0 missing detail**. `thumb_bytes_max` 17,568 B (one file above the 15 KB target).

## 4. Acquisition (Phase 3), and what it actually yields

`images_v2.py` looks up a word's Wikidata item, then tries, in order:

1. the item's `P18` image — but only if the item's English label or alias
   **equals** the word's gloss (`concept_image_files(qid, gloss)`). This is the
   gate that stopped "same → SAME Explorer II 90 Turbo".
2. the curated Commons category `Category:<gloss>`
   (`commons_category_files`) — membership is the identity evidence, so
   `IMG_2231.jpg` can pass where a filename check cannot.
3. optionally the article lead image (`--sitelink`).
4. Commons title search — **off by default** (`--allow-commons-search`). It
   produced "first → Shooter person views", "you and I → James Montgomery Flagg
   poster", "领导 → 3D Team Leadership Arrow": share-the-word matches no
   filename gate can separate from real ones.

Every candidate then passes licence (`CC0 / public domain / CC BY / CC BY-SA`
only; `NC`, `ND` and `Attribution`-only rejected), author-present, and quality
(`>=500 px`, aspect 0.5–2.2, no `illustration/engraving/poster/playbill/book/map`
titles), plus the lexical-relevance gate (a content word of the gloss must appear
in the filename, unless it came from the curated category).

Measured on this machine (single process, no parallelism):

- **~20 s per word** end to end; parallel launches double the process per launch
  and *reduce* throughput through SQLite contention (4→8 writers made it ~100 s
  per word).
- **~55% acceptance on concrete nouns** (铁, 铜, 鼓, 手套, 袜子, 灯笼, 剪刀, 拖鞋,
  篮子, 围巾, 山脉, 煤炭, 足球, 篮球, 洗衣机, 项链 …).
- **~0% on abstract/functional words** (时候, 稳定, 容量, 能级, 后人 …) — no
  photograph can be verified for them, and none is invented.

This session: 77 → 113 images (+36), 204 → 246 entries with a picture, 89 → 123
concepts.

## 5. Coverage today

| band | entries | with picture | coverage |
|---|---|---|---|
| all | 123,672 | 246 | 0.20% |
| top 500 | 598 | 29 | 4.85% |
| top 1,000 | 1,140 | 65 | 5.70% |
| top 2,000 | 2,205 | 95 | 4.31% |
| top 5,000 | 5,410 | 121 | 2.24% |
| top 10,000 | 10,634 | 157 | 1.48% |
| top 20,000 | 20,916 | 185 | 0.88% |

Baseline at the start of this work: 204 entries, top-500 4.68%, top-1,000 5.44%,
top-10,000 1.21%.

## 6. What 70% actually costs

At 20 s/attempt and ~55% acceptance on concrete nouns (~11 s per accepted
picture), and counting only words that *can* have a photograph:

| target | pictures needed | attempts | unattended time |
|---|---|---|---|
| 70% of top 500 | ~350 | ~640 | ~3.5 h |
| 70% of top 1,000 | ~800 | ~1,450 | ~8 h |
| 40% of top 10,000 | ~4,250 | ~7,700 | ~43 h |
| 70% of top 10,000 | ~7,450 | ~13,500 | ~75 h |
| 70% of all entries | ~86,500 | ~157,000 | ~870 h |

Two conclusions follow. First, the honest ceiling is **the top of the frequency
list**: 4.85% at top-500 today is a *content* gap, not an infrastructure gap —
the words people actually look up are mostly verbs, adverbs and function words
(是, 会, 已经, 这样), and no correctly-attributed photograph exists for them.
Second, 70% overall is not reachable with photographs at all; it would need a
second asset class (illustrations or pictograms drawn in-house, which the project
has ruled out) or a much looser relevance bar, which is exactly the failure mode
already rejected ("never show a wrong picture to raise the count").

## 7. Online fallback (Phase 4)

Local first, network only on a miss:

1. `imageForEntry` / `imageForWord` as in §2 (offline, bundled thumbnails only).
2. On miss, the client calls `GET /images?word=<headword>`; the server resolves
   the headword to an entry id, tries direct rows, then the concept family, and
   returns the same schema the offline path uses (including attribution,
   licence and licence URL). No image is downloaded into the bundle by the
   server; the client shows the remote detail URL with its attribution text.
3. Offline, a miss stays a miss: the card falls back to its category icon
   (13 icon families), never to a placeholder that looks like a broken photo.

## 8. Next actions

1. Run acquisition unattended in frequency order (`--limit 200` batches) toward
   70% of top-1,000 (~8 h) — the only band where the target is both meaningful
   and reachable.
2. Rebuild shrunk thumbnails for the 1 file above 15 KB
   (`make_missing_thumbs.py` thresholds already support it).
3. Keep `verify_image_assets.py` in CI so a nested or orphaned thumbnail can
   never reach a release again.
4. Do not lower the relevance or licence gates to move the percentage.

## 9. Second acquisition tier: Unsplash and Pixabay

Wikimedia carries objects, species and places; it has almost nothing clean and
modern for everyday nouns, and nothing at all for the rest. `tools/images_multi_source.py`
adds a second tier behind the same gates, so one picture can still be found for
a word that Commons cannot illustrate.

The keys live in the environment (`UNSPLASH_ACCESS_KEY`, `PIXABAY_API_KEY`) or in
`backend/.env`, which `.gitignore` excludes; the tool reads them, uses them only
to build an `Authorization` header, never prints them and never writes them into
a file or a log. Without a key it exits with code 2 and says which variable is
missing, rather than appearing to run. Quota is tracked per source in
`backend/data/build/api_quota.json` against the published limits (Unsplash demo
50 calls/hour, Pixabay 100/minute); when a window is spent the tool stops calling
that source instead of burning requests on 403s.

Acceptance requires a minimum short edge of 600 px, an aspect ratio between 0.5
and 2.2, and at least one content word of the English gloss present in the
result's alt text, description, slug or tags. Unsplash is recorded as the
"Unsplash License" and Pixabay as the "Pixabay Content License", with author,
source page and an attribution string in `images.attribution_text`; neither
licence requires credit, both permit redistribution inside an app.

Caching is the point of the tier: the first accepted picture is downloaded once,
hashed, written as `thumbs/<sha>.webp` (256 px, flat) and `detail/<sha>.webp`
(1024 px), inserted into `images` / `concept_images` / `entry_concepts` /
`entry_images`, and from then on the same word and every synonym in its concept
family are served from the local row with zero further API traffic. A repeat run
therefore costs nothing for anything already covered.

## 10. The precision failure that a percentage target invites

Two rounds of acquisition in this session produced the same lesson, and it is
worth recording precisely because the numbers looked better each time.

The first attempt widened the candidate pool with Commons *categories* and treated
membership in `Category:<gloss>` as evidence of identity. That put a bus
destination sign (`PSFS since T190.png`) on 第二 ("second") and a rally car
(`08 Lancia Ypsilon`) on 左右 ("left and right"): a category is a shelf, not a
description. The bypass is gone; a category may only widen the pool, and the
lexical gate still has to pass.

The second attempt audited the result with token equality instead of substring
matching, so `FullMoon2010.jpg` failed the test for the gloss "moon" and a
correct picture was deleted along with twenty-six others. Substring matching is
the right test for camel-cased filenames, which is why `tools/audit_image_precision.py`
uses it and only reports.

Even with both fixed, four links survived every automated gate and still failed
the only test that matters — would a reader accept this? A Dutch still life for
历史 ("history"), a single folk-ride photograph for 人们 ("people"), a Cacti
monitoring screenshot for 网络管理 ("network management") and an untitled personal
photograph for 行话 ("jargon"). They are now removed with reasons recorded
(`tools/drop_wrong_images.py`), which is why the shipped set is 109 images serving
235 entries rather than 113 serving 246.

## 11. Why 90% coverage is not a target that can be met by working harder

Measured on this machine: ~20.5 s per word end to end, ~55% acceptance on a
hand-picked concrete-noun list, and 123,672 entries of which 235 currently show a
picture. `tools/_projection.py` turns that into arithmetic:

| band | entries | covered now | need for 90% | attempts at 55% | time at 20.5 s |
|---|---|---|---|---|---|
| top 500 | 598 | 32 (5.35%) | 506 | 919 | ~5.2 h |
| top 1,000 | 1,140 | 68 (5.96%) | 958 | 1,741 | ~9.9 h |
| top 5,000 | 5,410 | 124 (2.29%) | 4,745 | 8,627 | ~49 h |
| top 20,000 | 20,916 | 188 (0.90%) | 18,636 | 33,883 | ~193 h |
| all entries | 123,672 | 235 (0.19%) | 111,305 | 202,373 | **~48 days** |

The obstacle is not hours, it is the corpus. Ninety per cent of all entries means
finding a photograph for 是, 会, 已经, 这样 and 111,000 of their neighbours —
verbs, adverbs, function words and bound morphemes for which no correctly
attributed photograph exists, in any source, at any price. Reaching the number
would require attaching pictures that mean nothing to the word, which is the one
outcome the project has explicitly forbidden. The honest ceiling is the
photographable subset, and the useful target is the band people actually search:
90% of top-1,000 is ~1,741 attempts, about ten hours of unattended crawling, and
that is reachable with the pipeline as it stands.

Two further constraints bound the paid tiers even if the keys arrive: Unsplash's
demo quota is 50 calls/hour, which is 1,200 a day; Pixabay allows 100/minute but
its content is thin for abstract Mandarin vocabulary. Neither can move an
entire 123,672-entry corpus, so the ordering that matters is frequency first.
