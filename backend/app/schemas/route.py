import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class FuelStopPosition(BaseModel):
    lat: float
    lon: float


class VehicleRangeInfo(BaseModel):
    name: str
    callsign: str | None
    range_km: float
    using_defaults: bool = False
    propulsion: str = "combustion"


class DurationHalt(BaseModel):
    stop_km: float
    stop_position: FuelStopPosition | None
    duration_min: int
    is_rest: bool = False


class FuelAnalysis(BaseModel):
    vehicles_with_range: list[VehicleRangeInfo]
    min_range_km: float | None
    route_distance_km: float
    fuel_stop_needed: bool
    fuel_stop_km: float | None
    fuel_stop_position: FuelStopPosition | None
    limiting_vehicle: str | None
    limiting_propulsion: str = "combustion"
    has_default_values: bool = False
    vehicles_without_data: int = 0
    recommended_stop_duration_min: int | None = None
    duration_halt_needed: bool = False
    duration_halts: list[DurationHalt] = []
    rest_needed: bool = False


class KanalwechselEntry(BaseModel):
    km: float
    lat: float
    lon: float
    leitstelle_id: str
    leitstelle_name: str
    anrufgruppe: str
    # Weitere hinterlegte Funkgruppen der Leitstelle:
    # [{"name": "Führungskanal", "kanal": "469"}, …]
    zusatz_kanaele: list[dict] = []
    # "convoy_anmeldung" = Anmeldung des Verbands bei der Start-Leitstelle,
    # "anmelden" = Wechsel zur neuen Leitstelle, "abmelden" = Abmeldung bei
    # der alten. Default für Routen, die vor Einführung des Feldes berechnet
    # wurden.
    typ: Literal["anmelden", "abmelden", "convoy_anmeldung"] = "anmelden"


class RouteResponse(BaseModel):
    id: uuid.UUID
    convoy_id: uuid.UUID
    distance_m: int | None
    duration_s: int | None
    routing_params: dict[str, Any] | None
    geojson: dict | None = None
    fuel_analysis: FuelAnalysis | None = None
    kanalwechsel: list[KanalwechselEntry] = []
    # Abmarschzeit und geplante Ankunft am Ziel. Beide werden auf derselben
    # Zeitbasis wie die Wegpunkt-Zeiten berechnet, damit der Zeitplan konsistent
    # dargestellt wird. planned_arrival = Abmarsch + Fahrzeit + alle Haltezeiten.
    planned_departure: datetime | None = None
    planned_arrival: datetime | None = None

    model_config = {"from_attributes": True}
