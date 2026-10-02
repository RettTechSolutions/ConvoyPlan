"""Öffentliche Aktionsseite und Positionsverlauf.

Eine Aktionsseite zeigt ausgewählte Konvois einer Organisation öffentlich —
verzögert, vergröbert und ohne Einsatzdetails. Ausgeliefert wird sie nicht
von hier, sondern von einer eigenen Anwendung (Convoyplan-EventTracker), die
``GET /api/public/aktion/{slug}`` mit dem Abruf-Token abholt. Was diese
Antwort enthalten darf, steht in ``services/aktionsseite.py``.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PublicTracker(Base):
    __tablename__ = "public_trackers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Freitext der Organisation („12 Lkw, rund 6 000 Päckchen") — nicht
    # berechnet, damit niemand aus der Seite die Ladung ableitet.
    facts: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme: Mapped[str] = mapped_column(String(20), default="neutral")
    delay_minutes: Mapped[int] = mapped_column(Integer)
    # Zielort als Punkt zeigen (vergröbert) — sonst nur der Text.
    show_destination: Mapped[bool] = mapped_column(Boolean, default=False)
    # Danach gibt es die Seite nicht mehr, und es wird nicht mehr aufgezeichnet.
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # SHA-256 des Abruf-Tokens. Das Token selbst sieht man nur beim Anlegen
    # und beim Erneuern; es ist zufällig und lang genug, dass ein schneller
    # Hash reicht (anders als ein Passwort).
    fetch_token_hash: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    convoys: Mapped[list["PublicTrackerConvoy"]] = relationship(
        back_populates="tracker",
        cascade="all, delete-orphan",
        order_by="PublicTrackerConvoy.position",
    )


class PublicTrackerConvoy(Base):
    __tablename__ = "public_tracker_convoys"

    tracker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_trackers.id", ondelete="CASCADE"), primary_key=True
    )
    convoy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("convoys.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # Öffentlicher Name. Intern heißt so etwas „KV 3 / Los B", draußen
    # „Konvoi Bosnien" — der Konvoiname geht nie hinaus.
    display_name: Mapped[str] = mapped_column(String(100))
    destination_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(9), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    tracker: Mapped[PublicTracker] = relationship(back_populates="convoys")


class VehiclePositionTrail(Base):
    """Verlauf der Positionen, ausgedünnt — nur für Konvois an einer aktiven
    Aktionsseite. Geschrieben ausschließlich von ``positionsverlauf.aufzeichnen``."""

    __tablename__ = "vehicle_position_trail"

    convoy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("convoys.id", ondelete="CASCADE"), primary_key=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
