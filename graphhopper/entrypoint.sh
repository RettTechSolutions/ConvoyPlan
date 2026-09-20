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
        # Bewusst kleine Werte: die Schleife drumherum ist bereits der grobe
        # Wiederholungsmechanismus (5 Versuche, 10 s Pause). Die curl-eigenen
        # Wiederholungen fangen nur die kurzen Aussetzer INNERHALB eines
        # Versuchs ab. Grosszuegiger gewaehlt wuerden beide Ebenen sich
        # multiplizieren und den Erststart minutenlang haengen lassen, bevor
        # er sichtbar scheitert.
        if curl -fL --progress-bar --retry 2 --retry-all-errors --retry-delay 5 \
                -o "${OSM_FILE}.tmp" "$DOWNLOAD_URL"; then
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

# ── GRAPH_ZUSTAND_ANFANG ────────────────────────────────────────────────────
# Testmarke (inhaltlich verankert, nicht an Zeilennummern): graphhopper/tests/
# test_entrypoint_graph_zustand.sh schneidet den Block von hier bis zur
# Endmarke heraus und sourct ihn isoliert, um die Wipe-Entscheidung ohne
# Java-Start und ohne echten Graphen zu pruefen. Beide Marken beim Refactoring
# erhalten oder den Test mitziehen — und ihre Namen NICHT im Kommentartext
# wiederholen, sonst schneidet der Test an der falschen Zeile ab.

# ── GraphHopper-Konfiguration generieren ────────────────────────────────────
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
    elif [ ! -f "$GRAPH_DIR/edges" ]; then
        # Verzeichnis nicht leer, aber ohne Kantendatei: Rest eines
        # abgebrochenen Imports. Der Fingerprint allein beweist hier nichts —
        # er wird UNTEN geschrieben, also bevor der Import ueberhaupt
        # beginnt. Ein Abbruch danach (Deploy, OOM, Host-Neustart) laesst ihn
        # passend zurueck, waehrend vom Graphen nur Bruchstuecke liegen.
        #
        # Genau das ist am 2026-09-19 passiert: uebrig war ein location_index
        # eines anderen Graphen. GraphHopper importiert dann 13 Minuten neu,
        # laedt in postProcessing den alten Index, findet die Pruefsumme
        # falsch — "location index was opened with incorrect graph" — und
        # endet. `restart: unless-stopped` startet neu: Endlosschleife, ohne
        # Routing, mit voller CPU. Ein Wipe kostet einen Neuaufbau, das
        # Nichterkennen kostet alle.
        #
        # `edges` als Beleg: GraphHopper legt die Kantendatei bei JEDEM
        # vollstaendigen Graphen an, und docker/updater/switch-region.sh
        # benutzt dieselbe Datei als Vollstaendigkeitsmerkmal.
        REBUILD_REASON="Unvollstaendiger Graph aus abgebrochenem Import"
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
# ── GRAPH_ZUSTAND_ENDE ──────────────────────────────────────────────────────

# ── Speicherzugriff auf den Graphen ─────────────────────────────────────────
# Zwei Phasen, zwei Zugriffsarten. Der IMPORT haelt den Graphen im Heap
# (RAM_STORE): dort entscheidet -Xmx aus JAVA_OPTS, und genau darauf beziehen
# sich die Richtwerte in Installer, Wiki und Regionswechsel. Der SERVER dagegen
# blendet die fertigen Graphdateien nur ein (MMAP): der Kernel haelt sie im
# Seitencache und gibt sie unter Speicherdruck wieder frei, statt dass die JVM
# bis -Xmx waechst und nie wieder etwas zurueckgibt. Fuer einen Routing-Dienst,
# der die meiste Zeit auf die naechste Anfrage wartet, ist das der Unterschied
# zwischen "8 GB dauerhaft belegt" und "belegt, was gerade gebraucht wird".
# Das Dateiformat ist bei beiden dasselbe — ein mit RAM_STORE gebauter Graph
# wird per MMAP geladen, ohne Umbau.
#
# GH_DATAACCESS=RAM_STORE stellt das alte Verhalten her: mehr RAM, dafuer keine
# Einlesezeit bei kaltem Seitencache. Der Import bleibt davon unberuehrt.
GH_DATAACCESS="${GH_DATAACCESS:-MMAP}"

