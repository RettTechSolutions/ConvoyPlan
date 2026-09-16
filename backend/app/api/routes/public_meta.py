"""Maschinenlesbare Selbstauskunft der Instanz.

Drei Dokumente, die ohne Anmeldung erreichbar sein müssen, damit ein Programm
oder ein KI-Agent überhaupt anfangen kann:

* ``GET /api/status/capabilities`` — welche Schnittstellen diese Instanz
  anbietet (liegt in ``status.py``, weil es zum Status gehört).
* ``GET /api/public/openapi.json`` — eine **Teilmenge** der OpenAPI-Beschreibung
  mit ausschließlich den Endpunkten, die ohnehin ohne Anmeldung erreichbar
  sind, plus den Sicherheitsschemata für alles andere.
* ``GET /.well-known/oauth-protected-resource`` — RFC 9728 für die REST-API.

Warum eine Teilmenge und nicht ``/openapi.json``: Die vollständige Beschreibung
ist in Produktion bewusst abgeschaltet und wird per ``DOCS_API_KEY`` geschützt
(siehe ``app/api/docs_ui.py``). Diese Entscheidung bleibt unangetastet — das
Admin- und Organisationsinnere taucht hier nicht auf. Was hier steht, könnte
ein Aufrufer auch durch Ausprobieren herausfinden; der Unterschied ist, dass er
es nicht muss.

Die Liste der öffentlichen Operationen steht **ausdrücklich** in
``PUBLIC_OPERATIONS``. Eine automatische Erkennung „hat keine Auth-Dependency,
also öffentlich" wäre bequemer und genau deshalb gefährlich: ein vergessener
Guard würde den Endpunkt nicht nur offen lassen, sondern ihn auch noch
veröffentlichen. ``tests/test_public_openapi.py`` prüft die Liste in beide
Richtungen — jeder Eintrag existiert, und keiner davon hängt an einem Guard.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.routes.version import _core_str
from app.config import settings
from app.mcp import scopes as scope_svc

router = APIRouter(prefix="/public", tags=["status"])
# Ohne Präfix: RFC 9728 verlangt das Dokument an der Wurzel der Site. Caddy
# reicht /.well-known/oauth-* an das Backend durch.
wellknown_router = APIRouter(include_in_schema=False)

# ── Was öffentlich ist ───────────────────────────────────────────────────

#: Die öffentlichen Operationen, jede mit einem **eigenen** Text.
#:
#: Die Beschreibung wird bewusst hier geschrieben und nicht aus dem Docstring
#: des Endpunkts übernommen. Docstrings in diesem Projekt erklären Entscheidungen
#: — warum etwas so und nicht anders gebaut wurde, welcher Fehler dahinter
#: steckte, welche Enumeration erschwert werden soll. Das ist für Mitlesende im
#: Repository richtig und in einem öffentlichen Dokument falsch: es beschreibt
#: nicht die Schnittstelle, sondern ihre Innenseite.
#:
#: Struktur (Parameter, Schemata, Antworten) kommt weiterhin aus der laufenden
#: App und kann deshalb nicht veralten.
PUBLIC_OPERATIONS: dict[tuple[str, str], dict[str, str]] = {
    ("/api/status/public", "get"): {
        "operationId": "getInstanceStatus",
        "summary": "Zustand dieser Instanz",
        "description": (
            "Grobkörniger Funktionsstatus: Erreichbarkeit von Datenbank, Routingdienst, "
            "Kartendaten und den externen Datenquellen für Wetter und Verkehr. Das Ergebnis "
            "ist kurz zwischengespeichert; häufigeres Abfragen liefert keine frischeren Daten."
        ),
    },
    ("/api/status/capabilities", "get"): {
        "operationId": "getInstanceCapabilities",
        "summary": "Welche Schnittstellen diese Instanz anbietet",
        "description": (
            "Sagt, ob der MCP-Server montiert ist, ob ein Demo-Zugang freigeschaltet ist und "
            "wo die maschinenlesbaren Beschreibungen liegen. Der richtige erste Aufruf für "
            "ein Programm, das diese Instanz noch nicht kennt."
        ),
    },
    ("/api/version", "get"): {
        "operationId": "getVersion",
        "summary": "Version dieser Instanz",
        "description": (
            "Die laufende Version und, falls bekannt, die neueste verfügbare. Ohne Anmeldung "
            "wird nur die Release-Version ausgegeben."
        ),
    },
    ("/api/version/changelog", "get"): {
        "operationId": "getChangelog",
        "summary": "Release Notes der laufenden Version",
        "description": (
            "Die Veröffentlichungshinweise zur laufenden Version, live von den GitHub-Releases "
            "bezogen und je Version zwischengespeichert."
        ),
    },
    ("/api/branding", "get"): {
        "operationId": "getBranding",
        "summary": "Branding dieser Instanz",
        "description": (
            "Name, Logos und Farben der Instanz. Ohne Anmeldung erreichbar, damit die "
            "Anmeldemaske bereits im richtigen Erscheinungsbild steht."
        ),
    },
    ("/api/branding/org/{slug}", "get"): {
        "operationId": "getOrganizationBranding",
        "summary": "Branding einer Organisation",
        "description": (
            "Das wirksame Erscheinungsbild einer Organisation: das Branding der Instanz, "
            "überschrieben durch die Angaben der Organisation."
        ),
    },
    ("/api/setup/status", "get"): {
        "operationId": "getSetupStatus",
        "summary": "Ob die Ersteinrichtung noch aussteht",
        "description": (
            "Meldet, ob auf dieser Instanz noch kein Superadmin-Konto besteht und der "
            "Einrichtungsassistent unter /setup läuft."
        ),
    },
    ("/api/auth/login", "post"): {
        "operationId": "login",
        "summary": "Anmelden und Token beziehen",
        "description": (
            "Meldet einen Benutzer an und liefert ein JWT für den Header "
            "`Authorization: Bearer …`. Ist für das Konto eine Multi-Faktor-Authentisierung "
            "eingerichtet, kommt stattdessen eine Aufforderung zurück, die zuerst beantwortet "
            "werden muss. Für feste Integrationen ist ein API-Key der bessere Weg — siehe "
            "/auth.md."
        ),
    },
    ("/api/auth/org-lookup", "get"): {
        "operationId": "lookupOrganization",
        "summary": "Organisations-Code auflösen",
        "description": (
            "Prüft, ob es zu einem Organisations-Code eine Organisation auf dieser Instanz "
            "gibt, und liefert deren Anzeigenamen für die Anmeldemaske."
        ),
    },
    ("/api/auth/demo-status", "get"): {
        "operationId": "getDemoStatus",
        "summary": "Ob ein Demo-Zugang freigeschaltet ist",
        "description": (
            "Meldet, ob auf dieser Instanz temporäre Demo-Umgebungen gestartet werden können "
            "und wie lange eine solche Sitzung gilt. Das ist die Sandbox dieser Instanz."
        ),
    },
    ("/api/license/mode", "get"): {
        "operationId": "getLicenseMode",
        "summary": "Ob die Instanz im Demo-Modus läuft",
        "description": (
            "Im Demo-Modus (keine gültige Lizenz hinterlegt) funktionieren lesende Zugriffe, "
            "schreibende antworten mit HTTP 402."
        ),
    },
    ("/api/region/outline", "get"): {
        "operationId": "getRegionOutline",
        "summary": "Umriss der geladenen Kartenregion",
        "description": (
            "Der Umriss der aktiven Kartenregion als GeoJSON-Feature. Außerhalb dieses "
            "Umrisses lässt sich keine Route berechnen — für einen Aufrufer die Antwort auf "
            "die Frage, ob eine Strecke überhaupt planbar ist."
        ),
    },
    ("/api/track/{slug}", "get"): {
        "operationId": "getSharedTrack",
        "summary": "Kolonne über einen Freigabe-Slug verfolgen",
        "description": (
            "Liefert Route, Wegpunkte, Fahrzeuge und die zuletzt gemeldeten Positionen einer "
            "Kolonne, die über einen öffentlichen Freigabe-Link geteilt wurde. Ist der Link "
            "passwortgeschützt, kommt zunächst nur ein Hinweis darauf zurück."
        ),
    },
    ("/api/track/{slug}/auth", "post"): {
        "operationId": "authenticateSharedTrack",
        "summary": "Passwortgeschützten Freigabe-Link öffnen",
        "description": (
            "Tauscht das Passwort eines geschützten Freigabe-Links gegen ein kurzlebiges "
            "Token, das im Header `X-Track-Token` mitgeschickt wird."
        ),
    },
}

_DESCRIPTION = """
Die **ohne Anmeldung erreichbaren** Endpunkte einer ConvoyPlan-Instanz.

