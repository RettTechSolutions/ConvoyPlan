import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, require_superadmin
from app.models.organization import UserOrganization
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserResponse, AdminUserUpdate, AdminUserOrgInfo

router = APIRouter(prefix="/admin", tags=["admin"])


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
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_superadmin is not None:
        user.is_superadmin = data.is_superadmin
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
