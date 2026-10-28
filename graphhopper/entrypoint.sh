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
# max_weight + max_weight_except: Gewichtsgrenzen (Brücken, Lkw-Verbote) samt
# Ausnahme wie "Anlieger frei"; max_axle_load: Achslastgrenzen (Zeichen 263) —
# gesperrt bzw. ausgewiesen in backend/app/services/gewichtsgrenzen.py.
# Fehlen diese Encoded Values im Graph, lehnt GraphHopper jede Routing-Anfrage
# ab, die sie benutzt; das Backend faellt fuer max_weight* und max_axle_load auf
# eine Anfrage ohne zurueck (routing.calculate_route), fuer die uebrigen nicht.
ENCODED_VALUES="car_access, car_average_speed, road_class, max_speed, max_height, max_weight, max_weight_except, max_axle_load"

# Abbiegeverbote aus OSM (type=restriction) kennt GraphHopper nur in Profilen
# mit turn_costs. Ohne sie routete `car` bis 2026-10 ueber jedes Verbot hinweg:
# an der B 472 bei Peissenberg (Anschluss WM 15) die Auffahrt hinauf und an
# ihrer Spitze per Haarnadel in die Gegenrichtung — genau das verbietet dort
# Relation 2083454 (only_right_turn). Die Einbahnregel hielt, das Abbiegen nicht.
# Der Wert steht im Fingerprint, weil GraphHopper einen Graphen mit anderen
# Profilen nicht laedt — ein Bestand ohne turn_costs muss neu gebaut werden.
TURN_COSTS_VEHICLES="motorcar, motor_vehicle"

# Die GraphHopper-Fassung (ENV aus dem Dockerfile) gehoert ebenfalls in den
# Fingerprint: das Speicherformat wechselt zwischen den Versionen (9.1 -> 10.2
# z. B. edges 22 -> 23), und einen Graphen einer anderen Fassung laedt
# GraphHopper nicht. Ohne diesen Teil saehe der Entrypoint nach einem
# Versionssprung "Fingerprint stimmt, edges da" und liesse den Server an dem
# alten Graphen scheitern — bei jedem Neustart wieder.
GH_VERSION="${GH_VERSION:-unbekannt}"

