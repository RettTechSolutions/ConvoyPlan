from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superadmin
from app.config import settings
from app.database import get_db
from app.middleware.license_guard import reset_license_cache
from app.models.user import User
from app.services import audit
from app.services import lizenz_ablauf, org_kontingent
from app.services.instance import aktuelle_lizenz, get_or_create_instance_id, save_license_key
from app.services.license import validate_license

router = APIRouter(prefix="/license", tags=["license"])


@router.get("/instance-id")
async def get_instance_id(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Return the installation's machine fingerprint used for license binding."""
    instance_id = await get_or_create_instance_id(db)
    return {"instance_id": instance_id}


@router.get("/status")
async def license_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    instance_id = await get_or_create_instance_id(db)
    key_source = "env" if settings.license_key else "db"
    info = await aktuelle_lizenz(db)
    return await _status_antwort(db, info, instance_id, key_source)


async def _status_antwort(db: AsyncSession, info, instance_id: str, key_source: str) -> dict:
    orgs_vorhanden, orgs_grenze = await org_kontingent.stand(db)
    heute = datetime.now(timezone.utc).date()
    return {
        "valid": info.valid,
        "demo_mode": not info.valid,
        "license_id": info.license_id,
        "customer": info.customer,
        "email": info.email,
        "issued": info.issued,
        "expires": info.expires,
        # Tage bis zum letzten gültigen Tag (0 = heute, negativ = abgelaufen);
        # None ohne lesbares Datum. `expiry_warning` sagt, ob Portal und Banner
        # darauf hinweisen sollen — dieselbe Grenze wie die Mail.
        "expires_in_days": lizenz_ablauf.tage_bis_ablauf(info, heute),
        "expiry_warning": _ablauf_warnen(info, heute),
        "max_users": info.max_users,
        "lts_until": info.lts_until or None,
        "instance_id": instance_id,
        "key_source": key_source,
        "error": info.error if not info.valid else None,
        # Lizenzmodell v2 — bei Altschlüsseln contract="legacy", max_orgs=None.
        "contract": info.contract if info.valid else None,
        "contract_until": info.contract_until or None,
        "contract_ended": org_kontingent.vertrag_beendet(info, heute),
        "max_orgs": info.max_orgs,
        # Was fürs Anlegen gerade gilt (Vertragsende und Demo eingerechnet).
        "orgs_limit": orgs_grenze,
        "orgs_count": orgs_vorhanden,
    }


def _ablauf_warnen(info, heute) -> bool:
    tage = lizenz_ablauf.tage_bis_ablauf(info, heute)
    return info.valid and tage is not None and tage <= lizenz_ablauf.WARN_TAGE


class LicenseActivateRequest(BaseModel):
    license_key: str


@router.post("/activate")
async def activate_license(
    data: LicenseActivateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """Validate and store a license key. Resets the middleware cache."""
    instance_id = await get_or_create_instance_id(db)
    info = validate_license(data.license_key.strip(), instance_id)

    if not info.valid:
        raise HTTPException(status_code=422, detail=info.error)

    await save_license_key(db, data.license_key.strip())
    reset_license_cache()
    await audit.record(
        db, audit.LICENSE_ACTIVATED, request=request, actor_id=current.id,
        actor_email=current.email, detail={"license_id": info.license_id, "customer": info.customer},
    )

    return await _status_antwort(db, info, instance_id, "db")


@router.delete("/")
async def remove_license(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Remove the stored license key, reverting to demo mode."""
    await save_license_key(db, "")
    reset_license_cache()
    return {"demo_mode": True}


@router.get("/mode")
async def license_mode(db: AsyncSession = Depends(get_db)):
    """Public endpoint — no auth required.

    Returns only {demo_mode: bool} so any logged-in frontend client can show
    a banner without exposing instance IDs or license details.
    """
    info = await aktuelle_lizenz(db)
    return {"demo_mode": not info.valid}
