import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_leitstelle_model_importable():
    from app.models.leitstelle import Leitstelle
    ls = Leitstelle(name="ILS München", anrufgruppe="468")
    assert ls.name == "ILS München"
    assert ls.anrufgruppe == "468"
    assert ls.zusatz_kanaele is None
    assert ls.geometry is None
    assert ls.district_codes is None


def _make_ls(**kw):
    ls = MagicMock()
    ls.id = kw.get("id", uuid.uuid4())
    ls.name = kw.get("name", "ILS München")
    ls.anrufgruppe = kw.get("anrufgruppe", "468")
    ls.zusatz_kanaele = kw.get("zusatz_kanaele", [])
    ls.geometry = kw.get("geometry", None)
    ls.district_codes = kw.get("district_codes", [])
    ls.org_id = kw.get("org_id", None)
    ls.status = kw.get("status", "global")
    ls.proposed_by_org_id = kw.get("proposed_by_org_id", None)
    ls.review_note = kw.get("review_note", None)
    ls.created_at = MagicMock()
    return ls


def _mock_db(ls_list=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ls_list or []
    result.scalar_one_or_none.return_value = ls_list[0] if ls_list else None
    result.all.return_value = []  # org_name_map row fetch
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


# ── Response helpers ───────────────────────────────────────────────────────────

def test_to_response_maps_new_fields():
    from app.api.routes.leitstellen import to_response
    oid = uuid.uuid4()
    ls = _make_ls(org_id=oid, status="local", district_codes=["09162", "09184"])
    r = to_response(ls, {oid: "Org X"})
    assert r.status == "local"
    assert r.org_name == "Org X"
    assert r.district_codes == ["09162", "09184"]
    assert r.has_geometry is False


def test_geojson_skips_features_without_geometry():
    from app.api.routes.leitstellen import geojson_feature_collection
    fc = geojson_feature_collection([_make_ls(geometry=None)])
    assert fc["type"] == "FeatureCollection"
    assert fc["features"] == []


def test_parse_geojson_unions_multiple_features():
    from app.api.routes.leitstellen import _parse_geojson
    import json
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {
                "type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}},
            {"type": "Feature", "properties": {}, "geometry": {
                "type": "Polygon", "coordinates": [[[1, 0], [1, 1], [2, 1], [2, 0], [1, 0]]]}},
        ],
    }
    geom = _parse_geojson(json.dumps(fc).encode())
    # Two adjacent unit squares dissolve into one polygon spanning x in [0, 2].
    assert geom is not None
    assert geom.geom_type in ("Polygon", "MultiPolygon")
    minx, _, maxx, _ = geom.bounds
    assert minx == 0 and maxx == 2


# ── Superadmin / global router ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_leitstellen_returns_list():
    from app.api.routes.leitstellen import list_leitstellen
    db = _mock_db([_make_ls()])
    result = await list_leitstellen(db=db)
    assert len(result) == 1
    assert result[0].name == "ILS München"
    assert result[0].status == "global"


@pytest.mark.asyncio
async def test_create_leitstelle_is_global():
    from app.api.routes.leitstellen import create_leitstelle
    from app.schemas.leitstelle import LeistelleCreate
    created = _make_ls(name="ILS Test", anrufgruppe="469")
    db = _mock_db()
    with patch("app.api.routes.leitstellen.Leitstelle", return_value=created):
        result = await create_leitstelle(
            data=LeistelleCreate(name="ILS Test", anrufgruppe="469"), db=db,
        )
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    assert result.status == "global"


@pytest.mark.asyncio
async def test_approve_pending_makes_global():
    from app.api.routes.leitstellen import approve_leitstelle
    oid = uuid.uuid4()
    ls = _make_ls(status="pending", org_id=oid)
    db = _mock_db([ls])
    await approve_leitstelle(leitstelle_id=ls.id, db=db)
    assert ls.status == "global"
    assert ls.org_id is None
    assert ls.proposed_by_org_id == oid


@pytest.mark.asyncio
async def test_approve_non_pending_conflicts():
    from app.api.routes.leitstellen import approve_leitstelle
    from fastapi import HTTPException
    ls = _make_ls(status="local")
    db = _mock_db([ls])
    with pytest.raises(HTTPException) as exc:
        await approve_leitstelle(leitstelle_id=ls.id, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reject_sets_note_and_status():
    from app.api.routes.leitstellen import reject_leitstelle
    from app.schemas.leitstelle import LeistelleReject
    ls = _make_ls(status="pending", org_id=uuid.uuid4())
    db = _mock_db([ls])
    await reject_leitstelle(leitstelle_id=ls.id, data=LeistelleReject(note="zu klein"), db=db)
    assert ls.status == "rejected"
    assert ls.review_note == "zu klein"


# ── Org-scoped router ────────────────────────────────────────────────────────────

def test_require_admin_rejects_low_roles():
    from app.api.routes.org_leitstellen import _require_admin
    from fastapi import HTTPException
    for role in ("beobachter", "fahrer", "planer"):
        with pytest.raises(HTTPException) as exc:
            _require_admin(role)
        assert exc.value.status_code == 403
    _require_admin("admin")  # should not raise


@pytest.mark.asyncio
async def test_org_create_is_local_and_scoped():
    from app.api.routes.org_leitstellen import create_leitstelle
    from app.schemas.leitstelle import LeistelleCreate
    org = MagicMock(id=uuid.uuid4())
    org.name = "Org X"
    created = _make_ls(name="Org-LS", anrufgruppe="500")
    db = _mock_db()

    def _factory(**kw):
        created.org_id = kw.get("org_id")
        created.status = kw.get("status", "local")
        return created

    with patch("app.api.routes.org_leitstellen.Leitstelle", side_effect=_factory):
        result = await create_leitstelle(
            data=LeistelleCreate(name="Org-LS", anrufgruppe="500"),
            ctx=(MagicMock(), org, "admin"), db=db,
        )
    assert created.org_id == org.id
    assert result.status == "local"


@pytest.mark.asyncio
async def test_org_submit_sets_pending():
    from app.api.routes.org_leitstellen import submit_leitstelle
    org = MagicMock(id=uuid.uuid4())
    org.name = "Org X"
    ls = _make_ls(status="local", org_id=org.id)
    db = _mock_db([ls])
    await submit_leitstelle(leitstelle_id=ls.id, ctx=(MagicMock(), org, "admin"), db=db)
    assert ls.status == "pending"
    assert ls.proposed_by_org_id == org.id


@pytest.mark.asyncio
async def test_org_cannot_edit_global():
    from app.api.routes.org_leitstellen import update_leitstelle
    from app.schemas.leitstelle import LeistelleUpdate
    from fastapi import HTTPException
    org = MagicMock(id=uuid.uuid4())
    org.name = "Org X"
    # A global leitstelle (org_id=None) is visible but not owned.
    ls = _make_ls(status="global", org_id=None)
    db = _mock_db([ls])
    with pytest.raises(HTTPException) as exc:
        await update_leitstelle(
            leitstelle_id=ls.id, data=LeistelleUpdate(name="x"),
            ctx=(MagicMock(), org, "admin"), db=db,
        )
    assert exc.value.status_code == 403
