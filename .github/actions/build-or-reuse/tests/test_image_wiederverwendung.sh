#!/usr/bin/env bash
# Prueft die Entscheidung aus ../decide.sh: wann ein Image neu gebaut wird und
# wann der veroeffentlichte Digest stehen bleibt.
#
# Die Zusage, die hier festgehalten wird, sieht man keinem Workflow-Lauf an:
# Ein Bau ohne Aenderung kostet auf jeder Installation einen Container-Tausch,
# bei GraphHopper minutenlangen Routing-Ausfall fuer den Neuaufbau des
# Graphen. Andersherum ist ein ausgelassener Bau ein Image, das ein
# Sicherheitsupdate nicht bekommt. Beide Fehler sind still — der eine faellt
# als "GraphHopper startet schon wieder" auf, der andere gar nicht.
#
# Geprueft wird die echte Datei, nicht ein Nachbau: decide.sh liest nur
# Umgebungsvariablen und schreibt nur nach stdout, genau dafuer ist sie von
# der Registry-Abfrage in action.yml getrennt.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DECIDE="$HERE/../decide.sh"
FAILED=0

ok()  { echo "ok   — $1"; }
bad() { echo "FAIL — $1"; FAILED=1; }

# Ruft decide.sh mit einem vollstaendigen, unauffaelligen Satz Variablen auf;
# jedes Argument der Form NAME=WERT ueberschreibt davon einen.
entscheide() {
    local frisch
    frisch="$(date -u -d '-1 day' +%Y-%m-%dT%H:%M:%SZ)"
    env \
        FORCE=false \
        HAVE_IMAGE=true \
        TREE=aaaa1111 \
        PREV_TREE=aaaa1111 \
        BASE="alpine:3.20" \
        BASE_DIGEST=sha256:bbbb \
        PREV_BASE=sha256:bbbb \
        CREATED="$frisch" \
        MAX_AGE_DAYS=7 \
        SOURCE_PATH=graphhopper \
        "$@" \
        bash "$DECIDE"
}

# Ein Grund liegt vor (egal welcher Wortlaut) — und er nennt das erwartete
# Stichwort, damit der Text im Workflow-Log brauchbar bleibt.
erwarte_bau() {
    local beschreibung="$1" stichwort="$2"; shift 2
    local grund; grund="$(entscheide "$@")"
    if [ -z "$grund" ]; then
        bad "$beschreibung: kein Grund genannt, es wuerde NICHT gebaut"
    elif [[ "$grund" != *"$stichwort"* ]]; then
        bad "$beschreibung: Grund '$grund' nennt '$stichwort' nicht"
    else
        ok "$beschreibung → $grund"
    fi
}

erwarte_wiederverwendung() {
    local beschreibung="$1"; shift
    local grund; grund="$(entscheide "$@")"
    if [ -n "$grund" ]; then
        bad "$beschreibung: wuerde gebaut ('$grund'), soll aber stehen bleiben"
    else
        ok "$beschreibung → bleibt stehen"
    fi
}

# ── Der Normalfall, um den es geht ──────────────────────────────────────────
erwarte_wiederverwendung "unveraendert, frisch, gleiches Base-Image"

# ── Jeder einzelne Grund fuer einen Bau ─────────────────────────────────────
erwarte_bau "Quelltext geaendert"        "graphhopper"  TREE=cccc2222
erwarte_bau "Base-Image bewegt"          "alpine:3.20"  BASE_DIGEST=sha256:neu
erwarte_bau "Image zu alt"               "Grenze"       CREATED="$(date -u -d '-30 days' +%Y-%m-%dT%H:%M:%SZ)"
erwarte_bau "noch kein Image im Kanal"   "noch kein"    HAVE_IMAGE=false
erwarte_bau "Altbestand ohne Quellstand" "Quellstand"   PREV_TREE=
erwarte_bau "Bau erzwungen"              "erzwungen"    FORCE=true

# Ein unlesbarer Zeitstempel ist kein Freibrief: lieber einmal zu viel bauen
# als ein Image unbekannten Alters unbegrenzt stehen lassen.
erwarte_bau "Erstellungszeitpunkt unlesbar" "Alter" CREATED="neulich"

# ── Die Faelle, in denen NICHT gebaut werden darf ───────────────────────────
# Ist die Registry beim Base-Image-Vergleich nicht erreichbar, bleibt der
# Digest leer. Das darf keinen Bau ausloesen (sonst baute jede Stoerung bei
# Docker Hub alles neu) — die Altersgrenze faengt den Fall auf.
erwarte_wiederverwendung "Base-Digest nicht ermittelbar" BASE_DIGEST= PREV_BASE=

# Genau an der Grenze: 6 Tage sind noch innerhalb von 7.
erwarte_wiederverwendung "knapp unter der Altersgrenze" \
    CREATED="$(date -u -d '-6 days' +%Y-%m-%dT%H:%M:%SZ)"

# ── Die Leseformel fuer die Label ───────────────────────────────────────────
# Sie steht in action.yml und wird hier NICHT nachgebaut, sondern
# herausgeschnitten: ein Nachbau prueft die Kopie, nicht das Original.
#
# Sie ist die einzige Stelle, an der die Form der imagetools-Ausgabe
# interpretiert wird, und ihr Versagen ist lautlos. Greift sie daneben, findet
# kein Lauf mehr einen Quellstand, jedes Image gilt als "Altbestand ohne
# Quellstand" und wird wieder bei jedem Push gebaut — nichts schlaegt dabei
# fehl, es wird nur alles wieder teuer. Die Form haengt davon ab, ob unter dem
# Tag ein einzelnes Manifest oder eine Liste liegt; beides kommt vor.
ACTION="$HERE/../action.yml"
FORMEL="$(sed -n "s/.*'\(\[\.\. | objects | \.Labels.*first \/\/ empty\)'.*/\1/p" "$ACTION" | head -1)"
if [ -z "$FORMEL" ]; then
    bad "Leseformel in action.yml nicht gefunden — Test und Aktion sind auseinandergelaufen"
else
    lies() { printf '%s' "$2" | jq -r --arg k de.convoyplan.source-tree "$FORMEL" 2>/dev/null; }

    einzeln='{"created":"2026-09-16T10:00:00Z","config":{"Labels":{"de.convoyplan.source-tree":"tree-aaa"}}}'
    liste='{"linux/amd64":{"created":"2026-09-16T10:00:00Z","config":{"Labels":{"de.convoyplan.source-tree":"tree-bbb"}}}}'
    ohne='{"created":"2026-09-16T10:00:00Z","config":{}}'

    [ "$(lies x "$einzeln")" = "tree-aaa" ] \
        && ok "Label aus einem einzelnen Manifest gelesen" \
        || bad "Label aus einem einzelnen Manifest: bekam '$(lies x "$einzeln")'"
    [ "$(lies x "$liste")" = "tree-bbb" ] \
        && ok "Label aus einer Manifestliste gelesen (Attestierungen machen daraus eine)" \
        || bad "Label aus einer Manifestliste: bekam '$(lies x "$liste")'"
    [ -z "$(lies x "$ohne")" ] \
        && ok "Image ohne unsere Label liefert leer statt Unsinn" \
        || bad "Image ohne unsere Label lieferte '$(lies x "$ohne")'"
fi

if [ "$FAILED" = 0 ]; then
    echo "Alle Zusicherungen erfuellt."
else
    echo "Es sind Zusicherungen fehlgeschlagen."
fi
exit "$FAILED"
