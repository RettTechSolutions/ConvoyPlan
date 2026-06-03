"""Org-scoped Leitstellen management.

An organization sees global Leitstellen (approved / superadmin-managed) plus its
own. Org admins can create org-local Leitstellen, edit/delete their own, and
submit them as proposals to become global (reviewed by the superadmin).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from geoalchemy2.shape import from_shape
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OrgCtx, get_org_context
from app.api.guards import ROLE_ORDER
from app.database import get_db
from app.models.leitstelle import Leitstelle
from app.schemas.leitstelle import (
    LeistelleCreate, LeistelleUpdate,
    LeistelleResponse, LeistelleDetailResponse,
)
from app.api.routes.leitstellen import (
    to_response, to_detail_response, responses_for,
    geojson_feature_collection, org_name_map, _apply_update, _read_boundary_file,
)

router = APIRouter(prefix="/org/leitstellen", tags=["leitstellen"])


def _require_admin(role: str) -> None:
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["admin"]:
        raise HTTPException(status_code=403, detail="Org-Adminrechte erforderlich")


def _visible_filter(org_id: uuid.UUID):
    # Global (approved) Leitstellen plus this org's own.
    return or_(Leitstelle.status == "global", Leitstelle.org_id == org_id)


async def _get_visible(db: AsyncSession, leitstelle_id: uuid.UUID, org_id: uuid.UUID) -> Leitstelle:
    result = await db.execute(
        select(Leitstelle).where(Leitstelle.id == leitstelle_id, _visible_filter(org_id))
    )
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(status_code=404, detail="Leitstelle not found")
    return ls


def _ensure_owned(ls: Leitstelle, org_id: uuid.UUID) -> None:
    if ls.org_id != org_id:
        raise HTTPException(status_code=403, detail="Globale Leitstellen können nur vom Superadmin bearbeitet werden")


@router.get("/", response_model=list[LeistelleResponse])
async def list_leitstellen(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, _role = ctx
    result = await db.execute(
        select(Leitstelle).where(_visible_filter(org.id)).order_by(Leitstelle.name)
    )
    return await responses_for(db, list(result.scalars().all()))


@router.get("/geojson")
async def leitstellen_geojson(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, _role = ctx
    result = await db.execute(
        select(Leitstelle).where(_visible_filter(org.id), Leitstelle.geometry.isnot(None))
    )
    items = list(result.scalars().all())
    names = await org_name_map(db, {ls.org_id for ls in items})
    return geojson_feature_collection(items, names)


@router.get("/{leitstelle_id}", response_model=LeistelleDetailResponse)
async def get_leitstelle(
    leitstelle_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, _role = ctx
    ls = await _get_visible(db, leitstelle_id, org.id)
    names = await org_name_map(db, {ls.org_id, ls.proposed_by_org_id})
    return to_detail_response(ls, names)


@router.post("/", response_model=LeistelleResponse, status_code=201)
async def create_leitstelle(
    data: LeistelleCreate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, role = ctx
    _require_admin(role)
    ls = Leitstelle(
        name=data.name,
        anrufgruppe=data.anrufgruppe,
        zusatz_kanaele=[k.model_dump() for k in data.zusatz_kanaele],
        district_codes=data.district_codes,
        org_id=org.id,
        status="local",
    )
    db.add(ls)
    await db.commit()
    await db.refresh(ls)
    return to_response(ls, {org.id: org.name})


@router.put("/{leitstelle_id}", response_model=LeistelleResponse)
async def update_leitstelle(
    leitstelle_id: uuid.UUID,
    data: LeistelleUpdate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, role = ctx
    _require_admin(role)
    ls = await _get_visible(db, leitstelle_id, org.id)
    _ensure_owned(ls, org.id)
    _apply_update(ls, data)
    await db.commit()
    await db.refresh(ls)
    return to_response(ls, {org.id: org.name})


@router.delete("/{leitstelle_id}", status_code=204)
async def delete_leitstelle(
    leitstelle_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, role = ctx
    _require_admin(role)
    ls = await _get_visible(db, leitstelle_id, org.id)
    _ensure_owned(ls, org.id)
    await db.delete(ls)
    await db.commit()


@router.post("/{leitstelle_id}/submit", response_model=LeistelleResponse)
async def submit_leitstelle(
    leitstelle_id: uuid.UUID,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Die org-eigene Leitstelle als Vorschlag zur globalen Freigabe einreichen."""
    _, org, role = ctx
    _require_admin(role)
    ls = await _get_visible(db, leitstelle_id, org.id)
    _ensure_owned(ls, org.id)
    if ls.status not in ("local", "rejected"):
        raise HTTPException(status_code=409, detail="Leitstelle wurde bereits eingereicht")
    ls.status = "pending"
    ls.proposed_by_org_id = org.id
    ls.review_note = None
    await db.commit()
    await db.refresh(ls)
    return to_response(ls, {org.id: org.name})


@router.post("/{leitstelle_id}/boundary", response_model=LeistelleDetailResponse)
async def import_boundary(
    leitstelle_id: uuid.UUID,
    file: UploadFile = File(...),
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    _, org, role = ctx
    _require_admin(role)
    ls = await _get_visible(db, leitstelle_id, org.id)
    _ensure_owned(ls, org.id)
    poly = await _read_boundary_file(file)
    ls.geometry = from_shape(poly, srid=4326)
    await db.commit()
    await db.refresh(ls)
    return to_detail_response(ls, {org.id: org.name})