ConvoyPlan ist self-hosted: jede Organisation betreibt ihre eigene Instanz unter
ihrer eigenen Domain. Diese Beschreibung gilt für genau die Instanz, von der sie
abgerufen wurde.

Der geschützte Teil der API — Konvois, Fahrzeuge, Wegpunkte, Routen, Positionen,
Benutzer und Administration — ist hier **nicht** enthalten, weil die
vollständige Beschreibung in Produktion bewusst nicht offen liegt. Die
Sicherheitsschemata unten beschreiben trotzdem, wie man sich dafür anmeldet:

* `bearerAuth` — JWT aus `POST /api/auth/login`, als `Authorization: Bearer …`
* `apiKeyAuth` — im Superadmin-Portal erzeugter Schlüssel als `X-API-Key: …`
* `oauth2` — für den MCP-Server unter `/mcp`, mit Zustimmung eines angemeldeten
  Benutzers und auf eine Organisation begrenzt

Ein geschützter Endpunkt antwortet ohne gültige Zugangsdaten mit `401` und einem
`WWW-Authenticate`-Header, der auf die Resource-Metadaten zeigt. Eine Instanz
ohne Lizenzschlüssel läuft im Demo-Modus: lesende Zugriffe funktionieren,
schreibende antworten mit `402`.

