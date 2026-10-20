#!/usr/bin/env bash
# Prueft den Schritt "Release-Notes aus dem CHANGELOG" in release.yml: Welcher
# Text steht ueber der automatischen PR-Liste eines Releases?
#
# Warum es diesen Test gibt: Bei 2026.8.0 und 2026.9.0 nannten die
# Release-Notes nur PR-Titel. Was beim Update zu beachten ist — jede Instanz
# baut ihren Graphen neu, Migrationen laufen —, stand nur im CHANGELOG und
# musste von Hand in die Notes kopiert werden.
#
# Der Schritt wird NICHT nachgebaut, sondern aus release.yml herausgeschnitten
# und gegen ein Wegwerf-CHANGELOG ausgefuehrt.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
YML="$HERE/../release.yml"
FAILED=0

ok()  { echo "ok   — $1"; }
bad() { echo "FAIL — $1"; FAILED=1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

awk '
  /^      - name: Release-Notes aus dem CHANGELOG/ { drin=1; next }
  drin && /^        run: \|/                       { lesen=1; next }
  lesen && /^      - name:/                        { exit }
  lesen                                             { sub(/^          /, ""); print }
' "$YML" > "$WORK/schritt.sh"

if [ ! -s "$WORK/schritt.sh" ]; then
    bad "Schritt 'Release-Notes aus dem CHANGELOG' in release.yml nicht gefunden"
    exit 1
fi
ok "Schritt aus release.yml gelesen ($(wc -l < "$WORK/schritt.sh") Zeilen)"

if grep -q 'body_path: release-notes.md' "$YML"; then
    ok "Create release liest release-notes.md"
else
    bad "Create release liest release-notes.md nicht (body_path fehlt)"
fi

cat > "$WORK/CHANGELOG.md" <<'EOF'
# Changelog

## [Unreleased]

## [2026.9.1] – 2026-10-21

### Fixed

- Ein Fix.

## [2026.9.0] – 2026-10-14

### Wichtig beim Update

- Graph wird neu gebaut.

### Added

- Etwas Neues.


## [2026.8.0] – 2026-10-09

### Added

- Altes.

[2026.9.0]: https://example.invalid/compare/v2026.8.0...v2026.9.0
EOF

# $1 = Tag. Fuehrt den Schritt im Wegwerf-Verzeichnis aus.
lauf() {
    (cd "$WORK" && rm -f release-notes.md && GITHUB_REF_NAME="$1" bash -e schritt.sh >/dev/null)
}

# 1: Der Abschnitt der Version, ohne Kopfzeile, ohne fremde Abschnitte.
lauf v2026.9.0
notes="$(cat "$WORK/release-notes.md")"
if [[ "$notes" == "### Wichtig beim Update"* ]]; then
    ok "1: beginnt mit dem ersten Unterabschnitt, ohne Kopfzeile und Leerzeilen"
else
    bad "1: Anfang falsch: $(head -2 "$WORK/release-notes.md")"
fi
grep -q "Graph wird neu gebaut" <<<"$notes" && grep -q "Etwas Neues" <<<"$notes" \
    && ok "1: Inhalt des Abschnitts vollstaendig" || bad "1: Inhalt fehlt"
if grep -q "Altes\|Ein Fix\|example.invalid" <<<"$notes"; then
    bad "1: Inhalt anderer Abschnitte oder der Linkliste uebernommen"
else
    ok "1: nichts aus anderen Abschnitten"
fi
if [ "$(tail -1 "$WORK/release-notes.md")" = "---" ]; then
    ok "1: Trennlinie vor der automatischen PR-Liste"
else
    bad "1: letzte Zeile ist '$(tail -1 "$WORK/release-notes.md")', erwartet '---'"
fi
vorletzte="$(tail -3 "$WORK/release-notes.md" | head -1)"
if [ -z "$vorletzte" ]; then
    bad "1: Leerzeilen am Abschnittsende nicht entfernt"
else
    ok "1: keine Leerzeilen-Haeufung vor der Trennlinie"
fi

# 2: Der oberste Abschnitt unter [Unreleased].
lauf v2026.9.1
grep -q "Ein Fix" "$WORK/release-notes.md" && ! grep -q "Graph" "$WORK/release-notes.md" \
    && ok "2: oberster Abschnitt endet am naechsten" || bad "2: Abschnitt 2026.9.1 falsch abgegrenzt"

# 3: Kein Abschnitt (Beta-Tag) — leere Datei, nur die PR-Liste.
lauf v2026.10.0-beta.1
if [ -e "$WORK/release-notes.md" ] && [ ! -s "$WORK/release-notes.md" ]; then
    ok "3: ohne Abschnitt leere Datei (nur automatische Notes)"
else
    bad "3: ohne Abschnitt erwartet leere Datei"
fi

# 4: Eine Version, die nur Praefix einer anderen ist, trifft nicht.
lauf v2026.9
if [ ! -s "$WORK/release-notes.md" ]; then
    ok "4: [2026.9] trifft nicht [2026.9.0]"
else
    bad "4: [2026.9] hat [2026.9.0] getroffen"
fi

# 5: Das echte CHANGELOG des Repos liefert fuer 2026.9.0 den Hinweis zum Update.
cp "$HERE/../../../CHANGELOG.md" "$WORK/CHANGELOG.md"
lauf v2026.9.0
if grep -q "Routing-Graphen" "$WORK/release-notes.md"; then
    ok "5: echtes CHANGELOG, 2026.9.0 nennt den Graph-Neuaufbau"
else
    bad "5: echtes CHANGELOG, Abschnitt 2026.9.0 nicht gefunden"
fi

exit "$FAILED"
