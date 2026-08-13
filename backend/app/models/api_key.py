import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# Discriminates what a key may reach. Kept as a column rather than inferred
# from a NULL organization_id so the intent is explicit at every call site.
SCOPE_ORGANIZATION = "organization"
SCOPE_SYSTEM = "system"


class ApiKey(Base):
    """An API key for programmatic access, in one of two scopes.

    Keys are created by superadmins. The plaintext key
    (``cvp_<prefix>_<secret>``) is shown only once at creation; only the
    ``prefix`` (a public lookup id) and a bcrypt hash of the secret are stored.

    ``scope="organization"`` — bound to a single organization, acts within it
    with the configured ``role`` (same hierarchy as user memberships).

    ``scope="system"`` — not bound to any organization (``organization_id`` is
    NULL) and carries no org role. It grants read-only access to the
    instance-wide system metrics under ``/api/admin/system`` and nothing else,
    so a monitoring system can poll them without a superadmin login. ``role``
    is unused for these keys.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # NULL for system-scoped keys — they belong to the instance, not to a tenant.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # organization | system
    scope: Mapped[str] = mapped_column(
        String(20), default=SCOPE_ORGANIZATION, server_default=SCOPE_ORGANIZATION
    )
    name: Mapped[str] = mapped_column(String(120))
    # Public, non-secret lookup id embedded in the key (8 hex chars).
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    # bcrypt hash of the secret part — never the raw key.
    key_hash: Mapped[str] = mapped_column(String(255))
    # admin | planer | fahrer | beobachter — only meaningful for organization scope.
    role: Mapped[str] = mapped_column(String(30), default="beobachter")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    organization: Mapped["Organization | None"] = relationship()
