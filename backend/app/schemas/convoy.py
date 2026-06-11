import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.vehicle import VehicleResponse
from app.schemas.waypoint import WaypointResponse


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


class UpdateVehicleInConvoyRequest(BaseModel):
    position: int | None = None
    sonderfunktion: str | None = None
    mobile_phone: str | None = None


class ConvoyVehicleReorderItem(BaseModel):
    vehicle_id: uuid.UUID
    position: int
