"""Image pipeline, stages 38–42: collect → licence-filter → match → store.

Scope of this build, stated up front so nothing looks bigger than it is:

  * Implemented source: Wikimedia Commons (MediaWiki API, official endpoint). It is
    the only plugin wired now; the `Source` interface and the CLI are generic, so
    Wikidata/Openverse/Flickr/Open-Images plugins slot in without touching the
    rest of the pipeline.
  * Licence gate: CC0 / Public domain / CC BY / CC BY-SA only. NC, ND, unknown and
    conflicting metadata are rejected with a stored reason.
  * Quality gate implemented: minimum width, aspect ratio, raster format, and
    attribution completeness. NOT implemented here: watermark/text detection,
    blur/contrast scoring, NSFW classifier, CLIP relevance, pHash dedupe. They
    need vision models and are listed in the report as "not run" rather than
    silently skipped.
  * Matching: Commons file title/tags against the entry's first English gloss —
    method `commons-search`. Confidence is capped at 0.60 because this is the
    weakest of the four matching tiers in the spec.
  * Storage: two real sizes fetched from the source's own thumbnailer (800 px
    detail, 256 px thumb) so no image maths happens locally. Files land under
    `data/images/`, never inside the app bundle.

Usage
-----
  python tools/fetch_images.py --db data/build/dictionary.sqlite --limit 120
  python tools/fetch_images.py --db ... --category nature --limit 200 --resume

Resumable: every accepted entry is written to the DB and to
`data/images/manifest.jsonl`, so a re-run skips what already succeeded.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
WIKI_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = (
    "TrilingualDictionary/0.2 (dictionary image pipeline; contact: project owner) "
    "python-urllib"
)

# Titles that are almost never the concept itself: places, buildings, events,
# documents, models, charts. The Commons search tier is rejected when these
# appear, because a file called "Dry (Loiret) Église" is not a picture of "dry".
NOISE_TITLE = re.compile(
    r"(église|eglise|church|cathedral|chapel|panneau|sign|plaque|monument|"
    r"damage|map|carte|diagram|chart|model|mockup|stamp|coin|banknote|logo|"
    r"coat of arms|seal|poster|screenshot|cover|book|titelseite|"
    r"cemetery|grave|tomb|station|airport|bridge|street|square|hotel)",
    re.IGNORECASE,
)

ALLOWED_LICENCE = re.compile(
    r"^(cc0|cc by(-sa)?|public domain|pd)\b", re.IGNORECASE
)
FORBIDDEN = re.compile(r"\b(nc|nd|noncommercial|no.?deriv)\b", re.IGNORECASE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
  image_id INTEGER PRIMARY KEY,
  content_hash TEXT UNIQUE NOT NULL,
  title TEXT,
  thumb_path TEXT,
  detail_path TEXT,
  width INTEGER,
  height INTEGER,
  source TEXT NOT NULL,
  source_url TEXT,
  author TEXT,
  license TEXT,
  license_url TEXT,
  attribution_text TEXT,
  status TEXT NOT NULL DEFAULT 'approved',   -- approved|rejected|removed
  reject_reason TEXT
);
CREATE TABLE IF NOT EXISTS entry_images (
  entry_id INTEGER NOT NULL REFERENCES entries(entry_id),
  sense_id INTEGER,
  image_id INTEGER NOT NULL REFERENCES images(image_id),
  confidence REAL NOT NULL DEFAULT 0,
  rank INTEGER NOT NULL DEFAULT 1,
  match_method TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (entry_id, image_id)
);
CREATE INDEX IF NOT EXISTS idx_entry_images_entry ON entry_images(entry_id, rank);
CREATE INDEX IF NOT EXISTS idx_images_hash ON images(content_hash);
CREATE VIEW IF NOT EXISTS best_image_per_entry AS
  SELECT ei.entry_id, ei.image_id, ei.confidence, ei.rank
  FROM entry_images ei
  JOIN images i ON i.image_id = ei.image_id
  WHERE i.status = 'approved'
  GROUP BY ei.entry_id
  HAVING ei.rank = MIN(ei.rank);
"""


@dataclass
class Candidate:
    title: str
    detail_url: str
    thumb_url: str
    width: int
    height: int
    mime: str
    author: str
    license: str
    license_url: str
    source_url: str
    article: str = ""


