import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# Status-Werte einer Leitstelle:
#   "global"   — für alle Organisationen sichtbar (vom Superadmin angelegt oder
#                ein freigegebener Vorschlag); org_id ist NULL.
#   "local"    — gehört einer Organisation, nur für diese sichtbar.
#   "pending"  — von einer Organisation als Vorschlag eingereicht, wartet auf
#                Review durch den Superadmin.
#   "rejected" — Vorschlag wurde abgelehnt, bleibt org-lokal.
LEITSTELLE_STATUSES = ("global", "local", "pending", "rejected")


class Leitstelle(Base):
    __tablename__ = "leitstellen"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    anrufgruppe: Mapped[str] = mapped_column(String(50))
    zusatz_kanaele: Mapped[list | None] = mapped_column(JSON, nullable=True)
    geometry = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    # Schlüssel der gewählten Gebiete, sofern das Gebiet über die Gebietsauswahl
    # statt als freies Polygon definiert wurde. Ermöglicht u. a. die Markierung
    # bereits vergebener Gebiete. Format: ISO-Länderkürzel + Landesschlüssel —
    # "DE-08115" (AGS), "AT-322" (Bezirkskennziffer), "CH-040" (Kanton),
    # "LI-000"; siehe app/schemas/leitstelle.py und Migration 0039.
    district_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Org-Zuordnung & Vorschlags-Workflow
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), server_default="global", default="global")
    proposed_by_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
