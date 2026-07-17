"""Best-effort IP geolocation for demo sessions.

Resolves the creating client's IP to a rough location ("Stadt, Region, Land")
via ipapi.co (HTTPS, keyless, generous free tier — demo creation is already
rate-limited to 10/h per IP, so the volume stays far below any quota).

The lookup runs as a FastAPI background task after the demo session has been
returned to the client, so a slow or unreachable geo API never delays or
breaks demo creation. Failures are logged and swallowed — the IP itself is
stored either way.
"""

import ipaddress
import logging
import uuid

import httpx
from sqlalchemy import select

from app.database import get_db_session
from app.models.organization import Organization

logger = logging.getLogger(__name__)

_LOOKUP_URL = "https://ipapi.co/{ip}/json/"
_TIMEOUT = 5.0


def _is_lookupable(ip: str | None) -> bool:
    """Only public IPs are worth a lookup (dev setups hand us loopback/LAN IPs)."""
    if not ip:
        return False
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return parsed.is_global


async def lookup_location(ip: str | None) -> str | None:
    """Resolve *ip* to "Stadt, Region, Land" (best effort, None on any failure)."""
    if not _is_lookupable(ip):
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_LOOKUP_URL.format(ip=ip))
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.info("GeoIP lookup failed for %s", ip, exc_info=True)
        return None
    if data.get("error"):
        return None
    parts = [data.get("city"), data.get("region"), data.get("country_name")]
    location = ", ".join(p for p in parts if p)
    return location[:255] or None


async def resolve_demo_origin(org_id: uuid.UUID, ip: str | None) -> None:
    """Background task: geolocate *ip* and store the result on the demo org."""
    location = await lookup_location(ip)
    if not location:
        return
    try:
        async with get_db_session() as db:
            result = await db.execute(
                select(Organization).where(Organization.id == org_id, Organization.is_demo.is_(True))
            )
            org = result.scalar_one_or_none()
            if org is None:  # session already terminated in the meantime
                return
            org.demo_created_location = location
            await db.commit()
    except Exception:
        logger.warning("Storing demo geo location failed for org %s", org_id, exc_info=True)
