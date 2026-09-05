#!/usr/bin/env bash
# switch-region.sh — führt einen Regionswechsel in fünf Phasen aus.
#
# Das Backend legt die Anforderung als region_request.json im geteilten Volume
# /update_status ab (es fasst Docker nie an). Dieses Skript läuft im Updater —
# dem einzigen Container mit Docker-Socket — und arbeitet sie ab:
#
#   1 Prüfen      Extract erreichbar? Platz da?          (nichts verändert)
#   2 Laden       Extract herunterladen, Prüfsumme       (nichts geschwenkt)
#   3 Importieren Graph in ein Staging-Verzeichnis bauen (Routing läuft weiter)
#   4 Schwenken   Graph tauschen, .region schreiben, GraphHopper neu starten
#   5 Aufräumen   alten Graph und altes Extract löschen
#
# Die Zusage an den Nutzer: Scheitert etwas VOR dem Schwenk, läuft die alte
# Region unberührt weiter. Der alte Graph wird deshalb erst in Phase 5 —
# also nach einem nachweislich gesunden neuen GraphHopper — gelöscht; scheitert
# der Schwenk selbst, holt _rollback_to_old_region() .region und Graph zurück.
# Jeder Eingriff in das Graph-Verzeichnis findet bei GESTOPPTEM GraphHopper
# statt, damit dessen Entrypoint nicht in einen Zwischenstand hineinläuft und
# den Graphen wegen Fingerprint-Mismatch löscht (siehe _stop_graphhopper).
#
# Aufruf: aus der Poll-Schleife des Updaters, wenn region_request.json vorliegt
# und kein region.lock existiert.
#
# Env (alles optional, Defaults = Produktion):
#   STATUS_DIR OSM_DIR GRAPH_DIR REPO_DIR COMPOSE_PROJECT_NAME
#   GRAPHHOPPER_IMAGE REGION_COMPOSE_FILE REGION_IMPORT_MODE
#   REGION_HEALTH_TIMEOUT REGION_IMPORT_TIMEOUT REGION_POLL_SLEEP SKIP_CHECKSUM
#   REGION_MEMINFO REGION_HEAP_RESERVE_MB REGION_HEAP_MIN_MB REGION_STOP_TIMEOUT
set -uo pipefail

STATUS_DIR="${STATUS_DIR:-/update_status}"
OSM_DIR="${OSM_DIR:-/data/osm}"
GRAPH_DIR="${GRAPH_DIR:-/data/graph}"
REPO_DIR="${REPO_DIR:-/workspace}"

REQ="$STATUS_DIR/region_request.json"
LOG="$STATUS_DIR/region.log"
LOCK="$STATUS_DIR/region.lock"
CANCEL="$STATUS_DIR/region.cancel"
STATUS_JSON="$STATUS_DIR/region_status.json"

# Staging und Altbestand liegen INNERHALB des Graph-Volumes: nur so ist der
# Tausch ein billiges Umbenennen im selben Dateisystem. Ein Verzeichnis neben
# dem Mountpunkt (z. B. /data/graph-staging) läge im Container-Dateisystem —
# der Tausch wäre ein stundenlanges Kopieren und `mv /data/graph` würde am
# Mountpunkt ohnehin mit "Device or resource busy" scheitern.
STAGING="$GRAPH_DIR/.staging"
OLD="$GRAPH_DIR/.old"
# Pfad des Staging-Verzeichnisses AUS SICHT des GraphHopper-Containers. Dort
# ist das Volume immer unter /data/graph gemountet, unabhängig davon, wohin
# dieses Skript es sieht (Tests nutzen ein temporäres Verzeichnis).
STAGING_IN_CONTAINER="/data/graph/.staging"

REGION_FILE="$OSM_DIR/.region"
REGION_BACKUP="$OSM_DIR/.region.prev"

COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-convoyplan}"
GRAPHHOPPER_IMAGE="${GRAPHHOPPER_IMAGE:-ghcr.io/retttechsolutions/convoyplan/graphhopper:latest}"

# Weg für den Graph-Bau: "import" (GraphHopper-Unterbefehl, Container endet von
# selbst) oder "server" (Container starten, warten bis der Graph steht, wieder
# beenden). Ob 9.1 den Unterbefehl `import` kennt, ist im Repo nirgends belegt —
# deshalb erkennt _import_graph() ein "Unrecognized command" und fällt selbst
# auf "server" zurück. Wer den Rückfall dauerhaft will: REGION_IMPORT_MODE=server.
REGION_IMPORT_MODE="${REGION_IMPORT_MODE:-import}"

# Wartezeit nach dem Schwenk. Der Graph ist zu diesem Zeitpunkt fertig gebaut,
# GraphHopper muss ihn nur noch laden — Minuten, nicht Stunden. Der Healthcheck
# in docker-compose.yml erlaubt bewusst 360 x 30 s = 3 h (für den Erstimport);
# darauf zu warten hieße, einen echten Fehlstart drei Stunden lang stehen zu
# lassen, bevor der Rollback greift.
REGION_HEALTH_TIMEOUT="${REGION_HEALTH_TIMEOUT:-900}"
# Wartezeit für den Server-Rückfall in Phase 3: hier wird der Graph tatsächlich
# gebaut, das darf für große Regionen Stunden dauern.
REGION_IMPORT_TIMEOUT="${REGION_IMPORT_TIMEOUT:-21600}"
REGION_POLL_SLEEP="${REGION_POLL_SLEEP:-5}"   # Sekunden zwischen zwei Abfragen
REGION_POLL_STEP="${REGION_POLL_STEP:-5}"     # dafür verbuchte Sekunden
# Wartezeit, bis ein per `compose stop` angehaltener Container wirklich als
# gestoppt bestätigt ist (siehe _stop_graphhopper). Ein klemmender Daemon kann
# `stop` mit Erfolgscode quittieren und den Container trotzdem weiterlaufen
# lassen — Sekunden, keine Minuten, denn ein SIGTERM/SIGKILL-Stopp ist schnell.
REGION_STOP_TIMEOUT="${REGION_STOP_TIMEOUT:-30}"

# Heap-Deckelung (Spec §3): Das Backend rechnet den Import-Heap aus Schätzwerten
# und zwischengespeicherten Host-Metriken. Der Updater sieht den Host zum
# Ausführungszeitpunkt und übernimmt den Wert deshalb nicht ungeprüft, sondern
# deckelt ihn auf den real verfügbaren Speicher abzüglich einer Reserve. Ein zu
# großes -Xmx ist die wahrscheinlichste Ursache dafür, dass der Import stirbt
# oder — schlimmer — der neue GraphHopper nach dem Schwenk nicht mehr hochkommt.
REGION_MEMINFO="${REGION_MEMINFO:-/proc/meminfo}"
REGION_HEAP_RESERVE_MB="${REGION_HEAP_RESERVE_MB:-1024}"  # für Kernel, Page-Cache, die übrigen Container
REGION_HEAP_MIN_MB="${REGION_HEAP_MIN_MB:-2048}"          # nie unter diesen Wert deckeln

