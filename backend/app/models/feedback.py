"""Eine Meldung aus der laufenden Anwendung — Fehler oder Wunsch.

Wer im Einsatz auf einen Fehler stößt, hat weder Zeit noch Lust, ihn woanders
aufzuschreiben. Die Meldung entsteht deshalb dort, wo der Fehler passiert, und
nimmt mit, was zur Einordnung nötig ist: Seite, Browser, Fassung, optional ein
Bildschirmfoto. Alles davon sieht nur, wer die Instanz betreibt.

**Die Zeile überlebt ihren Anlass.** Organisation und Benutzer hängen als
``SET NULL`` daran, daneben stehen Kopien von Name, Kürzel und Adresse als
Text. Eine gelöschte Demo-Organisation darf keine offene Fehlermeldung
mitreißen — der Fehler ist damit nicht behoben, und der Hinweis, in welcher
Umgebung er auftrat, bleibt lesbar.

Zwei Einschätzungen, die getrennt bleiben: ``severity`` ist die des Melders und
wird nicht mehr angefasst, ``priority`` die des Betreibers. Sie in ein Feld zu
legen hieße, die erste beim ersten Triage-Klick zu verlieren — und genau die
sagt, wie schlimm es sich *im Einsatz* angefühlt hat.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# ── Wertebereiche ─────────────────────────────────────────────────────────────
# Absichtlich Zeichenketten statt eines PostgreSQL-ENUMs: ein neuer Status ist
# dann eine Zeile hier und kein Typ-Umbau per Migration. Geprüft wird beim
# Eintritt (Schemata in `app/schemas/feedback.py`), nicht von der Datenbank.

KIND_BUG = "bug"
KIND_FEATURE = "feature"
KINDS = (KIND_BUG, KIND_FEATURE)

SEVERITIES = ("niedrig", "normal", "hoch", "kritisch")
PRIORITIES = ("niedrig", "normal", "hoch", "kritisch")

STATUS_NEU = "neu"
STATUS_GESICHTET = "gesichtet"
STATUS_GEPLANT = "geplant"
STATUS_IN_ARBEIT = "in_arbeit"
STATUS_ERLEDIGT = "erledigt"
STATUS_ABGELEHNT = "abgelehnt"
STATUS_DUPLIKAT = "duplikat"
STATUSES = (
    STATUS_NEU,
    STATUS_GESICHTET,
    STATUS_GEPLANT,
    STATUS_IN_ARBEIT,
    STATUS_ERLEDIGT,
    STATUS_ABGELEHNT,
    STATUS_DUPLIKAT,
)
# Was nicht mehr auf dem Tisch liegt. Die Liste steht hier und nicht in der
# Abfrage, weil sie an zwei Stellen gebraucht wird (Kennzahlen und Filter) und
# ein achtes Statuswort sonst an einer davon vergessen würde.
STATUSES_ABGESCHLOSSEN = (STATUS_ERLEDIGT, STATUS_ABGELEHNT, STATUS_DUPLIKAT)


class FeedbackReport(Base):
    """Eine gemeldete Beobachtung: Fehler oder Wunsch."""

    __tablename__ = "feedback_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    kind: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)

    # Die Einschätzung des Melders — bleibt, wie sie abgeschickt wurde.
    severity: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    # Die des Betreibers. Startet auf der des Melders und wird beim Sichten
    # geradegezogen.
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    status: Mapped[str] = mapped_column(
        String(20), default=STATUS_NEU, server_default=STATUS_NEU, index=True
    )

    # ── Herkunft ──────────────────────────────────────────────────────────────
    # SET NULL samt Textkopie: siehe Modulkommentar.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    org_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    org_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reporter_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reporter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reporter_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Aus einer Demo-Sitzung gemeldet. Nicht weniger wert — Demo-Nutzer laufen
    # als erste in das, was noch nicht rund ist —, aber anders einzuordnen:
    # die Umgebung dazu ist beim Sichten längst abgeräumt.
    is_demo: Mapped[bool] = mapped_column(default=False, server_default="false")

    # ── Umgebung zum Zeitpunkt der Meldung ───────────────────────────────────
    page_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    viewport: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Dateiname unter `FEEDBACK_DIR`, nie ein Pfad — was hier steht, wird beim
    # Ausliefern an das Verzeichnis gehängt.
    screenshot_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    screenshot_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Bearbeitung ───────────────────────────────────────────────────────────
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
