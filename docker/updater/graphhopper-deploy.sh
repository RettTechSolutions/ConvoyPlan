#!/bin/bash
# graphhopper-deploy.sh — einen laufenden Graph-Import nicht abwuergen.
#
# Von BEIDEN Updater-Varianten per `source` eingebunden (update.sh UND
# update-images.sh) — dieselbe Begruendung wie bei region-hook.sh: beide haben
# einen Deploy, der `docker compose up -d` ueber ALLE Dienste laufen laesst, und
# ein Fix in nur einem der beiden waere fuer die andere Installationsart nicht
# vorhanden.
#
# Das Problem: `up -d` tauscht jeden Dienst mit neuem Image aus, auch
# graphhopper — und trifft dort unter Umstaenden einen laufenden Import. Der
# Graph-Bau der groesseren Regionen dauert 45-75 Minuten; ein Deploy mitten
# darin laesst einen TORSO im Volume zurueck: Bruchstuecke plus ein
# location_index, aber kein `edges`.
#
# Am 2026-09-19 hat genau das das Routing gekostet. Der Updater lief auf
# nightly/auto und deployte mehrmals taeglich; einer dieser Deploys traf den
# Import. Danach sah der Entrypoint einen passenden Fingerprint (er schreibt ihn
# VOR dem Import, er beweist also keine Vollstaendigkeit), GraphHopper
# importierte 13 Minuten neu, las den liegengebliebenen location_index und starb
# an "location index was opened with incorrect graph" — worauf
# `restart: unless-stopped` von vorn anfing.
#
# graphhopper/entrypoint.sh erkennt so einen Torso inzwischen selbst und raeumt
# ihn weg (graphhopper/tests/test_entrypoint_graph_zustand.sh). Der Schaden ist
# damit nicht mehr dauerhaft, aber teuer bleibt er: der Import beginnt von vorn,
# und solange routet nichts. Deshalb wird graphhopper aus dem Deploy
# herausgenommen, solange er baut, und hinterher nachgezogen.
#
# Nachgewiesen wird ueber dieselbe Datei, an der auch der Entrypoint und
# switch-region.sh Vollstaendigkeit ablesen: `edges` gibt es erst bei einem
# fertigen Graphen. Ein Regionswechsel kommt dabei nicht ins Gehege — dessen
# Lock haelt jedes Update ohnehin an (region_switch_blocked in region-hook.sh).
#
# Voraussetzungen beim Aufrufer, VOR dem `source`:
#   log()                    — beide Updater-Skripte definieren sie ganz oben
#   COMPOSE_PROJECT          — Name des Compose-Projekts
#   gh_deploy_graphhopper()  — tauscht NUR den graphhopper-Dienst; der Aufruf
#                              unterscheidet sich zwischen den beiden Skripten
#                              (Image-Pull vs. Build aus dem Checkout), deshalb
#                              liegt er beim Aufrufer und nicht hier.
#
# Stellt zwei Funktionen bereit:
#
#   _plan_deploy_services "<dienste>"
#       Setzt DEPLOY_SERVICES auf die Dienste, die dieses Deploy anfassen darf.
#       Das Ergebnis steht in einer Variablen und nicht auf stdout, weil log()
#       auch auf stdout schreibt — in einer Kommandosubstitution landeten die
#       Meldungen mitten in der Dienstliste.
#
#   _deploy_deferred_graphhopper
#       Holt einen zurueckgestellten Deploy nach, sobald der Import durch ist.
#       Gehoert in die Poll-Schleife und nicht an das Ende des Deploys: zwischen
#       beidem liegt bis zu eine Stunde, und solange darf der Updater nicht
#       stehenbleiben.

