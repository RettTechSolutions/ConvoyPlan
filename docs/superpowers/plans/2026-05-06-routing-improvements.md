# Routing-Verbesserungen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Genaue Fahrzeitberechnung auf Basis tatsächlicher Routenzusammensetzung, konfigurierbare Straßenpräferenz, und Fahrzeugabstände aus DB-Feldern im Marschbefehl.

**Architecture:** Vier neue Felder am Convoy-Modell (road_preference, spacing_*). GraphHopper wird mit `details: ["road_class"]` abgefragt; Zeitberechnung nutzt Haversine-Distanz pro Segment statt fixer Gewichtung. PDF liest Abstandswerte aus dem Modell.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, GraphHopper custom_model, Svelte 5.

---

## File Map

| Datei | Änderung |
|-------|----------|
| `backend/app/models/convoy.py` | +4 neue Felder |
| `backend/alembic/versions/0005_routing_fields.py` | neue Migration |
| `backend/app/schemas/convoy.py` | +4 Felder in Create/Update/Response |
| `backend/app/services/routing.py` | road_preference→custom_model, details→road_class, return details |
| `backend/app/api/routes/routing.py` | road_class-basierte Zeitberechnung |
| `backend/app/services/pdf.py` | Abstandswerte aus convoy-Objekt |
| `frontend/src/lib/api/index.ts` | +4 Felder in Convoy-Interface |
| `frontend/src/routes/plan/+page.svelte` | Form + Plan-Tab-Anzeige |

---

### Task 1: Convoy-Modell + Alembic-Migration

**Files:**
- Modify: `backend/app/models/convoy.py`
- Create: `backend/alembic/versions/0005_routing_fields.py`

- [ ] **Step 1: Felder zum Modell hinzufügen**

  In `backend/app/models/convoy.py`, nach der Zeile `speed_rural_kmh: Mapped[int] = mapped_column(Integer, default=65)` folgende vier Zeilen einfügen:

  ```python
      road_preference: Mapped[str] = mapped_column(String(20), default="schnell")
      spacing_urban_m: Mapped[int] = mapped_column(Integer, default=15)
      spacing_rural_m: Mapped[int] = mapped_column(Integer, default=50)
      spacing_motorway_m: Mapped[int] = mapped_column(Integer, default=100)
  ```

- [ ] **Step 2: Migrationsdatei erstellen**

  Neue Datei `backend/alembic/versions/0005_routing_fields.py`:

  ```python
  """routing fields for convoy

  Revision ID: 0005
  Revises: 0004
  Create Date: 2026-05-06
  """
  from alembic import op
  import sqlalchemy as sa

  revision = '0005'
  down_revision = '0004'
  branch_labels = None
  depends_on = None


  def upgrade() -> None:
      op.add_column('convoys', sa.Column('road_preference', sa.String(20), nullable=False, server_default='schnell'))
      op.add_column('convoys', sa.Column('spacing_urban_m', sa.Integer(), nullable=False, server_default='15'))
      op.add_column('convoys', sa.Column('spacing_rural_m', sa.Integer(), nullable=False, server_default='50'))
      op.add_column('convoys', sa.Column('spacing_motorway_m', sa.Integer(), nullable=False, server_default='100'))


  def downgrade() -> None:
      op.drop_column('convoys', 'road_preference')
      op.drop_column('convoys', 'spacing_urban_m')
      op.drop_column('convoys', 'spacing_rural_m')
      op.drop_column('convoys', 'spacing_motorway_m')
  ```

- [ ] **Step 3: Migration ausführen**

  ```bash
  docker compose exec backend alembic upgrade head
  ```

  Expected output enthält: `Running upgrade 0004 -> 0005`

