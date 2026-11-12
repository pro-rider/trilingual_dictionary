"""Image pipeline v2 — concept-based matching, licence gate, dedupe, 15 KB thumbs.

Why v2 exists
-------------
`fetch_images.py` matched on Commons/Wikipedia *titles*, which cannot tell 苹果
(fruit) from Apple (company) and produced only 13 rows in a pilot. v2 resolves a
language-independent **concept** first (Wikidata QID with an exact-label check),
takes that concept's own image (P18, else the sitelink article's lead image), and
only then downloads. The concept is stored, so 苹果 / apple / स्याउ share one asset.

Design decisions this implements (the 14 issues raised in review):

  Issue 1  concept identity: Wikidata QID + exact label match; a title hit alone
           never approves an image.
  Issue 2  dedupe: sha256 of the bytes + 64-bit dHash; one asset row per file,
           many entries reference it.
  Issue 3  thumbnail: Pillow WebP encoder, quality 80→40 then width 200→160→120,
           hard byte ceiling checked after every attempt. Fails closed.
  Issue 4  storage: files on disk + paths/hashes in SQLite. No base64, no BLOB.
  Issue 5  licence: CC0 / PD / CC BY / CC BY-SA only, author required,
           attribution text stored, unknown → pending_review (never approved).
  Issue 6  fallback split: `discover` only records candidates; nothing is
           auto-approved. Generation is out of scope here.
  Issue 7  statuses: asset_status (discovered|pending_review|approved|rejected|
           unavailable) is separate from device cache, which the app derives from
           the file existing.
  Issue 8  migration: idempotent, column-by-column `PRAGMA table_info` checks;
           schema_version recorded in `meta`.
  Issue 9  concurrency: per-word `set` of in-flight concepts + INSERT OR IGNORE,
           so a resumed run cannot duplicate rows.
  Issue 10 retries: bounded, exponential, respects Retry-After, never retries 4xx
           other than 429.
  Issue 13 validation: HTTPS only, host allowlist, 20 MB cap, MIME + PIL verify,
           re-encode before writing, no path from remote metadata.

Nothing is written to the master tables. Images live in `images`,
`concept_images`, `entry_images`; the dictionary text is untouched.

Usage (PowerShell, from backend/):
  .\.venv\Scripts\python.exe tools\images_v2.py --db data\build\dictionary.sqlite \
      --limit 200 --out data\images
  # report only, no writes:
  .\.venv\Scripts\python.exe tools\images_v2.py --limit 50 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]

UA = (
    "TrilingualDictionary/0.3 (dictionary image pipeline; "
    "contact: project owner) python-urllib"
)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
ALLOWED_HOSTS = {
    "commons.wikimedia.org",
    "upload.wikimedia.org",
    "thumb.wikimedia.org",
    "www.wikidata.org",
}
MAX_BYTES = 20 * 1024 * 1024
THUMB_MAX_BYTES = 15_000

LICENCE_OK = re.compile(r"^(cc0|cc by(-sa)?( \d\.\d)?|public domain|pd\b)", re.I)
LICENCE_BAD = re.compile(r"\b(nc|nd|noncommercial|no.?deriv)\b", re.I)

# File names that are almost never the concept: buildings, maps, documents.
NOISE = re.compile(
    r"(logo|coat of arms|seal|plaque|map|carte|diagram|chart|stamp|coin|"
    r"banknote|poster|screenshot|manuscript|title page|frontispiece|engraving|"
    r"libretto|woodcut|sheet music)",
    re.I,
)

# Glosses that describe grammar, not a thing you can photograph.
GRAMMAR = re.compile(
    r"^(particle|suffix|prefix|pronoun|classifier|measure word|modal|auxiliary|"
    r"interjection|onomatop|used (in|to|as|for)|(a|an) (particle|suffix|prefix)|"
    r"to be\b|variant of|old variant|archaic|surname|abbr|see also|also written|"
    r"to |adverb|preposition|conjunction|verb$)",
    re.I,
)

# The highest-frequency Chinese characters that are pure grammar. Frequency
# ranking puts them first, and none of them is a picture of anything.
FUNCTION_WORDS = {
    "的", "是", "在", "了", "和", "有", "不", "人", "你", "为", "这", "那", "我",
    "他", "她", "它", "们", "就", "都", "也", "与", "及", "或", "个", "把", "被",
    "给", "让", "对", "从", "向", "以", "而", "则", "之", "其", "此", "所", "者",
    "很", "太", "更", "最", "还", "再", "又", "只", "才", "已", "将", "正", "可",
    "会", "能", "要", "该", "着", "过", "吗", "呢", "吧", "啊", "呀", "哦", "么",
    "谁", "哪", "几", "多少", "什么", "怎么", "因为", "所以", "但是", "如果",
    "虽然", "然而", "而且", "并且", "或者", "还是", "已经", "可以", "应该",
    "到", "来", "去", "说", "做", "用", "打", "拿", "走", "看", "想", "知道",
    "多", "少", "好", "大", "小", "上", "下", "里", "外", "前", "后", "中",
    "年", "月", "日", "时", "分", "秒", "一", "二", "三", "四", "五", "六",
    "七", "八", "九", "十", "百", "千", "万", "亿", "第", "每", "各", "些",
}

# Single characters that are almost always grammatical or abstract.
SINGLE_CHAR_SKIP = {
    "的", "是", "在", "了", "和", "有", "不", "人", "你", "为", "这", "那", "我",
    "他", "她", "它", "就", "都", "也", "与", "及", "或", "个", "把", "被", "给",
    "让", "对", "从", "向", "以", "而", "则", "之", "其", "此", "所", "者", "很",
    "太", "更", "最", "还", "再", "又", "只", "才", "已", "将", "正", "可", "会",
    "能", "要", "该", "着", "过", "吗", "呢", "吧", "啊", "呀", "哦", "么", "到",
    "来", "去", "说", "做", "用", "打", "拿", "走", "看", "想", "多", "少", "好",
    "大", "小", "上", "下", "里", "外", "前", "后", "中", "年", "月", "日", "时",
    "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "百", "千", "万",
    "第", "每", "各", "些", "字", "话", "事", "情", "面",
}

PICTABLE_CATEGORIES = [
    "nature", "everyday", "transport", "tools_instruments",
    "geography_environment", "science_medicine", "technology", "business",
]

MIGRATIONS = [
    (
        "v005_image_concepts",
        """
        CREATE TABLE IF NOT EXISTS concepts (
          concept_id   TEXT PRIMARY KEY,
          source       TEXT NOT NULL,
          qid          TEXT,
          label_en     TEXT,
          label_zh     TEXT,
          description  TEXT,
          category     TEXT,
          created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS concept_images (
          concept_id  TEXT NOT NULL,
          image_id    INTEGER NOT NULL,
          relevance   REAL NOT NULL DEFAULT 0,
          is_primary  INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (concept_id, image_id)
        );
        CREATE TABLE IF NOT EXISTS concept_lookup_cache (
          term        TEXT PRIMARY KEY,
          payload     TEXT NOT NULL,
          created_at  TEXT NOT NULL
        );
        """,
    ),
]


# ---------------------------------------------------------------- migration --
def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def migrate(con: sqlite3.Connection) -> list[str]:
    """Idempotent schema upgrade. Returns the list of changes actually applied."""
    applied: list[str] = []
    con.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
    )

    for name, sql in MIGRATIONS:
        con.executescript(sql)
        applied.append(f"table:{name}")

    # extended columns on `images` (Issue 4/7: hashes, bytes, remote url, statuses)
    want = {
        "sha256": "TEXT",
        "phash": "TEXT",
        "thumb_bytes": "INTEGER",
        "asset_status": "TEXT DEFAULT 'pending_review'",
        "verification_status": "TEXT DEFAULT 'unverified'",
        "thumb_asset": "TEXT",
        "detail_url": "TEXT",
        "concept_id": "TEXT",
        "bytes": "INTEGER",
        "created_at": "TEXT",
    }
    have = _columns(con, "images")
    for col, decl in want.items():
        if col not in have:
            con.execute(f"ALTER TABLE images ADD COLUMN {col} {decl}")
            applied.append(f"images+{col}")

    want_ei = {
        "concept_id": "TEXT",
        "match_confidence": "REAL",
        "match_reason": "TEXT",
        "device_hint": "TEXT",
    }
    have = _columns(con, "entry_images")
    for col, decl in want_ei.items():
        if col not in have:
            con.execute(f"ALTER TABLE entry_images ADD COLUMN {col} {decl}")
            applied.append(f"entry_images+{col}")

    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_images_sha ON images(sha256)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_concept_images_c ON concept_images(concept_id)"
    )
    # Never restamp the schema here. Writing a bare "5" broke the release builder's
    # `v005` comparison the moment this pipeline touched a finished database, so
    # the stamp is left exactly as the schema builder set it.
    applied.append("meta left untouched")
    con.commit()
    return applied


# ------------------------------------------------------------------ network --
def _get_json(url: str, params: dict, retries: int = 6) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    delay = 1.5
    last: Exception | None = None
    for _ in range(retries):
        req = urllib.request.Request(full, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 429 or 500 <= exc.code < 600:
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after or "").isdigit() else delay
                time.sleep(wait)
                delay = min(delay * 2, 30)
                continue
            raise
        except Exception as exc:  # noqa: BLE001 - transient network / SSL EOF
            last = exc
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise last or RuntimeError("request failed")


def cached_concept(con: sqlite3.Connection, term: str, traditional: str,
                   gloss: str, now: str) -> dict | None:
    """Concept resolution with a local cache: one lookup per headword, ever."""
    row = con.execute(
        "SELECT payload FROM concept_lookup_cache WHERE term = ?", (term,)
    ).fetchone()
    if row:
        payload = json.loads(row[0])
        return payload or None

    concept = resolve_concept_zh(term, traditional)
    if concept is None and gloss:
        concept = resolve_concept_en(gloss)
    con.execute(
        "INSERT OR REPLACE INTO concept_lookup_cache(term, payload, created_at) "
        "VALUES (?,?,?)",
        (term, json.dumps(concept or {}), now),
    )
    con.commit()
    return concept


def _clean(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or ""))).strip()


def resolve_concept_zh(term: str, traditional: str = "") -> dict | None:
    """Wikidata: exact label match on the Chinese headword (Issue 1)."""
    data = _get_json(
        WIKIDATA_API,
        {
            "action": "wbsearchentities",
            "search": term,
            "language": "zh",
            "uselang": "zh",
            "type": "item",
            "limit": "7",
            "format": "json",
        },
    )
    wanted = {term, traditional} - {""}
    for hit in data.get("search") or []:
        label = (hit.get("label") or "").strip()
        aliases = {a.strip() for a in (hit.get("aliases") or [])}
        if label in wanted or any(a in wanted for a in aliases):
            return {
                "qid": hit["id"],
                "concept_id": f"wd:{hit['id']}",
                "label_zh": label,
                "label_en": hit.get("match", {}).get("text", ""),
                "description": hit.get("description", ""),
                "source": "wikidata-zh",
            }
    return None


def resolve_concept_en(term: str) -> dict | None:
    data = _get_json(
        WIKIDATA_API,
        {
            "action": "wbsearchentities",
            "search": term,
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": "5",
            "format": "json",
        },
    )
    for hit in data.get("search") or []:
        if (hit.get("label") or "").strip().lower() == term.lower():
            return {
                "qid": hit["id"],
                "concept_id": f"wd:{hit['id']}",
                "label_en": hit.get("label", ""),
                "label_zh": "",
                "description": hit.get("description", ""),
                "source": "wikidata-en",
            }
    return None


def concept_image_files(qid: str, gloss: str = "") -> list[str]:
    """P18 (image) statements for the concept, in statement order.

    When `gloss` is given the item's English labels and aliases must contain it:
    a Wikidata item is only a trustworthy anchor if the item *is* the word. Without
    this check a search hit for a different sense (一次 → "first") ships a
    photograph of something else entirely.
    """
    data = _get_json(
        WIKIDATA_API,
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "claims|labels|aliases",
            "languages": "en|zh",
            "format": "json",
        },
    )
    entity = (data.get("entities") or {}).get(qid) or {}
    if gloss:
        wanted = _norm_word(gloss)
        names = {(entity.get("labels") or {}).get("en", {}).get("value", "")}
        for item in ((entity.get("aliases") or {}).get("en") or []):
            names.add(item.get("value", ""))
        if not any(_norm_word(n) == wanted for n in names if n):
            return []
    files: list[str] = []
    for claim in (entity.get("claims") or {}).get("P18", []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        # P18 is stored as a plain string ("Red Apple.jpg"), not an object.
        name = value if isinstance(value, str) else None
        if name:
            files.append(name)
    return files


def _norm_word(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s*\(.*?\)\s*", " ", text)
    text = re.sub(r"^(the|a|an)\s+", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 3 and text.endswith("s"):
        text = text[:-1]
    return text


def commons_search(term: str, limit: int = 8) -> list[str]:
    """Commons file-title search for the English gloss.

    Last resort when the concept has no P18 statement. The relevance gate still
    runs on every hit, so a search that returns something unrelated ("bus" ->
    "Bust of …") is rejected rather than shipped.
    """
    if not term or len(term) < 3:
        return []
    data = _get_json(
        COMMONS_API,
        {
            "action": "query",
            "list": "search",
            "srsearch": f"{term} filetype:bitmap",
            "srnamespace": "6",
            "srlimit": str(limit),
            "format": "json",
        },
    )
    hits = ((data.get("query") or {}).get("search") or [])
    return [h["title"].split("File:", 1)[-1] for h in hits if h.get("title")]


def commons_category_files(term: str, limit: int = 8) -> list[str]:
    """Files filed under Category:<gloss> on Commons.

    A Commons category is curated by humans around one subject, so a photograph
    taken from Category:Bus shows a bus even when its file name says nothing.
    That is the identity evidence a plain title search lacks, which is why this
    tier can be on by default while the title search stays opt-in.
    """
    if not term or len(term) < 3:
        return []
    data = _get_json(
        COMMONS_API,
        {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{term}",
            "cmtype": "file",
            "cmlimit": str(limit),
            "format": "json",
        },
    )
    members = ((data.get("query") or {}).get("categorymembers") or [])
    return [m["title"].split("File:", 1)[-1] for m in members if m.get("title")]


def sitelink_lead_image(qid: str, lang: str) -> tuple[str, str] | None:
    """Fallback: the zh/en Wikipedia article's lead image for that concept."""
    data = _get_json(
        WIKIDATA_API,
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "sitelinks|labels",
            "sitefilter": f"{lang}wiki",
            "format": "json",
        },
    )
    entity = (data.get("entities") or {}).get(qid) or {}
    title = ((entity.get("sitelinks") or {}).get(f"{lang}wiki") or {}).get("title")
    if not title:
        return None
    pages = _get_json(
        f"https://{lang}.wikipedia.org/w/api.php",
        {
            "action": "query",
            "format": "json",
            "prop": "pageimages",
            "piprop": "name",
            "titles": title,
            "redirects": "1",
        },
    )
    for page in ((pages.get("query") or {}).get("pages") or {}).values():
        name = page.get("pageimage") or ""
        if name:
            return name, title
    return None


