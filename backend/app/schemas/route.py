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
    # tech = Technischer Halt (WOLKE), break = Lenkzeitunterbrechung,
    # daily_rest = Tagesruhezeit
    kind: Literal["tech", "break", "daily_rest"] = "tech"
    # Rückwärtskompatibel: True für Lenkpause und Tagesruhezeit
    is_rest: bool = False
    # Kumulierte Lenkzeit bis zu diesem Halt
    after_drive_s: int = 0
    # Halt erfüllt (auch) die Lenkzeitunterbrechung
    covers_break: bool = False


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


class DurchfahrtshoeheEntry(BaseModel):
    km: float
    # Meter ab Start; fehlt bei Routen, die vor Migration 0056 berechnet wurden.
    m: int | None = None
    lat: float
    lon: float
    laenge_m: int
    # Angeschriebene Höhe aus OSM, im Graphen auf 0,1 m gerundet.
    hoehe_m: float
    # Höhe minus höchstes Fahrzeug; None ohne erfasste Fahrzeughöhe.
    spielraum_m: float | None = None
    stufe: Literal["eng", "knapp", "frei", "unbekannt"]


class GewichtsgrenzeEntry(BaseModel):
    km: float
    m: int
    lat: float
    lon: float
    laenge_m: int
    # Grenze aus OSM (maxweight, auch Lkw-Verbote), auf 0,1 t gerundet.
    grenze_t: float
    # Grenze minus schwerstes Fahrzeug; None ohne erfasstes Fahrzeuggewicht.
    reserve_t: float | None = None
    # "destination" (Anlieger frei), "delivery", "forestry" oder None.
    ausnahme: str | None = None
    stufe: Literal["ueberschritten", "knapp", "frei", "unbekannt"]
    # "gewicht" (Gesamtgewicht, maxweight) oder "achslast" (maxaxleload).
    art: Literal["gewicht", "achslast"] = "gewicht"


class BrueckeEntry(BaseModel):
    km: float
    m: int
    lat: float
    lon: float
    # Eisenbahnbrücke, Straßenbrücke, Fuß-/Radwegbrücke … — bei mehreren
    # Wegen an einer Stelle mit " / " verbunden.
    art: str
    name: str | None = None
    osm_ids: list[int] = []
    # Liegt auf Autobahn oder Kraftfahrstraße — dort gezählt, nicht gelistet.
    schnellstrasse: bool = False


class BrueckenPruefung(BaseModel):
    geprueft_at: datetime
    eintraege: list[BrueckeEntry] = []


class RouteResponse(BaseModel):
    id: uuid.UUID
    convoy_id: uuid.UUID
    distance_m: int | None
    duration_s: int | None
    routing_params: dict[str, Any] | None
    geojson: dict | None = None
    fuel_analysis: FuelAnalysis | None = None
    kanalwechsel: list[KanalwechselEntry] = []
    # None = nicht ermittelt (alte oder importierte Route), [] = keine bekannte
    # Höhenbeschränkung auf der Strecke.
    durchfahrtshoehen: list[DurchfahrtshoeheEntry] | None = None
    # None = noch nicht gesucht (POST …/route/bruecken)
    bruecken: BrueckenPruefung | None = None
    # None = nicht ermittelt, [] = keine bekannte Gewichtsgrenze.
    gewichtsgrenzen: list[GewichtsgrenzeEntry] | None = None
    # Abmarschzeit und geplante Ankunft am Ziel. Beide werden auf derselben
    # Zeitbasis wie die Wegpunkt-Zeiten berechnet, damit der Zeitplan konsistent
    # dargestellt wird. planned_arrival = Abmarsch + Fahrzeit + alle Haltezeiten.
    planned_departure: datetime | None = None
    planned_arrival: datetime | None = None

    model_config = {"from_attributes": True}
