# Multi-Tenancy Org-Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jede Organisation bekommt eine eigene URL `/o/{slug}/`; User loggen sich org-spezifisch ein und sehen ausschließlich Daten ihrer eigenen Organisation.

**Architecture:** `slug`-Feld auf `Organization` + erweiterter JWT (`org_id`, `role`) → neue `get_org_context`-Dependency filtert alle Queries nach JWT-Org → SvelteKit-Routen unter `o/[slug]/` mit Guard-Layout.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (Backend), SvelteKit 5 Runes + Svelte Stores (Frontend), python-jose JWT, pytest + httpx (Tests)

---

## Datei-Übersicht

### Neu erstellt
| Datei | Zweck |
|---|---|
| `backend/alembic/versions/0012_org_slug.py` | Slug-Spalte + Daten-Migration |
| `backend/tests/test_org_auth.py` | Tests für Org-Login + Lookup |
| `frontend/src/lib/stores/org.ts` | `$orgStore` — aktiver Org-Kontext |
| `frontend/src/routes/o/[slug]/+layout.svelte` | Org-Guard: Token prüfen, Store befüllen |
| `frontend/src/routes/o/[slug]/+page.svelte` | Redirect → `./plan` |
| `frontend/src/routes/o/[slug]/login/+page.svelte` | Org-Login-Formular |
| `frontend/src/routes/o/[slug]/plan/+page.svelte` | Konvoi-Liste (org-scoped) |
| `frontend/src/routes/o/[slug]/plan/[convoyId]/+page.svelte` | Planungsseite (org-scoped) |
| `frontend/src/routes/o/[slug]/admin/+page.svelte` | Org-Admin (org-scoped) |

### Modifiziert
| Datei | Was ändert sich |
|---|---|
| `backend/app/models/organization.py` | `slug`-Feld hinzufügen |
| `backend/app/api/deps.py` | `TokenData`, `get_token_data`, `get_org_context` |
| `backend/app/api/routes/auth.py` | Login um `org_slug`, `create_token` um Org-Felder, neuer `org-lookup`-Endpoint |
| `backend/app/api/routes/convoys.py` | Alle List/Create-Endpoints auf `get_org_context` umstellen |
| `backend/app/api/routes/vehicles.py` | List/Create auf `get_org_context` |
| `backend/app/api/routes/setup.py` | Erste Org + Slug im Setup anlegen |
| `frontend/src/routes/+page.svelte` | Org-Code-Eingabe statt Redirect |
| `frontend/src/routes/+layout.svelte` | `/o/` zu PUBLIC_ROUTES-Ausnahmen |
| `frontend/src/lib/api/client.ts` | Org-spezifischer Token (`token__{slug}`) |
| `frontend/src/lib/api/index.ts` | `orgLookup`-Endpoint |

---

## Task 1: Organization-Model — `slug`-Feld

**Files:**
- Modify: `backend/app/models/organization.py`
- Create: `backend/alembic/versions/0012_org_slug.py`

- [ ] **Schritt 1: Slug-Feld ins Model eintragen**

Ersetze in `backend/app/models/organization.py` die Klasse `Organization`:

```python
import re
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _slugify(text: str) -> str:
    """'Rettdienst München' → 'rettdienst-munchen'"""
    text = text.lower()
    text = text.translate(str.maketrans("äöüß", "aous"))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    members: Mapped[list["UserOrganization"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    convoys: Mapped[list["Convoy"]] = relationship(back_populates="org")
```

- [ ] **Schritt 2: Alembic-Migration erstellen**

Erstelle `backend/alembic/versions/0012_org_slug.py`:

```python
"""add slug to organizations

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-27
"""
import re
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _slugify(text: str) -> str:
    text = text.lower()
    text = text.translate(str.maketrans("äöüß", "aous"))
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


def upgrade() -> None:
    # 1. Spalte nullable hinzufügen
    op.add_column("organizations", sa.Column("slug", sa.String(80), nullable=True))

    # 2. Slugs aus Namen generieren (Python-Loop für Duplikat-Handling)
    conn = op.get_bind()
    orgs = conn.execute(sa.text("SELECT id, name FROM organizations ORDER BY created_at")).fetchall()
    seen: set[str] = set()
    for org in orgs:
        base = _slugify(org.name) or "org"
        slug = base
        i = 2
        while slug in seen:
            slug = f"{base}-{i}"
            i += 1
        seen.add(slug)
        conn.execute(
            sa.text("UPDATE organizations SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": str(org.id)},
        )

    # 3. NOT NULL + UNIQUE
    op.alter_column("organizations", "slug", nullable=False)
    op.create_unique_constraint("uq_organizations_slug", "organizations", ["slug"])
    op.create_index("idx_organizations_slug", "organizations", ["slug"])


def downgrade() -> None:
    op.drop_index("idx_organizations_slug", table_name="organizations")
    op.drop_constraint("uq_organizations_slug", "organizations", type_="unique")
    op.drop_column("organizations", "slug")
```

- [ ] **Schritt 3: Migration anwenden und prüfen**

```bash
cd backend
alembic upgrade head
```

Erwartung: `Running upgrade 0011 -> 0012, add slug to organizations`