OWNS_LOCK=0        # 1, sobald dieses Skript das Lock hält
FINISHED=0         # 1 nach erfolgreichem Abschluss
FAILED_REPORTED=0  # 1, sobald fail() den Endstatus geschrieben hat
GH_STOPPED=0       # 1, solange GraphHopper für den Graph-Tausch gestoppt ist
REGION_BACKED_UP=0 # 1, sobald .region gesichert wurde (erst dann ist ein Rücktausch sinnvoll)
IMPORT_CANCELLED=0 # 1, wenn der Import wegen region.cancel abgebrochen wurde

mkdir -p "$STATUS_DIR" 2>/dev/null || true

# ── Kleinkram ───────────────────────────────────────────────────────────────
log() {
    local line="[$(date -u '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$line"
    printf '%s\n' "$line" >> "$LOG" 2>/dev/null || true
    # Das Backend läuft als uid 1001 und liest diese Datei; der Updater als root.
    chmod 0644 "$LOG" 2>/dev/null || true
}

_json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/ }"
    printf '%s' "$s"
}

# Endstatus atomar schreiben: das Panel liest die Datei jederzeit, ein halb
# geschriebenes JSON würde dort als "idle" durchgehen.
phase() {
    local p="$1" msg="$2" tmp
    tmp="$(mktemp "$STATUS_DIR/.region_status.XXXXXX" 2>/dev/null)"
    if [ -n "$tmp" ]; then
        printf '{"phase":"%s","message":"%s","at":"%s"}\n' \
            "$p" "$(_json_escape "$msg")" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$tmp"
        chmod 0644 "$tmp" 2>/dev/null || true
        mv -f "$tmp" "$STATUS_JSON" 2>/dev/null || rm -f "$tmp"
    fi
    log "$msg"
}

# Reihenfolge ist bindend: erst der Endstatus (region_status.json), dann die
# Sperrdateien. read_status() und is_busy() im Backend lesen getrennte Dateien —
# andersherum meldete das Panel "nicht beschäftigt", während es noch die
# vorletzte Phase anzeigt.
_release() { rm -f "$LOCK" "$REQ" "$CANCEL"; }

fail() {
    FAILED_REPORTED=1
    phase "failed" "$1"
    exit 1
}

_on_exit() {
    local rc=$?
    # Notbremse: Bricht das Skript ab, WÄHREND GraphHopper für den Graph-Tausch
    # gestoppt ist (Signal, OOM des Skripts, `set -u`-Verstoß), bliebe das
    # Routing sonst dauerhaft aus — `compose stop` überlebt auch einen
    # Daemon-Neustart, `restart: unless-stopped` holt den Container nicht
    # zurück. Deshalb hier der letzte Versuch, ihn wieder hochzufahren.
    if [ "$GH_STOPPED" = 1 ]; then
        # Vor dem Hochfahren prüfen, ob $GRAPH_DIR überhaupt ein vollständiger
        # Graph ist. Ist der Rollback vorher selbst teilweise gescheitert (z. B.
        # ein `mv` aus .old, siehe _restore_old_graph), kann das Verzeichnis
        # leer oder unvollständig sein — der Entrypoint sähe dort einen
        # Fingerprint-Mismatch, würfe alles per `rm -rf` weg und baute über
        # Stunden neu, ohne dass es jemand mitbekommt. .graph_fingerprint
        # schreibt der Entrypoint als letzten Schritt eines fertigen Graphen;
        # seine Existenz ist der billigste verfügbare Beleg für Vollständigkeit.
        if [ -s "$GRAPH_DIR/.graph_fingerprint" ]; then
            log "GraphHopper ist noch gestoppt — starte ihn wieder."
            _compose up -d graphhopper >> "$LOG" 2>&1 || \
                log "FEHLER: GraphHopper konnte nicht wieder gestartet werden — manueller Eingriff nötig."
            GH_STOPPED=0
        else
            # Ein stehender Container, den ein Mensch bewusst wieder startet,
            # ist besser als ein unangekündigter Mehrstunden-Neuaufbau.
            log "FEHLER: Graph-Verzeichnis (${GRAPH_DIR}) ist unvollständig (kein .graph_fingerprint) — GraphHopper wird NICHT automatisch gestartet. Alter Bestand liegt vermutlich noch in ${OLD} — bitte manuell prüfen und erst dann den Container starten."
            phase "failed" "Notbremse: Graph-Verzeichnis unvollständig, GraphHopper bleibt bewusst gestoppt — manueller Eingriff nötig (Bestand ggf. in ${OLD})."
            FAILED_REPORTED=1
        fi
    fi
    if [ "$OWNS_LOCK" = 1 ]; then
        if [ "$rc" -ne 0 ] && [ "$FINISHED" != 1 ] && [ "$FAILED_REPORTED" != 1 ]; then
            # Abbruch von außen (Signal, `set -u`-Verstoß, OOM des Skripts):
            # trotzdem einen Endstatus hinterlassen, sonst zeigt das Panel für
            # immer die letzte erreichte Phase.
            phase "failed" "Regionswechsel unerwartet beendet (Code $rc)."
        fi
        # Bleibt eine dieser Dateien liegen, blockiert sie JEDEN weiteren
        # Versuch (region_request.json wird vom Backend exklusiv angelegt).
        _release
    fi
    exit "$rc"
}
trap _on_exit EXIT
trap 'exit 143' TERM INT

cancelled() { [ -f "$CANCEL" ]; }
abort_if_cancelled() {
    if cancelled; then
        fail "Abgebrochen — die bisherige Region läuft unverändert weiter."
    fi
}

# JSON-Werte ohne python3/jq lesen: das Updater-Image ist docker:cli (busybox +
# bash + git + curl), ein Interpreter ist dort nicht vorhanden und soll auch
# nicht dazukommen. Die Datei schreibt json.dumps() aus dem Backend — eine
# Zeile, flache Struktur, ausschließlich String-Werte.
_json_str() {
    local key="$1" file="$2" raw
    raw="$(sed -nE 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)".*/\1/p' "$file" 2>/dev/null | head -1)"
    raw="${raw//\\\"/\"}"
    raw="${raw//\\\//\/}"
    raw="${raw//\\\\/\\}"
    printf '%s' "$raw"
}

# ── Compose-Aufrufe ─────────────────────────────────────────────────────────
# Niemals blank `docker compose` aufrufen: ohne -p und -f trifft der Aufruf im
# Container den falschen oder gar keinen Stack (dieselbe Konstruktion wie in
# update.sh:24; update-images.sh nutzt stattdessen /stack/docker-compose.yml).
COMPOSE_FILES=(-p "$COMPOSE_PROJECT")
_resolve_compose_files() {
    if [ -n "${REGION_COMPOSE_FILE:-}" ] && [ -s "${REGION_COMPOSE_FILE}" ]; then
        COMPOSE_FILES+=(-f "$REGION_COMPOSE_FILE")
    elif [ -f "${REPO_DIR}/docker-compose.yml" ]; then
        COMPOSE_FILES+=(-f "${REPO_DIR}/docker-compose.yml")
        [ -f "${REPO_DIR}/docker-compose.override.yml" ] && \
            COMPOSE_FILES+=(-f "${REPO_DIR}/docker-compose.override.yml")
    elif [ -s /stack/docker-compose.yml ]; then
        COMPOSE_FILES+=(-f /stack/docker-compose.yml)
    else
        return 1
    fi
    return 0
}

_compose() { docker compose "${COMPOSE_FILES[@]}" "$@"; }

_gh_cid() {
    docker ps -aq \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=graphhopper" 2>/dev/null | head -1
}

