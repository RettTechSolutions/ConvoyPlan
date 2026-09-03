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
# Es wird am ERSTEN "=" je Zeile getrennt, da JAVA_OPTS-Werte Leerzeichen
# (aber kein "=") enthalten.

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
    else
        echo "WARNUNG: .region ist unvollstaendig oder fehlerhaft ($REGION_FILE) — Env-Vorgaben werden unveraendert verwendet" >&2
    fi

    unset region_url region_filename region_java_opts region_ok region_key region_value region_line
fi
