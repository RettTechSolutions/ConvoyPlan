import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConvoyShareLink(Base):
    __tablename__ = "convoy_share_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    convoy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("convoys.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="track")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    convoy: Mapped["Convoy"] = relationship(back_populates="share_links")