# Ueberschreibbar fuer Tests; die Betriebs-Defaults bleiben unveraendert —
# dasselbe Muster wie TRIGGER_FILE und REGION_STATUS_DIR.
GRAPH_DIR="${GRAPH_DIR:-/data/graph}"
GH_DEFER_FILE="${GH_DEFER_FILE:-/update_status/graphhopper_deferred}"
# Obergrenze der Zurueckstellung. Ohne sie schnitte ein Container, der aus einem
# ANDEREN Grund nie ein `edges` schreibt (OOM im Import, Platte voll), den
# GraphHopper-Dienst dauerhaft von jedem Update ab — auch von dem, das den
# Fehler behebt. Vier Stunden liegen deutlich ueber dem laengsten bekannten
# Import (75 min) und deutlich unter "faellt niemandem auf".
GH_IMPORT_GRACE="${GH_IMPORT_GRACE:-14400}"

_graphhopper_cid() {
    docker ps -q \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=graphhopper" | head -1
}

# Baut GraphHopper gerade? Laufender Container UND kein fertiger Graph.
#
# Fehlt das Graph-Volume in diesem Container (Altinstallation ohne den Mount),
# lautet die Antwort NEIN: lieber wie bisher deployen als wegen einer Datei, die
# hier gar nicht sichtbar ist, jeden Deploy dieses Dienstes zurueckzustellen.
# Ein gestoppter Container baut nichts — dann deployt es normal.
_graphhopper_importing() {
    if [ ! -d "${GRAPH_DIR}" ]; then return 1; fi
    if [ -f "${GRAPH_DIR}/edges" ]; then return 1; fi
    if [ -z "$(_graphhopper_cid)" ]; then return 1; fi
    return 0
}

# Epoch-Sekunden, seit wann zurueckgestellt wird; leer = gar nicht. Die Marke
# liegt im geteilten Volume und ueberlebt damit einen Neustart des Updaters —
# sonst begaenne die Geduldsfrist bei jedem Updater-Tausch von neuem.
_gh_defer_since() {
    if [ -f "${GH_DEFER_FILE}" ]; then
        tr -dc '0-9' < "${GH_DEFER_FILE}" 2>/dev/null || true
    fi
}

DEPLOY_SERVICES=""
_plan_deploy_services() {
    local all="$1" since now
    DEPLOY_SERVICES="${all}"
    if ! _graphhopper_importing; then
        rm -f "${GH_DEFER_FILE}" 2>/dev/null || true
        return 0
    fi
    now="$(date +%s)"
    since="$(_gh_defer_since)"
    if [ -z "${since}" ]; then
        since="${now}"
        echo "${since}" > "${GH_DEFER_FILE}" 2>/dev/null || true
    fi
    if [ "$((now - since))" -ge "${GH_IMPORT_GRACE}" ]; then
        log "GraphHopper hat seit $(( (now - since) / 60 )) Minuten noch immer keinen fertigen Graphen (kein ${GRAPH_DIR}/edges) — Geduldsfrist abgelaufen, der Dienst wird jetzt mitgetauscht."
        rm -f "${GH_DEFER_FILE}" 2>/dev/null || true
        return 0
    fi
    log "GraphHopper baut gerade den Routing-Graphen (kein ${GRAPH_DIR}/edges) — dieser Dienst wird aus dem Deploy herausgenommen und nach dem Import nachgezogen; alle anderen werden aktualisiert."
    DEPLOY_SERVICES="$(echo "${all}" | tr ' ' '\n' | grep -v '^graphhopper$' | tr '\n' ' ')"
}

_deploy_deferred_graphhopper() {
    [ -f "${GH_DEFER_FILE}" ] || return 0
    if _graphhopper_importing; then
        return 0
    fi
    log "Zurueckgestellter GraphHopper-Deploy wird nachgeholt (Graph ist fertig)."
    if gh_deploy_graphhopper; then
        rm -f "${GH_DEFER_FILE}" 2>/dev/null || true
        log "GraphHopper laeuft auf dem aktuellen Stand."
    else
        log "WARNUNG: Nachholen des GraphHopper-Deploys fehlgeschlagen — der naechste Zyklus versucht es erneut."
    fi
}
