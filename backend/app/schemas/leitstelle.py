import uuid
from pydantic import BaseModel


class ZusatzKanal(BaseModel):
    name: str
    kanal: str


class LeistelleCreate(BaseModel):
    name: str
    anrufgruppe: str
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
