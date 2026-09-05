#!/bin/sh
set -e

OSM_DIR="${OSM_DIR:-/data/osm}"
# GRAPH_DIR ist ueberschreibbar, damit der Regionswechsel (docker/updater/
# switch-region.sh, Phase 3) den neuen Graphen mit EXAKT dieser Konfiguration
# in ein Staging-Verzeichnis im selben Volume bauen kann, waehrend der aktive
# Graph unberuehrt weiterlaeuft. In docker-compose.yml wird die Variable nicht
# gesetzt — Produktionsverhalten unveraendert.
GRAPH_DIR="${GRAPH_DIR:-/data/graph}"
# Unterbefehl des GraphHopper-JARs: "server" (Normalbetrieb) oder "import"
# (baut nur den Graphen und endet). Ebenfalls nur vom Regionswechsel gesetzt.
GH_COMMAND="${GH_COMMAND:-server}"
OSM_FILENAME="${OSM_FILENAME:-dach-latest.osm.pbf}"
OSM_FILE="$OSM_DIR/$OSM_FILENAME"
DOWNLOAD_URL="${OSM_DOWNLOAD_URL:-https://download.geofabrik.de/europe/dach-latest.osm.pbf}"
JAVA_OPTS="${JAVA_OPTS:--Xmx8g -Xms1g -XX:+UseG1GC}"

# .region hat Vorrang vor den obigen Env-Vorgaben: ein Regionswechsel aus dem
# Admin-Panel schreibt die neue Region in diese Datei im osm_data-Volume.
# Fehlt sie (Bestandsinstallationen ohne Regionswechsel), aendert das Sourcen
# nichts — Regressionsschutz.
# REGION_SOURCE_SCRIPT ist nur fuer Tests ueberschreibbar (siehe
# tests/test_entrypoint_region.sh) — im Container immer der Default.
# shellcheck source=region-source.sh
. "${REGION_SOURCE_SCRIPT:-/region-source.sh}"

# OSM_FILE und DOWNLOAD_URL wurden oben aus den (jetzt ggf. durch .region
# ueberschriebenen) Env-Variablen abgeleitet und muessen deshalb NEU berechnet
# werden — sonst zeigen sie trotz korrekt gesetzter OSM_FILENAME/
# OSM_DOWNLOAD_URL weiterhin auf die alte Region.
OSM_FILE="$OSM_DIR/$OSM_FILENAME"
DOWNLOAD_URL="${OSM_DOWNLOAD_URL:-$DOWNLOAD_URL}"
# ── ENTRYPOINT_HEADER_ENDE ─────────────────────────────────────────────────
# Testmarker (inhaltlich verankert, nicht an Zeilennummern): tests/test_entrypoint_region.sh
# schneidet den Skriptkopf bis inklusive dieser Zeile heraus und sourct ihn
# isoliert, um die obige Neuberechnung ohne echten Download/Java-Start zu
# pruefen. Zeile beim Refactoring bitte erhalten oder den Test mitziehen.

mkdir -p "$OSM_DIR" "$GRAPH_DIR"

# â”€â”€ OSM-Daten holen (nur beim ersten Start) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
DOWNLOADED=0

# Zusammengesetzte Region: die Karte entsteht aus MEHREREN Geofabrik-Extracts,
# die der Updater laedt und mit `osmium merge` verschmilzt. Hier ist nur
# OSM_DOWNLOAD_URL bekannt — also der ERSTE Bestandteil. Wuerden wir den
# herunterladen, startete GraphHopper mit halber Karte und Routen liefen still
# an den Grenzen ins Leere. Deshalb: nichts laden, sondern sichtbar warten.
#
# Die Ausgabe alle 5 Minuten ist Absicht: Das Zusammenstellen kann bei grossen
# Kombinationen Stunden dauern, und ein stummer Container ist von einem
# haengenden nicht zu unterscheiden.
if [ -n "${OSM_SOURCES:-}" ] && [ ! -f "$OSM_FILE" ]; then
    echo "================================================================"
    echo "  Zusammengesetzte Kartenregion"
    echo "  Bestandteile : $OSM_SOURCES"
    echo "  Erwartet     : $OSM_FILE"
    echo "  Die Karte wird vom Updater bereitgestellt (Download aller"
    echo "  Bestandteile und Zusammenfuehrung). GraphHopper wartet solange."
    echo "================================================================"
    region_waited=0
    while [ ! -f "$OSM_FILE" ]; do
        # Ausstieg fuer den Test — im Betrieb nie gesetzt.
        [ -n "${REGION_COMPOSED_WAIT_ONCE:-}" ] && exit 0
        sleep 30
        region_waited=$((region_waited + 30))
        if [ "$((region_waited % 300))" -eq 0 ]; then
            echo "  ... warte weiter auf $OSM_FILE (seit ${region_waited}s)"
        fi
    done
    echo "  Karte ist da — GraphHopper startet."
    unset region_waited
fi
# ── COMPOSED_WAIT_ENDE ──────────────────────────────────────────────────────
# Marke fuer graphhopper/tests/test_first_start_composed.sh: der Test schneidet
# den Kopf bis hierher heraus und fuehrt ihn aus. An einer Kommentarmarke
# verankert statt an Zeilennummern, damit Einschuebe darueber ihn nicht brechen.

