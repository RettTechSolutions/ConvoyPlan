"""Die Zustimmungsstrecke für den MCP-Zugang.

Der OAuth-Provider (``app/services/oauth_provider.py``) stellt selbst keinen
Autorisierungscode aus. Er schickt den Browser auf ``/oauth/consent`` im
Frontend und übergibt die Anfrage als kurzlebiges, signiertes Ticket. Erst
hier — mit einer gültigen ConvoyPlan-Sitzung, also inklusive MFA — entsteht
aus einer Zustimmung ein Code.

Damit hängt jedes MCP-Token an einer bewussten Handlung eines Menschen. Die
Registrierung eines Clients allein verschafft niemandem Zugriff.
"""
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from mcp.server.auth.provider import construct_redirect_uri
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.mcp import scopes as scope_svc
from app.models.oauth_client import OAuthClient
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.services import audit, oauth_provider, oauth_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

CONSENT_GRANTED = "mcp.consent.granted"
CONSENT_DENIED = "mcp.consent.denied"


class ScopeInfo(BaseModel):
    scope: str
    label: str


class OrgChoice(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str
    # Welche der angefragten Scopes diese Organisation hergibt. Eine Org, in
    # der der Benutzer nur beobachtet, kann kein Schreibrecht erteilen — das
    # soll er vor dem Klick sehen und nicht danach.
    grantable_scopes: list[str]


class ConsentRequestInfo(BaseModel):
    client_id: str
    # Selbstauskunft aus der Registrierung. Ungeprüft — siehe unten.
    client_name: str
    client_name_verified: bool
    # Der Host der registrierten Redirect-URI. Das Einzige an dieser Anfrage,
    # das tatsächlich überprüft wurde, und damit die einzige belastbare
    # Angabe darüber, wohin der Zugriff geht.
    redirect_host: str
    requested_scopes: list[ScopeInfo]
    organizations: list[OrgChoice]
    # Wann die Anfrage verfällt. Der Benutzer soll nicht erst nach dem Klick
    # erfahren, dass er zu lange gebraucht hat.
    expires_at: datetime


class ConsentDecision(BaseModel):
    request: str
    approve: bool
    organization_id: uuid.UUID | None = None


class ConsentResult(BaseModel):
    redirect_url: str


def _require_enabled() -> None:
    if not settings.mcp_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Der MCP-Zugang ist auf dieser Instanz nicht aktiviert",
        )


def _decode_or_400(ticket: str) -> dict:
    request = oauth_provider.decode_authorize_request(ticket)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die Autorisierungsanfrage ist ungültig oder abgelaufen — "
            "bitte im Client erneut starten",
        )
    return request


async def _memberships(db: AsyncSession, user: User) -> list[tuple[Organization, str]]:
    rows = (
        await db.execute(
            select(Organization, UserOrganization.role)
            .join(UserOrganization, UserOrganization.organization_id == Organization.id)
            .where(UserOrganization.user_id == user.id)
            .order_by(Organization.name)
        )
    ).all()
    return [(org, role) for org, role in rows]


@router.get("/consent", response_model=ConsentRequestInfo)
async def read_consent_request(
    request: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsentRequestInfo:
    """Worum der Client bittet — für die Anzeige auf dem Consent-Screen."""
    _require_enabled()
    authz = _decode_or_400(request)

    client = await db.get(OAuthClient, authz["client_id"])
    if client is None or client.revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannter Client"
        )

    requested = authz.get("scopes") or list(scope_svc.SCOPES_SUPPORTED)
    known = [s for s in scope_svc.ALL_SCOPES if s in set(requested)]

    orgs = [
        OrgChoice(
            id=org.id,
            name=org.name,
            slug=org.slug,
            role=role,
            grantable_scopes=scope_svc.grantable(known, role),
        )
        for org, role in await _memberships(db, user)
    ]

    return ConsentRequestInfo(
        client_id=client.client_id,
        client_name=client.client_name or "(ohne Namen)",
        # Immer False. Der Name stammt aus der Registrierung, und registrieren
        # darf sich jeder — das ist der Sinn von DCR. Das Feld existiert, damit
        # die Oberfläche den Namen gar nicht erst vertrauenswürdig darstellen
        # *kann*, und nicht als Platzhalter für eine spätere Prüfung.
        client_name_verified=False,
        redirect_host=_redirect_host(authz["redirect_uri"]),
        requested_scopes=[
            ScopeInfo(scope=s, label=scope_svc.SCOPE_LABELS.get(s, s)) for s in known
        ],
        organizations=orgs,
        expires_at=datetime.fromtimestamp(authz["exp"], tz=timezone.utc),
    )


@router.post("/consent", response_model=ConsentResult)
async def decide_consent(
    decision: ConsentDecision,
    http_request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsentResult:
    """Zustimmen oder ablehnen; liefert die Redirect-URL zurück zum Client."""
    _require_enabled()
    authz = _decode_or_400(decision.request)
    issuer = oauth_tokens.issuer_url()

    if not decision.approve:
        await audit.record(
            db,
            CONSENT_DENIED,
            request=http_request,
            actor_id=user.id,
            actor_email=user.email,
            target_type="oauth_client",
            target_id=authz["client_id"],
        )
        await db.commit()
        return ConsentResult(
            redirect_url=construct_redirect_uri(
                authz["redirect_uri"],
                error="access_denied",
                error_description="Der Benutzer hat die Anfrage abgelehnt",
                state=authz.get("state"),
                # RFC 9207 auch im Fehlerfall — der Client muss den Absender
                # einer Fehlerantwort genauso prüfen können wie den eines
                # Codes, sonst lässt sich ihm eine fremde Antwort unterschieben.
                iss=issuer,
            )
        )

    if decision.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bitte eine Organisation auswählen",
        )

    membership = (
        await db.execute(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.organization_id == decision.organization_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kein Mitglied dieser Organisation",
        )

    requested = authz.get("scopes") or list(scope_svc.SCOPES_SUPPORTED)
    granted = scope_svc.grantable(requested, membership.role)
    if not granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Die Rolle „{membership.role}“ in dieser Organisation gibt keinen "
                "der angefragten Zugriffe her"
            ),
        )

    client = await db.get(OAuthClient, authz["client_id"])
    if client is None or client.revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannter Client"
        )

    code = await oauth_provider.mint_authorization_code(
        db,
        request=authz,
        user_id=user.id,
        organization_id=decision.organization_id,
        scopes=granted,
    )
    await audit.record(
        db,
        CONSENT_GRANTED,
        request=http_request,
        actor_id=user.id,
        actor_email=user.email,
        org_id=decision.organization_id,
        target_type="oauth_client",
        target_id=authz["client_id"],
        detail={"scopes": granted, "client_name": client.client_name},
    )
    await db.commit()

    return ConsentResult(
        redirect_url=construct_redirect_uri(
            authz["redirect_uri"],
            code=code,
            state=authz.get("state"),
            iss=issuer,
        )
    )


def _redirect_host(raw: str) -> str:
    parsed = urlparse(raw)
    if not parsed.hostname:
        return raw
    if parsed.port:
        return f"{parsed.hostname}:{parsed.port}"
    return parsed.hostname
