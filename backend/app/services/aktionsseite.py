"""Was eine öffentliche Aktionsseite zeigen darf — und was nicht.

Die Aktionsseite zeigt Konvois einer Organisation öffentlich: zum Teilen, für
die Presse, für einen Bildschirm bei einer Veranstaltung. Drei Regeln machen
das vertretbar, und alle drei gelten **hier**, nicht im Browser und nicht in
der Anwendung, die die Seite ausliefert (Convoyplan-EventTracker):

1. **Verzögert.** Ausgeliefert wird nur, was mindestens ``delay_minutes`` alt
   ist (Untergrenze 60, auch in der Datenbank erzwungen). Ein Filter beim
   Empfänger wäre einer, den jeder mit den Entwicklertools aushebelt — und die
   Echtzeitposition eines beladenen Lkw ist genau das, was nicht hinaus soll.
2. **Geparkt, sobald der Konvoi steht.** Die Verzögerung schützt einen
   fahrenden Konvoi. Einen parkenden nicht: Steht er um 20 Uhr auf einem
   Autohof, zeigte die Seite ab 22 Uhr den Parkplatz metergenau, die ganze
   Nacht. Steht er also zum verzögerten Zeitpunkt, erscheint er an einer
   Stelle seiner Route 10 bis 25 km vor oder hinter dem Halt, und die
   gefahrene Linie endet davor. Schon auf dem Weg dorthin und noch eine
   Strecke danach gilt er als haltend — die Verzögerung lässt dafür in die
   Zukunft schauen. Sonst verriete die letzte genaue Position vor der Pause
   oder die erste danach den Halt. Ohne Route bleibt es beim groben Raster;
   ohne Daten gilt er als stehend — im Zweifel grob.
3. **Nur, was ausdrücklich freigegeben ist.** Ein Punkt je Konvoi, keine
   Fahrzeuge, Rufnamen, Telefonnummern, Stärken, Betriebsstoffe oder Alarme,
   kein interner Konvoiname, keine Kennung aus der Datenbank. Die Liste steht
   als Schema in ``api/routes/aktionsseite.py`` und wird von
   ``tests/test_aktionsseite_felder.py`` festgehalten.

Die Entscheidungen sind reine Funktionen ohne Datenbank und Uhr;
``nutzlast`` setzt sie mit den Daten zusammen.
"""
import hashlib
import hmac
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from geoalchemy2.shape import to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.convoy import ConvoyVehicle
from app.models.public_tracker import PublicTracker, VehiclePositionTrail
from app.models.route import Route
from app.models.waypoint import Waypoint
from app.services import geometry as geo_svc
from app.services.positionsverlauf import abstand_m

MIN_VERZOEGERUNG_MIN = 60
MAX_VERZOEGERUNG_MIN = 360

# Ab wann ein Konvoi als stehend gilt: so lange innerhalb des Radius.
STEHEN_AB = timedelta(minutes=20)
STEHEN_RADIUS_M = 300.0
# Rasterweite der Vergröberung in Breitengrad (0,1° ≈ 11 km).
RASTER_GRAD = 0.1
# Die Linie endet so weit vor einem Halt, dass sie ihn nicht verrät.
LINIE_ABSTAND_ZUM_HALT_M = 10_000.0
# Ziel erreicht, wenn der Konvoi so nah am letzten Wegpunkt ist.
ANKUNFT_RADIUS_M = 3_000.0
# Das Spitzenfahrzeug vertritt den Konvoi, solange seine letzte Position nicht
# deutlich älter ist als die frischeste im Konvoi.
SPITZE_TOLERANZ = timedelta(minutes=15)
# Wie weit zurück die Linie reicht. Eine Fahrt dauert Tage, nicht Wochen.
VERLAUF_FENSTER = timedelta(days=14)
# Douglas-Peucker in Grad (~50 m) — genug für eine Übersichtskarte.
LINIE_TOLERANZ_GRAD = 0.0005
# Wo ein haltender Konvoi erscheint: so weit vor oder hinter dem Halt, auf
# seiner Route. Fest je Halt, nicht je Abruf — ein Versatz, der sich ändert,
# ließe sich herausmitteln.
PARKEN_MIN_M = 10_000.0
PARKEN_MAX_M = 25_000.0
# Schutzbereich um einen Halt: Wer darin ist, gilt als haltend — auf der
# Anfahrt schon, nach der Abfahrt noch. Der Radius ist je Halt und Richtung
# ein anderer, sonst läge der Halt genau einen bekannten Abstand hinter der
# ersten genauen Position nach der Pause.
SCHUTZ_MIN_M = 12_000.0
SCHUTZ_MAX_M = 30_000.0


