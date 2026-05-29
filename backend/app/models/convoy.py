import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Convoy(Base):
    __tablename__ = "convoys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    organization: Mapped[str | None] = mapped_column(String(100))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    parent_convoy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("convoys.id", ondelete="SET NULL", use_alter=True, name="fk_convoy_parent"), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_point = mapped_column(Geometry("POINT", srid=4326))
    end_point = mapped_column(Geometry("POINT", srid=4326))
    speed_urban_kmh: Mapped[int] = mapped_column(Integer, default=40)
    speed_rural_kmh: Mapped[int] = mapped_column(Integer, default=65)
    road_preference: Mapped[str] = mapped_column(String(20), default="schnell")
    spacing_urban_m: Mapped[int] = mapped_column(Integer, default=15)
    spacing_rural_m: Mapped[int] = mapped_column(Integer, default=50)
    spacing_motorway_m: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(20), default="planning")
    share_token: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    # Marschbefehl fields (official 7-section format)
    lage: Mapped[str | None] = mapped_column(Text, nullable=True)
    auftrag: Mapped[str | None] = mapped_column(Text, nullable=True)
    marschform: Mapped[str | None] = mapped_column(String(50), nullable=True)  # geschlossener_verband|einzelgruppen|individuell
    ablaufpunkt: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ablaufzeit: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ablaufführer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    versorgung: Mapped[str | None] = mapped_column(Text, nullable=True)
    funkgruppe: Mapped[str | None] = mapped_column(String(100), nullable=True)
    anlagen: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner: Mapped["User"] = relationship(back_populates="convoys")
    org: Mapped["Organization | None"] = relationship(back_populates="convoys", foreign_keys=[organization_id])
    convoy_vehicles: Mapped[list["ConvoyVehicle"]] = relationship(back_populates="convoy", cascade="all, delete-orphan", order_by="ConvoyVehicle.position")
    waypoints: Mapped[list["Waypoint"]] = relationship(back_populates="convoy", cascade="all, delete-orphan", order_by="Waypoint.order_index")
    route: Mapped["Route | None"] = relationship(back_populates="convoy", cascade="all, delete-orphan", uselist=False)
    vehicle_positions: Mapped[list["VehiclePosition"]] = relationship(back_populates="convoy", cascade="all, delete-orphan")
    share_links: Mapped[list["ConvoyShareLink"]] = relationship(back_populates="convoy", cascade="all, delete-orphan")


class ConvoyVehicle(Base):
    __tablename__ = "convoy_vehicles"

    convoy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("convoys.id"), primary_key=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_status: Mapped[str] = mapped_column(String(30), default="planned")  # planned/en_route/arrived/delayed
    sonderfunktion: Mapped[str | None] = mapped_column(String(50), nullable=True)  # spitzenführer|schließender|sanitaet|ablaufführer
    mobile_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)

    convoy: Mapped["Convoy"] = relationship(back_populates="convoy_vehicles")
    vehicle: Mapped["Vehicle"] = relationship(back_populates="convoy_vehicles")
