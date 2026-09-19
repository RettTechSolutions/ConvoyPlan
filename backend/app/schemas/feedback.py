"""Was eine Meldung mitbringt und was das Adminportal davon zu sehen bekommt."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.feedback import KINDS, PRIORITIES, SEVERITIES, STATUSES


def _aus(wert: str, erlaubt: tuple[str, ...], feld: str) -> str:
    if wert not in erlaubt:
        raise ValueError(f"{feld} muss einer von {', '.join(erlaubt)} sein")
    return wert


class FeedbackCreate(BaseModel):
    """Der Melde-Dialog aus der laufenden Anwendung.

    Die Umgebungsangaben (`page_url`, `user_agent`, `app_version`, `viewport`)
    kommen aus dem Browser und sind damit beliebig setzbar. Sie sind
    Hinweise für die Fehlersuche, nie eine Grundlage für eine Entscheidung —
    deshalb werden sie nur gekappt und nicht geprüft.
    """

    kind: str
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=8000)
    severity: str = "normal"

    page_url: str | None = Field(default=None, max_length=500)
    user_agent: str | None = Field(default=None, max_length=400)
    app_version: str | None = Field(default=None, max_length=80)
    viewport: str | None = Field(default=None, max_length=32)

    # Data-URL; Prüfung und Ablage in `services/feedback.py`. Die Obergrenze
    # hier ist die Base64-Länge und liegt deshalb über der Bildgrenze von 4 MB
    # — die gilt für die dekodierten Bytes.
    screenshot: str | None = Field(default=None, max_length=6_000_000)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        return _aus(v, KINDS, "kind")

    @field_validator("severity")
    @classmethod
    def _severity(cls, v: str) -> str:
        return _aus(v, SEVERITIES, "severity")

    @field_validator("title", "description")
    @classmethod
    def _getrimmt(cls, v: str) -> str:
        gekuerzt = v.strip()
        if not gekuerzt:
            raise ValueError("darf nicht leer sein")
        return gekuerzt


class FeedbackUpdate(BaseModel):
    """Was der Betreiber an einer Meldung ändern darf.

    Nicht dabei: Titel, Beschreibung, Schweregrad und die Umgebungsangaben.
    Eine Meldung ist die Aussage des Melders; wer sie umschreiben kann, kann
    sie auch entschärfen, und dann steht im Portal nicht mehr, was gemeldet
    wurde.
    """

    status: str | None = None
    priority: str | None = None
    admin_note: str | None = Field(default=None, max_length=8000)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str | None) -> str | None:
        return v if v is None else _aus(v, STATUSES, "status")

    @field_validator("priority")
    @classmethod
    def _priority(cls, v: str | None) -> str | None:
        return v if v is None else _aus(v, PRIORITIES, "priority")


class FeedbackSubmitted(BaseModel):
    """Die Quittung für den Melder — bewusst schmal.

    Zurück geht nur, dass es angekommen ist, und die Kennung zum Nachfragen.
    Der gespeicherte Datensatz geht den Melder nichts an; er enthält Felder
    (Notiz, Priorität), die dem Betreiber gehören.
    """

    id: uuid.UUID
    kind: str
    created_at: datetime


class FeedbackReportOut(BaseModel):
    """Eine Meldung, wie das Adminportal sie darstellt."""

    id: uuid.UUID
    kind: str
    title: str
    description: str
    severity: str
    priority: str
    status: str

    org_id: uuid.UUID | None
    org_slug: str | None
    org_name: str | None
    # `False`, sobald die Organisation gelöscht wurde — die Textkopien stehen
    # dann noch, der Verweis nicht mehr.
    org_vorhanden: bool

    user_id: uuid.UUID | None
    reporter_email: str | None
    reporter_name: str | None
    reporter_role: str | None
    is_demo: bool

    page_url: str | None
    user_agent: str | None
    app_version: str | None
    viewport: str | None

    has_screenshot: bool
    screenshot_bytes: int | None

    admin_note: str | None
    handled_by_email: str | None
    handled_at: datetime | None

    created_at: datetime
    updated_at: datetime


class FeedbackStats(BaseModel):
    """Die Kennzahlen über der Liste.

    `offen` zählt alles, was nicht erledigt, abgelehnt oder als Duplikat
    abgelegt ist — die Zahl, die sagt, ob jemand hinsehen muss.
    """

    gesamt: int
    offen: int
    bugs_offen: int
    features_offen: int
    kritisch_offen: int
    neu_7_tage: int
    je_status: dict[str, int]
