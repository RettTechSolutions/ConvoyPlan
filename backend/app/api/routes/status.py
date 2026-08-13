import asyncio
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import settings
from app.database import get_db
from app.services import weather as weather_svc
from app.services import overpass as overpass_svc
from app.services import autobahn as autobahn_svc
from app.services import traffic_flow as traffic_flow_svc

router = APIRouter(prefix="/status", tags=["status"])


async def _db_reachable(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _graphhopper_probe() -> tuple[str, dict | list | None]:
    """Erreichbarkeit des Routing-Dienstes plus — falls verfügbar — der
    abgedeckte Kartenausschnitt. Der Ausschnitt ist nur für angemeldete
    Aufrufer gedacht und bleibt der öffentlichen Statusseite vorenthalten."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            h = await client.get(f"{settings.graphhopper_url}/health")
            if not h.is_success:
                return "building", None
            bbox = None
            info = await client.get(f"{settings.graphhopper_url}/info")
            if info.is_success:
                bbox = info.json().get("bbox")
            return "ok", bbox
    except (httpx.ConnectError, httpx.ConnectTimeout):
        # Host nicht erreichbar — Container ist unten
        return "offline", None
    except Exception:
        # ReadTimeout / anderes — GH läuft, importiert aber noch den Graphen
        return "building", None


@router.get("")
async def service_status(db: AsyncSession = Depends(get_db)):
    db_ok = await _db_reachable(db)
    gh_status, gh_bbox = await _graphhopper_probe()

    overpass_check, autobahn_check = await asyncio.gather(
        overpass_svc.probe(), autobahn_svc.probe()
    )
    flow_cfg = await traffic_flow_svc.resolve_config(db)

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backend": "ok",
        "database": "ok" if db_ok else "error",
        "graphhopper": gh_status,
        "graphhopper_bbox": gh_bbox,
        "weather_api": weather_svc.last_check(),
        "overpass_api": overpass_check,
        "autobahn_api": autobahn_check,
        "traffic_flow": {"provider": flow_cfg.provider},
    }


# ── Öffentliche Statusseite ───────────────────────────────────────────────
# Die Seite unter /status ist ohne Anmeldung erreichbar. Sie beantwortet nur
# eine Frage: „Funktioniert das, was ich gleich tun will?" — deshalb nennt sie
# ausschließlich Funktionen (Routenplanung, Live-Tracking, …) und deren
# Zustand. Bewusst *nicht* enthalten: Latenzen, Anbieternamen, abgedeckte
# Kartenausschnitte, Container- oder Versionsangaben. Wer diese Details
# braucht, ist angemeldet und findet sie in der Admin-Systemübersicht.

_PUBLIC_CACHE_TTL = 15.0  # s — die Seite pollt, die Prüfungen sollen es nicht

# Antwort und Entstehungszeitpunkt hängen als *ein* Objekt zusammen: würden
# beide einzeln gesetzt, könnte ein paralleler Aufruf dazwischen eine frische
# Antwort mit altem Zeitstempel sehen (oder umgekehrt).
_public_cache: tuple[dict, float] | None = None
_public_lock = asyncio.Lock()


def _cached_public_status() -> dict | None:
    """Zwischengespeicherte Antwort, sofern sie noch frisch genug ist."""
    cached = _public_cache
    if cached is None:
        return None
    payload, created_at = cached
    if (time.monotonic() - created_at) >= _PUBLIC_CACHE_TTL:
        return None
    return payload


def _state_of(raw: str | None) -> str:
    """Rohstatus einer Einzelprüfung → öffentlicher Zustand."""
    if raw == "ok":
        return "operational"
    if raw == "building":
        return "degraded"
    if raw is None or raw == "unknown":
        return "unknown"
    return "down"


def _combine(*states: str) -> str:
    """Mehrere Einzelprüfungen zu einem Funktionszustand zusammenfassen.

    Unbekannte Prüfungen zählen nicht mit — sie ziehen eine ansonsten gesunde
    Funktion nicht herunter. Fällt ein Teil aus, ist die Funktion eingeschränkt;
    fallen alle bekannten Teile aus, ist sie nicht verfügbar.
    """
    known = [s for s in states if s != "unknown"]
    if not known:
        return "unknown"
    if all(s == "operational" for s in known):
        return "operational"
    if all(s == "down" for s in known):
        return "down"
    return "degraded"


def _overall(components: list[dict]) -> str:
    """Gesamtzustand — Kernfunktionen bestimmen die Aussage.

    Fällt eine Kernfunktion (Portal, Daten, Tracking) aus, ist die Instanz
    gestört. Zusatzdienste wie Wetter oder Verkehrslage schränken sie nur ein.
    """
    if any(c["core"] and c["state"] == "down" for c in components):
        return "down"
    if any(c["state"] in ("down", "degraded") for c in components):
        return "degraded"
    if all(c["state"] == "unknown" for c in components):
        return "unknown"
    return "operational"


async def _collect_public_status(db: AsyncSession) -> dict:
    db_state = _state_of("ok" if await _db_reachable(db) else "error")
    gh_state = _state_of((await _graphhopper_probe())[0])

    overpass_check, autobahn_check, weather_check = await asyncio.gather(
        overpass_svc.probe(), autobahn_svc.probe(), weather_svc.probe()
    )
    traffic_state = _combine(
        _state_of(overpass_check.get("status")),
        _state_of(autobahn_check.get("status")),
    )
    weather_state = _state_of(weather_check.get("status"))

    components = [
        {
            "key": "portal",
            "name": "Portal & Anmeldung",
            "description": "Anmeldung, Organisationsverwaltung und Zugriff auf das Portal.",
            "core": True,
            # Beantwortet der Server diese Anfrage, läuft das Portal.
            "state": "operational",
        },
        {
            "key": "data",
            "name": "Konvoi-Daten",
            "description": "Konvois, Fahrzeuge und Einsatzdaten speichern und laden.",
            "core": True,
            "state": db_state,
        },
        {
            "key": "planning",
            "name": "Routenplanung",
            "description": "Routen, Fahrzeiten und Wegpunkte für Konvois berechnen.",
            "core": False,
            "state": gh_state,
        },
        {
            "key": "tracking",
            "name": "Live-Tracking",
            "description": "Standortmeldungen der Fahrzeuge und die Live-Karte der Leitstelle.",
            "core": True,
            "state": db_state,
        },
        {
            "key": "traffic",
            "name": "Verkehr & Sperrungen",
            "description": "Straßensperren und Verkehrsmeldungen entlang der Route.",
            "core": False,
            "state": traffic_state,
        },
        {
            "key": "weather",
            "name": "Wetterdaten",
            "description": "Wetterlage und Vorhersage für Start- und Zielorte.",
            "core": False,
            "state": weather_state,
        },
    ]

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall": _overall(components),
        # `core` steuert nur die Gesamtaussage und bleibt intern.
        "components": [{k: v for k, v in c.items() if k != "core"} for c in components],
    }


@router.get("/public")
async def public_status(db: AsyncSession = Depends(get_db)):
    """Grobkörniger Funktionsstatus für die öffentliche Statusseite.

    Das Ergebnis wird kurz zwischengespeichert, damit häufiges Neuladen der
    Seite nicht auf die geprüften Dienste durchschlägt.
    """
    global _public_cache

    cached = _cached_public_status()
    if cached is not None:
        return cached

    async with _public_lock:
        # Zweite Prüfung: während des Wartens kann ein paralleler Aufruf den
        # Cache bereits gefüllt haben.
        cached = _cached_public_status()
        if cached is not None:
            return cached
        payload = await _collect_public_status(db)
        _public_cache = (payload, time.monotonic())

    return payload