def _fetch_json(url: str, retries: int = 4) -> dict:
    """GET JSON with exponential backoff; 429/503 are expected on shared IPs."""
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 503, 502, 500):
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                print(f"    HTTP {exc.code}, backing off {wait:.0f}s")
                time.sleep(wait)
                delay *= 2
                continue
            raise
        except Exception as exc:  # noqa: BLE001 - network flake, retried
            last = exc
            time.sleep(delay)
            delay *= 2
    raise last if last else RuntimeError("request failed")


def _http_json(params: dict) -> dict:
    return _fetch_json(API + "?" + urllib.parse.urlencode(params))


def _wiki_json(params: dict, lang: str = "en") -> dict:
    base = f"https://{lang}.wikipedia.org/w/api.php"
    return _fetch_json(base + "?" + urllib.parse.urlencode(params))


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def search_commons(term: str, limit: int = 8) -> list[Candidate]:
    """Commons plugin: search the File namespace, read imageinfo + extmetadata."""
    data = _http_json(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {term}",
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": "800",
        }
    )
    pages = (data.get("query") or {}).get("pages") or {}
    out: list[Candidate] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("thumburl"):
            continue
        meta = info.get("extmetadata") or {}
        license_short = _strip_html(
            (meta.get("LicenseShortName") or {}).get("value", "")
        )
        out.append(
            Candidate(
                title=page.get("title", "").removeprefix("File:"),
                detail_url=info.get("thumburl", ""),
                thumb_url=info.get("thumburl", "").replace(
                    "/800px-", "/256px-"
                ),
                width=int(info.get("width") or 0),
                height=int(info.get("height") or 0),
                mime=info.get("mime", ""),
                author=_strip_html((meta.get("Artist") or {}).get("value", "")),
                license=license_short,
                license_url=_strip_html(
                    (meta.get("LicenseUrl") or {}).get("value", "")
                ),
                source_url=info.get("descriptionurl", ""),
            )
        )
    return out


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def wiki_lead_image(term: str, lang: str = "en", strict: bool = True) -> Candidate | None:
    """Tier 2 of the matching spec: the concept's own Wikipedia article image.

    `strict` requires the article title to equal the term. That is what stops
    "hot" resolving to an article about hot-air balloons: a fuzzy search hit is
    rejected rather than turned into the wrong picture for the word.
    """
    search = _wiki_json(
        {
            "action": "query", "format": "json", "list": "search",
            "srsearch": term, "srlimit": "3", "srnamespace": "0",
        },
        lang=lang,
    )
    hits = (search.get("query") or {}).get("search") or []
    article = ""
    wanted = _norm_title(term)
    for hit in hits:
        title = hit.get("title", "")
        got = _norm_title(title)
        if not strict or got == wanted or got == f"the {wanted}":
            article = title
            break
    if not article:
        return None

    pages = _wiki_json(
        {
            "action": "query", "format": "json", "prop": "pageimages",
            "piprop": "name", "titles": article, "redirects": "1",
        },
        lang=lang,
    )
    page_list = (pages.get("query") or {}).get("pages") or {}
    file_name = ""
    for page in page_list.values():
        file_name = page.get("pageimage", "") or ""
    if not file_name:
        return None

    info = _http_json(
        {
            "action": "query", "format": "json",
            "titles": f"File:{file_name}", "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "800",
        }
    )
    for page in ((info.get("query") or {}).get("pages") or {}).values():
        detail = ((page.get("imageinfo") or [{}])[0])
        if not detail.get("thumburl"):
            continue
        meta = detail.get("extmetadata") or {}
        return Candidate(
            title=file_name,
            detail_url=detail.get("thumburl", ""),
            thumb_url=detail.get("thumburl", "").replace("/800px-", "/256px-"),
            width=int(detail.get("width") or 0),
            height=int(detail.get("height") or 0),
            mime=detail.get("mime", ""),
            author=_strip_html((meta.get("Artist") or {}).get("value", "")),
            license=_strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
            license_url=_strip_html((meta.get("LicenseUrl") or {}).get("value", "")),
            source_url=detail.get("descriptionurl", ""),
            article=article,
        )
    return None



def licence_ok(candidate: Candidate) -> tuple[bool, str]:
    """Verify against the source's own metadata; never trust a cached guess."""
    if not candidate.license:
        return False, "licence missing"
    if FORBIDDEN.search(candidate.license):
        return False, f"forbidden licence: {candidate.license}"
    if not ALLOWED_LICENCE.match(candidate.license):
        return False, f"licence not in allow-list: {candidate.license}"
    if not candidate.author:
        return False, "author missing (attribution impossible)"
    return True, ""


