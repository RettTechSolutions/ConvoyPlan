import uuid
from pydantic import BaseModel, Field


class ZusatzKanal(BaseModel):
    name: str
    kanal: str


class LeistelleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    anrufgruppe: str = Field(min_length=1, max_length=50)
    zusatz_kanaele: list[ZusatzKanal] = []


class LeistelleUpdate(BaseModel):
    name: str | None = None
    anrufgruppe: str | None = None
    zusatz_kanaele: list[ZusatzKanal] | None = None


class LeistelleResponse(BaseModel):
    id: uuid.UUID
    name: str
    anrufgruppe: str
    zusatz_kanaele: list[ZusatzKanal]
    has_geometry: bool

    model_config = {"from_attributes": True}


class LeistelleDetailResponse(LeistelleResponse):
    geometry_geojson: dict | None = None
