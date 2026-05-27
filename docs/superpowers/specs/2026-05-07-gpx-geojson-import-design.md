# GPX/GeoJSON Import Design

**Goal:** Allow users to import GPX and GeoJSON files into an existing convoy, populating waypoints and/or the stored route geometry.

**Architecture:** Two new upload endpoints in `routing.py` backed by a new `services/importer.py` parsing module. Each endpoint accepts a multipart file upload and a `?mode=add|replace` query parameter. Access is guarded at `write` level (planer+).

**Tech Stack:** FastAPI multipart upload, gpxpy (already in requirements), stdlib `json`, SQLAlchemy async, PostGIS LineString.

---

## Endpoints

```
POST /api/convoys/{convoy_id}/import/gpx?mode=add|replace
POST /api/convoys/{convoy_id}/import/geojson?mode=add|replace
```

Both accept `multipart/form-data` with a single `file` field.

**Access control:** `get_convoy_access(convoy_id, current_user, db, require="write")` — planer or admin only.

**Response:**
```json
{"waypoints_imported": 3, "route_stored": true}
```

---

## `services/importer.py`

```python
@dataclass
class ImportResult:
    waypoints: list[dict]             # each: {name, lat, lon, notes}
    route_coords: list[tuple] | None  # [(lon, lat), ...] or None

def parse_gpx(content: bytes) -> ImportResult: ...
def parse_geojson(content: bytes) -> ImportResult: ...
```

Raises `ValueError` with a human-readable message on parse failure or empty content.

---

## Data Mapping

### GPX → Waypoints (from `<wpt>` elements)

| GPX field | Waypoint field |
|---|---|
| `lat`, `lon` attributes | `lat`, `lon` |
| `<name>` | `name` (fallback: `"Waypoint {n}"`) |
| `<desc>` | `notes` |
| *(fixed)* | `type = "waypoint"` |
| *(fixed)* | `hold_duration_min = 0` |

### GPX → Route (from first `<trk>`)

Track points extracted as `[(lon, lat), ...]` and stored as a PostGIS `LINESTRING` in the `routes` table. `distance_m` and `duration_s` set to `None` (no routing recalculation triggered).

### GeoJSON → Waypoints (from `Point` features)

Accepts both a bare `Feature` and a `FeatureCollection`. Each `Point` geometry becomes a waypoint.

| GeoJSON field | Waypoint field |
|---|---|
| `geometry.coordinates[1]`, `[0]` | `lat`, `lon` |
| `properties.name` | `name` (fallback: `"Waypoint {n}"`) |
| `properties.description` or `properties.notes` | `notes` |
| *(fixed)* | `type = "waypoint"` |
| *(fixed)* | `hold_duration_min = 0` |

### GeoJSON → Route (from first `LineString` feature)

Coordinates array stored as PostGIS `LINESTRING`. `distance_m` / `duration_s` set to `None`.

---

## Import Mode

| `?mode=` | Behaviour |
|---|---|
| `replace` | Delete all existing `Waypoint` rows for the convoy, then insert imported waypoints starting at `order_index = 0` |
| `add` | Append imported waypoints after the last existing `order_index` |

`mode` is a required query parameter. Omitting it returns 422.

---

## Error Handling

| Condition | HTTP | Detail |
|---|---|---|
| File unparseable | 422 | `"Invalid GPX file"` / `"Invalid GeoJSON file"` |
| Valid file, no waypoints AND no route | 422 | `"No importable data found"` |
| Valid file, waypoints only | 200 | `{"waypoints_imported": N, "route_stored": false}` |
| Valid file, route only | 200 | `{"waypoints_imported": 0, "route_stored": true}` |
| beobachter / fahrer role | 403 | *(from guard)* |

---

## Frontend

In the planning view (`/plan`), add an **Import** button when a convoy is selected. It opens a file picker accepting `.gpx`, `.geojson`, `.json`. A mode toggle (Add / Replace) is shown before upload. On success the convoy store refreshes to show the new waypoints and route. No new route is required.

---

## Testing

New `backend/tests/test_import.py` covering:

- `parse_gpx`: waypoints + track → both returned
- `parse_gpx`: waypoints only → `route_coords = None`
- `parse_gpx`: track only → empty waypoints list, coords returned
- `parse_gpx`: invalid bytes → `ValueError`
- `parse_geojson`: FeatureCollection with Points + LineString → both returned
- `parse_geojson`: Points only → no route
- `parse_geojson`: invalid JSON → `ValueError`
- Endpoint `mode=replace`: existing waypoints deleted before insert
- Endpoint `mode=add`: waypoints appended with correct `order_index`
- Endpoint: `beobachter` role → 403 (via guard mock)
- Endpoint: empty file → 422