@dataclass(frozen=True)
class Punkt:
    t: datetime
    lat: float
    lon: float


@dataclass
class Kandidat:
    """Ein Fahrzeug des Konvois mit seinem Verlauf bis zur Stichzeit."""

    spitze: bool
    reihenfolge: int
    punkte: list[Punkt] = field(default_factory=list)


def stichzeit(jetzt: datetime, verzoegerung_min: int) -> datetime:
    """Der Zeitpunkt, bis zu dem die Seite Daten zeigt."""
    return jetzt - timedelta(minutes=max(verzoegerung_min, MIN_VERZOEGERUNG_MIN))


def bis(punkte: list[Punkt], stich: datetime) -> list[Punkt]:
    """Nur Punkte bis zur Stichzeit, zeitlich sortiert."""
    return sorted((p for p in punkte if p.t <= stich), key=lambda p: p.t)


def vertreter(kandidaten: list[Kandidat]) -> Kandidat | None:
    """Das Fahrzeug, das den Konvoi auf der Karte vertritt.

    Das Spitzenfahrzeug, solange es frisch meldet; fällt es aus, das mit der
    frischesten Position, damit die Seite nicht stehen bleibt."""
    mit_daten = [k for k in kandidaten if k.punkte]
    if not mit_daten:
        return None
    frischeste = max(k.punkte[-1].t for k in mit_daten)
    spitzen = [
        k for k in mit_daten if k.spitze and frischeste - k.punkte[-1].t <= SPITZE_TOLERANZ
    ]
    if spitzen:
        return min(spitzen, key=lambda k: k.reihenfolge)
    return max(mit_daten, key=lambda k: (k.punkte[-1].t, -k.reihenfolge))


def steht(punkte: list[Punkt], stich: datetime) -> bool:
    """Ob der Konvoi zur Stichzeit steht — allein aus dem, was bis dahin war.

    Ohne Daten seit ``STEHEN_AB`` gilt er als stehend: Ein Handy, das nichts
    mehr sendet, liegt oft in einem geparkten Fahrzeug."""
    if not punkte:
        return True
    letzter = punkte[-1]
    if stich - letzter.t >= STEHEN_AB:
        return True
    seit = letzter.t
    for p in reversed(punkte):
        if abstand_m(p.lat, p.lon, letzter.lat, letzter.lon) > STEHEN_RADIUS_M:
            break
        seit = p.t
    return stich - seit >= STEHEN_AB


@dataclass(frozen=True)
class Halt:
    """Ein Halt im Verlauf: Punkte ``anfang`` bis ``ende`` am selben Ort."""

    anfang: int
    ende: int
    lat: float
    lon: float


