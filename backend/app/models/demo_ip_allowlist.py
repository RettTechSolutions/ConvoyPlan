"""Dauerhaft von der Demo-IP-Sperre ausgenommene Adressen.

Das Gegenstück zu `demo_origins`: Dort steht, wer gerade gesperrt ist, hier,
wer gar nicht erst gesperrt wird. Gedacht für Anschlüsse, hinter denen
planmäßig viele verschiedene Interessenten sitzen — Firmenanschluss, Messe-
oder Schulungs-WLAN, der eigene Vertrieb. Ohne diese Liste müsste dort nach
jeder Vorführung von Hand entsperrt werden.

Ein Eintrag ist entweder eine einzelne Adresse (`203.0.113.7`) oder ein Netz in
CIDR-Schreibweise (`203.0.113.0/24`, `2001:db8::/32`) — Letzteres, weil ein
Firmenanschluss selten auf eine feste Adresse festgelegt ist. Die Einträge
werden vom Superadmin gepflegt und nicht automatisch aufgeräumt: Sie sind
Konfiguration, keine erhobenen Daten.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DemoIpAllowlistEntry(Base):
    """Eine Adresse oder ein Netz, für das die Karenzzeit nicht gilt."""

    __tablename__ = "demo_ip_allowlist"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Normalisierte Schreibweise (siehe services.demo.normalize_ip_pattern):
    # Einzeladresse ohne Präfix, Netz als CIDR mit Netzadresse. Eindeutig,
    # damit derselbe Anschluss nicht mehrfach in der Liste landet.
    pattern: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Wozu die Ausnahme gehört — ohne Notiz weiß in einem Jahr niemand mehr,
    # warum ausgerechnet dieses Netz freigestellt ist.
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
