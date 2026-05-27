import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superadmin
from app.config import settings
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def create_token(
    user_id: str,
    is_superadmin: bool,
    org_id: str | None = None,
    org_slug: str | None = None,
    role: str | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {
            "sub": user_id,
            "exp": expire,
            "is_superadmin": is_superadmin,
            "org_id": org_id,
            "org_slug": org_slug,
            "role": role,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


class LoginRequest(BaseModel):
    email: str
    password: str
    org_slug: str | None = None


@router.post("/login", response_model=Token)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if data.org_slug:
        # ── Org-scoped login ──────────────────────────────────────────────
        org_result = await db.execute(
            select(Organization).where(Organization.slug == data.org_slug)
        )
        org = org_result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user or not bcrypt.checkpw(data.password.encode(), user.hashed_password.encode()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
        mem_result = await db.execute(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.organization_id == org.id,
            )
        )
        membership = mem_result.scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        token = create_token(str(user.id), False, str(org.id), org.slug, membership.role)
        return Token(access_token=token)

    else:
        # ── Superadmin-Login (kein org_slug) ─────────────────────────────
        if not user or not bcrypt.checkpw(data.password.encode(), user.hashed_password.encode()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
        if not user.is_superadmin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
        token = create_token(str(user.id), True)
        return Token(access_token=token)


@router.get("/org-lookup")
async def org_lookup(slug: str, db: AsyncSession = Depends(get_db)):
    """Öffentlicher Endpoint: Org-Name für die Login-Seite.
    Timing-normalisiert um Org-Enumeration zu erschweren."""
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    await asyncio.sleep(0.05)   # konstante Antwortzeit
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation nicht gefunden")
    return {"name": org.name, "slug": org.slug}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=data.email,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
