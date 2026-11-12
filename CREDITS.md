# Credits and licences

**DRAFT — needs human and legal review before submission.**

This file is the source of truth for what ships in the app. The in-app screen
`lib/features/about/credits_screen.dart` shows the same three sources and the
same share-alike text; if one changes, change both.

## Data sources included in the release database

| Source | What is used | Licence | Licence URL |
|---|---|---|---|
| CC-CEDICT | English definitions and the headword list (123,672 entries) | CC BY-SA 4.0 | https://creativecommons.org/licenses/by-sa/4.0/ |
| Chinese Wiktionary (zh.wiktionary) | 13,867 Chinese definitions, imported row by row with provenance after review | CC BY-SA 4.0 | https://creativecommons.org/licenses/by-sa/4.0/ |
| Wikimedia Commons | 77 entry images plus their thumbnails | per-image (Public domain, CC0, CC BY, CC BY-SA) | recorded per row in `images.license_url` |

## Sources deliberately NOT included

| Source | Why not |
|---|---|
| Xinhua dictionary (`gloss_zh_candidates`, 17,786 rows) | licence unclear / not redistributable; kept only as an internal benchmark |
| MoEDict (Taiwan Ministry of Education, ND-licensed) | the ND clause forbids derivative works, which a definition import would be |
| AI models | outputs are unlicensed by nature, so they enter candidate tables and only become content after a human decision |

`backend/tools/build_release_db.py` enforces this: the build fails if a
restricted table or a restricted provenance source is present, and
`backend/tests/test_release_license_audit.py` proves the check works.

## Share-alike statement (required by CC BY-SA 4.0)

> This work includes material from CC-CEDICT and Chinese Wiktionary, both
> licensed CC BY-SA 4.0. Modifications: headwords were deduplicated (866
> traditional/simplified classifier rows removed), English glosses were kept as
> published, Chinese definitions were selectively imported and normalised
> (traditional converted to simplified), and machine translations were added and
> labelled as machine output. The modified database is distributed under the
> same CC BY-SA 4.0 licence.

## Image attribution

Each entry detail screen shows, for the image it displays: the file title, the
author, the licence and a link to the original Wikimedia page. CC BY-SA images
additionally fall under the share-alike statement above. The full per-image list
with author and licence is in `docs/IMAGE_AUDIT.md`.

## Application code

The Flutter client and the FastAPI backend are the project's own work. Third-
party packages are listed by `flutter pub get`/`pip`, and their licences are
carried by `pub` and the wheel metadata; the release notes should state that the
app bundles open-source packages under their respective licences.

**Human TODO:** confirm the CC BY-SA 4.0 obligations are met for a commercial
store listing (attribution placement, licence text reachability, and whether the
database file itself must carry a licence notice — suggested: a `LICENSE-DATA`
file shipped next to the app's own licence).
