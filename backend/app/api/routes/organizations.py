import uuid
from typing import Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.database import get_db
from app.models.organization import Organization, UserOrganization, _slugify
from app.models.user import User
from app.schemas.user import InviteUserRequest, UserResponse

router = APIRouter(prefix="/organizations", tags=["organizations"])


class OrgCreate(BaseModel):
    name: str
    description: str | None = None


OrgRole = Literal["beobachter", "fahrer", "planer", "admin"]


class OrgMemberAdd(BaseModel):
    email: str
    role: OrgRole = "beobachter"


class OrgMemberRoleUpdate(BaseModel):
    role: OrgRole


class OrgMemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    member_count: int
    my_role: str

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[OrgResponse])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Organization)
        .options(selectinload(Organization.members))
        .join(UserOrganization, (UserOrganization.organization_id == Organization.id) & (UserOrganization.user_id == current_user.id), isouter=True)
        .where(
            (Organization.owner_id == current_user.id)
            | (UserOrganization.user_id == current_user.id)
        )
    )
    orgs = result.scalars().unique().all()

    out = []
    for org in orgs:
        my_role = "admin" if org.owner_id == current_user.id else next(
            (m.role for m in org.members if m.user_id == current_user.id), "beobachter"
        )
        out.append(OrgResponse(
            id=org.id, name=org.name, description=org.description,
            member_count=len(org.members), my_role=my_role,
        ))
    return out


@router.post("/", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrgCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Generate a unique slug from the org name
    base = _slugify(data.name) or "org"
    slug = base[:77]  # leave room for suffix "-99"
    i = 2
    while True:
        existing_slug = await db.execute(select(Organization).where(Organization.slug == slug))
        if existing_slug.scalar_one_or_none() is None:
            break
        slug = f"{base[:77]}-{i}"
        i += 1

    org = Organization(name=data.name, description=data.description, owner_id=current_user.id, slug=slug)
    db.add(org)
    await db.flush()
    membership = UserOrganization(user_id=current_user.id, organization_id=org.id, role="admin")
    db.add(membership)
    await db.commit()
    await db.refresh(org)
    return OrgResponse(id=org.id, name=org.name, description=org.description, member_count=1, my_role="admin")


@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    data: OrgMemberAdd,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_org_admin(org_id, current_user.id, db)

    user_result = await db.execute(select(User).where(User.email == data.email))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    existing = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user.id,
            UserOrganization.organization_id == org_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Benutzer ist bereits Mitglied")

    db.add(UserOrganization(user_id=user.id, organization_id=org_id, role=data.role))
    await db.commit()
    return {"status": "added", "email": data.email, "role": data.role}


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_org_admin(org_id, current_user.id, db)
    result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.organization_id == org_id,
            UserOrganization.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership:
        await db.delete(membership)
        await db.commit()


@router.get("/{org_id}/members", response_model=list[OrgMemberResponse])
async def list_members(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only members and owner can list
    result = await db.execute(
        select(Organization)
        .options(selectinload(Organization.members))
        .where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden")
    is_member = org.owner_id == current_user.id or any(m.user_id == current_user.id for m in org.members)
    if not is_member:
        raise HTTPException(status_code=403, detail="Kein Zugriff")

    out = []
    for m in org.members:
        user_result = await db.execute(select(User).where(User.id == m.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            out.append(OrgMemberResponse(user_id=m.user_id, email=user.email, role=m.role))
    return out


@router.patch("/{org_id}/members/{user_id}", status_code=status.HTTP_200_OK)
async def update_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: OrgMemberRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_org_admin(org_id, current_user.id, db)
    result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.organization_id == org_id,
            UserOrganization.user_id == user_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    membership.role = data.role
    await db.commit()
    return {"status": "updated", "role": data.role}


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id, Organization.owner_id == current_user.id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden")
    await db.delete(org)
    await db.commit()


async def _get_org_admin(org_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation nicht gefunden")
    if org.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Nur der Organisationsinhaber darf Mitglieder verwalten")
    return org


@router.post("/{org_id}/members/invite", response_model=UserResponse, status_code=201)
async def invite_member(
    org_id: uuid.UUID,
    data: InviteUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_org_admin(org_id, current_user.id, db)

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=data.email,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(user)
    await db.flush()

    new_membership = UserOrganization(
        user_id=user.id,
        organization_id=org_id,
        role="beobachter",
    )
    db.add(new_membership)
    await db.commit()
    await db.refresh(user)
    return user