def halte(punkte: list[Punkt], datenende: datetime) -> list[Halt]:
    """Alle Halte im Verlauf.

    Ein Halt sind ``STEHEN_AB`` im Umkreis von ``STEHEN_RADIUS_M`` — oder eine
    Funkstille von mindestens ``STEHEN_AB``, auch am Ende bis ``datenende``."""
    gefunden = []
    i = 0
    while i < len(punkte):
        a = punkte[i]
        j = i
        while (
            j + 1 < len(punkte)
            and abstand_m(punkte[j + 1].lat, punkte[j + 1].lon, a.lat, a.lon) <= STEHEN_RADIUS_M
        ):
            j += 1
        still = (punkte[j + 1].t if j + 1 < len(punkte) else datenende) - punkte[j].t
        if punkte[j].t - a.t >= STEHEN_AB or still >= STEHEN_AB:
            gefunden.append(Halt(i, j, a.lat, a.lon))
        i = j + 1
    return gefunden


def _zufall(schluessel: bytes, halt_t: datetime) -> tuple[float, float, float, float]:
    """Vier feste Zahlen in [0, 1) je Halt: geheim, aber bei jedem Abruf gleich."""
    d = hmac.new(schluessel, halt_t.isoformat().encode(), hashlib.sha256).digest()
    return tuple(int.from_bytes(d[k : k + 4], "big") / 2**32 for k in (0, 4, 8, 12))


def schutzbereich(
    punkte: list[Punkt], halt: Halt, schluessel: bytes
) -> tuple[datetime, datetime | None]:
    """Von wann bis wann der Konvoi wegen dieses Halts als haltend gilt.

    Ab dem ersten Punkt im Anfahrtsradius bis vor den ersten außerhalb des
    Abfahrtsradius; ``None``, solange er den noch nicht verlassen hat."""
    _, _, u_an, u_ab = _zufall(schluessel, punkte[halt.anfang].t)
    r_an = SCHUTZ_MIN_M + u_an * (SCHUTZ_MAX_M - SCHUTZ_MIN_M)
    r_ab = SCHUTZ_MIN_M + u_ab * (SCHUTZ_MAX_M - SCHUTZ_MIN_M)
    von = halt.anfang
    while von > 0 and abstand_m(punkte[von - 1].lat, punkte[von - 1].lon, halt.lat, halt.lon) < r_an:
        von -= 1
    bis_ = halt.ende + 1
    while bis_ < len(punkte) and abstand_m(punkte[bis_].lat, punkte[bis_].lon, halt.lat, halt.lon) < r_ab:
        bis_ += 1
    return punkte[von].t, (punkte[bis_].t if bis_ < len(punkte) else None)


# ── Route ──────────────────────────────────────────────────────────────────

_M_JE_GRAD = 111_320.0


@dataclass(frozen=True)
class Strecke:
    """Die geplante Route in einer ebenen Näherung (Meter), zum Messen entlang.

    Ein Maßstab für die ganze Route: Auf 1 500 km Nord-Süd sind das ein paar
    Prozent Fehler — für einen absichtlich ungenauen Parkplatz egal."""

    linie: LineString
    kos: float

    def meter(self, lat: float, lon: float) -> Point:
        return Point(lon * _M_JE_GRAD * self.kos, lat * _M_JE_GRAD)

    def entlang(self, lat: float, lon: float) -> float:
        return self.linie.project(self.meter(lat, lon))

    def bei(self, m: float) -> tuple[float, float]:
        p = self.linie.interpolate(max(0.0, min(m, self.linie.length)))
        return p.y / _M_JE_GRAD, p.x / (_M_JE_GRAD * self.kos)


def strecke(koordinaten: list[tuple[float, float]]) -> Strecke | None:
    """Aus [lon, lat]-Paaren; ``None`` ohne brauchbare Route."""
    if len(koordinaten) < 2:
        return None
    lats = [lat for _, lat in koordinaten]
    kos = max(math.cos(math.radians((min(lats) + max(lats)) / 2)), 0.2)
    linie = LineString([(lon * _M_JE_GRAD * kos, lat * _M_JE_GRAD) for lon, lat in koordinaten])
    return Strecke(linie, kos) if linie.length > 0 else None


