import json
import uuid
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape, mapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.leitstelle import Leitstelle
from app.models.user import User
from app.schemas.leitstelle import (
    LeistelleCreate, LeistelleUpdate,
    LeistelleResponse, LeistelleDetailResponse, ZusatzKanal,
)

router = APIRouter(prefix="/leitstellen", tags=["leitstellen"])


def _to_response(ls: Leitstelle) -> LeistelleResponse:
    kanaele = [ZusatzKanal(**k) for k in (ls.zusatz_kanaele or [])]
    return LeistelleResponse(
        id=ls.id,
        name=ls.name,
        anrufgruppe=ls.anrufgruppe,
        zusatz_kanaele=kanaele,
        has_geometry=ls.geometry is not None,
    )


def _to_detail_response(ls: Leitstelle) -> LeistelleDetailResponse:
    kanaele = [ZusatzKanal(**k) for k in (ls.zusatz_kanaele or [])]
    geojson = None
    if ls.geometry is not None:
        try:
            geojson = mapping(to_shape(ls.geometry))
        except Exception:
            geojson = None
    return LeistelleDetailResponse(
        id=ls.id,
        name=ls.name,
        anrufgruppe=ls.anrufgruppe,
        zusatz_kanaele=kanaele,
        has_geometry=ls.geometry is not None,
        geometry_geojson=geojson,
    )


@router.get("/", response_model=list[LeistelleResponse])
async def list_leitstellen(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Leitstelle).order_by(Leitstelle.name))
    return [_to_response(ls) for ls in result.scalars().all()]


@router.get("/{leitstelle_id}", response_model=LeistelleDetailResponse)
async def get_leitstelle(
    leitstelle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")
    return _to_detail_response(ls)


@router.post("/", response_model=LeistelleResponse, status_code=201)
async def create_leitstelle(
    data: LeistelleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    ls = Leitstelle(
        name=data.name,
        anrufgruppe=data.anrufgruppe,
        zusatz_kanaele=[k.model_dump() for k in data.zusatz_kanaele],
    )
    db.add(ls)
    await db.commit()
    await db.refresh(ls)
    return _to_response(ls)


@router.put("/{leitstelle_id}", response_model=LeistelleResponse)
async def update_leitstelle(
    leitstelle_id: uuid.UUID,
    data: LeistelleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")
    if data.name is not None:
        ls.name = data.name
    if data.anrufgruppe is not None:
        ls.anrufgruppe = data.anrufgruppe
    if data.zusatz_kanaele is not None:
        ls.zusatz_kanaele = [k.model_dump() for k in data.zusatz_kanaele]
    await db.commit()
    await db.refresh(ls)
    return _to_response(ls)


@router.delete("/{leitstelle_id}", status_code=204)
async def delete_leitstelle(
    leitstelle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")
    await db.delete(ls)
    await db.commit()


@router.post("/{leitstelle_id}/boundary", response_model=LeistelleResponse)
async def import_boundary(
    leitstelle_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")

    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".kml"):
        poly = _parse_kml(content)
    else:
        poly = _parse_geojson(content)

    if poly is None:
        raise HTTPException(400, "No valid Polygon/MultiPolygon found in file")

    ls.geometry = from_shape(poly, srid=4326)
    await db.commit()
    await db.refresh(ls)
    return _to_response(ls)


def _parse_geojson(content: bytes):
    try:
        data = json.loads(content)
    except Exception:
        return None
    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
        if not features:
            return None
        data = features[0]
    if data.get("type") == "Feature":
        data = data.get("geometry", {})
    if data.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    try:
        return shape(data)
    except Exception:
        return None


def _parse_kml(content: bytes):
    try:
        root = ET.fromstring(content)
    except Exception:
        return None
    for ns_uri in ("http://www.opengis.net/kml/2.2", "http://earth.google.com/kml/2.0"):
        ns = {"k": ns_uri}
        coords_el = root.find(".//k:coordinates", ns)
        if coords_el is not None and coords_el.text:
            pts = []
            for token in coords_el.text.strip().split():
                parts = token.split(",")
                if len(parts) >= 2:
                    try:
                        pts.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue
            if len(pts) >= 3:
                from shapely.geometry import Polygon
                return Polygon(pts)
    return None
