"""Der KI-Zugriff aus Sicht einer Organisation.

Der Betreiber der Instanz schaltet die Schnittstelle im Adminportal ein oder
aus — ob es ``/mcp`` überhaupt gibt, steht dort. Hier entscheidet der Admin
**einer Organisation**, ob seine Organisation daran teilnimmt, welchen
Ausschnitt der Fachdaten er dafür freigibt und ob es beim Lesen bleibt.

Beides ist nötig, weil es selten dieselbe Person ist. Wer eine Instanz für
mehrere BOS-Organisationen betreibt, entscheidet nicht über deren Daten; und
eine Organisation, die einen Assistenten anbinden will, soll dafür nicht den
Betreiber fragen müssen, sobald der die Schnittstelle einmal freigegeben hat.

Der Standard ist **aus**. Eine neu angelegte Organisation nimmt nicht teil,
auch auf einer Instanz, auf der die Schnittstelle längst läuft.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgCtx, get_org_context
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.mcp import areas
from app.mcp import scopes as scope_svc
from app.models.oauth_client import OAuthClient
from app.models.oauth_refresh_token import OAuthRefreshToken
from app.models.user import User
from app.services import audit, mcp_config, oauth_tokens, org_mcp_policy

router = APIRouter(prefix="/org/mcp", tags=["mcp"])

POLICY_UPDATED = "org.mcp.policy_updated"
CONNECTION_REVOKED = "org.mcp.connection_revoked"


def _require_admin(role: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(status_code=403, detail="Org-Adminrechte erforderlich")


class Wahlmoeglichkeit(BaseModel):
    """Ein anzukreuzendes Kästchen samt Beschriftung.

    Die Oberfläche bekommt die Liste vom Server statt sie selbst zu führen:
    ein neuer Bereich soll im Portal erscheinen, ohne dass jemand daran
    denkt, ihn in einem zweiten Repository nachzutragen."""

    wert: str
    label: str


class OrgMcpPolicyResponse(BaseModel):
    enabled: bool
    scopes: list[str]
    bereiche: list[str]
    # Ob überhaupt schon einmal etwas eingestellt wurde. Die Oberfläche
    # unterscheidet damit „bewusst abgeschaltet" von „nie angefasst".
    konfiguriert: bool
    # Der Schalter des Betreibers. Steht hier, damit das Portal nicht erklären
    # muss, warum eine freigegebene Organisation trotzdem nicht erreichbar
    # ist — das ist die häufigste Rückfrage, und sie hat eine Antwort.
    instanz_aktiv: bool
    verbindungs_url: str
    verfuegbare_scopes: list[Wahlmoeglichkeit]
    verfuegbare_bereiche: list[Wahlmoeglichkeit]
    # Der Scope, der nicht zur Wahl steht: ohne ihn käme keine Verbindung
    # zustande (siehe ``services/org_mcp_policy.BASIS_SCOPE``).
    basis_scope: str
    aktive_verbindungen: int
    updated_at: datetime | None = None


class OrgMcpPolicyUpdate(BaseModel):
    enabled: bool
    scopes: list[str] = Field(default_factory=list)
    bereiche: list[str] = Field(default_factory=list)


class OrgMcpConnection(BaseModel):
    family_id: uuid.UUID
    client_id: str
    client_name: str
    user_id: uuid.UUID
    user_email: str | None
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime


def _aktive_verbindungen():
    """Was als aktive Verbindung zählt — eine Token-*Familie*, kein Token.

    Dieselbe Bedingung wie im Adminportal (``api/routes/admin.py``). Sie steht
    hier ein zweites Mal ausgeschrieben, weil der Import von ``admin`` in eine
    Org-Route die Abhängigkeiten in die falsche Richtung drehte; dass beide
    dasselbe meinen, hält ``tests/test_org_mcp_policy.py`` fest."""
    return and_(
        OAuthRefreshToken.revoked.is_(False),
        OAuthRefreshToken.rotated_at.is_(None),
        OAuthRefreshToken.expires_at > datetime.now(timezone.utc),
    )


async def _antwort(db: AsyncSession, org_id: uuid.UUID) -> OrgMcpPolicyResponse:
    from app.models.org_mcp_policy import OrganizationMcpPolicy

    policy = await org_mcp_policy.fuer_org(db, org_id)
    zeile = await db.get(OrganizationMcpPolicy, org_id)
    verbindungen = await db.scalar(
        select(func.count(func.distinct(OAuthRefreshToken.family_id))).where(
            _aktive_verbindungen(), OAuthRefreshToken.organization_id == org_id
        )
    )
    return OrgMcpPolicyResponse(
        enabled=policy.enabled,
        scopes=list(policy.scopes),
        bereiche=list(policy.bereiche),
        konfiguriert=policy.gesetzt,
        instanz_aktiv=await mcp_config.is_mcp_enabled(db),
        verbindungs_url=oauth_tokens.public_resource_url(),
        verfuegbare_scopes=[
            Wahlmoeglichkeit(wert=s, label=scope_svc.SCOPE_LABELS.get(s, s))
            for s in scope_svc.ALL_SCOPES
        ],
        verfuegbare_bereiche=[
            Wahlmoeglichkeit(wert=b, label=areas.BEREICH_LABELS.get(b, b))
            for b in areas.ALL_BEREICHE
        ],
        basis_scope=org_mcp_policy.BASIS_SCOPE,
        aktive_verbindungen=verbindungen or 0,
        updated_at=zeile.updated_at if zeile else None,
    )


@router.get("", response_model=OrgMcpPolicyResponse)
async def read_policy(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> OrgMcpPolicyResponse:
    """Was diese Organisation über die KI-Schnittstelle hergibt."""
    _user, org, role = ctx
    _require_admin(role)
    return await _antwort(db, org.id)


@router.put("", response_model=OrgMcpPolicyResponse)
async def update_policy(
    data: OrgMcpPolicyUpdate,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> OrgMcpPolicyResponse:
    """Die Freigabe ändern.

    Wirkt sofort und auch auf **bestehende** Verbindungen: die Richtlinie wird
    bei jedem Werkzeugaufruf frisch gelesen (``app/mcp/context.py``). Ein
    zurückgenommener Bereich ist also mit dem nächsten Aufruf zu, ohne dass
    ein Token ablaufen oder jemand eine Verbindung trennen müsste.

    Abschalten trennt trotzdem nichts: die Verbindungen bleiben stehen und
    laufen ins Leere. Das ist die freundlichere Reihenfolge — wer versehentlich
    abschaltet, schaltet wieder ein, und der Assistent des Kollegen arbeitet
    weiter. Wer sie wirklich los sein will, trennt sie unten einzeln."""
    user, org, role = ctx
    _require_admin(role)

    vorher = await org_mcp_policy.fuer_org(db, org.id)
    nachher = await org_mcp_policy.setzen(
        db,
        org.id,
        enabled=data.enabled,
        scopes=data.scopes,
        bereiche=data.bereiche,
        actor_id=user.id,
    )
    await audit.record(
        db,
        POLICY_UPDATED,
        request=request,
        actor_id=user.id,
        actor_email=user.email,
        org_id=org.id,
        target_type="organization",
        target_id=str(org.id),
        detail={
            "vorher": {
                "enabled": vorher.enabled,
                "scopes": list(vorher.scopes),
                "bereiche": list(vorher.bereiche),
            },
            "nachher": {
                "enabled": nachher.enabled,
                "scopes": list(nachher.scopes),
                "bereiche": list(nachher.bereiche),
            },
        },
    )
    await db.commit()
    return await _antwort(db, org.id)


@router.get("/connections", response_model=list[OrgMcpConnection])
async def list_connections(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> list[OrgMcpConnection]:
    """Die aktiven Verbindungen **dieser** Organisation.

    Eine Zeile je erteilter Zustimmung. Bewusst auf die eigene Organisation
    eingegrenzt — die Übersicht über alle bleibt beim Betreiber."""
    _user, org, role = ctx
    _require_admin(role)

    query = (
        select(OAuthRefreshToken, OAuthClient.client_name, User.email)
        .join(OAuthClient, OAuthClient.client_id == OAuthRefreshToken.client_id)
        .join(User, User.id == OAuthRefreshToken.user_id, isouter=True)
        .where(_aktive_verbindungen(), OAuthRefreshToken.organization_id == org.id)
        .order_by(OAuthRefreshToken.created_at.desc())
    )
    return [
        OrgMcpConnection(
            family_id=token.family_id,
            client_id=token.client_id,
            # Selbstauskunft aus der Registrierung, ungeprüft. Registrieren
            # darf sich jeder — das ist der Sinn von DCR.
            client_name=client_name or "(ohne Namen)",
            user_id=token.user_id,
            user_email=user_email,
            scopes=token.scopes.split(),
            created_at=token.created_at,
            last_used_at=token.last_used_at,
            expires_at=token.expires_at,
        )
        for token, client_name, user_email in (await db.execute(query)).all()
    ]


@router.delete("/connections/{family_id}", status_code=204)
async def disconnect(
    family_id: uuid.UUID,
    request: Request,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Eine Verbindung dieser Organisation trennen.

    Die Prüfung auf die eigene Organisation steht **in der Abfrage**, nicht
    hinter ihr: eine fremde ``family_id`` findet hier nichts und bekommt ein
    404, statt zuerst geladen und dann abgelehnt zu werden.

    Ein bereits ausgegebenes Access-Token bleibt bis zu seinem Ablauf gültig
    (MCP_ACCESS_TOKEN_TTL_MINUTES, Standard 15 Minuten) — der Preis
    zustandsloser Tokens. Wer sofortige Wirkung braucht, nimmt die Freigabe
    zurück: die wird bei jedem Aufruf frisch gelesen."""
    user, org, role = ctx
    _require_admin(role)

    vorhanden = await db.scalar(
        select(func.count())
        .select_from(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.family_id == family_id,
            OAuthRefreshToken.organization_id == org.id,
        )
    )
    if not vorhanden:
        raise HTTPException(404, "Verbindung nicht gefunden")

    anzahl = await oauth_tokens.revoke_family(
        db, family_id, reason="Trennung durch die Organisation"
    )
    await audit.record(
        db,
        CONNECTION_REVOKED,
        request=request,
        actor_id=user.id,
        actor_email=user.email,
        org_id=org.id,
        target_type="oauth_connection",
        target_id=str(family_id),
        detail={"tokens": anzahl},
    )
    await db.commit()
