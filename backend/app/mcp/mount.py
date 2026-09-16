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
from app.mcp import WRITE_TOOLS
from app.mcp import scopes as scope_svc
from app.mcp import resources as mcp_resources
from app.mcp import subscriptions as mcp_subs
from app.mcp import tools_read, tools_write
from app.middleware.license_guard import is_licensed
from app.services import oauth_tokens
from app.services.oauth_provider import ConvoyPlanOAuthProvider

logger = logging.getLogger(__name__)

MCP_PATH = "/mcp"

# Wird beim Montieren gesetzt und vom Lifespan gebraucht.
_session_manager: StreamableHTTPSessionManager | None = None


def _tool_name(tool) -> str | None:
    """Der Name eines Werkzeugs, gleich ob als dict oder als Modell."""
    if isinstance(tool, dict):
        return tool.get("name")
    return getattr(tool, "name", None)


class StepUpScopeMiddleware:
    """Beantwortet einen Werkzeugaufruf ohne ausreichende Rechte mit 403.

    Die Spec verlangt bei zu schmalen Rechten eine **HTTP**-Antwort: 403 mit
    ``error="insufficient_scope"`` und den nötigen Scopes im
    ``WWW-Authenticate``-Header. Ein kompatibler Client autorisiert daraufhin
    von sich aus nach — der Benutzer muss die Verbindung nicht von Hand neu
    erteilen.

    Das lässt sich nicht aus dem Werkzeug heraus erzeugen: dort läuft bereits
    eine HTTP-Anfrage, deren Status längst gesendet ist. Die Prüfung muss also
    **vor** den Transport, und dafür muss der Rumpf der Anfrage gelesen
    werden. Er wird gepuffert und unverändert weitergereicht — ein ASGI-Server
    liefert ihn nur einmal.

    Die Prüfung im Werkzeug (``ctx.require()``) bleibt bestehen und ist die
    maßgebliche: hier geht es um die *protokollgerechte Form* der Absage, nicht
    um die Absage selbst. Fällt diese Schicht aus, lehnt das Werkzeug
    weiterhin ab — nur eben ohne Challenge.
    """

    def __init__(self, app, resource_metadata_url) -> None:
        self.app = app
        self.resource_metadata_url = resource_metadata_url

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        body, replay = await _buffer_body(receive)
        fehlend = self._fehlender_scope(scope, body)
        if fehlend is None:
            await self.app(scope, replay, send)
            return

        await _send_insufficient_scope(send, fehlend, self.resource_metadata_url)

    def _fehlender_scope(self, scope, body: bytes) -> str | None:
        """Den fehlenden Scope bestimmen, oder None wenn alles passt.

        Fail-open per Absicht: was hier nicht eindeutig als Werkzeugaufruf
        mit zu schmalen Rechten erkennbar ist, geht durch — und trifft dann
        auf die Prüfung im Werkzeug. Diese Schicht darf nichts *zusätzlich*
        verbieten, sie darf nur früher und präziser ablehnen."""
        credentials = scope.get("auth")
        if credentials is None:
            return None
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            return None
        # Ein Stapel mehrerer Aufrufe wird nicht zerlegt — die Challenge
        # gälte dann für einen von mehreren, und das Protokoll sieht dafür
        # keine Form vor.
        if not isinstance(payload, dict) or payload.get("method") != "tools/call":
            return None
        name = (payload.get("params") or {}).get("name")
        if not isinstance(name, str):
            return None
        benoetigt = scope_svc.required_for_tool(name)
        if benoetigt is None:
            return None
        if scope_svc.satisfies(list(credentials.scopes), benoetigt):
            return None
        return benoetigt


async def _buffer_body(receive):
    """Den Anfragerumpf einlesen und ein receive liefern, das ihn erneut gibt."""
    teile: list[bytes] = []
    nachrichten: list[dict] = []
    while True:
        nachricht = await receive()
        nachrichten.append(nachricht)
        if nachricht["type"] != "http.request":
            break
        teile.append(nachricht.get("body", b""))
        if not nachricht.get("more_body", False):
            break

    index = 0

    async def replay():
        nonlocal index
        if index < len(nachrichten):
            nachricht = nachrichten[index]
            index += 1
            return nachricht
        return await receive()

    return b"".join(teile), replay