# Zustand über den Container erfragen, nicht per HTTP: ob der Updater
# GraphHopper per DNS erreicht, ist unverifiziert — der Healthcheck des
# Containers ist ohnehin die verlässlichere Quelle (docker-compose.yml).
# $3 = 1: zwischen zwei Abfragen auch region.cancel prüfen und dann mit 2
# abbrechen (Spec §3: „ein laufender Import bis zum Ende ODER Abbruch des
# Wegwerf-Containers"). Nur für den Import-Wartelauf gesetzt — nach dem Schwenk
# (Phase 4) ist kein Abbruch mehr vorgesehen.
_wait_container_healthy() {
    local cid="$1" timeout="$2" watch_cancel="${3:-0}" waited=0 health status restarts
    health=""; status=""
    while [ "$waited" -lt "$timeout" ]; do
        if [ "$watch_cancel" = 1 ] && cancelled; then
            log "Abbruch angefordert — der Import-Container wird gestoppt."
            return 2
        fi
        health="$(docker inspect "$cid" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || echo '')"
        status="$(docker inspect "$cid" --format '{{.State.Status}}' 2>/dev/null || echo '')"
        restarts="$(docker inspect "$cid" --format '{{.RestartCount}}' 2>/dev/null || echo 0)"
        case "$health" in
            healthy) return 0 ;;
            none)    [ "$status" = "running" ] && return 0 ;;
        esac
        if [ "${restarts:-0}" -ge 3 ]; then
            log "GraphHopper im Crash-Loop (RestartCount=${restarts}, Health=${health})."
            return 1
        fi
        sleep "$REGION_POLL_SLEEP"
        waited=$(( waited + REGION_POLL_STEP ))
    done
    log "GraphHopper nicht gesund innerhalb ${timeout}s (Health=${health:-unbekannt}, Status=${status:-unbekannt})."
    return 1
}

_wait_gh_healthy() {
    local cid
    cid="$(_gh_cid)"
    if [ -z "$cid" ]; then
        log "Kein GraphHopper-Container im Projekt ${COMPOSE_PROJECT} gefunden."
        return 1
    fi
    _wait_container_healthy "$cid" "$1"
}

# ── GraphHopper anhalten / hochfahren ───────────────────────────────────────
# Jeder Eingriff in $GRAPH_DIR passiert bei GESTOPPTEM Container. Grund: läuft
# GraphHopper (mit `restart: unless-stopped`) währenddessen weiter oder im
# Neustart-Takt, kann sein Entrypoint mitten in den Tausch hineinfallen. Er
# vergleicht dort OSM_FILENAME aus .region mit .graph_fingerprint im Graph-
# Verzeichnis und löscht bei Abweichung `rm -rf "$GRAPH_DIR"/*`
# (graphhopper/entrypoint.sh:117) — also genau die Dateien, die wir gerade
# hin- oder zurückschieben. Zwischen Tausch und .region-Schreiben (und im
# Rollback zwischen .region und Graph) liegt zwangsläufig ein Fenster mit
# unpassender Kombination; der gestoppte Container ist das, was dieses Fenster
# ungefährlich macht.
_stop_graphhopper() {
    [ "$GH_STOPPED" = 1 ] && return 0
    log "Halte GraphHopper an, bevor am Graph-Verzeichnis gearbeitet wird."
    # Vor dem `stop` markieren: schlägt der Aufruf teilweise fehl (Container
    # schon weg, Daemon zickt), soll die Notbremse in _on_exit trotzdem
    # greifen — ein überflüssiges `up -d` ist harmlos, ein ausgelassenes nicht.
    GH_STOPPED=1
    if ! _compose stop graphhopper >> "$LOG" 2>&1; then
        log "WARNUNG: 'compose stop graphhopper' meldete einen Fehler — prüfe trotzdem den tatsächlichen Zustand."
    fi
    # Weder ein Erfolgs- noch ein Fehlercode von `compose stop` ist verlässlich:
    # ein klemmender Docker-Daemon kann Erfolg melden, während der Container
    # weiterläuft. Deshalb hier verifizieren statt dem Rückgabewert zu
    # vertrauen — erst ein NACHWEISLICH gestoppter Container macht das Fenster
    # ungefährlich, das oben an dieser Funktionsgruppe beschrieben ist.
    local cid running waited=0
    cid="$(_gh_cid)"
    if [ -z "$cid" ]; then
        return 0   # kein Container im Projekt gefunden — es läuft nichts, das noch stünde
    fi
    while [ "$waited" -lt "$REGION_STOP_TIMEOUT" ]; do
        running="$(docker inspect "$cid" --format '{{.State.Running}}' 2>/dev/null)"
        [ "$running" = "false" ] && return 0
        sleep "$REGION_POLL_SLEEP"
        waited=$(( waited + REGION_POLL_STEP ))
    done
    log "FEHLER: GraphHopper läuft nach 'compose stop' immer noch (Container ${cid}, ${REGION_STOP_TIMEOUT}s abgewartet) — kein sicheres Fenster für den Graph-Zugriff."
    return 1
}

# ── Volumes ─────────────────────────────────────────────────────────────────
# Für `docker run` brauchen wir die NAMEN der Volumes: Pfade wie /data/osm sind
# containerinterne Pfade, der Docker-Daemon würde sie als Host-Pfade deuten und
# ein leeres Verzeichnis anlegen.
_resolve_volumes() {
    local cid=""
    cid="$(_gh_cid)"
    OSM_VOLUME=""
    GRAPH_VOLUME=""
    if [ -n "$cid" ]; then
        OSM_VOLUME="$(docker inspect "$cid" --format '{{range .Mounts}}{{if eq .Destination "/data/osm"}}{{.Name}}{{end}}{{end}}' 2>/dev/null | tr -d '[:space:]')"
        GRAPH_VOLUME="$(docker inspect "$cid" --format '{{range .Mounts}}{{if eq .Destination "/data/graph"}}{{.Name}}{{end}}{{end}}' 2>/dev/null | tr -d '[:space:]')"
    fi
    [ -n "$OSM_VOLUME" ]   || OSM_VOLUME="${COMPOSE_PROJECT}_osm_data"
    [ -n "$GRAPH_VOLUME" ] || GRAPH_VOLUME="${COMPOSE_PROJECT}_gh_graph"
}

# ── Heap-Deckelung ──────────────────────────────────────────────────────────
# "-Xmx3g" → 3072 (MB). Leerer Rückgabewert plus Rückgabecode 1, wenn der Wert
# nicht als Zahl mit bekannter Einheit lesbar ist — dann wird lieber gar nicht
# gedeckelt als falsch.
_xmx_mb() {
    local v="${1#-Xm?}" num unit=""
    v="$(printf '%s' "$v" | tr 'A-Z' 'a-z')"
    case "$v" in
        *k|*m|*g) unit="${v: -1}"; num="${v%?}" ;;
        *)        num="$v" ;;
    esac
    case "$num" in ''|*[!0-9]*) return 1 ;; esac
    case "$unit" in
        k) printf '%s' $(( num / 1024 )) ;;
        m) printf '%s' "$num" ;;
        g) printf '%s' $(( num * 1024 )) ;;
        *) printf '%s' $(( num / 1024 / 1024 )) ;;   # Bytes ohne Einheit
    esac
    return 0
}

