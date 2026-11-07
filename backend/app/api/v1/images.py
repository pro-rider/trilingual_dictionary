"""Image lookup API (stage 43 of the image plan).

Returns the approved image for an entry plus its attribution, or a category icon
key when there is none — never an error for a word that simply has no picture.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Query, Request

from app.core.config import settings
from app.schemas.images import ImageItem, ImagesResponse

router = APIRouter(tags=["images"])

MAX_BATCH = 50


def _db() -> Path:
    return Path(settings.dictionary_db_path)


def _normalise_entry_id(raw: str) -> str:
    """Accept 'zh23847', '23847' or a legacy fixture id."""
    raw = (raw or "").strip()
    if raw.startswith("zh") and raw[2:].isdigit():
        return raw[2:]
    return raw if raw.isdigit() else ""


def _relative(path: str) -> str:
    """Stored paths look like data/images/ab/hash_256.jpg."""
    normalised = path.replace("\\", "/")
    marker = "data/images/"
    idx = normalised.find(marker)
    return normalised[idx + len(marker):] if idx >= 0 else normalised


def _url(request: Request, relative: str) -> str:
    base = (settings.image_base_url or str(request.base_url)).rstrip("/")
    return f"{base}/static/images/{relative}"


def _query(entry_ids: list[str]) -> dict[str, list[dict]]:
    if not entry_ids or not _db().exists():
        return {}
    con = sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in entry_ids)
        rows = con.execute(
            f"SELECT ei.entry_id, ei.confidence, ei.rank, ei.match_method, "
            f"i.image_id, i.thumb_path, i.detail_path, i.width, i.height, "
            f"i.attribution_text, i.license, i.license_url, i.source_url "
            f"FROM entry_images ei JOIN images i ON i.image_id = ei.image_id "
            f"WHERE i.status = 'approved' AND ei.entry_id IN ({placeholders}) "
            f"ORDER BY ei.entry_id, ei.rank",
            entry_ids,
        ).fetchall()
    finally:
        con.close()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["entry_id"]), []).append(dict(row))
    return grouped


def _category_icon(entry_id: str) -> str:
    """Fallback icon key so the client shows something meaningful, not a blank."""
    if not entry_id or not _db().exists():
        return "general"
    con = sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT category, is_chengyu, is_proper FROM entries WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        con.close()
    if not row:
        return "general"
    if row[1]:
        return "idiom"
    if row[2]:
        return "proper_noun"
    return row[0] or "general"


@router.get("/images", response_model=ImagesResponse)
def images(request: Request, entry_id: str = Query(...), limit: int = Query(3, ge=1, le=5)):
    normalised = _normalise_entry_id(entry_id)
    grouped = _query([normalised]) if normalised else {}
    rows = grouped.get(normalised, [])[:limit]

    items = [
        ImageItem(
            image_id=row["image_id"],
            thumb_url=_url(request, _relative(row["thumb_path"] or "")),
            detail_url=_url(request, _relative(row["detail_path"] or "")),
            width=row["width"] or 0,
            height=row["height"] or 0,
            attribution=row["attribution_text"] or "",
            license=row["license"] or "",
            license_url=row["license_url"] or "",
            source_url=row["source_url"] or "",
            confidence=round(row["confidence"] or 0, 2),
            match_method=row["match_method"] or "",
        )
        for row in rows
        if row["thumb_path"] and row["detail_path"]
    ]
    return ImagesResponse(
        entry_id=entry_id,
        items=items,
        icon=_category_icon(normalised),
    )


@router.get("/images/batch", response_model=list[ImagesResponse])
def images_batch(
    request: Request,
    entry_ids: str = Query(..., description="Comma-separated, max 50"),
    limit: int = Query(2, ge=1, le=5),
):
    raw = [part for part in entry_ids.split(",") if part.strip()][:MAX_BATCH]
    normalised = {raw_id: _normalise_entry_id(raw_id) for raw_id in raw}
    grouped = _query([v for v in normalised.values() if v])

    out = []
    for raw_id, norm in normalised.items():
        rows = grouped.get(norm, [])[:limit]
        out.append(
            ImagesResponse(
                entry_id=raw_id,
                items=[
                    ImageItem(
                        image_id=row["image_id"],
                        thumb_url=_url(request, _relative(row["thumb_path"] or "")),
                        detail_url=_url(request, _relative(row["detail_path"] or "")),
                        width=row["width"] or 0,
                        height=row["height"] or 0,
                        attribution=row["attribution_text"] or "",
                        license=row["license"] or "",
                        license_url=row["license_url"] or "",
                        source_url=row["source_url"] or "",
                        confidence=round(row["confidence"] or 0, 2),
                        match_method=row["match_method"] or "",
                    )
                    for row in rows
                    if row["thumb_path"] and row["detail_path"]
                ],
                icon=_category_icon(norm),
            )
        )
    return out