async def _send_insufficient_scope(send, benoetigt: str, resource_metadata_url) -> None:
    """Die Scope-Challenge nach RFC 6750 §3.1 senden.

    Alle für die Operation nötigen Scopes in **einer** Challenge: inkrementell
    nachzufordern kostet eine Autorisierungsrunde pro Scope und damit den
    Benutzer je einen Klick zu viel. Weil unsere Scopes hierarchisch sind,
    genügt der breiteste — er schließt die schmaleren ein."""
    beschreibung = (
        f"Dieser Zugriff erfordert {benoetigt} "
        f"({scope_svc.SCOPE_LABELS.get(benoetigt, benoetigt)})"
    )
    teile = [
        'error="insufficient_scope"',
        f'error_description="{beschreibung}"',
        f'scope="{benoetigt}"',
    ]
    if resource_metadata_url:
        teile.append(f'resource_metadata="{resource_metadata_url}"')

    rumpf = json.dumps(
        {"error": "insufficient_scope", "error_description": beschreibung}
    ).encode()
    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(rumpf)).encode()),
            (b"www-authenticate", f"Bearer {', '.join(teile)}".encode()),
        ],
    })
    await send({"type": "http.response.body", "body": rumpf})


class LicenseGatedToolsMiddleware:
    """Blendet die schreibenden Werkzeuge aus, solange keine Lizenz vorliegt.

    Der MCP-Server verhält sich damit wie die REST-API im Demo-Modus: lesen
    ja, schreiben nein. Nur zeigt er die schreibenden Werkzeuge gar nicht
    erst an, statt sie anzubieten und beim Aufruf abzulehnen — ein Modell,
    das ein Werkzeug sieht, probiert es aus, und eine Absage nach dem
    Versuch ist eine schlechtere Auskunft als ein Werkzeug, das es nicht gibt.

    Geprüft wird bei **jeder** Auflistung, nicht einmalig beim Start: eine
    Lizenz lässt sich im Admin-Portal zur Laufzeit hinterlegen, und dann soll
    die nächste Verbindung sie sehen, ohne dass jemand den Dienst neu startet.
    ``is_licensed()`` hält dafür einen stündlichen Cache vor, der Aufruf
    kostet also im Normalfall nichts.
    """

    async def __call__(self, ctx, call_next):
        result = await call_next(ctx)
        if ctx.method != "tools/list":
            return result
        if await is_licensed():
            return result

        # Auf dieser Ebene reicht das Ergebnis als rohes dict durch, nicht als
        # ListToolsResult — die Modellvalidierung passiert erst danach. Beide
        # Formen werden bedient, damit ein Umbau im SDK hier nicht still
        # aufhört zu filtern, sondern höchstens am Test bricht.
        if isinstance(result, dict):
            tools = result.get("tools")
            if tools is None:
                return result
            result["tools"] = [t for t in tools if _tool_name(t) not in WRITE_TOOLS]
            return result

        tools = getattr(result, "tools", None)
        if tools is None:
            return result
        result.tools = [t for t in tools if _tool_name(t) not in WRITE_TOOLS]
        return result


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
        middleware=[LicenseGatedToolsMiddleware()],
        # Der eigene Bus statt des mitgelieferten: der ``ListenHandler`` des
        # SDK honoriert jede angefragte Resource-URI ohne Prüfung. Die
        # Mandantentrennung in der Zustellung steckt deshalb im Bus — siehe
        # app/mcp/subscriptions.py.
        subscriptions=mcp_subs.bus(),
    )
    tools_read.register(mcp)
    tools_write.register(mcp)
    mcp_resources.register(mcp)
    mcp_subs.register(mcp)
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
    # Client ID Metadata Documents ankündigen, sobald sie eingeschaltet sind.
    # Ohne die Angabe versucht es kein Client, und die Funktion läge brach.
    if settings.mcp_allow_cimd:
        metadata.client_id_metadata_document_supported = True
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
    # Live-Meldungen der Fahrzeugverfolgung in Abo-Ereignisse übersetzen.
    mcp_subs.attach_tracking()
    auth_settings = mcp.settings.auth
    assert auth_settings is not None and auth_settings.resource_server_url is not None

    provider = ConvoyPlanOAuthProvider()
    verifier = ConvoyPlanTokenVerifier()

    _session_manager = StreamableHTTPSessionManager(app=mcp._lowlevel_server)

    # Transport: Authentication außen, AuthContext darunter, RequireAuth
    # innen — dieselbe Reihenfolge, die das SDK auf App-Ebene herstellt.
    resource_metadata_url = build_resource_metadata_url(auth_settings.resource_server_url)
    endpoint = AuthenticationMiddleware(
        AuthContextMiddleware(
            ScopeAnnouncingAuthMiddleware(
                # Die Step-up-Prüfung sitzt innerhalb von RequireAuth: erst
                # muss überhaupt ein gültiges Token vorliegen (401), dann
                # entscheidet sie über die Breite seiner Rechte (403).
                StepUpScopeMiddleware(
                    StreamableHTTPASGIApp(_session_manager), resource_metadata_url
                ),
                auth_settings.required_scopes or [],
                resource_metadata_url,
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