# Verfügbarer Host-Speicher in MB. MemAvailable (nicht MemFree) ist der Wert,
# den der Kernel selbst als „ohne Swapping vergebbar" ausweist — Page-Cache,
# der zurückgewonnen werden kann, ist darin schon enthalten.
_mem_available_mb() {
    local kb
    kb="$(awk '/^MemAvailable:/{print $2; exit}' "$REGION_MEMINFO" 2>/dev/null)"
    case "${kb:-}" in ''|*[!0-9]*) return 1 ;; esac
    printf '%s' $(( kb / 1024 ))
    return 0
}

# Gibt $1 (JAVA_OPTS) mit gedeckeltem -Xmx/-Xms aus. $2 ist nur die Bezeichnung
# für das Log. Der Zeitpunkt des Aufrufs ist bewusst Teil der Semantik: für den
# Import wird gemessen, während der alte GraphHopper noch läuft; für den
# produktiven Heap in .region erst, nachdem er gestoppt wurde — beides ist
# genau der Zustand, in dem der jeweilige Heap tatsächlich gebraucht wird.
_capped_java_opts() {
    local opts="$1" purpose="$2" tok mb avail_mb cap_mb xmx_mb="" xmx_capped=0 out=""
    if ! avail_mb="$(_mem_available_mb)"; then
        log "WARNUNG: ${REGION_MEMINFO} nicht lesbar — Heap wird nicht gedeckelt (${purpose})." >&2
        printf '%s' "$opts"
        return 0
    fi
    cap_mb=$(( avail_mb - REGION_HEAP_RESERVE_MB ))
    [ "$cap_mb" -lt "$REGION_HEAP_MIN_MB" ] && cap_mb="$REGION_HEAP_MIN_MB"

    # Durchgang 1: den effektiven -Xmx bestimmen, damit -Xms in Durchgang 2
    # daran (und nicht nur an der Obergrenze) gemessen werden kann — ein -Xms
    # über -Xmx lässt die JVM gar nicht erst starten.
    for tok in $opts; do
        case "$tok" in
            -Xmx*)
                if mb="$(_xmx_mb "$tok")"; then
                    if [ "$mb" -gt "$cap_mb" ]; then
                        log "Heap gedeckelt (${purpose}): ${tok} → -Xmx${cap_mb}m — ${avail_mb} MB verfügbar abzüglich ${REGION_HEAP_RESERVE_MB} MB Reserve." >&2
                        xmx_mb="$cap_mb"
                        xmx_capped=1
                    else
                        xmx_mb="$mb"
                    fi
                else
                    log "WARNUNG: ${tok} nicht lesbar — bleibt ungedeckelt (${purpose})." >&2
                fi
                ;;
        esac
    done

    for tok in $opts; do
        case "$tok" in
            -Xmx*)
                # Nur bei tatsächlicher Deckelung neu schreiben — sonst bliebe
                # von "-Xmx3g" ein sachlich gleiches, aber grundlos anderes
                # "-Xmx3072m" in .region stehen.
                [ "$xmx_capped" = 1 ] && tok="-Xmx${xmx_mb}m"
                ;;
            -Xms*)
                if [ -n "$xmx_mb" ] && mb="$(_xmx_mb "$tok")" && [ "$mb" -gt "$xmx_mb" ]; then
                    log "Start-Heap gedeckelt (${purpose}): ${tok} → -Xms${xmx_mb}m (darf -Xmx nicht überschreiten)." >&2
                    tok="-Xms${xmx_mb}m"
                fi
                ;;
        esac
        out="${out:+$out }$tok"
    done
    printf '%s' "$out"
    return 0
}

# ── Phase 3: Graph bauen ────────────────────────────────────────────────────
# REGION_SOURCE_SCRIPT=/dev/null ist der wichtigste Schalter hier: /data/osm/.region
# enthält zu diesem Zeitpunkt noch die ALTE Region und hat im Container Vorrang
# vor der Env (graphhopper/region-source.sh). Ohne das Abschalten baute der
# Import-Container den Graphen der alten Region neu.
_import_container_args() {
    IMPORT_ARGS=(
        -v "${OSM_VOLUME}:/data/osm"
        -v "${GRAPH_VOLUME}:/data/graph"
        -e "OSM_FILENAME=${FILENAME}"
        -e "OSM_DOWNLOAD_URL=${URL}"
        -e "JAVA_OPTS=${IMPORT_JAVA_OPTS}"
        -e "GRAPH_DIR=${STAGING_IN_CONTAINER}"
        -e "REGION_SOURCE_SCRIPT=/dev/null"
    )
}

_import_graph_via_server() {
    local cid start_rc rc=1 wrc name="convoyplan-region-import-$$"
    _import_container_args
    log "Baue den Graphen über einen temporären GraphHopper-Server (Rückfallweg)."
    docker rm -f "$name" >/dev/null 2>&1
    # stderr getrennt halten und den Exit-Code auswerten: `2>&1 | tail -1`
    # lieferte bei einem Fehlstart die FEHLERMELDUNG statt einer Container-ID.
    # Die ist nicht leer, kam also am Leer-Guard vorbei — jedes folgende
    # `docker inspect` lieferte dann leere Werte, RestartCount fiel auf 0
    # zurück und die Warteschleife drehte bis REGION_IMPORT_TIMEOUT: sechs
    # Stunden mit gehaltenem Lock für einen Fehler, der sofort feststand.
    cid="$(docker run -d --name "$name" \
        --health-cmd "curl -f http://localhost:8989/health" \
        --health-interval 15s --health-timeout 10s --health-retries 3 \
        --health-start-period 60s \
        "${IMPORT_ARGS[@]}" -e "GH_COMMAND=server" \
        "$GRAPHHOPPER_IMAGE" 2>>"$LOG")"
    start_rc=$?
    if [ "$start_rc" -ne 0 ] || [ -z "$cid" ]; then
        log "Import-Container ließ sich nicht starten (docker run beendet mit ${start_rc})."
        docker rm -f "$name" >/dev/null 2>&1
        return 1
    fi
    _wait_container_healthy "$cid" "$REGION_IMPORT_TIMEOUT" 1
    wrc=$?
    [ "$wrc" = 0 ] && rc=0
    [ "$wrc" = 2 ] && IMPORT_CANCELLED=1
    docker logs --tail 50 "$cid" >> "$LOG" 2>&1
    docker stop -t 30 "$cid" >/dev/null 2>&1
    docker rm -f "$cid" >/dev/null 2>&1
    return "$rc"
}

# Wartet auf den im Hintergrund laufenden Import und prüft nebenher
# region.cancel. Rückgabe: 0 = Prozess regulär beendet, 1 = abgebrochen,
# 2 = Zeitlimit. In den Fällen 1 und 2 wird der Container hart entfernt —
# `docker run` beendet sich dadurch von selbst.
_await_import_process() {
    local pid="$1" name="$2" waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if cancelled; then
            log "Abbruch angefordert — der Import-Container wird gestoppt."
            docker rm -f "$name" >/dev/null 2>&1
            wait "$pid" 2>/dev/null
            return 1
        fi
        if [ "$waited" -ge "$REGION_IMPORT_TIMEOUT" ]; then
            log "Import überschreitet ${REGION_IMPORT_TIMEOUT}s — Container wird gestoppt."
            docker rm -f "$name" >/dev/null 2>&1
            wait "$pid" 2>/dev/null
            return 2
        fi
        sleep "$REGION_POLL_SLEEP"
        waited=$(( waited + REGION_POLL_STEP ))
    done
    wait "$pid" 2>/dev/null
    return 0
}