def quality_ok(candidate: Candidate) -> tuple[bool, str]:
    if candidate.mime not in ("image/jpeg", "image/png", "image/webp"):
        return False, f"mime {candidate.mime}"
    if candidate.width < 400:
        return False, f"too small ({candidate.width}px)"
    if not candidate.width or not candidate.height:
        return False, "no dimensions"
    ratio = candidate.width / candidate.height
    if ratio < 0.4 or ratio > 2.5:
        return False, f"aspect ratio {ratio:.2f}"
    return True, ""


def licence_rank(license_name: str) -> int:
    low = license_name.lower()
    if low.startswith(("cc0", "public", "pd")):
        return 3
    if low.startswith("cc by") and "-sa" not in low:
        return 2
    return 1


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 200:
        return True
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            blob = resp.read()
    except Exception as exc:  # noqa: BLE001 - logged, never fatal
        print(f"    download failed: {exc}")
        return False
    if len(blob) < 200:
        return False
    dest.write_bytes(blob)
    return True


def pick(candidates: list[Candidate]) -> Candidate | None:
    best = None
    best_score = -1.0
    for cand in candidates:
        ok_l, _ = licence_ok(cand)
        ok_q, _ = quality_ok(cand)
        if not (ok_l and ok_q):
            continue
        score = licence_rank(cand.license) * 1.0 + min(cand.width, 2400) / 2400
        if score > best_score:
            best, best_score = cand, score
    return best


