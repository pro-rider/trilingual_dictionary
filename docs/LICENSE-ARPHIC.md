# Licensing: stroke data in `assets/strokes/`

**Status: reviewed by reading every licence file in both upstream packages. This
document is an engineering reading, not legal advice — see §7 for what a lawyer
must answer.**

## 1. What exactly we bundle, and from where

| item | source | file we actually ship |
| --- | --- | --- |
| stroke outlines, stroke medians, radical stroke indices | `hanzi-writer-data@2.0.1` (npm), per-character JSON | one packed `assets/strokes/strokes.bin.gz` + `assets/strokes/strokes.index.json` |
| licence text | `ARPHICPL.TXT` in the same package | copied verbatim next to the data as `assets/strokes/ARPHICPL.TXT` |
| stroke-count reference (build-time only, not shipped) | Unicode `Unihan.zip` (UCD 18.0.0), `kTotalStrokes`, `kRSUnicode` | — |

Exact provenance, recorded so the build is reproducible:

```
package      hanzi-writer-data 2.0.1  (npm, published by chanind)
tarball      hanzi-writer-data-2.0.1.tgz
sha256       72baf3d82b114e60d6e40ea05f24d2262a05cd39d544e2f322ba2fceb7beff15
size         13,484,680 bytes
npm shasum   09ce12eb1c47d86aeb33313e622f17ba5cbac1ad
npm integrity sha512-nbQwM+MaryGoq7pBMIZLCd3lFq03nXuJuwku1+6UbjL58uU+9OULVcMkoNvNuJSoIV7f1bbPRfD4D/LQa5S7qg==
upstream     Make Me a Hanzi  (github.com/skishore/makemeahanzi)
Unihan.zip   sha256 4c93ea9c1f636451729a840978f1667a53886af37ba854fdcce109721c63d43e
```

`package.json` itself declares: `"license": "SEE LICENSE IN ARPHICPL.TXT"`.

## 2. Which licence covers which file — the part that matters

Make Me a Hanzi splits its data, and the split is stated in its own `COPYING`
file (fetched from `skishore/makemeahanzi`):

- `graphics.txt` — stroke outlines and medians extracted from the Arphic fonts
  `AR PL KaitiM GB`, `AR PL UKai`, `AR PL KaitiM Big5`, `AR PL Mingti2L Big5`
  → **Arphic Public License**, with the licence text shipped as the `APL/`
  directory (five copies: `english`, `big5`, `gb`, `zh_CN.UTF-8`, `zh_TW.UTF-8`)
  plus `ARPHICPL.TXT` at the package root.
- `dictionary.txt` — radical, definition, pinyin, decomposition, derived from
  **Unihan and CJKlib** → **LGPL-3.0-or-later**, a different licence.

The distinction decides what we may ship. I checked the actual records instead of
trusting the package description: every per-character file in
`hanzi-writer-data` has exactly three keys —

```
keys: ['medians', 'radStrokes', 'strokes']
```

There is **no `radical`, no `definition`, no `pinyin`, no `decomposition`** in
this package. So the files we bundle descend from `graphics.txt` only and are
covered by the **Arphic Public License**; the LGPL `dictionary.txt` material is
never copied, and no LGPL text needs to ship. That is the answer to "different
files may have different licences": one of them applies here, and it is Arphic.

Radical information in the panel is taken from a different source: radical
numbers come from Unicode `Unihan` (`kRSUnicode`), and the radical glyph and its
English name come from the Unicode Kangxi Radicals block character names
(`KANGXI RADICAL MAN` → "man"). Unihan and Unicode character data are under the
Unicode Terms of Use, which require a copyright notice and no modification of the
data files — both satisfied (we only read them at build time and never ship
them). No Chinese radical "name" is written by hand; the Chinese side displays
the Kangxi radical character itself (人, 木, 水), which is the standard form and
cannot drift from the data. Nepali is never shown, because no reviewed Nepali
translation of radical names exists.

## 3. What the Arphic Public License actually requires

Read in full (`ARPHICPL.TXT`, 6,900 bytes, English). The operative clauses:

- **§1 Copying & distribution** — verbatim copies of the Font in any medium are
  allowed **provided this license file is retained unaltered in all copies**.