- [ ] **Schritt 4: Commit**

```bash
git add backend/app/models/organization.py backend/alembic/versions/0012_org_slug.py
git commit -m "feat: add slug field to Organization model and migration"
```

---

## Task 2: Backend — `TokenData` + `get_org_context` in `deps.py`

**Files:**
- Modify: `backend/app/api/deps.py`

- [ ] **Schritt 1: Failing-Test schreiben**

Erstelle `backend/tests/test_org_deps.py`:

```python
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.api.deps import get_token_data, get_org_context, TokenData
from app.models.organization import Organization, UserOrganization
from app.models.user import User


def _make_token(user_id, org_id=None, org_slug=None, role=None, is_superadmin=False):
    from datetime import datetime, timedelta, timezone
    from jose import jwt
    from app.config import settings
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "is_superadmin": is_superadmin,
        "org_id": str(org_id) if org_id else None,
        "org_slug": org_slug,
        "role": role,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_get_token_data_org_scoped():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token = _make_token(user_id, org_id=org_id, org_slug="test-org", role="planer")
    td = get_token_data(token)
    assert td.user_id == user_id
    assert td.org_id == org_id
    assert td.org_slug == "test-org"
    assert td.role == "planer"
    assert td.is_superadmin is False


def test_get_token_data_superadmin():
    user_id = uuid.uuid4()
    token = _make_token(user_id, is_superadmin=True)
    td = get_token_data(token)
    assert td.user_id == user_id
    assert td.org_id is None
    assert td.is_superadmin is True


def test_get_token_data_invalid_raises():
    with pytest.raises(HTTPException) as exc:
        get_token_data("not.a.token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_org_context_success():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token_data = TokenData(user_id=user_id, org_id=org_id, org_slug="test", role="planer")

    user = MagicMock(spec=User)
    user.id = user_id
    user.is_active = True

    org = MagicMock(spec=Organization)
    org.id = org_id

    membership = MagicMock(spec=UserOrganization)
    membership.role = "planer"

    db = AsyncMock()
    db.get.side_effect = [user, org]
    mem_result = MagicMock()
    mem_result.scalar_one_or_none.return_value = membership
    db.execute.return_value = mem_result

    result_user, result_org, result_role = await get_org_context(token_data, db)
    assert result_role == "planer"
    assert result_org is org


@pytest.mark.asyncio
async def test_get_org_context_no_org_id_raises():
    token_data = TokenData(user_id=uuid.uuid4(), org_id=None)
    with pytest.raises(HTTPException) as exc:
        await get_org_context(token_data, AsyncMock())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_org_context_not_member_raises():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token_data = TokenData(user_id=user_id, org_id=org_id, org_slug="test", role="planer")

    user = MagicMock(spec=User); user.id = user_id; user.is_active = True
    org = MagicMock(spec=Organization); org.id = org_id

    db = AsyncMock()
    db.get.side_effect = [user, org]
    mem_result = MagicMock()
    mem_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mem_result

    with pytest.raises(HTTPException) as exc:
        await get_org_context(token_data, db)
    assert exc.value.status_code == 403
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```bash
cd backend
pytest tests/test_org_deps.py -v
```

Erwartung: `ImportError: cannot import name 'TokenData' from 'app.api.deps'`

- [ ] **Schritt 3: `deps.py` implementieren**

Ersetze `backend/app/api/deps.py` vollständig:

```python
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class TokenData(BaseModel):
    user_id: uuid.UUID
    org_id: uuid.UUID | None = None
    org_slug: str | None = None
    role: str | None = None
    is_superadmin: bool = False


def get_token_data(token: str = Depends(oauth2_scheme)) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        raw_org_id = payload.get("org_id")
        return TokenData(
            user_id=uuid.UUID(user_id_str),
            org_id=uuid.UUID(raw_org_id) if raw_org_id else None,
            org_slug=payload.get("org_slug"),
            role=payload.get("role"),
            is_superadmin=bool(payload.get("is_superadmin", False)),
        )
    except (JWTError, ValueError):
        raise credentials_exception