Prosa dazu: `/auth.md`, `/api.md` und `/agents.md` an der Wurzel dieser Instanz.
""".strip()

_BASE_URL_PATTERN = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$")


def _public_base_url(request: Request) -> str:
    """Die nach außen sichtbare Adresse dieser Instanz.

    Das Backend steht hinter Frontend und Reverse Proxy, seine eigene
    ``base_url`` wäre ``http://backend:8000``. Das Frontend reicht die echte
    Adresse durch; angenommen wird sie nur, wenn sie wie eine Adresse aussieht —
    ein Header ist Eingabe des Aufrufers, auch wenn er von nebenan kommt.
    """
    candidate = (request.headers.get("x-public-base-url") or "").strip().rstrip("/")
    if candidate and _BASE_URL_PATTERN.match(candidate):
        return candidate
    return settings.app_base_url.rstrip("/")


# ── OpenAPI-Teilmenge ────────────────────────────────────────────────────


def _collect_refs(node: Any, found: set[str]) -> None:
    """Alle ``$ref``-Ziele unterhalb eines Knotens einsammeln."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_refs(value, found)


def _referenced_schemas(paths: dict[str, Any], all_schemas: dict[str, Any]) -> dict[str, Any]:
    """Nur die Schemata behalten, die von den übernommenen Pfaden erreichbar sind.

    Ohne das trüge die öffentliche Beschreibung die Modelle der geschützten
    Endpunkte mit sich — genau das, was sie nicht tun soll.
    """
    wanted: set[str] = set()
    _collect_refs(paths, wanted)
    # Schemata verweisen auf Schemata; bis zum Fixpunkt folgen.
    while True:
        nested: set[str] = set()
        for name in wanted:
            if name in all_schemas:
                _collect_refs(all_schemas[name], nested)
        if nested <= wanted:
            break
        wanted |= nested
    return {name: all_schemas[name] for name in sorted(wanted) if name in all_schemas}


def _security_schemes(base: str) -> dict[str, Any]:
    return {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT aus POST /api/auth/login.",
        },
        "apiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "Im Superadmin-Portal erzeugter Schlüssel. Gehört zu genau einer "
                "Organisation und trägt eine feste Rolle."
            ),
        },
        "oauth2": {
            "type": "oauth2",
            "description": (
                "OAuth 2.1 mit PKCE für den MCP-Server. Zugriff entsteht durch die "
                "Zustimmung eines angemeldeten Benutzers und gilt für genau eine "
                "Organisation, gedeckelt durch dessen Rolle."
            ),
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": f"{base}/authorize",
                    "tokenUrl": f"{base}/token",
                    "refreshUrl": f"{base}/token",
                    "scopes": dict(scope_svc.SCOPE_LABELS),
                }
            },
        },
    }


