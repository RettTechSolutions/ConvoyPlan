"""Ortungsgeräte: feste Tracker im Fahrzeug (Repo ConvoyPlan-Tracker).

Ein Gerät gehört einer Organisation und ist mit höchstens einem Fahrzeug
gekoppelt; ein Fahrzeug hat höchstens ein Gerät. Es weist sich mit einem
Gerätetoken aus, das es beim Einrichten gegen einen Einmal-Code aus dem
Org-Admin tauscht. Beides liegt nur als SHA-256 vor, wie das Abruf-Token der
Aktionsseite: zufällig und lang genug, dass ein schneller Hash reicht.

Was das Gerät zuletzt gemeldet hat (Akku, Firmware, Signal, Zeitpunkt), steht
hier, damit der Org-Admin einen toten Tracker von einem stehenden Fahrzeug
unterscheiden kann. Die Regeln stehen in ``services/ortungsgeraet.py``.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Ortungsgeraet(Base):
    __tablename__ = "ortungsgeraete"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Ein Fahrzeug, ein Gerät — die Eindeutigkeit steht in der Datenbank, nicht
    # nur in der Prüfung beim Koppeln.
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(120))
    # stable | beta | nightly — der Firmware-Kanal des Geräts.
    kanal: Mapped[str] = mapped_column(String(20), default="stable", server_default="stable")
    # Gesperrt heißt: das Token gilt nicht mehr, das Gerät bekommt 401.
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Einmal-Code aus dem Org-Admin; verfällt mit dem Einlösen oder nach Ablauf.
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Gerätetoken; NULL, solange das Gerät nicht eingerichtet ist.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    eingerichtet_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Was das Gerät über sich sagt.
    hardware_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hardware: Mapped[str | None] = mapped_column(String(40), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(40), nullable=True)
    zuletzt_gesehen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    akku_prozent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extern: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Seit wann das Gerät ohne Bordnetz läuft: gesetzt bei der ersten Meldung
    # `extern=false` nach `true` oder ohne Vorwert, gelöscht mit `extern=true`
    # (``ortungsgeraet.akku_seit``). Serverzeit der Meldung, also „seit spätestens".
    akku_seit: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signal_dbm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Ergebnis des letzten Firmware-Updates: bestaetigt | zurueckgerollt | fehler.
    update_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    update_ergebnis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    update_meldung: Mapped[str | None] = mapped_column(String(200), nullable=True)
    update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vehicle: Mapped["Vehicle | None"] = relationship()
