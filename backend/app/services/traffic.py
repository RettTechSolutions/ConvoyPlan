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
from app.services import opendata_traffic as opendata_svc
from app.services import overpass as overpass_svc

logger = logging.getLogger(__name__)


class AllSourcesFailedError(RuntimeError):
    """Keine der Verkehrsdatenquellen war erreichbar."""


def _overpass_features(overpass_fc: dict | None) -> list[dict]:
    features = []
    for f in (overpass_fc or {}).get("features", []):
        f.setdefault("properties", {}).setdefault("source", "overpass")
        features.append(f)
    return features


async def get_closures(lat: float, lon: float, radius_m: int = 15000) -> dict:
    """Vereinte Sperrungen im Radius um (lat, lon) aus allen Quellen."""
    overpass_fc, extra_features = await _gather(
        ("overpass", overpass_svc.get_closures(lat, lon, radius_m)),
        ("autobahn", autobahn_svc.features_around(lat, lon, radius_m)),
        ("opendata", opendata_svc.features_around(lat, lon, radius_m)),
    )
    return {"type": "FeatureCollection", "features": _overpass_features(overpass_fc) + extra_features}


async def get_closures_along_route(
    coordinates: list[tuple[float, float]], corridor_m: int = 2000
) -> dict:
    """Vereinte Sperrungen im Korridor entlang der Route ([(lon, lat), ...])."""
    overpass_fc, extra_features = await _gather(
        ("overpass", overpass_svc.get_closures_along_route(coordinates, corridor_m)),
        ("autobahn", autobahn_svc.features_along_route(coordinates, corridor_m)),
        ("opendata", opendata_svc.features_along_route(coordinates, corridor_m)),
    )
    return {"type": "FeatureCollection", "features": _overpass_features(overpass_fc) + extra_features}


async def _gather(overpass_src, *feature_srcs) -> tuple[dict | None, list[dict]]:
    """Alle Quellen nebenläufig abfragen; Einzelausfälle tolerieren.

    ``overpass_src`` liefert eine FeatureCollection, die übrigen liefern jeweils
    eine Feature-Liste. Erst wenn **alle** Quellen scheitern, wird
    :class:`AllSourcesFailedError` ausgelöst.
    """
    names = [overpass_src[0]] + [s[0] for s in feature_srcs]
    coros = [overpass_src[1]] + [s[1] for s in feature_srcs]
    results = await asyncio.gather(*coros, return_exceptions=True)

    ok_any = False
    overpass_fc: dict | None = None
    extra_features: list[dict] = []
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            logger.warning("Verkehrsdatenquelle '%s' nicht verfügbar: %s", name, res)
            continue
        ok_any = True
        if name == "overpass":
            overpass_fc = res
        elif res:
            extra_features.extend(res)

    if not ok_any:
        raise AllSourcesFailedError("Keine Verkehrsdatenquelle erreichbar")
    return overpass_fc, extra_features
