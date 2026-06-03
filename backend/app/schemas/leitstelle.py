import uuid
from pydantic import BaseModel, Field


class ZusatzKanal(BaseModel):
    name: str
    kanal: str


class LeistelleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    anrufgruppe: str = Field(min_length=1, max_length=50)
    zusatz_kanaele: list[ZusatzKanal] = []
    district_codes: list[str] | None = None


class LeistelleUpdate(BaseModel):
    name: str | None = None
    anrufgruppe: str | None = None
    zusatz_kanaele: list[ZusatzKanal] | None = None
    district_codes: list[str] | None = None


class LeistelleReject(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class LeistelleResponse(BaseModel):
    id: uuid.UUID
    name: str
    anrufgruppe: str
    zusatz_kanaele: list[ZusatzKanal]
    has_geometry: bool
    district_codes: list[str] = []
    org_id: uuid.UUID | None = None
    org_name: str | None = None
    status: str = "global"
    proposed_by_org_id: uuid.UUID | None = None
    proposed_by_org_name: str | None = None
    review_note: str | None = None

    model_config = {"from_attributes": True}


class LeistelleDetailResponse(LeistelleResponse):
    geometry_geojson: dict | None = None
