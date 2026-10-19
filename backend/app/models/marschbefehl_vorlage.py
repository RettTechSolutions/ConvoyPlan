"""Word-Vorlage für den Marschbefehl einer Organisation.

Eine Zeile je Organisation; keine Zeile heißt: Export mit der Beispielvorlage
(``services/marschbefehl_vorlage.beispielvorlage``). Die Datei liegt als
``bytea`` in der Datenbank wie die Bilder der Aktionsseiten, also im Backup —
eine Vorlage, die nach einer Wiederherstellung fehlte, fiele erst im Einsatz auf.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarschbefehlVorlage(Base):
    __tablename__ = "marschbefehl_vorlagen"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    dateiname: Mapped[str] = mapped_column(String(200))
    groesse: Mapped[int] = mapped_column(Integer)
    daten: Mapped[bytes] = mapped_column(LargeBinary)
    hochgeladen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    hochgeladen_von_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