def build_public_openapi(app: Any, base: str) -> dict[str, Any]:
    """Die öffentliche Teilmenge aus der Beschreibung der laufenden App bauen."""
    full = app.openapi()
    full_paths = full.get("paths", {})
    paths: dict[str, Any] = {}

    for (path, method), described in PUBLIC_OPERATIONS.items():
        entry = full_paths.get(path)
        if not entry or method not in entry:
            continue
        operation = dict(entry[method])
        # Prosa ersetzen, Struktur behalten.
        operation["operationId"] = described["operationId"]
        operation["summary"] = described["summary"]
        operation["description"] = described["description"]
        # Diese Endpunkte brauchen ausdrücklich keine Anmeldung. Ohne die leere
        # Liste erbt ein Modell das Sicherheitsschema der App und fragt nach
        # einem Token, das hier niemand braucht.
        operation["security"] = []
        target = paths.setdefault(path, {})
        target[method] = operation
        # Parameter, die für alle Methoden eines Pfades gelten.
        if "parameters" in entry and "parameters" not in target:
            target["parameters"] = entry["parameters"]

    schemas = _referenced_schemas(paths, full.get("components", {}).get("schemas", {}))

    return {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "ConvoyPlan — öffentliche API",
            # Nur die Kernversion: ``settings.app_version`` ist ein
            # ``git describe``-String und verriete einem anonymen Aufrufer den
            # genauen Commit. ``/api/version`` hält ihn aus genau diesem Grund
            # zurück (siehe dort), und ein offenes Dokument darf ihn nicht
            # hintenherum nachreichen.
            "version": _core_str(settings.app_version) or "0",
            "summary": (
                "Ohne Anmeldung erreichbare Endpunkte einer ConvoyPlan-Instanz "
                "(Marsch- und Konvoiplanung für Einsatzorganisationen)."
            ),
            "description": _DESCRIPTION,
            "contact": {"name": "RettTech Solutions", "url": "https://convoyplan.de", "email": "anfrage@convoyplan.de"},
            "license": {"name": "AGPL-3.0-or-later", "url": "https://www.gnu.org/licenses/agpl-3.0.html"},
        },
        "servers": [{"url": base, "description": "Diese Instanz"}],
        "externalDocs": {
            "description": "Anleitung für Agenten und Authentifizierung",
            "url": f"{base}/agents.md",
        },
        "tags": [
            {"name": "status", "description": "Zustand, Version und Fähigkeiten dieser Instanz."},
            {"name": "auth", "description": "Anmeldung und Token-Ausgabe."},
            {"name": "track", "description": "Live-Tracking über einen öffentlichen Freigabe-Slug."},
            {"name": "branding", "description": "Farben und Logo dieser Instanz."},
            {"name": "region", "description": "Umriss der geladenen Kartenregion."},
            {"name": "setup", "description": "Ob die Ersteinrichtung noch aussteht."},
            {"name": "license", "description": "Lizenz- und Demo-Modus dieser Instanz."},
        ],
        "paths": paths,
        "components": {"schemas": schemas, "securitySchemes": _security_schemes(base)},
    }


@router.get(
    "/openapi.json",
    include_in_schema=False,
    summary="OpenAPI-Beschreibung der öffentlichen Endpunkte",
)
async def public_openapi(request: Request) -> JSONResponse:
    document = build_public_openapi(request.app, _public_base_url(request))
    return JSONResponse(
        document,
        headers={
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*",
            # JSONResponse setzt den Content-Type selbst; der ``media_type``
            # eines Response-Objekts, das FastAPI nur durchreicht, käme nicht
            # durch. Deshalb hier ausdrücklich.
            "Content-Type": "application/vnd.oai.openapi+json;version=3.1",
        },
    )


# ── RFC 9728 für die REST-API ────────────────────────────────────────────


@wellknown_router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request) -> JSONResponse:
    """Protected Resource Metadata der REST-API (RFC 9728).

    Nicht zu verwechseln mit der des MCP-Servers: die liegt unter
    ``/.well-known/oauth-protected-resource/mcp``, wird vom SDK erzeugt und
    existiert nur bei eingeschalteter KI-Schnittstelle. Dieses Dokument hier
    beschreibt die REST-API und ist immer da — sonst müsste ein Agent raten,
    wie er sich anmeldet, wenn MCP aus ist.

    ``authorization_servers`` bleibt bewusst leer, solange der MCP-Server aus
    ist: es gibt dann keinen erreichbaren Autorisierungsserver, und ein
    Verweis auf einen 404 wäre schlimmer als gar keiner.
    """
    from app.mcp import mount as mcp_mount

    base = _public_base_url(request)
    payload: dict[str, Any] = {
        "resource": f"{base}/api",
        "resource_name": "ConvoyPlan REST-API",
        "resource_documentation": f"{base}/api.md",
        "bearer_methods_supported": ["header"],
        "authorization_servers": [base] if mcp_mount.ist_aktiv() else [],
        "scopes_supported": list(scope_svc.SCOPES_SUPPORTED) if mcp_mount.ist_aktiv() else [],
        "authorization_details_types_supported": [],
        "tls_client_certificate_bound_access_tokens": False,
    }
    return JSONResponse(
        payload,
        headers={
            "Cache-Control": "public, max-age=300",
            "Access-Control-Allow-Origin": "*",
        },
    )