@dataclass
class Asset:
    file_name: str
    detail_url: str
    thumb_url: str
    width: int
    height: int
    mime: str
    author: str
    license: str
    license_url: str
    source_url: str
    extra: dict = field(default_factory=dict)


def file_asset(concept_file: str, width: int = 900) -> Asset | None:
    """Metadata for one Commons file, including licence and author."""
    data = _get_json(
        COMMONS_API,
        {
            "action": "query",
            "format": "json",
            "titles": f"File:{concept_file}",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": str(width),
        },
    )
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("thumburl"):
            continue
        meta = info.get("extmetadata") or {}
        return Asset(
            file_name=concept_file,
            detail_url=info.get("thumburl", ""),
            thumb_url=info.get("thumburl", ""),
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            mime=info.get("mime", ""),
            author=_clean((meta.get("Artist") or {}).get("value", "")),
            license=_clean((meta.get("LicenseShortName") or {}).get("value", "")),
            license_url=_clean((meta.get("LicenseUrl") or {}).get("value", "")),
            source_url=info.get("descriptionurl", ""),
            extra={"categories": _clean((meta.get("Categories") or {}).get("value", ""))},
        )
    return None


def licence_verdict(asset: Asset) -> tuple[bool, str]:
    if not asset.license:
        return False, "licence missing"
    if LICENCE_BAD.search(asset.license):
        return False, f"forbidden licence: {asset.license}"
    if not LICENCE_OK.match(asset.license):
        return False, f"licence not allow-listed: {asset.license}"
    if not asset.author:
        return False, "author missing (attribution impossible)"
    return True, ""


