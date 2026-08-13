"""Herkunft von Demo-Sitzungen — Grundlage der IP-Sperre.

Eine Zeile je Client-IP, die schon einmal eine Demo-Sitzung gestartet hat.
Bewusst *nicht* an die Demo-Organisation gekoppelt: die wird beim Ablauf vom
Retention-Job gelöscht, die Sperre muss den vollen Karenzzeitraum überdauern
(bei kurzer Sitzungslaufzeit ist die Org längst weg, wenn die Sperre noch
gilt). Umgekehrt räumt der Retention-Job diese Tabelle wieder auf, sobald die
Karenzzeit abgelaufen ist — die IP wird also nicht dauerhaft gespeichert
(DSGVO Art. 5(1)(e)).
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DemoOrigin(Base):
    """Letzter Demo-Start je Client-IP."""

    __tablename__ = "demo_origins"

    # Die IP ist der Schlüssel: ein gleichzeitiger zweiter Start derselben IP
    # scheitert damit an der Unique-Bedingung statt die Sperre zu unterlaufen.
    ip: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # Wie viele Demo-Sitzungen diese IP insgesamt gestartet hat — im Admin-Panel
    # der Hinweis darauf, ob jemand die Demo wiederholt nutzt.
    sessions: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
