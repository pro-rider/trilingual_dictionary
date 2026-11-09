"""Image index builder — concept-anchored, licence-gated, thumbnails <=15 KB.

Design decisions, and what each one buys:

  1. Identity is the **concept**, not the spelling. A Chinese headword is looked
     up as an exact Chinese Wikipedia article title; the article's Wikidata item
     is the concept (`concepts`), and its lead image / P18 is the picture. So
     "苹果" resolves to the fruit article, never to the Apple Inc. logo, because
     "苹果公司" is a different title. Title matching alone never approves an
     image: the licence gate and the quality gate still decide.
  2. One asset serves many words. Files are keyed by sha256 of the bytes; a
     second word answering to the same concept reuses `image_id` and only adds a
     `concept_images` / `entry_images` row.
  3. Thumbnails are re-encoded locally and **measured**. WebP, progressive
     quality 82→38, width 320→160; if it cannot be brought under 15,000 bytes
     the asset is rejected rather than shipped oversized.
  4. Downloads pass through `safe_get`: HTTPS only, host allow-list, byte cap,
     Pillow decode. An HTML page saved as .jpg never reaches the DB.
  5. Asset state (`asset_status`) is separate from the device cache. The phone
     derives "cached" from the file existing, never from a column it trusts.

Batching: 40 words per round costs 2–3 Wikipedia/Wikidata calls (title →
wikibase_item + lead image, then one batched Commons imageinfo), plus one
download per accepted word. That is what keeps 5,000 words to hours instead of
days — the naive per-word search tripped Wikidata's 429 wall at ~9 s/word.

Outputs
-------
  assets/images/thumbs/<sha16>.webp   bundled into the APK (pubspec lists it)
  data/images/full/<sha16>.<ext>      high-res original, server side only
  data/images/report_v2.json          per-run statistics
  data/images/manifest_v2.jsonl       one line per accepted asset

Usage
-----
  python tools/build_image_index.py --limit 40 --dry-run
  python tools/build_image_index.py --limit 1000 --sleep 0.4
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "build" / "dictionary.sqlite"
THUMB_DIR = ROOT.parent / "assets" / "images" / "thumbs"
FULL_DIR = ROOT / "data" / "images" / "full"
UA = (
    "TrilingualDictionary/0.3 (dictionary image index; lexicography project) "
    "python-urllib"
)

ZH_WIKI_API = "https://zh.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_HOSTS = (
    "commons.wikimedia.org",
    "upload.wikimedia.org",
    "thumb.wikimedia.org",
    "www.wikidata.org",
    "zh.wikipedia.org",
)
MAX_BYTES = 20 * 1024 * 1024
THUMB_MAX_BYTES = 15_000
THUMB_TARGET_WIDTH = 320
BATCH = 40

ALLOWED_LICENCE = re.compile(r"^(cc0|cc by(-sa)?|public domain|pd)\b", re.IGNORECASE)
FORBIDDEN_LICENCE = re.compile(r"\b(nc|nd|noncommercial|no.?deriv)\b", re.IGNORECASE)

# A file whose name says it is a diagram/logo/map is not a picture of the word.
NOISE_FILE = re.compile(
    r"(logo|icon|diagram|chart|schema|scheme|map|plot|graph|plan|sign|flag|"
    r"coat[_ ]of[_ ]arms|seal|screenshot|table|formula|equation|symbol|"
    r"clipart|drawing|sketch|cartoon|poster|cover|stamp|coin)",
    re.IGNORECASE,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS concepts (
  concept_id TEXT PRIMARY KEY,
  label_zh TEXT,
  label_en TEXT,
  description TEXT,
  category TEXT,
  source TEXT NOT NULL DEFAULT 'wikidata'
);
CREATE TABLE IF NOT EXISTS concept_images (
  concept_id TEXT NOT NULL,
  image_id INTEGER NOT NULL,
  relevance REAL NOT NULL DEFAULT 0,
  is_primary INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (concept_id, image_id)
);
CREATE TABLE IF NOT EXISTS entry_concepts (
  entry_id INTEGER NOT NULL,
  concept_id TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  method TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (entry_id, concept_id)
);
CREATE INDEX IF NOT EXISTS idx_entry_concepts_entry ON entry_concepts(entry_id);
"""

IMAGE_COLUMNS = (
    ("thumb_asset", "TEXT"),
    ("detail_url", "TEXT"),
    ("asset_status", "TEXT DEFAULT 'approved'"),
    ("phash", "TEXT"),
    ("thumb_bytes", "INTEGER"),
    ("license_status", "TEXT DEFAULT 'verified'"),
)

