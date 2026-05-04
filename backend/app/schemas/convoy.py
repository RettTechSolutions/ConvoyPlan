import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.vehicle import VehicleResponse
from app.schemas.waypoint import WaypointResponse


class PointSchema(BaseModel):
    lat: float
    lon: float


class ConvoyCreate(BaseModel):
    name: str
    organization: str | None = None
    start_time: datetime | None = None
    start_point: PointSchema | None = None
    end_point: PointSchema | None = None
    speed_urban_kmh: int = 50
    speed_rural_kmh: int = 80


class ConvoyUpdate(BaseModel):
    name: str | None = None
    organization: str | None = None
    start_time: datetime | None = None
    start_point: PointSchema | None = None
    end_point: PointSchema | None = None
    speed_urban_kmh: int | None = None
    speed_rural_kmh: int | None = None
    status: str | None = None


class ConvoyVehicleItem(BaseModel):
    vehicle: VehicleResponse
    position: int

    model_config = {"from_attributes": True}


class ConvoyResponse(BaseModel):
    id: uuid.UUID
    name: str
    organization: str | None
    start_time: datetime | None
    speed_urban_kmh: int
    speed_rural_kmh: int
    status: str
    share_token: uuid.UUID
    created_at: datetime
    start_point: PointSchema | None = None
    end_point: PointSchema | None = None
    convoy_vehicles: list[ConvoyVehicleItem] = []
    waypoints: list[WaypointResponse] = []

    model_config = {"from_attributes": True}


class AddVehicleRequest(BaseModel):
    vehicle_id: uuid.UUID
    position: int = 0
