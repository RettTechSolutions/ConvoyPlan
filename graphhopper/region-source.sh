# Liest die aktive Region aus .region und ueberschreibt damit die Env-
# Vorgaben. Fehlt die Datei, bleibt alles wie bisher — Regressionsschutz fuer
# Bestandsinstallationen.
#
# WICHTIG: Diese Datei wird von entrypoint.sh per ". /region-source.sh"
# GESOURCT, nicht ausgefuehrt. Der Entrypoint ist POSIX-sh (Alpine/BusyBox-
# Basis), deshalb hier keine bash-Erweiterungen ([[ ]], Arrays, "local", ...)
# — nur POSIX-sh-Konstrukte.
#
# Dateiformat (von Task 5 / GET /api/admin/region bereits festgelegt):
#   OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
#   OSM_FILENAME=berlin-latest.osm.pbf
#   JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
# Optional (nur bei zusammengesetzten Regionen, siehe Mehrere-Regionen-Spec):
#   OSM_SOURCES=europe/germany|europe/poland|europe/czech-republic
# Es wird am ERSTEN "=" je Zeile getrennt, da JAVA_OPTS-Werte Leerzeichen
# und ggf. selbst ein "=" enthalten koennen (z.B. "-XX:Flag=Wert") — alles
# ab dem ersten "=" gehoert zum Wert.
#
# OSM_SOURCES ist der EINZIGE optionale Schluessel: er darf in der Datei
# fehlen, ohne dass die Alles-oder-nichts-Regel unten greift und die Datei
# verwirft. Er markiert eine zusammengesetzte Region (mehrere Geofabrik-
# Extracts zu einer Karte verschmolzen) — entrypoint.sh liest ihn, um in
# diesem Fall selbst NICHT herunterzuladen, sondern auf den Updater zu warten
# (siehe entrypoint.sh, Abschnitt "OSM-Daten holen").
#
# Bewusste Entscheidungen ueber den Drei-Zeilen-Normalfall hinaus:
#   - Kommentarzeilen ("#...") sind NICHT Teil des festgelegten Formats und
#     werden NICHT toleriert: eine solche Zeile faellt wie jeder unbekannte
#     Schluessel unter "*)" unten und verwirft die komplette Datei. Das ist
#     bewusst streng (kein Komfort-Feature ergaenzt, das nicht verlangt war)
#     und konsistent mit der Alles-oder-nichts-Regel für alles Unerwartete.
#   - Doppelte Schluessel: der LETZTE Wert gewinnt (einfache Ueberschreib-
#     Semantik, wie man es von Shell-Variablenzuweisungen kennt).
#   - Reihenfolge der drei Schluessel ist beliebig — es wird zeilenweise
#     geparst und erst am Ende auf Vollstaendigkeit geprueft.

REGION_FILE="${OSM_DIR:-/data/osm}/.region"

if [ -f "$REGION_FILE" ]; then
    # Neue Werte zunaechst in Zwischenvariablen lesen statt sie sofort zu
    # exportieren: eine beschaedigte oder halb geschriebene .region (Zeile
    # ohne "=", unbekannter Schluessel, fehlender Schluessel) darf niemals
    # dazu fuehren, dass der Container mit einem Mischzustand aus alter und
    # neuer Region startet. Deshalb gilt "alles oder nichts" — entweder alle
    # drei Schluessel sind vollstaendig und sauber vorhanden, oder die
    # komplette Datei wird verworfen und die bisherigen Env-Vorgaben bleiben
    # unangetastet.
    region_url=""
    region_filename=""
    region_java_opts=""
    region_sources=""
    region_ok=1

    while IFS= read -r region_line || [ -n "$region_line" ]; do
        # Leere Zeilen ueberspringen (z.B. am Dateiende)
        [ -z "$region_line" ] && continue

        # Am ERSTEN "=" trennen: alles vor dem ersten "=" ist der Schluessel,
        # alles danach der Wert (kann selbst "=" oder Leerzeichen enthalten).
        region_key="${region_line%%=*}"
        if [ "$region_key" = "$region_line" ]; then
            # Kein "=" in der Zeile — Format verletzt, Datei ist beschaedigt
            region_ok=0
            break
        fi
        region_value="${region_line#*=}"

        case "$region_key" in
            OSM_DOWNLOAD_URL) region_url="$region_value" ;;
            OSM_FILENAME)     region_filename="$region_value" ;;
            JAVA_OPTS)        region_java_opts="$region_value" ;;
            OSM_SOURCES)      region_sources="$region_value" ;;
            *)
                # Unbekannter Schluessel — lieber die ganze Datei verwerfen
                # als auf gut Glueck weiterzumachen
                region_ok=0
                break
                ;;
        esac
    done < "$REGION_FILE"

    if [ "$region_ok" -eq 1 ] && [ -n "$region_url" ] && [ -n "$region_filename" ] && [ -n "$region_java_opts" ]; then
        export OSM_DOWNLOAD_URL="$region_url"
        export OSM_FILENAME="$region_filename"
        export JAVA_OPTS="$region_java_opts"
        # OSM_SOURCES ist optional: nur exportieren, wenn wirklich ein Wert
        # dasteht. Ein leerer Export wuerde entrypoint.sh nicht taeuschen
        # (dort wird auf -n geprueft), aber eine leere Variable in der
        # Umgebung zu hinterlassen ist unsauber.
        if [ -n "$region_sources" ]; then
            export OSM_SOURCES="$region_sources"
        else
            # Ohne else bliebe ein zuvor exportiertes OSM_SOURCES stehen: ein
            # zweites Sourcen mit einer .region OHNE den Schluessel wuerde die
            # Region wechseln, den Zusammensetzungs-Marker aber behalten. Heute
            # nicht erreichbar (entrypoint.sh sourct einmal je Prozess), aber
            # eine Falle fuer jedes kuenftige Re-Sourcing.
            unset OSM_SOURCES
        fi
    else
        echo "WARNUNG: .region ist unvollstaendig oder fehlerhaft ($REGION_FILE) — Env-Vorgaben werden unveraendert verwendet" >&2
    fi

    unset region_sources region_url region_filename region_java_opts region_ok region_key region_value region_line
fi
