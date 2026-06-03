import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    """Append-only security audit trail.

    Records security-relevant events (logins, MFA changes, admin actions,
    license activation). Actor/org references are stored as plain UUIDs — not
    foreign keys — so the trail survives deletion of the referenced user or
    organisation (required for ISO 27001 A.8.15 / evidence integrity).
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
