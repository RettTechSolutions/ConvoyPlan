# Kartenregion im Admin-Panel — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Kartenregion einer Instanz lässt sich aus dem Admin-Panel wechseln, ohne SSH und ohne stundenlangen Routing-Ausfall.

**Architecture:** Das Backend schreibt eine Absichtsdatei in das geteilte Volume `update_status`; der Updater-Container — der einzige mit Docker-Socket — pollt sie und führt den Wechsel in fünf Phasen aus. Der Graph wird in einem Wegwerf-Container gebaut, während der laufende GraphHopper in Betrieb bleibt; nur der abschließende Schwenk kostet einen Neustart. Die aktive Region wird als `.region` im `osm_data`-Volume persistiert, nicht in der Host-`.env`.

**Tech Stack:** FastAPI + SQLAlchemy (Backend), Bash (Updater, GraphHopper-Entrypoint), Svelte 5 mit Runes (Panel), pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-03-kartenregion-im-adminpanel-design.md`

## Global Constraints

- Das Backend erhält **keinen** Docker-Socket und keinen Schreibzugriff auf Host-Dateien. Jede privilegierte Aktion läuft über den Updater.
- URL-Allowlist, beidseitig geprüft (Backend **und** Updater): Schema `https`, Host exakt `download.geofabrik.de`, Pfad endet auf `-latest.osm.pbf`, keine Redirects.
- Geteiltes Volume: `/update_status` (Backend ↔ Updater). Region-Persistenz: `/data/osm/.region` (Updater ↔ GraphHopper).
- `.region` trägt drei Werte: `OSM_DOWNLOAD_URL`, `OSM_FILENAME`, `JAVA_OPTS`.
- Fehlt `.region`, gilt unverändert das bisherige Env-Verhalten. Regressionsschutz für Bestandsinstallationen.
- Sicherheitsaufschlag 20 % auf jede RAM-Schätzung; Einstufung `knapp` ab 80 % Auslastung des Verfügbaren.
- Kein Abbruch ab Phase 4.
- Alle Endpunkte hinter `require_superadmin` (`backend/app/api/deps.py:217`).
- Historie ausschließlich über das vorhandene `AuditLog` (`backend/app/models/audit_log.py`) — keine neue Tabelle.

---

## File Structure

**Neu:**

| Datei | Verantwortung |
|---|---|
| `backend/app/services/geofabrik.py` | Index holen/cachen, URL validieren, Extract-Größe per HEAD |
| `backend/app/services/region_estimate.py` | Schätzformel RAM/Graph/Dauer, Urteilsbildung |
| `backend/app/services/region_switch.py` | Dateiprotokoll im geteilten Volume, Lock, Statuslesen |
| `backend/app/api/routes/region.py` | Die sieben Endpunkte |
| `backend/tests/test_geofabrik.py` | Validierung und Index-Parsing |
| `backend/tests/test_region_estimate.py` | Schätzung und Urteil |
| `backend/tests/test_region_api.py` | Endpunkte, 409-Logik, Audit |
| `docker/updater/switch-region.sh` | Die fünf Phasen |
| `docker/updater/tests/test_switch_region.sh` | Phasen gegen einen `docker`-Stub |
| `graphhopper/tests/test_region_file.sh` | `.region`-Vorrang |
| `frontend/src/lib/components/RegionCard.svelte` | Panel-Karte |

**Geändert:**

| Datei | Änderung |
|---|---|
| `backend/app/main.py:340` | Router registrieren |
| `backend/app/api/routes/admin.py:1141` | `trigger-update` prüft das Region-Lock |
| `backend/app/services/system_metrics.py:63` | `disk_paths()` um die Graph-/OSM-Pfade ergänzen |
| `graphhopper/entrypoint.sh:4-9` | `.region` vor Env |
| `docker/updater/update.sh:8` | Poll-Schleife holt `region_request.json` ab |
| `docker-compose.yml` | `osm_data` auch im Updater mounten |
| `frontend/src/lib/api/index.ts` | `regionApi` |
| `frontend/src/routes/admin/+page.svelte:2049` | Karte im `system`-Tab |
| `.env.example` | `REGION_SWITCH_ENABLED` dokumentieren |

---

## Task 1: Offene Annahmen klären und Konstanten festzurren

Die Spec (Abschnitt 9) hat vier Punkte offen gelassen. Sie zu raten würde jede spätere Zahl unbrauchbar machen — vor allem die Schätzformel, an der später die Antwort auf „passt Europa?" hängt.

**Files:**
- Create: `backend/app/services/region_estimate.py`
- Create: `backend/tests/test_region_estimate.py`
- Modify: `docs/superpowers/specs/2026-09-03-kartenregion-im-adminpanel-design.md` (Abschnitt 9 abhaken)

**Interfaces:**
- Produces: `PBF_SIZES: dict[str, int]`, `estimate_ram_bytes(pbf_bytes: int) -> int`, `estimate_graph_bytes(pbf_bytes: int) -> int`, `estimate_duration_minutes(pbf_bytes: int) -> tuple[int, int]`

- [ ] **Step 1: Reale Extract-Größen messen**

```bash
for r in europe/dach europe/germany europe/germany/bayern europe/germany/berlin europe; do
  sz=$(curl -sSIL "https://download.geofabrik.de/${r}-latest.osm.pbf" \
       | awk 'BEGIN{IFS=": "} tolower($1)=="content-length:"{v=$2} END{print v+0}')
  printf "%-28s %s Bytes (%.2f GB)\n" "$r" "$sz" "$(echo "$sz/1073741824" | bc -l)"
done
```

Die Ausgabe protokollieren — sie ist die Grundlage der Formel und wandert in den Docstring.

- [ ] **Step 2: `graphhopper.jar import` prüfen**

```bash
docker run --rm --entrypoint java \
  ghcr.io/retttechsolutions/convoyplan/graphhopper:latest \
  -jar /graphhopper/graphhopper.jar import --help
