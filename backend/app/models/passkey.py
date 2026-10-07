"""Ein Passkey (WebAuthn-Zugangsdaten) eines Benutzers.

Gespeichert wird nur, was zum Prüfen einer Anmeldung nötig ist: die Kennung,
die das Gerät beim Anmelden nennt, und der öffentliche Schlüssel. Der private
Schlüssel verlässt das Gerät nie — ein Abzug dieser Tabelle ist deshalb, anders
als einer der Passwort-Hashes, für niemanden eine Anmeldung.

``sign_count`` ist der Zähler, den das Gerät bei jeder Anmeldung hochzählt.
Synchronisierte Passkeys (iCloud, Google) liefern dauerhaft 0; nur wo er
tatsächlich zählt, verrät ein Rückschritt einen geklonten Schlüssel
(``services/passkey.zaehler_ok``).
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Passkey(Base):
    __tablename__ = "passkeys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Wie das Gerät erreichbar ist (internal, hybrid, usb …) — nur ein Hinweis
    # an den Browser beim Anmelden, keine Sicherheitsangabe.
    transports: Mapped[list[str]] = mapped_column(JSON, default=list)
    name: Mapped[str] = mapped_column(String(100))
    # Synchronisiert (Passwortmanager, Cloud-Schlüsselbund) statt an ein Gerät
    # gebunden. Steht in der Liste, damit man weiß, was man löscht.
    backed_up: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