def parkplatz(
    halt_lat: float, halt_lon: float, route: Strecke | None, u_weit: float, u_richtung: float
) -> tuple[float, float, float]:
    """Wo der haltende Konvoi erscheint, und wie weit das entlang der Route
    vom Halt weg ist (Meter, vorwärts positiv).

    Ohne Route die Mitte der Rasterzelle. Läge der Platz hinter dem Anfang
    oder dem Ende der Route, geht es in die andere Richtung."""
    if route is None:
        lat, lon = vergroebern(halt_lat, halt_lon)
        return lat, lon, 0.0
    s_halt = route.entlang(halt_lat, halt_lon)
    weit = PARKEN_MIN_M + u_weit * (PARKEN_MAX_M - PARKEN_MIN_M)
    versatz = weit if u_richtung < 0.5 else -weit
    if not 0 <= s_halt + versatz <= route.linie.length:
        versatz = -versatz
    s = max(0.0, min(s_halt + versatz, route.linie.length))
    lat, lon = route.bei(s)
    return round(lat, 4), round(lon, 4), s - s_halt


def vergroebern(lat: float, lon: float) -> tuple[float, float]:
    """Auf die Mitte einer Rasterzelle legen.

    Fest gerastert statt verrauscht: Ein Zufallsversatz ließe sich über viele
    Abrufe herausmitteln, eine feste Zelle nicht."""
    zlat = (math.floor(lat / RASTER_GRAD) + 0.5) * RASTER_GRAD
    schritt_lon = RASTER_GRAD / max(math.cos(math.radians(zlat)), 0.2)
    zlon = (math.floor(lon / schritt_lon) + 0.5) * schritt_lon
    return round(zlat, 4), round(zlon, 4)


def linie(
    punkte: list[Punkt],
    halt: tuple[float, float] | None,
    meiden: list[tuple[float, float]] = (),
    route: Strecke | None = None,
    route_bis: float | None = None,
) -> list[list[float]]:
    """Gefahrene Strecke als [lon, lat]-Liste, vereinfacht.

    Hält der Konvoi, endet sie ``LINIE_ABSTAND_ZUM_HALT_M`` vor dem Halt und
    vor jedem Punkt aus ``meiden`` (dem Parkplatz) — und, mit Route, vor der
    Stelle ``route_bis`` entlang der Route, damit sie nicht über einen
    Parkplatz hinter dem Halt hinausreicht."""
    if halt is not None and punkte:
        sperren = [halt, *meiden]
        ende = len(punkte)
        while ende and (
            any(
                abstand_m(punkte[ende - 1].lat, punkte[ende - 1].lon, *q) < LINIE_ABSTAND_ZUM_HALT_M
                for q in sperren
            )
            or (
                route is not None
                and route_bis is not None
                and route.entlang(punkte[ende - 1].lat, punkte[ende - 1].lon)
                > route_bis - LINIE_ABSTAND_ZUM_HALT_M
            )
        ):
            ende -= 1
        punkte = punkte[:ende]
    koordinaten = [(p.lon, p.lat) for p in punkte]
    if len(koordinaten) < 2:
        return []
    vereinfacht = LineString(koordinaten).simplify(LINIE_TOLERANZ_GRAD)
    return [[round(x, 5), round(y, 5)] for x, y in vereinfacht.coords]


def strecke_km(punkte: list[Punkt]) -> float:
    gesamt = sum(
        abstand_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(punkte, punkte[1:])
    )
    return round(gesamt / 1000, 1)