_import_graph() {
    local out rcf pid wrc rc name="convoyplan-region-import-$$"
    if [ "$REGION_IMPORT_MODE" = "server" ]; then
        _import_graph_via_server
        return $?
    fi
    _import_container_args
    out="$STATUS_DIR/.region-import-out.$$"
    rcf="$STATUS_DIR/.region-import-rc.$$"
    docker rm -f "$name" >/dev/null 2>&1
    # Ausgabe live nach region.log (das Panel streamt sie über
    # GET /api/admin/region/log — ein Import kann Stunden dauern) UND in eine
    # Datei, um danach die Ursache eines Fehlschlags erkennen zu koennen.
    #
    # Der Aufruf läuft im Hintergrund, damit die Warteschleife nebenher
    # region.cancel prüfen kann. Zuvor stand `abort_if_cancelled` nur an den
    # Phasengrenzen: ein Abbruch in Phase 3 wirkte erst, wenn der Import von
    # selbst fertig war — bei großen Regionen Stunden später. Der Exit-Code
    # von `docker` (nicht der von `tee`) wandert über $rcf aus der Subshell
    # heraus; `wait` auf eine Hintergrund-Pipeline gibt ihn nicht verlässlich
    # zurück.
    ( docker run --rm --name "$name" "${IMPORT_ARGS[@]}" -e "GH_COMMAND=import" \
        "$GRAPHHOPPER_IMAGE" 2>&1 | tee -a "$LOG" > "$out"
      printf '%s' "${PIPESTATUS[0]}" > "$rcf" ) &
    pid=$!
    _await_import_process "$pid" "$name"
    wrc=$?
    if [ "$wrc" -ne 0 ]; then
        [ "$wrc" = 1 ] && IMPORT_CANCELLED=1
        rm -f "$out" "$rcf"
        return 1
    fi
    rc="$(cat "$rcf" 2>/dev/null)"
    case "${rc:-}" in ''|*[!0-9]*) rc=1 ;; esac
    rm -f "$rcf"
    if [ "$rc" -ne 0 ] && grep -qiE 'unrecognized command|invalid choice|unknown command' "$out" 2>/dev/null; then
        # Der Unterbefehl `import` existiert in dieser GraphHopper-Version nicht.
        log "GraphHopper kennt den Unterbefehl 'import' nicht — Rückfall auf den Server-Weg."
        rm -f "$out"
        _import_graph_via_server
        return $?
    fi
    rm -f "$out"
    return "$rc"
}