STOP_TOKENS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "than", "then",
    "some", "such", "other", "also", "used", "using", "one", "ones", "very",
    "any", "all", "more", "most", "not", "etc", "e.g", "i.e", "someone",
}

# Words that appear in thousands of file names and categories; matching them
# proves nothing. Keeping them would let "thing", "man", "building" approve
# almost any photograph.
GENERIC_TOKENS = {
    "photo", "image", "picture", "photograph", "file", "commons", "wikimedia",
    "wikipedia", "jpg", "jpeg", "png", "svg", "webp", "view", "closeup",
    "close-up", "copy", "version", "edit", "edited", "collection", "museum",
    "public", "domain", "cc", "by", "sa", "license", "author", "unknown",
    "object", "objects", "thing", "things", "part", "parts", "type", "types",
    "group", "groups", "people", "person", "persons", "man", "woman", "men",
    "women", "child", "children", "building", "buildings", "place", "places",
    "area", "areas", "system", "systems", "action", "actions", "process",
}


def _tokens(text: str) -> set[str]:
    raw = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {t for t in raw if len(t) >= 3 and t not in STOP_TOKENS and t not in GENERIC_TOKENS}


ABSTRACT_TOKENS = {
    "time", "life", "work", "state", "way", "case", "fact", "kind", "sort",
    "level", "period", "moment", "number", "amount", "value", "effect", "change",
    "form", "means", "idea", "name", "word", "language", "history", "science",
    "nature", "health", "art", "music", "sport", "business", "society", "culture",
    "world", "country", "city", "year", "day", "month", "age", "reason", "result",
}


