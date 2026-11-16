"""Concept layer, stage 1 (bounded live probe): does Commons actually deliver?

Stage 0 (`image_concept_plan.py`) showed how many entries a concept would cover.
This stage checks the other half of the question with real network calls: for a
concept keyword, can Wikimedia Commons return a *licence-clean, usable* bitmap,
how long does it take, and what share of concepts pass?

Nothing here touches a dictionary: it writes thumbnails to `data/images/_probe/`
and a CSV under `review/`. No DB write, no app bundle change.

Usage
-----
  python tools/image_concept_probe.py --concepts cat,water,tree --limit-per 4
  python tools/image_concept_probe.py --all
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://commons.wikimedia.org/w/api.php"
UA = "TrilingualDictionary/0.3 (concept image probe; lexicography) python-urllib"

ALLOWED_LICENCE = re.compile(r"^(cc0|cc by(-sa)?|public domain|pd)\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"\b(nc|nd|noncommercial|no.?deriv)\b", re.IGNORECASE)
NOISE_TITLE = re.compile(
    r"(logo|coat of arms|seal|map|carte|diagram|chart|screenshot|poster|stamp|"
    r"coin|banknote|sign|panneau|plaque|monument|cemetery|grave)",
    re.IGNORECASE,
)

DEFAULT_CONCEPTS = [
    "cat", "water", "tree", "mountain", "book", "chair", "hand", "car",
    "train", "apple", "doctor", "umbrella",
]


@dataclass
class Hit:
    concept: str
    title: str
    license: str
    license_url: str
    author: str
    source_url: str
    thumb_url: str
    width: int
    height: int
    bytes: int = 0
    pass_licence: bool = False
    pass_quality: bool = False
    reasons: list[str] = field(default_factory=list)


def get_json(params: dict, timeout: int = 25, attempts: int = 4) -> dict:
    """Commons answers 429 with a `retry-after` header; honour it instead of guessing."""
    url = API + "?" + urllib.parse.urlencode(params)
    last = ""
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            wait = 0
            try:
                wait = int(exc.headers.get("retry-after") or 0)
            except ValueError:
                wait = 0
            last = f"429, retry-after={wait}s"
            time.sleep(max(wait, 2) + attempt)
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 + attempt)
    raise RuntimeError(f"gave up after {attempts} attempts ({last})")


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value or ""))).strip()


def search(concept: str, limit: int) -> list[Hit]:
    data = get_json(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f'{concept} filetype:bitmap',
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": "640",
        }
    )
    hits: list[Hit] = []
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        hits.append(
            Hit(
                concept=concept,
                title=page.get("title", ""),
                license=strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
                license_url=strip_html((meta.get("LicenseUrl") or {}).get("value", "")),
                author=strip_html((meta.get("Artist") or {}).get("value", ""))[:120],
                source_url=info.get("descriptionurl", ""),
                thumb_url=info.get("thumburl", ""),
                width=int(info.get("width") or 0),
                height=int(info.get("height") or 0),
            )
        )
    return hits


def judge(hit: Hit) -> None:
    lic = hit.license or ""
    if not lic:
        hit.reasons.append("no licence metadata")
    elif FORBIDDEN.search(lic):
        hit.reasons.append(f"licence not allowed: {lic}")
    elif not ALLOWED_LICENCE.match(lic):
        hit.reasons.append(f"licence outside allowlist: {lic}")
    else:
        hit.pass_licence = True

    if NOISE_TITLE.search(hit.title):
        hit.reasons.append("noise title")
    if hit.width < 500 or hit.height < 400:
        hit.reasons.append(f"too small {hit.width}x{hit.height}")
    if hit.width and hit.height and hit.width / hit.height > 2.2:
        hit.reasons.append("extreme aspect")
    if not hit.thumb_url:
        hit.reasons.append("no thumbnail url")

    hit.pass_quality = not any(
        r.startswith(("noise", "too small", "extreme", "no thumbnail")) for r in hit.reasons
    )


def download(hit: Hit, out_dir: Path) -> None:
    if not hit.thumb_url:
        return
    req = urllib.request.Request(hit.thumb_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        blob = resp.read()
    name = hashlib.sha256(blob).hexdigest()[:10]
    path = out_dir / f"{hit.concept}_{name}.jpg"
    path.write_bytes(blob)
    hit.bytes = len(blob)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--concepts", default="", help="comma separated; empty = --all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit-per", type=int, default=4)
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--out", default=str(ROOT / "review" / "image_concepts_probe.csv"))
    args = ap.parse_args(argv)

    concepts = (
        DEFAULT_CONCEPTS if args.all or not args.concepts
        else [c.strip() for c in args.concepts.split(",") if c.strip()]
    )
    out_dir = ROOT / "data" / "images" / "_probe"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    t_start = time.time()
    solved = 0

    for concept in concepts:
        t0 = time.time()
        try:
            hits = search(concept, args.limit_per)
        except Exception as exc:  # noqa: BLE001
            print(f"{concept:<12} search failed: {exc}")
            rows.append({"concept": concept, "status": "search_failed", "reason": str(exc)})
            continue
        for hit in hits:
            judge(hit)
        good = [h for h in hits if h.pass_licence and h.pass_quality]
        good.sort(key=lambda h: (min(h.width, 2400), h.bytes), reverse=True)
        chosen = good[0] if good else None
        if chosen:
            solved += 1
            try:
                download(chosen, out_dir)
            except Exception as exc:  # noqa: BLE001
                chosen.reasons.append(f"download failed: {exc}")
        elapsed = round(time.time() - t0, 2)
        best_reason = "; ".join(chosen.reasons) if chosen else (
            hits[0].reasons[0] if hits and hits[0].reasons else "no result"
        )
        print(
            f"{concept:<12} results={len(hits):<2} usable={len(good):<2} "
            f"{'OK' if chosen else 'FAIL'}  {elapsed:>5.2f}s  {best_reason[:60]}"
        )
        rows.append(
            {
                "concept": concept,
                "status": "ok" if chosen else "no_usable_image",
                "title": chosen.title if chosen else "",
                "license": chosen.license if chosen else "",
                "license_url": chosen.license_url if chosen else "",
                "author": chosen.author if chosen else "",
                "source_url": chosen.source_url if chosen else "",
                "width": chosen.width if chosen else "",
                "height": chosen.height if chosen else "",
                "bytes": chosen.bytes if chosen else "",
                "seconds": elapsed,
                "reason": best_reason,
            }
        )
        time.sleep(args.sleep)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total = len(concepts)
    elapsed_all = time.time() - t_start
    print()
    print(f"concepts tested      {total}")
    print(f"usable image found   {solved}  ({100.0 * solved / max(1, total):.1f}%)")
    print(f"seconds / concept    {elapsed_all / max(1, total):.2f}")
    print(f"wrote {out}  (thumbnails in {out_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
