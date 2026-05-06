#!/bin/sh
set -e

OSM_DIR="/data/osm"
GRAPH_DIR="/data/graph"
OSM_FILENAME="${OSM_FILENAME:-germany-latest.osm.pbf}"
OSM_FILE="$OSM_DIR/$OSM_FILENAME"
DOWNLOAD_URL="${OSM_DOWNLOAD_URL:-https://download.geofabrik.de/europe/germany-latest.osm.pbf}"
JAVA_OPTS="${JAVA_OPTS:--Xmx2g -Xms512m -XX:+UseG1GC}"

mkdir -p "$OSM_DIR" "$GRAPH_DIR"

# â”€â”€ OSM-Daten holen (nur beim ersten Start) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [ ! -f "$OSM_FILE" ]; then
    echo "================================================================"
    echo "  OSM-Kartendaten fehlen â€“ Download wird gestartet"
    echo "  Quelle : $DOWNLOAD_URL"
    echo "  Ziel   : $OSM_FILE"
    echo "  (Erster Start kann je nach Region mehrere Minuten dauern)"
    echo "================================================================"
    if curl -fL --progress-bar -o "${OSM_FILE}.tmp" "$DOWNLOAD_URL"; then
        mv "${OSM_FILE}.tmp" "$OSM_FILE"
        echo "Download erfolgreich: $OSM_FILE"
    else
        rm -f "${OSM_FILE}.tmp"
        echo "FEHLER: Download fehlgeschlagen. URL prÃ¼fen: $DOWNLOAD_URL"
        exit 1
    fi
else
    echo "OSM-Daten vorhanden: $OSM_FILE"
fi

# â”€â”€ GraphHopper-Konfiguration generieren â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

  profiles:
    - name: car
      weighting: fastest
    - name: truck
      weighting: fastest

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
