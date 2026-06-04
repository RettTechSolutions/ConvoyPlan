import logging
import os
import re
from pathlib import Path

import bcrypt
import httpx
from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.organization import Organization, UserOrganization
from app.models.settings import SystemSetting
from app.models.user import User
from app.schemas.setup import SetupRequest, SetupStatusResponse

router = APIRouter(prefix="/setup", tags=["setup"])
logger = logging.getLogger(__name__)

CERTS_DIR = Path("/certs")


async def _superadmin_exists(db: AsyncSession) -> bool:
    result = await db.execute(select(User).where(User.is_superadmin.is_(True)))
    return result.scalar_one_or_none() is not None


def _security_header_block(domain: str) -> str:
    """Caddy `header` block: hardening headers + a Content-Security-Policy.

    The CSP is shipped in *Report-Only* mode by default (it cannot break the
    UI — browsers only report violations). Set `CSP_ENFORCE=true` to switch to
    an enforcing policy once it has been verified for the deployment.
    """
    csp = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'self'; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "worker-src 'self' blob:; font-src 'self' data:; "
        "connect-src 'self' https://tile.openstreetmap.org "
        f"https://nominatim.openstreetmap.org ws://{domain} wss://{domain}"
    )
    csp_header = (
        "Content-Security-Policy"
        if os.environ.get("CSP_ENFORCE", "false").lower() == "true"
        else "Content-Security-Policy-Report-Only"
    )
    return f"""header {{
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "geolocation=(self), microphone=(), camera=()"
        {csp_header} "{csp}"
        -Server
    }}"""


def _generate_caddyfile(domain: str, tls_mode: str, acme_email: str) -> str:
    if tls_mode == "custom":
        tls_directive = "tls /certs/cert.pem /certs/key.pem"
    elif tls_mode == "internal":
        tls_directive = "tls internal"
    else:
        tls_directive = ""  # auto Let's Encrypt

    header_block = _security_header_block(domain)

    return f"""{{
    admin 0.0.0.0:2019
    email {acme_email}
}}

{domain} {{
    {tls_directive}

    {header_block}

    # SSE live-log endpoint — flush every chunk immediately
    handle /api/admin/update-log {{
        reverse_proxy backend:8000 {{
            flush_interval -1
        }}
    }}
    handle /api/* {{
        reverse_proxy backend:8000
    }}
    handle /ws/* {{
        reverse_proxy backend:8000 {{
            flush_interval -1
        }}
    }}
    handle {{
        reverse_proxy frontend:3000
    }}
}}
"""


async def _reload_caddy(caddyfile: str) -> bool:
    """Push new Caddyfile to Caddy's admin API at :2019.

    NOTE: Caddy admin is bound to 0.0.0.0:2019 so this backend container can reach it
    on the Docker bridge network. The port is not exposed to the host (no ports: entry
    in docker-compose.yml for the caddy admin port), so exposure is limited to the
    internal Docker network.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: adapt Caddyfile -> JSON
            adapt = await client.post(
                f"{settings.caddy_admin_url}/adapt",
                content=caddyfile.encode(),
                params={"adapter": "caddyfile"},
            )
            adapt.raise_for_status()
            # Step 2: load JSON config (Caddy /adapt returns {"result": ..., "warnings": [...]})
            adapted_config = adapt.json()["result"]
            load = await client.post(
                f"{settings.caddy_admin_url}/load",
                json=adapted_config,
            )
            load.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Caddy reload failed (will apply on next start): %s", exc)
        return False


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

    # Write Caddyfile to shared volume (persists across restarts)
    caddyfile = _generate_caddyfile(data.domain, data.tls_mode, data.acme_email)
    (CERTS_DIR / "Caddyfile").write_text(caddyfile)

    # Live-reload Caddy
    reloaded = await _reload_caddy(caddyfile)

    return {"status": "ok", "caddy_reloaded": reloaded}
