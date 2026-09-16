"""MCP-Server (Model Context Protocol) für ConvoyPlan.

Der Server läuft in-process in derselben FastAPI-Anwendung wie die REST-API
und greift über dieselben Dienste (``app/services``) auf die Fachdaten zu —
nicht über HTTP auf die eigene API.

Aufbau:

- ``scopes``  — die drei Scopes als Projektion der Rollenhierarchie
- ``context`` — vom ``AccessToken`` zur ``OrgCtx`` (Benutzer, Org, Rolle)
- ``tools_read`` / ``tools_write`` — die Werkzeuge selbst
- ``mount``   — ASGI-Verdrahtung in die FastAPI-App

Montiert wird nur, wenn ``settings.mcp_enabled`` gesetzt ist.
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
ALLOWED_TOOLS: tuple[str, ...] = (
    # Lesend (Phase 1)
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
