import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Waypoint(Base):
    __tablename__ = "waypoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    convoy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("convoys.id"))
    name: Mapped[str] = mapped_column(String(100))
    # waypoint | stop | checkpoint | technical_stop
    type: Mapped[str] = mapped_column(String(30), default="waypoint")
    location = mapped_column(Geometry("POINT", srid=4326))
    # Naive wall-clock times (timestamp without time zone) — see migration 0030.
    # Storing them tz-aware shifted every Zeitplan time by the browser's UTC
    # offset when the frontend re-parsed them with new Date(...).
    planned_arrival: Mapped[datetime | None] = mapped_column(DateTime)
    planned_departure: Mapped[datetime | None] = mapped_column(DateTime)
    hold_duration_min: Mapped[int] = mapped_column(Integer, default=0)
    # V2: Grund für technische Halte (fuel | rest | maintenance | other)
    halt_purpose: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # Von der Anwendung vorgeschlagen (Technischer Halt, Tankstopp) und noch
    # nicht einsortiert. Die nächste Routenberechnung ordnet ihn entlang der
    # vorherigen Route ein und löscht die Marke — siehe
    # app/services/waypoint_order.py und Migration 0046.
    pending_placement: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )

    convoy: Mapped["Convoy"] = relationship(back_populates="waypoints")
