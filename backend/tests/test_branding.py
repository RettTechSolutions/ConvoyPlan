from unittest.mock import AsyncMock, MagicMock
import pytest


def _mock_db(settings=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = settings or []
    result.scalar_one_or_none.return_value = settings[0] if settings else None
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_get_branding_returns_defaults_when_empty():
    from app.api.routes.branding import get_branding
    db = _mock_db([])
    response = await get_branding(db=db)
    assert response.app_name == "ConvoyPlan"
    assert response.color_primary == "#E23D28"
    assert response.logo_main_url is None
    assert response.logo_horizontal_url is None


@pytest.mark.asyncio
async def test_get_branding_returns_stored_app_name():
    from app.api.routes.branding import get_branding
    setting = MagicMock()
    setting.key = "branding.app_name"
    setting.value = "Feuerwehr München"
    db = _mock_db([setting])
    response = await get_branding(db=db)
    assert response.app_name == "Feuerwehr München"


@pytest.mark.asyncio
async def test_update_branding_requires_superadmin():
    from app.api.routes.branding import update_branding
    from app.schemas.branding import BrandingUpdate
    from fastapi import HTTPException
    db = _mock_db()
    non_admin = MagicMock(is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        await update_branding(
            data=BrandingUpdate(
                app_name="Test",
                color_primary="#E23D28",
                color_primary_hover="#C23020",
                color_accent="#3498db",
                color_bg="#f5f3ee",
                color_surface="#ffffff",
                color_nav_bg="#2c3e50",
                color_nav_text="#ecf0f1",
                color_text="#2c3e50",
                color_text_muted="#7f8c8d",
            ),
            db=db,
            current_user=non_admin,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_logo_requires_superadmin():
    from app.api.routes.branding import upload_logo
    from fastapi import HTTPException
    db = _mock_db()
    non_admin = MagicMock(is_superadmin=False)
    mock_file = MagicMock()
    mock_file.filename = "logo.png"
    mock_file.read = AsyncMock(return_value=b"data")
    with pytest.raises(HTTPException) as exc:
        await upload_logo(slot="main", file=mock_file, db=db, current_user=non_admin)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_logo_rejects_oversized():
    from app.api.routes.branding import upload_logo
    from fastapi import HTTPException
    db = _mock_db()
    admin = MagicMock(is_superadmin=True)
    mock_file = MagicMock()
    mock_file.filename = "logo.png"
    mock_file.read = AsyncMock(return_value=b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(HTTPException) as exc:
        await upload_logo(slot="main", file=mock_file, db=db, current_user=admin)
    assert exc.value.status_code == 400
    assert "too large" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_upload_logo_rejects_bad_extension():
    from app.api.routes.branding import upload_logo
    from fastapi import HTTPException
    db = _mock_db()
    admin = MagicMock(is_superadmin=True)
    mock_file = MagicMock()
    mock_file.filename = "malware.exe"
    mock_file.read = AsyncMock(return_value=b"x")
    with pytest.raises(HTTPException) as exc:
        await upload_logo(slot="main", file=mock_file, db=db, current_user=admin)
    assert exc.value.status_code == 400
    assert "Invalid file type" in exc.value.detail
