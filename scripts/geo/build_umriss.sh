#!/bin/sh
# Baut `frontend/static/geo/dach.geojson` — den Umriss des Routing-Raums, der
# auf allen Karten als Maske liegt.
#
# Quelle ist `gebiete.geojson` (siehe build_gebiete.py): der Umriss ist exakt
# die Außengrenze der wählbaren Zuständigkeitsgebiete. Nur so decken sich Maske
# und Gebietsauswahl im Leitstellen-Dialog — kämen sie aus verschiedenen
# Datensätzen, ragten Gebiete sichtbar über den Maskenrand hinaus.
#
# Voraussetzung: mapshaper (via npx, kein globales Install nötig).
set -e

DIR="$(CDPATH='' cd "$(dirname "$0")/../../frontend/static/geo" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Umriss wird gebaut…" >&2

# Die drei Landesdatensätze ziehen ihre gemeinsamen Grenzen leicht unterschied-
# lich (BKG vs. Statistik Austria vs. Eurostat). Ohne Nahtschluss blieben dunkle
# Maskenstreifen entlang der Binnengrenzen stehen — `-clean gap-width=3km`
# schließt sie.
#
# Bewusst OHNE `-filter-slivers`: Der Verschnitt zwischen den Gebietsgrenzen
# taucht als Loch auf, nicht als eigene Fläche, und wird schon von `-clean`
# erledigt. `-filter-slivers` würde stattdessen kleine Außenflächen entfernen —
# und das sind hier echte Exklaven und Inseln (Vennbahn-Gebiet bei Aachen,
# Elbinseln, Halligen), gemessen zwischen 1,2 und 3 km².
npx --yes mapshaper "$DIR/gebiete.geojson" \
  -dissolve2 \
  -clean gap-width=3km close-outer-gaps \
  -dissolve \
  -o precision=0.0001 format=geojson "$TMP/umriss.geojson"

# Als einzelnes Feature mit Namen und Namensnennung speichern und die Innenringe
# verwerfen: übrig bleibt dort nur der Bodensee, an dem die Quellen unterschied-
# lich enden. Echte Enklaven gibt es innerhalb von DACH nicht mehr — Jungholz
# und Büsingen sind Binnenland.
python3 - "$TMP/umriss.geojson" "$DIR/gebiete.geojson" "$DIR/dach.geojson" <<'PY'
import json, math, sys

raw, gebiete, target = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(raw, encoding="utf-8"))
g = (d["geometries"][0] if d["type"] == "GeometryCollection"
     else d["geometry"] if d["type"] == "Feature"
     else d["features"][0]["geometry"] if d["type"] == "FeatureCollection"
     else d)
parts = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
dropped = sum(len(p) - 1 for p in parts)
parts = [[p[0]] for p in parts]

out = {
    "type": "Feature",
    "properties": {
        "name": "Deutschland, Österreich, Schweiz, Liechtenstein",
        "attribution": json.load(open(gebiete, encoding="utf-8"))["attribution"],
    },
    "geometry": {"type": "MultiPolygon", "coordinates": parts},
}
json.dump(out, open(target, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
xs = [c[0] for p in parts for r in p for c in r]
ys = [c[1] for p in parts for r in p for c in r]


def area_km2(ring):
    """Kugelkappen-Fläche (spherical excess).

    Eine planare Shoelace-Formel mit einem cos(Breite)-Faktor ist hier wertlos:
    der Hauptring spannt neun Breitengrade, jede feste Bezugsbreite liegt um
    Prozente daneben.
    """
    r = 6371008.8
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        x2, y2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        s += (x2 - x1) * (2 + math.sin(y1) + math.sin(y2))
    return abs(s * r * r / 2) / 1e6


total = sum(area_km2(p[0]) for p in parts)
# DE 357.596 + AT 83.879 + CH 41.291 + LI 160 km²; die Vereinfachung der
# Quelldaten kostet rund ein halbes Prozent.
SOLL = 482926
print(f"{target}: {len(parts)} Teilflächen, {dropped} Innenringe verworfen, "
      f"bbox lon {min(xs):.3f}..{max(xs):.3f} lat {min(ys):.3f}..{max(ys):.3f}, "
      f"Fläche {total:.0f} km² ({total / SOLL * 100:.1f} % der amtlichen)", file=sys.stderr)
if not 0.98 <= total / SOLL <= 1.02:
    print("FEHLER: Fläche weicht mehr als 2 % ab — Quelldaten prüfen.", file=sys.stderr)
    raise SystemExit(1)
PY
