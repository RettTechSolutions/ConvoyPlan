import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OAuthCode(Base):
    """Ein kurzlebiger Autorisierungscode, ausgestellt nach der Zustimmung.

    Gespeichert wird nur der SHA-256-Hash des Codes. Bewusst *nicht* bcrypt
    wie bei ``ApiKey``: der Code ist ein 256-Bit-Zufallswert, kein Passwort.
    Gegen Raten hilft hier die Entropie, nicht die Rechenzeit — und der
    Token-Endpunkt muss den Code in einem Zugriff finden können, nicht über
    alle Zeilen hinweg vergleichen. Der Hash schützt gegen das, wogegen er
    schützen soll: einen Angreifer mit Lesezugriff auf die Datenbank.

    ``consumed_at`` setzt die Einmalverwendung durch. Ein zweiter Einlöse-
    versuch ist kein Bedienfehler, sondern das Signal für einen abgefangenen
    Code — er widerruft zusätzlich die aus diesem Code entstandene
    Token-Familie (siehe ``app/services/oauth_provider.py``).
    """

    __tablename__ = "oauth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), index=True
    )
    # Der zustimmende Benutzer und die von ihm gewählte Organisation. Das
    # Token, das aus diesem Code entsteht, gilt für genau diese eine Org.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    # Leerzeichengetrennt, wie im OAuth-Protokoll.
    scopes: Mapped[str] = mapped_column(String(255), default="")
    # PKCE (RFC 7636), ausschließlich S256 — "plain" wird nie akzeptiert.
    code_challenge: Mapped[str] = mapped_column(String(255))
    redirect_uri: Mapped[str] = mapped_column(Text)
    # Ob der Client die redirect_uri in der Autorisierungsanfrage mitgeschickt
    # hat. Wenn ja, muss sie beim Token-Tausch identisch wiederkommen.
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # RFC 8707: für welche Resource der Client das Token haben will. Wird
    # in die aud-Claim des Access-Tokens übernommen.
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Familie der aus diesem Code entstandenen Refresh-Tokens — damit ein
    # Replay des Codes die ganze Familie mitnehmen kann.
    family_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