```

Beendet sich das mit Exit 0 und einer Nutzungsanzeige, gilt Annahme 1 als bestätigt. Andernfalls in Task 8 den `server`-Rückfall aus der Spec verwenden und hier vermerken.

- [ ] **Step 3: Failing Test schreiben**

```python
# backend/tests/test_region_estimate.py
import pytest
from app.services.region_estimate import (
    estimate_ram_bytes, estimate_graph_bytes, estimate_duration_minutes, verdict,
)

GB = 1024 ** 3

@pytest.mark.parametrize("pbf_gb,documented_ram_gb", [(0.7, 3), (4.0, 6), (5.5, 8)])
def test_estimate_matches_documented_installer_values(pbf_gb, documented_ram_gb):
    """Die Schätzung darf die Installer-Angaben nicht unterschreiten."""
    got = estimate_ram_bytes(int(pbf_gb * GB))
    assert got >= documented_ram_gb * GB

def test_estimate_includes_safety_margin():
    """20 % Aufschlag: die rohe Gerade allein reicht nicht."""
    raw = 2 * GB + int(1.1 * 5.5 * GB)
    assert estimate_ram_bytes(int(5.5 * GB)) >= int(raw * 1.2)

def test_verdict_tight_above_80_percent():
    assert verdict(needed=9 * GB, available=10 * GB) == "knapp"

def test_verdict_insufficient_when_over():
    assert verdict(needed=11 * GB, available=10 * GB) == "reicht nicht"

def test_verdict_ok_with_headroom():
    assert verdict(needed=4 * GB, available=10 * GB) == "ok"
```

- [ ] **Step 4: Test laufen lassen, Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_region_estimate.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.region_estimate'`

- [ ] **Step 5: Implementieren**

```python
# backend/app/services/region_estimate.py
"""Ressourcenschätzung für einen Regionswechsel.

Stützstellen sind die in scripts/install.sh:375 dokumentierten Werte:
Bayern >= 3 GB, Deutschland >= 6 GB, DACH >= 8 GB. Die Extract-Groessen
dazu stammen aus Task 1, Step 1 (HTTP-HEAD gegen Geofabrik) — die Zahlen
im Docstring dort eintragen, damit spaetere Leser die Herleitung sehen.
"""

GB = 1024 ** 3

_BASE_BYTES = 2 * GB          # JVM, Betriebssystem, GraphHopper-Grundlast
_PER_PBF_BYTE = 1.1           # Steigung der Geraden durch die drei Stuetzstellen
_SAFETY_MARGIN = 1.2          # 20 % Aufschlag (Spec Abschnitt 6)
_MINUTES_PER_GB_LOW = 12
_MINUTES_PER_GB_HIGH = 22
_TIGHT_THRESHOLD = 0.8


def estimate_ram_bytes(pbf_bytes: int) -> int:
    """Geschaetzter Heap-Bedarf des Imports, inklusive Sicherheitsaufschlag."""
    raw = _BASE_BYTES + int(_PER_PBF_BYTE * pbf_bytes)
    return int(raw * _SAFETY_MARGIN)


def estimate_graph_bytes(pbf_bytes: int) -> int:
    """Der gebaute Graph liegt erfahrungsgemaess in der Groessenordnung des Extracts."""
    return int(pbf_bytes * 1.5)


def estimate_duration_minutes(pbf_bytes: int) -> tuple[int, int]:
    gb = pbf_bytes / GB
    return (max(1, int(gb * _MINUTES_PER_GB_LOW)), max(2, int(gb * _MINUTES_PER_GB_HIGH)))


def verdict(needed: int, available: int) -> str:
    """'ok' | 'knapp' | 'reicht nicht' — die Einstufung fuer das Panel."""
    if needed > available:
        return "reicht nicht"
    if needed > available * _TIGHT_THRESHOLD:
        return "knapp"
    return "ok"
```

- [ ] **Step 6: Test laufen lassen, Erfolg bestätigen**

Run: `cd backend && pytest tests/test_region_estimate.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/region_estimate.py backend/tests/test_region_estimate.py \
        docs/superpowers/specs/2026-09-03-kartenregion-im-adminpanel-design.md
git commit -m "feat(region): Ressourcenschätzung mit belegten Stützstellen"
```

---

## Task 2: Geofabrik-Anbindung und URL-Validierung

**Files:**
- Create: `backend/app/services/geofabrik.py`
- Create: `backend/tests/test_geofabrik.py`

**Interfaces:**
- Produces: `validate_region_url(url: str) -> str` (wirft `ValueError`), `head_size_bytes(url: str) -> int`, `fetch_index() -> list[RegionEntry]`, `RegionEntry(id, name, path, url, size_bytes)`

- [ ] **Step 1: Failing Test schreiben**

Die Umgehungsversuche sind der Kern — die URL landet in einem Container mit Docker-Socket.

```python
# backend/tests/test_geofabrik.py
import pytest
from app.services.geofabrik import validate_region_url

OK = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"

def test_accepts_canonical_geofabrik_url():
    assert validate_region_url(OK) == OK

@pytest.mark.parametrize("bad", [
    "http://download.geofabrik.de/europe/dach-latest.osm.pbf",      # kein TLS
    "https://evil.example/europe/dach-latest.osm.pbf",              # fremder Host
    "https://download.geofabrik.de.evil.example/x-latest.osm.pbf",  # Suffix-Trick
    "https://download.geofabrik.de/europe/dach-latest.osm.bz2",     # falsche Endung
    "https://download.geofabrik.de/../etc/passwd-latest.osm.pbf",   # Traversal
    "https://user@download.geofabrik.de/e-latest.osm.pbf",          # Userinfo
    "file:///data/osm/x-latest.osm.pbf",                            # anderes Schema
])
def test_rejects_everything_else(bad):
    with pytest.raises(ValueError):
        validate_region_url(bad)
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_geofabrik.py -v`
Expected: FAIL mit `ModuleNotFoundError`

