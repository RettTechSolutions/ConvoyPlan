import httpx
import time
from datetime import datetime, timezone

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES = {
    0: "Klar", 1: "Überwiegend klar", 2: "Teils bewölkt", 3: "Bewölkt",
    45: "Nebel", 48: "Raureif",
    51: "Leichter Nieselregen", 53: "Nieselregen", 55: "Starker Nieselregen",
    61: "Leichter Regen", 63: "Regen", 65: "Starker Regen",
    71: "Leichter Schnee", 73: "Schnee", 75: "Starker Schnee",
    80: "Leichte Schauer", 81: "Schauer", 82: "Starke Schauer",
    95: "Gewitter", 96: "Gewitter mit Hagel", 99: "Schweres Gewitter mit Hagel",
}

_last_check: dict = {"status": "unknown", "latency_ms": None, "checked_at": None}


def last_check() -> dict:
    return dict(_last_check)


async def probe() -> dict:
    """Leichter Erreichbarkeitscheck, 60 s gecacht.

    Analog zu Overpass/Autobahn: die Statusanzeigen pollen regelmäßig, ein
    echter Wetterabruf über :func:`get_weather` aktualisiert ``_last_check``
    ohnehin. Nur wenn längere Zeit niemand Wetter abgerufen hat, prüft dieser
    Aufruf die API selbst — sonst stünde dort dauerhaft "unbekannt".
    """
    global _last_check
    if _last_check["checked_at"] is not None:
        last = datetime.fromisoformat(_last_check["checked_at"])
        if (datetime.now(timezone.utc) - last).total_seconds() < 60:
            return dict(_last_check)

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                OPEN_METEO_URL,
                params={"latitude": 52.52, "longitude": 13.41, "current_weather": True},
            )
            resp.raise_for_status()
        _last_check = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - t0) * 1000),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        _last_check = {
            "status": "error",
            "latency_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    return dict(_last_check)


async def get_weather(lat: float, lon: float) -> dict:
    global _last_check
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "hourly": "temperature_2m,precipitation_probability,weathercode,windspeed_10m",
        "forecast_days": 1,
        "timezone": "Europe/Berlin",
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        _last_check = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - t0) * 1000),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        _last_check = {
            "status": "error",
            "latency_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        raise

    cw = data.get("current_weather", {})
    hourly = data.get("hourly", {})
    hours = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precip = hourly.get("precipitation_probability", [])
    wcodes = hourly.get("weathercode", [])

    forecast = [
        {
            "time": hours[i],
            "temp_c": temps[i],
            "precip_pct": precip[i],
            "condition": WMO_CODES.get(wcodes[i], "Unbekannt"),
        }
        for i in range(min(len(hours), 12))
    ]

    return {
        "current": {
            "temp_c": cw.get("temperature"),
            "windspeed_kmh": cw.get("windspeed"),
            "condition": WMO_CODES.get(cw.get("weathercode", -1), "Unbekannt"),
            "is_day": cw.get("is_day", 1) == 1,
        },
        "hourly_forecast": forecast,
    }
