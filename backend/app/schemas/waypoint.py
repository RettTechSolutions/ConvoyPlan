import uuid
from datetime import datetime

from pydantic import BaseModel


class WaypointCreate(BaseModel):
    name: str
    type: str = "waypoint"  # waypoint | stop | checkpoint | technical_stop
    lat: float
    lon: float
    hold_duration_min: int = 0
    halt_purpose: str | None = None  # fuel | rest | maintenance | other
    notes: str | None = None
    order_index: int = 0
    # Ein von der Anwendung *vorgeschlagener* Halt (Technischer Halt,
    # Tankstopp): `order_index` ist nur ein Anhängen ans Listenende, die
    # nächste Routenberechnung ordnet ihn entlang der Route ein. Wer einen
    # Wegpunkt selbst setzt, lässt das Feld weg.
    pending_placement: bool = False


class WaypointUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    lat: float | None = None
    lon: float | None = None
    planned_arrival: datetime | None = None
    planned_departure: datetime | None = None
    hold_duration_min: int | None = None
    halt_purpose: str | None = None
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
    halt_purpose: str | None = None
    notes: str | None
    order_index: int
    pending_placement: bool = False

    model_config = {"from_attributes": True}


class WaypointReorderItem(BaseModel):
    id: uuid.UUID
    order_index: int
