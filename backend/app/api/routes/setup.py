import logging
import re

import bcrypt
from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.settings import SystemSetting
from app.models.user import User
from app.schemas.setup import SetupRequest, SetupStatusResponse
from app.services.caddy_config import CERTS_DIR, generate_caddyfile, reload_caddy
from app.services.password import assert_password_not_breached, validate_password

router = APIRouter(prefix="/setup", tags=["setup"])
logger = logging.getLogger(__name__)


async def _superadmin_exists(db: AsyncSession) -> bool:
    result = await db.execute(select(User).where(User.is_superadmin.is_(True)))
    return result.scalar_one_or_none() is not None


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status(db: AsyncSession = Depends(get_db)):
    return SetupStatusResponse(setup_required=not await _superadmin_exists(db))


@router.post("", status_code=201)
async def run_setup(data: SetupRequest, db: AsyncSession = Depends(get_db)):
    # Advisory lock prevents concurrent setup requests from both creating a superadmin
    lock = await db.execute(text("SELECT pg_try_advisory_xact_lock(1)"))
    if not lock.scalar():
        raise HTTPException(409, "Setup already in progress")

    if await _superadmin_exists(db):
        raise HTTPException(409, "Setup already completed")

    # Validate domain format
    if not re.match(r'^[a-zA-Z0-9._-]+$', data.domain):
        raise HTTPException(400, "Invalid domain format")

    if data.tls_mode == "custom" and (not data.cert_pem or not data.key_pem):
        raise HTTPException(400, "cert_pem and key_pem are required for custom TLS")

    if data.tls_mode == "custom" and data.cert_pem and data.key_pem:
        try:
            x509.load_pem_x509_certificate(data.cert_pem.encode())
        except Exception:
            raise HTTPException(400, "Invalid certificate PEM format")
        try:
            load_pem_private_key(data.key_pem.encode(), password=None)
        except Exception:
            raise HTTPException(400, "Invalid private key PEM format")

    if len(data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    validate_password(data.password)
    await assert_password_not_breached(data.password)

    # Create superadmin
    user = User(
        email=data.email,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        is_superadmin=True,
    )
    db.add(user)

    # Optional: erste Org mit Slug anlegen
    if data.org_name and data.org_slug:
        slug = re.sub(r"[^a-z0-9-]+", "", data.org_slug.lower().strip()).strip("-")[:8]
        await db.flush()          # user.id wird erst nach flush vergeben
        org = Organization(name=data.org_name, slug=slug, owner_id=user.id)
        db.add(org)
        await db.flush()          # org.id verfügbar
        membership = UserOrganization(
            user_id=user.id,
            organization_id=org.id,
            role="admin",
        )
        db.add(membership)

    # Persist settings
    for key, value in [
        ("domain", data.domain),
        ("tls_mode", data.tls_mode),
        ("acme_email", data.acme_email),
    ]:
        db.add(SystemSetting(key=key, value=value))

    await db.commit()

    # Write files after successful commit so DB is always the source of truth
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    if data.tls_mode == "custom" and data.cert_pem and data.key_pem:
        (CERTS_DIR / "cert.pem").write_text(data.cert_pem)
        (CERTS_DIR / "key.pem").write_text(data.key_pem)
        (CERTS_DIR / "key.pem").chmod(0o600)

    # Write Caddyfile to shared volume (persists across restarts). Note that
    # this file is authoritative from here on — Caddy's entrypoint prefers it
    # over its env-var fallback — so `caddy_config.ensure_security_headers()`
    # re-checks it on every backend start and regenerates it if it ever falls
    # behind the current hardening baseline.
    caddyfile = generate_caddyfile(data.domain, data.tls_mode, data.acme_email)
    (CERTS_DIR / "Caddyfile").write_text(caddyfile)

    # Live-reload Caddy
    reloaded = await reload_caddy(caddyfile)

    return {"status": "ok", "caddy_reloaded": reloaded}
