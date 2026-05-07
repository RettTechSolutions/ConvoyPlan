import logging
import re
from pathlib import Path

import bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.settings import SystemSetting
from app.models.user import User
from app.schemas.setup import SetupRequest, SetupStatusResponse

router = APIRouter(prefix="/setup", tags=["setup"])
logger = logging.getLogger(__name__)

CERTS_DIR = Path("/certs")


async def _superadmin_exists(db: AsyncSession) -> bool:
    result = await db.execute(select(User).where(User.is_superadmin == True))
    return result.scalar_one_or_none() is not None


def _generate_caddyfile(domain: str, tls_mode: str, acme_email: str) -> str:
    if tls_mode == "custom":
        tls_directive = "tls /certs/cert.pem /certs/key.pem"
    elif tls_mode == "internal":
        tls_directive = "tls internal"
    else:
        tls_directive = ""  # auto Let's Encrypt

    return f"""{{
    admin 0.0.0.0:2019
    email {acme_email}
}}

{domain} {{
    {tls_directive}

    handle /api/* {{
        reverse_proxy backend:8000
    }}
    handle /ws/* {{
        reverse_proxy backend:8000
    }}
    handle {{
        reverse_proxy frontend:3000
    }}
}}
"""


async def _reload_caddy(caddyfile: str) -> bool:
    """Push new Caddyfile to Caddy's admin API. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: adapt Caddyfile -> JSON
            adapt = await client.post(
                f"{settings.caddy_admin_url}/adapt",
                content=caddyfile.encode(),
                params={"adapter": "caddyfile"},
            )
            adapt.raise_for_status()
            # Step 2: load JSON config
            load = await client.post(
                f"{settings.caddy_admin_url}/load",
                content=adapt.content,
                headers={"Content-Type": "application/json"},
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
    if await _superadmin_exists(db):
        raise HTTPException(409, "Setup already completed")

    # Validate domain format
    if not re.match(r'^[a-zA-Z0-9._-]+$', data.domain):
        raise HTTPException(400, "Invalid domain format")

    # Create superadmin
    user = User(
        email=data.email,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        is_superadmin=True,
    )
    db.add(user)

    # Persist settings
    for key, value in [
        ("domain", data.domain),
        ("tls_mode", data.tls_mode),
        ("acme_email", data.acme_email),
    ]:
        db.add(SystemSetting(key=key, value=value))

    await db.commit()

    # Write cert files if custom TLS
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    if data.tls_mode == "custom" and data.cert_pem and data.key_pem:
        (CERTS_DIR / "cert.pem").write_text(data.cert_pem)
        (CERTS_DIR / "key.pem").write_text(data.key_pem)

    # Write Caddyfile to shared volume (persists across restarts)
    caddyfile = _generate_caddyfile(data.domain, data.tls_mode, data.acme_email)
    (CERTS_DIR / "Caddyfile").write_text(caddyfile)

    # Live-reload Caddy
    reloaded = await _reload_caddy(caddyfile)

    return {"status": "ok", "caddy_reloaded": reloaded}
