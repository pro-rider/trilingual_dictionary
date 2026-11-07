from fastapi import APIRouter

from app.api.v1 import (
    auth,
    feedback,
    health,
    popular,
    providers,
    search,
    sentence,
    suggest,
    favorites,
    analyze,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(providers.router)
api_router.include_router(search.router)
api_router.include_router(analyze.router)
api_router.include_router(sentence.router)
api_router.include_router(popular.router)
api_router.include_router(suggest.router)
api_router.include_router(auth.router)
api_router.include_router(favorites.router)
api_router.include_router(feedback.router)
