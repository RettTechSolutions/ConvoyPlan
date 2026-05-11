import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Leitstelle(Base):
    __tablename__ = "leitstellen"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    anrufgruppe: Mapped[str] = mapped_column(String(50))
    zusatz_kanaele: Mapped[list | None] = mapped_column(JSON, nullable=True)
    geometry = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