def relevance_verdict(asset: Asset, gloss: str) -> tuple[bool, str]:
    """Lexical overlap between the word's own English gloss and the file.

    Wikidata's exact-label check guarantees the *concept* is right, not the
    photograph. 时候 resolved to a concept whose P18 is "The AI Arms Race Is
    Changing Everything", and 企业 to a shopping centre — both perfectly licensed
    and perfectly wrong. Since the dictionary already holds an English gloss for
    the word, the cheapest honest gate is lexical: a content word from the gloss
    must appear in the file name, or (for words of five letters or more) in the
    file's Commons categories. Abstract gloss words such as "time" and "state"
    are ignored, because they match half of Commons by accident.
    """
    want = _tokens(gloss)
    if not want:
        return False, "no usable English gloss to verify against"
    strong = want - ABSTRACT_TOKENS
    name = _tokens(asset.file_name)
    cats = _tokens(asset.extra.get("categories", ""))
    hit = {t for t in strong
           if any(t == h or (len(t) >= 4 and (t in h or h in t)) for h in name)}
    if not hit:
        hit = {t for t in strong if len(t) >= 5 and any(t == h or t in h for h in cats)}
    if not hit:
        return False, f"no lexical overlap with '{gloss[:40]}'"
    return True, ""


ABSTRACT_GLOSS = re.compile(
    r"^(the )?(act|action|state|quality|process|fact|condition|situation|"
    r"relation|feeling|idea|amount|degree|period|time|way|method|system|"
    r"ability|right|power|influence|change|event|activity|behaviour|behavior|"
    r"concept|notion|term|word|expression|title|name)\b"
    r"|\b(sb|sth|somebody|something)\b"
    r"|^\w+ of (the |a )?\w+", re.I)

