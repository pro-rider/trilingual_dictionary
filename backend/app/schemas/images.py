from pydantic import BaseModel, Field


class ImageItem(BaseModel):
    image_id: int
    thumb_url: str
    detail_url: str
    width: int = 0
    height: int = 0
    attribution: str = ""
    license: str = ""
    license_url: str = ""
    source_url: str = ""
    confidence: float = 0.0
    match_method: str = ""


class ImagesResponse(BaseModel):
    entry_id: str
    items: list[ImageItem] = Field(default_factory=list)
    icon: str = "general"
