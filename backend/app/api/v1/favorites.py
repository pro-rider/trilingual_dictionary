from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.security import SupabaseUser
from app.models.cloud import Favorite
from app.schemas.search import (
    FavoriteAddRequest,
    FavoritesResponse,
)

router = APIRouter(tags=["favorites"])


@router.get("/favorites", response_model=FavoritesResponse)
def list_favorites(db: DbSession, user: dict = SupabaseUser):
    rows = db.scalars(
        select(Favorite.entry_id)
        .where(Favorite.user_id == user["uid"])
        .order_by(Favorite.entry_id)
    ).all()
    return FavoritesResponse(entry_ids=list(rows))


@router.post("/favorites", response_model=FavoritesResponse)
def add_favorite(req: FavoriteAddRequest, db: DbSession, user: dict = SupabaseUser):
    exists = db.scalar(
        select(Favorite.id).where(
            Favorite.user_id == user["uid"],
            Favorite.entry_id == req.entry_id,
        )
    )
    if exists is None:
        db.add(Favorite(user_id=user["uid"], entry_id=req.entry_id))
        db.commit()
    return list_favorites(db, user)


@router.delete("/favorites/{entry_id}", response_model=FavoritesResponse)
def remove_favorite(entry_id: str, db: DbSession, user: dict = SupabaseUser):
    rows = db.scalars(
        select(Favorite).where(
            Favorite.user_id == user["uid"], Favorite.entry_id == entry_id
        )
    ).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return list_favorites(db, user)
