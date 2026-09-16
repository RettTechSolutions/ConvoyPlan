import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OAuthRefreshToken(Base):
    """Ein rotierendes Refresh-Token.

    Nur der SHA-256-Hash liegt in der Datenbank (Begründung wie bei
    ``OAuthCode``). Jeder Einlöseversuch gibt ein neues Token aus und
    entwertet das alte.

    ``family_id`` verbindet alle Tokens, die aus derselben Zustimmung
    hervorgegangen sind. Taucht ein bereits rotiertes Token erneut auf, hat
    es jemand mitgelesen: dann stirbt die **ganze** Familie, nicht nur das
    vorgelegte Token. Das kostet den rechtmäßigen Benutzer eine erneute
    Anmeldung und dem Angreifer den Zugang — die richtige Seite des Tauschs.

    Access-Tokens stehen bewusst in keiner Tabelle: sie sind zustandslose
    JWTs mit kurzer Laufzeit. Ein Widerruf wirkt daher auf die Familie
    sofort und auf ein bereits ausgegebenes Access-Token erst mit dessen
    Ablauf (siehe ``settings.mcp_access_token_ttl``).
    """

    __tablename__ = "oauth_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scopes: Mapped[str] = mapped_column(String(255), default="")
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Gesetzt, sobald dieses Token rotiert wurde — ab dann ist es tot und
    # sein erneutes Auftauchen ein Diebstahlsignal.
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
