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
    u.mfa_enabled = False
    u.mfa_secret = None
    u.token_version = 0
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
    import jwt as _jwt
    from app.config import settings
    payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert payload["org_slug"] == "test-org"
    assert payload["role"] == "planer"
    assert payload["is_superadmin"] is False


@pytest.mark.asyncio
async def test_org_login_is_case_insensitive_for_email():
    """A mixed-/upper-case e-mail must log in against a lower-cased stored
    address. The route queries ``User.email == data.email``, so the request
    schema has to normalise the address before it reaches the DB."""
    user = _user(email="test@example.com")
    org = _org()
    mem = _membership("planer")
    db = _mock_db(user, org, mem)

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={
                "email": "  Test@Example.COM ",
                "password": "secret",
                "org_slug": "test-org",
            })
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200

    # The address bound into the first DB query must be normalised.
    first_stmt = db.execute.call_args_list[0].args[0]
    bound = list(first_stmt.compile().params.values())
    assert "test@example.com" in bound
    assert not any(isinstance(v, str) and v != v.lower() for v in bound)


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
    import jwt as _jwt
    from app.config import settings
    payload = _jwt.decode(r.json()["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
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
