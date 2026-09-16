"""
Verwaltung der E-Mail-Vorlagen durch den Superadmin.

GET  /api/admin/email-templates                  — alle Vorlagen mit Beschreibung
GET  /api/admin/email-templates/{kind}           — Betreff + HTML + is_custom
PUT  /api/admin/email-templates/{kind}           — eigene Fassung hinterlegen
POST /api/admin/email-templates/{kind}/reset     — eigene Fassung verwerfen
GET  /api/admin/email-templates/{kind}/preview   — Musterexemplar als HTML
POST /api/admin/email-templates/{kind}/test      — Musterexemplar an den Aufrufer

Bis auf die Zugangsdaten-Mail gab es hier nichts zu verwalten; die Endpunkte
trugen deshalb keine Kennung. Mit der Nachfrage-Mail nach einer Demo-Sitzung
sind es zwei, und weitere werden folgen — daher die Kennung im Pfad statt eines
zweiten Moduls mit denselben vier Endpunkten.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_superadmin
from app.config import settings
from app.models.settings import SystemSetting
from app.models.user import User
from app.services import audit
from app.services.email import (
    DEFAULT_DEMO_FOLLOWUP_HTML,
    DEFAULT_DEMO_FOLLOWUP_SUBJECT,
    DEFAULT_EMAIL_TEMPLATE_HTML,
    DEFAULT_EMAIL_TEMPLATE_SUBJECT,
    DEMO_FOLLOWUP_HTML_KEY,
    DEMO_FOLLOWUP_SUBJECT_KEY,
    PASSWORD_HTML_KEY,
    PASSWORD_SUBJECT_KEY,
    _render_demo_followup_email_async,
    _render_password_email_async,
    _send_html_email,
    is_smtp_configured,
)

router = APIRouter(prefix="/admin/email-templates", tags=["email-template"])


# ── Vorlagenverzeichnis ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class TemplateKind:
    """Eine verwaltbare Vorlage.

    `preview` rendert ein Musterexemplar mit erfundenen, aber realistischen
    Werten — dieselbe Funktion, die auch die echte Mail baut. Eine eigene
    Vorschau-Implementierung würde irgendwann auseinanderlaufen und dann das
    Falsche zeigen.
    """

    slug: str
    label: str
    description: str
    subject_key: str
    html_key: str
    default_subject: str
    default_html: str
    # Platzhalter, die in dieser Vorlage etwas bedeuten — im Editor die einzige
    # Quelle dafür, was man überhaupt einsetzen darf.
    placeholders: tuple[str, ...]
    preview: Callable[[AsyncSession], Awaitable[tuple[str, str]]] = field(repr=False)


async def _preview_password(db: AsyncSession) -> tuple[str, str]:
    return await _render_password_email_async(
        db=db,
        recipient_name="Max Mustermann",
        email="max.mustermann@example.com",
        password="ExamplePassw0rd!",
        login_url=f"{settings.app_base_url.rstrip('/')}/o/muster/login",
    )


async def _preview_demo_followup(db: AsyncSession) -> tuple[str, str]:
    base = settings.app_base_url.rstrip("/")
    return await _render_demo_followup_email_async(
        db=db,
        recipient_name="Max Mustermann",
        unsubscribe_url=f"{base}/demo/abmelden?token=musterexemplar",
        contact_url=settings.demo_followup_contact_url,
    )


KINDS: dict[str, TemplateKind] = {
    "password": TemplateKind(
        slug="password",
        label="Zugangsdaten",
        description=(
            "Geht an neu angelegte Benutzer und nach einem Zurücksetzen des "
            "Passworts."
        ),
        subject_key=PASSWORD_SUBJECT_KEY,
        html_key=PASSWORD_HTML_KEY,
        default_subject=DEFAULT_EMAIL_TEMPLATE_SUBJECT,
        default_html=DEFAULT_EMAIL_TEMPLATE_HTML,
        placeholders=(
            "recipient_name", "recipient_name_greeting", "email", "password",
            "login_url", "app_name", "logo_block", "color_primary",
            "color_primary_hover",
        ),
        preview=_preview_password,
    ),
    "demo_followup": TemplateKind(
        slug="demo_followup",
        label="Nachfrage nach der Demo",
        description=(
            "Geht einmalig an die beim Demo-Start angegebene Adresse, sobald "
            "die Sitzung abgelaufen ist."
        ),
        subject_key=DEMO_FOLLOWUP_SUBJECT_KEY,
        html_key=DEMO_FOLLOWUP_HTML_KEY,
        default_subject=DEFAULT_DEMO_FOLLOWUP_SUBJECT,
        default_html=DEFAULT_DEMO_FOLLOWUP_HTML,
        placeholders=(
            "recipient_name", "recipient_name_greeting", "app_name",
            "logo_block", "color_primary", "contact_url", "unsubscribe_url",
        ),
        preview=_preview_demo_followup,
    ),
}


def _kind_or_404(kind: str) -> TemplateKind:
    found = KINDS.get(kind)
    if found is None:
        raise HTTPException(404, "Diese Vorlage gibt es nicht")
    return found


# ── Schemas ───────────────────────────────────────────────────────────────────

class EmailTemplate(BaseModel):
    kind: str
    label: str
    description: str
    subject: str
    html: str
    is_custom: bool
    placeholders: list[str]


class EmailTemplateSummary(BaseModel):
    kind: str
    label: str
    description: str
    is_custom: bool


class EmailTemplateUpdate(BaseModel):
    subject: str
    html: str


class TestMailResult(BaseModel):
    status: str
    # An welche Adresse tatsächlich zugestellt wurde — der Aufrufer weiß sonst
    # nicht, in welchem Postfach er nachsehen soll.
    recipient: str


# ── Helfer ────────────────────────────────────────────────────────────────────

async def _stored(db: AsyncSession, kind: TemplateKind) -> tuple[str | None, str | None]:
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_([kind.subject_key, kind.html_key])
        )
    )
    rows = {r.key: r.value for r in result.scalars().all()}
    return rows.get(kind.subject_key), rows.get(kind.html_key)


async def _as_response(db: AsyncSession, kind: TemplateKind) -> EmailTemplate:
    subject, html = await _stored(db, kind)
    return EmailTemplate(
        kind=kind.slug,
        label=kind.label,
        description=kind.description,
        subject=subject or kind.default_subject,
        html=html or kind.default_html,
        is_custom=bool(subject or html),
        placeholders=list(kind.placeholders),
    )


async def _upsert(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


# ── Endpunkte ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[EmailTemplateSummary])
async def list_email_templates(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> list[EmailTemplateSummary]:
    """Welche Vorlagen es gibt und welche davon angepasst wurden."""
    out: list[EmailTemplateSummary] = []
    for kind in KINDS.values():
        subject, html = await _stored(db, kind)
        out.append(
            EmailTemplateSummary(
                kind=kind.slug, label=kind.label, description=kind.description,
                is_custom=bool(subject or html),
            )
        )
    return out


@router.get("/{kind}", response_model=EmailTemplate)
async def get_email_template(
    kind: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> EmailTemplate:
    return await _as_response(db, _kind_or_404(kind))


@router.put("/{kind}", response_model=EmailTemplate)
async def update_email_template(
    kind: str,
    data: EmailTemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
) -> EmailTemplate:
    template = _kind_or_404(kind)
    await _upsert(db, template.subject_key, data.subject)
    await _upsert(db, template.html_key, data.html)
    await db.commit()
    await audit.record(
        db, "admin.email_template.updated", request=request, actor_id=current.id,
        actor_email=current.email, target_type="email_template", target_id=template.slug,
    )
    return await _as_response(db, template)


@router.post("/{kind}/reset", response_model=EmailTemplate)
async def reset_email_template(
    kind: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
) -> EmailTemplate:
    """Eigene Fassung verwerfen — ab dann gilt wieder die mitgelieferte."""
    template = _kind_or_404(kind)
    for key in (template.subject_key, template.html_key):
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = result.scalar_one_or_none()
        if row:
            await db.delete(row)
    await db.commit()
    await audit.record(
        db, "admin.email_template.reset", request=request, actor_id=current.id,
        actor_email=current.email, target_type="email_template", target_id=template.slug,
    )
    return await _as_response(db, template)


@router.get("/{kind}/preview", response_class=HTMLResponse)
async def preview_email_template(
    kind: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
) -> HTMLResponse:
    """Musterexemplar mit erfundenen Werten — gerendert von derselben Funktion,
    die auch die echte Mail baut."""
    template = _kind_or_404(kind)
    _subject, html_body = await template.preview(db)
    return HTMLResponse(content=html_body)


@router.post("/{kind}/test", response_model=TestMailResult)
async def send_test_email(
    kind: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
) -> TestMailResult:
    """Das Musterexemplar an die eigene Adresse schicken.

    Nur an die eigene: Ein frei wählbarer Empfänger machte aus dem Admin-Portal
    einen Versender für beliebige Adressen — mit dem Absender und dem Ruf der
    Installation im Rücken. Wer die Mail jemand anderem zeigen will, leitet sie
    weiter.

    Der Weg dahin ist derselbe wie im Betrieb: dieselbe Vorlage, dasselbe
    Rendering, derselbe SMTP-Versand. Kommt sie an, kommt auch die echte an.
    """
    template = _kind_or_404(kind)
    if not current.email or "@" not in current.email:
        raise HTTPException(400, "Für dieses Konto ist keine E-Mail-Adresse hinterlegt")
    if not await is_smtp_configured(db):
        raise HTTPException(
            400, "SMTP ist nicht konfiguriert — bitte zuerst unter System einrichten"
        )

    subject, html_body = await template.preview(db)
    try:
        await _send_html_email(db, current.email, f"[Test] {subject}", html_body)
    except Exception as exc:  # noqa: BLE001 — der Grund gehört in die Oberfläche
        # Der Text des SMTP-Servers ist hier die eigentliche Auskunft
        # („Authentifizierung fehlgeschlagen", „Relay verweigert") und geht nur
        # an den Superadmin, der ihn braucht.
        raise HTTPException(502, f"Versand fehlgeschlagen: {exc}") from exc

    await audit.record(
        db, "admin.email_template.test_sent", request=request, actor_id=current.id,
        actor_email=current.email, target_type="email_template", target_id=template.slug,
    )
    return TestMailResult(status="sent", recipient=current.email)
