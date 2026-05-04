import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Convoy(Base):
    __tablename__ = "convoys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    organization: Mapped[str | None] = mapped_column(String(100))
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_point = mapped_column(Geometry("POINT", srid=4326))
    end_point = mapped_column(Geometry("POINT", srid=4326))
    speed_urban_kmh: Mapped[int] = mapped_column(Integer, default=50)
    speed_rural_kmh: Mapped[int] = mapped_column(Integer, default=80)
    status: Mapped[str] = mapped_column(String(20), default="planning")
    share_token: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    owner: Mapped["User"] = relationship(back_populates="convoys")
    convoy_vehicles: Mapped[list["ConvoyVehicle"]] = relationship(back_populates="convoy", cascade="all, delete-orphan", order_by="ConvoyVehicle.position")
    waypoints: Mapped[list["Waypoint"]] = relationship(back_populates="convoy", cascade="all, delete-orphan", order_by="Waypoint.order_index")
    route: Mapped["Route | None"] = relationship(back_populates="convoy", cascade="all, delete-orphan", uselist=False)


class ConvoyVehicle(Base):
    __tablename__ = "convoy_vehicles"

    convoy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("convoys.id"), primary_key=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    convoy: Mapped["Convoy"] = relationship(back_populates="convoy_vehicles")
    vehicle: Mapped["Vehicle"] = relationship(back_populates="convoy_vehicles")
