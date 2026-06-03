import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ApiKey(Base):
    """An organization-scoped API key for programmatic access.

    Keys are created by superadmins and bound to a single organization. The
    plaintext key (``cvp_<prefix>_<secret>``) is shown only once at creation;
    only the ``prefix`` (a public lookup id) and a bcrypt hash of the secret are
    stored. A key acts within its organization with the configured ``role``
    (same hierarchy as user memberships).
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    # Public, non-secret lookup id embedded in the key (8 hex chars).
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    # bcrypt hash of the secret part — never the raw key.
    key_hash: Mapped[str] = mapped_column(String(255))
    # admin | planer | fahrer | beobachter
    role: Mapped[str] = mapped_column(String(30), default="beobachter")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    organization: Mapped["Organization"] = relationship()