async def get_current_user(
    token_data: TokenData = Depends(get_token_data),
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
    return user


# Type alias for org-scoped dependencies
OrgCtx = tuple[User, Organization, str]


async def get_org_context(
    token_data: TokenData = Depends(get_token_data),
    db: AsyncSession = Depends(get_db),
) -> OrgCtx:
    if not token_data.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Org context required")

    user = await db.get(User, token_data.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")

    org = await db.get(Organization, token_data.org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation nicht gefunden")

    mem_result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user.id,
            UserOrganization.organization_id == org.id,
        )
    )
    membership = mem_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kein Mitglied dieser Organisation")

    return user, org, membership.role


async def require_superadmin(
    token_data: TokenData = Depends(get_token_data),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token_data.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS**

```bash
cd backend
pytest tests/test_org_deps.py -v
```

Erwartung: alle 6 Tests grün.

- [ ] **Schritt 5: Gesamte Test-Suite läuft noch durch**

```bash
pytest --tb=short -q
```

Erwartung: keine neuen Fehler (bestehende Tests nutzen `dependency_overrides`, die unberührt bleiben).

- [ ] **Schritt 6: Commit**

```bash
git add backend/app/api/deps.py backend/tests/test_org_deps.py
git commit -m "feat: add TokenData, get_token_data, get_org_context to deps"
```

---

## Task 3: Auth-Routes — Org-Login + Org-Lookup

**Files:**
- Modify: `backend/app/api/routes/auth.py`
- Create: `backend/tests/test_org_auth.py`

- [ ] **Schritt 1: Failing-Tests schreiben**

Erstelle `backend/tests/test_org_auth.py`:

```python
import uuid
import bcrypt
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.user import User


# ── Helpers ──────────────────────────────────────────────────────────────────

def _user(email="test@example.com", pw="secret", superadmin=False):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = email
    u.is_active = True
    u.is_superadmin = superadmin
    u.hashed_password = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    return u


def _org(slug="test-org", name="Test Org"):
    o = MagicMock(spec=Organization)
    o.id = uuid.uuid4()
    o.slug = slug
    o.name = name
    return o


def _membership(role="planer"):
    m = MagicMock(spec=UserOrganization)
    m.role = role
    return m


def _mock_db(*execute_returns) -> AsyncMock:
    """Baut eine DB-Mock die .execute() mit den angegebenen Werten beantwortet."""
    db = AsyncMock()
    results = []
    for val in execute_returns:
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        results.append(r)
    db.execute.side_effect = results
    return db


def _db_override(db: AsyncMock):
    """Gibt eine async-Generator-Funktion zurück, die FastAPI als Depends nutzen kann."""
    async def _override():
        yield db
    return _override


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_org_login_success():
    user = _user()
    org = _org()
    mem = _membership("planer")
    db = _mock_db(user, org, mem)

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={
                "email": "test@example.com",
                "password": "secret",
                "org_slug": "test-org",
            })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    token = r.json()["access_token"]
    from jose import jwt
    from app.config import settings
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert payload["org_slug"] == "test-org"
    assert payload["role"] == "planer"
    assert payload["is_superadmin"] is False


@pytest.mark.asyncio
async def test_org_login_wrong_password_returns_401():
    user = _user(pw="correct")
    org = _org()
    db = _mock_db(user, org)

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={
                "email": "test@example.com",
                "password": "wrong",
                "org_slug": "test-org",
            })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_org_login_not_member_returns_401():
    user = _user()
    org = _org()
    db = _mock_db(user, org, None)  # None → kein Membership

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={
                "email": "test@example.com",
                "password": "secret",
                "org_slug": "test-org",
            })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_superadmin_login_without_org_slug():
    user = _user(superadmin=True)
    db = _mock_db(user)

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={
                "email": "test@example.com",
                "password": "secret",
            })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    from jose import jwt
    from app.config import settings
    payload = jwt.decode(r.json()["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert payload["is_superadmin"] is True
    assert payload.get("org_id") is None


@pytest.mark.asyncio
async def test_org_lookup_found():
    org = _org(slug="rettdienst", name="Rettdienst München")
    db = _mock_db(org)

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/auth/org-lookup?slug=rettdienst")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    assert r.json()["name"] == "Rettdienst München"


@pytest.mark.asyncio
async def test_org_lookup_not_found():
    db = _mock_db(None)

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/auth/org-lookup?slug=unknown")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 404
```

- [ ] **Schritt 2: Tests ausführen — müssen FAIL**

```bash
pytest tests/test_org_auth.py -v
```

Erwartung: Fehler da `org_slug` im Login-Body noch nicht existiert.

- [ ] **Schritt 3: `auth.py` implementieren**

Ersetze `backend/app/api/routes/auth.py` vollständig:

```python
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
```

- [ ] **Schritt 4: Tests ausführen — müssen PASS**

```bash
pytest tests/test_org_auth.py -v
```

Erwartung: alle 6 Tests grün.

- [ ] **Schritt 5: Gesamte Suite**

```bash
pytest --tb=short -q
```

- [ ] **Schritt 6: Commit**

```bash
git add backend/app/api/routes/auth.py backend/tests/test_org_auth.py
git commit -m "feat: org-scoped login and org-lookup endpoint"
```

---

## Task 4: Backend — Convoy-Endpoints org-scopen

**Files:**
- Modify: `backend/app/api/routes/convoys.py`

- [ ] **Schritt 1: Failing-Test**

Füge am Ende von `backend/tests/test_guards.py` hinzu:

```python
# ── Org-Context Guard ────────────────────────────────────────────────────────

from app.api.deps import get_org_context, OrgCtx
from app.models.organization import Organization

def _org(org_id=None):
    o = MagicMock(spec=Organization)
    o.id = org_id or uuid.uuid4()
    return o


@pytest.mark.asyncio
async def test_list_convoys_returns_only_org_convoys(monkeypatch):
    """get_org_context muss als Dependency genutzt werden — nicht owner_id allein."""
    from app.api.routes.convoys import router
    # Prüfe dass get_org_context in den Dependencies der list-Route vorkommt
    list_route = next(r for r in router.routes if getattr(r, "path", "") == "/" and "GET" in getattr(r, "methods", []))
    dep_callables = [d.dependency for d in list_route.dependencies]
    assert get_org_context in dep_callables, "list_convoys muss get_org_context nutzen"
```

- [ ] **Schritt 2: Test ausführen — muss FAIL**

```bash
pytest tests/test_guards.py::test_list_convoys_returns_only_org_convoys -v
```

- [ ] **Schritt 3: `convoys.py` anpassen**

Öffne `backend/app/api/routes/convoys.py`. Ändere den Import-Block oben:

```python
# Ersetze die Zeile
from app.api.deps import get_current_user
# durch
from app.api.deps import get_current_user, get_org_context, OrgCtx
```

Ändere den `list_convoys`-Endpoint (suche `@router.get("/")`):

```python
@router.get("/", response_model=list[ConvoyResponse])
async def list_convoys(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    result = await db.execute(
        select(Convoy)
        .where(Convoy.organization_id == org.id)
        .order_by(Convoy.created_at.desc())
    )
    return result.scalars().all()
```

Ändere `create_convoy` (suche `@router.post("/")`):

```python
@router.post("/", response_model=ConvoyResponse, status_code=201)
async def create_convoy(
    data: ConvoyCreate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    convoy = Convoy(**data.model_dump(), owner_id=user.id, organization_id=org.id)
    db.add(convoy)
    await db.commit()
    await db.refresh(convoy)
    return convoy
```

Für alle anderen Endpoints (`get_convoy`, `update_convoy`, `delete_convoy`, etc.) die `get_current_user` nutzen: ersetze deren `user`-Dependency durch `ctx: OrgCtx = Depends(get_org_context)` und passe die Convoy-Access-Prüfung an — der Convoy muss zur Org passen:

```python
# In get_convoy und anderen Endpoints:
user, org, role = ctx
# Stelle sicher dass convoy.organization_id == org.id
if convoy.organization_id != org.id:
    raise HTTPException(404, "Convoy not found")
```

- [ ] **Schritt 4: Test ausführen — muss PASS**

```bash
pytest tests/test_guards.py -v
pytest --tb=short -q
```

- [ ] **Schritt 5: Commit**

```bash
git add backend/app/api/routes/convoys.py backend/tests/test_guards.py
git commit -m "feat: scope convoy endpoints to org context from JWT"
```

---

## Task 5: Backend — Vehicle-Endpoints org-scopen

**Files:**
- Modify: `backend/app/api/routes/vehicles.py`

- [ ] **Schritt 1: `vehicles.py` anpassen**

Öffne `backend/app/api/routes/vehicles.py`. Füge den Import hinzu:

```python
from app.api.deps import get_current_user, get_org_context, OrgCtx
```

Ändere `list_vehicles`:

```python
@router.get("/", response_model=list[VehicleResponse])
async def list_vehicles(
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    # Fahrzeuge aller Mitglieder dieser Org
    from app.models.organization import UserOrganization
    member_ids = select(UserOrganization.user_id).where(
        UserOrganization.organization_id == org.id
    )
    result = await db.execute(
        select(Vehicle)
        .where(Vehicle.owner_id.in_(member_ids))
        .order_by(Vehicle.order_index)
    )
    return result.scalars().all()
```

Ändere `create_vehicle`:

```python
@router.post("/", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    data: VehicleCreate,
    ctx: OrgCtx = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user, org, role = ctx
    vehicle = Vehicle(**data.model_dump(), owner_id=user.id)
    db.add(vehicle)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle
```

- [ ] **Schritt 2: Tests**

```bash
pytest --tb=short -q
```

- [ ] **Schritt 3: Commit**

```bash
git add backend/app/api/routes/vehicles.py
git commit -m "feat: scope vehicle list to org members"
```

---

## Task 6: Frontend — `$orgStore` + org-aware API-Client

**Files:**
- Create: `frontend/src/lib/stores/org.ts`
- Modify: `frontend/src/lib/api/client.ts`
- Modify: `frontend/src/lib/api/index.ts`

- [ ] **Schritt 1: `orgStore` erstellen**

Erstelle `frontend/src/lib/stores/org.ts`:

```typescript
import { writable, get } from 'svelte/store';

export interface OrgContext {
    slug: string;
    org_id: string;
    org_name: string;
    user_id: string;
    user_role: 'beobachter' | 'fahrer' | 'planer' | 'admin';
}

function createOrgStore() {
    const { subscribe, set, update } = writable<OrgContext | null>(null);

    return {
        subscribe,

        /** Wird vom o/[slug]/+layout.svelte aufgerufen */
        setFromToken(slug: string, orgName: string, token: string): void {
            try {
                const payload = JSON.parse(atob(token.split('.')[1]));
                set({
                    slug,
                    org_id: payload.org_id,
                    org_name: orgName,
                    user_id: payload.sub,
                    user_role: payload.role ?? 'beobachter',
                });
            } catch {
                set(null);
            }
        },

        clear(): void {
            set(null);
        },

        getToken(slug: string): string | null {
            return localStorage.getItem(`token__${slug}`);
        },

        setToken(slug: string, token: string): void {
            localStorage.setItem(`token__${slug}`, token);
        },

        removeToken(slug: string): void {
            localStorage.removeItem(`token__${slug}`);
        },
    };
}

export const orgStore = createOrgStore();
```

- [ ] **Schritt 2: API-Client um org-aware Token erweitern**

Öffne `frontend/src/lib/api/client.ts`. Ersetze `getToken()`:

```typescript
// Vorher:
function getToken(): string | null {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem('token');
}

// Nachher:
let _activeSlug: string | null = null;

/** Wird vom Org-Guard-Layout gesetzt bevor API-Calls gemacht werden */
export function setActiveSlug(slug: string | null): void {
    _activeSlug = slug;
}

function getToken(): string | null {
    if (typeof localStorage === 'undefined') return null;
    // Org-scoped token hat Vorrang
    if (_activeSlug) {
        const orgToken = localStorage.getItem(`token__${_activeSlug}`);
        if (orgToken) return orgToken;
    }
    // Fallback: globaler Superadmin-Token
    return localStorage.getItem('token');
}
```

- [ ] **Schritt 3: Org-Lookup zum API-Index hinzufügen**

Öffne `frontend/src/lib/api/index.ts`. Füge am Ende hinzu:

```typescript
export interface OrgLookupResult {
    name: string;
    slug: string;
}

export const orgAuthApi = {
    lookup: (slug: string) => api.get<OrgLookupResult>(`/api/auth/org-lookup?slug=${encodeURIComponent(slug)}`),
    loginOrg: (email: string, password: string, org_slug: string) =>
        api.post<{ access_token: string }>('/api/auth/login', { email, password, org_slug }),
};
```

- [ ] **Schritt 4: Commit**

```bash
git add frontend/src/lib/stores/org.ts frontend/src/lib/api/client.ts frontend/src/lib/api/index.ts
git commit -m "feat: orgStore and org-aware API client"
```

---

## Task 7: Frontend — Root-Page + Org-Guard-Layout

**Files:**
- Modify: `frontend/src/routes/+page.svelte`
- Modify: `frontend/src/routes/+layout.svelte`
- Create: `frontend/src/routes/o/[slug]/+layout.svelte`
- Create: `frontend/src/routes/o/[slug]/+page.svelte`

- [ ] **Schritt 1: Root-Page → Org-Code-Eingabe**

Ersetze `frontend/src/routes/+page.svelte`:

```svelte
<script lang="ts">
    import { goto } from '$app/navigation';
    import { orgAuthApi } from '$lib/api';

    let slugInput = $state('');
    let error = $state('');
    let loading = $state(false);

    async function handleSubmit() {
        const slug = slugInput.trim().toLowerCase();
        if (!slug) return;
        loading = true;
        error = '';
        try {
            await orgAuthApi.lookup(slug);
            goto(`/o/${slug}/login`);
        } catch {
            error = 'Organisation nicht gefunden. Bitte Code prüfen.';
        } finally {
            loading = false;
        }
    }
</script>

<div class="root-page">
    <div class="card">
        <h1>ConvoyPlan</h1>
        <p class="subtitle">Bitte Organisations-Code eingeben</p>
        <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
            <input
                type="text"
                bind:value={slugInput}
                placeholder="z.B. rettdienst-muenchen"
                autocomplete="organization"
                spellcheck="false"
            />
            {#if error}
                <p class="error">{error}</p>
            {/if}
            <button type="submit" disabled={loading}>
                {loading ? 'Suche…' : 'Weiter →'}
            </button>
        </form>
    </div>
</div>

<style>
    .root-page {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        background: var(--color-bg, #f5f5f5);
    }
    .card {
        background: var(--color-surface, #fff);
        border-radius: 12px;
        padding: 2.5rem;
        width: 100%;
        max-width: 380px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    h1 { margin: 0; font-size: 1.6rem; }
    .subtitle { color: var(--color-text-muted, #666); margin: 0; }
    input {
        width: 100%;
        padding: 0.75rem 1rem;
        border: 1px solid var(--color-border, #ddd);
        border-radius: 8px;
        font-size: 1rem;
        box-sizing: border-box;
    }
    button {
        width: 100%;
        padding: 0.75rem;
        background: var(--color-primary, #2563eb);
        color: #fff;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        cursor: pointer;
    }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .error { color: #dc2626; font-size: 0.9rem; margin: 0; }
</style>
```

- [ ] **Schritt 2: Root-Layout um `/o/`-Ausnahme erweitern**

Öffne `frontend/src/routes/+layout.svelte`. Suche die Zeile:

```typescript
const PUBLIC_ROUTES = ['/login', '/share', '/setup'];
```

Ersetze durch:

```typescript
// /o/ hat eigenes Guard-Layout; /tracking/ und /share/ sind öffentlich
const PUBLIC_ROUTES = ['/login', '/share', '/setup', '/tracking', '/o/'];
```

Und passe die Auth-Redirect-Logik an — sie soll bei Routen, die mit `/o/` beginnen, nicht eingreifen:

```typescript
// Suche den Auth-Check im onMount (ungefähr):
//   if (!$auth.token && !PUBLIC_ROUTES.some(r => $page.url.pathname.startsWith(r))) {
//       goto('/login');
//   }
// Diese Zeile bleibt unverändert — PUBLIC_ROUTES enthält jetzt '/o/'
```

- [ ] **Schritt 3: Org-Guard-Layout erstellen**

Erstelle `frontend/src/routes/o/[slug]/+layout.svelte`:

```svelte
<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { orgStore } from '$lib/stores/org';
    import { setActiveSlug } from '$lib/api/client';
    import { orgAuthApi } from '$lib/api';

    let { children } = $props();
    let ready = $state(false);

    onMount(async () => {
        const slug = $page.params.slug;
        const isLoginPage = $page.url.pathname.endsWith('/login');

        // Login-Seite braucht keinen Token-Check
        if (isLoginPage) {
            setActiveSlug(slug);
            ready = true;
            return;
        }

        const token = orgStore.getToken(slug);
        if (!token) {
            goto(`/o/${slug}/login`);
            return;
        }

        // Token-Payload prüfen
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            const exp = payload.exp * 1000;
            if (Date.now() > exp) {
                orgStore.removeToken(slug);
                goto(`/o/${slug}/login`);
                return;
            }
            if (payload.org_slug !== slug) {
                goto(`/o/${slug}/login`);
                return;
            }

            // Org-Name nachladen für den Store
            setActiveSlug(slug);
            let orgName = payload.org_slug; // Fallback
            try {
                const orgInfo = await orgAuthApi.lookup(slug);
                orgName = orgInfo.name;
            } catch { /* ignorieren */ }

            orgStore.setFromToken(slug, orgName, token);
            ready = true;
        } catch {
            goto(`/o/${slug}/login`);
        }
    });
</script>

{#if ready}
    {@render children()}
{/if}
```

- [ ] **Schritt 4: Org-Root-Seite (Redirect)**

Erstelle `frontend/src/routes/o/[slug]/+page.svelte`:

```svelte
<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';

    onMount(() => {
        goto(`/o/${$page.params.slug}/plan`, { replaceState: true });
    });
</script>
```

- [ ] **Schritt 5: App starten und Root-Flow testen**

```bash
cd frontend && npm run dev
```

Öffne `http://localhost:5173/`. Gib einen bekannten Org-Slug ein → Redirect auf `/o/{slug}/login` muss funktionieren. Unbekannter Slug → Fehlermeldung.

- [ ] **Schritt 6: Commit**

```bash
git add frontend/src/routes/+page.svelte \
        frontend/src/routes/+layout.svelte \
        frontend/src/routes/o/
git commit -m "feat: org-code root page and org-guard layout"
```

---

## Task 8: Frontend — Org-Login-Seite

**Files:**
- Create: `frontend/src/routes/o/[slug]/login/+page.svelte`

- [ ] **Schritt 1: Login-Seite erstellen**

Erstelle `frontend/src/routes/o/[slug]/login/+page.svelte`:

```svelte
<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { orgStore } from '$lib/stores/org';
    import { orgAuthApi } from '$lib/api';
    import { setActiveSlug } from '$lib/api/client';

    const slug = $derived($page.params.slug);
    let orgName = $state('');
    let email = $state('');
    let password = $state('');
    let error = $state('');
    let loading = $state(false);

    onMount(async () => {
        // Bereits eingeloggt? Weiterleiten
        const existing = orgStore.getToken(slug);
        if (existing) {
            try {
                const payload = JSON.parse(atob(existing.split('.')[1]));
                if (payload.exp * 1000 > Date.now() && payload.org_slug === slug) {
                    goto(`/o/${slug}/plan`);
                    return;
                }
            } catch { /* abgelaufen oder ungültig */ }
        }

        // Org-Name für Anzeige laden
        try {
            const info = await orgAuthApi.lookup(slug);
            orgName = info.name;
        } catch {
            // Org existiert nicht → zurück zur Root
            goto('/');
        }
    });

    async function handleLogin() {
        if (!email || !password) return;
        loading = true;
        error = '';
        try {
            setActiveSlug(slug);
            const data = await orgAuthApi.loginOrg(email, password, slug);
            orgStore.setToken(slug, data.access_token);
            orgStore.setFromToken(slug, orgName, data.access_token);
            goto(`/o/${slug}/plan`);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Login fehlgeschlagen';
        } finally {
            loading = false;
        }
    }
</script>

<div class="login-page">
    <div class="card">
        {#if orgName}
            <p class="org-label">Anmelden bei</p>
            <h1>{orgName}</h1>
        {:else}
            <h1>Anmelden</h1>
        {/if}

        <form onsubmit={(e) => { e.preventDefault(); handleLogin(); }}>
            <input type="email" bind:value={email} placeholder="E-Mail" autocomplete="email" />
            <input type="password" bind:value={password} placeholder="Passwort" autocomplete="current-password" />
            {#if error}
                <p class="error">{error}</p>
            {/if}
            <button type="submit" disabled={loading}>
                {loading ? 'Anmelden…' : 'Anmelden'}
            </button>
        </form>

        <a href="/" class="back-link">← Andere Organisation</a>
    </div>
</div>

<style>
    .login-page {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        background: var(--color-bg, #f5f5f5);
    }
    .card {
        background: var(--color-surface, #fff);
        border-radius: 12px;
        padding: 2.5rem;
        width: 100%;
        max-width: 380px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    .org-label { color: var(--color-text-muted, #666); margin: 0; font-size: 0.9rem; }
    h1 { margin: 0; font-size: 1.5rem; }
    input {
        width: 100%;
        padding: 0.75rem 1rem;
        border: 1px solid var(--color-border, #ddd);
        border-radius: 8px;
        font-size: 1rem;
        box-sizing: border-box;
    }
    button {
        width: 100%;
        padding: 0.75rem;
        background: var(--color-primary, #2563eb);
        color: #fff;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        cursor: pointer;
    }
    button:disabled { opacity: 0.6; }
    .error { color: #dc2626; font-size: 0.9rem; margin: 0; }
    .back-link { color: var(--color-text-muted, #666); font-size: 0.9rem; text-align: center; }
</style>
```

- [ ] **Schritt 2: Login-Flow manuell testen**

```bash
cd frontend && npm run dev
```

1. `http://localhost:5173/` → Org-Code eingeben → `/o/{slug}/login`
2. E-Mail + Passwort eingeben → erfolgreicher Login → Redirect `/o/{slug}/plan`
3. `/o/{slug}/` direkt aufrufen ohne Token → Redirect `/o/{slug}/login`

- [ ] **Schritt 3: Commit**

```bash
git add frontend/src/routes/o/[slug]/login/
git commit -m "feat: org-specific login page"
```

---

## Task 9: Frontend — Plan-Routen unter `/o/[slug]/plan/`

**Files:**
- Create: `frontend/src/routes/o/[slug]/plan/+page.svelte`
- Create: `frontend/src/routes/o/[slug]/plan/[convoyId]/+page.svelte`

- [ ] **Schritt 1: Plan-Übersichtsseite kopieren und anpassen**

Kopiere den Inhalt von `frontend/src/routes/plan/+page.svelte` nach `frontend/src/routes/o/[slug]/plan/+page.svelte`.

Passe folgende Dinge an:

1. **Auth-Store-Referenz** — ersetze alle `$auth.token`-Prüfungen:

```typescript
// Vorher:
import { auth } from '$lib/stores/auth';
if (!$auth.token) goto('/login');

// Nachher: der Org-Guard-Layout übernimmt Auth-Prüfung — onMount-Check entfernen
import { orgStore } from '$lib/stores/org';
// $orgStore.user_role statt $auth.is_superadmin für Rollenprüfung
```

2. **Navigation** — alle `goto('/plan')` ersetzen durch:

```typescript
import { page } from '$app/stores';
const slug = $page.params.slug;
// goto(`/o/${slug}/plan/${convoyId}`)
```

3. **`page.ts`** — falls vorhanden: kopiere nach `o/[slug]/plan/+page.ts`, `export const ssr = false;` bleibt.

- [ ] **Schritt 2: Planungsseite (Konvoi-Detail) kopieren**

Kopiere `frontend/src/routes/plan/[convoyId]/+page.svelte` → `frontend/src/routes/o/[slug]/plan/[convoyId]/+page.svelte`.

Gleiche Anpassungen wie Schritt 1:
- Auth-Guard-Check im `onMount` entfernen (Org-Layout übernimmt das)
- `goto('/plan')` → ``goto(`/o/${$page.params.slug}/plan`)``
- `goto(`/plan/${id}`)` → ``goto(`/o/${$page.params.slug}/plan/${id}`)``

- [ ] **Schritt 3: Testen**

```bash
cd frontend && npm run dev
```

`/o/{slug}/plan` muss die Konvoi-Liste zeigen (API-Calls gehen mit org-scoped Token).

- [ ] **Schritt 4: Commit**

```bash
git add frontend/src/routes/o/[slug]/plan/
git commit -m "feat: plan routes under org scope"
```

---

## Task 10: Frontend — Admin-Route unter `/o/[slug]/admin/`

**Files:**
- Create: `frontend/src/routes/o/[slug]/admin/+page.svelte`

- [ ] **Schritt 1: Admin-Seite kopieren und anpassen**

Kopiere `frontend/src/routes/admin/+page.svelte` → `frontend/src/routes/o/[slug]/admin/+page.svelte`.

Anpassungen:
```typescript
// Vorher (in onMount):
if (!$auth.is_superadmin) { goto('/plan'); return; }

// Nachher — Org-Admins haben Zugriff, Superadmin-Prüfung entfernen:
import { orgStore } from '$lib/stores/org';
// Nur Org-Admin-Tab zeigen; globale User-Verwaltung entfernen
// $orgStore.user_role === 'admin' prüfen statt is_superadmin
```

Entferne aus dem Org-Admin-Tab alle globalen Funktionen (Superadmin-User-Verwaltung, globale Lizenz-Verwaltung) — das bleibt im Superadmin-Panel unter `/admin`.

- [ ] **Schritt 2: Testen**

`/o/{slug}/admin` muss für Org-Admins die Org-Verwaltung zeigen (Mitglieder, Leitstellen, Branding).

- [ ] **Schritt 3: Commit**

```bash
git add frontend/src/routes/o/[slug]/admin/
git commit -m "feat: org-admin page under org scope"
```

---

## Task 11: Setup-Wizard — Erste Org mit Slug anlegen

**Files:**
- Modify: `backend/app/api/routes/setup.py`
- Modify: `frontend/src/routes/setup/+page.svelte`

- [ ] **Schritt 1: Backend-Setup um Org-Erstellung erweitern**

**Schema zuerst:** Öffne `backend/app/schemas/setup.py`. `SetupRequest` (Zeile 10) bekommt zwei neue Felder am Ende:

```python
class SetupRequest(BaseModel):
    # Admin account
    email: EmailStr
    password: str

    # Server config
    domain: str
    tls_mode: Literal["letsencrypt", "custom", "internal"]
    acme_email: EmailStr = "admin@example.com"

    # Custom cert (PEM content as strings, only when tls_mode == "custom")
    cert_pem: str = ""
    key_pem: str = ""

    # Optional: erste Organisation beim Setup anlegen
    org_name: str | None = None
    org_slug: str | None = None
```

**Route erweitern:** Öffne `backend/app/api/routes/setup.py`. Der User wird in Zeile 113–118 erstellt (`db.add(user)` endet in Zeile 118). Füge nach `db.add(user)` (Zeile 118) und **vor** `# Persist settings` (Zeile 120) ein:

```python
# Import am Anfang der Datei ergänzen:
from app.models.organization import Organization, UserOrganization

# --- nach db.add(user), vor "# Persist settings" ---
    # Optional: erste Org mit Slug anlegen
    if data.org_name and data.org_slug:
        slug = re.sub(r"[^a-z0-9-]+", "-", data.org_slug.lower().strip()).strip("-")
        await db.flush()          # user.id wird erst nach flush vergeben
        org = Organization(name=data.org_name, slug=slug)
        db.add(org)
        await db.flush()          # org.id verfügbar
        membership = UserOrganization(
            user_id=user.id,
            organization_id=org.id,
            role="admin",
        )
        db.add(membership)
    # await db.commit() bleibt in Zeile 128 — committet User + Org + Membership gemeinsam
```

`re` ist in `setup.py` bereits importiert (Zeile 103 nutzt es). Kein neuer Import nötig.

- [ ] **Schritt 2: Frontend-Setup-Wizard erweitern**

Öffne `frontend/src/routes/setup/+page.svelte`. Füge in Schritt 1 (Superadmin-Erstellung) zwei neue Felder hinzu:

```svelte
<!-- Org-Name -->
<input type="text" bind:value={orgName} placeholder="Organisations-Name (z.B. Rettdienst München)" />

<!-- Org-Slug mit Auto-Vorschlag -->
<input
    type="text"
    bind:value={orgSlug}
    placeholder="URL-Code (z.B. rettdienst-muenchen)"
    pattern="[a-z0-9-]+"
/>
```

Auto-Vorschlag beim Tippen des Org-Namens:

```typescript
let orgName = $state('');
let orgSlug = $state('');
let slugManuallyEdited = $state(false);

$effect(() => {
    if (!slugManuallyEdited && orgName) {
        orgSlug = orgName.toLowerCase()
            .replace(/[äöüß]/g, c => ({'ä':'a','ö':'o','ü':'u','ß':'s'}[c] ?? c))
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-|-$/g, '')
            .slice(0, 80);
    }
});
```

Übergib `org_name` und `org_slug` im Submit-Request.

- [ ] **Schritt 3: Testen**

Setup-Flow durchspielen: Superadmin + Org anlegen → Login via `/o/{slug}/login` muss funktionieren.

- [ ] **Schritt 4: Commit**

```bash
git add backend/app/api/routes/setup.py frontend/src/routes/setup/
git commit -m "feat: create first org with slug in setup wizard"
```

---

## Task 12: Gesamttest + Aufräumen

- [ ] **Schritt 1: Vollständige Backend-Test-Suite**

```bash
cd backend && pytest -v
```

Erwartung: alle Tests grün. Neue Tests: `test_org_deps.py` (6), `test_org_auth.py` (6).

- [ ] **Schritt 2: TypeScript-Check**

```bash
cd frontend && npm run check
```

Erwartung: keine Errors.

- [ ] **Schritt 3: Alte Routen mit Redirect versehen**

Damit bestehende Bookmarks nicht ins Leere laufen — füge in die alten Seiten einen Redirect ein:

In `frontend/src/routes/plan/+page.svelte`:
```svelte
<script lang="ts">
    import { goto } from '$app/navigation';
    import { onMount } from 'svelte';
    onMount(() => goto('/'));
</script>
```

In `frontend/src/routes/admin/+page.svelte`:
```svelte
<script lang="ts">
    import { goto } from '$app/navigation';
    import { onMount } from 'svelte';
    onMount(() => goto('/'));
</script>
```

- [ ] **Schritt 4: Final-Commit + Push**

```bash
git add -A
git commit -m "feat: multi-tenancy org isolation complete"
git push origin main
```