- [ ] **Step 3: Implementieren**

```python
# backend/app/services/geofabrik.py
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_HOST = "download.geofabrik.de"
_SUFFIX = "-latest.osm.pbf"
_INDEX_URL = f"https://{_HOST}/index-v1.json"


def validate_region_url(url: str) -> str:
    """Laesst ausschliesslich kanonische Geofabrik-Extract-URLs durch.

    Die URL wandert zum Updater, der sie mit Docker-Socket herunterlaedt —
    ohne diese Schranke waere das ein Primitiv fuer beliebige Downloads.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Nur https ist zulässig.")
    if parsed.username or parsed.password:
        raise ValueError("Zugangsdaten in der URL sind nicht zulässig.")
    if parsed.hostname != _HOST:
        raise ValueError(f"Nur {_HOST} ist als Quelle zugelassen.")
    if not parsed.path.endswith(_SUFFIX):
        raise ValueError(f"Der Pfad muss auf {_SUFFIX} enden.")
    if ".." in parsed.path:
        raise ValueError("Der Pfad darf keine Rückwärtsverweise enthalten.")
    return url


def head_size_bytes(url: str) -> int:
    """Groesse des Extracts, ohne es zu laden. Folgt bewusst keinen Redirects."""
    validate_region_url(url)
    with httpx.Client(follow_redirects=False, timeout=15) as client:
        resp = client.head(url)
    if resp.status_code != 200:
        raise ValueError(f"Extract nicht abrufbar (HTTP {resp.status_code}).")
    return int(resp.headers.get("content-length", 0))


@dataclass(frozen=True)
class RegionEntry:
    id: str
    name: str
    path: str        # "Europe › Germany › Bayern"
    url: str
    size_bytes: int | None
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `cd backend && pytest tests/test_geofabrik.py -v`
Expected: PASS (8 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/geofabrik.py backend/tests/test_geofabrik.py
git commit -m "feat(region): Geofabrik-URL-Allowlist und HEAD-Größenabfrage"
```

---

## Task 3: Dateiprotokoll im geteilten Volume

**Files:**
- Create: `backend/app/services/region_switch.py`
- Create: `backend/tests/test_region_switch.py`

**Interfaces:**
- Consumes: nichts
- Produces: `REQUEST_FILE`, `STATUS_FILE`, `LOG_FILE`, `CANCEL_FILE`, `LOCK_FILE`; `write_request(url, filename, java_opts, actor_email) -> None`, `read_status() -> dict`, `is_busy() -> bool`, `request_cancel() -> None`

- [ ] **Step 1: Failing Test schreiben**

```python
# backend/tests/test_region_switch.py
import json
from app.services import region_switch


def test_write_request_creates_readable_json(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    region_switch.write_request(
        url="https://download.geofabrik.de/europe/dach-latest.osm.pbf",
        filename="dach-latest.osm.pbf",
        java_opts="-Xmx8g -Xms1g -XX:+UseG1GC",
        actor_email="admin@example.org",
    )
    data = json.loads((tmp_path / "region_request.json").read_text())
    assert data["url"].endswith("dach-latest.osm.pbf")
    assert data["java_opts"] == "-Xmx8g -Xms1g -XX:+UseG1GC"
    assert data["requested_by"] == "admin@example.org"
    assert "requested_at" in data


def test_is_busy_true_while_request_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    assert region_switch.is_busy() is False
    region_switch.write_request("https://download.geofabrik.de/e-latest.osm.pbf",
                                "e-latest.osm.pbf", "-Xmx4g", "a@b.c")
    assert region_switch.is_busy() is True


def test_read_status_defaults_to_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    assert region_switch.read_status()["phase"] == "idle"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_region_switch.py -v`
Expected: FAIL mit `ModuleNotFoundError`

- [ ] **Step 3: Implementieren**

```python
# backend/app/services/region_switch.py
"""Dateiprotokoll zwischen Backend und Updater.

Dieselbe Bruecke wie der bestehende Update-Trigger (admin.py:1141): Das
Backend schreibt eine Absicht in das geteilte Volume, der Updater pollt sie.
Das Backend fasst Docker nie an.
"""
import json
import os
from datetime import datetime, timezone

VOLUME = "/update_status"

REQUEST_FILE = "region_request.json"
STATUS_FILE = "region_status.json"
LOG_FILE = "region.log"
CANCEL_FILE = "region.cancel"
LOCK_FILE = "region.lock"


def _path(name: str) -> str:
    return os.path.join(VOLUME, name)


def write_request(url: str, filename: str, java_opts: str, actor_email: str) -> None:
    os.makedirs(VOLUME, exist_ok=True)
    payload = {
        "url": url,
        "filename": filename,
        "java_opts": java_opts,
        "requested_by": actor_email,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    # Erste Log-Zeile sofort, damit das Terminal nicht leer bleibt, waehrend
    # der Updater bis zu 10 s schlaeft — analog trigger_update().
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with open(_path(LOG_FILE), "w") as f:
        f.write(f"[{ts}] Regionswechsel angefordert — warte auf Updater…\n")
    with open(_path(REQUEST_FILE), "w") as f:
        json.dump(payload, f)


def read_status() -> dict:
    try:
        with open(_path(STATUS_FILE)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"phase": "idle"}


def is_busy() -> bool:
    return os.path.exists(_path(REQUEST_FILE)) or os.path.exists(_path(LOCK_FILE))


def request_cancel() -> None:
    with open(_path(CANCEL_FILE), "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `cd backend && pytest tests/test_region_switch.py -v`
Expected: PASS (3 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/region_switch.py backend/tests/test_region_switch.py
git commit -m "feat(region): Dateiprotokoll zwischen Backend und Updater"
```

