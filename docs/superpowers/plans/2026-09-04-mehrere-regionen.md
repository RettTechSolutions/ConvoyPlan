# Mehrere Regionen kombinieren — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mehrere Geofabrik-Regionen lassen sich zu einer Karte zusammenführen, damit Konvois in Nachbarländer nicht ganz Europa erfordern.

**Architecture:** Die Zusammensetzung wandert als Kurz-Hash in den Dateinamen der zusammengeführten Datei — damit übernimmt der bestehende Fingerprint-Mechanismus aus #420 die Neubau-Erkennung unverändert. `.region` bekommt `OSM_SOURCES` als einzigen optionalen Schlüssel. Der Updater bekommt zwischen Laden und Importieren eine sechste Phase, die `osmium merge` in einem Wegwerf-Container ausführt.

**Tech Stack:** Bash (Updater, GraphHopper-Entrypoint), FastAPI (Backend), Svelte 5 mit Runes (Panel), `osmium-tool`, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-04-mehrere-regionen-design.md`

## Global Constraints

- **Fehlt `OSM_SOURCES`, verhält sich alles bitgleich zu heute.** Das ist der Regressionsschutz für jede Bestandsinstallation und die härteste Randbedingung dieses Plans.
- Der Dateiname der zusammengeführten Datei lautet `merged-<hash8>.osm.pbf`, wobei `<hash8>` aus der **sortierten** Bestandteilsliste gebildet wird. Gleiche Auswahl in anderer Reihenfolge → gleicher Hash → kein Neubau.
- `OSM_SOURCES` ist `|`-getrennt und sortiert, enthält Geofabrik-Pfade ohne Schema und ohne `-latest.osm.pbf`.
- **Jeder** Bestandteil durchläuft `validate_region_url` einzeln, beidseitig (Backend und Updater). Nichts an dieser Grenze wird gelockert.
- Teilerfolge gibt es nicht: Scheitert ein Download oder der Merge, bricht der ganze Wechsel ab und die alte Region läuft unverändert weiter.
- `osmium` läuft in einem **Wegwerf-Container**, nicht im GraphHopper-Image.
- `graphhopper/entrypoint.sh` ist POSIX-`sh` (`#!/bin/sh`, Alpine-Basis) — keine bash-Erweiterungen im gesourcten Code.
- Kommentare, Docstrings und Meldungen auf Deutsch.

---

## File Structure

**Neu:**

| Datei | Verantwortung |
|---|---|
| `docker/updater/merge-extracts.sh` | Phase 3: Wegwerf-Container, `osmium merge`, Plausibilitätsprüfung |
| `docker/updater/tests/test_merge_extracts.sh` | Merge-Phase gegen `docker`-Stub |
| `backend/app/services/region_compose.py` | Hash aus sortierter Liste, `OSM_SOURCES` bauen/parsen, Summenrechnung |
| `backend/tests/test_region_compose.py` | Hash-Stabilität, Summen, Überlappungserkennung |
| `.github/workflows/ci.yml` (Job) | Wiederkehrender Grenzroutings-Test (aus dem Spike) |

**Geändert:**

| Datei | Änderung |
|---|---|
| `graphhopper/region-source.sh` | `OSM_SOURCES` als optionaler vierter Schlüssel |
| `graphhopper/entrypoint.sh:44` | Kein Selbstdownload bei gesetztem `OSM_SOURCES` |
| `docker/updater/switch-region.sh` | N Downloads, Merge-Phase, Aufräumen aller Quellen |
| `backend/app/services/region_estimate.py` | Summenrechnung über mehrere Extracts |
| `backend/app/api/routes/region.py` | `preview` und `switch` nehmen eine Liste |
| `backend/app/services/region_switch.py` | `region_request.json` trägt die Liste |
| `frontend/src/lib/components/RegionCard.svelte` | Mehrfachauswahl, mitlaufende Summe, zwei Hinweise |
| `frontend/src/lib/api/index.ts` | `regionApi` nimmt Listen |

---

## Task 1: Den Erstdownload-Fall klären und absichern

Der unsicherste Punkt der Spec (Abschnitt 2). Hier greifen `entrypoint.sh` und Updater ineinander, und beide könnten sich für zuständig halten. Falsch gelöst startet eine frische Installation mit **halber Karte** und routet stillschweigend an Grenzen ins Leere.

**Files:**
- Modify: `graphhopper/entrypoint.sh:44-60`
- Modify: `graphhopper/region-source.sh`
- Create: `graphhopper/tests/test_first_start_composed.sh`

