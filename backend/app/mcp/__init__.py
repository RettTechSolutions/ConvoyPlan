"""MCP-Server (Model Context Protocol) für ConvoyPlan.

Der Server läuft in-process in derselben FastAPI-Anwendung wie die REST-API
und greift über dieselben Dienste (``app/services``) auf die Fachdaten zu —
nicht über HTTP auf die eigene API.

Aufbau:

- ``scopes``  — die drei Scopes als Projektion der Rollenhierarchie
- ``areas``   — die Bereiche: welcher Ausschnitt der Fachdaten je Werkzeug
- ``context`` — vom ``AccessToken`` zur ``OrgCtx`` (Benutzer, Org, Rolle)
- ``tools_read`` / ``tools_write`` — die Werkzeuge selbst
- ``mount``   — ASGI-Verdrahtung in die FastAPI-App

Zwei Schalter entscheiden über den Zugriff, und sie beantworten verschiedene
Fragen: ``services/mcp_config`` sagt, ob es die Schnittstelle auf dieser
**Instanz** gibt (abgeschaltet ist keine Route montiert);
``services/org_mcp_policy`` sagt, ob eine **Organisation** daran teilnimmt und
in welchem Umfang — standardmäßig gar nicht.
"""

# ── Positivliste der Werkzeuge ───────────────────────────────────────────
#
# Die Absicherung gegen löschende Werkzeuge läuft nicht über eine Namensregel
# ("kein Tool heißt *_loeschen"), sondern über diese Liste: ``tests/
# test_mcp_tools.py`` vergleicht die tatsächlich registrierten Namen **exakt**
# mit ihr. Ein neu hinzugefügtes Werkzeug bricht den Test, bis es hier bewusst
# eingetragen wurde — und ein kreativ benanntes kommt nicht daran vorbei.
#
# Es gibt kein Werkzeug, das einen Konvoi, ein Fahrzeug, einen Wegpunkt, eine
# Route oder einen Benutzer löscht.
READ_TOOLS: tuple[str, ...] = (
    # Lesend (Phase 1)
    "organisation_details",
    "konvois_auflisten",
    "konvoi_details",
    "unterkonvois_auflisten",
    "fahrzeuge_auflisten",
    "fahrzeug_details",
    "wegpunkte_auflisten",
    "route_abrufen",
    "fahrzeugpositionen_abrufen",
    "konvoi_status",
)
ALLOWED_TOOLS: tuple[str, ...] = READ_TOOLS

# Die schreibenden Werkzeuge (Phase 2). Sie erscheinen nur, wenn die Instanz
# lizenziert ist — ohne Lizenz verhält sich der MCP-Server wie die REST-API
# im Demo-Modus: lesen ja, schreiben nein.
#
# Keines davon löscht einen Datensatz. ``fahrzeug_aus_konvoi_entfernen`` löst
# nur die Zuordnung; Fahrzeug und Konvoi bleiben bestehen.
WRITE_TOOLS: tuple[str, ...] = (
    "konvoi_anlegen",
    "konvoi_aktualisieren",
    "fahrzeug_anlegen",
    "fahrzeug_aktualisieren",
    "fahrzeug_zu_konvoi_hinzufuegen",
    "fahrzeug_aus_konvoi_entfernen",
    "konvoi_fahrzeuge_umsortieren",
    "wegpunkt_anlegen",
    "wegpunkt_aktualisieren",
    "wegpunkte_umsortieren",
    "route_berechnen",
    "fahrzeugstatus_setzen",
    "fahrzeugstaerke_melden",
    "fahrzeug_betriebsstoff_melden",
)

ALLOWED_TOOLS = ALLOWED_TOOLS + WRITE_TOOLS
