"""Org-scoped branding: overrides live on the organization row and never
touch the platform-wide SystemSetting branding."""
import json
import uuid
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


def _org(branding=None):
    org = MagicMock()
    org.id = uuid.uuid4()
    org.branding = branding
    return org


def _update_payload(**overrides):
    from app.schemas.branding import BrandingUpdate
    values = dict(
        app_name="Feuerwehr München",
        color_primary="#112233",
        color_primary_hover="#223344",
        color_accent="#334455",
        color_bg="#445566",
        color_surface="#556677",
        color_nav_bg="#667788",
        color_nav_text="#778899",
        color_text="#8899aa",
        color_text_muted="#99aabb",
    )
    values.update(overrides)
    return BrandingUpdate(**values)


@pytest.mark.asyncio
async def test_update_org_branding_requires_org_admin():
    from app.api.routes.org_branding import update_org_branding
    from fastapi import HTTPException
    db = _mock_db()
    org = _org()
    for role in ("beobachter", "fahrer", "planer"):
        with pytest.raises(HTTPException) as exc:
            await update_org_branding(data=_update_payload(), ctx=(MagicMock(), org, role), db=db)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_org_branding_writes_org_row_not_system_settings():
    from app.api.routes.org_branding import update_org_branding
    db = _mock_db([])
    org = _org()
    response = await update_org_branding(data=_update_payload(), ctx=(MagicMock(), org, "admin"), db=db)
    # Override landet als JSON auf der Organisation …
    stored = json.loads(org.branding)
    assert stored["app_name"] == "Feuerwehr München"
    assert stored["color_primary"] == "#112233"
    # … und es wird kein SystemSetting angelegt (kein plattformweiter Effekt).
    db.add.assert_not_called()
    assert response.app_name == "Feuerwehr München"


@pytest.mark.asyncio
async def test_update_org_branding_keeps_existing_logo_overrides():
    from app.api.routes.org_branding import update_org_branding
    db = _mock_db([])
    org = _org(branding=json.dumps({"logo_main": "org-x-main.png"}))
    await update_org_branding(data=_update_payload(), ctx=(MagicMock(), org, "admin"), db=db)
    assert json.loads(org.branding)["logo_main"] == "org-x-main.png"


@pytest.mark.asyncio
async def test_org_branding_response_merges_over_platform_branding():
    from app.api.routes.branding import org_branding_response
    db = _mock_db([])
    org = _org(branding=json.dumps({"color_primary": "#123456"}))
    response = await org_branding_response(db, org)
    # Override greift …
    assert response.color_primary == "#123456"
    # … alles andere erbt vom Plattform-Branding (hier: Defaults).
    assert response.app_name == "ConvoyPlan"
    assert response.color_accent == "#3498db"


@pytest.mark.asyncio
async def test_org_branding_response_ignores_malformed_json():
    from app.api.routes.branding import org_branding_response
    db = _mock_db([])
    org = _org(branding="not-json{")
    response = await org_branding_response(db, org)
    assert response.app_name == "ConvoyPlan"


@pytest.mark.asyncio
async def test_get_org_branding_by_slug_404_for_unknown_org():
    from app.api.routes.branding import get_org_branding_by_slug
    from fastapi import HTTPException
    db = _mock_db([])
    with pytest.raises(HTTPException) as exc:
        await get_org_branding_by_slug(slug="gibt-es-nicht", db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_upload_org_logo_requires_org_admin():
    from app.api.routes.org_branding import upload_org_logo
    from fastapi import HTTPException
    db = _mock_db()
    mock_file = MagicMock()
    mock_file.filename = "logo.png"
    mock_file.read = AsyncMock(return_value=b"data")
    with pytest.raises(HTTPException) as exc:
        await upload_org_logo(slot="main", file=mock_file, ctx=(MagicMock(), _org(), "planer"), db=db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_org_logo_is_namespaced_per_org(tmp_path, monkeypatch):
    from app.api.routes import org_branding
    monkeypatch.setattr(org_branding, "LOGOS_DIR", tmp_path)
    db = _mock_db([])
    org = _org()
    mock_file = MagicMock()
    mock_file.filename = "logo.png"
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    mock_file.read = AsyncMock(return_value=png)
    await org_branding.upload_org_logo(slot="main", file=mock_file, ctx=(MagicMock(), org, "admin"), db=db)
    expected = f"org-{org.id}-main.png"
    assert (tmp_path / expected).read_bytes() == png
    assert json.loads(org.branding)["logo_main"] == expected


@pytest.mark.asyncio
async def test_reset_org_branding_clears_overrides():
    from app.api.routes.org_branding import reset_org_branding
    db = _mock_db([])
    org = _org(branding=json.dumps({"app_name": "X"}))
    response = await reset_org_branding(ctx=(MagicMock(), org, "admin"), db=db)
    assert org.branding is None
    assert response.app_name == "ConvoyPlan"
