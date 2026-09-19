"""Security audit logging.

`record()` writes an append-only entry and is intentionally defensive: a
logging failure must never break the request that triggered it.
"""

import logging
import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

# ── Action constants ──────────────────────────────────────────────────────────
LOGIN_SUCCESS = "auth.login.success"
LOGIN_FAILURE = "auth.login.failure"
MFA_ENABLED = "auth.mfa.enabled"
MFA_DISABLED = "auth.mfa.disabled"
PASSWORD_CHANGED = "auth.password.changed"
PASSWORD_RESET_REQUESTED = "auth.password.reset_requested"
USER_CREATED = "admin.user.created"
USER_DELETED = "admin.user.deleted"
USER_UPDATED = "admin.user.updated"
ORG_CREATED = "admin.org.created"
ORG_DELETED = "admin.org.deleted"
API_KEY_CREATED = "admin.api_key.created"
API_KEY_REVOKED = "admin.api_key.revoked"
LICENSE_ACTIVATED = "license.activated"
CONVOY_CREATED = "convoy.created"
CONVOY_UPDATED = "convoy.updated"
CONVOY_DELETED = "convoy.deleted"
SHARE_LINK_CREATED = "convoy.share_link.created"
SHARE_LINK_REVOKED = "convoy.share_link.revoked"
# Meldungen aus der Anwendung. Das Eingehen wird mitgeschrieben, weil der
# Melde-Dialog der einzige Weg ist, auf dem ein beliebiges Mitglied Text und
# ein Bild auf die Instanz legen kann — wer das missbraucht, soll auffindbar
# sein. Statuswechsel und Löschungen, weil sie fremde Aussagen betreffen.
FEEDBACK_SUBMITTED = "feedback.submitted"
FEEDBACK_UPDATED = "admin.feedback.updated"
FEEDBACK_DELETED = "admin.feedback.deleted"
# MCP: jeder schreibende Werkzeugaufruf. Ein eigener Präfix, damit sich im
# Audit-Log auf einen Blick trennen lässt, was ein Mensch im Portal getan hat
# und was ein Sprachmodell über die Schnittstelle. Für ein BOS-Produkt ist
# diese Unterscheidung keine Kür.
MCP_TOOL_CALL = "mcp.tool.call"
# Kennzeichnung in AuditLog.detail["source"]. Die Tabelle hat keine eigene
# Spalte dafür, und eine Migration nur für ein Wort wäre unverhältnismäßig —
# der Präfix der Aktion trägt die Information ohnehin doppelt.
SOURCE_MCP = "mcp"


def client_ip(request: Request | None) -> str | None:
    """Real client IP as reported by the Caddy reverse proxy.

    Caddy's reverse_proxy appends the connecting client's IP to the right of
    any existing X-Forwarded-For header rather than replacing it. Reading
    split(",")[0] (the leftmost entry) would be attacker-controlled: a client
    can send "X-Forwarded-For: fake-ip" and Caddy forwards it as
    "fake-ip, real-client-ip". Taking split(",")[-1] selects the entry Caddy
    itself added, which the client cannot forge.
    """
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()[:64]
    return request.client.host if request.client else None


async def record(
    db: AsyncSession,
    action: str,
    *,
    request: Request | None = None,
    actor_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    org_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    try:
        ua = request.headers.get("user-agent") if request else None
        entry = AuditLog(
            action=action,
            actor_id=actor_id,
            actor_email=actor_email,
            org_id=org_id,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=client_ip(request),
            user_agent=ua[:512] if ua else None,
            detail=detail,
        )
        db.add(entry)
        await db.commit()
    except Exception:
        logger.warning("Audit record failed for action=%s", action, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
