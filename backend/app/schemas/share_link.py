import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ShareLinkCreate(BaseModel):
    password_mode: Literal["none", "generate", "set"]
    password: str | None = None

    @model_validator(mode="after")
    def _check_password(self) -> "ShareLinkCreate":
        if self.password_mode == "set":
            if not self.password or len(self.password) < 4:
                raise ValueError("Passwort muss mindestens 4 Zeichen lang sein")
        else:
            self.password = None
        return self


class ShareLinkResponse(BaseModel):
    id: uuid.UUID
    slug: str
    scope: str
    requires_password: bool
    created_at: datetime
    last_accessed_at: datetime | None
    access_count: int
    revoked: bool
    url: str

    model_config = {"from_attributes": True}


class ShareLinkCreated(ShareLinkResponse):
    password_plain: str | None = Field(
        default=None,
        description="Plain-text password; only present immediately after creation in 'generate' mode.",
    )


class TrackAuthRequest(BaseModel):
    password: str


class TrackAuthResponse(BaseModel):
    token: str


class TrackVehicle(BaseModel):
    id: uuid.UUID
    name: str
    callsign: str | None = None
    sonderfunktion: str | None = None
    vehicle_status: str | None = None
    position: int


class TrackWaypoint(BaseModel):
    name: str
    type: str
    lat: float | None = None
    lon: float | None = None
    planned_arrival: datetime | None = None
    planned_departure: datetime | None = None
    halt_purpose: str | None = None


class TrackPosition(BaseModel):
    vehicle_id: uuid.UUID
    lat: float
    lon: float
    speed_kmh: float | None = None
    heading: float | None = None
    recorded_at: datetime


class TrackPublic(BaseModel):
    name: str
    organization: str | None = None
    start_time: datetime | None = None
    waypoints: list[TrackWaypoint]
    geojson: dict | None = None
    vehicles: list[TrackVehicle]
    positions: list[TrackPosition]


class TrackGate(BaseModel):
    requires_password: bool
    convoy_name: str
