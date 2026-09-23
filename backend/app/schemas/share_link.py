import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.route import KanalwechselEntry


class ShareLinkCreate(BaseModel):
    password_mode: Literal["none", "generate", "set"]
    password: str | None = None
    # "track" = read-only viewer link; "driver" = link holder may also pick a
    # vehicle and send its GPS position / status without logging in.
    scope: Literal["track", "driver"] = "track"

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
    # Mannschaftsstärke: Soll aus der Planung, Ist aus der Meldung unterwegs.
    # None bleibt None — die Ansicht muss „nicht gemeldet" anzeigen können.
    staerke_soll_fuehrer: int | None = None
    staerke_soll_unterfuehrer: int | None = None
    staerke_soll_mannschaften: int | None = None
    staerke_ist_fuehrer: int | None = None
    staerke_ist_unterfuehrer: int | None = None
    staerke_ist_mannschaften: int | None = None
    # Betriebsstoff aus den Stammdaten — ein eingetragener Wert, kein Messwert;
    # er sinkt unterwegs nicht. Belegt ist nur der Satz der eigenen Antriebsart,
    # der andere bleibt None (wie in der MCP-Antwort, ``tools_read.py``).
    propulsion: str | None = None
    tank_capacity_l: float | None = None
    current_fuel_l: float | None = None
    fuel_consumption_l100km: float | None = None
    battery_capacity_kwh: float | None = None
    current_charge_kwh: float | None = None
    consumption_kwh_100km: float | None = None
    # Was die Besatzung unterwegs meldet, in Prozent — Tank oder Akku, je nach
    # propulsion. None heißt "nicht gemeldet"; dann gilt der eingetragene Stand.
    fuellstand_ist_prozent: int | None = None
    fuellstand_gemeldet_at: datetime | None = None


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
    # "track" (viewer) or "driver" (may send GPS / status).
    scope: str = "track"
    waypoints: list[TrackWaypoint]
    geojson: dict | None = None
    # Routenlänge & Leitstellen-Übergabepunkte, damit die Tracking-Ansicht
    # Wegpunkte/Kanalwechsel anhand der Konvoi-Position ankündigen kann.
    distance_m: int | None = None
    kanalwechsel: list[KanalwechselEntry] = []
    vehicles: list[TrackVehicle]
    positions: list[TrackPosition]


class TrackGate(BaseModel):
    requires_password: bool
    convoy_name: str
    # Rolle des Links ("track" = nur lesend, "driver" = darf Position/Status
    # senden). Steht schon vor der Passworteingabe zur Verfügung, damit ein
    # Client die Anmeldemaske passend beschriften kann. Keine
    # Sicherheitsauswirkung: durchgesetzt wird der Scope serverseitig.
    scope: str = "track"