- [ ] **Step 4: Felder in DB prüfen**

  ```bash
  docker compose exec db psql -U marschplan -d marschplan -c "\d convoys" | grep -E "road|spacing"
  ```

  Expected: 4 Zeilen mit `road_preference`, `spacing_urban_m`, `spacing_rural_m`, `spacing_motorway_m`.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/models/convoy.py backend/alembic/versions/0005_routing_fields.py
  git commit -m "feat(routing): add road_preference and spacing fields to Convoy model"
  ```

---

### Task 2: Schemas aktualisieren

**Files:**
- Modify: `backend/app/schemas/convoy.py`

- [ ] **Step 1: Felder zu `ConvoyCreate` hinzufügen**

  In `ConvoyCreate` nach `speed_rural_kmh: int = 65` einfügen:

  ```python
      road_preference: str = "schnell"
      spacing_urban_m: int = 15
      spacing_rural_m: int = 50
      spacing_motorway_m: int = 100
  ```

- [ ] **Step 2: Felder zu `ConvoyUpdate` hinzufügen**

  In `ConvoyUpdate` nach `speed_rural_kmh: int | None = None` einfügen:

  ```python
      road_preference: str | None = None
      spacing_urban_m: int | None = None
      spacing_rural_m: int | None = None
      spacing_motorway_m: int | None = None
  ```

- [ ] **Step 3: Felder zu `ConvoyResponse` hinzufügen**

  In `ConvoyResponse` nach `speed_rural_kmh: int` einfügen:

  ```python
      road_preference: str = "schnell"
      spacing_urban_m: int = 15
      spacing_rural_m: int = 50
      spacing_motorway_m: int = 100
  ```

- [ ] **Step 4: Backend neu starten und Schema prüfen**

  ```bash
  docker compose restart backend
  ```

  Dann:
  ```bash
  curl -s http://localhost:8000/health
  ```

  Expected: `{"status":"ok","version":"0.2.0"}`

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/schemas/convoy.py
  git commit -m "feat(routing): add road_preference and spacing fields to convoy schemas"
  ```

---

### Task 3: Routing-Service erweitern

**Files:**
- Modify: `backend/app/services/routing.py`

- [ ] **Step 1: Unit-Test für Haversine schreiben**

  Neue Datei `backend/tests/test_routing_utils.py`:

  ```python
  import pytest
  from math import isclose


  def _haversine_m(lon1, lat1, lon2, lat2) -> float:
      from math import radians, cos, sin, asin, sqrt
      R = 6_371_000
      dlon, dlat = radians(lon2 - lon1), radians(lat2 - lat1)
      a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
      return 2 * R * asin(sqrt(a))


  def test_haversine_known_distance():
      # Berlin Mitte → Hamburg Mitte ≈ 255 km (rough)
      d = _haversine_m(13.405, 52.52, 9.993, 53.551)
      assert 250_000 < d < 260_000


  def test_haversine_zero():
      d = _haversine_m(10.0, 48.0, 10.0, 48.0)
      assert isclose(d, 0.0, abs_tol=0.01)
  ```

- [ ] **Step 2: Test ausführen — soll FAIL**

  ```bash
  docker compose exec backend python -m pytest tests/test_routing_utils.py -v 2>&1 | head -20
  ```

  Expected: `ModuleNotFoundError` oder `ImportError` weil `tests/` nicht existiert.

  ```bash
  docker compose exec backend mkdir -p tests && docker compose exec backend touch tests/__init__.py
  docker compose exec backend python -m pytest tests/test_routing_utils.py -v
  ```

  Expected: PASS (die Hilfsfunktion ist inline im Test — kein Produktionscode nötig).

- [ ] **Step 3: `routing.py` komplett ersetzen**

  `backend/app/services/routing.py` mit folgendem Inhalt ersetzen:

  ```python
  from math import asin, cos, radians, sin, sqrt
  from typing import Any

  import httpx

  from app.config import settings

  URBAN_ROAD_CLASSES = {"residential", "living_street", "service"}

  _PRIORITY_RULES = {
      "schnell": [],
      "bundesstrasse": [
          {"if": "road_class == MOTORWAY", "multiply_by": "0.3"}
      ],
      "landstrasse": [
          {"if": "road_class == MOTORWAY || road_class == TRUNK", "multiply_by": "0.05"}
      ],
  }


  def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
      R = 6_371_000
      dlon, dlat = radians(lon2 - lon1), radians(lat2 - lat1)
      a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
      return 2 * R * asin(sqrt(a))


  def _segment_dist_m(coords: list, from_i: int, to_i: int) -> float:
      return sum(
          _haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
          for i in range(from_i, to_i)
      )


  async def calculate_route(
      points: list[dict[str, float]],
      vehicle_params: dict[str, Any] | None = None,
      road_preference: str = "schnell",
  ) -> dict:
      """Call GraphHopper routing API and return route data with road_class details."""
      payload: dict[str, Any] = {
          "points": [[p["lon"], p["lat"]] for p in points],
          "profile": "car",
          "instructions": False,
          "points_encoded": False,
          "details": ["road_class"],
      }

      priority_rules = list(_PRIORITY_RULES.get(road_preference, []))

      custom_model: dict[str, Any] = {}
      if vehicle_params and "max_height_m" in vehicle_params:
          custom_model["priority"] = [
              {"if": f"max_height < {vehicle_params['max_height_m']}", "multiply_by": "0"},
              *priority_rules,
          ]
      elif priority_rules:
          custom_model["priority"] = priority_rules

      if custom_model:
          payload["custom_model"] = custom_model

      async with httpx.AsyncClient(timeout=30.0) as client:
          resp = await client.post(
              f"{settings.graphhopper_url}/route",
              json=payload,
          )
          if not resp.is_success:
              try:
                  detail = resp.json().get("message", resp.text)
              except Exception:
                  detail = resp.text
              raise ValueError(f"GraphHopper {resp.status_code}: {detail}")
          data = resp.json()

      path = data["paths"][0]
      return {
          "distance_m": int(path["distance"]),
          "duration_s": int(path["time"] / 1000),
          "geometry": path["points"],
          "road_class_details": path.get("details", {}).get("road_class", []),
      }
  ```

