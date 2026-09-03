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

REGION_REQUEST_FILE="/update_status/region_request.json"
REGION_LOCK_FILE="/update_status/region.lock"
# Überschreibbar für Tests (echte Betriebs-Defaults bleiben unverändert),
# analog zu den env-gesteuerten Defaults in switch-region.sh.
SWITCH_REGION_SCRIPT="${SWITCH_REGION_SCRIPT:-/switch-region.sh}"

region_switch_blocked() {
    [ -f "${REGION_LOCK_FILE}" ]
}

run_region_switch_if_requested() {
    if [ -f "${REGION_REQUEST_FILE}" ] && [ ! -f "${REGION_LOCK_FILE}" ]; then
        log "Regionswechsel angefordert — starte switch-region.sh"
        "${SWITCH_REGION_SCRIPT}" || log "Regionswechsel fehlgeschlagen (siehe region.log)"
        return 0
    fi
    return 1
}
