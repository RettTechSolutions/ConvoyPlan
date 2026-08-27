#!/bin/sh
set -e

OSM_DIR="/data/osm"
GRAPH_DIR="/data/graph"
OSM_FILENAME="${OSM_FILENAME:-dach-latest.osm.pbf}"
OSM_FILE="$OSM_DIR/$OSM_FILENAME"
DOWNLOAD_URL="${OSM_DOWNLOAD_URL:-https://download.geofabrik.de/europe/dach-latest.osm.pbf}"
JAVA_OPTS="${JAVA_OPTS:--Xmx8g -Xms1g -XX:+UseG1GC}"

mkdir -p "$OSM_DIR" "$GRAPH_DIR"

# â”€â”€ OSM-Daten holen (nur beim ersten Start) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
DOWNLOADED=0
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
echo "Starte GraphHopper (Graph-Cache: $GRAPH_DIR)..."
exec java $JAVA_OPTS \
    -jar /graphhopper/graphhopper.jar \
    server "$CONFIG_FILE"
