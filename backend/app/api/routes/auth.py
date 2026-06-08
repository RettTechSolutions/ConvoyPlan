import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
import jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TokenData, get_current_user, get_token_data, require_superadmin
from app.config import settings
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.schemas.user import (
    PasswordChangeRequest,
    PasswordResetRequest,
    UserCreate,
    UserResponse,
)
from app.services import audit
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.email import send_password_email
from app.services.password import assert_password_not_breached, generate_password, validate_password
from app.services.rate_limit import rate_limit, register_failure

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_token(
    user_id: str,
    is_superadmin: bool,
    org_id: str | None = None,
    org_slug: str | None = None,
    role: str | None = None,
    token_version: int = 0,
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
            "tv": token_version,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_mfa_pending_token(user_id: str, org_slug: str | None = None) -> str:
    """Short-lived token issued after password check when MFA is required.
    The frontend uses this to call /auth/mfa/verify with the TOTP code."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode(
        {
            "sub": user_id,
            "exp": expire,
            "mfa_pending": True,
            "org_slug": org_slug,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_mfa_pending_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if not payload.get("mfa_pending"):
            raise ValueError("Not an MFA-pending token")
        return payload
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder abgelaufener MFA-Token",
        )


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str
    org_slug: str | None = None


class LoginResponse(BaseModel):
    """Login can return either a full token or an MFA challenge."""
    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit("login", max_attempts=10, window_seconds=300))],
)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    try:
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

            if user.mfa_enabled and user.mfa_secret:
                mfa_token = create_mfa_pending_token(str(user.id), data.org_slug)
                return LoginResponse(mfa_required=True, mfa_token=mfa_token)

            token = create_token(str(user.id), False, str(org.id), org.slug, membership.role, user.token_version)
            await audit.record(
                db, audit.LOGIN_SUCCESS, request=request, actor_id=user.id,
                actor_email=user.email, org_id=org.id, detail={"scope": "org"},
            )
            return LoginResponse(access_token=token)

        else:
            # ── Superadmin-Login (kein org_slug) ─────────────────────────────
            if not user or not bcrypt.checkpw(data.password.encode(), user.hashed_password.encode()):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
            if not user.is_active:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
            if not user.is_superadmin:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")

            if user.mfa_enabled and user.mfa_secret:
                mfa_token = create_mfa_pending_token(str(user.id))
                return LoginResponse(mfa_required=True, mfa_token=mfa_token)

            token = create_token(str(user.id), True, token_version=user.token_version)
            await audit.record(
                db, audit.LOGIN_SUCCESS, request=request, actor_id=user.id,
                actor_email=user.email, detail={"scope": "superadmin"},
            )
            return LoginResponse(access_token=token)

    except HTTPException as exc:
        if exc.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            register_failure(request, "login")
            await audit.record(
                db, audit.LOGIN_FAILURE, request=request, actor_email=data.email,
                detail={"reason": exc.detail, "org_slug": data.org_slug},
            )
        raise


# ── Org Lookup ────────────────────────────────────────────────────────────────

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


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    validate_password(data.password)
    await assert_password_not_breached(data.password)
    user = User(
        email=data.email,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ── Password change (self-service) ────────────────────────────────────────────


@router.post("/password")
async def change_password(
    data: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    token_data: TokenData = Depends(get_token_data),
    db: AsyncSession = Depends(get_db),
):
    """Authenticated user changes their own password (current password required).

    Bumps the token version to revoke any other active sessions and returns a
    fresh token so the current client stays logged in."""
    if not bcrypt.checkpw(data.current_password.encode(), current_user.hashed_password.encode()):
        await asyncio.sleep(0.2)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Aktuelles Passwort falsch")
    validate_password(data.new_password)
    await assert_password_not_breached(data.new_password)
    current_user.hashed_password = bcrypt.hashpw(data.new_password.encode(), bcrypt.gensalt()).decode()
    current_user.token_version += 1
    db.add(current_user)
    await db.commit()
    await audit.record(
        db, audit.PASSWORD_CHANGED, request=request, actor_id=current_user.id,
        actor_email=current_user.email,
    )
    new_token = create_token(
        str(current_user.id), token_data.is_superadmin,
        str(token_data.org_id) if token_data.org_id else None,
        token_data.org_slug, token_data.role, current_user.token_version,
    )
    return {"status": "ok", "access_token": new_token}


# ── Password reset request (forgot password) ──────────────────────────────────


@router.post(
    "/password-reset",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("password-reset", max_attempts=5, window_seconds=900, count_attempts=True))],
)
async def request_password_reset(
    data: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint: generate a new password and email it to the user.

    Always returns 202 to avoid account enumeration. SMTP/lookup failures are
    swallowed; the response time is normalised to make timing-attacks harder."""
    response = {"status": "accepted"}

    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    # When org_slug is provided, only act if the user is a member of that org.
    org_for_link: Organization | None = None
    if data.org_slug:
        org_result = await db.execute(select(Organization).where(Organization.slug == data.org_slug))
        org_for_link = org_result.scalar_one_or_none()
        if user and org_for_link:
            mem_result = await db.execute(
                select(UserOrganization).where(
                    UserOrganization.user_id == user.id,
                    UserOrganization.organization_id == org_for_link.id,
                )
            )
            if mem_result.scalar_one_or_none() is None:
                user = None

    if user and user.is_active:
        new_password = generate_password()
        user.hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        user.token_version += 1  # revoke existing sessions
        await db.commit()
        await audit.record(
            db, audit.PASSWORD_RESET_REQUESTED, request=request, actor_id=user.id,
            actor_email=user.email,
        )

        base_url = settings.app_base_url.rstrip("/")
        if org_for_link:
            login_url = f"{base_url}/o/{org_for_link.slug}/login"
        else:
            login_url = f"{base_url}/login"

        try:
            await send_password_email(
                db=db,
                recipient_email=user.email,
                recipient_name="",
                password=new_password,
                login_url=login_url,
            )
        except Exception:
            # Don't leak SMTP errors — caller cannot distinguish "no account"
            # from "email server broken" by design.
            pass

    # Constant-ish response time (matches /auth/org-lookup pattern)
    await asyncio.sleep(0.3)
    return response


# ── MFA Setup ─────────────────────────────────────────────────────────────────

class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def mfa_setup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new TOTP secret for the authenticated user.
    The secret is stored (unconfirmed) and the provisioning URI for a QR code is returned.
    MFA is NOT active until /mfa/confirm succeeds."""
    secret = pyotp.random_base32()
    current_user.mfa_secret = encrypt_secret(secret)
    current_user.mfa_enabled = False  # not active until confirmed
    db.add(current_user)
    await db.commit()

    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=current_user.email, issuer_name="ConvoyPlan")
    return MfaSetupResponse(secret=secret, provisioning_uri=uri)


class MfaConfirmRequest(BaseModel):
    code: str


@router.post("/mfa/confirm")
async def mfa_confirm(
    data: MfaConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify the first TOTP code to activate MFA."""
    if not current_user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA-Setup wurde nicht gestartet")
    totp = pyotp.TOTP(decrypt_secret(current_user.mfa_secret))
    if not totp.verify(data.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Ungültiger Code")
    current_user.mfa_enabled = True
    db.add(current_user)
    await db.commit()
    await audit.record(
        db, audit.MFA_ENABLED, request=request, actor_id=current_user.id,
        actor_email=current_user.email,
    )
    return {"status": "MFA aktiviert"}


@router.post("/mfa/disable")
async def mfa_disable(
    data: MfaConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable MFA — requires current TOTP code as confirmation."""
    if not current_user.mfa_enabled or not current_user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA ist nicht aktiv")
    totp = pyotp.TOTP(decrypt_secret(current_user.mfa_secret))
    if not totp.verify(data.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Ungültiger Code")
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    db.add(current_user)
    await db.commit()
    await audit.record(
        db, audit.MFA_DISABLED, request=request, actor_id=current_user.id,
        actor_email=current_user.email,
    )
    return {"status": "MFA deaktiviert"}


@router.get("/mfa/status")
async def mfa_status(current_user: User = Depends(get_current_user)):
    """Return current MFA status for the authenticated user."""
    return {"mfa_enabled": current_user.mfa_enabled}


# ── MFA Verify (second login step) ───────────────────────────────────────────

class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str


@router.post(
    "/mfa/verify",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit("mfa-verify", max_attempts=10, window_seconds=300))],
)
async def mfa_verify(data: MfaVerifyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Exchange an mfa_pending token + TOTP code for a full JWT."""
    payload = decode_mfa_pending_token(data.mfa_token)
    user_id_str = payload.get("sub")
    org_slug = payload.get("org_slug")

    result = await db.execute(select(User).where(User.id == user_id_str))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA nicht konfiguriert")

    totp = pyotp.TOTP(decrypt_secret(user.mfa_secret))
    if not totp.verify(data.code, valid_window=1):
        register_failure(request, "mfa-verify")
        await audit.record(
            db, audit.LOGIN_FAILURE, request=request, actor_id=user.id,
            actor_email=user.email, detail={"reason": "invalid_mfa_code"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Code")

    if org_slug:
        org_result = await db.execute(select(Organization).where(Organization.slug == org_slug))
        org = org_result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        mem_result = await db.execute(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.organization_id == org.id,
            )
        )
        membership = mem_result.scalar_one_or_none()
        if not membership:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        token = create_token(str(user.id), False, str(org.id), org.slug, membership.role, user.token_version)
        await audit.record(
            db, audit.LOGIN_SUCCESS, request=request, actor_id=user.id,
            actor_email=user.email, org_id=org.id, detail={"scope": "org", "mfa": True},
        )
    else:
        token = create_token(str(user.id), True, token_version=user.token_version)
        await audit.record(
            db, audit.LOGIN_SUCCESS, request=request, actor_id=user.id,
            actor_email=user.email, detail={"scope": "superadmin", "mfa": True},
        )

    return LoginResponse(access_token=token)