# Der kompilierte Graph gehört zu genau EINER OSM-Datei und EINEM Satz Encoded
# Values. Ändert sich eines von beidem, muss er neu gebaut werden: bei den
# Encoded Values, weil GraphHopper sonst nicht startet bzw. Anfragen ablehnt —
# bei der OSM-Datei, weil GraphHopper einen vorhandenen Graphen kommentarlos
# weiterverwendet und nach einem Regionswechsel sonst still weiter die alte
# Region routen würde. Beides steckt deshalb im Fingerprint, dazu die Profile
# (turn_costs) und die GraphHopper-Fassung — Begruendung jeweils oben.
FINGERPRINT="$OSM_FILENAME|$ENCODED_VALUES|turn_costs: $TURN_COSTS_VEHICLES|graphhopper: $GH_VERSION"
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
        REBUILD_REASON="Kartenregion, Encoded Values, Profile oder GraphHopper-Version haben sich geändert"
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
        rm -rf "$GRAPH_DIR"/* "$FINGERPRINT_FILE" "$LEGACY_FINGERPRINT_FILE" \
            "$GRAPH_DIR/.lm_vorbereitung" "$GRAPH_DIR/.lm_gescheitert"
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

# JVM-Optionen NUR fuer den Import, zusaetzlich zu JAVA_OPTS. Die Vorgabe
# schreibt beim Beenden den Heap ins Log ("garbage-first heap total …K"). Der
# Wert `total` ist der zuletzt belegte Heap — weil G1 waehrend eines Imports
# praktisch nur waechst, eine brauchbare Naeherung fuer den Hoechststand. Er
# landet ueber den Regionswechsel in region.log und ist die einzige Messung,
# an der sich die Schaetzung in backend/app/services/region_estimate.py
# pruefen laesst; bis 2026-10 gab es nur Richtwerte aus dem Installer.
GH_IMPORT_JAVA_OPTS="${GH_IMPORT_JAVA_OPTS:--Xlog:gc+heap+exit}"

# Nur fuer Tests ueberschreibbar (siehe graphhopper/tests/) — im Container immer
# der Default, dasselbe Muster wie REGION_SOURCE_SCRIPT.
GH_JAR="${GH_JAR:-/graphhopper/graphhopper.jar}"
CONFIG_FILE="/tmp/graphhopper-config.yml"

# Keine Contraction Hierarchies (kein profiles_ch). Mit turn_costs waere CH fuer
# car kantenbasiert, und das ist die mit Abstand teuerste Phase des Imports —
# an Heap wie an Zeit, fuer DACH ein Vielfaches des knotenbasierten CH von
# frueher. Genutzt haette sie nur die Praeferenz „schnell" ohne Fahrzeughoehe:
# jede andere Anfrage schickt ein Custom Model und damit ch.disable
# (backend/app/services/routing.py), laeuft also ohnehin flexibel. Ohne CH
# routet GraphHopper jede Anfrage so; ch.disable bleibt erlaubt und wirkungslos.
# Nicht im Fingerprint: einen fertigen Graphen MIT CH-Daten laedt 10.2 unter
# dieser Konfiguration anstandslos, ein Neuaufbau braeuchte es dafuer nicht.
#
# Statt CH: Landmarks (LM, profiles_lm) fuer `car`. Ohne jede Beschleunigung
# brach eine Route Bayern–Albanien (3.250 km) an der Frist des Backends ab.
# LM vertraegt das Custom Model je Anfrage, solange es Gewichte nur ERHOEHT —
# das tun alle in routing.py (priority <= 1, limit_to, hoeheres
# distance_influence); wer dort ein multiply_by > 1 einbaut, macht LM-Routen
# falsch, nicht nur langsamer. `truck` fragt das Backend nicht an, es bekommt
# keine. GH_LM=false schaltet LM ab (Speicher; die Landmarks kosten 64 Byte je
# Knoten im Seitencache).
#
# Nicht im Fingerprint, und das ist der Punkt: einem fertigen Graphen ohne
# Landmarks rechnet GraphHopper sie beim Laden nach, ein Neuaufbau ist nicht
# noetig. Nur soll das nicht der Server tun (MMAP, kleiner Heap), sondern ein
# eigener Lauf vorweg — siehe unten bei LM_MARKE.
GH_LM="${GH_LM:-true}"
LM_DATEI="$GRAPH_DIR/landmarks_car"
# Liegt, solange die Landmarks eines fertigen Graphen nachgerechnet werden.
# Daran erkennen Deploy (docker/updater/graphhopper-deploy.sh), Regionswechsel
# (region-hook.sh) und Statusseite (backend/app/services/graph_aufbau.py) den
# Aufbau — `edges` liegt dann schon da und sagt nichts mehr.
LM_MARKE="$GRAPH_DIR/.lm_vorbereitung"

# $1: Zugriffsart (RAM_STORE oder MMAP). Wird je Phase neu geschrieben, weil
# sich die beiden Laeufe genau in dieser einen Zeile unterscheiden sollen.
# $2: mit Landmarks (ja/nein).
write_config() {
    LM_BLOCK=""
    if [ "$2" = "ja" ]; then
        LM_BLOCK="  profiles_lm:
    - profile: car
"
    fi
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
      turn_costs:
        vehicle_types: [$TURN_COSTS_VEHICLES]
        u_turn_costs: 60
      custom_model_files: [car.json]
    - name: truck
      turn_costs:
        vehicle_types: [$TURN_COSTS_VEHICLES]
        u_turn_costs: 60
      custom_model_files: [car.json]
${LM_BLOCK}
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
#
# Landmarks gehoeren nur dann in die Konfiguration, wenn sie fertig daliegen:
# fehlen sie, rechnete GraphHopper sie beim Laden selbst nach — im Server also
# per MMAP und mit dessen Optionen, und ein OutOfMemoryError beendete dort den
# Dienst (ExitOnOutOfMemoryError), der ohne Landmarks einwandfrei liefe.
lm_bereit() {
    [ "$GH_LM" != "false" ] && [ -f "$LM_DATEI" ] && [ ! -f "$LM_MARKE" ]
}

# Rechnet die Landmarks eines fertigen Graphen nach, als eigener `import`-Lauf
# (RAM_STORE, JAVA_OPTS) — GraphHopper liest dabei keine OSM-Daten, er laedt den
# Graphen und ergaenzt nur die Landmarks. Getrennt vom eigentlichen Import,
# damit dessen Speicherspitze bleibt, wie sie war: Scheitert dieser Schritt,
# laeuft das Routing weiter wie vor LM, statt im Kreis neu zu importieren.
#
# LM_MARKE liegt, solange gerechnet wird. Findet ein Start sie vor, wurde der
# Lauf abgebrochen (Deploy, OOM, Neustart): was an landmarks_* liegt, ist dann
# unvollstaendig und wird verworfen. LM_GESCHEITERT haelt fest, fuer welchen
# Graphen es nicht ging — sonst kostete jeder Neustart denselben vergeblichen
# Versuch, und nach einem Regionswechsel liefe er in die Gesundheitsfrist von
# switch-region.sh. Bewusst NICHT an JAVA_OPTS gebunden: der Import-Container des
# Wechsels laeuft mit anderen als der Server danach, und der versuchte es dann
# erneut, genau in dieser Frist. Neuer Versuch: neuer Graph oder die Datei
# loeschen.
LM_GESCHEITERT="$GRAPH_DIR/.lm_gescheitert"
lm_nachrechnen() {
    [ "$GH_LM" != "false" ] || return 0
    [ -f "$GRAPH_DIR/edges" ] || return 0
    if [ -f "$LM_MARKE" ]; then
        echo "Abgebrochene Landmark-Berechnung gefunden — wird verworfen und neu gestartet."
        rm -f "$GRAPH_DIR"/landmarks_* "$LM_MARKE"
    fi
    [ -f "$LM_DATEI" ] && return 0
    if [ "$(cat "$LM_GESCHEITERT" 2>/dev/null || true)" = "$FINGERPRINT" ]; then
        echo "WARNUNG: Landmarks liessen sich fuer diesen Graphen schon einmal nicht berechnen — Routing ohne LM. Neuer Versuch: $LM_GESCHEITERT loeschen (etwa nach mehr Heap in JAVA_OPTS); GH_LM=false schaltet LM ab."
        return 0
    fi
    : > "$LM_MARKE"
    write_config RAM_STORE ja
    echo "Berechne Landmarks fuer car (import, RAM_STORE, Graph-Cache: $GRAPH_DIR)..."
    if java $JAVA_OPTS $GH_IMPORT_JAVA_OPTS -jar "$GH_JAR" import "$CONFIG_FILE"; then
        rm -f "$LM_MARKE" "$LM_GESCHEITERT"
    else
        echo "WARNUNG: Landmark-Berechnung fehlgeschlagen — Routing laeuft ohne LM weiter (langsamer bei langen Routen)."
        rm -f "$GRAPH_DIR"/landmarks_* "$LM_MARKE"
        printf '%s' "$FINGERPRINT" > "$LM_GESCHEITERT"
    fi
}

lm_konfig() {
    if lm_bereit; then echo ja; else echo nein; fi
}

if [ "$GH_COMMAND" = "server" ] && [ ! -f "$GRAPH_DIR/edges" ]; then
    rm -f "$LM_GESCHEITERT"
    write_config RAM_STORE nein
    echo "Baue Routing-Graph (import, RAM_STORE, Graph-Cache: $GRAPH_DIR)..."
    java $JAVA_OPTS $GH_IMPORT_JAVA_OPTS -jar "$GH_JAR" import "$CONFIG_FILE"
fi

if [ "$GH_COMMAND" = "server" ]; then
    lm_nachrechnen
    write_config "$GH_DATAACCESS" "$(lm_konfig)"
    echo "Starte GraphHopper (server, $GH_DATAACCESS, Landmarks: $(lm_konfig), Graph-Cache: $GRAPH_DIR)..."
    exec java $JAVA_OPTS $GH_SERVER_JAVA_OPTS \
        -jar "$GH_JAR" \
        server "$CONFIG_FILE"
fi

# Der Regionswechsel ruft `import` direkt und wartet danach nur kurz auf einen
# gesunden Server (REGION_HEALTH_TIMEOUT in switch-region.sh) — die Landmarks
# rechnet deshalb schon dieser Container, nicht erst der Server nach dem Tausch.
if [ "$GH_COMMAND" = "import" ]; then
    rm -f "$LM_GESCHEITERT"
    write_config RAM_STORE nein
    echo "Starte GraphHopper (import, RAM_STORE, Graph-Cache: $GRAPH_DIR)..."
    java $JAVA_OPTS $GH_IMPORT_JAVA_OPTS -jar "$GH_JAR" import "$CONFIG_FILE"
    lm_nachrechnen
    exit 0
fi

# Jeder andere Unterbefehl laeuft wie bisher: eine Phase, RAM_STORE, JAVA_OPTS.
write_config RAM_STORE "$(lm_konfig)"
echo "Starte GraphHopper ($GH_COMMAND, RAM_STORE, Graph-Cache: $GRAPH_DIR)..."
exec java $JAVA_OPTS \
    -jar "$GH_JAR" \
    "$GH_COMMAND" "$CONFIG_FILE"