- [ ] **Step 4: Unit-Test für `_segment_dist_m` erweitern**

  In `backend/tests/test_routing_utils.py` hinzufügen:

  ```python
  def test_segment_dist_two_points():
      # zwei Punkte 1 Grad Breitenunterschied ≈ 111 km
      coords = [[10.0, 48.0], [10.0, 49.0]]
      from app.services.routing import _segment_dist_m
      d = _segment_dist_m(coords, 0, 1)
      assert 110_000 < d < 112_000


  def test_segment_dist_empty():
      from app.services.routing import _segment_dist_m
      d = _segment_dist_m([[10.0, 48.0], [10.0, 49.0]], 0, 0)
      assert d == 0.0
  ```

- [ ] **Step 5: Tests ausführen**

  ```bash
  docker compose exec backend python -m pytest tests/test_routing_utils.py -v
  ```

  Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

  ```bash
  git add backend/app/services/routing.py backend/tests/
  git commit -m "feat(routing): road_preference custom_model, road_class details, haversine helpers"
  ```

---

### Task 4: Zeitberechnung im Endpoint

**Files:**
- Modify: `backend/app/api/routes/routing.py`

- [ ] **Step 1: Zeitberechnungs-Helfer-Funktion extrahieren**

  Am Anfang von `backend/app/api/routes/routing.py`, nach den Imports, neue Funktion einfügen:

  ```python
  from app.services.routing import URBAN_ROAD_CLASSES, _segment_dist_m


  def _convoy_duration_s(
      distance_m: int,
      coords: list,
      road_class_details: list,
      speed_urban_kmh: int,
      speed_rural_kmh: int,
  ) -> int:
      """Calculate convoy travel time using actual road class distribution."""
      if road_class_details and coords:
          urban_dist = 0.0
          nonurban_dist = 0.0
          for from_i, to_i, rc in road_class_details:
              d = _segment_dist_m(coords, from_i, to_i)
              if rc.lower() in URBAN_ROAD_CLASSES:
                  urban_dist += d
              else:
                  nonurban_dist += d
          h = urban_dist / 1000 / speed_urban_kmh + nonurban_dist / 1000 / speed_rural_kmh
      else:
          # Fallback: fixed 70/30 split
          avg_speed = 0.7 * speed_rural_kmh + 0.3 * speed_urban_kmh
          h = distance_m / 1000 / avg_speed
      return max(1, int(h * 3600))
  ```

- [ ] **Step 2: `calculate_route`-Endpoint anpassen**

  In der `calculate_route`-Funktion (ca. Zeile 49–52), den `routing_svc.calculate_route`-Aufruf erweitern:

  ```python
      try:
          route_data = await routing_svc.calculate_route(
              points,
              vehicle_params or None,
              road_preference=convoy.road_preference,
          )
      except Exception as exc:
          raise HTTPException(status_code=502, detail=f"Routing failed: {exc}")
  ```

