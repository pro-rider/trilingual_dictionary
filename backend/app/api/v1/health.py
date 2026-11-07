from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": settings.version,
        "dataset_version": settings.dataset_version,
    }
