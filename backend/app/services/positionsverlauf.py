"""Positionsverlauf für die öffentliche Aktionsseite.

``vehicle_positions`` hält nur die letzte Position je Fahrzeug. Für eine
verzögerte Anzeige braucht es die Frage „wo war das Fahrzeug vor zwei
Stunden" — also einen Verlauf. Den gibt es **nur für Konvois an einer
aktiven Aktionsseite**: ein Bewegungsprofil jedes Einsatzes hat niemand
bestellt, und die Fahrer haben ihm nicht zugestimmt.

Ausgedünnt wird beim Schreiben (``noetig``): höchstens ein Punkt pro Minute,
und ein stehendes Fahrzeug nur alle fünf Minuten. Bei 30 Fahrzeugen über vier
Tage sind das grob 100 000 Zeilen.

``aufzeichnen`` wird an **jeder** Stelle aufgerufen, die ``VehiclePosition``
schreibt — heute drei: Fahrer-Link (``track.py``), REST und WebSocket der
angemeldeten Ansicht (``tracking.py``). ``tests/test_positionsverlauf.py``
prüft das am Quelltext; eine vierte Schreibstelle ohne Aufruf fällt dort auf.
"""
import math
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.public_tracker import PublicTracker, PublicTrackerConvoy, VehiclePositionTrail

MIN_ABSTAND_S = 60
STEHEND_ABSTAND_S = 300
BEWEGT_AB_M = 100

# Welche Konvois aufgezeichnet werden, ändert sich selten; die Frage kommt
# dagegen mit jeder Position. Eine Minute veraltet ist harmlos: der erste Punkt
# nach dem Anlegen einer Seite fehlt dann eben.
_AKTIV_TTL_S = 60.0
# Ein Behälter statt einer neu gebundenen Modulvariablen: kein ``global``, und
# ``vergessen`` leert denselben Speicher, den ``aktive_konvois`` liest.
_aktiv: dict[str, tuple[frozenset[uuid.UUID], float]] = {}


def abstand_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Großkreisabstand in Metern."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def noetig(
    letzter: tuple[datetime, float, float] | None,
    jetzt: datetime,
    lat: float,
    lon: float,
) -> bool:
    """Ob ein neuer Punkt in den Verlauf gehört."""
    if letzter is None:
        return True
    t, llat, llon = letzter
    vergangen = (jetzt - t).total_seconds()
    if vergangen < MIN_ABSTAND_S:
        return False
    if vergangen >= STEHEND_ABSTAND_S:
        return True
    return abstand_m(llat, llon, lat, lon) >= BEWEGT_AB_M


def vergessen() -> None:
    """Zwischenspeicher leeren — nach Anlegen, Ändern oder Löschen einer Seite."""
    _aktiv.clear()


async def aktive_konvois(db: AsyncSession, jetzt: datetime) -> frozenset[uuid.UUID]:
    cached = _aktiv.get("konvois")
    if cached is not None and time.monotonic() - cached[1] < _AKTIV_TTL_S:
        return cached[0]
    rows = await db.execute(
        select(PublicTrackerConvoy.convoy_id)
        .join(PublicTracker, PublicTracker.id == PublicTrackerConvoy.tracker_id)
        .where(
            PublicTracker.enabled.is_(True),
            or_(PublicTracker.valid_until.is_(None), PublicTracker.valid_until > jetzt),
        )
    )
    ids = frozenset(rows.scalars().all())
    _aktiv["konvois"] = (ids, time.monotonic())
    return ids


async def aufzeichnen(
    db: AsyncSession,
    convoy_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    lat: float,
    lon: float,
    jetzt: datetime | None = None,
) -> bool:
    """Punkt in den Verlauf legen, falls der Konvoi an einer aktiven Seite
    hängt und der Punkt nicht zu dicht am vorigen liegt. Committet nicht —
    das tut der Aufrufer zusammen mit der Live-Position."""
    jetzt = jetzt or datetime.now(timezone.utc)
    if convoy_id not in await aktive_konvois(db, jetzt):
        return False
    letzter = (
        await db.execute(
            select(
                VehiclePositionTrail.recorded_at,
                VehiclePositionTrail.lat,
                VehiclePositionTrail.lon,
            )
            .where(
                VehiclePositionTrail.convoy_id == convoy_id,
                VehiclePositionTrail.vehicle_id == vehicle_id,
            )
            .order_by(VehiclePositionTrail.recorded_at.desc())
            .limit(1)
        )
    ).first()
    if not noetig(tuple(letzter) if letzter else None, jetzt, lat, lon):
        return False
    await db.execute(
        pg_insert(VehiclePositionTrail)
        .values(convoy_id=convoy_id, vehicle_id=vehicle_id, recorded_at=jetzt, lat=lat, lon=lon)
        .on_conflict_do_nothing()
    )
    return True
