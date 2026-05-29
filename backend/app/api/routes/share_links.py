import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.guards import get_convoy_access
from app.config import settings
from app.database import get_db
from app.models.share_link import ConvoyShareLink
from app.models.user import User
from app.schemas.share_link import (
    ShareLinkCreate,
    ShareLinkCreated,
    ShareLinkResponse,
)
from app.services import share_links as share_links_svc

router = APIRouter(prefix="/convoys", tags=["share-links"])


def _build_url(slug: str, request: Request) -> str:
    base = settings.app_base_url.rstrip("/") if settings.app_base_url else ""
    if not base:
        base = f"{request.url.scheme}://{request.url.netloc}"
    return f"{base}/track/{slug}"


def _to_response(link: ConvoyShareLink, request: Request) -> ShareLinkResponse:
    return ShareLinkResponse(
        id=link.id,
        slug=link.slug,
        scope=link.scope,
        requires_password=link.password_hash is not None,
        created_at=link.created_at,
        last_accessed_at=link.last_accessed_at,
        access_count=link.access_count,
        revoked=link.revoked,
        url=_build_url(link.slug, request),
    )


@router.get("/{convoy_id}/share-links", response_model=list[ShareLinkResponse])
async def list_share_links(
    convoy_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="read")
    result = await db.execute(
        select(ConvoyShareLink)
        .where(ConvoyShareLink.convoy_id == convoy_id)
        .order_by(ConvoyShareLink.created_at.desc())
    )
    return [_to_response(link, request) for link in result.scalars().all()]


@router.post("/{convoy_id}/share-links", response_model=ShareLinkCreated)
async def create_share_link(
    convoy_id: uuid.UUID,
    data: ShareLinkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="write")

    plain_password: str | None = None
    if data.password_mode == "generate":
        plain_password = share_links_svc.generate_password()
        password_hash = share_links_svc.hash_password(plain_password)
    elif data.password_mode == "set":
        assert data.password is not None  # enforced by validator
        password_hash = share_links_svc.hash_password(data.password)
    else:
        password_hash = None

    slug = await share_links_svc.generate_unique_slug(db)
    link = ConvoyShareLink(
        convoy_id=convoy_id,
        slug=slug,
        password_hash=password_hash,
        scope="track",
        created_by_id=current_user.id,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    base = _to_response(link, request)
    return ShareLinkCreated(**base.model_dump(), password_plain=plain_password)


@router.delete("/{convoy_id}/share-links/{link_id}", status_code=204)
async def revoke_share_link(
    convoy_id: uuid.UUID,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="write")
    result = await db.execute(
        select(ConvoyShareLink).where(
            ConvoyShareLink.id == link_id,
            ConvoyShareLink.convoy_id == convoy_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Share-Link nicht gefunden")
    link.revoked = True
    await db.commit()
    return None
