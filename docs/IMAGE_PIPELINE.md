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
