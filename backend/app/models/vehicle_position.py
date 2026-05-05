import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VehiclePosition(Base):
    """Latest known position per vehicle in a convoy (upserted on update)."""

    __tablename__ = "vehicle_positions"

    convoy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("convoys.id"), primary_key=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    convoy: Mapped["Convoy"] = relationship(back_populates="vehicle_positions")
    vehicle: Mapped["Vehicle"] = relationship()