- **§2 Modification** — modification is allowed, including "converting format"
  and "re-encoding glyphs", on three conditions: (a) a prominent notice in each
  modified file saying how and when it was changed; (b) the modification must be
  made **Freely Available as a whole to all third parties under the terms of this
  licence**, e.g. by offering access to a copy from a designated place; (c) if the
  modified font normally reads commands interactively, it must display a copyright
  notice, a no-warranty statement and instructions for viewing the licence.
- **§2, last paragraph (the aggregation clause)** — sections not derived from the
  Font, and reasonably independent works in themselves, are **not** brought under
  the licence; "mere aggregation" of an unrelated work alongside the Font does not
  extend the licence to it.
- **§3** — no sublicensing or distribution outside these terms; **§7 no warranty**;
  **§8 damages waiver**.

### Required notice and attribution text

The app must ship, and the Credits screen must display:

1. the **unaltered** `ARPHICPL.TXT`, placed beside the data (`assets/strokes/ARPHICPL.TXT`);
2. a statement naming **Arphic Technology Co., Ltd.** as the original copyright
   holder (1999) and **Make Me a Hanzi** as the extractor;
3. a statement that our packed file is a **format conversion** of
   `graphics.txt` (JSON → one gzipped bundle), with the date, satisfying §2(a);
4. a statement that the converted data is available to recipients under the
   Arphic Public License, satisfying §2(b).

Suggested Credits wording (used verbatim in the Credits screen and in
`docs/LICENSE-ARPHIC.md` §6):

> Stroke outlines and stroke order come from Make Me a Hanzi (github.com/skishore/makemeahanzi), which extracted them from fonts by Arphic Technology Co., Ltd. and released them under the Arphic Public License (1999). The stroke data in this app is a format conversion of that data made on 2026-11-15 and is available to you under the same licence; the full licence text ships in assets/strokes/ARPHICPL.TXT.

### Does bundling in the APK count as redistribution?

Yes. An APK that contains the compressed stroke data is a copy distributed to
every user who installs the app, so §1/§2 apply: the licence text must travel with
it (we do that), the modification notice must exist (we do that), and the
converted data must be available to recipients under the same licence (see §5 —
this is the obligation that needs a real decision).

### Does it trigger source-availability duties?

§2(b) says the modification must be "Freely Available as a whole to all third
parties … such as by offering access to copy the modifications from a designated
place". Unlike the GPL, it does not spell out "source code"; the practical
reading is: a recipient must be able to obtain the modified data under this
licence. Two acceptable ways to satisfy it:

- ship the **pre-conversion** data alongside (our repo already contains the
  builder and the license; publishing the repo satisfies "designated place"), or
- expose the packed file itself plus this licence at a public URL.

**Decision taken: option A, the public repository is the designated place.**

| option | what it means | outcome |
| --- | --- | --- |
| **A. The main repository is public** | the app source, the builder, `ARPHICPL.TXT` and the packed data are all publicly obtainable; the repository URL is the "designated place" | **Chosen on 2026-11-15.** The repository `github.com/pro-rider/trilingual_dictionary` is public, so a recipient of the APK can obtain the converted data and the licence text, and can rebuild the pack from `tools/build_stroke_pack.py` with the checksums in §1. §2(b) is satisfied directly, with no extra page to maintain. |
| **B. A separate small public repo or page** | a repository containing only the pack, the builder and `ARPHICPL.TXT`, linked from Credits | Not needed under A. It remains the correct answer *if* the main repository ever goes private again: the stroke data must not become unobtainable just because the application source did. |

The consequence of A is recorded rather than hidden: making the repository public
also publishes `backend/` and the Supabase schema, an exposure accepted as a
product decision, not as a licence requirement. Keeping those two questions
separate is why option B existed; with A chosen, the licence obligation and the
security posture are independent again — the repository is public for the
project's own reasons, and it happens to satisfy §2(b) as well.

If the repository is ever made private, switch to option B before the next
release: §2(b) does not care why the data became unobtainable.

The printed conversion date in this document is not the record of truth: the
build writes `assets/strokes/build_info.json`, a generated Dart constant feeds the
Credits sentence, and `test/stroke_license_audit_test.dart` fails if the two
disagree.

