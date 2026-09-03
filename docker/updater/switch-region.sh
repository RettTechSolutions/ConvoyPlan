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
# der Schwenk selbst, holt _restore_old_graph() ihn samt alter .region zurück.
#
# Aufruf: aus der Poll-Schleife des Updaters, wenn region_request.json vorliegt
# und kein region.lock existiert.
#
# Env (alles optional, Defaults = Produktion):
#   STATUS_DIR OSM_DIR GRAPH_DIR REPO_DIR COMPOSE_PROJECT_NAME
#   GRAPHHOPPER_IMAGE REGION_COMPOSE_FILE REGION_IMPORT_MODE
#   REGION_HEALTH_TIMEOUT REGION_IMPORT_TIMEOUT REGION_POLL_SLEEP SKIP_CHECKSUM
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

OWNS_LOCK=0        # 1, sobald dieses Skript das Lock hält
FINISHED=0         # 1 nach erfolgreichem Abschluss
FAILED_REPORTED=0  # 1, sobald fail() den Endstatus geschrieben hat

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
_wait_container_healthy() {
    local cid="$1" timeout="$2" waited=0 health status restarts
    health=""; status=""
    while [ "$waited" -lt "$timeout" ]; do
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
        -e "JAVA_OPTS=${JAVA_OPTS}"
        -e "GRAPH_DIR=${STAGING_IN_CONTAINER}"
        -e "REGION_SOURCE_SCRIPT=/dev/null"
    )
}

_import_graph_via_server() {
    local cid rc=1 name="convoyplan-region-import-$$"
    _import_container_args
    log "Baue den Graphen über einen temporären GraphHopper-Server (Rückfallweg)."
    docker rm -f "$name" >/dev/null 2>&1
    cid="$(docker run -d --name "$name" \
        --health-cmd "curl -f http://localhost:8989/health" \
        --health-interval 15s --health-timeout 10s --health-retries 3 \
        --health-start-period 60s \
        "${IMPORT_ARGS[@]}" -e "GH_COMMAND=server" \
        "$GRAPHHOPPER_IMAGE" 2>&1 | tail -1)"
    if [ -z "$cid" ]; then
        log "Import-Container ließ sich nicht starten."
        return 1
    fi
    if _wait_container_healthy "$cid" "$REGION_IMPORT_TIMEOUT"; then
        rc=0
    fi
    docker logs --tail 50 "$cid" >> "$LOG" 2>&1
    docker stop -t 30 "$cid" >/dev/null 2>&1
    docker rm -f "$cid" >/dev/null 2>&1
    return "$rc"
}

_import_graph() {
    local out rc
    if [ "$REGION_IMPORT_MODE" = "server" ]; then
        _import_graph_via_server
        return $?
    fi
    _import_container_args
    out="$STATUS_DIR/.region-import-out.$$"
    # Ausgabe live nach region.log (das Panel zeigt sie an — ein Import kann
    # Stunden dauern) UND in eine Datei, um danach die Ursache eines
    # Fehlschlags erkennen zu koennen.
    docker run --rm "${IMPORT_ARGS[@]}" -e "GH_COMMAND=import" "$GRAPHHOPPER_IMAGE" 2>&1 \
        | tee -a "$LOG" > "$out"
    rc="${PIPESTATUS[0]}"
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
# also praktisch verzögerungsfrei. Der laufende GraphHopper stört das nicht:
# ein Umbenennen lässt offene Dateideskriptoren unberührt.
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

_restore_old_graph() {
    local entry base
    [ -d "$OLD" ] || return 0
    shopt -s dotglob nullglob
    for entry in "$GRAPH_DIR"/*; do
        base="${entry##*/}"
        case "$base" in .old) continue ;; esac
        rm -rf "$entry"
    done
    for entry in "$OLD"/*; do
        mv -f "$entry" "$GRAPH_DIR/"
    done
    shopt -u dotglob nullglob
    rmdir "$OLD" 2>/dev/null || rm -rf "$OLD"
}

# .region atomar schreiben: Temporärdatei im selben Verzeichnis, dann mv. Die
# Alles-oder-nichts-Semantik in graphhopper/region-source.sh fängt eine formal
# kaputte Datei ab — eine Datei mit allen drei Schlüsseln und abgeschnittenem
# letztem Wert käme aber durch.
_write_region_file() {
    local tmp="$OSM_DIR/.region.tmp.$$"
    if [ -f "$REGION_FILE" ]; then
        cp "$REGION_FILE" "$REGION_BACKUP" || return 1
    else
        rm -f "$REGION_BACKUP"
    fi
    printf 'OSM_DOWNLOAD_URL=%s\nOSM_FILENAME=%s\nJAVA_OPTS=%s\n' \
        "$URL" "$FILENAME" "$JAVA_OPTS" > "$tmp" || { rm -f "$tmp"; return 1; }
    chmod 0644 "$tmp" 2>/dev/null || true
    mv -f "$tmp" "$REGION_FILE" || { rm -f "$tmp"; return 1; }
    return 0
}

_restore_region_file() {
    if [ -f "$REGION_BACKUP" ]; then
        mv -f "$REGION_BACKUP" "$REGION_FILE"
    else
        rm -f "$REGION_FILE"
    fi
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
if [[ ! "$FILENAME" =~ ^[A-Za-z0-9._-]+-latest\.osm\.pbf$ ]]; then
    fail "Dateiname nicht zugelassen: $FILENAME"
fi
if [ "${URL##*/}" != "$FILENAME" ]; then
    fail "Dateiname passt nicht zur URL: $FILENAME"
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

