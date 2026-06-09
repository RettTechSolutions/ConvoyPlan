import json
import uuid
import defusedxml.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superadmin
from app.database import get_db
from app.models.leitstelle import Leitstelle
from app.models.organization import Organization
from app.models.user import User
from app.schemas.leitstelle import (
    LeistelleCreate, LeistelleUpdate, LeistelleReject,
    LeistelleResponse, LeistelleDetailResponse, ZusatzKanal,
)

router = APIRouter(prefix="/leitstellen", tags=["leitstellen"])


# ── Shared helpers (also used by the org-scoped router) ────────────────────────

async def org_name_map(db: AsyncSession, ids) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await db.execute(
        select(Organization.id, Organization.name).where(Organization.id.in_(ids))
    )
    return {r.id: r.name for r in rows.all()}


def to_response(ls: Leitstelle, org_names: dict[uuid.UUID, str] | None = None) -> LeistelleResponse:
    org_names = org_names or {}
    kanaele = [ZusatzKanal(**k) for k in (ls.zusatz_kanaele or [])]
    return LeistelleResponse(
        id=ls.id,
        name=ls.name,
        anrufgruppe=ls.anrufgruppe,
        zusatz_kanaele=kanaele,
        has_geometry=ls.geometry is not None,
        district_codes=ls.district_codes or [],
        org_id=ls.org_id,
        org_name=org_names.get(ls.org_id) if ls.org_id else None,
        status=ls.status,
        proposed_by_org_id=ls.proposed_by_org_id,
        proposed_by_org_name=org_names.get(ls.proposed_by_org_id) if ls.proposed_by_org_id else None,
        review_note=ls.review_note,
    )


def to_detail_response(ls: Leitstelle, org_names: dict[uuid.UUID, str] | None = None) -> LeistelleDetailResponse:
    base = to_response(ls, org_names)
    geojson = None
    if ls.geometry is not None:
        try:
            geojson = mapping(to_shape(ls.geometry))
        except Exception:
            geojson = None
    return LeistelleDetailResponse(**base.model_dump(), geometry_geojson=geojson)


async def responses_for(db: AsyncSession, items: list[Leitstelle]) -> list[LeistelleResponse]:
    ids = {ls.org_id for ls in items} | {ls.proposed_by_org_id for ls in items}
    names = await org_name_map(db, ids)
    return [to_response(ls, names) for ls in items]


def geojson_feature_collection(items: list[Leitstelle], org_names: dict[uuid.UUID, str] | None = None) -> dict:
    org_names = org_names or {}
    features = []
    for ls in items:
        if ls.geometry is None:
            continue
        try:
            geom = mapping(to_shape(ls.geometry))
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "id": str(ls.id),
                "name": ls.name,
                "anrufgruppe": ls.anrufgruppe,
                "status": ls.status,
                "org_name": org_names.get(ls.org_id) if ls.org_id else None,
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ── Superadmin / global management ─────────────────────────────────────────────

