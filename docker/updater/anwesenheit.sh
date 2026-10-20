#!/bin/bash
# anwesenheit.sh — kein automatisches Update, solange jemand im Portal arbeitet.
#
# Von BEIDEN Updater-Varianten per `source` eingebunden (update.sh UND
# update-images.sh) — dieselbe Begruendung wie bei graphhopper-deploy.sh: ein
# Fix in nur einem der beiden waere fuer die andere Installationsart nicht da.
#
# Ein Deploy tauscht Backend und Frontend; wer gerade plant, verliert den
# Live-Kanal, und im Nightly-Kanal geschah das mehrmals taeglich mitten in der
# Arbeit. Zurueckgehalten wird deshalb, solange angemeldete Nutzer,
# Demo-Nutzer oder Fahrer-Links aktiv sind (ein Fahrer-Link zaehlt, solange er
# verbunden ist, und fuenf Minuten nach dem Abriss). Superadmins zaehlen NICHT: der Betreiber sitzt selbst
# im Admin-Portal, und sonst hielte er sein eigenes Update auf.
#
# Gilt nur fuer das AUTOMATISCHE Update. Der manuelle Trigger ("Jetzt updaten")
# ruft diese Funktion nicht auf — wer ihn drueckt, hat entschieden.
#
# Die Zahlen schreibt das Backend (app/services/anwesenheit.py) alle 30 s nach
# ANWESENHEIT_FILE, aus seiner Aktivitaets-Registry (aktiv = Anfrage in den
# letzten fuenf Minuten). Zwei Rueckfaelle, beide zur Installation hin:
#
#   - Fehlt die Datei oder ist ihr Stand aelter als ANWESENHEIT_MAX_ALTER, wird
#     installiert. Ein Backend, das nicht mehr schreibt, ist kaputt oder alt —
#     genau dann darf das Update nicht an ihm haengen.
#   - Nach UPDATE_HOLD_MAX Sekunden durchgehenden Zurueckhaltens wird trotzdem
#     installiert (0 = nie). Eine Instanz, auf der rund um die Uhr jemand
#     arbeitet, bekaeme sonst nie ein Update, auch keinen Sicherheitsfix.
#
# Waehrend zurueckgehalten wird, steht der Zustand in HOLD_FILE; das Backend
# zeigt ihn im Admin-Panel an. "seit" bleibt ueber einen Zielwechsel hinweg
# stehen (sonst setzte jeder neue Nightly-Build die Frist zurueck) und gilt nur
# fort, solange die Datei frisch ist (HOLD_FORTSETZUNG).
#
# Voraussetzung beim Aufrufer, VOR dem `source`: log().
#
#   update_zurueckhalten "<ziel>"
#       0 = zurueckhalten (nicht installieren), 1 = installieren.

ANWESENHEIT_FILE="${ANWESENHEIT_FILE:-/update_status/anwesenheit}"
ANWESENHEIT_MAX_ALTER="${ANWESENHEIT_MAX_ALTER:-180}"
HOLD_FILE="${UPDATE_HOLD_FILE:-/update_status/zurueckgehalten}"
UPDATE_HOLD_MAX="${UPDATE_HOLD_MAX:-86400}"
HOLD_FORTSETZUNG="${HOLD_FORTSETZUNG:-1800}"

# Uhr ueberschreibbar fuer Tests.
_anw_jetzt() { echo "${ANWESENHEIT_JETZT:-$(date +%s)}"; }

# Wert eines Schluessels "name=wert" aus einer Datei; leer, wenn er fehlt oder
# keine Zahl ist. Ganze Zahl oder nichts: die Werte landen in $(( )).
_anw_wert() {
    local v
    v="$(grep -m1 "^$2=" "$1" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true)"
    case "${v}" in
        ''|*[!0-9]*) echo "" ;;
        *) echo "${v}" ;;
    esac
}

update_zurueckhalten() {
    local ziel="$1" jetzt stand nutzer demo fahrer seit zuletzt alt_ziel
    jetzt="$(_anw_jetzt)"

    stand="$(_anw_wert "${ANWESENHEIT_FILE}" stand)"
    nutzer="$(_anw_wert "${ANWESENHEIT_FILE}" nutzer)"
    demo="$(_anw_wert "${ANWESENHEIT_FILE}" demo)"
    # Optional: ein Backend von vor den Fahrer-Links schreibt die Zeile nicht.
    fahrer="$(_anw_wert "${ANWESENHEIT_FILE}" fahrer)"
    fahrer="${fahrer:-0}"
    if [ -z "${stand}" ] || [ -z "${nutzer}" ] || [ -z "${demo}" ] \
       || [ $((jetzt - stand)) -gt "${ANWESENHEIT_MAX_ALTER}" ]; then
        if [ -f "${HOLD_FILE}" ]; then
            log "Keine aktuelle Anwesenheitsmeldung vom Backend — Update wird nicht laenger zurueckgehalten."
        fi
        rm -f "${HOLD_FILE}"
        return 1
    fi

    if [ $((nutzer + demo + fahrer)) -eq 0 ]; then
        if [ -f "${HOLD_FILE}" ]; then
            log "Niemand mehr angemeldet — zurueckgehaltenes Update wird installiert."
        fi
        rm -f "${HOLD_FILE}"
        return 1
    fi

    seit=""
    alt_ziel=""
    if [ -f "${HOLD_FILE}" ]; then
        zuletzt="$(_anw_wert "${HOLD_FILE}" zuletzt)"
        if [ -n "${zuletzt}" ] && [ $((jetzt - zuletzt)) -le "${HOLD_FORTSETZUNG}" ]; then
            seit="$(_anw_wert "${HOLD_FILE}" seit)"
            alt_ziel="$(grep -m1 '^ziel=' "${HOLD_FILE}" 2>/dev/null | cut -d= -f2- || true)"
        fi
    fi
    [ -z "${seit}" ] && seit="${jetzt}"

    if [ "${UPDATE_HOLD_MAX}" -gt 0 ] && [ $((jetzt - seit)) -ge "${UPDATE_HOLD_MAX}" ]; then
        log "Update seit $(( (jetzt - seit) / 3600 )) h zurueckgehalten — wird trotz ${nutzer} angemeldeter Nutzer, ${demo} Demo-Nutzer und ${fahrer} Fahrer-Links installiert (UPDATE_HOLD_MAX=${UPDATE_HOLD_MAX})."
        rm -f "${HOLD_FILE}"
        return 1
    fi

    if [ "${alt_ziel}" != "${ziel}" ]; then
        log "Update ${ziel} zurueckgehalten: ${nutzer} Nutzer, ${demo} Demo-Nutzer und ${fahrer} Fahrer-Links aktiv — installiert wird, sobald niemand mehr aktiv ist."
    fi
    printf 'seit=%s\nzuletzt=%s\nziel=%s\nnutzer=%s\ndemo=%s\nfahrer=%s\n' \
        "${seit}" "${jetzt}" "${ziel}" "${nutzer}" "${demo}" "${fahrer}" > "${HOLD_FILE}" 2>/dev/null || true
    return 0
}