- [ ] **Step 3: Zeitberechnung ersetzen**

  Die bestehenden zwei Zeilen zur Zeitberechnung:
  ```python
      # Calculate convoy-appropriate duration (GraphHopper uses car speeds, convoys are slower)
      distance_km = route_data["distance_m"] / 1000
      avg_speed_kmh = 0.7 * convoy.speed_rural_kmh + 0.3 * convoy.speed_urban_kmh
      convoy_duration_s = int((distance_km / avg_speed_kmh) * 3600)
  ```

  Ersetzen durch:
  ```python
      coords = route_data["geometry"].get("coordinates", [])
      convoy_duration_s = _convoy_duration_s(
          route_data["distance_m"],
          coords,
          route_data.get("road_class_details", []),
          convoy.speed_urban_kmh,
          convoy.speed_rural_kmh,
      )
  ```

- [ ] **Step 4: Unit-Test für `_convoy_duration_s` schreiben**

  In `backend/tests/test_routing_utils.py` hinzufügen:

  ```python
  def test_convoy_duration_with_details():
      from app.api.routes.routing import _convoy_duration_s
      # 10 km komplett urban → 10/40 h = 0.25 h = 900 s
      coords = [[10.0, 48.0], [10.0, 48.09]]  # ~10 km
      details = [[0, 1, "residential"]]
      # Actual haversine distance for this segment ≈ 10.008 km
      d = _convoy_duration_s(10_000, coords, details, speed_urban_kmh=40, speed_rural_kmh=65)
      # 10 km / 40 km/h = 900 s, allow ±60 s for floating point
      assert 840 < d < 960


  def test_convoy_duration_fallback():
      from app.api.routes.routing import _convoy_duration_s
      # no details → fallback formula
      d = _convoy_duration_s(65_000, [], [], speed_urban_kmh=40, speed_rural_kmh=65)
      # avg = 0.7*65 + 0.3*40 = 57.5 km/h → 65/57.5 h ≈ 4061 s
      assert 4000 < d < 4120
  ```

- [ ] **Step 5: Tests ausführen**

  ```bash
  docker compose exec backend python -m pytest tests/test_routing_utils.py -v
  ```

  Expected: 6 tests PASS.