if [ ! -f "$OSM_FILE" ]; then
    echo "================================================================"
    echo "  OSM-Kartendaten fehlen â€“ Download wird gestartet"
    echo "  Quelle : $DOWNLOAD_URL"
    echo "  Ziel   : $OSM_FILE"
    echo "  (Erster Start kann je nach Region mehrere Minuten dauern)"
    echo "================================================================"
    RETRIES=5
    DELAY=10
    SUCCESS=0
    for i in $(seq 1 $RETRIES); do
        echo "Versuch $i/$RETRIES..."
        if curl -fL --progress-bar -o "${OSM_FILE}.tmp" "$DOWNLOAD_URL"; then
            mv "${OSM_FILE}.tmp" "$OSM_FILE"
            echo "Download erfolgreich: $OSM_FILE"
            SUCCESS=1
            break
        else
            rm -f "${OSM_FILE}.tmp"
            echo "Versuch $i fehlgeschlagen, warte ${DELAY}s..."
            sleep $DELAY
        fi
    done
    if [ $SUCCESS -eq 0 ]; then
        echo "FEHLER: Download nach $RETRIES Versuchen fehlgeschlagen. URL prüfen: $DOWNLOAD_URL"
        exit 1
    fi
    DOWNLOADED=1
else
    echo "OSM-Daten vorhanden: $OSM_FILE"
fi

# â”€â”€ GraphHopper-Konfiguration generieren â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# road_class + max_speed: vom Backend als Routen-Details angefragt (Fahrzeit-
# Berechnung innerorts/außerorts) und im Custom Model der Straßenpräferenzen
# verwendet. max_height: Höhenbeschränkung aus den Fahrzeugdaten.
# Fehlen diese Encoded Values im Graph, lehnt GraphHopper jede Routing-Anfrage
# ab und calculate-route schlägt fehl.
ENCODED_VALUES="car_access, car_average_speed, road_class, max_speed, max_height"

# Der kompilierte Graph gehört zu genau EINER OSM-Datei und EINEM Satz Encoded
# Values. Ändert sich eines von beidem, muss er neu gebaut werden: bei den
# Encoded Values, weil GraphHopper sonst nicht startet bzw. Anfragen ablehnt —
# bei der OSM-Datei, weil GraphHopper einen vorhandenen Graphen kommentarlos
# weiterverwendet und nach einem Regionswechsel sonst still weiter die alte
# Region routen würde. Beides steckt deshalb im Fingerprint.
FINGERPRINT="$OSM_FILENAME|$ENCODED_VALUES"
FINGERPRINT_FILE="$GRAPH_DIR/.graph_fingerprint"
LEGACY_FINGERPRINT_FILE="$GRAPH_DIR/.encoded_values"

PREV_FINGERPRINT="$(cat "$FINGERPRINT_FILE" 2>/dev/null || true)"
if [ -z "$PREV_FINGERPRINT" ] && [ -f "$LEGACY_FINGERPRINT_FILE" ]; then
    # Bestand von vor der DACH-Umstellung: dort standen nur die Encoded Values
    # in der Datei, die Region war nicht vermerkt. Der Altbestand darf als
    # passend gelten — ein echter Regionswechsel wird unten über $DOWNLOADED
    # erkannt, sonst würde ein reines Update den Graphen ohne Not neu bauen.
    PREV_FINGERPRINT="$OSM_FILENAME|$(cat "$LEGACY_FINGERPRINT_FILE")"
fi

if [ -n "$(ls -A "$GRAPH_DIR" 2>/dev/null | grep -vE '^\.(graph_fingerprint|encoded_values)$')" ]; then
    REBUILD_REASON=""
    if [ "$PREV_FINGERPRINT" != "$FINGERPRINT" ]; then
        REBUILD_REASON="Kartenregion oder Encoded Values haben sich geändert"
    elif [ "$DOWNLOADED" -eq 1 ]; then
        # Frisch geladene OSM-Datei neben einem bereits vorhandenen Graphen:
        # der Graph stammt aus anderen Daten und passt nicht mehr dazu.
        REBUILD_REASON="Neue OSM-Daten geladen"
    fi
    if [ -n "$REBUILD_REASON" ]; then
        echo "================================================================"
        echo "  $REBUILD_REASON – Routing-Graph wird"
        echo "  aus den OSM-Daten neu gebaut (kann mehrere Minuten dauern)."
        echo "================================================================"
        rm -rf "$GRAPH_DIR"/* "$FINGERPRINT_FILE" "$LEGACY_FINGERPRINT_FILE"
    fi
fi
printf '%s' "$FINGERPRINT" > "$FINGERPRINT_FILE"
rm -f "$LEGACY_FINGERPRINT_FILE"

CONFIG_FILE="/tmp/graphhopper-config.yml"
cat > "$CONFIG_FILE" << CONF
graphhopper:
  datareader.file: $OSM_FILE
  graph.location: $GRAPH_DIR

  import.osm.ignored_highways:
    - footway
    - cycleway
    - path
    - pedestrian
    - platform

  graph.encoded_values: $ENCODED_VALUES

  profiles:
    - name: car
      custom_model_files: [car.json]
    - name: truck
      custom_model_files: [car.json]

  profiles_ch:
    - profile: car

  routing:
    ch.disabling_allowed: true

server:
  application_connectors:
    - type: http
      port: 8989
  admin_connectors:
    - type: http
      port: 8990
CONF

# â”€â”€ GraphHopper starten â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "Starte GraphHopper ($GH_COMMAND, Graph-Cache: $GRAPH_DIR)..."
exec java $JAVA_OPTS \
    -jar /graphhopper/graphhopper.jar \
    "$GH_COMMAND" "$CONFIG_FILE"
