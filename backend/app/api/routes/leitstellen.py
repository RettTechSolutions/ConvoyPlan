import json
import uuid
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import unary_union
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
    base = _to_response(ls)
    geojson = None
    if ls.geometry is not None:
        try:
            geojson = mapping(to_shape(ls.geometry))
        except Exception:
            geojson = None
    return LeistelleDetailResponse(**base.model_dump(), geometry_geojson=geojson)


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
        raise HTTPException(status_code=404, detail="Leitstelle not found")
    return _to_detail_response(ls)


@router.post("/", response_model=LeistelleResponse, status_code=201)
async def create_leitstelle(
    data: LeistelleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required")
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
        raise HTTPException(status_code=403, detail="Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(status_code=404, detail="Leitstelle not found")
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
        raise HTTPException(status_code=403, detail="Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(status_code=404, detail="Leitstelle not found")
    await db.delete(ls)
    await db.commit()


@router.post("/{leitstelle_id}/boundary", response_model=LeistelleDetailResponse)
async def import_boundary(
    leitstelle_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(status_code=404, detail="Leitstelle not found")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")
    filename = (file.filename or "").lower()

    if filename.endswith(".kml"):
        poly = _parse_kml(content)
    else:
        poly = _parse_geojson(content)

    if poly is None:
        raise HTTPException(status_code=400, detail="No valid Polygon/MultiPolygon found in file")

    ls.geometry = from_shape(poly, srid=4326)
    await db.commit()
    await db.refresh(ls)
    return _to_detail_response(ls)


def _geom_from_obj(obj):
    """Extract a Polygon/MultiPolygon shape from a GeoJSON Feature or geometry."""
    if not isinstance(obj, dict):
        return None
    if obj.get("type") == "Feature":
        obj = obj.get("geometry") or {}
    if not isinstance(obj, dict) or obj.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    try:
        return shape(obj)
    except Exception:
        return None


def _parse_geojson(content: bytes):
    try:
        data = json.loads(content)
    except Exception:
        return None
    geoms = []
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        for feat in data.get("features", []):
            g = _geom_from_obj(feat)
            if g is not None and not g.is_empty:
                geoms.append(g)
    else:
        g = _geom_from_obj(data)
        if g is not None and not g.is_empty:
            geoms.append(g)
    if not geoms:
        return None
    if len(geoms) == 1:
        return geoms[0]
    # Mehrere Flächen (z.B. ausgewählte Landkreise) zu einem Gebiet verschmelzen,
    # damit innere Grenzen verschwinden (wichtig für die Kanalwechsel-Berechnung).
    try:
        return unary_union(geoms)
    except Exception:
        return geoms[0]


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
                return Polygon(pts)
    return None
