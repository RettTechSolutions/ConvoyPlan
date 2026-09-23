"""Quittung eines Alarms durch die Führung.

Ein technischer Halt oder ein Ausfall löst bei allen Beteiligten einen Alarm
aus (``alert``). Bisher endete der Weg dort: Ob die Führung ihn gesehen hatte,
erfuhr niemand — die Besatzung im liegengebliebenen Fahrzeug nicht, und ein
zweites Führungsfahrzeug auch nicht. Quittiert wurde je Gerät, in der
Weboberfläche wie in der Begleit-App, und jedes Gerät für sich.

Jetzt quittiert, wer quittiert, **am Server**: Die Quittung liegt am Fahrzeug
(``convoy_vehicles.alarm_quittiert_at``/``_von``), geht als
``alarm_quittiert`` an alle Verbindungen des Verbands und steht in der
Tracking-Nutzlast, damit ein später verbundenes Gerät sie auch sieht.

Drei Regeln:

- **Sie gilt einem Alarm.** Welcher gemeint ist, sagt sein Zeitstempel — der
  ``ts`` aus dem ``alert``, also ``status_changed_at``. Hat das Fahrzeug
  inzwischen etwas anderes gemeldet, gilt die Quittung als veraltet und wird
  abgelehnt; jeder neue Status setzt eine alte Quittung zurück
  (:func:`zuruecksetzen`).
- **Die erste zählt.** Quittieren zwei Führungsgeräte denselben Alarm, bleibt
  die erste Quittung stehen; die zweite bekommt sie als Antwort, ohne dass
  noch einmal gesendet wird.
- **Den eigenen Alarm quittiert man nicht.** Ein Gerät, das das alarmierende
  Fahrzeug selbst belegt, bekommt ``own-alert``: Es bestätigte sich sonst
  selbst, und die Besatzung hielte die Meldung für gesehen.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.models.convoy import ConvoyVehicle
from app.services import vehicle_status as vs
from app.services.tracking import tracking_manager

#: So lang darf der Anzeigetext „quittiert von" werden (Spalte: 120).
VON_MAX = 120


def alarm_ts(cv: ConvoyVehicle) -> datetime | None:
    """Beginn des laufenden Alarms — ``None``, wenn das Fahrzeug keinen hat."""
    if cv.vehicle_status in vs.ALERT_STATUSES and cv.status_changed_at is not None:
        return cv.status_changed_at
    return None


def zuruecksetzen(cv: ConvoyVehicle) -> None:
    """Ein neuer Status beginnt ohne Quittung — auch ein neuer Alarm."""
    cv.alarm_quittiert_at = None
    cv.alarm_quittiert_von = None


def _zeitpunkt(roh: object) -> datetime | None:
    if not isinstance(roh, str):
        return None
    try:
        wert = datetime.fromisoformat(roh)
    except ValueError:
        return None
    return wert if wert.tzinfo is not None else None


def von_kuerzen(von: str) -> str:
    von = " ".join(von.split())
    return von[:VON_MAX] if von else "Unbekannt"


def nachricht(vehicle_id: uuid.UUID, ts: datetime, von: str, at: datetime) -> dict:
    return {
        "type": "alarm_quittiert",
        "vehicle_id": str(vehicle_id),
        "alarm_ts": ts.isoformat(),
        "quittiert_von": von,
        "quittiert_at": at.isoformat(),
    }


def _ergebnis(cv: ConvoyVehicle) -> dict:
    return {
        "result": "ok",
        "applied": {
            "vehicle_id": str(cv.vehicle_id),
            "alarm_ts": cv.status_changed_at.isoformat(),
            "quittiert_von": cv.alarm_quittiert_von,
        },
        "ts": cv.alarm_quittiert_at.isoformat(),
    }


def _abgelehnt(grund: str) -> dict:
    return {"result": "rejected", "reason": grund}


async def quittieren(
    convoy_uuid: uuid.UUID,
    roh: dict,
    von: str,
    eigene_fahrzeuge: tuple[str, ...] | list[str] = (),
) -> dict:
    """Quittiert den Alarm, den ``roh`` nennt, und meldet es allen.

    ``roh`` trägt ``vehicle_id`` (das **alarmierende** Fahrzeug) und
    ``alarm_ts``. Antwortet im Format der Quittungen am Fahrer-Link
    (``result``/``reason``), damit beide Kanäle dieselbe Antwort geben.
    """
    try:
        vehicle_id = uuid.UUID(str(roh.get("vehicle_id")))
    except (TypeError, ValueError):
        return _abgelehnt("invalid-vehicle")
    gemeint = _zeitpunkt(roh.get("alarm_ts"))
    if gemeint is None:
        return _abgelehnt("invalid-alarm")
    if str(vehicle_id) in eigene_fahrzeuge:
        return _abgelehnt("own-alert")

    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (convoy_uuid, vehicle_id), with_for_update=True)
        if cv is None:
            return _abgelehnt("vehicle-not-in-convoy")
        laufend = alarm_ts(cv)
        if laufend is None or laufend != gemeint:
            return _abgelehnt("alarm-outdated")
        if cv.alarm_quittiert_at is not None:
            # Schon quittiert — von hier oder von einem anderen Gerät. Die erste
            # Quittung bleibt stehen, und niemand bekommt sie zweimal gemeldet.
            return _ergebnis(cv)
        cv.alarm_quittiert_at = datetime.now(timezone.utc)
        cv.alarm_quittiert_von = von_kuerzen(von)
        await db.commit()
        antwort = _ergebnis(cv)
        meldung = nachricht(vehicle_id, laufend, cv.alarm_quittiert_von, cv.alarm_quittiert_at)

    await tracking_manager.broadcast_neu(str(convoy_uuid), meldung)
    return antwort
