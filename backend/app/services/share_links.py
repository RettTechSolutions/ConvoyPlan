"""Helpers for public convoy share links (slug generation, password hashing, session tokens)."""

import secrets
import string
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as _jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.share_link import ConvoyShareLink

SLUG_ALPHABET = string.ascii_letters + string.digits  # base62
SLUG_LENGTH = 8
PASSWORD_LENGTH = 10
SESSION_TOKEN_TTL_HOURS = 24
SESSION_TOKEN_KIND = "share_link"


def _random_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LENGTH))


async def generate_unique_slug(db: AsyncSession, max_attempts: int = 5) -> str:
    for _ in range(max_attempts):
        candidate = _random_slug()
        existing = await db.execute(
            select(ConvoyShareLink.id).where(ConvoyShareLink.slug == candidate)
        )
        if existing.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError("Could not generate a unique share-link slug after several attempts")


def generate_password() -> str:
    """10-char alphanumeric (62^10 ≈ 8.4·10¹⁷), readable when dictated."""
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(PASSWORD_LENGTH))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def issue_session_token(slug: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=SESSION_TOKEN_TTL_HOURS)
    return _jwt.encode(
        {"sub": slug, "kind": SESSION_TOKEN_KIND, "exp": expire},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_session_token(token: str) -> str | None:
    """Return the slug if the token is a valid share-link session token, else None."""
    try:
        payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError:
        return None
    if payload.get("kind") != SESSION_TOKEN_KIND:
        return None
    slug = payload.get("sub")
    return slug if isinstance(slug, str) else None
