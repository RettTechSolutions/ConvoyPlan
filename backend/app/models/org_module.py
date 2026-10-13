"""Freigabe eines Moduls für eine Organisation durch den Betreiber.

Eine Zeile je Organisation und Modul, für die der Superadmin ausdrücklich
entschieden hat. **Keine Zeile heißt Standard der Betriebsart**
(``services/org_module.standard``): selbst gehostet frei, auf dem
Hosting-Server gesperrt. Gespeichert wird deshalb ``freigegeben`` als Wert
und nicht die bloße Anwesenheit einer Zeile — sonst ließe sich auf einer
selbst betriebenen Instanz nichts sperren.

Was ein Modul ist und was es heißt, wenn es fehlt, steht in
``services/org_module.py``.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OrganizationModule(Base):
    __tablename__ = "organization_modules"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    # Schlüssel aus ``services/org_module.MODULE``. Ein Schlüssel, den der Code
    # nicht mehr kennt, wird ignoriert, nicht ausgewertet.
    modul: Mapped[str] = mapped_column(String(30), primary_key=True)
    freigegeben: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
