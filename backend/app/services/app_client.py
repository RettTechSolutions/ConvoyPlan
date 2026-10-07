"""Der fest eingebaute OAuth-Client der Begleit-App.

Die App (Repo Convoyplan-Companion) meldet sich über den Browser des Systems
an — ASWebAuthenticationSession bzw. Custom Tabs, OAuth 2.1 mit PKCE nach
RFC 8252. Ein nativer Passkey in der App bräuchte die Domain jeder Instanz in
den Associated Domains bzw. einer ``assetlinks.json`` im Store-Build, und
damit wären alle selbst betriebenen Instanzen ausgeschlossen. So bleibt der
Passkey bei der Webseite, und die App bekommt einen Code.

Drei Unterschiede zu einem MCP-Client, und alle drei sind Absicht:

**Im Code, nicht registriert.** Kein ``/register``, kein Secret
(``token_endpoint_auth_method: none``), PKCE Pflicht, genau eine Redirect-URI
mit eigenem Schema. ``oauth_provider.validate_redirect_uri`` lässt für
registrierte Clients weiterhin nur HTTPS und Loopback zu — das Schema hier
gilt für diesen einen Client und kommt nie aus einer Anfrage.

**Keine Zustimmung, aber eine Anmeldung.** Die App bekommt dieselben Rechte
wie die Webanmeldung in derselben Organisation, es gibt nichts auszuwählen.
Aber: ohne Zustimmungsschirm könnte jede fremde Seite den Browser eines
angemeldeten Menschen auf ``/authorize`` schicken, und der Code ginge an
welche App auch immer sich auf dem Gerät das Schema geschnappt hat. Deshalb
wird der Code nur ohne Rückfrage ausgestellt, wenn die Sitzung **in diesem
Ablauf** entstanden ist (``frisch_angemeldet``); eine ältere verlangt einen
Klick. Das entscheidet der Server, nicht ein Parameter der Seite.

**Tokens für die REST-API, nicht für ``/mcp``.** Ein Access-Token der App ist
ein gewöhnliches ConvoyPlan-Token (``typ="access"``), nur kurzlebig und mit
eigener Audience (``api_resource_url``). An ``/mcp`` ist es wertlos — dort
gilt nur ``typ="mcp"`` —, und ein MCP-Token ist umgekehrt an der REST-API
wertlos. Unabhängig vom MCP-Schalter und von der MCP-Richtlinie der
Organisation: die App ist keine KI-Schnittstelle.
"""
from datetime import datetime, timedelta, timezone

import jwt as _jwt
from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.oauth_client import AUTH_METHOD_NONE, OAuthClient
from app.models.organization import Organization
from app.models.user import User
from app.services import oauth_tokens

CLIENT_ID = "convoyplan-companion"
CLIENT_NAME = "ConvoyPlan-App"
REDIRECT_URI = "de.convoyplan.companion:/oauth"


def ist_app_client(client_id: str | None) -> bool:
    return client_id == CLIENT_ID


def aktiv() -> bool:
    return settings.app_oauth_enabled


def api_resource_url() -> str:
    """Die Audience der App-Tokens: die REST-API dieser Instanz.

    Nicht ``public_resource_url()`` — das ist ``/mcp``, und ein Token, das für
    beides gälte, verwischte genau die Trennung, an der die beiden
    Token-Prüfungen hängen."""
    return settings.app_base_url.rstrip("/") + "/api"


def client_information() -> OAuthClientInformationFull:
    """Was das SDK über diesen Client wissen muss."""
    return OAuthClientInformationFull(
        client_id=CLIENT_ID,
        client_secret=None,
        token_endpoint_auth_method=AUTH_METHOD_NONE,
        client_name=CLIENT_NAME,
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        # Keine Scopes: was die App darf, entscheidet wie im Web die Rolle in
        # der Organisation, bei jedem Aufruf neu (``deps.get_org_context``).
        scope=None,
    )


async def zeile_sicherstellen(db: AsyncSession) -> None:
    """Die Zeile in ``oauth_clients`` anlegen, falls sie fehlt.

    Gebraucht wird sie nur für die Fremdschlüssel von Codes und
    Refresh-Tokens. Angelegt beim ersten Code statt per Migration: so hängt
    nichts daran, ob jemand sie im Adminportal gelöscht hat."""
    await db.execute(
        insert(OAuthClient)
        .values(
            client_id=CLIENT_ID,
            client_name=CLIENT_NAME,
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            token_endpoint_auth_method=AUTH_METHOD_NONE,
            scope="",
        )
        .on_conflict_do_nothing(index_elements=["client_id"])
    )


def mint_access_token(*, user: User, org: Organization, role: str) -> tuple[str, int]:
    """Ein Access-Token der App. Gibt (Token, Gültigkeit in Sekunden).

    Dieselben Claims wie ``auth.create_token`` — die REST-API soll keinen
    zweiten Weg zur Organisation kennen —, dazu ``aud``, ``iss`` und
    ``client_id``. Die Rolle steht nur der Vollständigkeit halber darin:
    entschieden wird sie bei jedem Aufruf aus der Datenbank."""
    ttl = timedelta(minutes=settings.app_oauth_access_token_ttl_minutes)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "iat": now,
        "exp": now + ttl,
        "typ": "access",
        "aud": api_resource_url(),
        "iss": oauth_tokens.issuer_url(),
        "client_id": CLIENT_ID,
        "is_superadmin": False,
        "org_id": str(org.id),
        "org_slug": org.slug,
        "role": role,
        "tv": user.token_version,
    }
    return (
        _jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm),
        int(ttl.total_seconds()),
    )


def refresh_ttl() -> timedelta:
    return timedelta(days=settings.app_oauth_refresh_token_ttl_days)


def frisch_angemeldet(sitzung_iat: int | float | None, anfrage_iat: int | float | None) -> bool:
    """Ob die Sitzung erst in diesem Ablauf entstanden ist.

    ``anfrage_iat`` ist der Zeitpunkt, zu dem ``/authorize`` die Anfrage
    angenommen hat, ``sitzung_iat`` der der Anmeldung. Eine Sitzung ohne
    ``iat`` stammt von vor dieser Änderung und gilt als alt — im Zweifel ein
    Klick mehr, nicht einer weniger."""
    if sitzung_iat is None or anfrage_iat is None:
        return False
    return float(sitzung_iat) >= float(anfrage_iat)