# JVM-Optionen NUR fuer die Server-Phase, zusaetzlich zu JAVA_OPTS:
#  - G1PeriodicGCInterval: G1 raeumt im Leerlauf auf und gibt ungenutzten Heap
#    an das Betriebssystem zurueck (JEP 346). Ohne die Option bleibt die Spitze
#    einer einzigen langen Anfrage bis zum naechsten Neustart belegt. Bei einem
#    anderen Kollektor in JAVA_OPTS ist die Option wirkungslos, aber erlaubt.
#  - ExitOnOutOfMemoryError: eine JVM nach OutOfMemoryError beantwortet
#    /health weiter, routet aber nichts mehr und dreht in der GC. Beenden
#    laesst `restart: unless-stopped` sie sauber neu starten — der fertige
#    Graph liegt ja da, der Neustart kostet Sekunden statt eines Imports.
# Fuer den Import gilt beides nicht: dort ist ein OutOfMemoryError ohnehin das
# Ende des Prozesses, und ein Kollektor, der Speicher zurueckgibt, hilft einem
# Lauf nicht, der ihn bis zum Schluss braucht.
GH_SERVER_JAVA_OPTS="${GH_SERVER_JAVA_OPTS:--XX:G1PeriodicGCInterval=300000 -XX:+ExitOnOutOfMemoryError}"

# Nur fuer Tests ueberschreibbar (siehe graphhopper/tests/) — im Container immer
# der Default, dasselbe Muster wie REGION_SOURCE_SCRIPT.
GH_JAR="${GH_JAR:-/graphhopper/graphhopper.jar}"
CONFIG_FILE="/tmp/graphhopper-config.yml"

# $1: Zugriffsart (RAM_STORE oder MMAP). Wird je Phase neu geschrieben, weil
# sich die beiden Laeufe genau in dieser einen Zeile unterscheiden sollen.
write_config() {
    cat > "$CONFIG_FILE" << CONF
graphhopper:
  datareader.file: $OSM_FILE
  graph.location: $GRAPH_DIR
  graph.dataaccess.default_type: $1

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
}

# ── GraphHopper starten ─────────────────────────────────────────────────────
# `server` baut einen fehlenden Graphen zwar selbst, aber im selben Prozess und
# mit derselben Zugriffsart wie das spaetere Routing. Deshalb laeuft der Import
# hier als eigener Schritt voraus: mit RAM_STORE (ein MMAP-Import dauert ein
# Vielfaches) und mit JAVA_OPTS allein, und erst der Server bekommt die
# sparsamen Einstellungen. `edges` ist dabei dasselbe Vollstaendigkeitsmerkmal
# wie im Block darueber, in graphhopper-deploy.sh und in switch-region.sh.
if [ "$GH_COMMAND" = "server" ] && [ ! -f "$GRAPH_DIR/edges" ]; then
    write_config RAM_STORE
    echo "Baue Routing-Graph (import, RAM_STORE, Graph-Cache: $GRAPH_DIR)..."
    java $JAVA_OPTS -jar "$GH_JAR" import "$CONFIG_FILE"
fi

if [ "$GH_COMMAND" = "server" ]; then
    write_config "$GH_DATAACCESS"
    echo "Starte GraphHopper (server, $GH_DATAACCESS, Graph-Cache: $GRAPH_DIR)..."
    exec java $JAVA_OPTS $GH_SERVER_JAVA_OPTS \
        -jar "$GH_JAR" \
        server "$CONFIG_FILE"
fi

# Jeder andere Unterbefehl (der Regionswechsel ruft `import` direkt) laeuft wie
# bisher: eine Phase, RAM_STORE, nur JAVA_OPTS.
write_config RAM_STORE
echo "Starte GraphHopper ($GH_COMMAND, RAM_STORE, Graph-Cache: $GRAPH_DIR)..."
exec java $JAVA_OPTS \
    -jar "$GH_JAR" \
    "$GH_COMMAND" "$CONFIG_FILE"
