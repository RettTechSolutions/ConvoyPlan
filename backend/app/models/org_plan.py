"""Der Plan einer Organisation auf einer betriebenen Instanz (Hosting).

Der Lizenzschlüssel gilt für die **Instanz**. Auf einer gemeinsamen
Hosting-Instanz laufen aber viele Organisationen mit verschiedenen Paketen —
eine hat 25 Fahrzeuge gebucht, die nächste 150, eine dritte nur ein
Einsatz-Paket für vier Wochen. Das kann ein Instanzschlüssel nicht
ausdrücken, und signiert werden muss es auch nicht: die Instanz gehört dem,
der den Plan setzt.

Keine Zeile heißt **ohne Plan und ohne Grenzen**. Das ist der Normalfall auf
jeder selbst betriebenen Installation, und er darf durch ein Update nicht zu
„Grenze erreicht" werden.

Gespeichert werden die geltenden Werte, nicht nur der Name des Plans: ein
Angebot weicht vom Katalog ab (drei Fahrzeuge mehr, Laufzeit bis Quartalsende),
und eine spätere Änderung am Katalog soll bestehende Verträge nicht still
umschreiben.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OrganizationPlan(Base):
    __tablename__ = "organization_plans"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    # Schlüssel aus ``services/org_plan.KATALOG`` — zur Anzeige und als
    # Ausgangspunkt, nicht als Quelle der Grenzen.
    plan: Mapped[str] = mapped_column(String(30))
    # None = unbegrenzt.
    max_vehicles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_planners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Ortungsgeräte (Tracker); None = unbegrenzt — auch für jeden Plan, der
    # vor dieser Spalte gesetzt wurde (Migration 0059).
    max_trackers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Letzter Tag, an dem der Plan gilt; None = bis auf Weiteres (Vertrag).
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Freitext für den Betreiber (Angebotsnummer, Absprache). Sieht nur er.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    organization: Mapped["Organization"] = relationship()
