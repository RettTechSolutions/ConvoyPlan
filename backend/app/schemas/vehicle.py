import uuid

from pydantic import BaseModel


class VehicleCreate(BaseModel):
    name: str
    callsign: str | None = None
    license_plate: str | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    length_cm: int | None = None
    convoy_role: str | None = None


class VehicleUpdate(VehicleCreate):
    name: str | None = None


class VehicleResponse(BaseModel):
    id: uuid.UUID
    name: str
    callsign: str | None
    license_plate: str | None
    height_cm: int | None
    weight_kg: int | None
    length_cm: int | None
    convoy_role: str | None

    model_config = {"from_attributes": True}