## 4. Coexistence with the CC BY-SA 4.0 dictionary data in the same app

The dictionary content (CC-CEDICT, CC BY-SA 4.0) lives in a **separate SQLite
database**, and the stroke data lives in **separate asset files**. Nothing is
merged: no stroke data is written into the database, and no dictionary text is
written into the stroke pack. Under APL §2's aggregation clause, an independent
work distributed alongside is not pulled into the Arphic licence, and equally the
APL data does not become a CC BY-SA derivative. The Android APK is a container of
both, which is aggregation, not a derivative work — that conclusion rests on the
APL aggregation clause alone, and on the two practical rules below. It does not
rest on an analogy with any other project's licensing choices.

Two practical rules follow, and the code follows them:

- never copy stroke JSON into `dictionary.sqlite` (it would mix licences inside
  one derived database);
- keep `assets/strokes/ARPHICPL.TXT` and the CC BY-SA attribution separate in
  Credits, each naming its own licence, so a reader sees two distinct grants
  rather than one blended one.

## 5. What changes for a future closed or paid build

- **Closed-source is fine; closed stroke data is not.** The Arphic Public License
  is a copyleft-style licence on the *data*: a paid app may ship it, but the
  stroke data (and any converted form of it) must remain available to recipients
  under the APL. You cannot make the stroke assets "all rights reserved".
- **A proprietary app that hides the repository** must still expose the packed
  stroke data and the licence text at a public URL and say so in Credits (§2(b)).
- **Paid distribution is explicitly allowed** — §0 "Freely Available" clarifies
  that freedom is about permissions, not price: "If you wish, you can charge for
  this service."
- **Trademark and font names** must not be used to imply endorsement; the
  attribution names Arphic as copyright holder, nothing more.
- **If a future build wants LGPL radical/decomposition data** from Make Me a
  Hanzi (the `dictionary.txt` half), that is a separate licensing exercise: LGPL
  obligations attach to that data, and the two licences must be tracked apart.
- **Do not relicense the pack.** Ship it under the APL, with the licence text
  unchanged, and document the conversion.

## 6. Where the notice lives in this repo

| place | what it says |
| --- | --- |
| `assets/strokes/ARPHICPL.TXT` | the unaltered licence, beside the data |
| `assets/strokes/README.md` | provenance, checksums, conversion note, date |
| Credits screen | the sentence quoted in §3 |
| `docs/LICENSE-ARPHIC.md` (this file) | the full reading |
| `test/stroke_license_audit_test.dart` | fails if any of the above disappears or if the pack is rebuilt without the licence |

## 7. Questions for a lawyer (not answered here)

1. Does a **gzip-packed JSON** count as "converting format" under §2 (so the
   modification notice is required), or as a verbatim copy under §1? Our reading
   is conversion; confirm.
2. Is "make the modifications Freely Available … from a designated place"
   satisfied by a **public source repository**, when the distributed artifact is
   an APK that does not itself contain the builder?
3. Does shipping the data inside a **paid** app trigger any additional
   obligation beyond §2(b)?
4. Does **storing the data in RAM only, decoding on demand** count as
   distribution, or only the on-disk asset matter?
5. If the app later adds **LGPL `dictionary.txt`** fields (radical text,
   decomposition), what exactly must be offered, and can the two data sets share
   one file or must they stay separate?
6. Is a **user-visible Credits line** sufficient as "prominent notice", or does
   the licence text need to be reachable from a top-level menu item?
7. Confirm that the **Unicode Terms of Use** permit reading `kTotalStrokes` /
   `kRSUnicode` at build time and displaying derived radical numbers, with no
   redistribution of the Unihan files.
8. **APL §2(c)**: the licence requires that a program which "reads commands
   interactively" display the notice. Our app does not read Arphic *data* as
   commands, but confirm that §2(c) is not triggered by an app that merely renders
   stroke paths derived from the data.
9. With the main repository public (option A), confirm that the repository URL —
   containing the builder, the packed data and `ARPHICPL.TXT`, but also unrelated
   application and backend source — satisfies "designated place" for the
   *pre-conversion* data, or whether the original per-character JSON must also be
   published. We do not ship that original JSON; it is obtainable from the npm
   package named in §1 instead.