# A photograph cannot illustrate a grammatical particle. These headwords are
# skipped before any network call: 吧 resolved to the Ukrainian city Bar,
# 其 to the French commune His — both "correct" label matches, both useless.
FUNCTION_WORDS = set("""
的 是 在 了 和 有 不 人 你 我 他 她 它 咱 您 谁 何 哪 怎 什 么 为 这 那 吧 其 该 只
就 都 而 及 与 或 也 很 再 又 还 被 把 给 让 从 向 对 于 吗 呢 啊 着 过 地 得 之 以
所 但 却 等 些 个 去 来 上 下 里 中 大 小 多 少 好 会 能 可 要 想 说 做 看 用 使 若
如 因 由 自 已 未 没 无 非 最 更 才 刚 常 每 各 某 全 半 一 二 三 四 五 六 七 八 九
十 百 千 万 亿 零 两 吗 嘛 哦 呀 嗯 呃 哎 喂 于 乎 者 所 乃 则 且 并 若 虽 然 故 且
便 到 家 处理 官方 成功 进行 表示 开始 应该 可能 需要 已经 现在 今天 昨天 明天 时候
东西 事情 问题 情况 方式 方法 部分 方面 过程 结果 原因 影响 作用 意义 价值 关系 内容
""".split())

# Pronoun/adverb glosses that name no kind of thing.
GLOSS_STOP = set("""
his her its their our your my the a an to be is are was were am been being of in
on at for with and or but not no very more most much many some any all each every
this that these those he she it they we you i me him them us who whom whose which
what when where why how if then than so as by from into over under again also just
can could may might must shall should will would do does did done have has had
""".split())

# Words whose meaning is concrete enough that a photograph can carry it.
# `general` must be here: it is the dictionary's largest bucket (74,664 rows) and
# contains ordinary concrete words (玩具/声音/书/医院/狗). Leaving it out meant
# the bulk runs never even considered them — the two screenshots in the report
# (toy, sound) were both `general`.
# `business` is deliberately excluded: 国家/公司/时间/企业/研究/成功 all resolved
# to encyclopedia topics whose lead image illustrates the *topic*, not the word.
IMAGE_CATEGORIES = (
    "general", "nature", "everyday", "transport", "technology",
    "tools_instruments", "science_medicine", "geography_environment",
)

# First-meaning English words that promise nothing photographable. Frequency
# lists are dominated by them (一个 "one", 他们 "they", 可以 "can"), and every
# one of them cost a Commons lookup that could only fail.
ABSTRACTS = frozenset("""
one two three they them their he she it its we you i this that these those
what which who whom whose where when why how
be is are was were been being have has had do does did
can could may might must shall should will would
not no yes so if then than as at in on of for with from by to into onto
and or but nor also too very more most less least such same other another
self oneself something anything nothing someone anyone everyone
""".split())


# --------------------------------------------------------------------- network


