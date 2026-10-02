#!/usr/bin/env bash
# Prueft den Schritt "Naechste Version bestimmen" in auto-release.yml: Welche
# Nummer bekommt ein automatisch geschnittenes Release?
#
# Warum es diesen Test gibt: Am 2026-09-30 lag 2026.7.0 vorbereitet auf main
# (Changelog, frontend/package.json), aber ungetaggt. Eine Dependabot-Welle
# loeste diesen Workflow aus, und der zaehlte stur die FIX-Komponente des
# letzten Tags hoch: v2026.6.1 -> v2026.6.2. Ausgeliefert wurde der ganze
# 7.0-Stand unter einer Fix-Nummer.
#
# Der Schritt wird NICHT nachgebaut, sondern aus auto-release.yml
# herausgeschnitten und in einem Wegwerf-Repository ausgefuehrt — mit echten
# Tags und einer echten package.json, ohne Netz.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
YML="$HERE/../auto-release.yml"
FAILED=0

ok()  { echo "ok   — $1"; }
bad() { echo "FAIL — $1"; FAILED=1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

awk '
  /^      - name: Nächste Version bestimmen/ { drin=1; next }
  drin && /^        run: \|/                 { lesen=1; next }
  lesen && /^      - name:/                  { exit }
  lesen                                       { sub(/^          /, ""); print }
' "$YML" > "$WORK/schritt.sh"

if [ ! -s "$WORK/schritt.sh" ]; then
    bad "Schritt 'Nächste Version bestimmen' in auto-release.yml nicht gefunden"
    exit 1
fi
ok "Schritt aus auto-release.yml gelesen ($(wc -l < "$WORK/schritt.sh") Zeilen)"

# Ein Repository mit Ursprung (fuer `git fetch --tags`), Tags auf frueheren
# Commits und HEAD darueber. $1 = Version in package.json, weitere Argumente
# sind Tags, alle auf dem ersten Commit. Ausgabe: der Wert von `next`.
naechste() {
    local version="$1"; shift
    local d="$WORK/fall$RANDOM"
    git init -q --bare "$d/ursprung.git"
    git init -q "$d/repo"
    (
        cd "$d/repo"
        git config user.email t@t; git config user.name t
        git remote add origin "$d/ursprung.git"
        mkdir -p frontend
        printf '{\n\t"name": "frontend",\n\t"version": "%s",\n\t"private": true\n}\n' "$version" > frontend/package.json
        git add -A; git commit -q -m eins
        for t in "$@"; do git tag "$t"; done
        echo x > neu; git add -A; git commit -q -m zwei
        git push -q origin HEAD:main --tags 2>/dev/null
        : > "$d/out"
        GITHUB_OUTPUT="$d/out" bash "$WORK/schritt.sh" >/dev/null 2>&1
        sed -n 's/^next=//p' "$d/out"
    )
}

# Der Fall vom 30.09.: 7.0 vorbereitet, letzter Tag 6.1.
[ "$(naechste 2026.7.0 v2026.6.0 v2026.6.1)" = "v2026.7.0" ] \
    && ok "vorbereitetes 2026.7.0 wird getaggt statt v2026.6.2" \
    || bad "vorbereitetes 2026.7.0: erwartet v2026.7.0, bekam '$(naechste 2026.7.0 v2026.6.0 v2026.6.1)'"

# Der Normalfall: package.json steht auf dem letzten Release.
[ "$(naechste 2026.7.0 v2026.7.0)" = "v2026.7.1" ] \
    && ok "package.json = letzter Tag: FIX wird erhöht" \
    || bad "package.json = letzter Tag: erwartet v2026.7.1, bekam '$(naechste 2026.7.0 v2026.7.0)'"

# Nach Fix-Releases steht package.json unter dem letzten Tag.
[ "$(naechste 2026.7.0 v2026.7.0 v2026.7.1 v2026.7.2)" = "v2026.7.3" ] \
    && ok "package.json unter dem letzten Tag: FIX wird erhöht" \
    || bad "package.json unter dem letzten Tag: erwartet v2026.7.3"

# Zweistellige Master-Nummer: numerisch, nicht als Text verglichen.
[ "$(naechste 2026.10.0 v2026.9.4)" = "v2026.10.0" ] \
    && ok "2026.10.0 liegt über v2026.9.4" \
    || bad "2026.10.0 gegen v2026.9.4: erwartet v2026.10.0, bekam '$(naechste 2026.10.0 v2026.9.4)'"

# Eine Vorabversion in package.json ist kein vorbereitetes Release.
[ "$(naechste 2026.8.0-beta.1 v2026.7.2)" = "v2026.7.3" ] \
    && ok "Vorabversion in package.json zählt nicht" \
    || bad "Vorabversion: erwartet v2026.7.3, bekam '$(naechste 2026.8.0-beta.1 v2026.7.2)'"

# Beta-Tags sind nicht der letzte Stand.
[ "$(naechste 2026.7.0 v2026.7.0 v2026.8.0-beta.1)" = "v2026.7.1" ] \
    && ok "Beta-Tags werden übergangen" \
    || bad "Beta-Tags: erwartet v2026.7.1, bekam '$(naechste 2026.7.0 v2026.7.0 v2026.8.0-beta.1)'"

exit $FAILED
