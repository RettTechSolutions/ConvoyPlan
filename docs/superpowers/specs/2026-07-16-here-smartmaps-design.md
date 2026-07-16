# SmartMaps mit Jahresdeckel — Design Spec

**Datum:** 2026-07-16
**Status:** Approved

> **Korrektur (2026-07-16):** Ursprünglich gegen HEREs Raster Tile API entworfen —
> „SmartMaps" ist aber der eigenständige Dienst **YellowMap SmartMaps**
> (smartmaps.net / tiles.smartmaps.cloud), nicht ein HERE-Produkt. Die
> umgesetzte Lösung nutzt daher den SmartMaps-Raster-Endpoint
> `https://tiles.smartmaps.cloud/tiles/v1/smartmaps/{style}/{z}/{x}/{y}.webp?apiKey=…`
> (WebP), einen **eigenen `SMARTMAPS_API_KEY`** (nicht den HERE-Key), Style-Config
> `SMARTMAPS_STYLE` (Default `light`) und `SMARTMAPS_YEARLY_LIMIT`. Architektur
> (Backend-Proxy + In-Memory-Jahreszähler + OSM-Fallback + Toggle) ist unverändert;
> unten stehende HERE-spezifische Details (Endpoint, Key-Reuse, PNG) sind durch
> diese Korrektur ersetzt.

## Ziel

HERE SmartMaps (aktuell: HERE Raster Tile API v3) als zusätzliche, optionale Kartenansicht in der
Hauptkarte (`MapView.svelte`, Routenberechnung) anbieten — umschaltbar neben der bestehenden
OSM-Basemap. Analog zum bestehenden Geocoding-Kostendeckel (`HERE_MONTHLY_LIMIT`, siehe
`backend/app/services/geocoding.py`) wird ein App-seitiger Jahresdeckel eingezogen, damit das
HERE-Freikontingent nicht überschritten und keine Kosten ausgelöst werden.

HERE stellt für SmartMaps ein Freikontingent von 300.000 Tile-Requests/Jahr. Der App-Deckel wird
mit Sicherheitspuffer darunter gesetzt (analog zum Verhältnis 25.000/30.000 bei der Geokodierung):

```
here_smartmaps_yearly_limit: int = 250000   # 0 = Deckel deaktiviert
```

## Warum kein 1:1-Muster wie beim Geocoding-Deckel

Der Geocoding-Deckel schreibt synchron pro Request in die DB (`system_settings`-Tabelle, ein
Commit pro Autosuggest-Anfrage) — das ist bei Adresssuche unkritisch, da Anfragen debounced und
selten sind. Kartenkacheln entstehen dagegen in Bürsten: ein einzelner Kartenschwenk oder Zoom
kann 20–50 Tile-Requests auslösen. Ein synchroner DB-Commit pro Tile würde die DB unnötig belasten.
Deshalb: In-Memory-Zähler mit periodischem Flush statt Sync-Write pro Request.

Das Backend läuft laut `docker-compose.yml` als einzelner `uvicorn`-Prozess ohne `--workers` und
ohne `deploy.replicas` — ein In-Memory-Zähler ist also nicht von Multi-Process-Races betroffen.
Er überlebt aber keinen Prozess-Neustart ohne Flush, daher der periodische + shutdown-Flush.

## Backend

### Config (`backend/app/config.py`)

```python
here_smartmaps_yearly_limit: int = 250000  # Puffer unter 300k Freikontingent; 0 = deaktiviert
```

Kein neuer API-Key: die Route nutzt die bestehende `resolve_here_key()`-Auflösung aus
`geocoding.py` (dedizierter `here_api_key` oder Fallback auf den gespeicherten Traffic-Key) — HERE
stellt ohnehin einen Key für alle Produkte aus.

### Neuer Service: `backend/app/services/smartmaps.py`

Folgt dem Stil von `rate_limit.py` (In-Memory-State mit dokumentierter Multi-Replica-Einschränkung)
und `update_notify.py` (periodischer `asyncio`-Loop, in `lifespan` gestartet).

Modul-globaler State:

```python
_flushed: dict[str, int] = {}   # Jahr -> zuletzt aus der DB gelesener Stand
_pending: dict[str, int] = {}   # Jahr -> noch nicht geflushte Increments
_lock = asyncio.Lock()
```

- `usage_key(year: str) -> str`: `f"smartmaps.tile_usage.{year}"` (analog
  `geocode.here_usage.<YYYY-MM>`, gleiche `system_settings`-Tabelle, kein neues Model/Migration).