**Interfaces:**
- Produces: `OSM_SOURCES` als exportierte Variable aus `region-source.sh`; Entrypoint-Verhalten „warten statt laden"

- [ ] **Step 1: Den heutigen Erstdownload-Pfad lesen und verstehen**

Lies `graphhopper/entrypoint.sh:44-60`. Notiere im Report, unter welchen genauen Bedingungen heute geladen wird und was passiert, wenn der Download scheitert. Ohne dieses Verständnis ist Step 3 Raten.

- [ ] **Step 2: Failing Test schreiben**

```bash
#!/usr/bin/env bash
# graphhopper/tests/test_first_start_composed.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FAILED=0
check() { if [ "$2" = "$3" ]; then echo "ok   — $1"; else echo "FAIL — $1: erwartet '$3', bekam '$2'"; FAILED=1; fi }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/osm"

# Fall 1: OSM_SOURCES gesetzt, zusammengefuehrte Datei fehlt -> NICHT laden, sondern warten
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany-latest.osm.pbf
OSM_FILENAME=merged-a3f9c21e.osm.pbf
JAVA_OPTS=-Xmx6g
OSM_SOURCES=europe/germany|europe/poland
EOF
out=$(OSM_DIR="$TMP/osm" REGION_COMPOSED_WAIT_ONCE=1 \
      sh "$HERE/../entrypoint-head-for-test.sh" 2>&1 || true)
echo "$out" | grep -q "wartet" && r=wartet || r=geladen
check "mit OSM_SOURCES wird nicht selbst geladen" "$r" "wartet"
echo "$out" | grep -qi "updater" && r=ja || r=nein
check "Meldung nennt den Updater als Zustaendigen" "$r" "ja"

# Fall 2: kein OSM_SOURCES -> Verhalten unveraendert (Download wird versucht)
rm -f "$TMP/osm/.region"
out=$(OSM_DIR="$TMP/osm" OSM_FILENAME=berlin-latest.osm.pbf \
      OSM_DOWNLOAD_URL=https://example.invalid/x-latest.osm.pbf \
      REGION_COMPOSED_WAIT_ONCE=1 sh "$HERE/../entrypoint-head-for-test.sh" 2>&1 || true)
echo "$out" | grep -q "Download wird gestartet" && r=geladen || r=wartet
check "ohne OSM_SOURCES bleibt der Download-Pfad" "$r" "geladen"

exit $FAILED
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag bestätigen**

Run: `bash graphhopper/tests/test_first_start_composed.sh`
Expected: FAIL — `entrypoint-head-for-test.sh` existiert nicht

- [ ] **Step 4: Implementieren**

`region-source.sh` um den optionalen Schlüssel erweitern — er darf **fehlen**, ohne die Datei zu verwerfen:

```sh
            OSM_SOURCES)      region_sources="$region_value" ;;
```

und beim Export:

```sh
        [ -n "$region_sources" ] && export OSM_SOURCES="$region_sources"
```

In `entrypoint.sh` vor dem Download-Block:

```sh
# Bei einer zusammengesetzten Region erzeugt AUSSCHLIESSLICH der Updater die
# Datei (er laedt N Extracts und fuehrt sie zusammen). Wuerde der Entrypoint
# hier selbst laden, bekaeme er nur den ERSTEN Bestandteil und startete mit
# halber Karte — Routen wuerden an den Grenzen still ins Leere laufen.
if [ -n "${OSM_SOURCES:-}" ] && [ ! -f "$OSM_FILE" ]; then
    echo "================================================================"
    echo "  Zusammengesetzte Region ($OSM_SOURCES)"
    echo "  Die Karte wird vom Updater bereitgestellt — GraphHopper wartet."
    echo "================================================================"
    while [ ! -f "$OSM_FILE" ]; do
        [ -n "${REGION_COMPOSED_WAIT_ONCE:-}" ] && exit 0
        sleep 30
    done
