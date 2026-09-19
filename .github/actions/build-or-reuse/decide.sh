#!/usr/bin/env bash
# Entscheidet, ob ein Image neu gebaut werden muss — die reine Logik, ohne
# Registry, ohne Git, ohne Workflow.
#
# Warum es diese Entscheidung ueberhaupt gibt: Jeder Bau erzeugt einen neuen
# Digest, auch wenn am Inhalt kein Byte anders ist. metadata-action schreibt
# Commit-SHA und Zeitstempel als Label in die Image-Konfiguration, und die
# gehoert zum Digest. Der Updater auf den Installationen vergleicht Image-IDs,
# sieht eine neue und tauscht den Container. Bei GraphHopper heisst das: der
# Routing-Graph wird neu geladen und das Routing faellt fuer Minuten aus — fuer
# ein Image, das sich nicht geaendert hat. Bei mehreren Merges auf main pro Tag
# entsprechend mehrmals taeglich.
#
# Gelesen wird ausschliesslich aus der Umgebung, geschrieben ausschliesslich
# nach stdout: die Begruendung fuer einen Neubau — oder nichts, wenn das
# veroeffentlichte Image stehen bleiben kann. Genau diese Trennung macht die
# Entscheidung ohne Docker und ohne Registry pruefbar
# (tests/test_image_wiederverwendung.sh).
#
# Erwartete Variablen:
#   FORCE          "true" erzwingt den Bau (Hand am Hebel: workflow_dispatch)
#   HAVE_IMAGE     "true", wenn unter dem beweglichen Tag ein Image liegt
#   TREE           Tree-Hash des Quellverzeichnisses, wie es jetzt ist
#   PREV_TREE      Tree-Hash aus dem Label des veroeffentlichten Images
#   BASE           Base-Image aus der letzten FROM-Zeile (nur fuer den Text)
#   BASE_DIGEST    Digest des Base-Images jetzt; leer = nicht ermittelbar
#   PREV_BASE      Base-Digest aus dem Label des veroeffentlichten Images
#   CREATED        Erstellungszeitpunkt des veroeffentlichten Images (RFC 3339)
#   MAX_AGE_DAYS   Spaetestens nach so vielen Tagen wird ohnehin gebaut
#   SOURCE_PATH    Pfad im Repository (nur fuer den Text)
set -uo pipefail

_alter_in_tagen() {
    # `date -d` ist GNU-spezifisch (Ubuntu-Runner). Bei leerem oder unlesbarem
    # Zeitstempel gibt es kein Alter — der Aufrufer baut dann lieber neu, als
    # ein unbekannt altes Image stehen zu lassen.
    local erstellt jetzt
    erstellt="$(date -u -d "${1:-}" +%s 2>/dev/null)"
    case "${erstellt:-}" in
        ''|*[!0-9]*) return 1 ;;
    esac
    jetzt="$(date -u +%s)"
    echo $(( (jetzt - erstellt) / 86400 ))
}

if [ "${FORCE:-false}" = "true" ]; then
    echo "Neubau erzwungen"
elif [ "${HAVE_IMAGE:-false}" != "true" ]; then
    echo "unter dem beweglichen Tag liegt noch kein Image"
elif [ -z "${PREV_TREE:-}" ]; then
    # Bestand von vor dieser Automatik: ohne Quellstand im Label ist nicht
    # entscheidbar, ob er zum jetzigen passt. Der erste Lauf baut deshalb
    # einmal und traegt das Label nach.
    echo "das veroeffentlichte Image traegt keinen Quellstand"
elif [ "${PREV_TREE}" != "${TREE:-}" ]; then
    echo "Quelltext unter ${SOURCE_PATH:-?} hat sich geaendert"
elif [ -n "${BASE_DIGEST:-}" ] && [ "${PREV_BASE:-}" != "${BASE_DIGEST}" ]; then
    # Sicherheitsupdates kommen fast immer hierueber und nicht aus unserem
    # eigenen Quelltext. Ohne Base-Digest (Registry nicht erreichbar) faellt
    # dieser Zweig aus und das Alter unten faengt es auf.
    echo "Base-Image ${BASE:-?} hat sich bewegt"
else
    alter="$(_alter_in_tagen "${CREATED:-}")" || alter=""
    if [ -z "${alter}" ]; then
        echo "Alter des veroeffentlichten Images nicht lesbar"
    elif [ "${alter}" -ge "${MAX_AGE_DAYS:-7}" ]; then
        # Auffangnetz: `apk upgrade` und `apt-get upgrade` ziehen neuere Pakete,
        # ohne dass sich der Digest des Base-Images bewegt. Ohne diese Grenze
        # bliebe ein unveraendertes Image beliebig lange auf alten Paketen.
        echo "veroeffentlichtes Image ist ${alter} Tage alt (Grenze: ${MAX_AGE_DAYS:-7})"
    fi
fi
exit 0
