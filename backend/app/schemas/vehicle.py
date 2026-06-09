import uuid

from pydantic import BaseModel, Field, model_validator


class VehicleCreate(BaseModel):
    name: str
    callsign: str | None = None
    license_plate: str | None = None
    height_cm: int | None = Field(default=None, ge=0, le=1000)
    weight_kg: int | None = Field(default=None, ge=0, le=100_000)
    length_cm: int | None = Field(default=None, ge=0, le=5000)
    convoy_role: str | None = None
    tank_capacity_l: float | None = None
    fuel_consumption_l100km: float | None = None
    current_fuel_l: float | None = None


class VehicleUpdate(VehicleCreate):
    name: str | None = None


DEFAULT_CONSUMPTION = 7.5
DEFAULT_TANK = 70.0


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
    order_index: int = 0
    range_km: float | None = None
    range_uses_defaults: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_range(self) -> "VehicleResponse":
        fuel = self.current_fuel_l
        cons = self.fuel_consumption_l100km
        cap = self.tank_capacity_l
        has_real_data = bool(cons and cons > 0 and (fuel or cap))
        eff_fuel = fuel if fuel else (cap if cap else DEFAULT_TANK)
        eff_cons = cons if (cons and cons > 0) else DEFAULT_CONSUMPTION
        self.range_km = round((eff_fuel / eff_cons) * 100, 1)
        self.range_uses_defaults = not has_real_data
        return self
