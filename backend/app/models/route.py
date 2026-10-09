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
    # Abbiegehinweise aus der letzten Berechnung (routing.compact_instructions).
    # None heißt: keine vorhanden — Route vor Migration 0047 berechnet oder
    # importiert. Das Roadbook sagt das dann, statt eine leere Liste zu drucken.
    instructions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Höhenbeschränkungen entlang der Route (services/durchfahrtshoehe.py).
    # None heißt: nicht ermittelt — Route vor Migration 0055 berechnet oder
    # importiert. Eine leere Liste heißt: keine bekannte Beschränkung.
    durchfahrtshoehen: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Brücken ohne bekannte Höhe (services/bruecken.py), gesucht nach der
    # Berechnung: {"geprueft_at": …, "eintraege": […]}. None = nicht gesucht.
    bruecken: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Meterbereiche [von, bis] auf Autobahn/Kraftfahrstraße, für die Suche.
    schnellstrassen: Mapped[list | None] = mapped_column(JSON, nullable=True)

    convoy: Mapped["Convoy"] = relationship(back_populates="route")