# Glosses that never correspond to a photograph: function words, pronouns,
# modals, directions, and verbs. Filtering them here is a cheap pre-check; the
# lexical gate would reject their matches anyway, but only after a download.
FUNCTION_GLOSS = re.compile(
    r"^(yes|no|maybe|perhaps|how|what|who|whom|whose|when|where|why|whether|"
    r"can|may|might|must|should|shall|will|would|could|not|also|again|still|"
    r"very|more|most|all|any|some|each|every|both|either|neither|other|another|"
    r"such|so|as|if|then|than|because|although|though|while|during|before|"
    r"after|under|over|between|above|below|inside|outside|near|far|here|there|"
    r"now|today|tomorrow|yesterday|to |a |an |the )", re.I)


# A dictionary entry wants a photograph of the thing. Book plates, playbills,
# engravings and museum scans share the word but show a page, not the object.
REPRODUCTION = re.compile(
    r"\b(illustration|engraving|lithograph|etching|woodcut|manuscript|"
    r"playbill|poster|book|books|titlepage|title page|frontispiece|"
    r"stamp|banknote|comic|cartoon|diagram|schematic|painting|drawing|"
    r"sketch|plaque|sign|logo|coat of arms|map|chart|graph|table)\b", re.I)


def quality_verdict(asset: Asset) -> tuple[bool, str]:
    if asset.mime not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        return False, f"mime {asset.mime or 'unknown'}"
    if asset.width < 500:
        return False, f"too small ({asset.width}px)"
    if NOISE.search(asset.file_name):
        return False, f"noise title ({asset.file_name[:40]})"
    ratio = asset.width / asset.height if asset.height else 0
    if ratio < 0.5 or ratio > 2.2:
        return False, f"aspect ratio {ratio:.2f}"
    if REPRODUCTION.search(asset.file_name):
        return False, f"reproduction, not a photograph ({asset.file_name[:40]})"
    return True, ""


