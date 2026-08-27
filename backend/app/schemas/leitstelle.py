import uuid
from typing import Annotated

from pydantic import BaseModel, Field

# Gebietsschlüssel: ISO-Länderkürzel, Bindestrich, Schlüssel der jeweiligen
# Landesebene — "DE-08115" (AGS), "AT-322" (Bezirkskennziffer), "CH-040"
# (Kanton), "LI-000". Das Präfix ist Pflicht, weil sich die Nummernkreise sonst
# überschneiden: der dreistellige österreichische Bezirk "401" und ein
# deutscher AGS-Anfang wären nicht mehr auseinanderzuhalten.
#
# Die Prüfung ist bewusst nur formal — welche Schlüssel es wirklich gibt, steht
# in `frontend/static/geo/gebiete.geojson`, und die Liste hier gegen den
# Geodatensatz zu spiegeln hieße, sie bei jeder Gebietsreform doppelt zu pflegen.
DistrictCode = Annotated[str, Field(pattern=r"^(DE|AT|CH|LI)-[A-Za-z0-9]{1,10}$")]


class ZusatzKanal(BaseModel):
    name: str
    kanal: str


class LeistelleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    anrufgruppe: str = Field(min_length=1, max_length=50)
    zusatz_kanaele: list[ZusatzKanal] = []
    district_codes: list[DistrictCode] | None = None


class LeistelleUpdate(BaseModel):
    name: str | None = None
    anrufgruppe: str | None = None
    zusatz_kanaele: list[ZusatzKanal] | None = None
    district_codes: list[DistrictCode] | None = None


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
