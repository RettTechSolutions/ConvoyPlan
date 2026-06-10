import uuid

import jwt as _jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.services import api_key as api_key_svc

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
# Optional variants for endpoints that accept either a bearer token or an
# organization-scoped API key. auto_error=False so a missing one is not fatal
# on its own — get_org_context decides based on which credential is present.
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class TokenData(BaseModel):
    user_id: uuid.UUID
    org_id: uuid.UUID | None = None
    org_slug: str | None = None
    role: str | None = None
    is_superadmin: bool = False
    token_version: int = 0


def _ensure_token_current(token_data: TokenData, user: User) -> None:
    """Reject tokens whose version is older than the user's current one (T6)."""
    if token_data.token_version != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sitzung abgelaufen — bitte erneut anmelden",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _decode_token(token: str, *, allow_stream: bool = False) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        # Reject half-authenticated MFA-pending tokens and any unexpected token
        # type. mfa_pending tokens are issued after the password step but before
        # TOTP; they must NOT grant access. Stream tickets (typ=stream) are only
        # accepted on the SSE/WebSocket paths, never on normal API endpoints.
        if payload.get("mfa_pending"):
            raise credentials_exception
        token_type = payload.get("typ")
        allowed_types = ("access", "stream") if allow_stream else ("access",)
        if token_type is not None and token_type not in allowed_types:
            raise credentials_exception
        raw_org_id = payload.get("org_id")
        return TokenData(
            user_id=uuid.UUID(user_id_str),
            org_id=uuid.UUID(raw_org_id) if raw_org_id else None,
            org_slug=payload.get("org_slug"),
            role=payload.get("role"),
            is_superadmin=bool(payload.get("is_superadmin", False)),
            token_version=int(payload.get("tv", 0)),
        )
    except (InvalidTokenError, ValueError):
        raise credentials_exception


def get_token_data(token: str = Depends(oauth2_scheme)) -> TokenData:
    return _decode_token(token)


def decode_stream_token(token: str) -> TokenData:
    """Decode a token passed via an SSE/WebSocket query parameter.

    EventSource/WebSocket cannot send an Authorization header, so clients pass
    a credential in the URL. Accepts a normal access token, a legacy token
    (no typ) or a short-lived stream ticket (typ=stream), but rejects
    mfa_pending tokens so the MFA second factor is enforced here too (K1)."""
    return _decode_token(token, allow_stream=True)


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
    _ensure_token_current(token_data, user)
    return user


# Type alias for org-scoped dependencies
OrgCtx = tuple[User, Organization, str]


async def _api_key_org_context(raw_key: str, db: AsyncSession) -> OrgCtx:
    """Resolve an organization-scoped API key into an OrgCtx.

    The key acts within its organization with the configured role; the
    organization's owner is used as the acting user so existing ownership
    logic (e.g. owner_id on created resources) keeps working."""
    key = await api_key_svc.resolve_key(db, raw_key)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger, widerrufener oder abgelaufener API-Key",
        )
    org = await db.get(Organization, key.organization_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation nicht gefunden")
    user = await db.get(User, org.owner_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organisation hat keinen aktiven Eigentümer",
        )
    return user, org, key.role


async def get_org_context(
    token: str | None = Depends(oauth2_optional),
    raw_api_key: str | None = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> OrgCtx:
    # Organization-scoped API key takes precedence when supplied.
    if raw_api_key:
        return await _api_key_org_context(raw_api_key, db)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_data = _decode_token(token)
    if not token_data.org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Org context required")

    user = await db.get(User, token_data.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
    _ensure_token_current(token_data, user)

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
    # Re-check the DB — the JWT claim could be stale if superadmin was revoked
    if not user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
    _ensure_token_current(token_data, user)
    return user