# ── Phase 4: Tausch und Rücktausch ──────────────────────────────────────────
# Beides sind Umbenennungen innerhalb des Graph-Volumes (gleiches Dateisystem),
# also praktisch verzögerungsfrei. Beide Funktionen setzen voraus, dass
# GraphHopper gestoppt ist (_stop_graphhopper) — nicht wegen der offenen
# Dateideskriptoren (die überlebt ein Umbenennen), sondern weil sein Entrypoint
# beim Neustart einen Zwischenstand aus neuer .region und altem Graph als
# Fingerprint-Mismatch deutet und das Verzeichnis leerräumt.
_swap_in_new_graph() {
    local entry base rc=0
    rm -rf "$OLD" || return 1
    mkdir -p "$OLD" || return 1
    shopt -s dotglob nullglob
    for entry in "$GRAPH_DIR"/*; do
        base="${entry##*/}"
        case "$base" in .staging|.old) continue ;; esac
        mv -f "$entry" "$OLD/" || { rc=1; break; }
    done
    if [ "$rc" = 0 ]; then
        for entry in "$STAGING"/*; do
            mv -f "$entry" "$GRAPH_DIR/" || { rc=1; break; }
        done
    fi
    shopt -u dotglob nullglob
    [ "$rc" = 0 ] && { rmdir "$STAGING" 2>/dev/null || rm -rf "$STAGING"; }
    return "$rc"
}

# Rückgabewert ist bindend: die Funktion lieferte früher immer 0 und prüfte
# keinen einzigen `mv` — ein halb zurückgeschobener Graph sah damit aus wie ein
# gelungener Rollback. Scheitert etwas, bleibt $OLD absichtlich stehen, damit
# der Bestand für einen manuellen Eingriff erhalten bleibt.
_restore_old_graph() {
    local entry base rc=0
    [ -d "$OLD" ] || return 0
    shopt -s dotglob nullglob
    for entry in "$GRAPH_DIR"/*; do
        base="${entry##*/}"
        case "$base" in .old) continue ;; esac
        rm -rf "$entry" || { rc=1; log "FEHLER: $entry ließ sich nicht entfernen."; }
    done
    for entry in "$OLD"/*; do
        mv -f "$entry" "$GRAPH_DIR/" || { rc=1; log "FEHLER: $entry ließ sich nicht zurückschieben."; }
    done
    shopt -u dotglob nullglob
    if [ "$rc" = 0 ]; then
        rmdir "$OLD" 2>/dev/null || rm -rf "$OLD"
    else
        log "Der alte Graph ist nur unvollständig zurückgeschoben — ${OLD} bleibt für den manuellen Eingriff erhalten."
    fi
    return "$rc"
}

# .region atomar schreiben: Temporärdatei im selben Verzeichnis, dann mv. Die
# Alles-oder-nichts-Semantik in graphhopper/region-source.sh fängt eine formal
# kaputte Datei ab — eine Datei mit allen drei Schlüsseln und abgeschnittenem
# letztem Wert käme aber durch.
# Sicherung getrennt vom Schreiben: der Rollback muss auch dann greifen, wenn
# der Schwenk VOR _write_region_file scheitert (Graph-Tausch fehlgeschlagen).
# Solange REGION_BACKED_UP 0 ist, steht in .region noch die alte Region und
# _restore_region_file darf sie auf keinen Fall löschen.
_backup_region_file() {
    if [ -f "$REGION_FILE" ]; then
        cp "$REGION_FILE" "$REGION_BACKUP" || return 1
    else
        # Kein .region vorhanden (Bestandsinstallation vor dem ersten Wechsel):
        # der Rollback muss die Datei dann wieder entfernen, nicht zurückspielen.
        rm -f "$REGION_BACKUP"
    fi
    REGION_BACKED_UP=1
    return 0
}

_write_region_file() {
    local tmp="$OSM_DIR/.region.tmp.$$"
    printf 'OSM_DOWNLOAD_URL=%s\nOSM_FILENAME=%s\nJAVA_OPTS=%s\n' \
        "$URL" "$FILENAME" "$JAVA_OPTS" > "$tmp" || { rm -f "$tmp"; return 1; }
    # Vierter Schluessel NUR bei einer zusammengesetzten Region. Ohne ihn waere
    # der gesamte Erstdownload-Schutz in entrypoint.sh toter Code: Auf einem
    # leeren Volume laedt der Entrypoint sonst nur den ERSTEN Bestandteil und
    # routet still mit halber Karte. Fehlt der Schluessel, verhaelt sich alles
    # bitgleich zu einer Einzelregion — das ist der Regressionsschutz.
    if [ -n "$SOURCES" ]; then
        printf 'OSM_SOURCES=%s\n' "$SOURCES" >> "$tmp" || { rm -f "$tmp"; return 1; }
    fi
    chmod 0644 "$tmp" 2>/dev/null || true
    mv -f "$tmp" "$REGION_FILE" || { rm -f "$tmp"; return 1; }
    return 0
}

_restore_region_file() {
    local rc=0
    # Ohne Sicherung gibt es nichts zurückzustellen — .region enthält dann noch
    # unverändert die alte Region.
    [ "$REGION_BACKED_UP" = 1 ] || return 0
    if [ -f "$REGION_BACKUP" ]; then
        mv -f "$REGION_BACKUP" "$REGION_FILE" || { rc=1; log "FEHLER: .region ließ sich nicht zurückstellen."; }
    else
        rm -f "$REGION_FILE" || rc=1
    fi
    [ "$rc" = 0 ] && REGION_BACKED_UP=0
    return "$rc"
}

# Rollback nach einem gescheiterten Schwenk. Die Reihenfolge ist bindend:
# ZUERST .region, DANN der Graph. Andersherum lag im Fenster zwischen beiden
# Schritten — `rm -rf` über den neuen Graphen plus `mv` über Gigabytes — die
# NEUE .region neben dem ALTEN .graph_fingerprint; ein Entrypoint-Lauf, der da
# hineinfiel, sah einen Fingerprint-Mismatch und löschte per
# `rm -rf "$GRAPH_DIR"/*` genau die Dateien, die gerade zurückgeschoben wurden
# (graphhopper/entrypoint.sh:117). Zusätzlich ist GraphHopper während des
# gesamten Rollbacks gestoppt (_stop_graphhopper) — das schließt das Fenster
# wirklich, die Reihenfolge ist der Gürtel dazu.
_rollback_to_old_region() {
    local rc=0
    if ! _stop_graphhopper; then
        # Andere Lage als vor Phase 4: der Tausch liegt schon hinter uns (neuer
        # Graph aktiv oder halb getauscht, alter Bestand in $OLD) und der
        # Container, der sich nicht anhalten lässt, ist hier der NEUE
        # (vermutlich kranke). Trotzdem NICHT versuchen, .region/Graph gegen
        # einen nachweislich noch laufenden Container zu tauschen — das wäre
        # exakt das Fenster, das den Critical ausgemacht hat (Entrypoint sieht
        # Fingerprint-Mismatch, räumt $GRAPH_DIR per `rm -rf` leer). Deshalb
        # hier abbrechen: $OLD bleibt unangetastet für den manuellen Eingriff,
        # der (kranke) neue Graph bleibt stehen und wird nicht zusätzlich
        # beschädigt — der Aufrufer meldet ohnehin "manueller Eingriff nötig".
        log "FEHLER: GraphHopper ließ sich vor dem Rücktausch nicht anhalten — Rücktausch abgebrochen, Bestand in ${OLD} bleibt für den manuellen Eingriff erhalten."
        return 1
    fi
    _restore_region_file || rc=1
    _restore_old_graph   || rc=1
    rm -rf "$STAGING"
    return "$rc"
}

# ════════════════════════════════════════════════════════════════════════════
[ -f "$REQ" ] || exit 0
touch "$LOCK" 2>/dev/null
chmod 0644 "$LOCK" 2>/dev/null || true
OWNS_LOCK=1

URL="$(_json_str url "$REQ")"
FILENAME="$(_json_str filename "$REQ")"
JAVA_OPTS="$(_json_str java_opts "$REQ")"
REQUESTED_BY="$(_json_str requested_by "$REQ")"
# Leer bei einer Einzelregion; sonst die sortierte, |-getrennte Liste der
# Bestandteile, die zu EINER Karte verschmolzen werden.
SOURCES="$(_json_str sources "$REQ")"
# Phasenzahl haengt davon ab, ob zusammengefuehrt wird — sonst saehe der
# Operator bei einer Kombination zweimal "Phase 3".
if [ -n "$SOURCES" ]; then
    _PH_IMPORT="4/6"; _PH_SWITCH="5/6"; _PH_CLEAN="6/6"
else
    _PH_IMPORT="3/5"; _PH_SWITCH="4/5"; _PH_CLEAN="5/5"
fi

log "Regionswechsel angefordert von ${REQUESTED_BY:-unbekannt}: ${URL:-<leer>}"

# Allowlist erneut prüfen — dem Backend wird nicht vertraut: dieses Skript hat
# den Docker-Socket, das Backend nicht.
[ -n "$URL" ] || fail "Anforderung unlesbar: keine URL gefunden."
[ -n "$FILENAME" ] || fail "Anforderung unlesbar: kein Dateiname gefunden."
if [[ ! "$URL" =~ ^[A-Za-z0-9:/._~%-]+$ ]]; then
    fail "URL enthält unerlaubte Zeichen."
fi
case "$URL" in
    https://download.geofabrik.de/*-latest.osm.pbf) ;;
    *) fail "URL nicht zugelassen: $URL" ;;
esac
# Zwei zulaessige Formen: der Geofabrik-Originalname bei einer Einzelregion,
# und merged-<8 Hex>.osm.pbf bei einer zusammengesetzten. Der Hash kommt aus
# der sortierten Bestandteilsliste (backend/app/services/region_compose.py);
# an ihm erkennt entrypoint.sh spaeter einen Wechsel der Zusammensetzung.
if [ -n "$SOURCES" ]; then
    if [[ ! "$FILENAME" =~ ^merged-[0-9a-f]{8}\.osm\.pbf$ ]]; then
        fail "Dateiname einer zusammengesetzten Region nicht zugelassen: $FILENAME"
    fi
    # Die Bestandteile selbst pruefen — die abgeleiteten URLs entstehen erst in
    # Phase 2 aus genau diesen Pfaden, ein `case` auf die fertige URL waere
    # unerreichbarer toter Code.
    _old_ifs="$IFS"; IFS='|'
    for _s in $SOURCES; do
        IFS="$_old_ifs"
        if [[ ! "$_s" =~ ^[a-z0-9][a-z0-9./-]*$ ]] || [[ "$_s" == *..* ]]; then
            fail "Bestandteil nicht zugelassen: $_s"
        fi
        IFS='|'
    done
    IFS="$_old_ifs"
else
    if [[ ! "$FILENAME" =~ ^[A-Za-z0-9._-]+-latest\.osm\.pbf$ ]]; then
        fail "Dateiname nicht zugelassen: $FILENAME"
    fi
    if [ "${URL##*/}" != "$FILENAME" ]; then
        fail "Dateiname passt nicht zur URL: $FILENAME"
    fi
fi
# JAVA_OPTS landet als Zeile in .region — ein Zeilenumbruch (auch als
# JSON-Escape \n) könnte dort einen weiteren Schlüssel einschmuggeln.
if [[ ! "$JAVA_OPTS" =~ ^[A-Za-z0-9\ :=+.,%_/-]*$ ]]; then
    fail "JAVA_OPTS enthält unerlaubte Zeichen."
fi

if ! _resolve_compose_files; then
    fail "Compose-Datei nicht gefunden — Regionswechsel nicht möglich."
fi

mkdir -p "$OSM_DIR" "$GRAPH_DIR" 2>/dev/null || true
abort_if_cancelled

