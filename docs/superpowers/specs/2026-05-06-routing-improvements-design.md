# Routing-Verbesserungen Design

## Ziel

Genaue Fahrzeitberechnung auf Basis der tatsächlichen Routenzusammensetzung (Innerorts/Außerorts), konfigurierbare Straßenpräferenz pro Verband, und Fahrzeugabstände für den Marschbefehl.

---

## Datenmodell — neue Felder am Convoy

| Feld | Typ | Default | Beschreibung |
|------|-----|---------|-------------|
| `road_preference` | `VARCHAR(20)` | `schnell` | `schnell` \| `bundesstrasse` \| `landstrasse` |
| `spacing_urban_m` | `INTEGER` | `15` | Fahrzeugabstand Innerorts (m) |
| `spacing_rural_m` | `INTEGER` | `50` | Fahrzeugabstand Außerorts (m) |
| `spacing_motorway_m` | `INTEGER` | `100` | Fahrzeugabstand Autobahn (m) |

DB-Migration via Alembic (neue Spalten mit Defaultwerten, nullable=False).

Schemas: `ConvoyCreate` und `ConvoyUpdate` in `backend/app/schemas/convoy.py` werden um die vier Felder erweitert. `ConvoyResponse` ebenso.

---

## Routing-Service (`backend/app/services/routing.py`)

### Signaturänderung

```python
async def calculate_route(
    points: list[dict[str, float]],
    vehicle_params: dict[str, Any] | None = None,
    road_preference: str = "schnell",
) -> dict:
```

### GraphHopper-Payload

`details: ["road_class"]` wird immer mitgeschickt.

`custom_model.priority` je nach `road_preference`:

| Wert | custom_model |
|------|-------------|
| `schnell` | keiner (Standard-Autoprofil) |
| `bundesstrasse` | `{"if": "road_class == MOTORWAY", "multiply_by": "0.3"}` |
| `landstrasse` | `{"if": "road_class == MOTORWAY \|\| road_class == TRUNK", "multiply_by": "0.05"}` |

Falls bereits ein `custom_model` für Höhenbeschränkungen gesetzt ist, wird die neue Priority-Regel der vorhandenen `priority`-Liste hinzugefügt.

### Rückgabe

Das Ergebnis enthält zusätzlich `road_class_details` — die rohen GH-Detail-Segmente:

```python
return {
    "distance_m": ...,
    "duration_s": ...,   # GH-Rohzeit, wird im Endpoint nicht mehr genutzt
    "geometry": ...,
    "road_class_details": path.get("details", {}).get("road_class", []),
}
```

---

## Zeitberechnung (`backend/app/api/routes/routing.py`)

Ersetzt die bisherige `avg_speed`-Formel.

### Urban-Klassifizierung

Segmente mit `road_class` in `{"residential", "living_street", "service"}` gelten als **Innerorts**. Alle anderen als **Außerorts**.

### Distanz-Aufteilung

Die GH-Details enthalten Segmente als `[from_index, to_index, value]`, Indizes in das `geometry.coordinates`-Array (`[lon, lat]`-Paare). Distanz pro Segment wird per Haversine aus den tatsächlichen Koordinaten berechnet:

```python
from math import radians, cos, sin, asin, sqrt

URBAN_CLASSES = {"residential", "living_street", "service"}

def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    R = 6_371_000
    dlon, dlat = radians(lon2 - lon1), radians(lat2 - lat1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))

def _segment_dist_m(coords, from_i, to_i) -> float:
    return sum(
        _haversine_m(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])
        for i in range(from_i, to_i)
    )

urban_dist = 0.0
nonurban_dist = 0.0
for from_i, to_i, rc in road_class_details:
    d = _segment_dist_m(coords, from_i, to_i)
    if rc.lower() in URBAN_CLASSES:
        urban_dist += d
    else:
        nonurban_dist += d
```

### Fahrzeit

```python
h_urban = urban_dist / 1000 / convoy.speed_urban_kmh
h_nonurban = nonurban_dist / 1000 / convoy.speed_rural_kmh
convoy_duration_s = int((h_urban + h_nonurban) * 3600)
```

Fallback: Falls `road_class_details` leer ist (GH ohne Details), wird die alte Formel `0.7 * rural + 0.3 * urban` als Fallback genutzt.

---

## Marschbefehl-PDF (`backend/app/services/pdf.py`)

Neuer Block **„Fahrzeugabstände"** nach dem Verbandsdetail-Abschnitt:

```
Fahrzeugabstände:
  Innerorts:   <spacing_urban_m> m
  Außerorts:   <spacing_rural_m> m
  Autobahn:    <spacing_motorway_m> m
```

Die `generate_marschbefehl`-Funktion erhält die Spacing-Werte über das bestehende `convoy`-Objekt (da die neuen Felder im Modell sind).

---

## Frontend (`frontend/src/routes/plan/+page.svelte`)

### Convoy-Formular (Erstellen + Bearbeiten)

Neues Feld **Straßenpräferenz** (Radio oder Select) mit drei Optionen:
- `schnell` → „Schnellste Route (Autobahn erlaubt)"
- `bundesstrasse` → „Bundesstraßen bevorzugt"
- `landstrasse` → „Nur Landstraßen"

Default beim Erstellen: `schnell`.

Neue Felder **Fahrzeugabstände** (drei `<input type="number">`):
- Innerorts: Default `15`
- Außerorts: Default `50`
- Autobahn: Default `100`

### Plan-Tab (Anzeige)

Im Plan-Tab wird die aktive Straßenpräferenz neben dem Tempo angezeigt:

```
Tempo: 65 km/h (außerorts) / 40 km/h (innerorts) · Landstraßen
```

---

## Nicht im Scope

- Kein separates Autobahn-Tempo-Feld (nur 2 Geschwindigkeiten: innerorts + außerorts)
- Keine Änderung der Wegpunkt-Verwaltung (eigener Spec)
- Keine Änderung der GPX/JSON-Exporte
