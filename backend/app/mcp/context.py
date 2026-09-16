"""Vom MCP-Token zum Organisationskontext.

Das Gegenstück zu ``app/api/deps.py::get_org_context`` für den MCP-Pfad. Es
gibt dieselbe ``OrgCtx`` zurück, die alle bestehenden Zugriffsprüfungen
erwarten (``app/api/guards.py``), damit im MCP-Server keine zweite
Berechtigungslogik entsteht.
"""
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.mcp import scopes as scope_svc
from app.models.organization import Organization, UserOrganization
from app.models.user import User

logger = logging.getLogger(__name__)


class McpError(ToolError):
    """Ein vorhergesehener Fehler, der als Tool-Ergebnis beim Modell landet.

    Die Meldung ist für ein Sprachmodell geschrieben, nicht für einen Log:
    sie sagt, was fehlt und was stattdessen ginge, damit das Modell den
    nächsten Schritt wählen kann statt es erneut zu versuchen.

    Die Ableitung von ``ToolError`` ist dabei nicht kosmetisch: das SDK
    behandelt jede andere Ausnahme als Absturz und ersetzt den Text durch
    ein nacktes „Error executing tool …". Die sorgfältig formulierte
    Meldung käme also nie an, und der Log bekäme einen Traceback für etwas,
    das kein Fehler des Servers ist."""


@dataclass
class McpContext:
    user: User
    organization: Organization
    role: str
    scopes: list[str]
    client_id: str
    db: AsyncSession

    @property
    def org_ctx(self) -> tuple[User, Organization, str]:
        """Die OrgCtx, die guards.py und die Services erwarten."""
        return (self.user, self.organization, self.role)

    def require(self, scope: str) -> None:
        """Einen Scope erzwingen.

        Die Prüfung berücksichtigt die Scope-Hierarchie — wer schreiben darf,
        darf auch lesen."""
        if not scope_svc.satisfies(self.scopes, scope):
            raise McpError(
                f"Dieser Zugriff erfordert die Berechtigung „{scope}“ "
                f"({scope_svc.SCOPE_LABELS.get(scope, scope)}). "
                f"Die aktuelle Verbindung hat nur: {', '.join(self.scopes) or '(keine)'}. "
                "Die Verbindung muss im ConvoyPlan-Portal mit erweiterten "
                "Rechten neu erteilt werden."
            )


@asynccontextmanager
async def mcp_context():
    """Den Kontext des laufenden Tool-Aufrufs herstellen.

    Der ``AccessToken`` kommt aus der Middleware-Kette des SDK; Benutzer,
    Organisation und Rolle werden bei **jedem** Aufruf frisch aus der
    Datenbank gelesen. Das ist Absicht: eine entzogene Mitgliedschaft oder
    eine herabgestufte Rolle wirkt damit sofort und nicht erst, wenn das
    Token abläuft."""
    token = get_access_token()
    if token is None:
        # Sollte nie passieren — RequireAuthMiddleware lässt nichts ohne
        # Token durch. Fail-closed statt sich darauf zu verlassen.
        raise McpError("Nicht authentifiziert.")

    org_id = None
    user_id = None
    try:
        user_id = uuid.UUID(token.subject) if token.subject else None
        claims = token.claims or {}
        raw_org = claims.get("org_id")
        org_id = uuid.UUID(raw_org) if raw_org else None
    except (TypeError, ValueError):
        raise McpError("Das Zugriffstoken ist beschädigt.")

    if user_id is None or org_id is None:
        raise McpError("Das Zugriffstoken nennt keine Organisation.")

    async with get_db_session() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            raise McpError("Das Benutzerkonto ist nicht mehr aktiv.")

        organization = await db.get(Organization, org_id)
        if organization is None:
            raise McpError("Die Organisation existiert nicht mehr.")

        membership = (
            await db.execute(
                select(UserOrganization).where(
                    UserOrganization.user_id == user_id,
                    UserOrganization.organization_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            raise McpError(
                "Das Benutzerkonto ist nicht mehr Mitglied dieser Organisation."
            )

        # Die Scopes fallen auf das zurück, was die *aktuelle* Rolle hergibt.
        effective = scope_svc.grantable(token.scopes, membership.role)

        yield McpContext(
            user=user,
            organization=organization,
            role=membership.role,
            scopes=effective,
            client_id=token.client_id,
            db=db,
        )
