#!/usr/bin/env bash
# Prueft den Nachweisschritt "Beleg 1/3" des Jobs `region-switch` in ci.yml:
# haelt er einem GraphHopper stand, der waehrend des Zugriffs neu startet, und
# sagt er im Fehlerfall, was los war?
#
# Warum es diesen Test gibt: Am 2026-09-21 war der Schritt rot mit `exit 137`
# und einer einzigen Zeile Ausgabe — der Container war unter dem
# `docker compose exec` weggestartet worden. Zeitgleich fiel derselbe Job auf
# `main` um, auf demselben Stand lief er Minuten spaeter durch. Ohne Diagnose
# liess sich nicht entscheiden, ob es der Runner war oder ein echter Bruch im
# Regionswechsel; geraten wurde auf Speicherdruck, belegt war nichts.
#
# Der Schritt wird NICHT nachgebaut, sondern aus ci.yml herausgeschnitten: ein
# Nachbau prueft die Kopie, nicht das Original. Docker, curl, free und sleep
# sind Stubs — der Test braucht weder Container noch Netz noch Wartezeit.
#
# Die Zusicherungen unten sind bewusst zweiseitig. Eine Wiederholung, die auch
# eine falsche Region oder eine tote Route durchwinkt, waere keine Haertung,
# sondern ein abgeschalteter Test.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CI_YML="$HERE/../ci.yml"
FAILED=0

ok()  { echo "ok   — $1"; }
bad() { echo "FAIL — $1"; FAILED=1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ── Den Schritt aus ci.yml herausschneiden ──────────────────────────────────
awk '
  /^      - name: "Beleg 1\/3:/ { drin=1; next }
  drin && /^        run: \|/    { lesen=1; next }
  lesen && /^      - name:/     { exit }
  lesen                          { sub(/^          /, ""); print }
' "$CI_YML" > "$WORK/schritt.sh"

if [ ! -s "$WORK/schritt.sh" ]; then
    bad "Schritt 'Beleg 1/3' in ci.yml nicht gefunden — Test und Workflow sind auseinandergelaufen"
    exit 1
fi
ok "Schritt 'Beleg 1/3' aus ci.yml gelesen ($(wc -l < "$WORK/schritt.sh") Zeilen)"

# ── Stubs ───────────────────────────────────────────────────────────────────
# `docker compose exec` verhaelt sich nach $SZENARIO und zaehlt seine Aufrufe;
# so laesst sich pruefen, dass ueberhaupt wiederholt wird und nicht nur einmal
# gefragt.
mkdir -p "$WORK/stub"
cat > "$WORK/stub/docker" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "compose" ] && [ "$2" = "exec" ]; then
  n=$(( $(cat "$ZAEHLER" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$ZAEHLER"
  case "$SZENARIO" in
    sofort)         echo "OSM_FILENAME=berlin-latest.osm.pbf"; exit 0 ;;
    erholt)         if [ "$n" -lt 3 ]; then
                      echo "Error response from daemon: container is restarting" >&2; exit 137
                    fi
                    echo "OSM_FILENAME=berlin-latest.osm.pbf"; exit 0 ;;
    dauerhaft_tot)  echo "Error response from daemon: container is restarting" >&2; exit 137 ;;
    falsche_region) echo "OSM_FILENAME=liechtenstein-latest.osm.pbf"; exit 0 ;;
  esac
fi
case "$1 $2" in
  "compose ps")   echo "convoyplan-region-ci-graphhopper-1  Restarting" ;;
  "compose logs") echo "[graphhopper] java.lang.OutOfMemoryError: Java heap space" ;;
  inspect*)       echo "Status=restarting OOMKilled=true ExitCode=137 RestartCount=4" ;;
esac
exit 0
STUB
cat > "$WORK/stub/curl" <<'STUB'
#!/usr/bin/env bash
[ "${ROUTE_OK:-1}" = "0" ] && exit 7
echo '{"paths":[{"distance":2500}]}'
STUB
cat > "$WORK/stub/free"  <<'STUB'
#!/usr/bin/env bash
echo "Mem: total 15990 used 15012 free 210"
STUB
# Ohne diesen Stub wartet der Test die echten Wiederholungspausen ab.
cat > "$WORK/stub/sleep" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x "$WORK"/stub/*

# Fuehrt den Schritt aus und legt Ausgabe, Rueckgabewert und Versuchszahl ab.
lauf() {
    local szenario="$1" route_ok="${2:-1}"
    echo 0 > "$WORK/zaehler"
    AUSGABE="$(PATH="$WORK/stub:$PATH" SZENARIO="$szenario" ROUTE_OK="$route_ok" \
               ZAEHLER="$WORK/zaehler" bash "$WORK/schritt.sh" 2>&1)"
    RC=$?
    VERSUCHE="$(cat "$WORK/zaehler")"
}

# ── 1: Der Normalfall bleibt schnell ────────────────────────────────────────
lauf sofort
[ "$RC" = 0 ] && [ "$VERSUCHE" = 1 ] \
    && ok "ansprechbarer Container: gruen nach einem Versuch" \
    || bad "ansprechbarer Container: rc=$RC, Versuche=$VERSUCHE (erwartet 0/1)"

# ── 2: Der gemeldete Fall ───────────────────────────────────────────────────
# Zwei Fehlversuche, dann antwortet der Container. Genau hier war der Schritt
# vorher rot — und zwar mit 137, ohne je die eigene Fehlerbehandlung zu
# erreichen.
lauf erholt
[ "$RC" = 0 ] && [ "$VERSUCHE" = 3 ] \
    && ok "neu startender Container: wird abgewartet statt den Job zu faellen" \
    || bad "neu startender Container: rc=$RC, Versuche=$VERSUCHE (erwartet 0/3)"

# ── 3: Ein echter Ausfall bleibt rot — und wird erklaert ────────────────────
lauf dauerhaft_tot
[ "$RC" != 0 ] \
    && ok "dauerhaft toter Container: Schritt faellt" \
    || bad "dauerhaft toter Container: Schritt wurde gruen (rc=$RC) — die Wiederholung verdeckt den Ausfall"
[ "$VERSUCHE" -ge 3 ] \
    && ok "dauerhaft toter Container: es wurde mehrfach versucht ($VERSUCHE)" \
    || bad "dauerhaft toter Container: nur $VERSUCHE Versuch(e)"
for muss in "OOMKilled" "RestartCount" "OutOfMemoryError" "::error::"; do
    case "$AUSGABE" in
        *"$muss"*) ok "Diagnose nennt '$muss'" ;;
        *)         bad "Diagnose nennt '$muss' nicht — der naechste Ausfall waere wieder unerklaert" ;;
    esac
done

# ── 4: Die eigentliche Zusicherung ist unveraendert scharf ──────────────────
lauf falsche_region
[ "$RC" != 0 ] \
    && ok "falsche Region: Schritt faellt weiterhin" \
    || bad "falsche Region: Schritt wurde gruen — der Beleg ist wertlos geworden"

lauf sofort 0
[ "$RC" != 0 ] \
    && ok "tote Routenabfrage: Schritt faellt weiterhin" \
    || bad "tote Routenabfrage: Schritt wurde gruen — der Beleg ist wertlos geworden"

if [ "$FAILED" = 0 ]; then
    echo "Alle Zusicherungen erfuellt."
else
    echo "Es sind Zusicherungen fehlgeschlagen."
fi
exit "$FAILED"