def konvoi(
    kandidaten: list[Kandidat],
    stich: datetime,
    ziel: tuple[float, float] | None,
    *,
    jetzt: datetime | None = None,
    route: Strecke | None = None,
    schluessel: bytes = b"",
) -> dict:
    """Öffentlicher Stand eines Konvois (ohne Namen, die setzt der Aufrufer).

    Die Kandidaten dürfen Punkte bis ``jetzt`` tragen. Was danach kam, sagt
    nur, ob der Konvoi zur Stichzeit schon auf einen Halt zufährt; hinaus geht
    davon allein der Parkplatz dieses Halts, nie eine Position in Fahrt."""
    jetzt = jetzt or stich
    gekuerzt = [Kandidat(k.spitze, k.reihenfolge, bis(k.punkte, stich)) for k in kandidaten]
    v = vertreter(gekuerzt)
    if v is None:
        return {"status": "vor_abfahrt", "position": None, "trail": [], "driven_km": 0.0}
    alle = bis(kandidaten[gekuerzt.index(v)].punkte, jetzt)
    punkte = v.punkte
    letzter = punkte[-1]
    angekommen = ziel is not None and abstand_m(letzter.lat, letzter.lon, *ziel) <= ANKUNFT_RADIUS_M

    aktuell = None
    for h in halte(alle, jetzt):
        von, bis_ = schutzbereich(alle, h, schluessel)
        if von <= stich and (bis_ is None or stich < bis_):
            aktuell = h
            break
    # Was der Verlauf bis zur Stichzeit allein sagt, gilt weiter — auch wenn
    # die Punkte danach (noch) keinen Halt ergeben.
    if aktuell is None and steht(punkte, stich):
        aktuell = Halt(len(punkte) - 1, len(punkte) - 1, letzter.lat, letzter.lon)
        alle = punkte

    if aktuell is None:
        return {
            "status": "angekommen" if angekommen else "unterwegs",
            "position": {
                "lat": round(letzter.lat, 5),
                "lon": round(letzter.lon, 5),
                "coarse": False,
                "at": letzter.t,
            },
            "trail": linie(punkte, None),
            "driven_km": strecke_km(punkte),
        }

    u_weit, u_richtung, _, _ = _zufall(schluessel, alle[aktuell.anfang].t)
    if angekommen:
        # Am Ziel kein Versatz die Route zurück: Die Lagerhalle steht nicht
        # auf der Seite, ein Parkplatz 20 km davor wäre aber falsch.
        lat, lon = vergroebern(aktuell.lat, aktuell.lon)
        versatz = 0.0
    else:
        lat, lon, versatz = parkplatz(aktuell.lat, aktuell.lon, route, u_weit, u_richtung)
    s_halt = route.entlang(aktuell.lat, aktuell.lon) if route else None
    gefahren = strecke_km(alle[: aktuell.anfang + 1]) + versatz / 1000
    return {
        "status": "angekommen" if angekommen else "pause",
        "position": {"lat": lat, "lon": lon, "coarse": True, "at": letzter.t},
        # Nur bis zum Halt: Nach der Abfahrt zeigte die Linie sonst die genaue
        # Spitze, während der Konvoi noch als haltend gilt.
        "trail": linie(
            punkte[: aktuell.anfang + 1],
            (aktuell.lat, aktuell.lon),
            [(lat, lon)],
            route,
            None if s_halt is None else s_halt + min(versatz, 0.0),
        ),
        # Ganze Kilometer, passend zum Parkplatz — der genaue Stand verriete
        # mit der Gesamtlänge der Route die Stelle des Halts.
        "driven_km": float(max(round(gefahren), 0)),
    }


# ── Zusammensetzen ────────────────────────────────────────────────────────


def ist_aktiv(tracker: PublicTracker, jetzt: datetime) -> bool:
    return tracker.enabled and (tracker.valid_until is None or tracker.valid_until > jetzt)