def _request(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(base: str, params: dict, retries: int = 5) -> dict:
    delay = 3.0
    last: Exception | None = None
    for _ in range(retries):
        url = base + "?" + urllib.parse.urlencode(params)
        try:
            return json.loads(_request(url).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504):
                retry_after = exc.headers.get("Retry-After") or ""
                wait = float(retry_after) if retry_after.isdigit() else delay
                print(f"      HTTP {exc.code}, backoff {wait:.0f}s")
                time.sleep(wait)
                delay = min(delay * 2, 90)
                continue
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(delay)
            delay = min(delay * 2, 90)
    raise last if last else RuntimeError("request failed")


def safe_get(url: str, timeout: int = 60) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"not https: {url[:60]}")
    host = (parsed.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise ValueError(f"host not allowed: {host}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        declared = int(resp.headers.get("Content-Length") or 0)
        if declared > MAX_BYTES:
            raise ValueError(f"declares {declared} bytes (> cap)")
        blob = resp.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError("body exceeded cap")
    if len(blob) < 500:
        raise ValueError(f"body too small ({len(blob)} B)")
    Image.open(io.BytesIO(blob)).verify()
    return blob


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


# ------------------------------------------------------------------ batching


def titles_info(pairs: list[tuple[str, str]]) -> dict[str, dict]:
    """Exact-or-redirect zh.wikipedia titles -> {qid, lead image} in one call.

    The Chinese Wikipedia uses traditional/formal titles (飞机 → 飛機,
    书 → 图书, 狗 → 犬). A redirect is therefore accepted only when the article
    it lands on is titled with the headword itself or its traditional form —
    otherwise 计划 → 项目 would smuggle in a PRINCE2 diagram, which is a
    confident-looking picture of the wrong concept.
    """
    words = [w for w, _t in pairs]
    params = {
        "action": "query",
        "format": "json",
        "titles": "|".join(words),
        "redirects": "1",
        "prop": "pageprops|pageimages",
        "ppprop": "wikibase_item",
        "piprop": "name",
    }
    data = get_json(ZH_WIKI_API, params)
    query = data.get("query") or {}
    normalized = {n.get("from", ""): n.get("to", "") for n in query.get("normalized") or []}
    redirect = {r.get("from", ""): r.get("to", "") for r in query.get("redirects") or []}
    trad = {w: (t or w) for w, t in pairs}

    by_title: dict[str, dict] = {}
    for page in (query.get("pages") or {}).values():
        if page.get("missing") is not None:
            continue
        title = page.get("title", "")
        qid = (page.get("pageprops") or {}).get("wikibase_item", "")
        if not qid:
            continue
        by_title[title] = {"qid": qid, "file": page.get("pageimage", "") or "",
                           "title": title, "method": "zh-title", "conf": 0.9}

    out: dict[str, dict] = {}
    for word in words:
        resolved = normalized.get(word, word)
        resolved = redirect.get(resolved, resolved)
        if resolved != word and resolved != trad.get(word):
            continue
        info = by_title.get(resolved)
        if info:
            out[word] = info
    return out


def search_exact_label(words: list[str], sleep: float) -> dict[str, dict]:
    """Per-word Wikidata search, exact label required. Slow path for misses."""
    out: dict[str, dict] = {}
    for word in words:
        try:
            data = get_json(
                WIKIDATA_API,
                {
                    "action": "wbsearchentities", "search": word, "language": "zh",
                    "uselang": "zh", "format": "json", "limit": "5", "type": "item",
                },
            )
        except Exception:  # noqa: BLE001
            time.sleep(sleep)
            continue
        for hit in data.get("search") or []:
            if (hit.get("label") or "").strip() == word:
                out[word] = {"qid": hit["id"], "file": "", "title": word,
                             "method": "zh-label", "conf": 0.85}
                break
        time.sleep(sleep)
    return out


def search_gloss_label(gloss: str, sleep: float) -> dict | None:
    """English gloss -> Wikidata item whose *English label* is exactly the gloss.

    The CC-CEDICT gloss is the accurate sense ("train", "cell phone"), and
    English labels separate concepts that Chinese search merges: 火车 searched
    in Chinese returns 铁路车站 (a station) before 铁路列车 (a train), while
    gloss "train" returns the vehicle. Confidence is lower than an exact
    Chinese title, and the method is recorded so a reviewer can see it.
    """
    term = re.split(r"[;,()]", gloss or "")[0].strip().lower()
    term = re.sub(r"^to\s+", "", term).strip()
    if not term or len(term) < 3 or len(term) > 24 or term in GLOSS_STOP:
        return None
    try:
        data = get_json(
            WIKIDATA_API,
            {
                "action": "wbsearchentities", "search": term, "language": "en",
                "uselang": "en", "format": "json", "limit": "5", "type": "item",
            },
        )
    except Exception:  # noqa: BLE001
        time.sleep(sleep)
        return None
    finally:
        time.sleep(sleep)
    for hit in data.get("search") or []:
        label = (hit.get("label") or "").strip()
        desc = (hit.get("description") or "").lower()
        # Case-sensitive: Wikidata capitalises proper nouns, so "See" (a German
        # lake) must not answer the gloss "see", and "His" (a French commune)
        # must not answer "his". Lower-casing the comparison silently accepted
        # both, which is how 见 got a photograph of a lake.
        if label != term:
            continue
        if re.search(r"film|surname|given name|band|album|song|website", desc):
            continue
        return {"qid": hit["id"], "file": "", "title": term}
    return None


def p18_for_qids(qids: list[str]) -> dict[str, str]:
    """P18 filename per QID, batched (50 ids per call)."""
    out: dict[str, str] = {}
    for start in range(0, len(qids), 50):
        chunk = qids[start:start + 50]
        data = get_json(
            WIKIDATA_API,
            {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "format": "json",
                "props": "claims",
            },
        )
        for qid, entity in (data.get("entities") or {}).items():
            for claim in ((entity.get("claims") or {}).get("P18") or []):
                value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
                if isinstance(value, str) and value.strip():
                    out[qid] = value.strip()
                    break
    return out


def commons_batch(files: list[str]) -> dict[str, dict]:
    """Imageinfo per file name, 50 titles per call."""
    out: dict[str, dict] = {}
    for start in range(0, len(files), 50):
        chunk = files[start:start + 50]
        data = get_json(
            COMMONS_API,
            {
                "action": "query",
                "format": "json",
                "titles": "|".join(f"File:{f}" for f in chunk),
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": "1280",
            },
        )
        pages = (data.get("query") or {}).get("pages") or {}
        norm = {
            (n.get("to") or ""): (n.get("from") or "")
            for n in (data.get("query") or {}).get("normalized") or []
        }
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            if not info.get("url"):
                continue
            title = page.get("title", "")
            name = norm.get(title, title).removeprefix("File:")
            out[name] = info
    return out


# ------------------------------------------------------------ gates and image


def licence_ok(license_name: str, author: str) -> tuple[bool, str]:
    if not license_name:
        return False, "licence missing"
    if FORBIDDEN_LICENCE.search(license_name):
        return False, f"forbidden licence: {license_name}"
    if not ALLOWED_LICENCE.match(license_name):
        return False, f"licence not in allow-list: {license_name}"
    if not author:
        return False, "author missing"
    return True, ""


def quality_ok(width: int, height: int, mime: str) -> tuple[bool, str]:
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        return False, f"mime {mime}"
    if not width or not height:
        return False, "no dimensions"
    if width < 400:
        return False, f"too small ({width}px)"
    ratio = width / height
    if ratio < 0.4 or ratio > 2.5:
        return False, f"aspect ratio {ratio:.2f}"
    return True, ""


def dhash(image: Image.Image) -> str:
    small = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    bits = 0
    idx = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            if px[base + col] < px[base + col + 1]:
                bits |= 1 << idx
            idx += 1
    return f"{bits:016x}"


def make_thumb(image: Image.Image) -> tuple[bytes, int, int] | None:
    rgb = image.convert("RGB")
    for width in (THUMB_TARGET_WIDTH, 256, 200, 160):
        if rgb.width > width:
            height = max(1, round(rgb.height * width / rgb.width))
            candidate = rgb.resize((width, height), Image.Resampling.LANCZOS)
        else:
            candidate = rgb
        for quality in (82, 72, 62, 52, 45, 38):
            buf = io.BytesIO()
            candidate.save(buf, format="WEBP", quality=quality, method=6)
            if buf.tell() <= THUMB_MAX_BYTES:
                return buf.getvalue(), candidate.width, candidate.height
    return None


# ------------------------------------------------------------------------- db


def migrate(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_SQL)
    existing = {r[1] for r in con.execute("PRAGMA table_info(images)")}
    for name, decl in IMAGE_COLUMNS:
        if name not in existing:
            con.execute(f"ALTER TABLE images ADD COLUMN {name} {decl}")
            print(f"  + images.{name} {decl}")
    entry_cols = {r[1] for r in con.execute("PRAGMA table_info(entry_images)")}
    if "match_confidence" not in entry_cols:
        con.execute("ALTER TABLE entry_images ADD COLUMN match_confidence REAL")
        print("  + entry_images.match_confidence REAL")
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version','v005')")
    con.commit()


def select_words(con: sqlite3.Connection, limit: int, skip: set[str]) -> list[sqlite3.Row]:
    """High-frequency words that can actually carry a photograph.

    Ordering by frequency alone once produced 12 candidates and 0 accepted
    images: 一个 / 他们 / 没有 / 可以 rise to the top of any frequency list and
    none of them has a picture to fetch. A verb ("to play") or an abstract noun
    ("success") is the same dead end, so both are dropped before any network
    call — the pipeline is for nouns you can see.
    """
    placeholders = ",".join("?" for _ in IMAGE_CATEGORIES)
    rows = con.execute(
        f"SELECT e.entry_id, e.simplified, e.traditional, e.category, e.freq_rank, "
        f" (SELECT s.gloss_en FROM senses s WHERE s.entry_id = e.entry_id "
        f"  ORDER BY s.sense_order LIMIT 1) AS gloss_en "
        f"FROM entries e WHERE e.freq_rank IS NOT NULL "
        f"  AND e.category IN ({placeholders}) "
        f"  AND LENGTH(e.simplified) BETWEEN 1 AND 3 "
        f"ORDER BY e.freq_rank ASC, e.entry_id ASC",
        IMAGE_CATEGORIES,
    ).fetchall()
    out: list[sqlite3.Row] = []
    seen: set[str] = set()
    for row in rows:
        word = row["simplified"]
        gloss = (row["gloss_en"] or "").strip()
        if word in seen or word in skip or word in FUNCTION_WORDS:
            continue
        if not gloss:
            continue
        low = gloss.lower()
        # Verbs, adverbs, and grammatical labels never have a word-picture.
        if low.startswith(("to ", "(coll", "(of", "(final", "(measure", "a ", "an ")):
            continue
        if low.startswith("(") and ")" in low[:14]:
            continue
        # An entry whose *first* meaning is a function word has no picture to
        # fetch: 一个 "one", 他们 "they", 可以 "can", 不是 "no; not".
        head = low.split(";")[0].strip(" ,.")
        if head in ABSTRACTS or low in ABSTRACTS:
            continue
        seen.add(word)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def prune_missing(con: sqlite3.Connection) -> int:
    """Mark an approved asset as 'missing' when its bundled file is gone.

    The app trusts `asset_status`, so a row pointing at a thumbnail that is not
    in the APK would render as a broken box. Deriving the state from the file
    system keeps the two in step (Issue 7 / Issue 11).
    """
    pruned = 0
    for image_id, rel in con.execute(
        "SELECT image_id, thumb_asset FROM images WHERE thumb_asset IS NOT NULL"
    ).fetchall():
        path = ROOT.parent / rel
        if not path.exists():
            con.execute(
                "UPDATE images SET asset_status='missing' WHERE image_id=?", (image_id,)
            )
            pruned += 1
    if pruned:
        con.commit()
        print(f"  pruned {pruned} rows whose thumbnail is not on disk")
    return pruned


def purge_bad(con: sqlite3.Connection) -> int:
    """Remove mappings the current rules forbid. Assets stay on disk: another
    word may still point at them.

    Only two conditions disqualify a mapping: the headword is a particle, or its
    category is `business` — the one category deliberately excluded, because its
    "images" are topic illustrations (flags, logos, org charts). `general` is the
    dictionary's largest bucket (74,664 rows) and must stay eligible; treating
    every category outside IMAGE_CATEGORIES as junk wiped 玩具/声音/书/学校/医院
    in a single earlier pass.
    """
    bad_entry_ids = [
        r[0] for r in con.execute(
            "SELECT entry_id, simplified, category FROM entries"
        ).fetchall()
        if r[1] in FUNCTION_WORDS or (r[2] or "") == "business"
    ]
    removed = 0
    for entry_id in bad_entry_ids:
        cur = con.execute("DELETE FROM entry_images WHERE entry_id=?", (entry_id,))
        removed += cur.rowcount
        con.execute("DELETE FROM entry_concepts WHERE entry_id=?", (entry_id,))
    con.execute(
        "DELETE FROM images WHERE image_id NOT IN (SELECT image_id FROM entry_images)"
    )
    con.commit()
    print(f"  purged {removed} entry_images rows, "
          f"{con.execute('SELECT COUNT(*) FROM images').fetchone()[0]} assets remain")
    return removed


def fill_concept_labels(con: sqlite3.Connection) -> int:
    """Fetch the English label for every concept that has none.

    The English label is what makes cross-headword sharing possible: 玩具 ("toy"),
    玩意 ("plaything") and the English query "toy" all reach the same concept only
    if the concept itself carries the canonical English word. One batched
    `wbgetentities` call covers 50 ids, so this costs almost nothing.
    """
    missing = [
        r[0] for r in con.execute(
            "SELECT concept_id FROM concepts WHERE COALESCE(label_en,'') = ''"
        ).fetchall()
    ]
    filled = 0
    for start in range(0, len(missing), 50):
        chunk = missing[start:start + 50]
        qids = "|".join(c.replace("wd:", "") for c in chunk)
        try:
            data = get_json(WIKIDATA_API, {
                "action": "wbgetentities", "format": "json",
                "ids": qids, "props": "labels", "languages": "en",
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  label batch failed: {exc}")
            continue
        for cid in chunk:
            qid = cid.replace("wd:", "")
            ent = (data.get("entities") or {}).get(qid) or {}
            label = ((ent.get("labels") or {}).get("en") or {}).get("value") or ""
            if label:
                con.execute("UPDATE concepts SET label_en=? WHERE concept_id=?",
                            (label, cid))
                filled += 1
        con.commit()
        time.sleep(0.5)
    print(f"  concept labels filled: {filled}/{len(missing)}")
    return filled


def propagate_siblings(con: sqlite3.Connection) -> int:
    """Share an approved image with entries that are the *same lexical item*.

    Chinese has several headwords for one concept (玩具 / 玩意 both gloss "toy"),
    and a photo indexed against one of them was invisible on the other: searching
    "toy" landed on entry 72162 (玩意) while the image lived on 72148 (玩具), so
    the card said "No picture yet" with a perfectly good thumbnail on disk.

    An image is copied to a sibling only when both conditions hold:
      * the headword is identical, or the first sense gloss is byte-identical
        (case-sensitive, so "Turkey" never matches "turkey"), and
      * the sibling has the same category and is not a particle.
    Inherited rows carry a lower confidence (0.7) and their own method, so a
    review pass can tell them apart from directly matched images.
    """
    direct = con.execute(
        "SELECT ei.entry_id, ei.image_id, ei.match_confidence, "
        "       (SELECT s.gloss_en FROM senses s WHERE s.entry_id = ei.entry_id "
        "        ORDER BY s.sense_order LIMIT 1) AS gloss, "
        "       (SELECT c.label_en FROM entry_concepts ec "
        "        JOIN concepts c ON c.concept_id = ec.concept_id "
        "        WHERE ec.entry_id = ei.entry_id LIMIT 1) AS concept_en "
        "FROM entry_images ei WHERE ei.match_method != 'sibling'").fetchall()
    added = 0
    for entry_id, image_id, conf, gloss, concept_en in direct:
        if not gloss and not concept_en:
            continue
        word_row = con.execute(
            "SELECT simplified, traditional, category FROM entries WHERE entry_id=?",
            (entry_id,)).fetchone()
        if not word_row:
            continue
        simplified, traditional, category = word_row
        # Two bridges to the same concept:
        #   headword  — same spelling (玩具 / 玩具), survives any wording difference
        #   gloss     — the entry's own gloss, plus the concept's English label.
        # The label bridge is what connects 玩具 ("plaything") with 玩意 ("toy"),
        # which is the exact pair behind the "toy" placeholder on the phone.
        glosses = [g for g in (gloss, concept_en) if g]
        cond = " OR ".join(
            ["e.simplified = ?", "e.traditional = ?"]
            + ["(SELECT s.gloss_en FROM senses s WHERE s.entry_id=e.entry_id "
               "ORDER BY s.sense_order LIMIT 1) = ?"] * len(glosses)
        )
        params = [simplified, traditional or simplified] + glosses
        cand = con.execute(
            "SELECT e.entry_id, e.simplified, e.category FROM entries e "
            f"WHERE ({cond}) "
            "  AND e.entry_id NOT IN (SELECT entry_id FROM entry_images)",
            params).fetchall()
        for sid, swords, _cat in cand:
            if swords in FUNCTION_WORDS:
                continue
            con.execute(
                "INSERT OR REPLACE INTO entry_images(entry_id, sense_id, image_id, "
                " confidence, rank, match_method, match_confidence) "
                "VALUES (?,?,?,?,2,'sibling',?)",
                (sid, None, image_id, 0.7, 0.7),
            )
            added += 1
    con.commit()
    print(f"  propagated {added} sibling rows")
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--words", default="", help="comma separated headwords, bypasses --limit")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--purge", action="store_true",
                    help="delete mappings that current rules forbid, then continue")
    ap.add_argument("--propagate-only", action="store_true",
                    help="only share existing images with sibling entries, no network")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"no database at {db_path}", file=sys.stderr)
        return 1
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    if not args.dry_run:
        migrate(con)
        prune_missing(con)
        if args.purge:
            purge_bad(con)
        if args.propagate_only:
            fill_concept_labels(con)
            propagate_siblings(con)
            con.close()
            return 0

    done = {
        r[0] for r in con.execute(
            "SELECT DISTINCT e.simplified FROM entry_images ei "
            "JOIN images i ON i.image_id = ei.image_id "
            "JOIN entries e ON e.entry_id = ei.entry_id "
            "WHERE i.status = 'approved' "
            "  AND COALESCE(i.asset_status,'approved') = 'approved'"
        )
    }
    # Concept resolutions already recorded in a previous run are reused, so a
    # resumed run never pays the rate-limit cost twice (Issue 9 — idempotency).
    known = {
        r[0]: (r[1] or "").removeprefix("wd:")
        for r in con.execute(
            "SELECT entry_id, concept_id FROM entry_concepts WHERE concept_id LIKE 'wd:%'"
        )
    }
    words = select_words(con, args.limit, done)
    if args.words:
        wanted = [w.strip() for w in args.words.split(",") if w.strip()]
        rows = []
        for w in wanted:
            row = con.execute(
                "SELECT e.entry_id, e.simplified, e.traditional, e.category, e.freq_rank, "
                " (SELECT s.gloss_en FROM senses s WHERE s.entry_id = e.entry_id "
                "  ORDER BY s.sense_order LIMIT 1) AS gloss_en "
                "FROM entries e WHERE e.simplified = ? "
                "ORDER BY e.freq_rank LIMIT 1",
                (w,),
            ).fetchone()
            if row:
                rows.append(row)
        words = rows
    print(f"candidates: {len(words)} (already illustrated: {len(done)})")

    stats = {
        "tried": 0, "accepted": 0, "no_article": 0, "no_image": 0,
        "licence_rejected": 0, "quality_rejected": 0, "thumb_rejected": 0,
        "download_failed": 0, "duplicate_asset": 0,
    }
    sizes: list[int] = []
    failures: list[dict] = []
    started = time.time()
    manifest = (FULL_DIR.parent / "manifest_v2.jsonl").open("a", encoding="utf-8")

    for start in range(0, len(words), BATCH):
        chunk = words[start:start + BATCH]
        stats["tried"] += len(chunk)
        batch_words = [r["simplified"] for r in chunk]
        try:
            info = titles_info([
                (r["simplified"], r["traditional"] or "") for r in chunk
            ])
        except Exception as exc:  # noqa: BLE001
            print(f"batch {start}: title lookup failed ({exc})")
            info = {}

        for row in chunk:
            qid = known.get(row["entry_id"])
            if qid and row["simplified"] not in info:
                info[row["simplified"]] = {
                    "qid": qid, "file": "", "title": row["simplified"],
                    "method": "cache", "conf": 0.85,
                }

        # Per-word Wikidata search is expensive under the shared-IP rate limit,
        # so only one slow path is used: the English gloss. The Chinese-label
        # search duplicates it and doubled the 429 rate.
        gloss_of = {r["simplified"]: (r["gloss_en"] or "") for r in chunk}
        still_missing = [w for w in batch_words if w not in info]
        for word in still_missing:
            hit = search_gloss_label(gloss_of.get(word, ""), max(args.sleep, 1.2))
            if hit:
                info[word] = {**hit, "method": "en-gloss", "conf": 0.75}

        # second pass: ask Wikidata for P18 for every resolved concept — the
        # article lead image is sometimes a GIF/logo that the quality gate
        # rejects, and P18 is often a better photograph of the same concept.
        qids = [v["qid"] for v in info.values() if v["qid"]]
        p18: dict[str, str] = {}
        if qids:
            try:
                p18 = p18_for_qids(qids)
            except Exception as exc:  # noqa: BLE001
                print(f"batch {start}: P18 lookup failed ({exc})")

        per_word_files: dict[str, list[str]] = {}
        for word in batch_words:
            row = info.get(word)
            if not row:
                continue
            files_for_word = []
            if row["file"]:
                files_for_word.append(row["file"])
            alt = p18.get(row["qid"], "")
            if alt and alt not in files_for_word:
                files_for_word.append(alt)
            per_word_files[word] = files_for_word

        images: dict[str, dict] = {}
        all_files = sorted({f for files in per_word_files.values() for f in files})
        if all_files:
            try:
                images = commons_batch(all_files)
            except Exception as exc:  # noqa: BLE001
                print(f"batch {start}: commons lookup failed ({exc})")

        for row in chunk:
            word = row["simplified"]
            hit = info.get(word)
            if not hit:
                stats["no_article"] += 1
                print(f"  {word:6s} no exact article  (resolved={len(info)}/{len(chunk)})")
                continue

            chosen_file = ""
            image_info: dict = {}
            for candidate_file in per_word_files.get(word, []):
                if NOISE_FILE.search(candidate_file):
                    continue
                candidate_info = images.get(candidate_file)
                if not candidate_info:
                    continue
                ok_q_peek, _ = quality_ok(
                    int(candidate_info.get("width") or 0),
                    int(candidate_info.get("height") or 0),
                    candidate_info.get("mime", ""),
                )
                if ok_q_peek:
                    chosen_file, image_info = candidate_file, candidate_info
                    break
            if not image_info:
                stats["no_image"] += 1
                continue
            file_name = chosen_file

            meta = image_info.get("extmetadata") or {}
            license_name = _strip_html((meta.get("LicenseShortName") or {}).get("value", ""))
            author = _strip_html((meta.get("Artist") or {}).get("value", ""))
            license_url = _strip_html((meta.get("LicenseUrl") or {}).get("value", ""))
            ok_l, why_l = licence_ok(license_name, author)
            ok_q, why_q = quality_ok(
                int(image_info.get("width") or 0),
                int(image_info.get("height") or 0),
                image_info.get("mime", ""),
            )
            if not ok_l:
                stats["licence_rejected"] += 1
                failures.append({"word": word, "reason": why_l})
                continue
            if not ok_q:
                stats["quality_rejected"] += 1
                failures.append({"word": word, "reason": why_q})
                continue

            url = image_info.get("thumburl") or image_info["url"]
            try:
                blob = safe_get(url)
            except Exception as exc:  # noqa: BLE001
                stats["download_failed"] += 1
                failures.append({"word": word, "reason": str(exc)[:120]})
                continue

            sha256 = hashlib.sha256(blob).hexdigest()
            sha16 = sha256[:16]
            picture = Image.open(io.BytesIO(blob))
            picture.load()
            phash = dhash(picture)
            thumb = make_thumb(picture)
            if thumb is None:
                stats["thumb_rejected"] += 1
                failures.append({"word": word, "reason": "thumb > 15 KB"})
                continue
            thumb_bytes, thumb_w, thumb_h = thumb
            sizes.append(len(thumb_bytes))

            if args.dry_run:
                stats["accepted"] += 1
                print(f"  {word:6s} {hit['title'][:12]:12s} {file_name[:30]:30s} "
                      f"{license_name:12s} {len(thumb_bytes):5d} B  DRY")
                time.sleep(args.sleep)
                continue

            existing = con.execute(
                "SELECT image_id FROM images WHERE content_hash = ?", (sha256,)
            ).fetchone()
            if existing:
                image_id = existing[0]
                stats["duplicate_asset"] += 1
            else:
                ext = "png" if picture.format == "PNG" else (
                    "webp" if picture.format == "WEBP" else "jpg")
                full_path = FULL_DIR / f"{sha16}.{ext}"
                thumb_path = THUMB_DIR / f"{sha16}.webp"
                if not full_path.exists():
                    full_path.write_bytes(blob)
                if not thumb_path.exists():
                    thumb_path.write_bytes(thumb_bytes)
                attribution = (
                    f"{file_name} — {author} — {license_name} via Wikimedia Commons"
                )
                cur = con.execute(
                    "INSERT INTO images(content_hash, title, thumb_path, detail_path, "
                    " width, height, source, source_url, author, license, license_url, "
                    " attribution_text, status, thumb_asset, detail_url, asset_status, "
                    " phash, thumb_bytes, license_status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'approved',?,?,'approved',?,?, 'verified')",
                    (
                        sha256, file_name, str(thumb_path).replace("\\", "/"),
                        str(full_path).replace("\\", "/"), thumb_w, thumb_h,
                        "wikimedia_commons", image_info.get("descriptionurl", ""),
                        author, license_name, license_url, attribution,
                        f"assets/images/thumbs/{sha16}.webp", url, phash,
                        len(thumb_bytes),
                    ),
                )
                image_id = cur.lastrowid

            method = hit.get("method", "zh-title")
            conf = float(hit.get("conf") or 0.9)
            con.execute(
                "INSERT OR REPLACE INTO concepts(concept_id, source, qid, label_zh, "
                " label_en, description, category, created_at) "
                "VALUES (?, 'wikidata', ?, ?, ?, ?, ?, ?)",
                (f"wd:{hit['qid']}", hit["qid"], word, "", hit["title"],
                 row["category"] or "", time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                      time.gmtime())),
            )
            con.execute(
                "INSERT OR REPLACE INTO concept_images(concept_id, image_id, "
                " relevance, is_primary) VALUES (?,?,?,1)",
                (f"wd:{hit['qid']}", image_id, conf),
            )
            con.execute(
                "INSERT OR REPLACE INTO entry_images(entry_id, sense_id, image_id, "
                " confidence, rank, match_method, match_confidence) "
                "VALUES (?,?,?,?,1,?,?)",
                (row["entry_id"], None, image_id, conf, method, conf),
            )
            con.execute(
                "INSERT OR REPLACE INTO entry_concepts(entry_id, concept_id, "
                " confidence, method) VALUES (?,?,?,?)",
                (row["entry_id"], f"wd:{hit['qid']}", conf, method),
            )
            con.commit()
            stats["accepted"] += 1
            manifest.write(json.dumps({
                "entry_id": row["entry_id"], "word": word,
                "concept": f"wd:{hit['qid']}", "article": hit["title"],
                "file": file_name, "license": license_name, "author": author,
                "sha16": sha16, "phash": phash, "thumb_bytes": len(thumb_bytes),
                "thumb": f"assets/images/thumbs/{sha16}.webp", "detail_url": url,
            }, ensure_ascii=False) + "\n")
            manifest.flush()
            print(f"  {word:6s} {hit['title'][:12]:12s} {file_name[:30]:30s} "
                  f"{license_name:12s} {len(thumb_bytes):5d} B")
            time.sleep(args.sleep)

    manifest.close()
    if not args.dry_run:
        propagate_siblings(con)
    elapsed = round(time.time() - started, 1)
    report = {
        **stats,
        "candidates": len(words),
        "seconds": elapsed,
        "sec_per_word": round(elapsed / max(1, stats["tried"]), 2),
        "thumb_max_bytes": max(sizes) if sizes else 0,
        "thumb_avg_bytes": round(sum(sizes) / len(sizes)) if sizes else 0,
        "thumb_over_limit": sum(1 for s in sizes if s > THUMB_MAX_BYTES),
        "accept_rate": round(stats["accepted"] / max(1, stats["tried"]), 3),
        "failures": failures[:25],
        "images_in_db": con.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        if not args.dry_run else None,
        "entries_with_image": con.execute(
            "SELECT COUNT(DISTINCT entry_id) FROM entry_images").fetchone()[0]
        if not args.dry_run else None,
    }
    (FULL_DIR.parent / "report_v2.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
