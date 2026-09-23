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
    # Der laufende Alarm (Techn. Halt, Ausfall) — sein Beginn, derselbe Wert wie
    # ``ts`` im ``alert`` —, und ob die Führung ihn quittiert hat. Damit sieht
    # auch ein Gerät, das erst nach dem Alarm verbindet, beides.
    alarm_ts: datetime | None = None
    alarm_quittiert_at: datetime | None = None
    alarm_quittiert_von: str | None = None
    # Kraftstoff-Stammdaten aus der Planung — das „Soll" zur Meldung darunter,
    # wie die Sollstärke zur gemeldeten. Die App belegt damit vor, sodass die
    # Besatzung unterwegs nur noch den Füllstand einstellt.
    propulsion: str = "combustion"
    tank_capacity_l: float | None = None
    fuel_consumption_l100km: float | None = None
    # Dasselbe für ein E-Fahrzeug, in kWh. Eigene Felder statt der Literfelder:
    # Die Planung führt beides getrennt, und eine Ansicht, die nur Liter kennt,
    # darf eine Akkukapazität nie als Tank lesen. Gemeldet wird beim
    # E-Fahrzeug nur der Ladestand in Prozent — Kapazität und Verbrauch stehen
    # hier, damit die Reichweite daraus gerechnet werden kann.
    battery_capacity_kwh: float | None = None
    consumption_kwh_100km: float | None = None
    # Betriebsstofflage aus der Meldung unterwegs — None heißt „nicht gemeldet".
    betriebsstoff_verbrauch: float | None = None
    betriebsstoff_tank: int | None = None
    betriebsstoff_fuellstand: int | None = None
    betriebsstoff_gemeldet_at: datetime | None = None


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


class RouteStep(BaseModel):
    """Ein Fahrhinweis, auf die Linie gelegt (services/route_steps.py)."""

    # Meter ab Start entlang der ausgelieferten `geojson`-Linie (Haversine über
    # die Stützpunkte) — derselbe Massstab, mit dem die Companion-App den
    # eigenen Standort projiziert.
    m: float
    # GraphHopper-Vorzeichen: -3…3 abbiegen, 0 geradeaus, 4 Ziel,
    # 5 Zwischenziel, 6 Kreisverkehr, ±7 halten, ±8/-98 wenden.
    sign: int
    text: str | None = None
    street_name: str | None = None
    exit_number: int | None = None


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
    # Abbiegehinweise für die Fahrt, nach `m` aufsteigend. Leer bei importierten
    # Routen — GPX kennt keine Hinweise.
    route_steps: list[RouteStep] = []
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
