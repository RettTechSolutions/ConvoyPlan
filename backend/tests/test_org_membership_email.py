from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import email as email_svc


def _branding_db() -> AsyncMock:
    """DB mock whose SystemSetting query returns no rows (→ default branding)."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_render_org_membership_email_contains_org_and_login():
    db = _branding_db()
    subject, body = await email_svc._render_org_membership_email_async(
        db=db,
        recipient_name="Max Mustermann",
        org_name="Rettdienst München",
        role="planer",
        login_url="https://app.example.com/o/rettdienst/login",
    )

    assert "Rettdienst München" in subject
    # Body carries the org, the human-readable role label and the login link.
    assert "Rettdienst München" in body
    assert "Planer" in body
    assert "https://app.example.com/o/rettdienst/login" in body
    assert "Max Mustermann" in body


@pytest.mark.asyncio
async def test_render_org_membership_email_escapes_html_in_name():
    db = _branding_db()
    _, body = await email_svc._render_org_membership_email_async(
        db=db,
        recipient_name="<script>alert(1)</script>",
        org_name="Org & Co",
        role="admin",
        login_url="https://app.example.com/o/org/login",
    )

    # User-controlled values must be escaped to prevent HTML injection.
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "Org &amp; Co" in body


@pytest.mark.asyncio
async def test_render_org_membership_email_unknown_role_falls_back():
    db = _branding_db()
    _, body = await email_svc._render_org_membership_email_async(
        db=db,
        recipient_name="",
        org_name="Org",
        role="custom-role",
        login_url="https://app.example.com/o/org/login",
    )
    # Unknown role keys render verbatim rather than raising.
    assert "custom-role" in body
