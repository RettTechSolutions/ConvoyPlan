"""Zusammenführung mehrerer Verkehrsdatenquellen.

Sperrungen/Baustellen/Hindernisse werden aus **Overpass (OpenStreetMap)** und
der **Autobahn-API** geholt und zu einer gemeinsamen FeatureCollection vereint
(„in einen Topf") — so ergibt sich eine bessere Abdeckung als mit einer Quelle
allein. Fällt eine Quelle aus, liefert die andere weiterhin Ergebnisse; nur
wenn *beide* scheitern, wird ein Fehler ausgelöst.
"""
import asyncio
import logging

from app.services import autobahn as autobahn_svc
from app.services import overpass as overpass_svc

logger = logging.getLogger(__name__)


class AllSourcesFailedError(RuntimeError):
    """Keine der Verkehrsdatenquellen war erreichbar."""


def _merge(overpass_fc: dict | None, autobahn_features: list[dict] | None) -> dict:
    features: list[dict] = []
    if overpass_fc:
        for f in overpass_fc.get("features", []):
            f.setdefault("properties", {}).setdefault("source", "overpass")
            features.append(f)
    if autobahn_features:
        features.extend(autobahn_features)
    return {"type": "FeatureCollection", "features": features}


async def get_closures(lat: float, lon: float, radius_m: int = 15000) -> dict:
    """Vereinte Sperrungen im Radius um (lat, lon) aus allen Quellen."""
    overpass_fc, autobahn_features = await _gather(
        overpass_svc.get_closures(lat, lon, radius_m),
        autobahn_svc.features_around(lat, lon, radius_m),
    )
    return _merge(overpass_fc, autobahn_features)


async def get_closures_along_route(
    coordinates: list[tuple[float, float]], corridor_m: int = 2000
) -> dict:
    """Vereinte Sperrungen im Korridor entlang der Route ([(lon, lat), ...])."""
    overpass_fc, autobahn_features = await _gather(
        overpass_svc.get_closures_along_route(coordinates, corridor_m),
        autobahn_svc.features_along_route(coordinates, corridor_m),
    )
    return _merge(overpass_fc, autobahn_features)


async def _gather(overpass_coro, autobahn_coro) -> tuple[dict | None, list[dict] | None]:
    """Beide Quellen nebenläufig abfragen; Einzelausfälle tolerieren.

    Erst wenn beide Quellen scheitern, wird :class:`AllSourcesFailedError`
    ausgelöst.
    """
    overpass_res, autobahn_res = await asyncio.gather(
        overpass_coro, autobahn_coro, return_exceptions=True
    )

    overpass_fc: dict | None = None
    if isinstance(overpass_res, Exception):
        logger.warning("Overpass-Verkehrsdaten nicht verfügbar: %s", overpass_res)
    else:
        overpass_fc = overpass_res

    autobahn_features: list[dict] | None = None
    if isinstance(autobahn_res, Exception):
        logger.warning("Autobahn-Verkehrsdaten nicht verfügbar: %s", autobahn_res)
    else:
        autobahn_features = autobahn_res

    if overpass_fc is None and autobahn_features is None:
        raise AllSourcesFailedError("Keine Verkehrsdatenquelle erreichbar")
    return overpass_fc, autobahn_features