---

## Task 4: Preview-Endpunkt

**Files:**
- Create: `backend/app/api/routes/region.py`
- Create: `backend/tests/test_region_api.py`
- Modify: `backend/app/main.py:340`

**Interfaces:**
- Consumes: `geofabrik.validate_region_url`, `geofabrik.head_size_bytes`, `region_estimate.*`, `host_metrics.read_memory`, `host_metrics.disk_usage`
- Produces: `POST /api/admin/region/preview` → `{extract_bytes, graph_bytes, ram_needed_bytes, ram_available_bytes, disk_free_bytes, duration_minutes: [int,int], verdict, reason}`

- [ ] **Step 1: Failing Test schreiben**

```python
# backend/tests/test_region_api.py
from app.services import geofabrik, region_estimate

GB = 1024 ** 3
URL = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"


def test_preview_returns_verdict_and_numbers(client, superadmin_headers, monkeypatch):
    monkeypatch.setattr(geofabrik, "head_size_bytes", lambda url: int(5.5 * GB))
    resp = client.post("/api/admin/region/preview", json={"url": URL},
                       headers=superadmin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["extract_bytes"] == int(5.5 * GB)
    assert body["verdict"] in {"ok", "knapp", "reicht nicht"}
    assert body["reason"]


def test_preview_rejects_foreign_host(client, superadmin_headers):
    resp = client.post("/api/admin/region/preview",
                       json={"url": "https://evil.example/x-latest.osm.pbf"},
                       headers=superadmin_headers)
    assert resp.status_code == 400


def test_preview_requires_superadmin(client):
    resp = client.post("/api/admin/region/preview", json={"url": URL})
    assert resp.status_code == 401
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_region_api.py -v`
Expected: FAIL mit 404 (Route existiert nicht)

- [ ] **Step 3: Implementieren**

```python
# backend/app/api/routes/region.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_superadmin
from app.models.user import User
from app.services import geofabrik, region_estimate
from app.services.host_metrics import disk_usage, read_memory

router = APIRouter(prefix="/admin/region", tags=["admin"])

OSM_PATH = "/data/osm"


class RegionUrl(BaseModel):
    url: str


@router.post("/preview")
async def preview(body: RegionUrl, _: User = Depends(require_superadmin)):
    try:
        geofabrik.validate_region_url(body.url)
        extract = geofabrik.head_size_bytes(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    graph = region_estimate.estimate_graph_bytes(extract)
    ram_needed = region_estimate.estimate_ram_bytes(extract)
    mem = read_memory()
    ram_available = mem.available_bytes if mem else 0
    disks = disk_usage([OSM_PATH])
    disk_free = disks[0].free_bytes if disks else 0

    # Waehrend des Wechsels liegen altes und neues Extract plus beide Graphen
    # gleichzeitig auf der Platte — deshalb die doppelte Rechnung.
    disk_needed = extract + graph
    ram_verdict = region_estimate.verdict(ram_needed, ram_available)
    disk_verdict = region_estimate.verdict(disk_needed, disk_free)
    worst = "reicht nicht" if "reicht nicht" in (ram_verdict, disk_verdict) else (
        "knapp" if "knapp" in (ram_verdict, disk_verdict) else "ok"
    )

    def gb(n: int) -> str:
        return f"{n / (1024 ** 3):.1f} GB"

    reason = (
        f"Import braucht ~{gb(ram_needed)} Heap, verfügbar sind {gb(ram_available)}. "
        f"Auf der Platte werden ~{gb(disk_needed)} benötigt, frei sind {gb(disk_free)}."
    )
    return {
        "extract_bytes": extract,
        "graph_bytes": graph,
        "ram_needed_bytes": ram_needed,
        "ram_available_bytes": ram_available,
        "disk_needed_bytes": disk_needed,
        "disk_free_bytes": disk_free,
        "duration_minutes": list(region_estimate.estimate_duration_minutes(extract)),
        "verdict": worst,
        "reason": reason,
    }
```

In `backend/app/main.py` nach Zeile 351 ergänzen:

```python
app.include_router(region.router, prefix="/api")
```

