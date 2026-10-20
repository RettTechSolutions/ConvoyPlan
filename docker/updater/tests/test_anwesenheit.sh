#!/usr/bin/env bash
# docker/updater/tests/test_anwesenheit.sh
#
# Prueft die Zusage aus docker/updater/anwesenheit.sh: Ein AUTOMATISCHES Update
# wird zurueckgehalten, solange Nutzer oder Demo-Nutzer angemeldet sind — und
# nur dann. Kein Backend, keine Meldung, ein Superadmin allein oder die
# Hoechstfrist: es wird installiert. Der manuelle Trigger kommt an der Pruefung
# gar nicht vorbei.
#
#   Teil 1 — die Entscheidung, ohne Docker: die echte Datei wird gesourct.
#   Teil 2 — die Verdrahtung in beiden Updatern, am Quelltext.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATER_DIR="$(cd "$HERE/.." && pwd)"
FAILED=0

ok()    { echo "ok   — $1"; }
bad()   { echo "FAIL — $1"; FAILED=1; }
check() { if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }
eq()    { if [ "$2" = "$3" ]; then ok "$1"; else echo "FAIL — $1: erwartet '$3', bekam '$2'"; FAILED=1; fi; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ANW="$TMP/anwesenheit"
HOLD="$TMP/zurueckgehalten"
LOGF="$TMP/log.txt"
T0=1800000000

# Fuehrt update_zurueckhalten in einer Subshell aus; gibt "halten" oder
# "installieren" aus. $1 = Uhrzeit, $2 = Ziel.
entscheide() {
    ( set -euo pipefail
      log() { echo "$*" >> "$LOGF"; }
      ANWESENHEIT_FILE="$ANW" UPDATE_HOLD_FILE="$HOLD" ANWESENHEIT_JETZT="$1"
      UPDATE_HOLD_MAX="${UPDATE_HOLD_MAX:-86400}"
      # shellcheck source=/dev/null
      . "$UPDATER_DIR/anwesenheit.sh"
      if update_zurueckhalten "$2"; then echo halten; else echo installieren; fi )
}
# $4 = Fahrer-Links; ohne Angabe fehlt die Zeile, wie bei einem Backend von
# vor den Fahrer-Links.
meldung() {
    printf 'stand=%s\nnutzer=%s\ndemo=%s\n' "$1" "$2" "$3" > "$ANW"
    if [ -n "${4:-}" ]; then printf 'fahrer=%s\n' "$4" >> "$ANW"; fi
    if [ -n "${5:-}" ]; then printf 'tracker=%s\n' "$5" >> "$ANW"; fi
}
neu()     { rm -f "$ANW" "$HOLD"; : > "$LOGF"; }

echo "── Teil 1: die Entscheidung ─────────────────────────────────────────"

neu
eq "1: keine Meldung vom Backend → installieren" "$(entscheide $T0 'nightly abc')" installieren

neu; meldung $T0 0 0
eq "2: niemand angemeldet → installieren" "$(entscheide $T0 'nightly abc')" installieren

neu; meldung $T0 2 0
eq "3: Nutzer angemeldet → halten" "$(entscheide $T0 'nightly abc')" halten
[ -f "$HOLD" ]; check $? "3: Zustand fuers Admin-Panel geschrieben"
eq "3: seit" "$(grep '^seit=' "$HOLD")" "seit=$T0"
eq "3: Nutzerzahl" "$(grep '^nutzer=' "$HOLD")" "nutzer=2"
grep -q "zurueckgehalten" "$LOGF"; check $? "3: geloggt"

neu; meldung $T0 0 1
eq "4: nur Demo-Nutzer angemeldet → halten" "$(entscheide $T0 'stable v1')" halten

neu; meldung $T0 0 0 1
eq "4b: nur ein Fahrer-Link verbunden → halten" "$(entscheide $T0 'nightly abc')" halten
eq "4b: Fahrer-Links im Zustand fuers Panel" "$(grep '^fahrer=' "$HOLD")" "fahrer=1"

neu; meldung $T0 0 0 0 2
eq "4f: nur Tracker senden → halten" "$(entscheide $T0 'nightly abc')" halten
eq "4f: Tracker im Zustand fuers Panel" "$(grep '^tracker=' "$HOLD")" "tracker=2"

neu; meldung $T0 0 0 0 0
eq "4g: Tracker-Zeile mit 0 → installieren" "$(entscheide $T0 'nightly abc')" installieren

neu; meldung $T0 0 0 0
eq "4c: Fahrer-Zeile mit 0 → installieren" "$(entscheide $T0 'nightly abc')" installieren

neu; meldung $T0 0 0
eq "4d: altes Backend ohne Fahrer-Zeile, niemand da → installieren" "$(entscheide $T0 'nightly abc')" installieren

neu; printf 'stand=%s\nnutzer=0\ndemo=0\nfahrer=x\n' $T0 > "$ANW"
eq "4e: unlesbare Fahrer-Zeile zaehlt als 0" "$(entscheide $T0 'nightly abc')" installieren

neu; meldung $((T0 - 600)) 3 0
eq "5: veraltete Meldung (Backend schreibt nicht mehr) → installieren" "$(entscheide $T0 'stable v1')" installieren

neu; printf 'stand=%s\nnutzer=x\ndemo=0\n' $T0 > "$ANW"
eq "6: unlesbare Meldung → installieren" "$(entscheide $T0 'stable v1')" installieren

# 7: Halten geht weiter, "seit" bleibt, auch wenn ein neues Ziel kommt
neu; meldung $T0 1 0
entscheide $T0 'nightly a' >/dev/null
meldung $((T0 + 300)) 1 0
eq "7: weiter angemeldet → halten" "$(entscheide $((T0 + 300)) 'nightly b')" halten
eq "7: seit bleibt ueber den Zielwechsel stehen" "$(grep '^seit=' "$HOLD")" "seit=$T0"
eq "7: neues Ziel steht drin" "$(grep '^ziel=' "$HOLD")" "ziel=nightly b"
eq "7: einmal je Ziel geloggt" "$(grep -c 'zurueckgehalten:' "$LOGF")" 2
entscheide $((T0 + 300)) 'nightly b' >/dev/null
eq "7: gleiches Ziel nicht erneut geloggt" "$(grep -c 'zurueckgehalten:' "$LOGF")" 2

# 8: Niemand mehr da → installieren, Zustand weg
meldung $((T0 + 600)) 0 0
eq "8: alle abgemeldet → installieren" "$(entscheide $((T0 + 600)) 'nightly b')" installieren
[ ! -f "$HOLD" ]; check $? "8: Zustand entfernt"

# 9: Hoechstfrist
neu; meldung $T0 1 0
entscheide $T0 'stable v2' >/dev/null
# Der Updater prueft alle UPDATE_INTERVAL (300 s); hier alle 20 min, also
# innerhalb von HOLD_FORTSETZUNG — das Halten gilt als durchgehend.
for t in $(seq 1200 1200 85200); do
    meldung $((T0 + t)) 1 0
    entscheide $((T0 + t)) 'stable v2' >/dev/null
done
eq "9: kurz vor 24 h noch gehalten" "$(grep '^seit=' "$HOLD")" "seit=$T0"
meldung $((T0 + 86400)) 1 0
eq "9: nach 24 h trotz Nutzern → installieren" "$(entscheide $((T0 + 86400)) 'stable v2')" installieren
grep -q "trotz 1 angemeldeter Nutzer" "$LOGF"; check $? "9: Grund geloggt"

neu; meldung $T0 1 0
entscheide $T0 'stable v2' >/dev/null
meldung $((T0 + 90000)) 1 0
eq "10: UPDATE_HOLD_MAX=0 haelt unbegrenzt — aber nur mit frischem Zustand" \
    "$(UPDATE_HOLD_MAX=0 entscheide $((T0 + 90000)) 'stable v2')" halten
eq "10: ein Zustand ohne Fortschreibung zaehlt nicht als durchgehend" \
    "$(grep '^seit=' "$HOLD")" "seit=$((T0 + 90000))"

echo "── Teil 2: die Verdrahtung ──────────────────────────────────────────"

for s in update.sh update-images.sh; do
    grep -q '^source /anwesenheit.sh$' "$UPDATER_DIR/$s"
    check $? "$s bindet anwesenheit.sh ein"
done
grep -q '^COPY anwesenheit.sh /anwesenheit.sh$' "$UPDATER_DIR/Dockerfile"
check $? "das Updater-Image enthaelt anwesenheit.sh"

# update-images.sh: Aufruf in check_target_and_update, VOR do_update und
# NACH dem notify-Zweig; der Trigger-Zweig der Schleife ruft ihn nicht.
body="$(awk '/^check_target_and_update\(\)/,/^}/' "$UPDATER_DIR/update-images.sh")"
z_halt="$(printf '%s\n' "$body" | grep -n 'update_zurueckhalten' | head -1 | cut -d: -f1)"
z_notify="$(printf '%s\n' "$body" | grep -n 'read_mode)" = "notify"' | head -1 | cut -d: -f1)"
z_do="$(printf '%s\n' "$body" | grep -n 'if do_update' | head -1 | cut -d: -f1)"
[ -n "$z_halt" ] && [ -n "$z_notify" ] && [ -n "$z_do" ] && [ "$z_notify" -lt "$z_halt" ] && [ "$z_halt" -lt "$z_do" ]
check $? "update-images.sh: Pruefung zwischen notify und do_update"
trig="$(awk '/if \[ -f "\$\{TRIGGER_FILE\}" \]; then/,/continue$/' "$UPDATER_DIR/update-images.sh" | grep -c update_zurueckhalten)"
eq "update-images.sh: manueller Trigger haelt nicht zurueck" "$trig" 0

# update.sh: der Zweig verlangt ein gesetztes DEPLOYED (der Trigger leert es)
grep -q 'elif \[ -n "${DEPLOYED}" \] && \[ "${DEPLOYED}" != "${REMOTE}" \] && \\$' "$UPDATER_DIR/update.sh"
check $? "update.sh: Pruefung nur mit gesetztem DEPLOYED (nicht beim Trigger)"

exit $FAILED