# ── Phase 1: Prüfen ─────────────────────────────────────────────────────────
phase "checking" "Phase 1/5: Prüfe Verfügbarkeit und Platz…"
SIZE="$(curl -sSIL --max-time 60 "$URL" 2>/dev/null | awk 'tolower($1)=="content-length:"{v=$2} END{printf "%d", v+0}')"
[ "${SIZE:-0}" -gt 0 ] 2>/dev/null || fail "Extract nicht abrufbar: $URL"
# Grobe Faustregel: neues Extract + neuer Graph, rund das 2,5-fache der
# Extract-Größe. Beide Volumes liegen in der Regel auf demselben Dateisystem;
# liegen sie es nicht, wird hier zu Recht jedes einzeln geprüft.
NEEDED=$(( SIZE * 5 / 2 ))
for dir in "$OSM_DIR" "$GRAPH_DIR"; do
    free_kb="$(df -Pk "$dir" 2>/dev/null | awk 'NR==2{print $4}')"
    free=$(( ${free_kb:-0} * 1024 ))
    if [ "$free" -le "$NEEDED" ]; then
        fail "Zu wenig Plattenplatz unter $dir: $NEEDED Bytes benötigt, $free frei."
    fi
done
abort_if_cancelled

# ── Phase 2: Laden ──────────────────────────────────────────────────────────
phase "downloading" "Phase 2/5: Lade ${FILENAME}…"
PART="$OSM_DIR/$FILENAME.part"
rm -f "$PART"
if ! curl -fsSL --retry 3 --retry-delay 10 -o "$PART" "$URL"; then
    rm -f "$PART"
    fail "Download fehlgeschlagen: $URL"
fi
if [ -z "${SKIP_CHECKSUM:-}" ]; then
    if command -v md5sum >/dev/null 2>&1; then
        if ! curl -fsSL --max-time 60 -o "$OSM_DIR/$FILENAME.md5" "$URL.md5"; then
            rm -f "$PART"
            fail "Prüfsumme nicht abrufbar: $URL.md5"
        fi
        if ! ( cd "$OSM_DIR" && sed "s|$FILENAME|$FILENAME.part|" "$FILENAME.md5" | md5sum -c - ); then
            rm -f "$PART" "$OSM_DIR/$FILENAME.md5"
            fail "Prüfsumme stimmt nicht — Datei verworfen."
        fi
        rm -f "$OSM_DIR/$FILENAME.md5"
    else
        log "WARNUNG: md5sum nicht verfügbar — Prüfsumme übersprungen."
    fi
fi
mv -f "$PART" "$OSM_DIR/$FILENAME" || fail "Extract konnte nicht abgelegt werden."
abort_if_cancelled

# ── Phase 3: Importieren ────────────────────────────────────────────────────
phase "importing" "Phase 3/5: Baue Routing-Graph (läuft im Hintergrund, Routing bleibt aktiv)…"
rm -rf "$STAGING"
_resolve_volumes
if ! _import_graph; then
    rm -rf "$STAGING"
    fail "Graph-Bau fehlgeschlagen (häufigste Ursache: zu wenig Heap). Die alte Region läuft weiter."
fi
if cancelled; then
    rm -rf "$STAGING"
    fail "Abgebrochen — die bisherige Region läuft unverändert weiter."
fi

# ── Phase 4: Schwenken (ab hier kein Abbruch mehr) ──────────────────────────
phase "switching" "Phase 4/5: Schwenke auf die neue Region…"
if ! _swap_in_new_graph; then
    _restore_old_graph
    rm -rf "$STAGING"
    fail "Graph-Tausch fehlgeschlagen — die alte Region ist wiederhergestellt."
fi
if ! _write_region_file; then
    _restore_old_graph
    fail ".region konnte nicht geschrieben werden — die alte Region ist wiederhergestellt."
fi
_compose up -d --force-recreate graphhopper >> "$LOG" 2>&1 || \
    log "WARNUNG: 'compose up' meldete einen Fehler — prüfe trotzdem den Zustand."

if ! _wait_gh_healthy "$REGION_HEALTH_TIMEOUT"; then
    log "Der neue Graph wird nicht gesund — Rollback auf die vorherige Region."
    _restore_old_graph
    _restore_region_file
    _compose up -d --force-recreate graphhopper >> "$LOG" 2>&1 || true
    if _wait_gh_healthy "$REGION_HEALTH_TIMEOUT"; then
        fail "Rollback auf die vorherige Region durchgeführt — die neue Region wurde nicht gesund."
    fi
    fail "Die neue Region wurde nicht gesund UND der Rollback ist fehlgeschlagen — manueller Eingriff nötig."
fi

# ── Phase 5: Aufräumen ──────────────────────────────────────────────────────
phase "cleaning" "Phase 5/5: Räume alte Daten auf…"
rm -rf "$OLD" "$STAGING"
rm -f "$REGION_BACKUP"
find "$OSM_DIR" -maxdepth 1 -name '*-latest.osm.pbf' ! -name "$FILENAME" -exec rm -f {} + 2>/dev/null
find "$OSM_DIR" -maxdepth 1 \( -name '*.md5' -o -name '*.part' \) -exec rm -f {} + 2>/dev/null

phase "done" "Regionswechsel abgeschlossen: $FILENAME"
FINISHED=1
_release
exit 0