# Guard VOR Phase 1: ein befüllter .old-Ordner ist von _restore_old_graph
# bewusst stehengelassen worden, weil ein früherer Rollback selbst gescheitert
# ist ("für den manuellen Eingriff", siehe dort). _swap_in_new_graph löscht
# .old bedingungslos zu Beginn von Phase 4 — ohne diesen Guard ginge genau
# dieser aufbewahrte Altbestand beim nächsten Wechselversuch ersatzlos
# verloren, bevor ein Mensch ihn je gesehen hat.
if [ -d "$OLD" ] && [ -n "$(ls -A "$OLD" 2>/dev/null)" ]; then
    fail "Ein früherer Rollback ist unvollständig; Bestand liegt in ${OLD} — bitte prüfen und entfernen, bevor ein neuer Regionswechsel gestartet wird."
fi

# ── Phase 1: Prüfen ─────────────────────────────────────────────────────────
if [ -n "$SOURCES" ]; then
    phase "checking" "Phase 1/6: Prüfe Verfügbarkeit und Platz…"
else
    phase "checking" "Phase 1/5: Prüfe Verfügbarkeit und Platz…"
fi

_head_size() {
    curl -sSIL --max-time 60 "$1" 2>/dev/null \
        | awk 'tolower($1)=="content-length:"{v=$2} END{printf "%d", v+0}'
}

if [ -n "$SOURCES" ]; then
    # Die Groesse ALLER Bestandteile, nicht nur des ersten. Ohne das prueft der
    # Updater bei DE+PL+CZ gegen ~10 GB, waehrend der Spitzenbedarf bei ~32 GB
    # liegt — der Wechsel liefe an der Pruefung vorbei und straebe Stunden
    # spaeter mitten im Merge oder Import an ENOSPC.
    SIZE=0
    _old_ifs="$IFS"; IFS='|'
    for _s in $SOURCES; do
        IFS="$_old_ifs"
        _sz="$(_head_size "https://download.geofabrik.de/${_s}-latest.osm.pbf")"
        [ "${_sz:-0}" -gt 0 ] 2>/dev/null || fail "Extract nicht abrufbar: $_s"
        SIZE=$(( SIZE + _sz ))
        IFS='|'
    done
    IFS="$_old_ifs"
    # Waehrend eines zusammengesetzten Wechsels liegen gleichzeitig auf der
    # Platte: die N Quelldateien, die daraus verschmolzene Datei, der Staging-
    # Graph (~1,5x) und der alte Bestand. Dieselbe Rechnung wie im Backend
    # (region_estimate.estimate_disk_during_switch), damit Panel und Updater
    # nicht verschiedene Zahlen nennen.
    NEEDED=$(( SIZE * 9 / 2 ))
else
    SIZE="$(_head_size "$URL")"
    [ "${SIZE:-0}" -gt 0 ] 2>/dev/null || fail "Extract nicht abrufbar: $URL"
    # Grobe Faustregel: neues Extract + neuer Graph, rund das 2,5-fache der
    # Extract-Größe. Beide Volumes liegen in der Regel auf demselben Dateisystem;
    # liegen sie es nicht, wird hier zu Recht jedes einzeln geprüft.
    NEEDED=$(( SIZE * 5 / 2 ))
fi
for dir in "$OSM_DIR" "$GRAPH_DIR"; do
    free_kb="$(df -Pk "$dir" 2>/dev/null | awk 'NR==2{print $4}')"
    free=$(( ${free_kb:-0} * 1024 ))
    if [ "$free" -le "$NEEDED" ]; then
        fail "Zu wenig Plattenplatz unter $dir: $NEEDED Bytes benötigt, $free frei."
    fi
done
abort_if_cancelled

# ── Phase 2: Laden ──────────────────────────────────────────────────────────
# Laedt EINE Datei mit Pruefsumme. Bei einer zusammengesetzten Region wird die
# Funktion je Bestandteil aufgerufen; scheitert einer, scheitert der ganze
# Wechsel. Eine Karte, der ein Land fehlt, waere schlimmer als kein Wechsel:
# sie liefert stillschweigend falsche Routen, statt sichtbar zu fehlen.
_download_one() {
    _dl_url="$1"; _dl_name="$2"
    _dl_part="$OSM_DIR/$_dl_name.part"
    rm -f "$_dl_part"
    if ! curl -fsSL --retry 3 --retry-delay 10 -o "$_dl_part" "$_dl_url"; then
        rm -f "$_dl_part"
        fail "Download fehlgeschlagen: $_dl_url"
    fi
    if [ -z "${SKIP_CHECKSUM:-}" ]; then
        if command -v md5sum >/dev/null 2>&1; then
            if ! curl -fsSL --max-time 60 -o "$OSM_DIR/$_dl_name.md5" "$_dl_url.md5"; then
                rm -f "$_dl_part"
                fail "Prüfsumme nicht abrufbar: $_dl_url.md5"
            fi
            if ! ( cd "$OSM_DIR" && sed "s|$_dl_name|$_dl_name.part|" "$_dl_name.md5" | md5sum -c - ); then
                rm -f "$_dl_part" "$OSM_DIR/$_dl_name.md5"
                fail "Prüfsumme stimmt nicht — Datei verworfen: $_dl_name"
            fi
            rm -f "$OSM_DIR/$_dl_name.md5"
        else
            log "WARNUNG: md5sum nicht verfügbar — Prüfsumme übersprungen."
        fi
    fi
    mv -f "$_dl_part" "$OSM_DIR/$_dl_name" || fail "Extract konnte nicht abgelegt werden: $_dl_name"
}

SOURCE_FILES=""
if [ -n "$SOURCES" ]; then
    _n=$(echo "$SOURCES" | tr '|' '\n' | wc -l | tr -d ' ')
    _i=0
    _old_ifs="$IFS"; IFS='|'
    for _src in $SOURCES; do
        IFS="$_old_ifs"
        _i=$((_i + 1))
        _src_name="$(basename "$_src")-latest.osm.pbf"
        _src_url="https://download.geofabrik.de/${_src}-latest.osm.pbf"
        # Die Bestandteile sind oben bereits gegen die Zeichen-Allowlist
        # geprueft worden; ein case auf die hier gebaute URL waere
        # unerreichbar, weil sie aus genau diesem Praefix entsteht.
        phase "downloading" "Phase 2/6: Lade ${_i}/${_n} — ${_src_name}…"
        _download_one "$_src_url" "$_src_name"
        SOURCE_FILES="$SOURCE_FILES $OSM_DIR/$_src_name"
        abort_if_cancelled
        IFS='|'
    done
    IFS="$_old_ifs"
else
    phase "downloading" "Phase 2/5: Lade ${FILENAME}…"
    _download_one "$URL" "$FILENAME"
fi
abort_if_cancelled

# ── Phase 3: Zusammenfuehren (nur bei mehreren Bestandteilen) ───────────────
if [ -n "$SOURCES" ]; then
    phase "merging" "Phase 3/6: Führe ${_n} Extracts zu einer Karte zusammen…"
    _resolve_volumes
    # Pfad ueberschreibbar wie REGION_SOURCE_SCRIPT: im Container liegt das
    # Skript unter /, im Test daneben. Der Default bleibt der Containerpfad.
    if ! OSM_VOLUME="$OSM_VOLUME" "${REGION_MERGE_SCRIPT:-/merge-extracts.sh}" \
            "$OSM_DIR/$FILENAME" $SOURCE_FILES; then
        rm -f $SOURCE_FILES "$OSM_DIR/$FILENAME"
        fail "Zusammenführen fehlgeschlagen — die alte Region läuft unverändert weiter."
    fi
    abort_if_cancelled
