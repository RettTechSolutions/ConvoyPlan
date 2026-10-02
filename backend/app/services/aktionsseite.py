"""Was eine öffentliche Aktionsseite zeigen darf — und was nicht.

Die Aktionsseite zeigt Konvois einer Organisation öffentlich: zum Teilen, für
die Presse, für einen Bildschirm bei einer Veranstaltung. Drei Regeln machen
das vertretbar, und alle drei gelten **hier**, nicht im Browser und nicht in
der Anwendung, die die Seite ausliefert (Convoyplan-EventTracker):

1. **Verzögert.** Ausgeliefert wird nur, was mindestens ``delay_minutes`` alt
   ist (Untergrenze 60, auch in der Datenbank erzwungen). Ein Filter beim
   Empfänger wäre einer, den jeder mit den Entwicklertools aushebelt — und die
   Echtzeitposition eines beladenen Lkw ist genau das, was nicht hinaus soll.
2. **Vergröbert, sobald der Konvoi steht.** Die Verzögerung schützt einen
   fahrenden Konvoi. Einen parkenden nicht: Steht er um 20 Uhr auf einem
   Autohof, zeigte die Seite ab 22 Uhr den Parkplatz metergenau, die ganze
   Nacht. Steht er also zum verzögerten Zeitpunkt, wird die Position auf ein
   Raster von rund zehn Kilometern gelegt und die gefahrene Linie endet
   entsprechend davor. Ohne Daten gilt er als stehend — im Zweifel grob.
3. **Nur, was ausdrücklich freigegeben ist.** Ein Punkt je Konvoi, keine
   Fahrzeuge, Rufnamen, Telefonnummern, Stärken, Betriebsstoffe oder Alarme,
   kein interner Konvoiname, keine Kennung aus der Datenbank. Die Liste steht
   als Schema in ``api/routes/aktionsseite.py`` und wird von
   ``tests/test_aktionsseite_felder.py`` festgehalten.

Die Entscheidungen sind reine Funktionen ohne Datenbank und Uhr;
``nutzlast`` setzt sie mit den Daten zusammen.
"""
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from shapely.geometry import LineString
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Ob der Konvoi zur Stichzeit steht.

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


def vergroebern(lat: float, lon: float) -> tuple[float, float]:
    """Auf die Mitte einer Rasterzelle legen.

    Fest gerastert statt verrauscht: Ein Zufallsversatz ließe sich über viele
    Abrufe herausmitteln, eine feste Zelle nicht."""
    zlat = (math.floor(lat / RASTER_GRAD) + 0.5) * RASTER_GRAD
    schritt_lon = RASTER_GRAD / max(math.cos(math.radians(zlat)), 0.2)
    zlon = (math.floor(lon / schritt_lon) + 0.5) * schritt_lon
    return round(zlat, 4), round(zlon, 4)


def linie(punkte: list[Punkt], haelt: bool) -> list[list[float]]:
    """Gefahrene Strecke als [lon, lat]-Liste, vereinfacht.

    Steht der Konvoi, endet sie ``LINIE_ABSTAND_ZUM_HALT_M`` vor dem Halt."""
    if haelt and punkte:
        halt = punkte[-1]
        ende = len(punkte)
        while ende and abstand_m(
            punkte[ende - 1].lat, punkte[ende - 1].lon, halt.lat, halt.lon
        ) < LINIE_ABSTAND_ZUM_HALT_M:
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
) -> dict:
    """Öffentlicher Stand eines Konvois (ohne Namen, die setzt der Aufrufer)."""
    v = vertreter(kandidaten)
    punkte = v.punkte if v else []
    if not punkte:
        return {"status": "vor_abfahrt", "position": None, "trail": [], "driven_km": 0.0}
    haelt = steht(punkte, stich)
    letzter = punkte[-1]
    angekommen = ziel is not None and abstand_m(letzter.lat, letzter.lon, *ziel) <= ANKUNFT_RADIUS_M
    if haelt:
        lat, lon = vergroebern(letzter.lat, letzter.lon)
    else:
        lat, lon = round(letzter.lat, 5), round(letzter.lon, 5)
    return {
        "status": "angekommen" if angekommen else ("pause" if haelt else "unterwegs"),
        "position": {"lat": lat, "lon": lon, "coarse": haelt, "at": letzter.t},
        "trail": linie(punkte, haelt),
        "driven_km": strecke_km(punkte),
    }


# ── Zusammensetzen ────────────────────────────────────────────────────────


def ist_aktiv(tracker: PublicTracker, jetzt: datetime) -> bool:
    return tracker.enabled and (tracker.valid_until is None or tracker.valid_until > jetzt)


async def _kandidaten(
    db: AsyncSession, convoy_id: uuid.UUID, stich: datetime
) -> list[Kandidat]:
    fahrzeuge = (
        await db.execute(select(ConvoyVehicle).where(ConvoyVehicle.convoy_id == convoy_id))
    ).scalars().all()
    zeilen = (
        await db.execute(
            select(VehiclePositionTrail)
            .where(
                VehiclePositionTrail.convoy_id == convoy_id,
                VehiclePositionTrail.recorded_at <= stich,
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
            punkte=bis(je_fahrzeug.get(cv.vehicle_id, []), stich),
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


async def nutzlast(db: AsyncSession, tracker: PublicTracker, jetzt: datetime | None = None) -> dict:
    """Die öffentliche Antwort einer Aktionsseite."""
    jetzt = jetzt or datetime.now(timezone.utc)
    stich = stichzeit(jetzt, tracker.delay_minutes)
    konvois = []
    for nr, tc in enumerate(tracker.convoys, start=1):
        ziel = await _ziel(db, tc.convoy_id)
        stand = konvoi(await _kandidaten(db, tc.convoy_id, stich), stich, ziel)
        route = (
            await db.execute(select(Route.distance_m).where(Route.convoy_id == tc.convoy_id))
        ).scalar_one_or_none()
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
                "total_km": round(route / 1000, 1) if route else None,
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
