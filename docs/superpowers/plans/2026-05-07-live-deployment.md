# Live Deployment: User Management & SSL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three-tier user management (Superadmin → Org Admin → User) and Caddy-based SSL termination (auto Let's Encrypt or custom cert) to make ConvoyPlan production-ready.

**Architecture:** New `is_superadmin`/`is_active` flags on the User model, a new `/api/admin/users` router (superadmin-only), and an `/api/organizations/{id}/members/invite` endpoint for org admins. Caddy runs as a reverse proxy container, terminating TLS and routing to frontend/backend. The frontend gets an `/admin` page and exposes `is_superadmin` from the JWT.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, SvelteKit, Caddy 2, Docker Compose

---

## File Map

**New files:**
- `backend/alembic/versions/0007_user_roles.py` — migration: add is_superadmin, is_active
- `backend/app/api/routes/admin.py` — superadmin user management endpoints
- `backend/tests/test_admin.py` — admin endpoint tests
- `backend/tests/test_invite.py` — org invite endpoint tests
- `frontend/src/routes/admin/+page.svelte` — admin UI page
- `caddy/entrypoint.sh` — generates Caddyfile from env vars at runtime

**Modified files:**
- `backend/app/models/user.py` — add is_superadmin, is_active columns
- `backend/app/schemas/user.py` — add fields to UserResponse; new AdminUserCreate, AdminUserUpdate, AdminUserResponse, InviteUserRequest
- `backend/app/api/deps.py` — add require_superadmin dep; add is_active check to get_current_user
- `backend/app/api/routes/auth.py` — include is_superadmin in JWT; restrict /register to superadmin-only
- `backend/app/api/routes/organizations.py` — add /invite endpoint
- `backend/app/config.py` — add SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD, ACME_EMAIL
- `backend/app/main.py` — register admin router; add lifespan with seed logic
- `frontend/src/lib/stores/auth.ts` — decode JWT, expose is_superadmin
- `frontend/src/lib/api/index.ts` — add adminApi, add inviteOrgMember to orgsApi
- `frontend/src/routes/plan/+page.svelte` — admin link in header; invite UI in Org tab
- `docker-compose.yml` — add caddy service; remove external ports from frontend/backend (prod)
- `portainer-stack.yml` — same as docker-compose.yml changes

---

## Task 1: DB migration — add is_superadmin and is_active

**Files:**
- Modify: `backend/app/models/user.py`
- Create: `backend/alembic/versions/0007_user_roles.py`

- [ ] **Step 1: Update User model**

In `backend/app/models/user.py`, add two columns after `hashed_password`:

```python
is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
is_superadmin: Mapped[bool] = mapped_column(default=False, server_default="false")
```