fi

# ── Phase 3: Importieren ────────────────────────────────────────────────────
phase "importing" "Phase ${_PH_IMPORT}: Baue Routing-Graph (läuft im Hintergrund, Routing bleibt aktiv)…"
rm -rf "$STAGING"
_resolve_volumes
# Import-Heap gegen den Speicher deckeln, der JETZT — mit noch laufendem
# GraphHopper — tatsächlich frei ist.
IMPORT_JAVA_OPTS="$(_capped_java_opts "$JAVA_OPTS" "Import")"
if ! _import_graph; then
    rm -rf "$STAGING"
    if [ "$IMPORT_CANCELLED" = 1 ]; then
        fail "Abgebrochen — die bisherige Region läuft unverändert weiter."
    fi
    fail "Graph-Bau fehlgeschlagen (häufigste Ursache: zu wenig Heap). Die alte Region läuft weiter."
fi
if cancelled; then
    rm -rf "$STAGING"
    fail "Abgebrochen — die bisherige Region läuft unverändert weiter."
fi

# ── Phase 4: Schwenken (ab hier kein Abbruch mehr) ──────────────────────────
phase "switching" "Phase ${_PH_SWITCH}: Schwenke auf die neue Region…"

# Beleg, dass im Staging überhaupt ein Graph liegt. `_import_graph` kann 0
# liefern, ohne dass etwas entstanden ist; die Schleife in
# `_swap_in_new_graph` liefe dann nullmal durch und ließe $GRAPH_DIR LEER
# zurück — der einzige unumkehrbare Schritt, ausgerechnet ungeprüft. Der
# Fingerprint ist der belastbarste Beleg: ihn schreibt der Entrypoint erst,
# nachdem er die Graph-Konfiguration festgelegt hat.
if [ ! -s "$STAGING/.graph_fingerprint" ]; then
    rm -rf "$STAGING"
    fail "Der Import hat keinen Graphen hinterlassen — die alte Region läuft unverändert weiter."
fi

# Ab hier wird am Graph-Verzeichnis gearbeitet: GraphHopper muss dafür still
# stehen (Begründung ausführlich bei _stop_graphhopper). Verifiziert
# _stop_graphhopper das nicht (klemmender Daemon), ist HIER der sicherste
# Abbruchpunkt: An diesem Graph-Verzeichnis wurde noch nichts verändert, also
# läuft die alte Region beim Abbruch unberührt weiter.
if ! _stop_graphhopper; then
    fail "GraphHopper ließ sich nicht sicher anhalten — die alte Region läuft unverändert weiter, nichts wurde verändert."
fi
# Erst jetzt den produktiven Heap deckeln: mit gestopptem GraphHopper meldet
# MemAvailable genau den Speicher, den der neue Container gleich vorfindet.
JAVA_OPTS="$(_capped_java_opts "$JAVA_OPTS" "produktiver GraphHopper")"
_backup_region_file || fail ".region konnte nicht gesichert werden — Schwenk abgebrochen, die alte Region läuft weiter."

if ! _swap_in_new_graph; then
    if ! _rollback_to_old_region; then
        fail "Graph-Tausch fehlgeschlagen UND der Rücktausch von Graph und .region ist fehlgeschlagen — manueller Eingriff nötig."
    fi
    fail "Graph-Tausch fehlgeschlagen — die alte Region ist wiederhergestellt."
fi
if ! _write_region_file; then
    if ! _rollback_to_old_region; then
        fail ".region konnte nicht geschrieben werden UND der Rücktausch ist fehlgeschlagen — manueller Eingriff nötig."
    fi
    fail ".region konnte nicht geschrieben werden — die alte Region ist wiederhergestellt."
fi

# Rückgabewert auswerten UND nachsehen, ob wirklich ein neuer Container steht:
# scheitert `compose up` früh (Konfigurationsfehler, fehlende Variable), läuft
# der ALTE Container weiter. _gh_cid fände ihn, _wait_gh_healthy meldete
# „gesund", Phase 5 löschte .old und das alte Extract — das Panel meldete
# „done", geroutet würde die alte Region, und es gäbe keinen Rollback-Bestand
# mehr. Der Vergleich der Container-ID vor/nach ist der Beleg, dass der
# Austausch stattgefunden hat.
GH_CID_BEFORE="$(_gh_cid)"
SWITCH_OK=1
if ! _compose up -d --force-recreate graphhopper >> "$LOG" 2>&1; then
    log "FEHLER: 'compose up -d --force-recreate graphhopper' ist fehlgeschlagen."
    SWITCH_OK=0
else
    GH_STOPPED=0
    GH_CID_AFTER="$(_gh_cid)"
    if [ -z "$GH_CID_AFTER" ]; then
        log "FEHLER: Nach 'compose up' existiert kein GraphHopper-Container."
        SWITCH_OK=0
    elif [ -n "$GH_CID_BEFORE" ] && [ "$GH_CID_AFTER" = "$GH_CID_BEFORE" ]; then
        log "FEHLER: GraphHopper läuft unverändert unter ${GH_CID_BEFORE} — 'compose up' hat nichts ausgetauscht."
        SWITCH_OK=0
    fi
fi
if [ "$SWITCH_OK" = 1 ] && ! _wait_gh_healthy "$REGION_HEALTH_TIMEOUT"; then
    log "Der neue Graph wird nicht gesund."
    SWITCH_OK=0
fi

if [ "$SWITCH_OK" != 1 ]; then
    log "Rollback auf die vorherige Region."
    if ! _rollback_to_old_region; then
        fail "Der Schwenk ist gescheitert UND der Rücktausch von Graph und .region ist fehlgeschlagen — manueller Eingriff nötig."
    fi
    if _compose up -d --force-recreate graphhopper >> "$LOG" 2>&1; then
        GH_STOPPED=0
    else
        # GH_STOPPED bleibt 1 — die Notbremse in _on_exit versucht es erneut.
        log "WARNUNG: 'compose up' nach dem Rollback meldete einen Fehler."
    fi
    if _wait_gh_healthy "$REGION_HEALTH_TIMEOUT"; then
        fail "Rollback auf die vorherige Region durchgeführt — der Schwenk auf die neue Region ist gescheitert."
    fi
    fail "Rollback auf die vorherige Region durchgeführt, aber GraphHopper wird auch damit nicht gesund — manueller Eingriff nötig."
fi

# ── Phase 5: Aufräumen ──────────────────────────────────────────────────────
phase "cleaning" "Phase ${_PH_CLEAN}: Räume alte Daten auf…"
rm -rf "$OLD" "$STAGING"
rm -f "$REGION_BACKUP"
find "$OSM_DIR" -maxdepth 1 \( -name '*-latest.osm.pbf' -o -name 'merged-*.osm.pbf' \) \
     ! -name "$FILENAME" -exec rm -f {} + 2>/dev/null
find "$OSM_DIR" -maxdepth 1 \( -name '*.md5' -o -name '*.part' \) -exec rm -f {} + 2>/dev/null

phase "done" "Regionswechsel abgeschlossen: $FILENAME"
FINISHED=1
_release
exit 0
