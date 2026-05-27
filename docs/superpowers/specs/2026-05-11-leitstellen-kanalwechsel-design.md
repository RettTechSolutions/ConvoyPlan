# Leitstellen-Verzeichnis & automatische Kanalwechsel

## Überblick

Systemweites Verzeichnis aller Leitstellen (ILS, RLS usw.) mit Gebietsgrenzen als PostGIS-Polygone. Bei der Routenberechnung wird automatisch erkannt, wo der Marsch Leitstellengrenzen überquert — die Kanalwechsel werden im Marschbefehl und der Wegpunktliste ausgegeben.

---

## Datenmodell

### Neue Tabelle `leitstellen`

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | UUID PK | |
| `name` | String(100) | z.B. "ILS München" |
| `anrufgruppe` | String(50) | Primärer Kanal, z.B. "468" |
| `zusatz_kanaele` | JSON | `[{"name": "Führungskanal", "kanal": "469"}, …]` |
| `geometry` | PostGIS Geometry(Polygon/MultiPolygon, 4326) | Zuständigkeitsgebiet |
| `created_at` | DateTime | |

Kein Org-Bezug — systemweit, für alle Nutzer lesbar.

### Erweiterung `routes`-Tabelle

Neues JSON-Feld `kanalwechsel`:

```json
[
  {
    "km": 34.2,
    "lat": 47.856,
    "lon": 12.103,
    "leitstelle_id": "uuid",
    "leitstelle_name": "ILS Rosenheim",
    "anrufgruppe": "438"
  }
]
```

Wird bei jeder Routenberechnung neu befüllt. Leere Liste wenn keine Grenzen geschnitten werden.

---

## Backend

### Neuer Router `app/api/routes/leitstellen.py`

| Method | Endpoint | Auth | Funktion |
|--------|----------|------|---------|
| GET | `/api/leitstellen` | eingeloggt | Alle Leitstellen (ohne Geometrie) |
| GET | `/api/leitstellen/{id}` | eingeloggt | Einzelne Leitstelle inkl. GeoJSON-Polygon |
| POST | `/api/leitstellen` | superuser | Neue Leitstelle anlegen |
| PUT | `/api/leitstellen/{id}` | superuser | Name/Kanäle/Polygon editieren |
| DELETE | `/api/leitstellen/{id}` | superuser | Löschen |
| POST | `/api/leitstellen/{id}/boundary` | superuser | GeoJSON- oder KML-Datei hochladen → Polygon überschreiben |

Superuser-Check über bestehendes `User.is_superuser`-Flag.

### Erweiterung `calculate_route`

Nach der GraphHopper-Berechnung, sobald die Route-Geometrie als PostGIS-LineString vorliegt:

```sql
SELECT ls.id, ls.name, ls.anrufgruppe,
       ST_AsGeoJSON(
         ST_Intersection(route_line, ST_Boundary(ls.geometry))
       ) AS crossing_geojson
FROM leitstellen ls
WHERE ST_Intersects(route_line, ls.geometry)
  AND ls.geometry IS NOT NULL
```

Kreuzungspunkte werden nach Distanz entlang der Route sortiert (`ST_LineLocatePoint`) und als `kanalwechsel`-JSON im Route-Record gespeichert.

### Schema-Erweiterung `RouteResponse`

```python
class KanalwechselEntry(BaseModel):
    km: float
    lat: float
    lon: float
    leitstelle_id: str
    leitstelle_name: str
    anrufgruppe: str

class RouteResponse(BaseModel):
    ...
    kanalwechsel: list[KanalwechselEntry] = []
```

---

## Frontend

### Admin-Seite (`/admin`) – neuer Tab "Leitstellen"

**Listenansicht:**
- Tabelle: Name | Anrufgruppe | Zusatzkanäle (Anzahl) | Grenzen (✓/✗) | Aktionen
- Edit/Löschen nur für Superuser sichtbar

**Erstellen/Editieren – Modal:**

*Formular:*
- Name (Textfeld)
- Anrufgruppe (Textfeld)
- Zusatzkanäle (dynamische Liste: Bezeichnung + Kanalwert, + Zeile hinzufügen)

*Karte (MapLibre):*
- Polygon zeichnen: Klick = Vertex, Doppelklick = schließen, Reset-Button löscht Polygon
- Bestehendes Polygon wird in Rot angezeigt
- GeoJSON/KML-Datei-Upload überschreibt das aktuelle Polygon

### Routenplanung (`/plan`) – Wegpunktliste

Kanalwechsel werden als automatisch generierte, read-only Einträge zwischen den echten Wegpunkten eingeblendet:

```
● Start München
  ↓
📡 Wechsel → ILS Rosenheim  •  Anrufgruppe 438  •  km 34,2
  ↓
● Wegpunkt Rosenheim
  ↓
📡 Wechsel → ILS Traunstein  •  Anrufgruppe 452  •  km 67,8
  ↓
● Ziel Traunstein
```

- Anderer visueller Stil als Wegpunkte (grauer Hintergrund, 📡-Icon)
- Hover über Leitstellenname → Tooltip mit Zusatzkanälen
- Nicht verschiebbar, werden bei neuer Routenberechnung automatisch aktualisiert

### Routenplanung (`/plan`) – Marschbefehl-Tab

Neuer Unterabschnitt "Kanalwechsel" (nur sichtbar wenn `kanalwechsel.length > 0`):

| km | Leitstelle | Anrufgruppe |
|----|-----------|-------------|
| 34,2 | ILS Rosenheim | 438 |
| 67,8 | ILS Traunstein | 452 |

Hover über Leitstellenname → Tooltip mit Zusatzkanälen (identisch mit Wegpunktliste).

### PDF-Export

Marschbefehl-PDF bekommt eine neue Sektion "Kanalwechsel" mit derselben Tabelle. Wird weggelassen wenn die Liste leer ist.

---

## Berechtigungen

| Aktion | Berechtigung |
|--------|-------------|
| Leitstellen lesen | Jeder eingeloggte User |
| Leitstellen anlegen/editieren/löschen | `is_superuser = True` |
| Kanalwechsel in Route sehen | Jeder mit Convoy-Zugriff (Beobachter+) |

---

## Nicht im Scope

- Leitstellengrenzen auf der Karte anzeigen (explizit ausgeschlossen)
- Kanalwechsel im Tracking-View als Marker
- Mehrere Kanalwechsel an exakt demselben Punkt (wird zusammengeführt)
- Offline-Verfügbarkeit des Verzeichnisses