async def _kandidaten(
    db: AsyncSession, convoy_id: uuid.UUID, stich: datetime, jetzt: datetime
) -> list[Kandidat]:
    fahrzeuge = (
        await db.execute(select(ConvoyVehicle).where(ConvoyVehicle.convoy_id == convoy_id))
    ).scalars().all()
    zeilen = (
        await db.execute(
            select(VehiclePositionTrail)
            .where(
                VehiclePositionTrail.convoy_id == convoy_id,
                # Bis jetzt, nicht bis zur Stichzeit: Was danach kam, sagt
                # ``konvoi``, ob ein Halt bevorsteht.
                VehiclePositionTrail.recorded_at <= jetzt,
                VehiclePositionTrail.recorded_at >= stich - VERLAUF_FENSTER,
            )
            .order_by(VehiclePositionTrail.recorded_at)
        )
    ).scalars().all()
    je_fahrzeug: dict[uuid.UUID, list[Punkt]] = {}
    for z in zeilen:
        je_fahrzeug.setdefault(z.vehicle_id, []).append(Punkt(z.recorded_at, z.lat, z.lon))
    return [
        Kandidat(
            spitze=cv.sonderfunktion == "spitzenführer",
            reihenfolge=cv.position,
            punkte=bis(je_fahrzeug.get(cv.vehicle_id, []), jetzt),
        )
        for cv in fahrzeuge
    ]


async def _ziel(db: AsyncSession, convoy_id: uuid.UUID) -> tuple[float, float] | None:
    letzter = (
        await db.execute(
            select(Waypoint)
            .where(Waypoint.convoy_id == convoy_id)
            .order_by(Waypoint.order_index.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if letzter is None:
        return None
    c = geo_svc.waypoint_coords(letzter)
    if c["lat"] is None:
        return None
    return c["lat"], c["lon"]


def _strecke(geometrie) -> Strecke | None:
    if geometrie is None:
        return None
    return strecke(list(to_shape(geometrie).coords))


def _schluessel(tracker_id: uuid.UUID, convoy_id: uuid.UUID) -> bytes:
    """Geheim je Seite und Konvoi: Wer den Versatz eines Halts kennt, kennt
    damit weder den nächsten noch den einer anderen Seite."""
    return hmac.new(
        settings.jwt_secret.encode(),
        f"aktionsseite-parken:{tracker_id}:{convoy_id}".encode(),
        hashlib.sha256,
    ).digest()


async def nutzlast(db: AsyncSession, tracker: PublicTracker, jetzt: datetime | None = None) -> dict:
    """Die öffentliche Antwort einer Aktionsseite."""
    jetzt = jetzt or datetime.now(timezone.utc)
    stich = stichzeit(jetzt, tracker.delay_minutes)
    konvois = []
    for nr, tc in enumerate(tracker.convoys, start=1):
        ziel = await _ziel(db, tc.convoy_id)
        route = (
            await db.execute(
                select(Route.distance_m, Route.geometry).where(Route.convoy_id == tc.convoy_id)
            )
        ).one_or_none()
        stand = konvoi(
            await _kandidaten(db, tc.convoy_id, stich, jetzt),
            stich,
            ziel,
            jetzt=jetzt,
            route=_strecke(route.geometry if route else None),
            schluessel=_schluessel(tracker.id, tc.convoy_id),
        )
        ziel_punkt = None
        if tracker.show_destination and ziel is not None:
            zlat, zlon = vergroebern(*ziel)
            ziel_punkt = {"lat": zlat, "lon": zlon}
        konvois.append(
            {
                # Laufende Nummer statt Datenbank-Kennung: die verrät nichts
                # und bleibt stabil, solange die Reihenfolge bleibt.
                "key": str(nr),
                "name": tc.display_name,
                "destination": tc.destination_label,
                "destination_point": ziel_punkt,
                "color": tc.color,
                "total_km": round(route.distance_m / 1000, 1) if route and route.distance_m else None,
                **stand,
            }
        )
    return {
        "title": tracker.title,
        "subtitle": tracker.subtitle,
        "facts": tracker.facts,
        "theme": tracker.theme,
        "delay_minutes": max(tracker.delay_minutes, MIN_VERZOEGERUNG_MIN),
        "as_of": stich,
        "generated_at": jetzt,
        "valid_until": tracker.valid_until,
        "convoys": konvois,
    }