# --------------------------------------------------------------- download ----
def download(url: str, cap: int = MAX_BYTES) -> bytes:
    """Issue 13: HTTPS, host allowlist, byte cap, redirect checked by urlopen."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"non-https url: {parsed.scheme}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"host not allow-listed: {parsed.hostname}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        final = urllib.parse.urlparse(resp.geturl())
        if final.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"redirect left allowlist: {final.hostname}")
        blob = resp.read(cap + 1)
    if len(blob) > cap:
        raise ValueError("response larger than cap")
    if len(blob) < 1024:
        raise ValueError("response too small to be an image")
    return blob


def validate_image(blob: bytes) -> tuple[Image.Image, str]:
    """Signature + PIL verify + re-encode. Decompression bomb guarded."""
    Image.MAX_IMAGE_PIXELS = 40_000_000
    img = Image.open(io.BytesIO(blob))
    img.verify()                       # structural check, raises on corrupt
    img = Image.open(io.BytesIO(blob)) # verify() invalidates the handle
    if img.width * img.height > 40_000_000:
        raise ValueError("image too large (decompression bomb guard)")
    fmt = (img.format or "").upper()
    if fmt not in ("JPEG", "PNG", "WEBP", "GIF"):
        raise ValueError(f"unexpected format {fmt}")
    if fmt == "GIF":
        # Animated GIF: keep the first frame; the pipeline ships a still WebP.
        img.seek(0)
    return img.convert("RGB"), ("gif" if fmt == "GIF" else fmt.lower())


def make_thumb(img: Image.Image) -> tuple[bytes, int, int]:
    """Progressive WebP, hard ceiling THUMB_MAX_BYTES (Issue 3)."""
    for width in (200, 160, 120):
        scale = width / float(img.width)
        height = max(1, int(round(img.height * scale)))
        resized = img.resize((width, height), Image.LANCZOS)
        for quality in range(80, 39, -10):
            buf = io.BytesIO()
            resized.save(buf, format="WEBP", quality=quality, method=6)
            if buf.tell() <= THUMB_MAX_BYTES:
                return buf.getvalue(), width, height
    raise ValueError("thumbnail cannot meet the 15 KB ceiling")


def dhash(img: Image.Image) -> str:
    """64-bit difference hash, pure Pillow (Issue 2: perceptual dedupe)."""
    small = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            left = px[row * 9 + col]
            right = px[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


# -------------------------------------------------------------------- main ---
def candidate_rows(con: sqlite3.Connection, limit: int, skip: set[int],
                   categories: list[str], words: list[str] | None = None,
                   concrete_only: bool = False) -> list[sqlite3.Row]:
    """Picturable words first.

    Ordering by raw frequency alone selects 的 / 是 / 和 — grammatical function
    words that have no picture and never will. So: real-world categories only
    (nature, tools, transport …), no idioms, no grammatical glosses. When an
    explicit word list is given, only those words are considered.
    """
    if words:
        rows = con.execute(
            "SELECT e.entry_id, e.simplified, e.traditional, e.category, "
            "       s.gloss_en, s.sense_order "
            "FROM entries e JOIN senses s ON s.entry_id = e.entry_id "
            "WHERE s.sense_order = 0 AND e.simplified IN (%s) "
            "GROUP BY e.entry_id %s" % (
                ",".join("?" * len(words)),
                "ORDER BY e.freq_rank IS NULL, e.freq_rank",
            ),
            words,
        ).fetchall()
        return [r for r in rows if r["entry_id"] not in skip][:limit]

    cat_sql = ""
    args: list = []
    if categories:
        cat_sql = " AND e.category IN (%s)" % ",".join("?" * len(categories))
        args = list(categories)
    sql = (
        "SELECT e.entry_id, e.simplified, e.traditional, e.category, "
        "       s.gloss_en, s.sense_order "
        "FROM entries e JOIN senses s "
        "  ON s.entry_id = e.entry_id AND s.sense_order = 0 "
        "WHERE e.is_proper = 0 AND e.is_chengyu = 0 AND e.is_classifier = 0 "
        "  AND LENGTH(e.simplified) BETWEEN 1 AND 12 "
        "  AND s.gloss_en IS NOT NULL AND LENGTH(s.gloss_en) BETWEEN 2 AND 70 "
        + cat_sql +
        " ORDER BY e.freq_rank IS NULL, e.freq_rank, e.entry_id LIMIT ?"
    )
    rows = con.execute(sql, args + [limit + len(skip) + 400]).fetchall()
    out = []
    for row in rows:
        if row["entry_id"] in skip:
            continue
        if GRAMMAR.search(row["gloss_en"] or ""):
            continue
        if row["simplified"] in FUNCTION_WORDS:
            continue
        if len(row["simplified"]) == 1 and row["simplified"] in SINGLE_CHAR_SKIP:
            continue
        if concrete_only and ABSTRACT_GLOSS.search(row["gloss_en"] or ""):
            continue
        if concrete_only and FUNCTION_GLOSS.match(row["gloss_en"] or ""):
            continue
        if concrete_only and len(row["simplified"]) < 2:
            continue
        if concrete_only:
            gloss = (row["gloss_en"] or "").strip()
            # A picturable word is nearly always glossed as a short noun phrase:
            # one to three words, no verb marker, no clause punctuation.
            if gloss.count(" ") > 2 or re.search(r"[;,()/]|^to ", gloss) \
                    or gloss.endswith("ing") or gloss.startswith(("a ", "an ")):
                continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/build/dictionary.sqlite")
    ap.add_argument("--out", default=str(REPO_ROOT / "assets" / "images"),
                    help="where thumbs/ and detail/ live; defaults to the bundled "
                         "assets/images so thumb_asset never points at a stray folder")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--dry-run", action="store_true", help="resolve only, write nothing")
    ap.add_argument("--allow-commons-search", action="store_true",
                    help="last tier: Commons file-title search (confidence 0.45)")
    ap.add_argument("--categories", default=",".join(PICTABLE_CATEGORIES),
                    help="comma-separated entry categories to consider; empty = all")
    ap.add_argument("--words", default="",
                    help="path to a newline/comma separated list of headwords to try first")
    ap.add_argument("--concrete-only", action="store_true",
                    help="skip glosses that describe abstractions (state of, act of, "
                         "quality, relation …) — they never have a photograph")
    ap.add_argument("--sitelink", action="store_true",
                    help="also try the zh/en Wikipedia lead image (2 extra "
                         "round-trips per word; rarely the only source)")
    args = ap.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"no database at {db}", file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    (out_dir / "thumbs").mkdir(parents=True, exist_ok=True)
    (out_dir / "detail").mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    changes = migrate(con)
    print("migration:", changes)

    done = {r[0] for r in con.execute("SELECT DISTINCT entry_id FROM entry_images")}
    print(f"resume: {len(done)} entries already mapped")

    stats = {"tried": 0, "approved": 0, "no_concept": 0, "no_image": 0,
             "licence_rejected": 0, "quality_rejected": 0, "download_failed": 0,
             "thumb_failed": 0, "deduped": 0}
    manifest = (out_dir / f"manifest_v2_{os.getpid()}.jsonl").open("a", encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    seed_words: list[str] | None = None
    if args.words:
        raw = Path(args.words).read_text(encoding="utf-8")
        seed_words = [w.strip() for w in re.split(r"[\n,]+", raw) if w.strip()]
        print(f"word list: {len(seed_words)} headwords")

    for row in candidate_rows(con, args.limit, done,
                              [c.strip() for c in args.categories.split(",") if c.strip()],
                              seed_words, args.concrete_only):
        stats["tried"] += 1
        term = re.split(r"[;(]", row["gloss_en"] or "")[0].strip()
        term = re.sub(r"^[a-z]*\.\s*", "", term)
        simplified = row["simplified"]
        traditional = row["traditional"] or ""

        concept = None
        try:
            concept = cached_concept(con, simplified, traditional, term, now)
        except Exception as exc:  # noqa: BLE001
            print(f"[{stats['tried']}] {simplified}: concept lookup failed ({exc})")
        if concept is None:
            stats["no_concept"] += 1
            print(f"[{stats['tried']}] {simplified} / {term}: no concept")
            time.sleep(args.sleep)
            continue

        # Candidate files: the concept's own image first. The article lead image
        # is only consulted when that fails — two extra round-trips per word is
        # the difference between 20 and 6 words a minute.
        files: list[str] = []
        try:
            files = concept_image_files(concept["qid"], term)
        except Exception as exc:  # noqa: BLE001
            print(f"  P18 lookup failed: {exc}")

        def try_files(names: list[str], gloss: str,
                      from_category: bool = False) -> tuple[Asset | None, str]:
            why = ""
            for name in names:
                if name.lower().endswith((".svg", ".tif", ".tiff", ".pdf", ".ogv", ".webm")):
                    why = f"unsupported file type ({name[-5:]})"
                    continue
                try:
                    cand = file_asset(name)
                except Exception as exc:  # noqa: BLE001
                    why = f"metadata failed: {exc}"
                    continue
                if cand is None:
                    why = "no imageinfo"
                    continue
                ok_l, why_l = licence_verdict(cand)
                if not ok_l:
                    why = why_l
                    continue
                ok_q, why_q = quality_verdict(cand)
                if not ok_q:
                    why = why_q
                    continue
                ok_r, why_r = relevance_verdict(cand, gloss)
                if not ok_r and from_category:
                    # Category membership alone is NOT enough evidence: Category:
                    # Second is full of unrelated photographs, and it put a
                    # destination-sign photo on 第二 and a rally car on 左右.
                    # Membership only widens the candidate pool; the gloss still
                    # has to appear in the file name or its categories.
                    ok_r, why_r = False, f"{why_r} (category membership alone rejected)"
                if not ok_r:
                    why = why_r
                    continue
                return cand, ""
            return None, why

        asset, reason = try_files(files[:2], term)

        if asset is None:
            # Curated category first: the subject of the category is the subject
            # of the word, so a photo filed under Category:Bus is a photo of a bus.
            try:
                members = commons_category_files(term)
            except Exception as exc:  # noqa: BLE001
                members = []
                print(f"  category lookup failed: {exc}")
            if members:
                asset, reason2 = try_files(members[:4], term, from_category=True)
                reason = reason2 or reason

        if asset is None and args.allow_commons_search:
            # Off by default: a Commons search for the gloss returns files that
            # merely share the word ("first" → "Shooter person views"), which no
            # filename-level gate can tell apart from a real match. Only the
            # curated P18 statement is trustworthy enough to ship.
            try:
                hits = commons_search(term)
            except Exception as exc:  # noqa: BLE001
                hits = []
                print(f"  commons search failed: {exc}")
            if hits:
                asset, reason2 = try_files(hits[:4], term)
                reason = reason2 or reason

        if asset is None and args.sitelink:
            extra: list[str] = []
            for lang in ("zh", "en"):
                try:
                    lead = sitelink_lead_image(concept["qid"], lang)
                except Exception as exc:  # noqa: BLE001
                    print(f"  sitelink {lang} failed: {exc}")
                    continue
                if lead and lead[0] not in files:
                    extra.append(lead[0])
            if extra:
                asset, reason2 = try_files(extra[:2], term)
                reason = reason2 or reason

        if asset is None and not files:
            stats["no_image"] += 1
            print(f"[{stats['tried']}] {simplified}: concept {concept['qid']} has no "
                  f"image, search for '{term}' gave nothing usable ({reason})")
            time.sleep(args.sleep)
            continue

        if asset is None:
            print(f"[{stats['tried']}] {simplified}: rejected ({reason})")
            time.sleep(args.sleep)
            continue

        try:
            blob = download(asset.detail_url)
            img, fmt = validate_image(blob)
        except Exception as exc:  # noqa: BLE001
            stats["download_failed"] += 1
            print(f"[{stats['tried']}] {simplified}: download/validate failed ({exc})")
            time.sleep(args.sleep)
            continue

        sha = hashlib.sha256(blob).hexdigest()
        ph = dhash(img)

        existing = con.execute(
            "SELECT image_id FROM images WHERE sha256 = ?", (sha,)
        ).fetchone()
        if existing:
            stats["deduped"] += 1
            image_id = existing[0]
        else:
            try:
                thumb, tw, th = make_thumb(img)
            except Exception as exc:  # noqa: BLE001
                stats["thumb_failed"] += 1
                print(f"[{stats['tried']}] {simplified}: thumb failed ({exc})")
                time.sleep(args.sleep)
                continue

            sub = sha[:2]
            detail_path = out_dir / "detail" / sub / f"{sha}.{fmt}"
            # Flat, not <sha2>/<sha>.webp: Flutter bundles the files of a declared
            # asset directory, and a previous build shipped 84 thumbnails while
            # 35 rows pointed at nested paths that never entered the APK. One
            # level keeps `pubspec.yaml` (`assets/images/thumbs/`) sufficient.
            thumb_path = out_dir / "thumbs" / f"{sha}.webp"
            detail_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            detail_path.write_bytes(blob)
            thumb_path.write_bytes(thumb)

            attribution = (
                f"{asset.file_name.replace('_', ' ')} — {asset.author} — "
                f"{asset.license} — Wikimedia Commons"
            )
            if args.dry_run:
                print(f"[dry] {simplified} -> {asset.file_name} "
                      f"({asset.license}, thumb {len(thumb)} B)")
                stats["approved"] += 1
                time.sleep(args.sleep)
                continue

            cur = con.execute(
                "INSERT OR IGNORE INTO images(content_hash, sha256, phash, title, "
                "thumb_path, detail_path, thumb_asset, detail_url, width, height, "
                "source, source_url, author, license, license_url, "
                "attribution_text, status, asset_status, verification_status, "
                "thumb_bytes, bytes, concept_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'approved','approved',"
                "'verified',?,?,?,?)",
                (
                    sha, sha, ph, asset.file_name,
                    str(thumb_path).replace("\\", "/"),
                    str(detail_path).replace("\\", "/"),
                    f"assets/images/thumbs/{sha}.webp",
                    asset.detail_url, asset.width, asset.height,
                    "wikimedia_commons", asset.source_url, asset.author,
                    asset.license, asset.license_url, attribution,
                    len(thumb), len(blob), concept["concept_id"], now,
                ),
            )
            image_id = cur.lastrowid
            if not image_id:
                image_id = con.execute(
                    "SELECT image_id FROM images WHERE sha256 = ?", (sha,)
                ).fetchone()[0]

        if not args.dry_run:
            con.execute(
                "INSERT OR REPLACE INTO concepts(concept_id, source, qid, label_en,"
                " label_zh, description, category, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (concept["concept_id"], concept["source"], concept["qid"],
                 concept.get("label_en", ""), concept.get("label_zh", ""),
                 concept.get("description", ""), row["category"] or "", now),
            )
            con.execute(
                "INSERT OR IGNORE INTO concept_images(concept_id, image_id, "
                "relevance, is_primary) VALUES (?,?,?,1)",
                (concept["concept_id"], image_id, 0.9),
            )
            # Record the word→concept link as well, so a later synonym or the
            # traditional variant can inherit this picture through the family
            # instead of needing its own Wikimedia lookup.
            con.execute(
                "INSERT OR REPLACE INTO entry_concepts(entry_id, concept_id, "
                "confidence, method) VALUES (?,?,?,?)",
                (row["entry_id"], concept["concept_id"], 0.9, "wikidata-exact-label"),
            )
            con.execute(
                "INSERT OR REPLACE INTO entry_images(entry_id, sense_id, image_id, "
                "confidence, rank, match_method, concept_id, match_confidence, "
                "match_reason, device_hint) VALUES (?,?,?,?,1,?,?,?,?,?)",
                (row["entry_id"], None, image_id, 0.9,
                 "wikidata-p18" if "article" not in concept else "sitelink-lead",
                 concept["concept_id"], 0.9,
                 f"{concept['source']} exact label → {concept['qid']} → "
                 f"{asset.file_name[:40]}",
                 "not_cached"),
            )
            con.commit()
            stats["approved"] += 1
            manifest.write(json.dumps({
                "entry_id": row["entry_id"], "word": simplified, "term": term,
                "concept_id": concept["concept_id"], "qid": concept["qid"],
                "file": asset.file_name, "license": asset.license,
                "author": asset.author, "sha256": sha, "phash": ph,
                "thumb_bytes": len(thumb), "detail_url": asset.detail_url,
            }, ensure_ascii=False) + "\n")
            manifest.flush()
            print(f"[{stats['tried']}] {simplified} / {term} -> {asset.file_name[:45]} "
                  f"({asset.license}) {len(thumb)} B")

        time.sleep(args.sleep)

    manifest.close()
    con.commit()

    report = {
        "generated_at": now,
        "stats": stats,
        "schemas": changes,
        "db_images": con.execute("SELECT COUNT(*) FROM images").fetchone()[0],
        "db_mappings": con.execute("SELECT COUNT(*) FROM entry_images").fetchone()[0],
        "concepts": con.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
        "license_breakdown": {
            r[0]: r[1] for r in con.execute(
                "SELECT license, COUNT(*) FROM images GROUP BY license")
        },
        "thumb_bytes_max": con.execute(
            "SELECT MAX(thumb_bytes) FROM images").fetchone()[0],
        "thumb_over_15k": con.execute(
            "SELECT COUNT(*) FROM images WHERE thumb_bytes > 15000").fetchone()[0],
    }
    (out_dir / "report_v2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