- [ ] **Step 6: Backend neu starten und Route-Berechnung testen**

  ```bash
  docker compose restart backend
  ```

  Dann in der App eine Route berechnen und prüfen ob die Fahrzeit plausibel ist (kein 3-Sekunden-Trip mehr).

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/api/routes/routing.py backend/tests/test_routing_utils.py
  git commit -m "feat(routing): accurate convoy duration via road_class segment distances"
  ```

---

### Task 5: PDF-Service aktualisieren

**Files:**
- Modify: `backend/app/services/pdf.py`

- [ ] **Step 1: Hardcodierte Abstandswerte ersetzen**

  In `backend/app/services/pdf.py`, den Block „Fahrzeugabstände" (ca. Zeile 196–205) finden. Er sieht so aus:

  ```python
      # Fahrzeugabstände
      _subsection(pdf, "Fahrzeugabstände")
      pdf.set_font("Helvetica", "", 9)
      pdf.multi_cell(
          0, 5,
          "  • 50 Meter bei Marschgeschwindigkeit bis 50 km/h\n"
          "  • 100 Meter bei Marschgeschwindigkeit über 50 km/h\n"
          "  • Mindestens 100 Meter auf Autobahnen und Schnellstraßen"
      )
      pdf.ln(2)
  ```

  Ersetzen durch:

  ```python
      # Fahrzeugabstände
      _subsection(pdf, "Fahrzeugabstände")
      pdf.set_font("Helvetica", "", 9)
      pdf.multi_cell(
          0, 5,
          f"  • Innerorts: {getattr(convoy, 'spacing_urban_m', 15)} m\n"
          f"  • Außerorts: {getattr(convoy, 'spacing_rural_m', 50)} m\n"
          f"  • Autobahn: {getattr(convoy, 'spacing_motorway_m', 100)} m"
      )
      pdf.ln(2)
  ```

- [ ] **Step 2: PDF generieren und prüfen**

  In der App einen Marschbefehl als PDF exportieren. Im Abschnitt „Fahrzeugabstände" müssen die Werte des Verbands erscheinen (bei Defaults: 15m / 50m / 100m).

- [ ] **Step 3: Commit**

  ```bash
  git add backend/app/services/pdf.py
  git commit -m "feat(routing): use convoy spacing fields in Marschbefehl PDF"
  ```

---

### Task 6: Frontend — Typen, Formular, Anzeige

**Files:**
- Modify: `frontend/src/lib/api/index.ts`
- Modify: `frontend/src/routes/plan/+page.svelte`

- [ ] **Step 1: `Convoy`-Interface in `index.ts` erweitern**

  In `frontend/src/lib/api/index.ts`, im `Convoy`-Interface nach `speed_rural_kmh: number;` einfügen:

  ```typescript
  	road_preference: string;
  	spacing_urban_m: number;
  	spacing_rural_m: number;
  	spacing_motorway_m: number;
  ```

- [ ] **Step 2: `newConvoy`-State erweitern**

  In `frontend/src/routes/plan/+page.svelte`, die `newConvoy`-State-Zeile (ca. Zeile 43):
  ```typescript
  let newConvoy = $state({ name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, lage:'', auftrag:'', marschform:'geschlossener_verband', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', versorgung:'', funkgruppe:'', anlagen:'' });
  ```

  Ersetzen durch:
  ```typescript
  let newConvoy = $state({ name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, road_preference:'schnell', spacing_urban_m:15, spacing_rural_m:50, spacing_motorway_m:100, lage:'', auftrag:'', marschform:'geschlossener_verband', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', versorgung:'', funkgruppe:'', anlagen:'' });
  ```

  Ebenso die Reset-Zeile in `createConvoy()` (ca. Zeile 94) identisch aktualisieren.

- [ ] **Step 3: `createConvoy()`-Payload erweitern**

  In der `createConvoy()`-Funktion (ca. Zeile 83–88), nach `speed_rural_kmh: newConvoy.speed_rural_kmh,` hinzufügen:

  ```typescript
  			road_preference: newConvoy.road_preference,
  			spacing_urban_m: newConvoy.spacing_urban_m,
  			spacing_rural_m: newConvoy.spacing_rural_m,
  			spacing_motorway_m: newConvoy.spacing_motorway_m,
  ```

- [ ] **Step 4: Formular-Felder im Modal hinzufügen**

  Im Convoy-Erstellen-Modal (ca. Zeile 750–757), nach den Geschwindigkeitsfeldern und vor dem Hinweis-Text einfügen:

  ```svelte
  				<label>Straßenpräferenz
  					<select bind:value={newConvoy.road_preference}>
  						<option value="schnell">Schnellste Route (Autobahn erlaubt)</option>
  						<option value="bundesstrasse">Bundesstraßen bevorzugt</option>
  						<option value="landstrasse">Nur Landstraßen</option>
  					</select>
  				</label>
  				<label>Fahrzeugabstand Innerorts (m)<input type="number" bind:value={newConvoy.spacing_urban_m} min="5" max="200" /></label>
  				<label>Fahrzeugabstand Außerorts (m)<input type="number" bind:value={newConvoy.spacing_rural_m} min="10" max="500" /></label>
  				<label>Fahrzeugabstand Autobahn (m)<input type="number" bind:value={newConvoy.spacing_motorway_m} min="10" max="500" /></label>
  ```

- [ ] **Step 5: Plan-Tab-Anzeige ergänzen**

  Im Plan-Tab (ca. Zeile 348), die Tempo-Zeile:
  ```svelte
  						<p><strong>Tempo:</strong> {selected.speed_urban_kmh} km/h (innerorts) / {selected.speed_rural_kmh} km/h (außerorts)</p>
  ```

  Ersetzen durch:
  ```svelte
  						<p><strong>Tempo:</strong> {selected.speed_urban_kmh} km/h (innerorts) / {selected.speed_rural_kmh} km/h (außerorts) · {{ schnell: 'Autobahn', bundesstrasse: 'Bundesstr.', landstrasse: 'Landstr.' }[selected.road_preference] ?? selected.road_preference}</p>
  						<p><strong>Abstände:</strong> {selected.spacing_urban_m} m / {selected.spacing_rural_m} m / {selected.spacing_motorway_m} m (i/a/BAB)</p>
  ```

- [ ] **Step 6: Frontend neu bauen und testen**

  ```bash
  docker compose build frontend && docker compose up -d --no-deps frontend
  ```

  Prüfen:
  - Neuer Verband erstellen: Straßenpräferenz und Abstandsfelder erscheinen im Modal
  - Nach Erstellen: Plan-Tab zeigt Präferenz und Abstände
  - Route berechnen: Fahrzeit ändert sich je nach gewählter Präferenz (Landstraße → längere Zeit als Autobahn)

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/src/lib/api/index.ts frontend/src/routes/plan/+page.svelte
  git commit -m "feat(routing): road_preference and spacing fields in convoy form and plan tab"
  ```
