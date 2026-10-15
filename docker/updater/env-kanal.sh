#!/bin/bash
# env-kanal.sh — die Image-Tags in der .env des Hosts auf den Kanal ziehen.
#
# Von update-images.sh per `source` eingebunden.
#
# Das Problem: Den Kanal (stable/beta/nightly/lts) waehlt der Admin im Portal,
# und der Updater setzt ihn nur in SEINER Umgebung durch — _apply_channel_images
# exportiert GRAPHHOPPER_IMAGE=…:nightly usw., bevor er `docker compose` ruft.
# Die .env auf dem Host behaelt dabei, was der Installer hineingeschrieben hat:
# …:latest. Ein `docker compose pull && up -d` von Hand im Installations-
# verzeichnis liest nur die .env und tauscht still auf Stable zurueck.
#
# Am 2026-10-09 ist genau das passiert: eine Nightly-Instanz, deren GraphHopper
# im Kreis neu startete, sollte von Hand den Fix ziehen und bekam stattdessen
# das Stable-Image vom 07.10. — aelter als der Stand, der vorher lief, und mit
# einem anderen Graph-Fingerprint, also ein weiterer kompletter Neuaufbau.
#
# Deshalb schreibt der Updater den Kanal-Tag zusaetzlich in die .env. Umgeschrieben
# werden nur die fuenf *_IMAGE-Zeilen, die auf ein Image dieses Projekts zeigen
# und einen Tag tragen — ein eigener Mirror, ein Digest (@sha256:…) oder eine
# Zeile in Anfuehrungszeichen bleiben, wie sie sind: lieber eine Zeile nicht
# anfassen als eine fremde Angabe kaputt umschreiben. Alles andere in der Datei
# (Passwoerter, Schluessel) wird Byte fuer Byte durchgereicht.
#
# Voraussetzungen beim Aufrufer, VOR dem `source`:
#   log()            — update-images.sh definiert sie ganz oben
#   STACK_FILE_PATH  — Host-Pfad der Compose-Datei; die .env liegt daneben
#                      (Installer: $INSTALL_DIR/.env und
#                      $INSTALL_DIR/docker-compose.yml)

# Ueberschreibbar fuer Tests — dasselbe Muster wie GH_DEFER_FILE.
ENV_KANAL_HELPER_IMAGE="${ENV_KANAL_HELPER_IMAGE:-alpine}"

_ENV_KANAL_PREFIX="ghcr.io/retttechsolutions/convoyplan/"

# Liest den Inhalt einer .env auf stdin und gibt ihn mit umgeschriebenen
# Image-Tags auf stdout aus. $1 = Kanal-Tag (latest|beta|nightly|lts).
# Reine Textverarbeitung ohne Docker, damit der Test sie direkt pruefen kann.
_env_kanal_umschreiben() {
    local tag="$1" zeile key val name
    while IFS= read -r zeile || [ -n "${zeile}" ]; do
        case "${zeile}" in
            BACKEND_IMAGE=*|FRONTEND_IMAGE=*|GRAPHHOPPER_IMAGE=*|UPDATER_IMAGE=*|REGION_MERGE_IMAGE=*)
                key="${zeile%%=*}"
                val="${zeile#*=}"
                name="${val#"${_ENV_KANAL_PREFIX}"}"
                # Nur "<Praefix><name>:<tag>" mit einfachem Namen und Tag —
                # kein Digest, kein Pfad, keine Anfuehrungszeichen.
                if [ "${name}" != "${val}" ] \
                    && [[ "${name}" =~ ^[a-z0-9-]+:[A-Za-z0-9._-]+$ ]]; then
                    printf '%s=%s%s:%s\n' "${key}" "${_ENV_KANAL_PREFIX}" "${name%%:*}" "${tag}"
                else
                    printf '%s\n' "${zeile}"
                fi
                ;;
            *)
                printf '%s\n' "${zeile}"
                ;;
        esac
    done
}

# Zieht die .env neben STACK_FILE_PATH auf den Kanal-Tag $1. Schreibt nur, wenn
# sich etwas aendert. Fehler werden geloggt und nie weitergereicht — eine nicht
# angepasste .env ist kein Grund, ein Update abzubrechen.
#
# Gelesen und geschrieben wird ueber einen kurzlebigen Hilfscontainer, wie beim
# Zurueckschreiben der Compose-Datei: der Updater selbst sieht vom Host nur die
# Compose-Datei. Gemountet wird das VERZEICHNIS, nicht die .env: fehlt die Datei,
# legte ein Datei-Mount auf dem Host ein leeres Verzeichnis namens .env an.
# Geschrieben wird mit `cat >` in die bestehende Datei — Besitzer und Rechte
# (der Installer legt sie mit umask 077 an) bleiben so erhalten.
_env_kanal_abgleichen() {
    local tag="$1" dir alt neu
    if [ -z "${STACK_FILE_PATH:-}" ] || [ "${STACK_FILE_PATH}" = "/dev/null" ]; then
        return 0
    fi
    dir="$(dirname "${STACK_FILE_PATH}")"

    if ! alt="$(docker run --rm -v "${dir}:/stack:ro" "${ENV_KANAL_HELPER_IMAGE}" \
            sh -c '[ -f /stack/.env ] && cat /stack/.env' 2>/dev/null)"; then
        return 0   # keine .env neben der Compose-Datei — nichts abzugleichen
    fi
    [ -n "${alt}" ] || return 0

    neu="$(printf '%s\n' "${alt}" | _env_kanal_umschreiben "${tag}")"
    [ "${neu}" = "${alt}" ] && return 0

    if printf '%s\n' "${neu}" | docker run --rm -i -v "${dir}:/stack" "${ENV_KANAL_HELPER_IMAGE}" \
            sh -c '[ -f /stack/.env ] && cat > /stack/.env' >/dev/null 2>&1; then
        log "Image-Tags in ${dir}/.env auf den Kanal-Tag :${tag} gesetzt — ein 'docker compose' von Hand zieht jetzt dieselben Images wie der Updater."
    else
        log "WARNUNG: ${dir}/.env konnte nicht auf den Kanal-Tag :${tag} gesetzt werden — ein 'docker compose pull' von Hand zoege weiter die Tags aus der .env."
    fi
}
