"""Organization-scoped API key generation and verification.

Key format: ``cvp_<prefix>_<secret>``
  - ``prefix``  — 8 hex chars, public, stored in clear for O(1) lookup.
  - ``secret``  — high-entropy random token; only its bcrypt hash is stored.

The plaintext key is returned to the caller exactly once (at creation).
"""
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey

KEY_PREFIX = "cvp_"
# Only refresh last_used_at at most this often to avoid a write per request.
_LAST_USED_THROTTLE_SECONDS = 300


@dataclass
class GeneratedKey:
    prefix: str
    secret: str
    key_hash: str

    @property
    def full_key(self) -> str:
        return f"{KEY_PREFIX}{self.prefix}_{self.secret}"


def generate_key() -> GeneratedKey:
    prefix = secrets.token_hex(4)  # 8 hex chars
    secret = secrets.token_urlsafe(32)
    key_hash = bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()
    return GeneratedKey(prefix=prefix, secret=secret, key_hash=key_hash)


def _parse(raw: str) -> tuple[str, str] | None:
    """Split a presented key into (prefix, secret); None if malformed."""
    if not raw or not raw.startswith(KEY_PREFIX):
        return None
    rest = raw[len(KEY_PREFIX):]
    prefix, _, secret = rest.partition("_")
    if not prefix or not secret:
        return None
    return prefix, secret


def is_expired(key: ApiKey, now: datetime | None = None) -> bool:
    if key.expires_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return key.expires_at <= now


async def resolve_key(db: AsyncSession, raw: str) -> ApiKey | None:
    """Return the matching, valid ApiKey for a presented raw key, or None.

    Validates the bcrypt secret, revocation and expiry. Opportunistically
    refreshes ``last_used_at`` (throttled)."""
    parsed = _parse(raw)
    if not parsed:
        return None
    prefix, secret = parsed

    result = await db.execute(select(ApiKey).where(ApiKey.prefix == prefix))
    key = result.scalar_one_or_none()
    if key is None or key.revoked:
        return None
    if not bcrypt.checkpw(secret.encode(), key.key_hash.encode()):
        return None
    if is_expired(key):
        return None

    now = datetime.now(timezone.utc)
    if key.last_used_at is None or (now - key.last_used_at).total_seconds() > _LAST_USED_THROTTLE_SECONDS:
        key.last_used_at = now
        try:
            await db.commit()
        except Exception:
            await db.rollback()

    return key
