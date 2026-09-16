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
        log "Regionswechsel angefordert — starte switch-region.sh"
        "${SWITCH_REGION_SCRIPT}" || log "Regionswechsel fehlgeschlagen (siehe region.log)"
        return 0
    fi
    return 1
}
