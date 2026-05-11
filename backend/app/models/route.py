import uuid

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    convoy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("convoys.id"), unique=True)
    geometry = mapped_column(Geometry("LINESTRING", srid=4326))
    distance_m: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    routing_params: Mapped[dict | None] = mapped_column(JSON)
    gpx_data: Mapped[str | None] = mapped_column(Text)
    kanalwechsel: Mapped[list | None] = mapped_column(JSON, nullable=True)

    convoy: Mapped["Convoy"] = relationship(back_populates="route")
