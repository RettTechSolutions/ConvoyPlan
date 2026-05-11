def test_leitstelle_model_importable():
    from app.models.leitstelle import Leitstelle
    ls = Leitstelle(name="ILS München", anrufgruppe="468")
    assert ls.name == "ILS München"
    assert ls.anrufgruppe == "468"
    assert ls.zusatz_kanaele is None
    assert ls.geometry is None


import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_ls(**kw):
    ls = MagicMock()
    ls.id = uuid.uuid4()
    ls.name = kw.get("name", "ILS München")
    ls.anrufgruppe = kw.get("anrufgruppe", "468")
    ls.zusatz_kanaele = kw.get("zusatz_kanaele", [])
    ls.geometry = kw.get("geometry", None)
    ls.created_at = MagicMock()
    return ls


def _mock_db(ls_list=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ls_list or []
    result.scalar_one_or_none.return_value = ls_list[0] if ls_list else None
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_leitstellen_returns_list():
    from app.api.routes.leitstellen import list_leitstellen
    db = _mock_db([_make_ls()])
    user = MagicMock(is_active=True)
    result = await list_leitstellen(db=db, current_user=user)
    assert len(result) == 1
    assert result[0].name == "ILS München"


@pytest.mark.asyncio
async def test_create_leitstelle_requires_superadmin():
    from app.api.routes.leitstellen import create_leitstelle
    from app.schemas.leitstelle import LeistelleCreate
    from fastapi import HTTPException
    db = _mock_db()
    non_admin = MagicMock(is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        await create_leitstelle(
            data=LeistelleCreate(name="X", anrufgruppe="1"),
            db=db,
            current_user=non_admin,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_leitstelle_succeeds_for_superadmin():
    from app.api.routes.leitstellen import create_leitstelle
    from app.schemas.leitstelle import LeistelleCreate

    created = _make_ls(name="ILS Test", anrufgruppe="469")
    db = _mock_db()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    admin = MagicMock(is_superadmin=True)
    with patch("app.api.routes.leitstellen.Leitstelle", return_value=created):
        result = await create_leitstelle(
            data=LeistelleCreate(name="ILS Test", anrufgruppe="469"),
            db=db,
            current_user=admin,
        )
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_leitstelle_requires_superadmin():
    from app.api.routes.leitstellen import delete_leitstelle
    from fastapi import HTTPException
    db = _mock_db([_make_ls()])
    non_admin = MagicMock(is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        await delete_leitstelle(leitstelle_id=uuid.uuid4(), db=db, current_user=non_admin)
    assert exc.value.status_code == 403
