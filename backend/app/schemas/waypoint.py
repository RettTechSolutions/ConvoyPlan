import uuid
from datetime import datetime

from pydantic import BaseModel


class WaypointCreate(BaseModel):
    name: str
    type: str = "waypoint"
    lat: float
    lon: float
    hold_duration_min: int = 0
    notes: str | None = None
    order_index: int = 0


class WaypointUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    lat: float | None = None
    lon: float | None = None
    planned_arrival: datetime | None = None
    planned_departure: datetime | None = None
    hold_duration_min: int | None = None
    notes: str | None = None
    order_index: int | None = None


class WaypointResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    lat: float | None = None
    lon: float | None = None
    planned_arrival: datetime | None
    planned_departure: datetime | None
    hold_duration_min: int
    notes: str | None
    order_index: int

    model_config = {"from_attributes": True}