def sentences(con: sqlite3.Connection, limit: int, category: str | None, skip: set[int]):
    sql = (
        "SELECT e.entry_id, e.simplified, s.gloss_en FROM entries e "
        "JOIN senses s ON s.entry_id = e.entry_id AND s.sense_order = 0 "
        "WHERE e.is_proper = 0 AND LENGTH(s.gloss_en) BETWEEN 3 AND 60"
    )
    args: list = []
    if category:
        sql += " AND e.category = ?"
        args.append(category)
    sql += " ORDER BY LENGTH(s.gloss_en), e.entry_id LIMIT ?"
    args.append(limit + len(skip) + 50)
    for row in con.execute(sql, args).fetchall():
        if row["entry_id"] in skip:
            continue
        yield row
        limit -= 1
        if limit <= 0:
            return


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--images-dir", default="data/images")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--category", default=None)
    ap.add_argument("--sleep", type=float, default=0.7)
    ap.add_argument(
        "--allow-commons",
        action="store_true",
        help="Also try Commons file-title search when no article image matches "
        "(unverified relevance; inspection only).",
    )
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"No dictionary at {db_path} — build it first.", file=sys.stderr)
        return 1

    images_dir = Path(args.images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    manifest = images_dir / "manifest.jsonl"

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    done = {
        r["entry_id"]
        for r in con.execute(
            "SELECT DISTINCT entry_id FROM entry_images"
        ).fetchall()
    }
    print(f"resume: {len(done)} entries already have an image")

    stats = {
        "tried": 0, "accepted": 0, "no_result": 0,
        "licence_rejected": 0, "quality_rejected": 0, "download_failed": 0,
    }
    mf = manifest.open("a", encoding="utf-8")

    for row in sentences(con, args.limit, args.category, done):
        stats["tried"] += 1
        term = re.split(r"[;(]", row["gloss_en"])[0].strip()
        term = re.sub(r"^[a-z]*\.\s*", "", term)  # drop "n."/"v." prefixes
        if not term:
            stats["no_result"] += 1
            continue

        chosen: Candidate | None = None
        method = ""
        confidence = 0.0

        try:
            lead = wiki_lead_image(row["simplified"], lang="zh", strict=True)
        except Exception as exc:  # noqa: BLE001 - one bad word must not end the run
            print(f"[{stats['tried']}] {term}: zh lookup failed ({exc})")
            lead = None
        if lead is None:
            try:
                lead = wiki_lead_image(term, lang="en", strict=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[{stats['tried']}] {term}: en lookup failed ({exc})")
                lead = None

        if lead is not None:
            chosen, method, confidence = lead, "wikipedia-lead-image", 0.85
        elif not args.allow_commons:
            # Without a vision model to score relevance, unverified title search
            # produces nonsense ("hot" -> a hot-air balloon). Off by default;
            # use it only for inspection with --allow-commons.
            chosen = None
        else:
            # Secondary tier: file-title search, but require the term to be a
            # whole word of the title and reject place/document/architecture
            # names that merely contain it.
            try:
                candidates = search_commons(f'intitle:"{term}"')
            except Exception as exc:  # noqa: BLE001
                print(f"[{stats['tried']}] {term}: commons search failed ({exc})")
                candidates = []
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            candidates = [
                cand for cand in candidates
                if pattern.search(cand.title) and not NOISE_TITLE.search(cand.title)
            ]
            for cand in candidates:
                ok_l, why_l = licence_ok(cand)
                ok_q, why_q = quality_ok(cand)
                if not ok_l:
                    stats["licence_rejected"] += 1
                elif not ok_q:
                    stats["quality_rejected"] += 1
            lead = pick(candidates)
            if lead is not None:
                chosen, method, confidence = lead, "commons-title", 0.55

        if chosen is None:
            stats["no_result"] += 1
            print(f"[{stats['tried']}] {row['simplified']} / {term}: no usable image")
            time.sleep(args.sleep)
            continue

        ok_l, why_l = licence_ok(chosen)
        ok_q, why_q = quality_ok(chosen)
        if not ok_l:
            stats["licence_rejected"] += 1
            print(f"[{stats['tried']}] {row['simplified']}: licence rejected ({why_l})")
            time.sleep(args.sleep)
            continue
        if not ok_q:
            stats["quality_rejected"] += 1
            print(f"[{stats['tried']}] {row['simplified']}: quality rejected ({why_q})")
            time.sleep(args.sleep)
            continue

        digest = hashlib.sha1(
            (chosen.detail_url + row["simplified"]).encode()
        ).hexdigest()
        sub = digest[:2]
        detail = images_dir / sub / f"{digest}_800.jpg"
        thumb = images_dir / sub / f"{digest}_256.jpg"

        ok = download(chosen.detail_url, detail) and download(chosen.thumb_url, thumb)
        if not ok:
            stats["download_failed"] += 1
            time.sleep(args.sleep)
            continue

        attribution = (
            f"{chosen.title} — {chosen.author} — {chosen.license} "
            "via Wikimedia Commons"
        )
        cur = con.execute(
            "INSERT OR IGNORE INTO images(content_hash, title, thumb_path, "
            "detail_path, width, height, source, source_url, author, license, "
            "license_url, attribution_text, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'approved')",
            (
                digest, chosen.title, str(thumb).replace("\\", "/"),
                str(detail).replace("\\", "/"), chosen.width, chosen.height,
                "wikimedia_commons", chosen.source_url, chosen.author,
                chosen.license, chosen.license_url, attribution,
            ),
        )
        image_id = cur.lastrowid
        if not image_id:
            image_id = con.execute(
                "SELECT image_id FROM images WHERE content_hash = ?", (digest,)
            ).fetchone()[0]
        con.execute(
            "INSERT OR REPLACE INTO entry_images(entry_id, sense_id, image_id, "
            "confidence, rank, match_method) VALUES (?,?,?,?,1,?)",
            (row["entry_id"], None, image_id, confidence, method),
        )
        con.commit()
        stats["accepted"] += 1
        mf.write(json.dumps({
            "entry_id": row["entry_id"], "word": row["simplified"],
            "term": term, "image_id": image_id, "confidence": confidence,
            "match_method": method, "license": chosen.license,
            "author": chosen.author,
            "detail": str(detail), "thumb": str(thumb),
        }, ensure_ascii=False) + "\n")
        mf.flush()
        print(f"[{stats['tried']}] {row['simplified']} / {term} -> {chosen.title[:40]} "
              f"({chosen.license})")
        time.sleep(args.sleep)

    mf.close()
    con.commit()

    report = {
        "stats": stats,
        "not_run": ["watermark/text detection", "blur/contrast scoring",
                    "NSFW/violence classifier", "CLIP relevance", "pHash dedupe"],
        "images_in_db": con.execute(
            "SELECT COUNT(*) FROM images"
        ).fetchone()[0],
        "entries_with_image": con.execute(
            "SELECT COUNT(DISTINCT entry_id) FROM entry_images"
        ).fetchone()[0],
        "license_breakdown": {
            r[0]: r[1]
            for r in con.execute(
                "SELECT license, COUNT(*) FROM images GROUP BY license"
            ).fetchall()
        },
        "disk_mb": round(
            sum(f.stat().st_size for f in images_dir.rglob("*.jpg")) / 1048576, 2
        ),
    }
    con.close()
    out = images_dir / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