- `async def reserve_tile_quota(db, year, limit) -> bool`: lädt `_flushed[year]` lazy aus
  `system_settings`, falls noch nicht im Speicher. Prüft unter `_lock`:
  `_flushed.get(year, 0) + _pending.get(year, 0) < limit`. Bei `limit <= 0` immer `True`
  (Deckel deaktiviert). Wenn Platz: `_pending[year] += 1`, `True`. Sonst `False`.
- `async def flush_pending(db)`: für jedes Jahr mit `_pending > 0` — read-modify-write auf
  `system_settings` (gleiches Pattern wie `reserve_here_quota` in `geocoding.py`), danach
  `_flushed[year] += _pending[year]`, `_pending[year] = 0`.
- `async def smartmaps_flush_loop()`: `while True: await asyncio.sleep(30); flush_pending(...)`,
  mit `try/except Exception` um den Body (Loop darf nicht sterben), `except asyncio.CancelledError:
  raise` für sauberen Shutdown.

In `backend/app/main.py`s `_lifespan`: `smartmaps_flush_loop()` als zweiter `asyncio.create_task`
neben `update_notify_loop()`; im `finally`-Block Task canceln, `gather`, und einmal final
`flush_pending()` aufrufen, damit bei Redeploys kein Zählstand verloren geht.

Docstring-Hinweis (analog `rate_limit.py`): In-Memory-Zähler ist nicht multi-replica-sicher; falls
`backend` je horizontal skaliert wird, braucht es einen shared Store (Redis o.ä.).

### Neue Route: `backend/app/api/routes/tiles.py`

```
GET /tiles/here/{z}/{x}/{y}
```

- **Auth:** geschützt wie Geocoding (`get_current_user`) — kein öffentlicher Endpunkt.
- **Ablauf:**
  1. Key auflösen (`resolve_here_key`). Kein Key, oder `here_smartmaps_yearly_limit > 0` und
     `reserve_tile_quota()` liefert `False` → **302-Redirect** auf
     `https://tile.openstreetmap.org/{z}/{x}/{y}.png` (stiller Fallback; keine CSP-Änderung nötig,
     da diese Domain bereits in `img-src` erlaubt ist, siehe `caddy/entrypoint.sh:45` und
     `backend/app/api/routes/setup.py:43,46`).
  2. Sonst: Tile von
     `https://maps.hereapi.com/v3/base/mc/{z}/{x}/{y}/png8?style=explore.day&apiKey=<key>`
     serverseitig holen (HERE Raster Tile API v3) und als `image/png` proxen — same-origin, keine
     CSP-Änderung für die HERE-Domain nötig.
  3. Bei HERE-Fehler (Timeout/Non-2xx): ebenfalls 302-Redirect auf den OSM-Tile-Fallback. Das
     bereits reservierte Kontingent (`_pending`-Increment) wird nicht zurückgerollt — analog zum
     bestehenden Verhalten bei der Geokodierung (Reservierung passiert vor dem HERE-Call).

## Frontend

### `MapView.svelte`

Neuer Custom-Control-Button neben `NavigationControl` (oben rechts), togglet die aktive
Raster-Source zwischen der bestehenden `osm`-Source und einer neuen `here-smartmaps`-Source:

```js
{
  type: 'raster',
  tiles: ['/api/tiles/here/{z}/{x}/{y}'],
  tileSize: 256,
  attribution: '© HERE',
}
```

Same-origin-Request, Auth-Cookie geht automatisch mit. Standard bleibt OSM (Toggle-Zustand als
lokaler `$state`, kein neuer globaler Store — YAGNI, analog zur Begründung im Demo-Banner-Spec).

Kein Rollout auf `LeitstellenOverviewMap.svelte` oder `LeitstelleAreaPicker.svelte` — nur die
Hauptkarte zur Routenberechnung.

## Testing

- Unit-Tests für `reserve_tile_quota`/`flush_pending`: Grenzfall Limit erreicht, Jahr-Rollover,
  Flush-Verhalten (pending → flushed), Deckel deaktiviert (`limit = 0`).
- Route-Test: bei erschöpftem Deckel liefert `GET /tiles/here/{z}/{x}/{y}` einen 302-Redirect auf
  die OSM-Tile-URL.
- Route-Test: erfolgreicher HERE-Fetch wird als `image/png` durchgereicht (HERE-Call gemockt).

## Nicht im Scope

- Vector-Tile-API (nur Raster, analog zur bestehenden OSM-Raster-Integration).
- SmartMaps in `LeitstellenOverviewMap.svelte` oder `LeitstelleAreaPicker.svelte`.
- Admin-UI zur Anzeige des aktuellen Tile-Verbrauchs (wie beim Geocoding-Deckel: rein intern,
  keine Oberfläche).
- Shared-Store-Lösung (Redis) für Multi-Replica-Betrieb — aktuell nicht relevant, da Backend als
  Single-Process läuft.