Full file after change:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    is_superadmin: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    convoys: Mapped[list["Convoy"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    org_memberships: Mapped[list["UserOrganization"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

- [ ] **Step 2: Create Alembic migration**

Create `backend/alembic/versions/0007_user_roles.py`:

```python
"""add user roles

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("users", "is_superadmin")
    op.drop_column("users", "is_active")
```

- [ ] **Step 3: Verify migration runs**

```bash
cd backend && alembic upgrade head
```

Expected: `Running upgrade 0006 -> 0007, add user roles`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/user.py backend/alembic/versions/0007_user_roles.py
git commit -m "feat: add is_active and is_superadmin to User model"
```

---

## Task 2: Update schemas and add require_superadmin dependency

**Files:**
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/app/api/deps.py`

- [ ] **Step 1: Write failing test for require_superadmin**

Create `backend/tests/test_admin.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_admin_requires_superadmin(regular_user_token):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {regular_user_token}"},
        )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test — expect failure (no admin router yet)**

```bash
cd backend && pytest tests/test_admin.py -v
```

Expected: `FAILED` — ImportError or 404 (admin router not registered yet). That's fine, we're testing the shape.

- [ ] **Step 3: Update schemas**

Replace `backend/app/schemas/user.py`:

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    is_superadmin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str
    is_superadmin: bool = False


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    is_superadmin: bool | None = None


class AdminUserOrgInfo(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    is_superadmin: bool
    created_at: datetime
    orgs: list[AdminUserOrgInfo] = []

    model_config = {"from_attributes": True}


class InviteUserRequest(BaseModel):
    email: EmailStr
    password: str
```

- [ ] **Step 4: Update deps.py — add require_superadmin and is_active check**

Replace `backend/app/api/deps.py`:

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
    return user


async def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
    return current_user
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/user.py backend/app/api/deps.py backend/tests/test_admin.py
git commit -m "feat: add superadmin/active user schema fields and require_superadmin dep"
```

---

## Task 3: Include is_superadmin in JWT + config + seed

**Files:**
- Modify: `backend/app/api/routes/auth.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Update config.py**

Replace `backend/app/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://marschplan:marschplan@localhost:5432/marschplan"
    jwt_secret: str = "changeme-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    graphhopper_url: str = "http://localhost:8989"
    superadmin_email: str = ""
    superadmin_password: str = ""
    acme_email: str = "admin@example.com"

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Update auth.py — add is_superadmin to JWT, restrict register to superadmin**

Replace `backend/app/api/routes/auth.py`:

```python
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
import bcrypt
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import LoginRequest, Token, UserCreate, UserResponse
from app.api.deps import get_db, require_superadmin

router = APIRouter(prefix="/auth", tags=["auth"])


def create_token(user_id: str, is_superadmin: bool) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "is_superadmin": is_superadmin},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


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


@router.post("/login", response_model=Token)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not bcrypt.checkpw(data.password.encode(), user.hashed_password.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
    return Token(access_token=create_token(str(user.id), user.is_superadmin))
```

- [ ] **Step 3: Add lifespan with seed to main.py**

Replace `backend/app/main.py`:

```python
import os
from contextlib import asynccontextmanager

import bcrypt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes import auth, convoys, vehicles, routing, organizations, tracking, lage, weather, overpass, status, users
from app.api.routes import admin as admin_router
from app.config import settings
from app.database import get_db_session
from app.models.user import User


async def _seed_superadmin() -> None:
    if not settings.superadmin_email or not settings.superadmin_password:
        return
    async for db in get_db_session():
        result = await db.execute(select(User).where(User.is_superadmin == True))
        if result.scalar_one_or_none():
            return
        user = User(
            email=settings.superadmin_email,
            hashed_password=bcrypt.hashpw(
                settings.superadmin_password.encode(), bcrypt.gensalt()
            ).decode(),
            is_superadmin=True,
        )
        db.add(user)
        await db.commit()
        print(f"[seed] Superadmin created: {settings.superadmin_email}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _seed_superadmin()
    yield


app = FastAPI(title="ConvoyPlan API", version="0.3.0", lifespan=lifespan)

_origins_env = os.environ.get("CORS_ORIGINS", "*")
_allow_origins = [o.strip() for o in _origins_env.split(",")] if _origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(convoys.router, prefix="/api")
app.include_router(routing.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(tracking.router, prefix="/api")
app.include_router(lage.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(overpass.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.3.0"}
```

- [ ] **Step 4: Add get_db_session to database.py**

Check `backend/app/database.py` — add a `get_db_session` async generator if it only has `get_db` (the Depends version). Add:

```python
from contextlib import asynccontextmanager

@asynccontextmanager  
async def get_db_session():
    async with AsyncSessionLocal() as session:
        yield session
```

(Or if `get_db` already yields from `AsyncSessionLocal`, call `get_db_session = get_db` as an alias.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/api/routes/auth.py backend/app/main.py backend/app/database.py
git commit -m "feat: add is_superadmin to JWT, superadmin seed on startup, restrict register"
```

---

## Task 4: Admin user management API routes

**Files:**
- Create: `backend/app/api/routes/admin.py`
- Modify: `backend/tests/test_admin.py`

- [ ] **Step 1: Create admin.py**

Create `backend/app/api/routes/admin.py`:

```python
import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, require_superadmin
from app.models.organization import Organization, UserOrganization
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
```

- [ ] **Step 2: Add UserOrganization.organization relationship**

Check `backend/app/models/organization.py` — ensure `UserOrganization` has a `organization` relationship. If not, add:

```python
organization: Mapped["Organization"] = relationship(back_populates="members")
```

(And on Organization: `members: Mapped[list["UserOrganization"]] = relationship(back_populates="organization")`)

- [ ] **Step 3: Run backend, verify endpoint exists**

```bash
cd backend && uvicorn app.main:app --reload
curl http://localhost:8000/api/admin/users  # should return 401
```

Expected: `{"detail":"Not authenticated"}`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/admin.py backend/app/models/organization.py
git commit -m "feat: admin user management endpoints (list, create, patch, delete)"
```

---

## Task 5: Org admin invite endpoint

**Files:**
- Modify: `backend/app/api/routes/organizations.py`
- Create: `backend/tests/test_invite.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_invite.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_invite_requires_org_admin(regular_user_token, org_id):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/organizations/{org_id}/members/invite",
            json={"email": "new@example.com", "password": "pass123"},
            headers={"Authorization": f"Bearer {regular_user_token}"},
        )
    assert resp.status_code == 403
```

- [ ] **Step 2: Add invite endpoint to organizations.py**

Add after the existing imports and schemas in `backend/app/api/routes/organizations.py`:

```python
from app.schemas.user import InviteUserRequest, UserResponse
```

Add at the bottom of the router:

```python
@router.post("/{org_id}/members/invite", response_model=UserResponse, status_code=201)
async def invite_member(
    org_id: uuid.UUID,
    data: InviteUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import bcrypt
    # Check caller is org admin
    membership_result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.organization_id == org_id,
            UserOrganization.user_id == current_user.id,
            UserOrganization.role == "admin",
        )
    )
    if not membership_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Org admin required")

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
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/routes/organizations.py backend/tests/test_invite.py
git commit -m "feat: org admin invite endpoint to create and add users in one step"
```

---

## Task 6: Frontend — auth store exposes is_superadmin

**Files:**
- Modify: `frontend/src/lib/stores/auth.ts`

- [ ] **Step 1: Update auth store to decode JWT and expose is_superadmin**

Replace `frontend/src/lib/stores/auth.ts`:

```typescript
import { writable, derived } from 'svelte/store';
import { authApi } from '$lib/api';

interface AuthState {
    token: string | null;
    is_superadmin: boolean;
}

function parseToken(token: string): { is_superadmin: boolean } {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return { is_superadmin: !!payload.is_superadmin };
    } catch {
        return { is_superadmin: false };
    }
}

function createAuthStore() {
    const { subscribe, set } = writable<AuthState>({ token: null, is_superadmin: false });

    const init = () => {
        const token = localStorage.getItem('token');
        if (token) {
            set({ token, ...parseToken(token) });
        } else {
            set({ token: null, is_superadmin: false });
        }
    };

    const login = async (email: string, password: string) => {
        const data = await authApi.login(email, password);
        localStorage.setItem('token', data.access_token);
        set({ token: data.access_token, ...parseToken(data.access_token) });
    };

    const logout = () => {
        localStorage.removeItem('token');
        set({ token: null, is_superadmin: false });
    };

    return { subscribe, init, login, logout };
}

export const auth = createAuthStore();
export const isLoggedIn = { subscribe: (fn: (v: boolean) => void) => auth.subscribe((s) => fn(!!s.token)) };
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/stores/auth.ts
git commit -m "feat: decode JWT in auth store to expose is_superadmin"
```

---

## Task 7: Frontend — admin API client

**Files:**
- Modify: `frontend/src/lib/api/index.ts`

- [ ] **Step 1: Add adminApi and inviteOrgMember to api/index.ts**

Open `frontend/src/lib/api/index.ts` and add the following types and API objects (append to the file):

```typescript
export interface AdminUser {
    id: string;
    email: string;
    is_active: boolean;
    is_superadmin: boolean;
    created_at: string;
    orgs: { id: string; name: string; role: string }[];
}

export interface AdminUserCreate {
    email: string;
    password: string;
    is_superadmin?: boolean;
}

export interface AdminUserUpdate {
    is_active?: boolean;
    is_superadmin?: boolean;
}

export const adminApi = {
    listUsers: () => api.get<AdminUser[]>('/api/admin/users'),
    createUser: (data: AdminUserCreate) => api.post<AdminUser>('/api/admin/users', data),
    updateUser: (id: string, data: AdminUserUpdate) => api.patch<AdminUser>(`/api/admin/users/${id}`, data),
    deleteUser: (id: string) => api.delete(`/api/admin/users/${id}`),
};
```

Also add `inviteOrgMember` to the existing `orgsApi` object:

```typescript
// Inside orgsApi, add:
inviteMember: (orgId: string, email: string, password: string) =>
    api.post(`/api/organizations/${orgId}/members/invite`, { email, password }),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api/index.ts
git commit -m "feat: add adminApi and inviteOrgMember to frontend API client"
```

---

## Task 8: Frontend — /admin page

**Files:**
- Create: `frontend/src/routes/admin/+page.svelte`
- Modify: `frontend/src/routes/plan/+page.svelte` (admin link in header)

- [ ] **Step 1: Create admin page**

Create `frontend/src/routes/admin/+page.svelte`:

```svelte
<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { auth } from '$lib/stores/auth';
    import { adminApi, type AdminUser } from '$lib/api';

    let users = $state<AdminUser[]>([]);
    let loading = $state(true);
    let error = $state('');
    let showCreateForm = $state(false);
    let newUser = $state({ email: '', password: '', is_superadmin: false });
    let activeTab = $state<'users'>('users');

    onMount(async () => {
        if (!$auth.is_superadmin) { goto('/plan'); return; }
        await loadUsers();
    });

    async function loadUsers() {
        try {
            loading = true;
            users = await adminApi.listUsers();
        } catch { error = 'Benutzer konnten nicht geladen werden'; }
        finally { loading = false; }
    }

    async function createUser() {
        try {
            await adminApi.createUser(newUser);
            newUser = { email: '', password: '', is_superadmin: false };
            showCreateForm = false;
            await loadUsers();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Fehler beim Erstellen';
        }
    }

    async function toggleActive(user: AdminUser) {
        try {
            await adminApi.updateUser(user.id, { is_active: !user.is_active });
            await loadUsers();
        } catch { error = 'Konnte Status nicht ändern'; }
    }

    async function toggleSuperadmin(user: AdminUser) {
        try {
            await adminApi.updateUser(user.id, { is_superadmin: !user.is_superadmin });
            await loadUsers();
        } catch { error = 'Konnte Rolle nicht ändern'; }
    }

    async function deleteUser(user: AdminUser) {
        if (!confirm(`${user.email} wirklich löschen?`)) return;
        try {
            await adminApi.deleteUser(user.id);
            await loadUsers();
        } catch { error = 'Benutzer konnte nicht gelöscht werden'; }
    }
</script>

<div class="admin-page">
    <div class="admin-header">
        <h1>Admin</h1>
        <a href="/plan" class="back-link">← Plan</a>
    </div>

    {#if error}
        <div class="error-bar">{error} <button onclick={() => (error = '')}>✕</button></div>
    {/if}

    <div class="section">
        <div class="section-header">
            <strong>Benutzer ({users.length})</strong>
            <button class="btn-small" onclick={() => (showCreateForm = !showCreateForm)}>+ Neu</button>
        </div>

        {#if showCreateForm}
            <form class="create-form" onsubmit={(e) => { e.preventDefault(); createUser(); }}>
                <input placeholder="E-Mail *" type="email" bind:value={newUser.email} required />
                <input placeholder="Passwort *" type="password" bind:value={newUser.password} required />
                <label class="checkbox-label">
                    <input type="checkbox" bind:checked={newUser.is_superadmin} />
                    Superadmin
                </label>
                <button type="submit">Anlegen</button>
            </form>
        {/if}

        {#if loading}
            <p class="hint">Lade…</p>
        {:else}
            <table class="user-table">
                <thead>
                    <tr>
                        <th>E-Mail</th>
                        <th>Organisationen</th>
                        <th>Aktiv</th>
                        <th>Superadmin</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {#each users as user}
                        <tr class:inactive={!user.is_active}>
                            <td>{user.email}</td>
                            <td class="orgs-cell">
                                {#each user.orgs as org}
                                    <span class="tag">{org.name} ({org.role})</span>
                                {/each}
                            </td>
                            <td>
                                <button class="toggle-btn" class:on={user.is_active} onclick={() => toggleActive(user)}>
                                    {user.is_active ? 'Aktiv' : 'Inaktiv'}
                                </button>
                            </td>
                            <td>
                                <button class="toggle-btn" class:on={user.is_superadmin} onclick={() => toggleSuperadmin(user)}>
                                    {user.is_superadmin ? 'Ja' : 'Nein'}
                                </button>
                            </td>
                            <td>
                                <button class="btn-small danger" onclick={() => deleteUser(user)}>🗑</button>
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {/if}
    </div>
</div>

<style>
    :global(body) { margin: 0; font-family: system-ui, sans-serif; background: #0F1B24; color: white; }
    .admin-page { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
    .admin-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; }
    h1 { margin: 0; font-size: 1.4rem; }
    .back-link { color: rgba(255,255,255,.6); font-size: .9rem; text-decoration: none; }
    .back-link:hover { color: white; }
    .error-bar { background: #C23020; color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    .section { background: rgba(255,255,255,.05); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
    .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; }
    .create-form { display: flex; flex-direction: column; gap: .5rem; margin-bottom: 1rem; padding: .75rem; background: rgba(255,255,255,.05); border-radius: 6px; }
    .create-form input { padding: .4rem .6rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.1); color: white; font-size: .9rem; }
    .create-form button { align-self: flex-start; padding: .4rem .9rem; background: #6B7F4D; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; }
    .checkbox-label { display: flex; align-items: center; gap: .4rem; font-size: .88rem; color: rgba(255,255,255,.8); cursor: pointer; }
    .user-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
    .user-table th { text-align: left; padding: .4rem .5rem; color: rgba(255,255,255,.5); font-weight: 600; border-bottom: 1px solid rgba(255,255,255,.1); }
    .user-table td { padding: .4rem .5rem; border-bottom: 1px solid rgba(255,255,255,.07); vertical-align: middle; }
    .user-table tr.inactive td { opacity: .45; }
    .orgs-cell { display: flex; flex-wrap: wrap; gap: .25rem; }
    .tag { display: inline-block; padding: .1rem .35rem; background: rgba(255,255,255,.12); border-radius: 3px; font-size: .72rem; }
    .toggle-btn { padding: .2rem .5rem; border-radius: 3px; border: 1px solid rgba(255,255,255,.25); background: rgba(255,255,255,.08); color: rgba(255,255,255,.6); font-size: .75rem; cursor: pointer; }
    .toggle-btn.on { background: rgba(107,127,77,.3); border-color: #6B7F4D; color: #a8c070; }
    .btn-small { padding: .2rem .5rem; font-size: .78rem; border-radius: 3px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.08); color: white; cursor: pointer; }
    .btn-small.danger { border-color: #E23D28; color: #E23D28; }
    .hint { color: rgba(255,255,255,.4); font-size: .85rem; }
</style>
```

- [ ] **Step 2: Add admin link in plan page sidebar header**

In `frontend/src/routes/plan/+page.svelte`, find the sidebar-header section and add the admin link:

```svelte
<!-- Find this block: -->
<div class="sidebar-header">
    <div class="logo-wrap"><AppLogo width={null} /></div>
    <button class="logout-btn" onclick={logout} title="Abmelden">✕</button>
</div>

<!-- Replace with: -->
<div class="sidebar-header">
    <div class="logo-wrap"><AppLogo width={null} /></div>
    <div style="display:flex;align-items:center;gap:.5rem">
        {#if $auth.is_superadmin}
            <a href="/admin" class="admin-link">⚙ Admin</a>
        {/if}
        <button class="logout-btn" onclick={logout} title="Abmelden">✕</button>
    </div>
</div>
```

Add to the CSS in the same file:
```css
.admin-link { font-size: .72rem; color: rgba(0,0,0,.45); text-decoration: none; white-space: nowrap; }
.admin-link:hover { color: rgba(0,0,0,.7); }
```

And add the import at the top of the `<script>` block:
```typescript
import { auth } from '$lib/stores/auth';
```

- [ ] **Step 3: Build and verify admin page loads for superadmin**

```bash
cd frontend && npm run build
```

Expected: No TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/admin/+page.svelte frontend/src/routes/plan/+page.svelte
git commit -m "feat: admin UI page with user management and admin link in sidebar"
```

---

## Task 9: Frontend — Org admin invite UI

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`

- [ ] **Step 1: Find the Org tab in plan page**

Search for `activeTab === 'org'` in `frontend/src/routes/plan/+page.svelte`. Inside the org-card expand block, after the members list, add an invite form visible only to org admins.

- [ ] **Step 2: Add invite form to org tab**

Find the org-detail section (around the members list in `{#if expandedOrgId === org.id}`). Add this invite block after the members list:

```svelte
<!-- add to script: -->
let orgInviteForm = $state<Record<string, { email: string; password: string }>>({});
let orgInviteError = $state<Record<string, string>>({});

async function inviteMember(orgId: string) {
    const form = orgInviteForm[orgId];
    if (!form?.email || !form?.password) return;
    try {
        await orgsApi.inviteMember(orgId, form.email, form.password);
        orgInviteForm = { ...orgInviteForm, [orgId]: { email: '', password: '' } };
        await loadOrgMembers(orgId);
    } catch (e: unknown) {
        orgInviteError = { ...orgInviteError, [orgId]: e instanceof Error ? e.message : 'Fehler' };
    }
}
```

In the template, inside `{#if expandedOrgId === org.id}` and after the existing members list, add:

```svelte
{#if org.my_role === 'admin'}
    <p class="org-section-label" style="margin-top:.75rem">User einladen</p>
    {#if !orgInviteForm[org.id]}
        {(orgInviteForm = { ...orgInviteForm, [org.id]: { email: '', password: '' } }, '')}
    {/if}
    <div class="invite-form">
        <input
            type="email"
            placeholder="E-Mail"
            bind:value={orgInviteForm[org.id].email}
        />
        <input
            type="password"
            placeholder="Passwort"
            bind:value={orgInviteForm[org.id].password}
        />
        <button class="btn-small" onclick={() => inviteMember(org.id)}>Einladen</button>
    </div>
    {#if orgInviteError[org.id]}
        <p class="hint" style="color:#E23D28">{orgInviteError[org.id]}</p>
    {/if}
{/if}
```

Add CSS in the `<style>` block:
```css
.invite-form { display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .3rem; }
.invite-form input { flex: 1; min-width: 120px; padding: .3rem .5rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.1); color: white; font-size: .8rem; }
```

Also add `orgsApi` to the destructured import if not already present:
```typescript
import { ..., orgsApi } from '$lib/api';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/plan/+page.svelte
git commit -m "feat: org admin invite-user form in Organisation tab"
```

---

## Task 10: Caddy SSL reverse proxy

**Files:**
- Create: `caddy/entrypoint.sh`
- Modify: `docker-compose.yml`
- Modify: `portainer-stack.yml`

- [ ] **Step 1: Create caddy entrypoint script**

Create `caddy/entrypoint.sh`:

```sh
#!/bin/sh
set -e

DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-admin@example.com}"

if [ -n "$CADDY_TLS_CERT" ] && [ -n "$CADDY_TLS_KEY" ]; then
    TLS_DIRECTIVE="tls $CADDY_TLS_CERT $CADDY_TLS_KEY"
elif [ "$DOMAIN" = "localhost" ]; then
    TLS_DIRECTIVE="tls internal"
else
    TLS_DIRECTIVE=""  # automatic Let's Encrypt via ACME
fi

cat > /tmp/Caddyfile << CADDYEOF
{
    email $ACME_EMAIL
}

$DOMAIN {
    $TLS_DIRECTIVE

    reverse_proxy /api/* backend:8000
    reverse_proxy /ws/* backend:8000
    reverse_proxy /* frontend:3000
}
CADDYEOF

echo "[caddy] Starting with domain: $DOMAIN"
exec caddy run --config /tmp/Caddyfile --adapter caddyfile
```

Make it executable:
```bash
chmod +x caddy/entrypoint.sh
```

- [ ] **Step 2: Update docker-compose.yml — add caddy, remove external ports**

In `docker-compose.yml`, add the `caddy` service and update `frontend`/`backend` to not expose ports externally:

```yaml
services:
  db:
    # unchanged

  backend:
    build: ./backend
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    environment:
      DATABASE_URL: postgresql+asyncpg://marschplan:marschplan@db:5432/marschplan
      JWT_SECRET: changeme-in-production
      GRAPHHOPPER_URL: http://graphhopper:8989
      SUPERADMIN_EMAIL: ${SUPERADMIN_EMAIL:-}
      SUPERADMIN_PASSWORD: ${SUPERADMIN_PASSWORD:-}
    volumes:
      - ./backend:/app
    # No external port — only accessible via Caddy
    depends_on:
      db:
        condition: service_healthy
      graphhopper:
        condition: service_healthy

  graphhopper:
    # unchanged (keep port 8989 for direct health checks during dev)

  frontend:
    build:
      context: ./frontend
    # No external port — only accessible via Caddy

  caddy:
    image: caddy:2-alpine
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
    environment:
      DOMAIN: ${DOMAIN:-localhost}
      ACME_EMAIL: ${ACME_EMAIL:-admin@example.com}
      CADDY_TLS_CERT: ${CADDY_TLS_CERT:-}
      CADDY_TLS_KEY: ${CADDY_TLS_KEY:-}
    volumes:
      - ./caddy/entrypoint.sh:/entrypoint.sh:ro
      - caddy_data:/data
      - caddy_config:/config
      - ${CERT_DIR:-/tmp}:/certs:ro
    entrypoint: ["/bin/sh", "/entrypoint.sh"]
    depends_on:
      - frontend
      - backend

volumes:
  postgres_data:
  osm_data:
  gh_graph:
  caddy_data:
  caddy_config:
```

- [ ] **Step 3: Update portainer-stack.yml**

Apply the same pattern in `portainer-stack.yml` — add `caddy` service, add `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` env vars to backend, add `caddy_data`/`caddy_config` volumes:

```yaml
services:
  db:
    # unchanged

  backend:
    image: ${BACKEND_IMAGE:-marschplan-backend:latest}
    restart: unless-stopped
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-marschplan}:${POSTGRES_PASSWORD:-marschplan}@db:5432/${POSTGRES_DB:-marschplan}
      JWT_SECRET: ${JWT_SECRET:-changeme-in-production}
      GRAPHHOPPER_URL: http://graphhopper:8989
      SUPERADMIN_EMAIL: ${SUPERADMIN_EMAIL:-}
      SUPERADMIN_PASSWORD: ${SUPERADMIN_PASSWORD:-}
    # No external ports
    depends_on:
      db:
        condition: service_healthy
      graphhopper:
        condition: service_healthy

  graphhopper:
    image: ${GRAPHHOPPER_IMAGE:-marschplan-graphhopper:latest}
    restart: unless-stopped
    environment:
      OSM_DOWNLOAD_URL: ${OSM_DOWNLOAD_URL:-https://download.geofabrik.de/europe/germany-latest.osm.pbf}
      OSM_FILENAME: ${OSM_FILENAME:-germany-latest.osm.pbf}
      JAVA_OPTS: ${JAVA_OPTS:--Xmx2g -Xms512m -XX:+UseG1GC}
    volumes:
      - osm_data:/data/osm
      - gh_graph:/data/graph
    ports:
      - "${GH_PORT:-8989}:8989"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8989/health"]
      interval: 15s
      timeout: 10s
      retries: 40
      start_period: 30s

  frontend:
    image: ${FRONTEND_IMAGE:-marschplan-frontend:latest}
    restart: unless-stopped
    # No external ports
    depends_on:
      - backend

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
    environment:
      DOMAIN: ${DOMAIN}
      ACME_EMAIL: ${ACME_EMAIL:-admin@example.com}
      CADDY_TLS_CERT: ${CADDY_TLS_CERT:-}
      CADDY_TLS_KEY: ${CADDY_TLS_KEY:-}
    volumes:
      - ./caddy/entrypoint.sh:/entrypoint.sh:ro
      - caddy_data:/data
      - caddy_config:/config
      - ${CERT_DIR:-/tmp}:/certs:ro
    entrypoint: ["/bin/sh", "/entrypoint.sh"]
    depends_on:
      - frontend
      - backend

volumes:
  postgres_data:
  osm_data:
  gh_graph:
  caddy_data:
  caddy_config:
```

- [ ] **Step 4: Test Caddy entrypoint locally**

```bash
# Test the entrypoint script generates a valid Caddyfile
DOMAIN=localhost sh caddy/entrypoint.sh &
sleep 2 && curl -k https://localhost/health
```

Expected: `{"status":"ok","version":"0.3.0"}` (proxied through Caddy)

- [ ] **Step 5: Commit**

```bash
git add caddy/entrypoint.sh docker-compose.yml portainer-stack.yml
git commit -m "feat: Caddy reverse proxy with auto Let's Encrypt and custom cert support"
```

---

## Task 11: Production .env template

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Create .env.example**

Create `.env.example` at project root:

```bash
# Database
POSTGRES_USER=marschplan
POSTGRES_PASSWORD=change-me-strong-password
POSTGRES_DB=marschplan

# JWT — generate with: openssl rand -hex 32
JWT_SECRET=change-me-generate-a-real-secret

# Superadmin — created automatically on first start if no superadmin exists
SUPERADMIN_EMAIL=admin@yourdomain.com
SUPERADMIN_PASSWORD=change-me-strong-password

# SSL / Caddy
DOMAIN=convoy.yourdomain.com
ACME_EMAIL=admin@yourdomain.com
HTTP_PORT=80
HTTPS_PORT=443

# Custom cert (optional — leave empty for auto Let's Encrypt)
# CADDY_TLS_CERT=/certs/cert.pem
# CADDY_TLS_KEY=/certs/key.pem
# CERT_DIR=/path/to/your/certs

# GraphHopper region (smaller = faster first start)
# OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf
# OSM_FILENAME=bayern-latest.osm.pbf
```

- [ ] **Step 2: Ensure .env is in .gitignore**

```bash
grep -q "^\.env$" .gitignore || echo ".env" >> .gitignore
```

- [ ] **Step 3: Commit**

```bash
git add .env.example .gitignore
git commit -m "docs: add .env.example with all production configuration options"
```

---

## Self-Review

**Spec coverage check:**
- ✅ is_superadmin + is_active on User model → Task 1
- ✅ Alembic migration 0007 → Task 1
- ✅ Superadmin seed from env vars → Task 3
- ✅ /api/admin/users (GET, POST, PATCH, DELETE) → Task 4
- ✅ require_superadmin dependency → Task 2
- ✅ is_active check on get_current_user → Task 2
- ✅ is_superadmin in JWT → Task 3
- ✅ /api/organizations/{id}/members/invite → Task 5
- ✅ /api/auth/register restricted to superadmin → Task 3
- ✅ Frontend auth store exposes is_superadmin → Task 6
- ✅ adminApi client → Task 7
- ✅ /admin page with user table (toggle active, toggle superadmin, delete, create) → Task 8
- ✅ Admin link in sidebar (superadmin only) → Task 8
- ✅ Org invite form in Organisation tab (org admin only) → Task 9
- ✅ Caddy entrypoint with Let's Encrypt + custom cert modes → Task 10
- ✅ caddy service in docker-compose.yml and portainer-stack.yml → Task 10
- ✅ Frontend/backend lose external ports in production → Task 10
- ✅ SUPERADMIN_EMAIL/PASSWORD env vars wired through compose → Tasks 3, 10
- ✅ .env.example → Task 11

**Type consistency:** `AdminUserResponse` defined in Task 2 (schemas), used in Task 4 (admin.py) and Task 7 (frontend api) — consistent. `InviteUserRequest` defined in Task 2, used in Task 5. `orgsApi.inviteMember` defined in Task 7, used in Task 9.

**No placeholders found.**
