import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class VehicleCreate(BaseModel):
    name: str
    callsign: str | None = None
    license_plate: str | None = None
    height_cm: int | None = Field(default=None, ge=0, le=1000)
    weight_kg: int | None = Field(default=None, ge=0, le=100_000)
    length_cm: int | None = Field(default=None, ge=0, le=5000)
    convoy_role: str | None = None
    propulsion: Literal["combustion", "electric"] = "combustion"
    # Verbrenner
    tank_capacity_l: float | None = None
    fuel_consumption_l100km: float | None = None
    current_fuel_l: float | None = None
    # E-Fahrzeug
    battery_capacity_kwh: float | None = None
    consumption_kwh_100km: float | None = None
    current_charge_kwh: float | None = None


class VehicleUpdate(VehicleCreate):
    name: str | None = None
    propulsion: Literal["combustion", "electric"] | None = None


DEFAULT_CONSUMPTION = 7.5
DEFAULT_TANK = 70.0
# E-Fahrzeug-Standardwerte (mittlerer Verbrauch / mittlere Akkukapazität)
DEFAULT_CONSUMPTION_KWH = 20.0
DEFAULT_BATTERY_KWH = 60.0


class VehicleResponse(BaseModel):
    id: uuid.UUID
    name: str
    callsign: str | None
    license_plate: str | None
    height_cm: int | None
    weight_kg: int | None
    length_cm: int | None
    convoy_role: str | None
    propulsion: str = "combustion"
    tank_capacity_l: float | None = None
    fuel_consumption_l100km: float | None = None
    current_fuel_l: float | None = None
    battery_capacity_kwh: float | None = None
    consumption_kwh_100km: float | None = None
    current_charge_kwh: float | None = None
    order_index: int = 0
    range_km: float | None = None
    range_uses_defaults: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_range(self) -> "VehicleResponse":
        if self.propulsion == "electric":
            charge = self.current_charge_kwh
            cons = self.consumption_kwh_100km
            cap = self.battery_capacity_kwh
            has_real_data = bool(cons and cons > 0 and (charge or cap))
            eff_charge = charge if charge else (cap if cap else DEFAULT_BATTERY_KWH)
            eff_cons = cons if (cons and cons > 0) else DEFAULT_CONSUMPTION_KWH
        else:
            charge = self.current_fuel_l
            cons = self.fuel_consumption_l100km
            cap = self.tank_capacity_l
            has_real_data = bool(cons and cons > 0 and (charge or cap))
            eff_charge = charge if charge else (cap if cap else DEFAULT_TANK)
            eff_cons = cons if (cons and cons > 0) else DEFAULT_CONSUMPTION
        self.range_km = round((eff_charge / eff_cons) * 100, 1)
        self.range_uses_defaults = not has_real_data
        return self
