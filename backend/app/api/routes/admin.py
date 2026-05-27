import json
import os
import uuid
from datetime import datetime, timezone

import bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, require_superadmin
from app.config import settings
from app.models.organization import Organization, UserOrganization, _slugify
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserResponse, AdminUserUpdate, AdminUserOrgInfo

router = APIRouter(prefix="/admin", tags=["admin"])

STATUS_FILE = "/update_status/status.json"
TRIGGER_FILE = "/update_status/trigger"


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.org_memberships).selectinload(UserOrganization.organization))
        .order_by(User.created_at)
    )
    users = result.scalars().all()
    out = []
    for u in users:
        orgs = [
            AdminUserOrgInfo(id=m.organization.id, name=m.organization.name, role=m.role)
            for m in u.org_memberships
            if m.organization is not None
        ]
        out.append(AdminUserResponse(
            id=u.id,
            email=u.email,
            is_active=u.is_active,
            is_superadmin=u.is_superadmin,
            created_at=u.created_at,
            orgs=orgs,
        ))
    return out


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def create_user(
    data: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    user = User(
        email=data.email,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        is_superadmin=data.is_superadmin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return AdminUserResponse(id=user.id, email=user.email, is_active=user.is_active,
                             is_superadmin=user.is_superadmin, created_at=user.created_at, orgs=[])


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.org_memberships).selectinload(UserOrganization.organization))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == current.id:
        if data.is_superadmin is False or data.is_active is False:
            raise HTTPException(400, "Cannot demote or deactivate your own account")
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_superadmin is not None:
        user.is_superadmin = data.is_superadmin
    if data.email is not None:
        conflict = await db.execute(select(User).where(User.email == data.email, User.id != user_id))
        if conflict.scalar_one_or_none():
            raise HTTPException(400, "Email already in use")
        user.email = data.email
    if data.password is not None:
        if len(data.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        user.hashed_password = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    await db.commit()
    await db.refresh(user)
    orgs = [
        AdminUserOrgInfo(id=m.organization.id, name=m.organization.name, role=m.role)
        for m in user.org_memberships
        if m.organization is not None
    ]
    return AdminUserResponse(id=user.id, email=user.email, is_active=user.is_active,
                             is_superadmin=user.is_superadmin, created_at=user.created_at, orgs=orgs)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    if user_id == current.id:
        raise HTTPException(400, "Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    await db.delete(user)
    await db.commit()


@router.get("/update-status")
async def get_update_status(
    _: User = Depends(require_superadmin),
):
    deployed_sha = None
    deployed_at = None
    try:
        with open(STATUS_FILE) as f:
            data = json.load(f)
            deployed_sha = data.get("deployed_sha")
            deployed_at = data.get("deployed_at")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Fallback: SHA was baked into the image at build time via ARG GIT_SHA
    if not deployed_sha:
        baked = os.environ.get("GIT_SHA", "")
        if baked and baked != "unknown":
            deployed_sha = baked[:7]

    remote_sha = None
    github_reachable = False
    try:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{settings.github_repo}/commits?sha=main&per_page=1",
                headers=headers,
            )
        if resp.is_success:
            commits = resp.json()
            if commits and isinstance(commits, list):
                remote_sha = commits[0]["sha"][:7]
            github_reachable = True
    except Exception:
        pass

    update_available = bool(
        deployed_sha and remote_sha and deployed_sha[:7] != remote_sha[:7]
    )

    return {
        "deployed_sha": deployed_sha,
        "deployed_at": deployed_at,
        "remote_sha": remote_sha,
        "update_available": update_available,
        "github_reachable": github_reachable,
    }


class AdminOrgAssign(BaseModel):
    org_id: uuid.UUID
    role: str = "beobachter"


@router.post("/users/{user_id}/orgs", status_code=201)
async def admin_add_user_to_org(
    user_id: uuid.UUID,
    data: AdminOrgAssign,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    if not user_result.scalar_one_or_none():
        raise HTTPException(404, "User not found")

    org_result = await db.execute(select(Organization).where(Organization.id == data.org_id))
    if not org_result.scalar_one_or_none():
        raise HTTPException(404, "Organization not found")

    existing = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.organization_id == data.org_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "User is already a member of this organization")

    db.add(UserOrganization(user_id=user_id, organization_id=data.org_id, role=data.role))
    await db.commit()
    return {"status": "added"}


@router.delete("/users/{user_id}/orgs/{org_id}", status_code=204)
async def admin_remove_user_from_org(
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership:
        await db.delete(membership)
        await db.commit()


class AdminOrgCreate(BaseModel):
    name: str
    slug: str


@router.post("/organizations", status_code=201)
async def admin_create_organization(
    data: AdminOrgCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    slug = data.slug.strip().lower()
    # Validate slug chars
    import re as _re
    slug = _re.sub(r"[^a-z0-9-]+", "", slug).strip("-")[:8]
    if not slug:
        raise HTTPException(400, "Invalid slug")

    existing = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Slug already in use")

    org = Organization(name=data.name.strip(), slug=slug, owner_id=current.id)
    db.add(org)
    await db.flush()
    membership = UserOrganization(user_id=current.id, organization_id=org.id, role="admin")
    db.add(membership)
    await db.commit()
    await db.refresh(org)
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "owner_email": current.email,
        "member_count": 1,
    }


@router.get("/organizations")
async def list_all_organizations(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(Organization)
        .options(selectinload(Organization.members), selectinload(Organization.owner))
        .order_by(Organization.name)
    )
    orgs = result.scalars().all()
    return [
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "owner_email": org.owner.email if org.owner else None,
            "member_count": len(org.members),
        }
        for org in orgs
    ]


@router.delete("/organizations/{org_id}", status_code=204)
async def admin_delete_organization(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    await db.delete(org)
    await db.commit()


@router.post("/trigger-update", status_code=202)
async def trigger_update(
    _: User = Depends(require_superadmin),
):
    if os.path.exists(TRIGGER_FILE):
        raise HTTPException(409, "Update already triggered")
    os.makedirs(os.path.dirname(TRIGGER_FILE), exist_ok=True)
    with open(TRIGGER_FILE, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
    return {"status": "triggered"}
