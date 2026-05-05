import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LageLayer(Base):
    __tablename__ = "lage_layers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    convoy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("convoys.id"))
    name: Mapped[str] = mapped_column(String(100))
    geojson_data: Mapped[dict] = mapped_column(JSON)
    color: Mapped[str] = mapped_column(String(20), default="#e74c3c")
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    convoy: Mapped["Convoy"] = relationship(back_populates="lage_layers")