fi
```

Den Kopf bis zu dieser Stelle als `entrypoint-head-for-test.sh` per `sed` an einer Kommentarmarke herausschneiden — **nicht nachbauen**, sonst prüft der Test eine Kopie statt des Originals. Vorbild: `graphhopper/tests/test_entrypoint_region.sh` aus dem vorigen Vorhaben.

- [ ] **Step 5: Test laufen lassen, Erfolg bestätigen**

Run: `bash graphhopper/tests/test_first_start_composed.sh`
Expected: drei `ok`-Zeilen, Exit 0

- [ ] **Step 6: Commit**

```bash
git add graphhopper/
git commit -m "feat(graphhopper): zusammengesetzte Region wartet auf den Updater"
```

---

## Task 2: Hash und Zusammensetzung im Backend

**Files:**
- Create: `backend/app/services/region_compose.py`
- Create: `backend/tests/test_region_compose.py`

**Interfaces:**
- Produces: `compose_hash(paths: list[str]) -> str` (8 Zeichen), `merged_filename(paths) -> str`, `sources_value(paths) -> str`, `parse_sources(value: str) -> list[str]`, `overlapping(paths) -> list[tuple[str, str]]`

- [ ] **Step 1: Failing Test schreiben**

```python
# backend/tests/test_region_compose.py
from app.services.region_compose import (
    compose_hash, merged_filename, sources_value, parse_sources, overlapping,
)

DE, PL, CZ = "europe/germany", "europe/poland", "europe/czech-republic"
BY = "europe/germany/bayern"


def test_hash_ignoriert_die_reihenfolge():
    """Gleiche Auswahl, andere Reihenfolge -> gleicher Hash, kein Neubau."""
    assert compose_hash([DE, PL]) == compose_hash([PL, DE])


def test_hash_aendert_sich_bei_anderer_zusammensetzung():
    assert compose_hash([DE, PL]) != compose_hash([DE, CZ])


def test_hash_ist_acht_zeichen_und_stabil():
    h = compose_hash([DE, PL])
    assert len(h) == 8 and h == compose_hash([DE, PL])


def test_dateiname_traegt_den_hash():
    assert merged_filename([DE, PL]) == f"merged-{compose_hash([DE, PL])}.osm.pbf"


def test_sources_wird_sortiert_geschrieben_und_gelesen():
    v = sources_value([PL, DE, CZ])
    assert v == "|".join(sorted([DE, PL, CZ]))
    assert parse_sources(v) == sorted([DE, PL, CZ])


def test_parse_sources_leer_ergibt_leere_liste():
    assert parse_sources("") == []


def test_ueberlappung_wird_erkannt():
    """Deutschland und Bayern zusammen ist erlaubt, aber verschwenderisch."""
    assert overlapping([DE, BY]) == [(DE, BY)]
    assert overlapping([DE, PL]) == []
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_region_compose.py -v`
Expected: FAIL mit `ModuleNotFoundError`

- [ ] **Step 3: Implementieren**

```python
# backend/app/services/region_compose.py
"""Zusammensetzung mehrerer Geofabrik-Regionen zu einer Karte.

Der Kern ist der Hash: Er wandert in den Dateinamen der zusammengefuehrten
Datei, und `graphhopper/entrypoint.sh:90` bildet den Fingerprint aus genau
diesem Namen. Dadurch erkennt der bestehende Mechanismus aus #420 einen
Wechsel der Zusammensetzung, ohne dass hier etwas Eigenes noetig waere.

Die Sortierung ist keine Kosmetik: Ohne sie ergaeben "DE, PL" und "PL, DE"
verschiedene Hashes und damit einen ueberfluessigen, stundenlangen Neubau.
"""
import hashlib

_SEP = "|"


def compose_hash(paths: list[str]) -> str:
    """Acht Zeichen aus der sortierten Bestandteilsliste."""
    joined = _SEP.join(sorted(paths))
    return hashlib.sha256(joined.encode()).hexdigest()[:8]


def merged_filename(paths: list[str]) -> str:
    return f"merged-{compose_hash(paths)}.osm.pbf"


def sources_value(paths: list[str]) -> str:
    """Der Wert fuer OSM_SOURCES in `.region` — sortiert, |-getrennt."""
    return _SEP.join(sorted(paths))


def parse_sources(value: str) -> list[str]:
    if not value.strip():
        return []
    return sorted(p for p in value.split(_SEP) if p)


def overlapping(paths: list[str]) -> list[tuple[str, str]]:
    """Paare (Oberregion, Unterregion) — erlaubt, aber verschwenderisch.

    osmium merge dedupliziert das korrekt; der Operator laedt dann aber
    Daten doppelt herunter und wartet laenger als noetig.
    """
    out = []
    for a in sorted(paths):
        for b in sorted(paths):
            if a != b and b.startswith(a + "/"):
                out.append((a, b))
    return out
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

