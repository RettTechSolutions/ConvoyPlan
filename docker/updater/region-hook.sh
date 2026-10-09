#!/bin/bash
# region-hook.sh — Einhängen des Regionswechsels in die Poll-Schleife.
#
# Von BEIDEN Updater-Varianten per `source` eingebunden (update.sh UND
# update-images.sh): docker-compose.yml:273 überschreibt den Dockerfile-
# ENTRYPOINT und lässt in der Standard-Installation update-images.sh laufen,
# nicht update.sh. Ein Einhängen nur in update.sh würde die Anforderung in
# Produktion nie abholen — deshalb liegt die Logik hier an einer Stelle,
# statt sie in beiden Skripten zu verdoppeln.
#
# Voraussetzung: Der Aufrufer hat vor dem `source` bereits eine Funktion
# `log()` definiert (beide Updater-Skripte tun das ganz oben).
#
# Stellt zwei Funktionen bereit, die die Poll-Schleife direkt neben der
# bestehenden TRIGGER_FILE-Behandlung aufruft:
#
#   run_region_switch_if_requested()
#       Führt switch-region.sh aus, wenn eine Anforderung vorliegt UND noch
#       kein Lock aktiv ist. Gibt 0 zurück, wenn sie ausgeführt wurde — der
#       Aufrufer soll dann mit `continue` in die nächste Runde springen.
#       Andernfalls 1 (nichts zu tun).
#
#   region_switch_blocked()
#       True, solange region.lock existiert. Spiegelbildlich zu is_busy() im
#       Backend (backend/app/services/region_switch.py): Ein Lock bedeutet
#       "beschäftigt", auch ein verwaistes Lock nach einem Absturz von
#       switch-region.sh (z. B. SIGKILL/OOM — der EXIT-Trap dort läuft dann
#       nicht). Die reguläre Update-Ausführung darf in diesem Fall NICHT
#       loslaufen: beide fassen denselben Compose-Stack an.
#
# Kein Doppelstart: run_region_switch_if_requested() prüft region.lock selbst
# noch einmal (zusätzlich zur Prüfung in switch-region.sh:376), damit ein
# zweiter Schleifendurchlauf kein bereits laufendes switch-region.sh erneut
# anstößt.

# Überschreibbar für Tests (echte Betriebs-Defaults bleiben unverändert),
# analog zu den env-gesteuerten Defaults in switch-region.sh.
REGION_STATUS_DIR="${REGION_STATUS_DIR:-/update_status}"
REGION_REQUEST_FILE="${REGION_REQUEST_FILE:-${REGION_STATUS_DIR}/region_request.json}"
REGION_LOCK_FILE="${REGION_LOCK_FILE:-${REGION_STATUS_DIR}/region.lock}"
REGION_CANCEL_FILE="${REGION_CANCEL_FILE:-${REGION_STATUS_DIR}/region.cancel}"
SWITCH_REGION_SCRIPT="${SWITCH_REGION_SCRIPT:-/switch-region.sh}"
# Graph- und OSM-Volume — dieselben Mounts wie in switch-region.sh.
REGION_GRAPH_DIR="${REGION_GRAPH_DIR:-/data/graph}"
REGION_OSM_DIR="${REGION_OSM_DIR:-/data/osm}"
# Marke, dass das Warten auf den Graph-Aufbau schon im Log steht.
REGION_WAIT_MARK="${REGION_WAIT_MARK:-${REGION_STATUS_DIR}/region_wait_graph}"
# Dieselbe Frist wie in graphhopper-deploy.sh und im Backend (graph_aufbau.py).
REGION_GRAPH_GRACE="${REGION_GRAPH_GRACE:-${GH_IMPORT_GRACE:-14400}}"
# So lange darf die Download-Datei unveraendert liegen und gilt noch als aktiv.
REGION_DOWNLOAD_STALL="${REGION_DOWNLOAD_STALL:-600}"

region_switch_blocked() {
    [ -f "${REGION_LOCK_FILE}" ]
}

