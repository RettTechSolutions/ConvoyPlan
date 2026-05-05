import uuid

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    callsign: Mapped[str | None] = mapped_column(String(50))
    license_plate: Mapped[str | None] = mapped_column(String(20))
    height_cm: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[int | None] = mapped_column(Integer)
    length_cm: Mapped[int | None] = mapped_column(Integer)
    convoy_role: Mapped[str | None] = mapped_column(String(50))
    # Kraftstoff
    tank_capacity_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    fuel_consumption_l100km: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_fuel_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    owner: Mapped["User"] = relationship(back_populates="vehicles")
    convoy_vehicles: Mapped[list["ConvoyVehicle"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan")
