"""Kontaktdaten zu einer Demo-Sitzung — wer die Demo gestartet hat.

Bewusst eine eigene Tabelle und *nicht* der Demo-Benutzer: Die Demo-Org samt
Benutzer löscht der Retention-Job beim Ablauf, die Nachfrage-Mail geht aber
genau danach raus. Die Zeile muss die Sitzung also überleben.

Die angegebene Adresse landet deshalb auch nicht in `users.email` — dort steht
weiterhin die synthetische `demo-<hex>@demo.local`. Sonst kollidierte der
Demo-Zugang mit einem bestehenden Konto derselben Adresse (Unique-Constraint),
und ein Demo-Zugang wäre plötzlich unter einer echten Kennung anmeldbar.

Aufbewahrung: `RETENTION_DEMO_LEADS_DAYS` (Standard 180 Tage), danach räumt der
Retention-Job die Zeile ab — Interessentendaten sind kein Dauerbestand
(DSGVO Art. 5(1)(e)).
"""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def new_unsubscribe_token() -> str:
    """Zufälliges Token für den Abmeldelink in der Nachfrage-Mail."""
    return secrets.token_urlsafe(32)


class DemoLead(Base):
    """Eine Kontaktangabe beim Start einer Demo-Sitzung."""

    __tablename__ = "demo_leads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Die vom Besucher angegebene Adresse (normalisiert: getrimmt, klein).
    # Nicht eindeutig: dieselbe Adresse darf die Demo später erneut starten.
    email: Mapped[str] = mapped_column(String(255), index=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # SET NULL statt CASCADE: Wenn die Demo-Org abgeräumt wird, bleibt die
    # Kontaktangabe bestehen — sie ist der Anlass für die Nachfrage-Mail.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    # Der Code der Sitzung als Text, damit im Admin-Portal auch nach dem
    # Löschen der Org noch erkennbar ist, worauf sich der Kontakt bezieht.
    org_slug: Mapped[str] = mapped_column(String(80))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Kopie von Organization.demo_expires_at — der Auslöser für die
    # Nachfrage-Mail. Als Kopie, weil die Org zu diesem Zeitpunkt schon
    # gelöscht sein kann; wird bei Verlängerung/vorzeitigem Ende mitgeführt.
    session_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    followup_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Fehlversuche des Versands. Ohne Obergrenze liefe der Retention-Job bei
    # einer unzustellbaren Adresse stündlich in denselben Fehler.
    followup_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    followup_error: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Abmeldelink der Nachfrage-Mail (kein Opt-in-Häkchen beim Start, dafür ein
    # Widerspruch mit einem Klick).
    unsubscribe_token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=new_unsubscribe_token
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