# Ist die vorliegende Anforderung jetzt an der Reihe?
#
# Ein Wechsel kann auf einen Zeitpunkt gelegt werden — vor allem fuer den
# Wartungsmodus, in dem das Routing waehrend des Imports ausfaellt und den man
# deshalb nachts fahren will. Die Terminierung braucht dafuer weder einen
# Scheduler noch einen zweiten Prozess: Diese Schleife sieht ohnehin alle paar
# Sekunden nach, ob eine Anforderung daliegt. Sie bleibt einfach liegen, bis
# ihre Zeit gekommen ist — das ueberlebt auch einen Neustart des Updaters,
# weil sie im geteilten Volume liegt und nicht in irgendeinem Speicher.
#
# Verglichen werden Epoch-Sekunden, die das Backend NEBEN den ISO-Zeitstempel
# schreibt: Das Updater-Image ist Alpine, dessen busybox-`date` ISO-8601 mit
# Zeitzonen-Offset nicht verlaesslich parst. Zahlen vergleicht jede Shell.
region_switch_due() {
    local due now
    # Ein Abbruch sticht die Terminierung. switch-region.sh laeuft dann an,
    # sieht region.cancel und raeumt die Anforderung mit derselben Maschinerie
    # auf wie jeden anderen Abbruch — inklusive Statusmeldung fuers Panel.
    # Ohne das bliebe eine abbestellte Anforderung bis zu ihrem Termin liegen
    # und ginge dann trotzdem los.
    [ -f "${REGION_CANCEL_FILE}" ] && return 0
    due="$(sed -nE 's/.*"scheduled_for_epoch"[[:space:]]*:[[:space:]]*"([0-9]+)".*/\1/p' \
           "${REGION_REQUEST_FILE}" 2>/dev/null | head -1)"
    # Kein Termin: sofort faellig — der Normalfall, unveraendertes Verhalten.
    [ -n "${due}" ] || return 0
    now="$(date -u +%s 2>/dev/null)"
    case "${now:-}" in
        ''|*[!0-9]*)
            # Ohne lesbare Uhr lieber warten als raten: Ein zu frueh
            # gestarteter Wechsel nimmt im Wartungsmodus das Routing mit.
            return 1 ;;
    esac
    [ "${now}" -ge "${due}" ]
}

# Baut GraphHopper gerade selbst (nach einem Update, einem Neustart ohne
# fertigen Graphen)? Abgelesen an denselben Spuren wie im Backend
# (backend/app/services/graph_aufbau.py), ohne Docker:
#   - eine *.osm.pbf.tmp, die sich in den letzten zehn Minuten geaendert hat —
#     der Entrypoint laedt gerade das Extract;
#   - ein .graph_fingerprint ohne edges, juenger als die Frist — der Entrypoint
#     schreibt ihn unmittelbar VOR dem Import, edges entsteht erst am Ende.
#
# Ein Wechsel, der jetzt anliefe, importierte daneben: zwei Importe um denselben
# Speicher, und am Ende tauschte er das Graph-Verzeichnis und startete
# GraphHopper neu — der laufende Import waere verloren. Das Backend lehnt einen
# SOFORTIGEN Wechsel in dieser Lage schon ab; ein GEPLANTER darf angefordert
# werden und wartet hier, bis sein Termin erreicht UND der Bau fertig ist.
#
# Ueber der Frist gilt ein Import als haengend und haelt nichts mehr auf: Dann
# kann gerade ein Wechsel auf eine kleinere Region der Ausweg sein.
region_graph_building() {
    local now mtime f
    now="$(date -u +%s 2>/dev/null)"
    case "${now:-}" in ''|*[!0-9]*) return 1 ;; esac

    for f in "${REGION_OSM_DIR}"/*.osm.pbf.tmp; do
        [ -f "$f" ] || continue
        mtime="$(stat -c %Y "$f" 2>/dev/null)"
        case "${mtime:-}" in ''|*[!0-9]*) continue ;; esac
        [ "$((now - mtime))" -le "${REGION_DOWNLOAD_STALL}" ] && return 0
    done

    [ -f "${REGION_GRAPH_DIR}/edges" ] && return 1
    mtime="$(stat -c %Y "${REGION_GRAPH_DIR}/.graph_fingerprint" 2>/dev/null)"
    case "${mtime:-}" in ''|*[!0-9]*) return 1 ;; esac
    [ "$((now - mtime))" -le "${REGION_GRAPH_GRACE}" ]
}

run_region_switch_if_requested() {
    if [ -f "${REGION_REQUEST_FILE}" ] && [ ! -f "${REGION_LOCK_FILE}" ]; then
        # Noch nicht an der Reihe: liegen lassen und 1 zurueckgeben, damit der
        # Aufrufer mit dem regulaeren Update-Check weitermacht. Ein geplanter
        # Wechsel legt den Updater also nicht bis zu seinem Termin still.
        #
        # Bewusst ohne Logzeile: Diese Funktion laeuft alle paar Sekunden, eine
        # Meldung je Durchlauf ersaeufte region.log. Dass ein Wechsel geplant
        # ist, steht beim Anfordern im Log und zeigt das Panel aus dem Status.
        region_switch_due || return 1
        # Abbruch geht vor: switch-region.sh raeumt die Anforderung dann nur
        # auf, es importiert nichts. Sonst wartet ein faelliger Wechsel auf
        # einen laufenden Graph-Aufbau — mit genau EINER Logzeile, aus
        # demselben Grund wie oben.
        if [ ! -f "${REGION_CANCEL_FILE}" ] && region_graph_building; then
            if [ ! -f "${REGION_WAIT_MARK}" ]; then
                log "Regionswechsel ist faellig, GraphHopper baut aber gerade seinen Graphen — der Wechsel startet nach dessen Abschluss."
                : > "${REGION_WAIT_MARK}" 2>/dev/null || true
            fi
            return 1
        fi
        rm -f "${REGION_WAIT_MARK}" 2>/dev/null || true
        log "Regionswechsel angefordert — starte switch-region.sh"
        "${SWITCH_REGION_SCRIPT}" || log "Regionswechsel fehlgeschlagen (siehe region.log)"
        return 0
    fi
    return 1
}
