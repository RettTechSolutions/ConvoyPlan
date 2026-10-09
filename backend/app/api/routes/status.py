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
from app.services import graph_aufbau, region_switch

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


# Warum eine Funktion nicht (voll) nutzbar ist — in Worten eines Anwenders.
# Dieselbe Grenze wie oben: Funktionen und Folgen, keine Anbieter- oder
# Dienstnamen. Bei „betriebsbereit" und „unbekannt" gibt es keinen Grund.
_REASON_DATA_DOWN = "Die Datenbank ist nicht erreichbar. Gespeicherte Daten bleiben erhalten."
_REASON_TRACKING_DOWN = (
    "Die Datenbank ist nicht erreichbar — Standortmeldungen werden derzeit nicht gespeichert."
)
_REASON_PLANNING = {
    "building": "Die Straßenkarte wird gerade geladen. Routen lassen sich danach wieder berechnen.",
    "region": "Die Kartenregion wird gerade gewechselt; die Straßenkarte wird dafür neu aufgebaut.",
    "download": (
        "Die Kartendaten werden gerade heruntergeladen; danach wird die Straßenkarte "
        "aufgebaut. Bereits berechnete Routen bleiben erhalten."
    ),
    # Ein laufender Aufbau ist erkannt (services/graph_aufbau.py) — was hier
    # übrig bleibt, ist nicht angekündigt. Dann ist „melden" der richtige Rat.
    "offline": (
        "Der Routing-Dienst antwortet nicht, ohne dass ein Neuaufbau der Straßenkarte "
        "läuft. Hält das an, bitte beim Betreiber melden. Bereits berechnete Routen "
        "bleiben erhalten."
    ),
}


