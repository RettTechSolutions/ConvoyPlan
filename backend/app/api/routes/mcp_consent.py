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

from app.api.deps import get_current_person
from app.database import get_db
from app.mcp import scopes as scope_svc
from app.models.oauth_client import OAuthClient
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.services import audit, mcp_config, oauth_provider, oauth_tokens

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
    # Was die Rolle darüber hinaus hergäbe, der Client aber nicht verlangt
    # hat. Das Angebot existiert, weil nicht jeder Client nachfordern kann,
    # was er zunächst nicht angefragt hat: ChatGPT etwa liest die
    # ``scopes_supported`` der Resource und bleibt sonst bei dem, was es
    # beim Verbinden erfragt hat. Ohne dieses Feld wäre eine Verbindung für
    # immer lesend, obwohl die Rolle mehr hergibt.
    optional_scopes: list[str]


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
    # Die Beschriftungen zu den Scopes, die der Client *nicht* verlangt hat.
    # Welche davon eine Organisation tatsächlich hergibt, steht in
    # ``OrgChoice.optional_scopes`` — hier stehen nur die Texte dazu.
    optional_scopes: list[ScopeInfo]
    organizations: list[OrgChoice]
    # Wann die Anfrage verfällt. Der Benutzer soll nicht erst nach dem Klick
    # erfahren, dass er zu lange gebraucht hat.
    expires_at: datetime


class ConsentDecision(BaseModel):
    request: str
    approve: bool
    organization_id: uuid.UUID | None = None
    # Was der Benutzer angekreuzt hat. ``None`` heißt „keine Auswahl
    # getroffen" und erteilt das Angefragte — so verhalten sich ältere
    # Oberflächen und Tests weiter wie bisher. Die Auswahl kann nur
    # *innerhalb* der Rolle liegen; ``grantable()`` schneidet sie darauf
    # zurecht, nicht diese Zeile.
    scopes: list[str] | None = None


class ConsentResult(BaseModel):
    redirect_url: str


async def _require_enabled(db: AsyncSession) -> None:
    """Der *geltende* Zustand — Datenbank schlägt Umgebungsvariable.

    Stand hier ``settings.mcp_enabled``, also allein die Umgebungsvariable.
    Das war richtig, solange es den Schalter im Portal nicht gab; seither ist
    es falsch, und zwar auf die unangenehme Art: Der Consent-Router hängt
    nicht am Laufzeitschalter (``main.py`` montiert ihn fest, außerhalb von
    ``mcp_mount.mount``), er hat den Wechsel auf die Datenbank also nicht
    mitbekommen. Auf einer Instanz mit ``MCP_ENABLED=false`` in der ``.env``
    und dem Schalter im Portal auf „an" zeigte das Portal einen aktiven
    MCP-Server, während der Zustimmungsbildschirm mit 404 antwortete — der
    Verbindungsaufbau jedes Clients endete dort, für alle Benutzer."""
    if not await mcp_config.is_mcp_enabled(db):
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


async def _client_for(db: AsyncSession, authz: dict) -> OAuthClient:
    """Den Client der Anfrage laden und die Zieladresse gegenprüfen.

    Das Ticket ist signiert, die ``redirect_uri`` darin hat der Server also
    selbst hineingeschrieben, nachdem das SDK sie gegen die registrierten
    URIs geprüft hat. Trotzdem wird hier erneut geprüft, aus zwei Gründen:

    Erstens hängt die Zusage sonst allein an der Signatur — eine Eigenschaft
    drei Dateien entfernt, die beim nächsten Umbau niemand mehr im Blick hat.
    Eine ungeprüfte Weiterleitung auf genau dem Bildschirm, auf dem jemand
    Zugriff erteilt, ist die klassische Open-Redirect-Lücke (CWE-601).

    Zweitens kann sich die Registrierung zwischen Ausstellung und Einlösung
    des Tickets geändert haben. Wird eine URI entfernt oder der Client
    widerrufen, soll ein noch offener Consent-Screen nicht mehr dorthin
    zurückführen.
    """
    client = await db.get(OAuthClient, authz["client_id"])
    if client is None or client.revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unbekannter Client"
        )
    if authz["redirect_uri"] not in (client.redirect_uris or []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die Zieladresse ist für diesen Client nicht registriert",
        )
    return client


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
    user: User = Depends(get_current_person),
    db: AsyncSession = Depends(get_db),
) -> ConsentRequestInfo:
    """Worum der Client bittet — für die Anzeige auf dem Consent-Screen."""
    await _require_enabled(db)
    authz = _decode_or_400(request)

    client = await _client_for(db, authz)

    requested = authz.get("scopes") or list(scope_svc.REQUIRED_SCOPES)
    known = [s for s in scope_svc.ALL_SCOPES if s in set(requested)]
    weitere = [s for s in scope_svc.ALL_SCOPES if s not in set(known)]

    orgs = [
        OrgChoice(
            id=org.id,
            name=org.name,
            slug=org.slug,
            role=role,
            grantable_scopes=scope_svc.grantable(known, role),
            optional_scopes=scope_svc.grantable(weitere, role),
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
        optional_scopes=[
            ScopeInfo(scope=s, label=scope_svc.SCOPE_LABELS.get(s, s)) for s in weitere
        ],
        organizations=orgs,
        expires_at=datetime.fromtimestamp(authz["exp"], tz=timezone.utc),
    )


@router.post("/consent", response_model=ConsentResult)
async def decide_consent(
    decision: ConsentDecision,
    http_request: Request,
    user: User = Depends(get_current_person),
    db: AsyncSession = Depends(get_db),
) -> ConsentResult:
    """Zustimmen oder ablehnen; liefert die Redirect-URL zurück zum Client."""
    await _require_enabled(db)
    authz = _decode_or_400(decision.request)
    issuer = oauth_tokens.issuer_url()
    # Vor jeder Verzweigung: auch die Absage führt zu einer Weiterleitung und
    # darf deshalb nur an eine registrierte Adresse gehen.
    client = await _client_for(db, authz)

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

    requested = authz.get("scopes") or list(scope_svc.REQUIRED_SCOPES)
    # Die Auswahl des Benutzers schlägt die Anfrage des Clients — nach oben
    # wie nach unten. Nach unten ist das OAuth-Alltag (RFC 6749 §3.3: der
    # Server darf weniger erteilen als verlangt). Nach oben ist es der Punkt,
    # an dem ein Mensch einem Client mehr gibt, als der zu fragen wusste;
    # dass er es *wusste*, ist der Unterschied zu einer stillen Ausweitung,
    # und die Token-Antwort nennt dem Client den erteilten Umfang ohnehin.
    #
    # Die Rolle bleibt die Obergrenze: ``grantable()`` schneidet die Auswahl
    # auf das zurecht, was die Mitgliedschaft hergibt. Ein Client, der sich
    # hier ``convoy:write`` in die Anfrage schreibt, kommt damit bei einem
    # Beobachter keinen Schritt weiter.
    gewaehlt = requested if decision.scopes is None else decision.scopes
    granted = scope_svc.effective(gewaehlt, membership.role)
    if not granted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Die Rolle „{membership.role}“ in dieser Organisation gibt keinen "
                "der ausgewählten Zugriffe her"
            ),
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
