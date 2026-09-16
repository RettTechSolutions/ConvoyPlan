"""ASGI-Verdrahtung des MCP-Servers in die FastAPI-App.

Die Form hier ist das Ergebnis eines Spikes (Plan ``2026-09-16-mcp-server``,
Task 0.1) und weicht bewusst von dem ab, was das SDK als bequemen Weg
anbietet. Zwei Gründe, beide gemessen und nicht vermutet:

**Kein ``Mount`` für den Transport.** ``MCPServer.streamable_http_app()``
registriert den Endpunkt als ``Route``, nicht als ``Mount``. Hängt man die
zurückgegebene Starlette-App unter ``/mcp`` ein, beantwortet ``POST /mcp``
die Anfrage mit einem ``307`` auf ``/mcp/`` — Starlette ergänzt den
Schrägstrich. Die kanonische Resource-URI trägt aber keinen (RFC 8707), und
eine Umleitung auf jedem Aufruf ist weder spec-konform noch robust. Deshalb
eine echte ``Route`` und die Middleware-Kette von Hand darum herum.

**Die Auth-Middleware gehört um den Endpunkt, nicht an die App.** Läge sie
auf App-Ebene, ginge jeder ``Authorization``-Header auf ``/api/*`` durch den
MCP-Token-Verifier — ein ganz normaler ConvoyPlan-Login würde dort geprüft
und abgelehnt. Die Kette umschließt deshalb nur ``/mcp``.

**Der Session-Manager braucht den Lifespan.** Die vom SDK gebaute App trägt
ihn in ihrem eigenen Lifespan, und den führt Starlette für eine gemountete
Sub-App nicht aus. Ohne ``session_manager.run()`` in ConvoyPlans ``_lifespan``
scheitert der erste Request mit ``RuntimeError: Task group is not
initialized``. ``lifespan_context()`` unten ist genau dafür da.

Weil diese Verdrahtung an inneren Details des SDK hängt, ist ``mcp`` in
``requirements.txt`` exakt gepinnt und ``tests/test_mcp_auth.py`` prüft das
beobachtbare Verhalten — ein SDK-Sprung soll dort brechen und nicht in
Produktion.
"""
import contextlib
import json
import logging

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import (
    build_metadata,
    build_resource_metadata_url,
    cors_middleware,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.streamable_http_manager import (
    StreamableHTTPASGIApp,
    StreamableHTTPSessionManager,
)
from pydantic import AnyHttpUrl
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Route
from starlette.types import Send

from app.config import settings
from app.database import get_db_session
from app.mcp import scopes as scope_svc
from app.mcp import tools_read
from app.services import oauth_tokens
from app.services.oauth_provider import ConvoyPlanOAuthProvider

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"

# Wird beim Montieren gesetzt und vom Lifespan gebraucht.
_session_manager: StreamableHTTPSessionManager | None = None


class ScopeAnnouncingAuthMiddleware(RequireAuthMiddleware):
    """Wie ``RequireAuthMiddleware``, aber mit ``scope`` in der Challenge.

    Die Spec sagt, der Server **SHOULD** im ``WWW-Authenticate``-Header
    nennen, welche Scopes er braucht — sonst muss ein Client raten oder
    vorsichtshalber alles anfordern, was dem Prinzip der geringsten Rechte
    zuwiderläuft. Das SDK lässt das Feld weg; hier kommt es dazu.

    Die Spec verlangt außerdem alle für die Operation nötigen Scopes in
    **einer** Challenge: inkrementell nachzufordern kostet eine
    Autorisierungsrunde pro Scope und damit den Benutzer einen Klick zu viel.
    """

    async def _send_auth_error(
        self, send: Send, status_code: int, error: str, description: str
    ) -> None:
        parts = [f'error="{error}"', f'error_description="{description}"']
        if self.required_scopes:
            parts.append(f'scope="{" ".join(self.required_scopes)}"')
        if self.resource_metadata_url:
            parts.append(f'resource_metadata="{self.resource_metadata_url}"')

        body = json.dumps({"error": error, "error_description": description}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", f"Bearer {', '.join(parts)}".encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class ConvoyPlanTokenVerifier(TokenVerifier):
    """Prüft ein präsentiertes Bearer-Token als MCP-Token.

    Akzeptiert ausschließlich ``typ="mcp"``. Ein ConvoyPlan-Access-Token ist
    hier damit wertlos — und umgekehrt weist ``app/api/deps.py`` ein
    MCP-Token an der REST-API ab. Beide Richtungen hängen an einer Prüfung,
    nicht an einer Konvention."""

    async def verify_token(self, token: str) -> AccessToken | None:
        async with get_db_session() as db:
            verified = await oauth_tokens.verify_access_token(db, token)
        if verified is None:
            return None
        return AccessToken(
            token=token,
            client_id=verified.client_id,
            scopes=verified.scopes,
            expires_at=verified.expires_at,
            resource=verified.resource,
            subject=str(verified.user_id),
            claims={"org_id": str(verified.organization_id)},
        )


def build_server() -> MCPServer:
    """Den MCP-Server aufbauen und die Werkzeuge anmelden."""
    resource_url = AnyHttpUrl(oauth_tokens.public_resource_url())
    auth_settings = AuthSettings(
        issuer_url=AnyHttpUrl(oauth_tokens.issuer_url()),
        resource_server_url=resource_url,
        # Der minimale Satz für die Grundfunktion. Breitere Scopes fordert
        # der Client per Step-up nach — so will es die Scope-Minimierung
        # der Spec.
        required_scopes=list(scope_svc.SCOPES_SUPPORTED),
        # RFC 8707: ein Token, das für eine andere Instanz ausgestellt wurde,
        # wird hier abgelehnt.
        validate_token_resource=True,
        client_registration_options=ClientRegistrationOptions(
            enabled=settings.mcp_allow_dcr,
            # Was ein Client bei der Registrierung überhaupt in seine
            # Speisekarte schreiben darf. Das ist **keine** Zusage: was er
            # am Ende bekommt, schneidet die Rolle des zustimmenden
            # Benutzers zu (siehe scopes.grantable).
            valid_scopes=list(scope_svc.ALL_SCOPES),
            # Nennt ein Client bei der Registrierung keine Scopes, darf er
            # trotzdem später nach allen fragen — sonst käme er nie an
            # Schreibrechte heran, ohne sich neu zu registrieren. Fragt er
            # dann beim Autorisieren nach nichts Bestimmtem, bekommt er
            # weiterhin nur convoy:read (siehe provider.authorize).
            default_scopes=list(scope_svc.ALL_SCOPES),
        ),
        revocation_options=RevocationOptions(enabled=True),
    )

    mcp = MCPServer(
        "ConvoyPlan",
        title="ConvoyPlan",
        instructions=(
            "ConvoyPlan plant Marschkolonnen (Konvois) für BOS-Organisationen: "
            "Fahrzeuge, Wegpunkte, Routen, Marschbefehl und Live-Status. "
            "Alle Werkzeuge arbeiten innerhalb genau einer Organisation — "
            "derjenigen, für die diese Verbindung erteilt wurde."
        ),
        version=settings.app_version,
        token_verifier=ConvoyPlanTokenVerifier(),
        auth=auth_settings,
    )
    tools_read.register(mcp)
    return mcp


def _authorization_server_metadata_route(auth_settings: AuthSettings) -> Route:
    """Die AS-Metadata selbst bauen, um ``iss`` anzukündigen.

    Das SDK setzt ``authorization_response_iss_parameter_supported`` nicht.
    Ohne die Angabe darf ein Client ein fehlendes ``iss`` laut RFC 9207 §2.4
    nicht beanstanden — die Prüfung, die Mix-up-Angriffe verhindert, liefe
    dann ins Leere. Wir senden ``iss`` (siehe ``routes/mcp_consent.py``),
    also sagen wir es auch; eine kommende Spec-Revision hebt das ohnehin von
    SHOULD auf MUST.

    Gebaut statt nachträglich gepatcht, weil der fertige Handler in einer
    CORS-Hülle steckt und sich von außen nicht verlässlich erreichen lässt."""
    metadata = build_metadata(
        auth_settings.issuer_url,
        auth_settings.service_documentation_url,
        auth_settings.client_registration_options or ClientRegistrationOptions(),
        auth_settings.revocation_options or RevocationOptions(),
    )
    metadata.authorization_response_iss_parameter_supported = True
    return Route(
        "/.well-known/oauth-authorization-server",
        endpoint=cors_middleware(MetadataHandler(metadata).handle, ["GET", "OPTIONS"]),
        methods=["GET", "OPTIONS"],
    )


def mount(app: FastAPI) -> None:
    """Den MCP-Server in die FastAPI-App einhängen.

    Tut nichts, wenn ``MCP_ENABLED`` nicht gesetzt ist — dann existieren
    weder ``/mcp`` noch die Well-Known-Dokumente, und eine Bestandsinstallation
    verhält sich exakt wie vorher."""
    global _session_manager

    if not settings.mcp_enabled:
        logger.info("MCP: nicht aktiviert (MCP_ENABLED=false) — keine Routen montiert")
        return

    mcp = build_server()
    auth_settings = mcp.settings.auth
    assert auth_settings is not None and auth_settings.resource_server_url is not None

    provider = ConvoyPlanOAuthProvider()
    verifier = ConvoyPlanTokenVerifier()

    _session_manager = StreamableHTTPSessionManager(app=mcp._lowlevel_server)

    # Transport: Authentication außen, AuthContext darunter, RequireAuth
    # innen — dieselbe Reihenfolge, die das SDK auf App-Ebene herstellt.
    endpoint = AuthenticationMiddleware(
        AuthContextMiddleware(
            ScopeAnnouncingAuthMiddleware(
                StreamableHTTPASGIApp(_session_manager),
                auth_settings.required_scopes or [],
                build_resource_metadata_url(auth_settings.resource_server_url),
            )
        ),
        backend=BearerAuthBackend(
            verifier, resource_server_url=auth_settings.resource_server_url
        ),
    )
    # Ohne methods=, damit GET (SSE-Stream), POST (JSON-RPC) und DELETE
    # (Session beenden) alle auf denselben Endpunkt treffen.
    app.router.routes.append(Route(MCP_PATH, endpoint=endpoint))

    # OAuth- und Well-Known-Routen an der WURZEL. RFC 9728 verlangt die
    # Protected Resource Metadata unter /.well-known/oauth-protected-resource
    # plus dem Pfad der Resource — unterhalb von /api wäre sie unauffindbar.
    metadata_routes = create_protected_resource_routes(
        resource_url=auth_settings.resource_server_url,
        authorization_servers=[auth_settings.issuer_url],
        scopes_supported=list(scope_svc.SCOPES_SUPPORTED),
        resource_name="ConvoyPlan",
    )
    auth_routes = create_auth_routes(
        provider=provider,
        issuer_url=auth_settings.issuer_url,
        client_registration_options=auth_settings.client_registration_options,
        revocation_options=auth_settings.revocation_options,
    )
    # Die AS-Metadata des SDK durch die eigene mit iss-Ankündigung ersetzen.
    auth_routes = [
        r for r in auth_routes
        if getattr(r, "path", "") != "/.well-known/oauth-authorization-server"
    ]
    app.router.routes.extend(metadata_routes)
    app.router.routes.append(_authorization_server_metadata_route(auth_settings))
    app.router.routes.extend(auth_routes)

    logger.info(
        "MCP: montiert auf %s (Resource %s, DCR %s)",
        MCP_PATH,
        auth_settings.resource_server_url,
        "an" if settings.mcp_allow_dcr else "aus",
    )


@contextlib.asynccontextmanager
async def lifespan_context():
    """Den Session-Manager starten, solange die App läuft.

    Gehört in ConvoyPlans ``_lifespan``. Ohne das läuft die Task-Group des
    Transports nie an und der erste MCP-Request scheitert mit einem
    ``RuntimeError`` — laut, immerhin, aber eben kaputt."""
    if _session_manager is None:
        yield
        return
    async with _session_manager.run():
        yield