und den Import oben bei den übrigen Routen mitführen.

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `cd backend && pytest tests/test_region_api.py -v`
Expected: PASS (3 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/region.py backend/tests/test_region_api.py backend/app/main.py
git commit -m "feat(region): Preview-Endpunkt mit Ressourcenurteil"
```

---

## Task 5: Auslösen, Status, Abbruch und gegenseitiger Ausschluss

**Files:**
- Modify: `backend/app/api/routes/region.py`
- Modify: `backend/app/api/routes/admin.py:1141`
- Modify: `backend/tests/test_region_api.py`

**Interfaces:**
- Consumes: `region_switch.write_request/read_status/is_busy/request_cancel`, `AuditLog`
- Produces: `POST /api/admin/region` (202), `GET /api/admin/region/status`, `POST /api/admin/region/cancel`, `GET /api/admin/regions`, `GET /api/admin/region`

- [ ] **Step 1: Failing Test schreiben**

```python
def test_switch_returns_202_and_writes_audit(client, superadmin_headers, db, monkeypatch):
    monkeypatch.setattr(geofabrik, "head_size_bytes", lambda url: int(1 * GB))
    resp = client.post("/api/admin/region", json={"url": URL}, headers=superadmin_headers)
    assert resp.status_code == 202
    from app.models.audit_log import AuditLog
    rows = db.query(AuditLog).filter(AuditLog.action == "region.switch_requested").all()
    assert len(rows) == 1
    assert rows[0].target_type == "region"


def test_switch_conflicts_with_running_update(client, superadmin_headers, monkeypatch):
    from app.api.routes import admin
    monkeypatch.setattr(admin.os.path, "exists", lambda p: p == admin.TRIGGER_FILE)
    resp = client.post("/api/admin/region", json={"url": URL}, headers=superadmin_headers)
    assert resp.status_code == 409


def test_update_trigger_conflicts_with_running_region_switch(
    client, superadmin_headers, monkeypatch
):
    from app.services import region_switch
    monkeypatch.setattr(region_switch, "is_busy", lambda: True)
    resp = client.post("/api/admin/trigger-update", headers=superadmin_headers)
    assert resp.status_code == 409
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_region_api.py -v`
Expected: FAIL — die drei neuen Tests scheitern mit 404 bzw. 202 statt 409

- [ ] **Step 3: Implementieren**

In `region.py` ergänzen:

```python
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.audit_log import AuditLog
from app.services import region_switch


def _audit(db: Session, action: str, actor: User, detail: dict) -> None:
    db.add(AuditLog(action=action, actor_id=actor.id, actor_email=actor.email,
                    target_type="region", detail=detail))
    db.commit()


@router.post("", status_code=202)
async def switch_region(body: RegionUrl, user: User = Depends(require_superadmin),
                        db: Session = Depends(get_db)):
    from app.api.routes.admin import TRIGGER_FILE
    if os.path.exists(TRIGGER_FILE) or region_switch.is_busy():
        raise HTTPException(409, "Es läuft bereits ein Update oder Regionswechsel.")
    try:
        url = geofabrik.validate_region_url(body.url)
        extract = geofabrik.head_size_bytes(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    ram = region_estimate.estimate_ram_bytes(extract)
    heap_gb = max(2, round(ram / (1024 ** 3)))
    java_opts = f"-Xmx{heap_gb}g -Xms1g -XX:+UseG1GC"
    filename = url.rsplit("/", 1)[-1]

    try:
        region_switch.write_request(url, filename, java_opts, user.email)
    except OSError as exc:
        raise HTTPException(
            503,
            "Regionswechsel konnte nicht ausgelöst werden: Das Update-Volume ist "
            "nicht beschreibbar. Der Updater repariert die Rechte automatisch beim "
            "nächsten Lauf — bitte in wenigen Minuten erneut versuchen.",
        ) from exc

    _audit(db, "region.switch_requested", user,
           {"url": url, "extract_bytes": extract, "java_opts": java_opts})
    return {"status": "requested"}


@router.get("/status")
async def status(_: User = Depends(require_superadmin)):
    return region_switch.read_status()


@router.post("/cancel", status_code=202)
async def cancel(user: User = Depends(require_superadmin)):
    if not region_switch.is_busy():
        raise HTTPException(409, "Es läuft kein Regionswechsel.")
    region_switch.request_cancel()
    return {"status": "cancelling"}
```

In `admin.py:1141` die Gegenprüfung einsetzen, direkt nach der bestehenden `TRIGGER_FILE`-Prüfung:

```python
    from app.services import region_switch
    if region_switch.is_busy():
        raise HTTPException(409, "Ein Regionswechsel läuft — Update währenddessen gesperrt.")
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `cd backend && pytest tests/test_region_api.py -v`
Expected: PASS (6 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/region.py backend/app/api/routes/admin.py backend/tests/test_region_api.py
git commit -m "feat(region): Wechsel auslösen, Status, Abbruch, Lock gegen Update"
```

---

## Task 6: `.region` hat Vorrang vor der Env

**Files:**
- Modify: `graphhopper/entrypoint.sh:4-9`
- Create: `graphhopper/tests/test_region_file.sh`

**Interfaces:**
- Produces: `/data/osm/.region` als Quelle für `OSM_DOWNLOAD_URL`, `OSM_FILENAME`, `JAVA_OPTS`

- [ ] **Step 1: Failing Test schreiben**

```bash
#!/usr/bin/env bash
# graphhopper/tests/test_region_file.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FAILED=0

check() { if [ "$2" = "$3" ]; then echo "ok   — $1"; else echo "FAIL — $1: erwartet '$3', bekam '$2'"; FAILED=1; fi }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/osm"

# Fall 1: .region vorhanden — sie gewinnt
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
EOF
out=$(OSM_DIR="$TMP/osm" OSM_FILENAME="dach-latest.osm.pbf" JAVA_OPTS="-Xmx8g" \
      bash "$HERE/../region-source.sh" && echo "$OSM_FILENAME|$JAVA_OPTS")
check ".region gewinnt gegen Env" "$out" "berlin-latest.osm.pbf|-Xmx3g -Xms1g -XX:+UseG1GC"

# Fall 2: keine .region — Env bleibt unveraendert (Regressionsschutz)
rm -f "$TMP/osm/.region"
out=$(OSM_DIR="$TMP/osm" OSM_FILENAME="dach-latest.osm.pbf" JAVA_OPTS="-Xmx8g" \
      bash "$HERE/../region-source.sh" && echo "$OSM_FILENAME|$JAVA_OPTS")
check "ohne .region bleibt Env" "$out" "dach-latest.osm.pbf|-Xmx8g"

exit $FAILED
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `bash graphhopper/tests/test_region_file.sh`
Expected: FAIL — `region-source.sh` existiert nicht

- [ ] **Step 3: Implementieren**

Neue Datei `graphhopper/region-source.sh` — herausgezogen, damit sie ohne Container testbar ist:

```bash
#!/usr/bin/env bash
# Liest die aktive Region aus .region und ueberschreibt damit die Env-Vorgaben.
# Fehlt die Datei, bleibt alles wie bisher — Regressionsschutz fuer Bestand.
REGION_FILE="${OSM_DIR:-/data/osm}/.region"
if [ -f "$REGION_FILE" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            OSM_DOWNLOAD_URL) export OSM_DOWNLOAD_URL="$value" ;;
            OSM_FILENAME)     export OSM_FILENAME="$value" ;;
            JAVA_OPTS)        export JAVA_OPTS="$value" ;;
        esac
    done < "$REGION_FILE"
fi
```

In `entrypoint.sh` direkt nach den Defaults (Zeile 9) einbinden:

```bash
# shellcheck source=region-source.sh
. /graphhopper/region-source.sh
OSM_FILE="$OSM_DIR/$OSM_FILENAME"
DOWNLOAD_URL="$OSM_DOWNLOAD_URL"
```

Im `graphhopper/Dockerfile` die Datei mitkopieren.

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `bash graphhopper/tests/test_region_file.sh`
Expected: beide Zeilen `ok`, Exit 0

- [ ] **Step 5: Commit**

```bash
git add graphhopper/region-source.sh graphhopper/entrypoint.sh graphhopper/Dockerfile \
        graphhopper/tests/test_region_file.sh
git commit -m "feat(graphhopper): .region hat Vorrang vor den Env-Vorgaben"
```

---

## Task 7: Updater — die fünf Phasen

**Files:**
- Create: `docker/updater/switch-region.sh`
- Create: `docker/updater/tests/test_switch_region.sh`
- Modify: `docker-compose.yml` (`osm_data` im Updater mounten)

**Interfaces:**
- Consumes: `region_request.json`
- Produces: `region_status.json`, `region.log`, `/data/osm/.region`

- [ ] **Step 1: Failing Test schreiben**

Ein `docker`-Stub im `PATH` protokolliert Aufrufe, statt sie auszuführen.

```bash
#!/usr/bin/env bash
# docker/updater/tests/test_switch_region.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAILED=0

mkdir -p "$TMP/bin" "$TMP/status" "$TMP/osm" "$TMP/graph"
cat > "$TMP/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_CALLS"
exit 0
EOF
cat > "$TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
# HEAD liefert Groesse, GET legt eine Dummy-Datei an
for a in "$@"; do case "$a" in -o) shift; touch "$2";; esac; done
echo "content-length: 1000"
exit 0
EOF
chmod +x "$TMP/bin/docker" "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH" DOCKER_CALLS="$TMP/calls.txt"

cat > "$TMP/status/region_request.json" <<'EOF'
{"url":"https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf",
 "filename":"berlin-latest.osm.pbf","java_opts":"-Xmx3g","requested_by":"a@b.c"}
EOF

STATUS_DIR="$TMP/status" OSM_DIR="$TMP/osm" GRAPH_DIR="$TMP/graph" SKIP_CHECKSUM=1 \
  bash "$HERE/../switch-region.sh" || true

phase=$(python3 -c "import json;print(json.load(open('$TMP/status/region_status.json'))['phase'])")
[ "$phase" = "done" ] && echo "ok   — Endphase done" || { echo "FAIL — Endphase: $phase"; FAILED=1; }

grep -q "compose up -d graphhopper" "$TMP/calls.txt" \
  && echo "ok   — Schwenk ruft compose up" || { echo "FAIL — kein compose up"; FAILED=1; }

[ -f "$TMP/osm/.region" ] && echo "ok   — .region geschrieben" || { echo "FAIL — .region fehlt"; FAILED=1; }

grep -q "^JAVA_OPTS=-Xmx3g$" "$TMP/osm/.region" \
  && echo "ok   — Heap wandert mit" || { echo "FAIL — Heap fehlt in .region"; FAILED=1; }

exit $FAILED
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `bash docker/updater/tests/test_switch_region.sh`
Expected: FAIL — `switch-region.sh` existiert nicht

- [ ] **Step 3: Implementieren**

```bash
#!/usr/bin/env bash
# docker/updater/switch-region.sh — fuehrt einen Regionswechsel in fuenf Phasen aus.
set -uo pipefail

STATUS_DIR="${STATUS_DIR:-/update_status}"
OSM_DIR="${OSM_DIR:-/data/osm}"
GRAPH_DIR="${GRAPH_DIR:-/data/graph}"
REQ="$STATUS_DIR/region_request.json"
LOG="$STATUS_DIR/region.log"
LOCK="$STATUS_DIR/region.lock"
CANCEL="$STATUS_DIR/region.cancel"

log()   { echo "[$(date -u +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
phase() { printf '{"phase":"%s","message":"%s","at":"%s"}\n' \
          "$1" "$2" "$(date -u +%FT%TZ)" > "$STATUS_DIR/region_status.json"; log "$2"; }
fail()  { phase "failed" "$1"; rm -f "$LOCK" "$REQ" "$CANCEL"; exit 1; }
cancelled() { [ -f "$CANCEL" ]; }

[ -f "$REQ" ] || exit 0
touch "$LOCK"

URL=$(python3 -c "import json;print(json.load(open('$REQ'))['url'])")
FILENAME=$(python3 -c "import json;print(json.load(open('$REQ'))['filename'])")
JAVA_OPTS=$(python3 -c "import json;print(json.load(open('$REQ'))['java_opts'])")

# Allowlist erneut pruefen — dem Backend wird nicht vertraut.
case "$URL" in
  https://download.geofabrik.de/*-latest.osm.pbf) ;;
  *) fail "URL nicht zugelassen: $URL" ;;
esac

# ── Phase 1: Pruefen ────────────────────────────────────────────────────────
phase "checking" "Prüfe Verfügbarkeit und Platz…"
SIZE=$(curl -sSIL "$URL" | awk 'tolower($1)=="content-length:"{v=$2} END{print v+0}')
[ "$SIZE" -gt 0 ] || fail "Extract nicht abrufbar."
FREE=$(df -PB1 "$OSM_DIR" | awk 'NR==2{print $4}')
NEEDED=$(( SIZE * 5 / 2 ))   # neues Extract + neuer Graph, grob 2,5x
[ "$FREE" -gt "$NEEDED" ] || fail "Zu wenig Plattenplatz: $NEEDED benötigt, $FREE frei."
cancelled && fail "Abgebrochen."

# ── Phase 2: Laden ──────────────────────────────────────────────────────────
phase "downloading" "Lade $FILENAME…"
curl -sSL -o "$OSM_DIR/$FILENAME.part" "$URL" || fail "Download fehlgeschlagen."
if [ -z "${SKIP_CHECKSUM:-}" ]; then
    curl -sSL -o "$OSM_DIR/$FILENAME.md5" "$URL.md5" || fail "Prüfsumme nicht abrufbar."
    ( cd "$OSM_DIR" && sed "s/$FILENAME/$FILENAME.part/" "$FILENAME.md5" | md5sum -c - ) \
        || fail "Prüfsumme stimmt nicht — Datei verworfen."
fi
mv "$OSM_DIR/$FILENAME.part" "$OSM_DIR/$FILENAME"
cancelled && fail "Abgebrochen."

# ── Phase 3: Importieren ────────────────────────────────────────────────────
phase "importing" "Baue Routing-Graph (läuft im Hintergrund, Routing bleibt aktiv)…"
STAGING="$GRAPH_DIR/../graph-staging"
rm -rf "$STAGING"; mkdir -p "$STAGING"
docker run --rm \
  -v "$OSM_DIR:/data/osm" -v "$STAGING:/data/graph" \
  -e "OSM_FILENAME=$FILENAME" -e "JAVA_OPTS=$JAVA_OPTS" -e "IMPORT_ONLY=1" \
  "${GRAPHHOPPER_IMAGE:-ghcr.io/retttechsolutions/convoyplan/graphhopper:latest}" \
  || fail "Graph-Bau fehlgeschlagen (vermutlich zu wenig Heap). Alte Region läuft weiter."
cancelled && fail "Abgebrochen."

# ── Phase 4: Schwenken (kein Abbruch mehr) ──────────────────────────────────
phase "switching" "Schwenke auf die neue Region…"
mv "$GRAPH_DIR" "$GRAPH_DIR.old" && mv "$STAGING" "$GRAPH_DIR"
printf 'OSM_DOWNLOAD_URL=%s\nOSM_FILENAME=%s\nJAVA_OPTS=%s\n' \
    "$URL" "$FILENAME" "$JAVA_OPTS" > "$OSM_DIR/.region"
docker compose up -d graphhopper || true

HEALTHY=0
for _ in $(seq 1 60); do
    if curl -sf "http://graphhopper:8989/health" >/dev/null 2>&1; then HEALTHY=1; break; fi
    sleep 5
done
if [ "$HEALTHY" -ne 1 ]; then
    log "Neuer Graph wird nicht gesund — Rollback."
    rm -rf "$GRAPH_DIR"; mv "$GRAPH_DIR.old" "$GRAPH_DIR"
    rm -f "$OSM_DIR/.region"
    docker compose up -d graphhopper || true
    fail "Rollback auf die vorherige Region durchgeführt."
fi

# ── Phase 5: Aufräumen ──────────────────────────────────────────────────────
phase "cleaning" "Räume alte Daten auf…"
rm -rf "$GRAPH_DIR.old"
find "$OSM_DIR" -name '*-latest.osm.pbf' ! -name "$FILENAME" -delete
rm -f "$OSM_DIR"/*.md5

phase "done" "Regionswechsel abgeschlossen: $FILENAME"
rm -f "$LOCK" "$REQ" "$CANCEL"
```

In `docker-compose.yml` beim Updater ergänzen:

```yaml
      - osm_data:/data/osm
      - gh_graph:/data/graph
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `bash docker/updater/tests/test_switch_region.sh`
Expected: vier `ok`-Zeilen, Exit 0

- [ ] **Step 5: Commit**

```bash
git add docker/updater/switch-region.sh docker/updater/tests/test_switch_region.sh docker-compose.yml
git commit -m "feat(updater): Regionswechsel in fünf Phasen mit Rollback"
```

---

## Task 8: Updater-Poll-Schleife holt die Anforderung ab

**Files:**
- Modify: `docker/updater/update.sh:8`

**Interfaces:**
- Consumes: `switch-region.sh`

- [ ] **Step 1: Einbau**

In der Trigger-Prüfschleife, direkt neben der bestehenden `TRIGGER_FILE`-Behandlung:

```bash
  if [ -f /update_status/region_request.json ] && [ ! -f /update_status/region.lock ]; then
      log "Regionswechsel angefordert — starte switch-region.sh"
      /switch-region.sh || log "Regionswechsel fehlgeschlagen (siehe region.log)"
  fi
```

Im `docker/updater/Dockerfile` die Datei kopieren und ausführbar machen — analog zu `update.sh`.

- [ ] **Step 2: Prüfen, dass Update und Wechsel sich ausschließen**

Run: `grep -n "region.lock" docker/updater/update.sh`
Expected: Die Update-Ausführung überspringt, solange `region.lock` existiert.

- [ ] **Step 3: Commit**

```bash
git add docker/updater/update.sh docker/updater/Dockerfile
git commit -m "feat(updater): Regionswechsel in die Poll-Schleife einhängen"
```

---

## Task 9: Panel-Karte

**Files:**
- Create: `frontend/src/lib/components/RegionCard.svelte`
- Modify: `frontend/src/lib/api/index.ts`
- Modify: `frontend/src/routes/admin/+page.svelte:2049`

**Interfaces:**
- Consumes: `/api/admin/region*`
- Produces: `regionApi.preview/switch/status/cancel/list`

- [ ] **Step 1: API-Client ergänzen**

```typescript
export const regionApi = {
  current: () => get<RegionCurrent>('/api/admin/region'),
  list:    () => get<RegionEntry[]>('/api/admin/regions'),
  preview: (url: string) => post<RegionPreview>('/api/admin/region/preview', { url }),
  switch:  (url: string) => post<{ status: string }>('/api/admin/region', { url }),
  status:  () => get<RegionStatus>('/api/admin/region/status'),
  cancel:  () => post<{ status: string }>('/api/admin/region/cancel', {}),
};
```

- [ ] **Step 2: Karte bauen**

Kernzustand mit Svelte-5-Runes; die Vorab-Rechnung lädt bei jeder Auswahl neu, der Knopf bleibt bei `reicht nicht` gesperrt:

```svelte
<script lang="ts">
  import { regionApi } from '$lib/api';
  let current = $state<RegionCurrent | null>(null);
  let selected = $state<string>('');
  let preview = $state<RegionPreview | null>(null);
  let status = $state<RegionStatus>({ phase: 'idle' });
  const busy = $derived(status.phase !== 'idle' && status.phase !== 'done');
  const blocked = $derived(preview?.verdict === 'reicht nicht');

  async function choose(url: string) {
    selected = url;
    preview = await regionApi.preview(url);
  }
</script>
```

Darstellung: Ruhezustand mit vier Kennzahlen, Suchfeld mit Pfadanzeige, Vorab-Rechnung als Gegenüberstellung „benötigt / verfügbar" für RAM und Platte, `preview.reason` im Klartext daneben. Während `busy` ersetzt die Phasenanzeige den Knopf, darunter das Terminal (`.update-terminal` wiederverwenden), Abbrechen nur solange `status.phase` in `checking|downloading|importing`.

- [ ] **Step 3: Fehlschlag-Text**

Bei `status.phase === 'failed'` ausdrücklich anzeigen: *„Die bisherige Region läuft unverändert weiter. Verloren sind nur Zeit und Plattenplatz."* — das ist die zentrale Zusage des Entwurfs und darf nicht der Erschließung überlassen bleiben.

- [ ] **Step 4: Typprüfung**

Run: `cd frontend && npm run check`
Expected: keine Fehler

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/RegionCard.svelte frontend/src/lib/api/index.ts \
        frontend/src/routes/admin/+page.svelte
git commit -m "feat(admin): Karte für den Regionswechsel im System-Reiter"
```

---

## Task 10: Integrationstest mit dem Berlin-Extract

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Job ergänzen**

Berlin ist klein genug für einen Runner und prüft als einziger Test die fünf Phasen gegeneinander.

```yaml
  region-switch:
    name: Region – Wechsel end-to-end (Berlin)
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - name: Stack starten
        run: docker compose up -d graphhopper updater
      - name: Wechsel auf Berlin auslösen
        run: |
          echo '{"url":"https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf",
                 "filename":"berlin-latest.osm.pbf","java_opts":"-Xmx3g",
                 "requested_by":"ci@convoyplan"}' \
            | docker compose exec -T updater tee /update_status/region_request.json
      - name: Auf Abschluss warten (max. 20 min)
        run: |
          for _ in $(seq 1 120); do
            p=$(docker compose exec -T updater cat /update_status/region_status.json \
                | python3 -c "import json,sys;print(json.load(sys.stdin)['phase'])" || echo "-")
            [ "$p" = "done" ] && exit 0
            [ "$p" = "failed" ] && { docker compose exec -T updater cat /update_status/region.log; exit 1; }
            sleep 10
          done
          exit 1
```

- [ ] **Step 2: Manuellen Prüfschritt dokumentieren**

Grosse Regionen sprengen jeden Runner. In `docs/` vermerken, dass der Pfad mit DACH oder groesser vor jedem Release einmal von Hand auf einer echten Instanz zu prüfen ist — als bewusste, benannte Lücke statt als stillschweigende.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml docs/
git commit -m "test(region): End-to-end-Wechsel auf Berlin in CI"
```

---

## Self-Review

**Spec-Abdeckung:** Abschnitt 1 → Tasks 6/7 · Abschnitt 2 (Entscheidungen) → Tasks 6/7 · Abschnitt 3 (fünf Phasen) → Task 7 · Abschnitt 4 (API) → Tasks 2–5 · Abschnitt 5 (Panel) → Task 9 · Abschnitt 6 (Schätzung) → Task 1 · Abschnitt 7 (Fehlerfälle) → Task 7 (Rollback, Prüfsumme, Platz) + Task 5 (409) · Abschnitt 8 (Tests) → Tasks 1/2/6/7/10 · Abschnitt 9 (offene Punkte) → Task 1.

**Lücke, bewusst offen gelassen:** `GET /api/admin/regions` (Index-Baum) und `GET /api/admin/region` (aktueller Stand) sind in Task 5 als Endpunkte genannt, aber ohne eigenen Testblock. Beides ist Lesezugriff ohne Nebenwirkung; die Tests dafür gehören in Task 5, Step 1 ergänzt, sobald das Index-Parsing steht — die Struktur von `index-v1.json` sollte man vor dem Testschreiben einmal real gesehen haben, statt sie zu erfinden.

**Typkonsistenz geprüft:** `estimate_ram_bytes` / `estimate_graph_bytes` / `estimate_duration_minutes` / `verdict` einheitlich zwischen Tasks 1, 4 und 5. `region_switch.is_busy` in Tasks 3, 5 und in `admin.py`. `.region`-Schlüssel identisch in Tasks 6 und 7. `STATUS_DIR`/`OSM_DIR`/`GRAPH_DIR` durchgängig in Task 7 und dessen Test.

**Offener Punkt 4 der Spec** — Verlässlichkeit des Health-Checks als Rollback-Auslöser — ist in Task 7 als 60×5-Sekunden-Schleife gegen `/health` umgesetzt. Ob dieser Endpunkt existiert und aussagekräftig ist, muss Task 7 vor der Implementierung prüfen; andernfalls tritt der Compose-Healthcheck des Containers an seine Stelle.