Run: `cd backend && pytest tests/test_region_compose.py -v`
Expected: PASS (7 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/region_compose.py backend/tests/test_region_compose.py
git commit -m "feat(region): Hash und Zusammensetzung mehrerer Regionen"
```

---

## Task 3: Schätzung über mehrere Extracts

**Files:**
- Modify: `backend/app/services/region_estimate.py`
- Modify: `backend/tests/test_region_estimate.py`

**Interfaces:**
- Consumes: `region_compose`
- Produces: `estimate_ram_bytes(total_pbf_bytes)` unverändert; neu `sum_extract_bytes(sizes: list[int]) -> int`, `estimate_disk_during_switch(sizes: list[int]) -> int`

- [ ] **Step 1: Failing Test schreiben**

```python
GB = 1024 ** 3

def test_summe_der_extracts():
    from app.services.region_estimate import sum_extract_bytes
    assert sum_extract_bytes([4 * GB, 2 * GB, 1 * GB]) == 7 * GB

def test_plattenbedarf_beruecksichtigt_alle_gleichzeitig_liegenden_dateien():
    """Waehrend des Wechsels liegen N Quellen, die zusammengefuehrte Datei,
    Staging-Graph, alter Graph und altes Extract gleichzeitig auf der Platte."""
    from app.services.region_estimate import estimate_disk_during_switch
    need = estimate_disk_during_switch([4 * GB, 2 * GB, 1 * GB])
    assert need > 7 * GB * 2   # deutlich mehr als nur Quellen + Merge
```

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_region_estimate.py -v`
Expected: FAIL mit `ImportError`

- [ ] **Step 3: Implementieren**

```python
def sum_extract_bytes(sizes: list[int]) -> int:
    """Summe der Bestandteile.

    Die Ueberlappung im Grenzstreifen (im Spike 0,67 % zwischen Sachsen und
    Niederschlesien) wird bewusst NICHT abgezogen: Sie ist regionsabhaengig
    und klein, und eine Ueberschaetzung ist hier der sichere Fehler.
    """
    return sum(sizes)


def estimate_disk_during_switch(sizes: list[int]) -> int:
    """Spitzenbedarf waehrend des Wechsels.

    Gleichzeitig auf der Platte: die N Quelldateien, die zusammengefuehrte
    Datei (~Summe), der Staging-Graph (~1,5x), der alte Graph und das alte
    Extract. Letztere beiden sind unbekannt; als Naeherung wird die Summe
    noch einmal veranschlagt.
    """
    total = sum(sizes)
    return total + total + int(total * 1.5) + total
```

- [ ] **Step 4: Erfolg bestätigen**

Run: `cd backend && pytest tests/test_region_estimate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/region_estimate.py backend/tests/test_region_estimate.py
git commit -m "feat(region): Schätzung über mehrere Extracts"
```

---

## Task 4: Backend-API nimmt Listen

**Files:**
- Modify: `backend/app/api/routes/region.py`
- Modify: `backend/app/services/region_switch.py`
- Modify: `backend/tests/test_region_api.py`

**Interfaces:**
- Consumes: `region_compose`, `region_estimate`
- Produces: `POST /api/admin/region/preview` und `POST /api/admin/region` nehmen `{urls: [...]}`; `region_request.json` trägt `sources` und `filename`

- [ ] **Step 1: Failing Test schreiben**

```python
URLS = [
    "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
    "https://download.geofabrik.de/europe/poland-latest.osm.pbf",
]

async def test_preview_summiert_mehrere_regionen(...):
    """Die Vorab-Rechnung muss ueber alle Bestandteile summieren."""
    # head_size_bytes je URL mocken, Summe im Ergebnis pruefen
    ...

async def test_preview_meldet_ueberlappende_auswahl(...):
    """Deutschland + Bayern: erlaubt, aber Hinweis im Ergebnis."""
    ...

async def test_switch_schreibt_sortierte_quellenliste(...):
    """region_request.json traegt sources sortiert und den Merged-Dateinamen."""
    ...

async def test_einzelne_region_bleibt_der_alte_pfad(...):
    """Genau eine URL -> kein Merge, kein OSM_SOURCES."""
    ...
```

Die Tests folgen dem Muster aus `test_admin.py:1-30` (`AsyncClient` mit `ASGITransport`, `app.dependency_overrides`) — **nicht** den Fixtures `client`/`db`, die es nicht gibt. Die DB ist eine `AsyncSession`.

- [ ] **Step 2: Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_region_api.py -v`
Expected: FAIL — die Routen nehmen noch eine einzelne URL

- [ ] **Step 3: Implementieren**

`RegionUrl` wird zu `RegionUrls` mit `urls: list[str]` (mindestens ein Eintrag). Jede URL einzeln durch `validate_region_url`; `head_size_bytes` je URL, Summe über `sum_extract_bytes`. Bei genau einer URL bleibt alles wie heute — **kein** `sources`, kein Merge-Dateiname. Bei mehreren: `merged_filename(paths)` als Zieldatei, `sources_value(paths)` in die Anforderung.

`region_switch.write_request` bekommt zwei zusätzliche Felder (`sources`, leer bei Einzelregion). Die exklusive Anlage per `os.link` und die Atomarität bleiben unverändert.

- [ ] **Step 4: Erfolg bestätigen**

Run: `cd backend && pytest tests/test_region_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/
git commit -m "feat(region): API nimmt mehrere Regionen entgegen"
```

---

## Task 5: Merge-Phase im Updater

**Files:**
- Create: `docker/updater/merge-extracts.sh`
- Create: `docker/updater/tests/test_merge_extracts.sh`
- Modify: `docker/updater/switch-region.sh`
- Modify: `docker/updater/Dockerfile`

**Interfaces:**
- Consumes: `region_request.json` mit `sources`
- Produces: `merged-<hash>.osm.pbf` im `osm_data`-Volume

- [ ] **Step 1: Klären, welches Image `osmium-tool` mitbringt**

Offener Punkt 2 der Spec. Prüfe, ob ein fertiges Image existiert, das `osmium-tool` enthält und gepflegt wird — sonst ein schlankes Debian-Image plus `apt-get install osmium-tool` zur Laufzeit des Wegwerf-Containers. Begründe die Wahl im Report; ein Image, das bei jedem Wechsel Pakete nachlädt, ist von einem Netzausfall abhängig.

- [ ] **Step 2: Failing Test schreiben**

```bash
#!/usr/bin/env bash
# docker/updater/tests/test_merge_extracts.sh
# Prueft die Merge-Phase gegen einen docker-Stub: Reihenfolge der Aufrufe,
# Plausibilitaetspruefung, Aufraeumen bei Fehlschlag.
set -uo pipefail
# ... Stub-Aufbau wie in test_switch_region.sh ...

# Fall 1: zwei Quellen -> osmium merge wird mit beiden aufgerufen
# Fall 2: Merge liefert unplausibel kleine Datei -> Abbruch, alte Region unberuehrt
# Fall 3: eine Quelle -> KEIN Merge-Aufruf (alter Pfad)
# Fall 4: Fehlschlag -> Quelldateien aufgeraeumt, Lock freigegeben
```

- [ ] **Step 3: Fehlschlag bestätigen**

Run: `bash docker/updater/tests/test_merge_extracts.sh`
Expected: FAIL — `merge-extracts.sh` existiert nicht

- [ ] **Step 4: Implementieren**

`merge-extracts.sh` mit den Randbedingungen:
- `docker run --rm` mit dem in Step 1 gewählten Image, `osm_data`-Volume als **Volume-Name** (nicht Containerpfad — Fehler aus dem vorigen Vorhaben)
- `osmium merge <n Quellen> -o merged-<hash>.osm.pbf.tmp`, dann atomar per `mv`
- **Plausibilitätsprüfung:** Ergebnisgröße muss zwischen 80 % und 105 % der Quellsumme liegen. Darunter ist der Merge verstümmelt, darüber stimmt etwas nicht. Der Spike maß 0,67 % Überlappung — die 20 % Spielraum nach unten sind großzügig, weil die Überlappung regionsabhängig ist.
- Bei Fehlschlag: Quelldateien und Teilergebnis entfernen, `fail` aufrufen

In `switch-region.sh` Phase 2 auf N Downloads erweitern (jede URL erneut gegen die Allowlist prüfen), Phase 3 einschieben, Phase 6 um das Aufräumen aller Quellen erweitern. Die Phasennamen für `region_status.json` erweitern: `merging` zwischen `downloading` und `importing`.

- [ ] **Step 5: Erfolg bestätigen**

Run: `bash docker/updater/tests/test_merge_extracts.sh && bash docker/updater/tests/test_switch_region.sh`
Expected: beide grün

- [ ] **Step 6: Commit**

```bash
git add docker/updater/
git commit -m "feat(updater): Merge-Phase für zusammengesetzte Regionen"
```

---

## Task 6: Panel-Mehrfachauswahl

**Files:**
- Modify: `frontend/src/lib/components/RegionCard.svelte`
- Modify: `frontend/src/lib/api/index.ts`

- [ ] **Step 1: API-Client auf Listen umstellen**

```typescript
preview: (urls: string[]) => api.post<RegionPreview>('/api/admin/region/preview', { urls }),
switch:  (urls: string[]) => api.post<{ status: string }>('/api/admin/region', { urls }),
```

Die Phase `merging` in den `RegionPhase`-Typ aufnehmen — **exakt** so geschrieben wie in `switch-region.sh`, sonst bleibt die Anzeige bei dieser Phase leer.

- [ ] **Step 2: Auswahl zur Liste machen**

Suchtreffer **fügen hinzu**, Schnellwahl-Knöpfe **ersetzen**. Gewählte Regionen als entfernbare Marken über dem Suchfeld. Bei jeder Änderung `preview(urls)` neu abrufen, damit Summe und Urteil mitlaufen.

- [ ] **Step 3: Die zwei Hinweise**

Überlappende Auswahl (aus `preview`) mit Angebot, die Unterregion zu entfernen. Und: Übersteigt die Summe eine fertige Geofabrik-Region, Hinweis darauf plus direkter Weg dorthin.

- [ ] **Step 4: Typprüfung**

Run: `cd frontend && npm run check`
Expected: 0 Fehler

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(admin): Mehrfachauswahl für kombinierte Kartenregionen"
```

---

## Task 7: Grenzroutings-Test in CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/superpowers/specs/2026-09-04-mehrere-regionen-design.md`

- [ ] **Step 1: Den Spike als wiederkehrenden Job einbauen**

Der Wegwerf-Workflow aus der Vorbedingung wird zum festen Job: Sachsen + Niederschlesien laden, `osmium merge`, importieren, drei Routen prüfen (Kontrolle innerhalb Sachsens, Görlitz→Zgorzelec, Dresden→Wrocław). Er hat die Machbarkeit belegt; er soll belegen, dass sie erhalten bleibt.

Die Kontrollroute ist nicht optional: Ohne sie unterscheidet der Job nicht zwischen „Grenze kaputt" und „Graph generell kaputt".

- [ ] **Step 2: Manuellen Prüfschritt dokumentieren**

In der Spec festhalten, dass große Kombinationen (DACH plus mehrere Nachbarn) Laufzeit und Speicher jedes Runners sprengen und vor jedem Release einmal von Hand auf einer echten Instanz zu prüfen sind.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml docs/
git commit -m "test(region): Grenzrouting bei zusammengeführten Extracts in CI"
```

---

## Self-Review

**Spec-Abdeckung:** Abschnitt 1 (Vorbedingung) → Task 7 · Abschnitt 2 (Datenmodell) → Tasks 1, 2 · Abschnitt 3 (Ablauf) → Task 5 · Abschnitt 4 (Oberfläche) → Task 6 · Abschnitt 5 (Fehlerfälle) → Tasks 5, 6 · Abschnitt 6 (Tests) → alle Tasks · Abschnitt 7 (offene Punkte) → Task 1 (Erstdownload), Task 5 Step 1 (Image), Task 5 Step 4 (Plausibilitätsgrenze).

**Offener Punkt 4 der Spec** — ob `OSM_SOURCES` in `.region` das richtige Format bleibt, sobald die Liste lang wird — ist **bewusst nicht** in einen Task gegossen. Bei drei bis fünf Ländern ist die Zeile kurz; wird sie unhandlich, ist das der Zeitpunkt für eine eigene Datei. Vorher wäre es Vorratsarbeit.

**Bewusste Lücke:** Task 4 Step 1 skizziert die Tests, statt sie auszuschreiben — anders als in den übrigen Tasks. Grund: Die genaue Form hängt davon ab, wie Task 2 und 3 ihre Signaturen festlegen, und ein ausgeschriebener Test gegen geratene Signaturen wäre schlechter als eine klare Beschreibung. Der Implementierer von Task 4 hat beide Module dann vorliegen.

**Typkonsistenz geprüft:** `compose_hash` / `merged_filename` / `sources_value` / `parse_sources` / `overlapping` einheitlich zwischen Tasks 2, 4 und 5. Der Phasenname `merging` identisch in Task 5 (`switch-region.sh`) und Task 6 (`RegionPhase`). `OSM_SOURCES` als Schlüsselname identisch in Tasks 1, 4 und 5.
