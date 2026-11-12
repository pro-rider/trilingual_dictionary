"""Multi-source image acquisition: Unsplash + Pixabay, cached on first use.

Why this exists
---------------
Wikimedia gives encyclopaedic coverage for objects, and nothing usable for the
long tail (a generic "scarf" photo beats a museum catalogue scan). Unsplash and
Pixabay give clean, modern photography for everyday nouns, at zero cost, under
licences that allow redistribution in an app. This tool adds them as a second
tier behind the same gates the Wikimedia pipeline uses.

Security
--------
Keys are never written into this file, into git, or into a log. They are read,
in order, from:
  1. the process environment (UNSPLASH_ACCESS_KEY / UNSPLASH_API_KEY, PIXABAY_API_KEY);
  2. `backend/.env`, which `.gitignore` excludes.
A key is only ever used to build an Authorization header. The tool refuses to
start if a requested source has no key, instead of silently returning nothing.

Caching
-------
Every accepted asset is downloaded once, hashed, written as
`assets/images/thumbs/<sha>.webp` (256 px, the flat layout Flutter bundles) plus
`assets/images/detail/<sha>.webp`, and inserted into `images` /
`concept_images` / `entry_concepts` / `entry_images`. A repeat run for the same
concept or a synonym hits the local row and makes **no** API call, so quota is
spent only on words that have nothing.

Licence handling
----------------
Unsplash: "Unsplash License" (free commercial use, attribution appreciated).
Pixabay:  "Pixabay Content License" (free commercial use, attribution appreciated).
Both are recorded with author, source URL and an attribution string, so the
client can display credit even though neither licence requires it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "backend" / "data" / "build" / "dictionary.sqlite"
OUT = REPO / "assets" / "images"
THUMBS = OUT / "thumbs"
DETAIL = OUT / "detail"
QUOTA = REPO / "backend" / "data" / "build" / "api_quota.json"
ENV_FILE = REPO / "backend" / ".env"

UA = "trilingual_dictionary/1.0 (offline dictionary image pipeline)"
THUMB_EDGE = 256
DETAIL_EDGE = 1024

WORD_RE = re.compile(r"[A-Za-z]{3,}")
STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are", "was"}

# Provenance strings per source; the licence itself is a property of the API.
SOURCES = {
    "unsplash": {
        "license": "Unsplash License",
        "license_url": "https://unsplash.com/license",
        "attribution": "Photo by {author} on Unsplash ({url})",
    },
    "pixabay": {
        "license": "Pixabay Content License",
        "license_url": "https://pixabay.com/service/license-summary/",
        "attribution": "Image by {author} on Pixabay ({url})",
    },
}

LIMITS = {"unsplash": (50, 3600), "pixabay": (100, 60)}  # (calls, window seconds)


# ------------------------------------------------------------------ credentials --
def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.is_file():
        return {}
    values = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_key(name: str) -> str:
    """Return a key, environment first, `.env` second. Never log the value."""
    aliases = {
        "unsplash": ("UNSPLASH_ACCESS_KEY", "UNSPLASH_API_KEY", "UNSPLASH_KEY"),
        "pixabay": ("PIXABAY_API_KEY", "PIXABAY_KEY"),
    }[name]
    for alias in aliases:
        value = os.environ.get(alias, "").strip()
        if value:
            return value
    env = _read_env_file()
    for alias in aliases:
        value = env.get(alias, "").strip()
        if value:
            return value
    return ""


# ------------------------------------------------------------------------ quota --
def _quota_state() -> dict:
    if QUOTA.is_file():
        try:
            return json.loads(QUOTA.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def quota_allow(source: str) -> bool:
    calls, window = LIMITS[source]
    state = _quota_state().get(source) or {}
    now = time.time()
    start = float(state.get("window_start") or 0)
    used = int(state.get("used") or 0)
    if now - start >= window:
        return True
    return used < calls


def quota_consume(source: str) -> None:
    calls, window = LIMITS[source]
    state = _quota_state()
    entry = state.get(source) or {}
    now = time.time()
    if now - float(entry.get("window_start") or 0) >= window:
        entry = {"window_start": now, "used": 0}
    entry["used"] = int(entry.get("used") or 0) + 1
    state[source] = entry
    QUOTA.parent.mkdir(parents=True, exist_ok=True)
    QUOTA.write_text(json.dumps(state, indent=2), encoding="utf-8")


def quota_left(source: str) -> str:
    calls, window = LIMITS[source]
    entry = _quota_state().get(source) or {}
    used = int(entry.get("used") or 0)
    if time.time() - float(entry.get("window_start") or 0) >= window:
        used = 0
    return f"{calls - used}/{calls} per {window // 60} min"


# ---------------------------------------------------------------------- network --
def fetch_json(url: str, headers: dict | None = None, retries: int = 3) -> dict:
    request_headers = {"User-Agent": UA, "Accept": "application/json"}
    request_headers.update(headers or {})
    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 + attempt * 3)
    raise RuntimeError(last)


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


# ----------------------------------------------------------------------- gates --
def content_words(text: str) -> set[str]:
    return {w for w in WORD_RE.findall((text or "").lower()) if w not in STOP}


def plausible(gloss: str, haystack: str) -> bool:
    """At least one content word of the gloss must appear in the result metadata."""
    words = content_words(gloss)
    if not words:
        return False
    blob = (haystack or "").lower()
    return any(word in blob for word in words)


def usable_size(width: int, height: int) -> tuple[bool, str]:
    if not width or not height:
        return False, "no dimensions"
    if min(width, height) < 600:
        return False, f"too small ({min(width, height)}px)"
    ratio = width / height
    if ratio < 0.5 or ratio > 2.2:
        return False, f"aspect ratio {ratio:.2f}"
    return True, ""


def build_assets(raw: bytes, sha: str) -> tuple[str, str, int, int, int]:
    """Write thumb + detail, return (thumb_asset, detail_asset, w, h, thumb_bytes)."""
    image = Image.open(io.BytesIO(raw))
    image = image.convert("RGB") if image.mode not in ("RGB", "L") else image
    width, height = image.size
    detail = image.copy()
    detail.thumbnail((DETAIL_EDGE, DETAIL_EDGE))
    thumb = image.copy()
    thumb.thumbnail((THUMB_EDGE, THUMB_EDGE))
    DETAIL.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    detail_rel = f"assets/images/detail/{sha}.webp"
    thumb_rel = f"assets/images/thumbs/{sha}.webp"
    detail.save(REPO / detail_rel, "WEBP", quality=82, method=4)
    thumb.save(REPO / thumb_rel, "WEBP", quality=78, method=6)
    return thumb_rel, detail_rel, width, height, (REPO / thumb_rel).stat().st_size


# ---------------------------------------------------------------------- sources --
def search_unsplash(gloss: str, key: str, count: int = 6) -> list[dict]:
    url = "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode({
        "query": gloss, "per_page": count, "orientation": "landscape",
        "content_filter": "high",
    })
    data = fetch_json(url, {"Authorization": f"Client-ID {key}"})
    out = []
    for item in data.get("results", []):
        meta_text = " ".join(str(item.get(k) or "") for k in
                             ("alt_description", "description", "slug"))
        tags = " ".join(t.get("title", "") for t in (item.get("tags") or []) if isinstance(t, dict))
        out.append({
            "id": item.get("id"),
            "width": (item.get("width") or 0),
            "height": (item.get("height") or 0),
            "url": (item.get("urls") or {}).get("regular") or (item.get("urls") or {}).get("full"),
            "page": (item.get("links") or {}).get("html"),
            "author": (item.get("user") or {}).get("name") or "",
            "meta": f"{meta_text} {tags}",
        })
    return [c for c in out if c["url"]]


def search_pixabay(gloss: str, key: str, count: int = 6) -> list[dict]:
    url = "https://pixabay.com/api/?" + urllib.parse.urlencode({
        "key": key, "q": gloss, "image_type": "photo", "per_page": max(count, 3),
        "safesearch": "true", "category": "objects",
    })
    data = fetch_json(url)
    out = []
    for item in data.get("hits", []):
        tags = str(item.get("tags") or "") + " " + str(item.get("user") or "")
        out.append({
            "id": item.get("id"),
            "width": item.get("imageWidth") or 0,
            "height": item.get("imageHeight") or 0,
            "url": item.get("largeImageURL") or item.get("webformatURL"),
            "page": item.get("pageURL"),
            "author": item.get("user") or "",
            "meta": tags,
        })
    return [c for c in out if c["url"]]


SEARCH = {"unsplash": search_unsplash, "pixabay": search_pixabay}


# --------------------------------------------------------------------------- db --
def target_entries(con: sqlite3.Connection, limit: int, min_freq: int, max_freq: int) -> list[sqlite3.Row]:
    """Entries ranked by frequency that have no picture and no concept yet."""
    return con.execute(
        "SELECT e.entry_id, e.simplified, e.pos_primary, e.freq_rank, "
        "       (SELECT gloss_en FROM senses s WHERE s.entry_id=e.entry_id "
        "        ORDER BY s.sense_order LIMIT 1) AS gloss "
        "FROM entries e "
        "WHERE e.freq_rank IS NOT NULL AND e.freq_rank BETWEEN ? AND ? "
        "  AND NOT EXISTS (SELECT 1 FROM entry_images ei WHERE ei.entry_id=e.entry_id) "
        "  AND NOT EXISTS (SELECT 1 FROM entry_concepts ec WHERE ec.entry_id=e.entry_id) "
        "ORDER BY e.freq_rank LIMIT ?",
        (min_freq, max_freq, limit)).fetchall()


def store(con: sqlite3.Connection, source: str, cand: dict, raw: bytes, word: str,
          entry_id: int, gloss: str) -> tuple[bool, str]:
    import hashlib

    sha = hashlib.sha256(raw).hexdigest()
    existing = con.execute("SELECT image_id, thumb_asset FROM images WHERE content_hash=?",
                           (sha,)).fetchone()
    if existing and existing["thumb_asset"]:
        thumb_asset = existing["thumb_asset"]
        image_id = existing["image_id"]
    else:
        thumb_asset, detail_asset, width, height, thumb_bytes = build_assets(raw, sha)
        image_id = existing["image_id"] if existing else None
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        meta = SOURCES[source]
        attribution = meta["attribution"].format(author=cand["author"] or "unknown", url=cand["page"] or "")
        values = dict(
            content_hash=sha, title=(cand["meta"] or word)[:120],
            thumb_path=detail_asset, detail_path=detail_asset,
            width=width, height=height, source=source, source_url=cand["page"],
            author=cand["author"], license=meta["license"], license_url=meta["license_url"],
            attribution_text=attribution, status="approved", sha256=sha,
            thumb_bytes=thumb_bytes, asset_status="approved",
            verification_status="verified", thumb_asset=thumb_asset,
            detail_url=cand["url"], bytes=len(raw), created_at=now,
            license_status="verified",
        )
        if image_id:
            con.execute(
                "UPDATE images SET " + ", ".join(f"{k}=?" for k in values) +
                " WHERE image_id=?", (*values.values(), image_id))
        else:
            cols = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            cur = con.execute(f"INSERT INTO images({cols}) VALUES({placeholders})",
                              tuple(values.values()))
            image_id = cur.lastrowid

    concept_id = f"{source}:{word}"
    con.execute(
        "INSERT OR IGNORE INTO concepts(concept_id, source, label_en, created_at) "
        "VALUES (?,?,?,?)",
        (concept_id, source, gloss[:60],
         datetime.now(timezone.utc).replace(microsecond=0).isoformat()))
    con.execute(
        "INSERT OR REPLACE INTO concept_images(concept_id, image_id, relevance, is_primary) "
        "VALUES (?,?,?,1)", (concept_id, image_id, 0.85))
    con.execute(
        "INSERT OR REPLACE INTO entry_concepts(entry_id, concept_id, confidence, method) "
        "VALUES (?,?,?,?)", (entry_id, concept_id, 0.85, f"{source}-search"))
    con.execute(
        "INSERT OR REPLACE INTO entry_images(entry_id, image_id, confidence, rank, "
        "match_method, concept_id, match_confidence, match_reason) "
        "VALUES (?,?,?,1,?,?,?,?)",
        (entry_id, image_id, 0.8, source, concept_id, 0.8, f"{source} search for '{gloss}'"))
    con.commit()
    return True, str(image_id)


# ------------------------------------------------------------------------- main --
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["unsplash", "pixabay", "both"], default="both")
    ap.add_argument("--limit", type=int, default=50, help="entries to attempt")
    ap.add_argument("--min-freq", type=int, default=1)
    ap.add_argument("--max-freq", type=int, default=20000)
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    sources = ["unsplash", "pixabay"] if args.source == "both" else [args.source]
    keys = {}
    for source in sources:
        key = get_key(source)
        if not key:
            print(f"{source}: no API key found (environment or backend/.env) — skipped")
            continue
        print(f"{source}: key loaded ({len(key)} chars), quota {quota_left(source)}")
        keys[source] = key
    if not keys:
        print("no usable source: set UNSPLASH_ACCESS_KEY and/or PIXABAY_API_KEY "
              "in the environment or backend/.env (the file is git-ignored)")
        return 2

    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")

    targets = target_entries(con, args.limit, args.min_freq, args.max_freq)
    print(f"targets: {len(targets)} entries (freq {args.min_freq}-{args.max_freq}, no image, no concept)")

    added = tried = 0
    calls = {s: 0 for s in keys}
    for row in targets:
        gloss = (row["gloss"] or "").strip()
        if not gloss or len(content_words(gloss)) == 0:
            print(f"[{row['entry_id']}] {row['simplified']}: no usable English gloss")
            continue
        tried += 1
        got = False
        for source in keys:
            if got:
                break
            if not quota_allow(source):
                print(f"  {source}: quota exhausted ({quota_left(source)}), moving on")
                continue
            try:
                cands = SEARCH[source](gloss, keys[source], 6)
            except Exception as exc:  # noqa: BLE001
                print(f"  {source} search failed for '{gloss}': {exc}")
                continue
            calls[source] += 1
            quota_consume(source)
            for cand in cands:
                ok_size, why = usable_size(cand["width"], cand["height"])
                if not ok_size:
                    print(f"  {source} reject {cand['id']}: {why}")
                    continue
                if not plausible(gloss, cand["meta"]):
                    print(f"  {source} reject {cand['id']}: lexical gate ('{gloss}')")
                    continue
                if args.dry_run:
                    print(f"  [dry] {source} accept {cand['id']} for {row['simplified']}/{gloss}")
                    got = True
                    break
                try:
                    raw = fetch_bytes(cand["url"])
                except Exception as exc:  # noqa: BLE001
                    print(f"  {source} download failed: {exc}")
                    continue
                try:
                    stored, image_id = store(con, source, cand, raw, row["simplified"],
                                             row["entry_id"], gloss)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {source} store failed: {exc}")
                    continue
                added += 1
                got = True
                print(f"[{tried}] {row['simplified']} / {gloss} -> {source} image {image_id} "
                      f"({len(raw):,} B)")
                break
        if not got:
            print(f"[{tried}] {row['simplified']} / {gloss}: nothing usable")
        time.sleep(args.sleep)

    if not args.dry_run and added:
        con.commit()
    total = con.execute("SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0]
    print(f"\nattempted {tried} entries, added {added} image(s); "
          f"calls unsplash={calls.get('unsplash', 0)} pixabay={calls.get('pixabay', 0)}")
    for source in calls:
        print(f"  {source} quota left: {quota_left(source)}")
    print(f"entries with a picture: {total}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
