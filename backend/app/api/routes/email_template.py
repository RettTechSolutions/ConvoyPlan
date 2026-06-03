"""
E-Mail template CRUD for superadmin.

GET  /api/admin/email-template          — returns subject + html + is_custom
PUT  /api/admin/email-template          — upsert custom template
POST /api/admin/email-template/reset    — delete custom template (revert to default)
GET  /api/admin/email-template/preview  — render sample e-mail and return HTML
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_superadmin
from app.models.settings import SystemSetting
from app.models.user import User
from app.services.email import (
    DEFAULT_EMAIL_TEMPLATE_HTML,
    DEFAULT_EMAIL_TEMPLATE_SUBJECT,
)

router = APIRouter(prefix="/admin/email-template", tags=["email-template"])

_KEY_SUBJECT = "email.template.subject"
_KEY_HTML = "email.template.html"


# ── Schemas ────────────────────────────────────────────────────────────────────

class EmailTemplate(BaseModel):
    subject: str
    html: str
    is_custom: bool


class EmailTemplateUpdate(BaseModel):
    subject: str
    html: str


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_template(db: AsyncSession) -> tuple[str, str, bool]:
    """Returns (subject, html, is_custom)."""
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_([_KEY_SUBJECT, _KEY_HTML])
        )
    )
    rows = {r.key: r.value for r in result.scalars().all()}
    subject = rows.get(_KEY_SUBJECT)
    html = rows.get(_KEY_HTML)
    is_custom = bool(subject or html)
    return (
        subject or DEFAULT_EMAIL_TEMPLATE_SUBJECT,
        html or DEFAULT_EMAIL_TEMPLATE_HTML,
        is_custom,
    )


async def _upsert(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=EmailTemplate)
async def get_email_template(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
) -> EmailTemplate:
    subject, html, is_custom = await _get_template(db)
    return EmailTemplate(subject=subject, html=html, is_custom=is_custom)


@router.put("", response_model=EmailTemplate)
async def update_email_template(
    data: EmailTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
) -> EmailTemplate:
    await _upsert(db, _KEY_SUBJECT, data.subject)
    await _upsert(db, _KEY_HTML, data.html)
    await db.commit()
    subject, html, is_custom = await _get_template(db)
    return EmailTemplate(subject=subject, html=html, is_custom=is_custom)


@router.post("/reset", response_model=EmailTemplate)
async def reset_email_template(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
) -> EmailTemplate:
    for key in (_KEY_SUBJECT, _KEY_HTML):
        result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = result.scalar_one_or_none()
        if row:
            await db.delete(row)
    await db.commit()
    return EmailTemplate(
        subject=DEFAULT_EMAIL_TEMPLATE_SUBJECT,
        html=DEFAULT_EMAIL_TEMPLATE_HTML,
        is_custom=False,
    )


@router.get("/preview", response_class=HTMLResponse)
async def preview_email_template(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_superadmin),
) -> HTMLResponse:
    from app.services.email import _render_password_email_async

    html = await _render_password_email_async(
        db=db,
        recipient_name="Max Mustermann",
        email="max.mustermann@example.com",
        password="ExamplePassw0rd!",
        login_url="https://convoyplan.example.com/login",
    )
    _subject, rendered_html = html
    return HTMLResponse(content=rendered_html)
