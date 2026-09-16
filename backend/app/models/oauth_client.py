import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Wie sich der Client am Token-Endpunkt ausweist. Ein öffentlicher Client
# (Claude Desktop, jede lokal laufende Anwendung) kann kein Geheimnis
# vertraulich halten und schützt den Austausch stattdessen per PKCE.
AUTH_METHOD_NONE = "none"
AUTH_METHOD_SECRET_POST = "client_secret_post"
AUTH_METHOD_SECRET_BASIC = "client_secret_basic"


class OAuthClient(Base):
    """Ein per Dynamic Client Registration (RFC 7591) registrierter MCP-Client.

    Registrieren darf sich jeder, der den Endpunkt erreicht — das ist der
    Sinn von DCR und der Grund, warum aus einer Registrierung *kein* Zugriff
    folgt: erst die Zustimmung eines angemeldeten Benutzers auf dem
    Consent-Screen bindet den Client an eine Organisation.

    Deshalb ist ``client_name`` frei wählbarer Text des Anfragenden und darf
    nirgends als vertrauenswürdige Angabe behandelt werden. Überprüft ist
    ausschließlich ``redirect_uris``: dorthin geht der Autorisierungscode,
    und nur eine exakt registrierte URI wird akzeptiert.
    """

    __tablename__ = "oauth_clients"

    # Vom Server vergeben (kein vom Client gewählter Wert), damit sich
    # niemand über die Registrierung eine fremde client_id aneignet.
    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Fernet-verschlüsseltes Client-Secret; NULL bei öffentlichen Clients
    # (token_endpoint_auth_method = "none"), die per PKCE arbeiten.
    #
    # Verschlüsselt und nicht gehasht wie bei ``ApiKey``, weil der Wert im
    # Klartext zurückgebraucht wird: das SDK vergleicht ihn am Token-Endpunkt
    # selbst (hmac.compare_digest). Dasselbe Muster wie ``User.mfa_secret``,
    # siehe app/services/crypto.py.
    client_secret_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Selbstauskunft des Anfragenden — siehe Klassendoku, ist NICHT geprüft.
    client_name: Mapped[str] = mapped_column(String(255), default="")
    # Liste exakt zulässiger Redirect-URIs. Keine Wildcards, kein Präfix-Match.
    redirect_uris: Mapped[list] = mapped_column(JSON, default=list)
    grant_types: Mapped[list] = mapped_column(JSON, default=list)
    token_endpoint_auth_method: Mapped[str] = mapped_column(
        String(40), default=AUTH_METHOD_NONE, server_default=AUTH_METHOD_NONE
    )
    # Leerzeichengetrennte Scope-Liste, um die der Client gebeten hat. Eine
    # Obergrenze des Wünschbaren, keine Zusage — was er tatsächlich bekommt,
    # entscheidet die Rolle des zustimmenden Benutzers.
    scope: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    client_secret_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    @staticmethod
    def new_client_id() -> str:
        return uuid.uuid4().hex