@router.get("/", response_model=list[LeistelleResponse])
async def list_leitstellen(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(select(Leitstelle).order_by(Leitstelle.name))
    return await responses_for(db, list(result.scalars().all()))


@router.get("/geojson")
async def leitstellen_geojson(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(select(Leitstelle).where(Leitstelle.geometry.isnot(None)))
    items = list(result.scalars().all())
    names = await org_name_map(db, {ls.org_id for ls in items})
    return geojson_feature_collection(items, names)


@router.get("/{leitstelle_id}", response_model=LeistelleDetailResponse)
async def get_leitstelle(
    leitstelle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    ls = await _get_or_404(db, leitstelle_id)
    names = await org_name_map(db, {ls.org_id, ls.proposed_by_org_id})
    return to_detail_response(ls, names)


@router.post("/", response_model=LeistelleResponse, status_code=201)
async def create_leitstelle(
    data: LeistelleCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    ls = Leitstelle(
        name=data.name,
        anrufgruppe=data.anrufgruppe,
        zusatz_kanaele=[k.model_dump() for k in data.zusatz_kanaele],
        district_codes=data.district_codes,
        org_id=None,
        status="global",
    )
    db.add(ls)
    await db.commit()
    await db.refresh(ls)
    return to_response(ls)


@router.put("/{leitstelle_id}", response_model=LeistelleResponse)
async def update_leitstelle(
    leitstelle_id: uuid.UUID,
    data: LeistelleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    ls = await _get_or_404(db, leitstelle_id)
    _apply_update(ls, data)
    await db.commit()
    await db.refresh(ls)
    names = await org_name_map(db, {ls.org_id, ls.proposed_by_org_id})
    return to_response(ls, names)


@router.delete("/{leitstelle_id}", status_code=204)
async def delete_leitstelle(
    leitstelle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    ls = await _get_or_404(db, leitstelle_id)
    await db.delete(ls)
    await db.commit()


@router.post("/{leitstelle_id}/approve", response_model=LeistelleResponse)
async def approve_leitstelle(
    leitstelle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Einen org-Vorschlag freigeben: die Leitstelle wird global und
    superadmin-verwaltet (org_id wird gelöst, Herkunft bleibt erhalten)."""
    ls = await _get_or_404(db, leitstelle_id)
    if ls.status != "pending":
        raise HTTPException(status_code=409, detail="Leitstelle ist kein offener Vorschlag")
    ls.status = "global"
    if ls.org_id and not ls.proposed_by_org_id:
        ls.proposed_by_org_id = ls.org_id
    ls.org_id = None
    ls.review_note = None
    await db.commit()
    await db.refresh(ls)
    names = await org_name_map(db, {ls.proposed_by_org_id})
    return to_response(ls, names)


@router.post("/{leitstelle_id}/reject", response_model=LeistelleResponse)
async def reject_leitstelle(
    leitstelle_id: uuid.UUID,
    data: LeistelleReject,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Einen org-Vorschlag ablehnen: die Leitstelle bleibt org-lokal."""
    ls = await _get_or_404(db, leitstelle_id)
    if ls.status != "pending":
        raise HTTPException(status_code=409, detail="Leitstelle ist kein offener Vorschlag")
    ls.status = "rejected"
    ls.review_note = data.note
    await db.commit()
    await db.refresh(ls)
    names = await org_name_map(db, {ls.org_id, ls.proposed_by_org_id})
    return to_response(ls, names)


@router.post("/{leitstelle_id}/boundary", response_model=LeistelleDetailResponse)
async def import_boundary(
    leitstelle_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    ls = await _get_or_404(db, leitstelle_id)
    poly = await _read_boundary_file(file)
    ls.geometry = from_shape(poly, srid=4326)
    await db.commit()
    await db.refresh(ls)
    names = await org_name_map(db, {ls.org_id, ls.proposed_by_org_id})
    return to_detail_response(ls, names)


# ── Internal helpers ───────────────────────────────────────────────────────────

async def _get_or_404(db: AsyncSession, leitstelle_id: uuid.UUID) -> Leitstelle:
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(status_code=404, detail="Leitstelle not found")
    return ls


def _apply_update(ls: Leitstelle, data: LeistelleUpdate) -> None:
    if data.name is not None:
        ls.name = data.name
    if data.anrufgruppe is not None:
        ls.anrufgruppe = data.anrufgruppe
    if data.zusatz_kanaele is not None:
        ls.zusatz_kanaele = [k.model_dump() for k in data.zusatz_kanaele]
    if data.district_codes is not None:
        ls.district_codes = data.district_codes


_MAX_BOUNDARY_BYTES = 5 * 1024 * 1024  # 5 MB hard cap for KML/GeoJSON uploads


async def _read_boundary_file(file: UploadFile):
    content = await file.read(_MAX_BOUNDARY_BYTES + 1)
    if len(content) > _MAX_BOUNDARY_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")
    filename = (file.filename or "").lower()
    poly = _parse_kml(content) if filename.endswith(".kml") else _parse_geojson(content)
    if poly is None:
        raise HTTPException(status_code=400, detail="No valid Polygon/MultiPolygon found in file")
    return poly


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
