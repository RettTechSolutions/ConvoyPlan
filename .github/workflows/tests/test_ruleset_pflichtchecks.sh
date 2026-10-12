#!/usr/bin/env bash
# Prueft, dass jeder Pflicht-Check aus .github/rulesets/main.json als Job in
# ci.yml existiert und auf den Ereignissen laeuft, auf die das Ruleset wartet.
#
# Warum es diesen Test gibt: Ein Pflicht-Check ist im Ruleset nur ein String.
# Benennt jemand den Job um (oder tippt "-" statt "–"), meldet GitHub keinen
# Fehler — es wartet auf "Expected — Waiting for status", und weder ein PR
# noch die Merge Queue kommt je durch. Dasselbe passiert, wenn ci.yml einen
# Pfadfilter bekommt oder den merge_group-Trigger verliert.
#
# Gelesen wird das Original, ohne Netz und ohne YAML-Bibliothek: Job-Namen
# stehen in ci.yml auf genau vier Leerzeichen Einrueckung.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CI="$HERE/../ci.yml"
RULESET="$HERE/../../rulesets/main.json"
FAILED=0

ok()  { echo "ok   — $1"; }
bad() { echo "FAIL — $1"; FAILED=1; }

PFLICHT="$(python3 -c '
import json, sys
for r in json.load(open(sys.argv[1]))["rules"]:
    if r["type"] == "required_status_checks":
        for c in r["parameters"]["required_status_checks"]:
            print(c["context"])
' "$RULESET")"

if [ -z "$PFLICHT" ]; then
    bad "keine Pflicht-Checks in main.json gefunden"
    exit 1
fi

# Job-Namen aus ci.yml: "    name: …" direkt unter einem Job-Schluessel.
NAMEN="$(awk '/^jobs:/ { j=1; next } j && /^    name: / { sub(/^    name: /, ""); print }' "$CI")"

while IFS= read -r ctx; do
    if printf '%s\n' "$NAMEN" | grep -qxF -- "$ctx"; then
        ok "Pflicht-Check '$ctx' ist ein Job in ci.yml"
    else
        bad "Pflicht-Check '$ctx' steht in main.json, aber kein Job in ci.yml heisst so"
    fi
done <<< "$PFLICHT"

# Ein Job, der nur nach Zeitplan laeuft, meldet auf einem PR nie.
while IFS= read -r ctx; do
    bedingung="$(awk -v n="    name: $ctx" '
        $0 == n { drin=1; next }
        drin && /^  [a-z]/ { exit }
        drin && /^    if: / { sub(/^    if: /, ""); print; exit }
    ' "$CI")"
    case "$bedingung" in
        ""|"github.event_name != 'schedule'"|"always() && github.event_name != 'schedule'"|"github.event_name != 'schedule' && needs.changes.outputs.region == 'true'")
            ok "'$ctx' meldet auf PR und Merge Queue (ausgefuehrt oder uebersprungen)" ;;
        *) bad "'$ctx' hat die Bedingung '$bedingung' — meldet er auf jedem PR?" ;;
    esac
done <<< "$PFLICHT"

# Die Ausloeser selbst: merge_group fuer die Queue, kein Pfadfilter.
AUSLOESER="$(awk '/^on:/ { o=1; next } o && /^[a-z]/ { exit } o' "$CI")"
if printf '%s\n' "$AUSLOESER" | grep -q '^  merge_group:'; then
    ok "ci.yml hoert auf merge_group"
else
    bad "ci.yml hat keinen merge_group-Trigger — die Merge Queue wartete ewig"
fi
if printf '%s\n' "$AUSLOESER" | grep -qE '^\s+(paths|paths-ignore):'; then
    bad "ci.yml hat einen Pfadfilter — Pflicht-Checks blieben bei manchen PRs aus"
else
    ok "ci.yml hat keinen Pfadfilter"
fi

exit "$FAILED"
