import uuid

from pydantic import BaseModel, model_validator


class VehicleCreate(BaseModel):
    name: str
    callsign: str | None = None
    license_plate: str | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    length_cm: int | None = None
    convoy_role: str | None = None
    tank_capacity_l: float | None = None
    fuel_consumption_l100km: float | None = None
    current_fuel_l: float | None = None


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
    tank_capacity_l: float | None = None
    fuel_consumption_l100km: float | None = None
    current_fuel_l: float | None = None
    range_km: float | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_range(self) -> "VehicleResponse":
        fuel = self.current_fuel_l
        cons = self.fuel_consumption_l100km
        if fuel and cons and cons > 0:
            self.range_km = round((fuel / cons) * 100, 1)
        elif self.tank_capacity_l and cons and cons > 0:
            self.range_km = round((self.tank_capacity_l / cons) * 100, 1)
        return self
