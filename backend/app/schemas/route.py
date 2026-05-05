import uuid
from typing import Any

from pydantic import BaseModel


class FuelStopPosition(BaseModel):
    lat: float
    lon: float


class VehicleRangeInfo(BaseModel):
    name: str
    callsign: str | None
    range_km: float


class FuelAnalysis(BaseModel):
    vehicles_with_range: list[VehicleRangeInfo]
    min_range_km: float | None
    route_distance_km: float
    fuel_stop_needed: bool
    fuel_stop_km: float | None
    fuel_stop_position: FuelStopPosition | None
    limiting_vehicle: str | None


class RouteResponse(BaseModel):
    id: uuid.UUID
    convoy_id: uuid.UUID
    distance_m: int | None
    duration_s: int | None
    routing_params: dict[str, Any] | None
    geojson: dict | None = None
    fuel_analysis: FuelAnalysis | None = None

    model_config = {"from_attributes": True}