def _import_reason(seit: float | None) -> str:
    dauer = ""
    if seit is not None:
        minuten = max(0, int((time.time() - seit) // 60))
        dauer = " (seit einer Minute)" if minuten <= 1 else f" (seit {minuten} Minuten)"
    return (
        f"Die Straßenkarte wird gerade neu aufgebaut{dauer}, meist nach einem Update. "
        "Danach lassen sich Routen wieder berechnen; bereits berechnete bleiben erhalten."
    )
_REASON_TRAFFIC = {
    "closures": "Sperrungen aus dem Kartenbestand fehlen derzeit; Autobahnmeldungen kommen weiter an.",
    "autobahn": "Autobahnmeldungen fehlen derzeit; Sperrungen aus dem Kartenbestand kommen weiter an.",
    "both": "Die externen Quellen für Sperrungen und Verkehrsmeldungen antworten nicht.",
}
_REASON_WEATHER_DOWN = (
    "Der externe Wetterdienst antwortet nicht. Routen lassen sich ohne Wetterangaben planen."
)


def _planning_reason(raw: str) -> str | None:
    if raw == "ok":
        return None
    if region_switch.laeuft():
        return _REASON_PLANNING["region"]
    aufbau = graph_aufbau.laufender_aufbau()
    if aufbau is not None:
        if aufbau.phase == "download":
            return _REASON_PLANNING["download"]
        return _import_reason(aufbau.seit)
    return _REASON_PLANNING.get(raw, _REASON_PLANNING["offline"])


def _traffic_reason(overpass: str, autobahn: str) -> str | None:
    if overpass == "down" and autobahn == "down":
        return _REASON_TRAFFIC["both"]
    if overpass == "down":
        return _REASON_TRAFFIC["closures"]
    if autobahn == "down":
        return _REASON_TRAFFIC["autobahn"]
    return None


async def _collect_public_status(db: AsyncSession) -> dict:
    db_state = _state_of("ok" if await _db_reachable(db) else "error")
    gh_raw = (await _graphhopper_probe())[0]
    gh_state = _state_of(gh_raw)

    overpass_check, autobahn_check, weather_check = await asyncio.gather(
        overpass_svc.probe(), autobahn_svc.probe(), weather_svc.probe()
    )
    overpass_state = _state_of(overpass_check.get("status"))
    autobahn_state = _state_of(autobahn_check.get("status"))
    traffic_state = _combine(overpass_state, autobahn_state)
    weather_state = _state_of(weather_check.get("status"))
    data_down = db_state == "down"

    components = [
        {
            "key": "portal",
            "name": "Portal & Anmeldung",
            "description": "Anmeldung, Organisationsverwaltung und Zugriff auf das Portal.",
            "core": True,
            # Beantwortet der Server diese Anfrage, läuft das Portal.
            "state": "operational",
            "reason": None,
        },
        {
            "key": "data",
            "name": "Konvoi-Daten",
            "description": "Konvois, Fahrzeuge und Einsatzdaten speichern und laden.",
            "core": True,
            "state": db_state,
            "reason": _REASON_DATA_DOWN if data_down else None,
        },
        {
            "key": "planning",
            "name": "Routenplanung",
            "description": "Routen, Fahrzeiten und Wegpunkte für Konvois berechnen.",
            "core": False,
            "state": gh_state,
            "reason": _planning_reason(gh_raw),
        },
        {
            "key": "tracking",
            "name": "Live-Tracking",
            "description": "Standortmeldungen der Fahrzeuge und die Live-Karte der Leitstelle.",
            "core": True,
            "state": db_state,
            "reason": _REASON_TRACKING_DOWN if data_down else None,
        },
        {
            "key": "traffic",
            "name": "Verkehr & Sperrungen",
            "description": "Straßensperren und Verkehrsmeldungen entlang der Route.",
            "core": False,
            "state": traffic_state,
            "reason": _traffic_reason(overpass_state, autobahn_state),
        },
        {
            "key": "weather",
            "name": "Wetterdaten",
            "description": "Wetterlage und Vorhersage für Start- und Zielorte.",
            "core": False,
            "state": weather_state,
            "reason": _REASON_WEATHER_DOWN if weather_state == "down" else None,
        },
    ]

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall": _overall(components),
        # `core` steuert nur die Gesamtaussage und bleibt intern.
        "components": [{k: v for k, v in c.items() if k != "core"} for c in components],
    }


@router.get("/capabilities")
async def capabilities(db: AsyncSession = Depends(get_db)):
    """Welche Schnittstellen diese Instanz anbietet — ohne Anmeldung abfragbar.

    Gedacht für Programme und KI-Agenten, die wissen wollen, womit sie es zu
    tun haben, bevor sie einen Endpunkt raten. Alles hier ist ohnehin
    beobachtbar: ob ``/mcp`` antwortet, merkt ein Aufrufer mit einer Anfrage.
    Der Unterschied ist, dass er sie sich sparen kann.

    Das Frontend baut daraus die Agenten-Dokumente (``llms.txt``,
    ``agent-card.json``, ``server-card.json``). Deshalb steht hier nur, was
    tatsächlich montiert ist: ein angekündigter Endpunkt, der mit 404
    antwortet, ist schlimmer als ein verschwiegener.
    """
    from app.api import docs_ui
    from app.api.routes.version import _core_str
    from app.mcp import mount as mcp_mount
    from app.services import demo as demo_svc

    try:
        demo_enabled = await demo_svc.is_demo_enabled(db)
    except Exception:
        demo_enabled = False

    return {
        "name": "ConvoyPlan",
        # Kernversion, nicht der ``git describe``-String: den hält
        # ``/api/version`` vor anonymen Aufrufern zurueck, weil er den genauen
        # Commit einer unveroeffentlichten Instanz verraet.
        "version": _core_str(settings.app_version),
        "mcp_enabled": mcp_mount.ist_aktiv(),
        "mcp_url": "/mcp" if mcp_mount.ist_aktiv() else None,
        "demo_enabled": demo_enabled,
        "docs_enabled": docs_ui.docs_enabled(),
        "rest_api": "/api",
        "public_openapi": "/openapi.json",
        "agent_instructions": "/agents.md",
        "llms_txt": "/llms.txt",
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
