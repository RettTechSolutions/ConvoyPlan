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

from fastapi import HTTPException

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db_session
from app.mcp import scopes as scope_svc
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.services import audit, rate_limit

logger = logging.getLogger(__name__)


class McpError(ToolError, ResourceError):
    """Ein vorhergesehener Fehler, der als Ergebnis beim Modell landet.

    Die Meldung ist für ein Sprachmodell geschrieben, nicht für einen Log:
    sie sagt, was fehlt und was stattdessen ginge, damit das Modell den
    nächsten Schritt wählen kann statt es erneut zu versuchen.

    Die Ableitung ist dabei nicht kosmetisch: das SDK behandelt jede andere
    Ausnahme als Absturz und ersetzt den Text durch ein nacktes „Error
    executing tool …". Die sorgfältig formulierte Meldung käme also nie an,
    und der Log bekäme einen Traceback für etwas, das kein Fehler des
    Servers ist.

    **Beide** Basisklassen sind nötig, weil das SDK Werkzeuge und Resources
    getrennt behandelt: die Werkzeugschicht lässt ``ToolError`` durch, die
    Resource-Schicht ``ResourceError`` — und was dort nicht passt, wird in
    ``UnexpectedResourceError`` verpackt, dessen Text nur die URI nennt.
    Mit nur ``ToolError`` kam die Absage einer Resource also als „Error
    creating resource from template …" an, und die Zugriffsprüfung stand
    im Log als Absturz. Beide leiten von ``MCPServerError`` ab, die
    Mehrfachvererbung ist daher geradlinig."""


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

    async def audit(
        self,
        tool: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Einen schreibenden Werkzeugaufruf im Audit-Log festhalten.

        Jeder Schreibaufruf, ausnahmslos. Wer später nachvollziehen muss, wie
        eine Marschkolonne zu ihrer Route kam, muss sehen können, ob ein
        Mensch im Portal oder ein Modell über diese Schnittstelle gehandelt
        hat — und über welchen Client."""
        await audit.record(
            self.db,
            audit.MCP_TOOL_CALL,
            actor_id=self.user.id,
            actor_email=self.user.email,
            org_id=self.organization.id,
            target_type=target_type,
            target_id=target_id,
            detail={
                "source": audit.SOURCE_MCP,
                "tool": tool,
                "client_id": self.client_id,
                **(detail or {}),
            },
        )

    def spend(self, bucket: str, limit: int, *, window_seconds: int = 3600) -> None:
        """Ein Kontingent belasten, das eine Fremdleistung kostet.

        Die REST-API schützt GraphHopper und HERE über FastAPI-Dependencies
        (``app/api/quota.py``); im MCP-Pfad greifen die nicht. Gezählt wird
        deshalb hier, aber gegen **dieselben** ``QUOTA_*``-Einstellungen —
        zwei Zahlenwelten für dasselbe Kontingent wären eine Einladung zum
        Auseinanderlaufen.

        Der Schlüssel enthält den Benutzer, nicht das Token: wer sich ein
        zweites Token holt, bekommt dadurch kein zweites Budget."""
        if not settings.rate_limit_enabled:
            return
        retry_after = rate_limit.check(
            f"mcp:{bucket}:{self.user.id}", limit, window_seconds, record=True
        )
        if retry_after is not None:
            raise McpError(
                f"Das Kontingent für „{bucket}“ ist für diese Stunde aufgebraucht "
                f"(Grenze: {limit}). Es steht in etwa {retry_after // 60 + 1} Minuten "
                "wieder zur Verfügung. Bereits vorhandene Daten lassen sich "
                "weiterhin lesen."
            )

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


def translate(exc: HTTPException) -> McpError:
    """Eine ``HTTPException`` der wiederverwendeten Route in einen
    Werkzeugfehler übersetzen.

    Die schreibenden Werkzeuge rufen dieselben Funktionen auf, die auch hinter
    der REST-API stehen — genau eine Implementierung je Operation, damit eine
    künftige Korrektur dort nicht am MCP-Pfad vorbeigeht. Diese Funktionen
    melden Fehler als ``HTTPException``; das Modell sieht davon nur den Text,
    also wird er hier mit dem übernommen, was er bedeutet."""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    if exc.status_code == 403:
        return McpError(f"Nicht erlaubt: {detail}")
    if exc.status_code == 404:
        return McpError(f"Nicht gefunden: {detail}")
    if exc.status_code == 409:
        return McpError(f"Widerspruch zum aktuellen Stand: {detail}")
    if exc.status_code == 402:
        return McpError(
            "Ohne gültige Lizenz sind über diese Schnittstelle nur lesende "
            "Zugriffe möglich."
        )
    return McpError(detail)


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

    # Obergrenze je Verbindung. Absichtlich hier und nicht nur bei den
    # schreibenden Werkzeugen: ein Modell, das sich in einer Schleife
    # festgefahren hat, liest genauso stur, wie es schreibt.
    if settings.rate_limit_enabled:
        retry_after = rate_limit.check(
            f"mcp:calls:{token.client_id}:{user_id}",
            settings.mcp_tool_calls_per_minute,
            60,
            record=True,
        )
        if retry_after is not None:
            raise McpError(
                "Zu viele Werkzeugaufrufe in kurzer Folge "
                f"(Grenze: {settings.mcp_tool_calls_per_minute} pro Minute). "
                f"In {retry_after} Sekunden geht es weiter — bitte nicht in einer "
                "Schleife wiederholen, sondern die bisherigen Ergebnisse auswerten."
            )

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
