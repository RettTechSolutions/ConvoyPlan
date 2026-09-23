import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.vehicle import VehicleResponse
from app.schemas.waypoint import WaypointResponse
from app.services.staerke import MAX_JE_ROLLE


class PointSchema(BaseModel):
    lat: float
    lon: float


class ConvoyCreate(BaseModel):
    name: str
    organization: str | None = None
    organization_id: uuid.UUID | None = None
    start_time: datetime | None = None
    start_point: PointSchema | None = None
    end_point: PointSchema | None = None
    speed_urban_kmh: int = 40
    speed_rural_kmh: int = 65
    # "bundesstrasse"/"landstrasse" are legacy values, mapped to "standard"
    road_preference: Literal["standard", "schnell", "kuerzeste", "bundesstrasse", "landstrasse"] = "standard"
    spacing_urban_m: int = 15
    spacing_rural_m: int = 50
    spacing_motorway_m: int = 100
    lage: str | None = None
    auftrag: str | None = None
    marschform: str | None = None
    ablaufpunkt: str | None = None
    ablaufzeit: datetime | None = None
    ablaufführer: str | None = None
    versorgung: str | None = None
    funkgruppe: str | None = None
    anlagen: str | None = None


class ConvoyUpdate(BaseModel):
    name: str | None = None
    organization: str | None = None
    organization_id: uuid.UUID | None = None
    start_time: datetime | None = None
    start_point: PointSchema | None = None
    end_point: PointSchema | None = None
    speed_urban_kmh: int | None = None
    speed_rural_kmh: int | None = None
    road_preference: Literal["standard", "schnell", "kuerzeste", "bundesstrasse", "landstrasse"] | None = None
    spacing_urban_m: int | None = None
    spacing_rural_m: int | None = None
    spacing_motorway_m: int | None = None
    status: str | None = None
    lage: str | None = None
    auftrag: str | None = None
    marschform: str | None = None
    ablaufpunkt: str | None = None
    ablaufzeit: datetime | None = None
    ablaufführer: str | None = None
    versorgung: str | None = None
    funkgruppe: str | None = None
    anlagen: str | None = None


class ConvoyVehicleItem(BaseModel):
    vehicle: VehicleResponse
    position: int
    vehicle_status: str = "planned"
    status_level: str | None = None
    status_note: str | None = None
    status_changed_at: datetime | None = None
    sonderfunktion: str | None = None
    mobile_phone: str | None = None
    staerke_soll_fuehrer: int | None = None
    staerke_soll_unterfuehrer: int | None = None
    staerke_soll_mannschaften: int | None = None
    staerke_ist_fuehrer: int | None = None
    staerke_ist_unterfuehrer: int | None = None
    staerke_ist_mannschaften: int | None = None
    staerke_gemeldet_at: datetime | None = None
    fuellstand_ist_prozent: int | None = None
    fuellstand_gemeldet_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConvoyResponse(BaseModel):
    id: uuid.UUID
    name: str
    organization: str | None
    organization_id: uuid.UUID | None = None
    start_time: datetime | None
    speed_urban_kmh: int
    speed_rural_kmh: int
    road_preference: str
    spacing_urban_m: int
    spacing_rural_m: int
    spacing_motorway_m: int
    status: str
    share_token: uuid.UUID
    created_at: datetime
    start_point: PointSchema | None = None
    end_point: PointSchema | None = None
    convoy_vehicles: list[ConvoyVehicleItem] = []
    waypoints: list[WaypointResponse] = []
    lage: str | None = None
    auftrag: str | None = None
    marschform: str | None = None
    ablaufpunkt: str | None = None
    ablaufzeit: datetime | None = None
    ablaufführer: str | None = None
    versorgung: str | None = None
    funkgruppe: str | None = None
    anlagen: str | None = None

    model_config = {"from_attributes": True}


class AddVehicleRequest(BaseModel):
    vehicle_id: uuid.UUID
    position: int = 0
    sonderfunktion: str | None = None
    mobile_phone: str | None = None
    staerke_soll_fuehrer: int | None = Field(None, ge=0, le=MAX_JE_ROLLE)
    staerke_soll_unterfuehrer: int | None = Field(None, ge=0, le=MAX_JE_ROLLE)
    staerke_soll_mannschaften: int | None = Field(None, ge=0, le=MAX_JE_ROLLE)


class UpdateVehicleInConvoyRequest(BaseModel):
    """Was der Planer an einem Fahrzeug *im Verband* ändert.

    Die Marschfolge steht bewusst nicht darin — die hat mit
    ``PATCH .../vehicles/reorder`` einen eigenen Weg, der die Positionen
    lückenlos hält. Zwei Wege auf dieselbe Spalte wären einer zu viel.

    Nur genannte Felder werden geschrieben (``exclude_unset``), sonst löschte
    ein Formular, das nur die Stärke schickt, die Sonderfunktion mit.
    """

    sonderfunktion: str | None = None
    mobile_phone: str | None = None
    staerke_soll_fuehrer: int | None = Field(None, ge=0, le=MAX_JE_ROLLE)
    staerke_soll_unterfuehrer: int | None = Field(None, ge=0, le=MAX_JE_ROLLE)
    staerke_soll_mannschaften: int | None = Field(None, ge=0, le=MAX_JE_ROLLE)


class ConvoyVehicleReorderItem(BaseModel):
    vehicle_id: uuid.UUID
    position: int
