#!/usr/bin/env python3
"""Baut `frontend/static/geo/gebiete.geojson` — die wählbaren Zuständigkeits-
gebiete für Leitstellen im gesamten Routing-Raum (DACH).

Drei Ebenen, drei Quellen, ein Schema:

| Land | Ebene                          | Quelle                                  |
|------|--------------------------------|-----------------------------------------|
| DE   | Landkreise / kreisfreie Städte | `sources/landkreise.geojson` (BKG VG2500) |
| AT   | Politische Bezirke             | Statistik Austria via ginseng666        |
| CH   | Kantone                        | Eurostat NUTS-3 via Nuts2json           |
| LI   | Land                           | Eurostat NUTS-3 via Nuts2json           |

Die Ebenen sind bewusst NICHT einheitlich: In Deutschland und Österreich ist die
Kreis- bzw. Bezirksebene das, woran Leitstellen-Zuständigkeit hängt; in der
Schweiz ist es der Kanton. Schweizer Bezirke wären zu klein und in mehreren
Kantonen gar nicht vorhanden.

Deutschland kommt bewusst aus der bereits im Repo liegenden Datei statt aus einer
frischen Quelle (`sources/landkreise.geojson`): So bleibt der Datensatz zwischen
zwei Laeufen stabil und der Auswahl-Dialog springt nicht, wenn eine Fremdquelle
ihre Geometrie nachzieht.

Aufruf (Netzzugang nötig, lädt AT und CH/LI herunter):

    python3 scripts/geo/build_gebiete.py

Ohne Argumente schreibt das Skript direkt nach `frontend/static/geo/`.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GEO_DIR = REPO / "frontend" / "static" / "geo"

# Liegt bewusst NICHT unter static/: die Datei ist Bau-Eingang, kein Asset. Das
# Frontend lädt nur noch gebiete.geojson, und 700 kB Kreisgrenzen müssen weder
# ins Image noch über die Leitung.
DE_SOURCE = REPO / "scripts" / "geo" / "sources" / "landkreise.geojson"
AT_URL = (
    "https://raw.githubusercontent.com/ginseng666/GeoJSON-TopoJSON-Austria/"
    "master/2021/simplified-99.9/bezirke_999_geo.json"
)
NUTS_URL = (
    "https://raw.githubusercontent.com/eurostat/Nuts2json/"
    "master/pub/v2/2024/4326/03M/3.json"
)

ATTRIBUTION = (
    "© GeoBasis-DE / BKG (dl-de/by-2-0) · "
    "© Statistik Austria (CC BY 4.0) · "
    "© EuroGeographics / Eurostat"
)

# Erste Ziffer der Gemeindekennziffer = Bundesland.
AT_BUNDESLAENDER = {
    "1": "Burgenland",
    "2": "Kärnten",
    "3": "Niederösterreich",
    "4": "Oberösterreich",
    "5": "Salzburg",
    "6": "Steiermark",
    "7": "Tirol",
    "8": "Vorarlberg",
    "9": "Wien",
}


def fetch_json(url: str) -> dict:
    print(f"  lade {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=300) as resp:  # noqa: S310 - feste HTTPS-URLs
        return json.load(resp)


# ── TopoJSON ─────────────────────────────────────────────────────────
#
# Nuts2json liefert TopoJSON. Die Dekodierung ist klein und vollständig
# spezifiziert, deshalb hier direkt statt über eine Zusatzabhängigkeit.


def _decode_arcs(topo: dict) -> list[list[list[float]]]:
    """Delta-Kodierung auflösen und Quantisierung zurückrechnen."""
    tf = topo.get("transform")
    sx, sy = (tf["scale"] if tf else (1.0, 1.0))
    tx, ty = (tf["translate"] if tf else (0.0, 0.0))
    decoded = []
    for arc in topo["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            if tf:
                x += dx
                y += dy
                points.append([x * sx + tx, y * sy + ty])
            else:
                points.append([float(dx), float(dy)])
        decoded.append(points)
    return decoded


def _ring(arcs: list[list[list[float]]], indexes: list[int]) -> list[list[float]]:
    """Einen Ring aus seinen Arc-Verweisen zusammensetzen.

    Ein negativer Index ``~i`` meint Arc ``i`` rückwärts. Aufeinanderfolgende
    Arcs teilen sich ihren Endpunkt — der wird beim Anhängen übersprungen.
    """
    out: list[list[float]] = []
    for idx in indexes:
        arc = arcs[~idx][::-1] if idx < 0 else arcs[idx]
        out.extend(arc[1:] if out else arc)
    if out and out[0] != out[-1]:
        out.append(out[0])
    return out


def topo_geometry(topo: dict, arcs: list[list[list[float]]], geom: dict) -> dict | None:
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [_ring(arcs, r) for r in geom["arcs"]]}
    if geom["type"] == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [[_ring(arcs, r) for r in poly] for poly in geom["arcs"]],
        }
    return None


# ── Quellen → einheitliche Features ──────────────────────────────────


def feature(code: str, name: str, country: str, region: str | None, geometry: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {"code": code, "name": name, "country": country, "region": region},
        "geometry": geometry,
    }


def germany() -> list[dict]:
    fc = json.loads(DE_SOURCE.read_text(encoding="utf-8"))
    out = []
    for f in fc["features"]:
        p = f["properties"]
        out.append(
            feature(f"DE-{p['krs_code']}", p["krs_name"], "DE", p.get("lan_name"), f["geometry"])
        )
    return out


def austria() -> list[dict]:
    fc = fetch_json(AT_URL)
    out = []
    for f in fc["features"]:
        iso = f["properties"]["iso"]
        # Die Quelle enthält Wien doppelt: einmal als Ganzes (900) und einmal in
        # 23 Gemeindebezirken (901-923), deckungsgleich übereinander. Für die
        # Zuständigkeit zählt Wien als eine Einheit — die 23 fliegen raus.
        if iso != "900" and iso.startswith("9"):
            continue
        # "Wiener Neustadt(Land)" → "Wiener Neustadt (Land)"
        name = re.sub(r"\s*\(", " (", f["properties"]["name"]).strip()
        out.append(feature(f"AT-{iso}", name, "AT", AT_BUNDESLAENDER.get(iso[0]), f["geometry"]))
    return out


def switzerland_and_liechtenstein() -> list[dict]:
    topo = fetch_json(NUTS_URL)
    arcs = _decode_arcs(topo)
    out = []
    for geom in topo["objects"]["nutsrg"]["geometries"]:
        nuts = geom["properties"]["id"]
        country = nuts[:2]
        if country not in ("CH", "LI"):
            continue
        geometry = topo_geometry(topo, arcs, geom)
        if geometry is None:
            continue
        # Kantone haben unterhalb des Bundes keine übergeordnete Verwaltungs-
        # ebene; dasselbe gilt für Liechtenstein. region bleibt deshalb leer,
        # statt eine statistische Großregion als Verwaltungsebene auszugeben.
        out.append(feature(f"{country}-{nuts[2:]}", geom["properties"]["na"], country, None, geometry))
    return out


def main() -> int:
    print("Gebiete werden gebaut…", file=sys.stderr)
    features = germany() + austria() + switzerland_and_liechtenstein()
    features.sort(key=lambda f: f["properties"]["code"])

    codes = [f["properties"]["code"] for f in features]
    duplicates = {c for c in codes if codes.count(c) > 1}
    if duplicates:
        print(f"FEHLER: doppelte Schlüssel: {sorted(duplicates)}", file=sys.stderr)
        return 1

    fc = {
        "type": "FeatureCollection",
        "name": "Zuständigkeitsgebiete DACH",
        "attribution": ATTRIBUTION,
        "features": features,
    }
    target = GEO_DIR / "gebiete.geojson"
    target.write_text(
        json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    per_country: dict[str, int] = {}
    for f in features:
        per_country[f["properties"]["country"]] = per_country.get(f["properties"]["country"], 0) + 1
    print(
        f"{target.relative_to(REPO)}: {len(features)} Gebiete "
        f"({', '.join(f'{k} {v}' for k, v in sorted(per_country.items()))}), "
        f"{target.stat().st_size / 1024:.0f} kB",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
