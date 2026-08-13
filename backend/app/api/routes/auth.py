import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pyotp
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
import jwt as _jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TokenData, get_current_user, get_token_data, require_superadmin
from app.config import settings
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.schemas.user import (
    NormalizedEmail,
    PasswordChangeRequest,
    PasswordResetRequest,
    UserCreate,
    UserResponse,
)
from app.services import audit
from app.services import demo as demo_svc
from app.services import geoip
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.email import build_login_url, send_password_email
from app.services.password import (
    MAX_PASSWORD_LENGTH,
    assert_password_not_breached,
    generate_password,
    validate_password,
)
from app.services.rate_limit import rate_limit, register_failure

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Strong references to in-flight fire-and-forget email tasks so the event loop
# doesn't garbage-collect them mid-send (see _dispatch_reset_email).
_BG_EMAIL_TASKS: set[asyncio.Task] = set()


def _dispatch_reset_email(email: str, password: str, login_url: str, recipient_name: str = "") -> None:
    """Send the reset email outside the request/response cycle.

    The SMTP handshake + relay can take several seconds; awaiting it inside the
    request is what made reset links feel slow to arrive. We fire-and-forget
    with a fresh DB session (the request session is closed once the response is
    returned) and swallow errors — the caller already received its 202."""
    async def _run() -> None:
        from app.database import AsyncSessionLocal
        try:
            async with AsyncSessionLocal() as bg_db:
                await send_password_email(
                    db=bg_db,
                    recipient_email=email,
                    recipient_name=recipient_name,
                    password=password,
                    login_url=login_url,
                )
        except Exception:
            logger.warning("Password-reset email dispatch failed", exc_info=True)

    task = asyncio.create_task(_run())
    _BG_EMAIL_TASKS.add(task)
    task.add_done_callback(_BG_EMAIL_TASKS.discard)

# Pre-computed at startup; used by _checkpw to ensure bcrypt always runs even
# when the queried account does not exist, preventing user-enumeration via
# response-time differences (CWE-208 Observable Timing Discrepancy).
_DUMMY_HASH: str = bcrypt.hashpw(b"dummy-timing-sentinel", bcrypt.gensalt()).decode()


def _checkpw(password: str, user: "User | None") -> bool:
    """Always run bcrypt regardless of whether *user* exists.

    Short-circuiting `not user or not bcrypt.checkpw(...)` would skip the
    expensive hash comparison for nonexistent accounts, leaking account
    existence via timing.  Returns True only when the user exists AND the
    password matches the stored hash."""
    candidate_hash = user.hashed_password if user is not None else _DUMMY_HASH
    matches = bcrypt.checkpw(password.encode(), candidate_hash.encode())
    return user is not None and matches


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
    return _jwt.encode(
        {
            "sub": user_id,
            "exp": expire,
            # Explicit token type so a half-authenticated mfa_pending token can
            # never be mistaken for a full access token (CWE-287). _decode_token
            # rejects anything that is not "access".
            "typ": "access",
            "is_superadmin": is_superadmin,
            "org_id": org_id,
            "org_slug": org_slug,
            "role": role,
            "tv": token_version,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_stream_ticket(token_data: TokenData) -> str:
    """Short-lived (60 s) stream-scoped ticket for SSE/WebSocket connections.

    EventSource/WebSocket cannot set an Authorization header, so the client
    exchanges its bearer token for this ticket and passes it in the URL instead
    of the long-lived access token. typ=stream means every normal API endpoint
    rejects it (see deps._decode_token), so even if it ends up in a proxy log
    or the browser history it cannot be replayed for API calls and expires
    within a minute."""
    expire = datetime.now(timezone.utc) + timedelta(seconds=60)
    return _jwt.encode(
        {
            "sub": str(token_data.user_id),
            "exp": expire,
            "typ": "stream",
            "is_superadmin": token_data.is_superadmin,
            "org_id": str(token_data.org_id) if token_data.org_id else None,
            "org_slug": token_data.org_slug,
            "role": token_data.role,
            "tv": token_data.token_version,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_mfa_pending_token(user_id: str, org_slug: str | None = None) -> str:
    """Short-lived token issued after password check when MFA is required.
    The frontend uses this to call /auth/mfa/verify with the TOTP code."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    return _jwt.encode(
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
        payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
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
    # Normalised (trim + lower-case) so login is case-insensitive and matches the
    # normalised addresses stored at sign-up. Kept as a plain string rather than
    # EmailStr so a malformed value still yields a 401, not a 422.
    email: NormalizedEmail
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
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
            if not _checkpw(data.password, user):
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
            if not _checkpw(data.password, user):
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


def _reject_demo_user(current_user: "User") -> None:
    """Block account-security actions for ephemeral demo accounts.

    Demo sessions are shared, throwaway logins. Allowing a password change or
    MFA enrolment would let one visitor lock out everyone else who uses the
    same demo account (reported as a security concern)."""
    if getattr(current_user, "is_demo", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="In der Demo nicht verfügbar. Bitte eine Vollversion anfragen.",
        )


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
    _reject_demo_user(current_user)
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


# ── Stream ticket (SSE / WebSocket auth) ───────────────────────────────────────


@router.post("/stream-ticket")
async def stream_ticket(
    token_data: TokenData = Depends(get_token_data),
    current_user: User = Depends(get_current_user),
):
    """Exchange the bearer token for a short-lived stream ticket.

    EventSource/WebSocket cannot send an Authorization header, so the client
    uses this ticket in the connection URL instead of its long-lived access
    token. get_current_user guarantees the session is still active and the
    token version is current before a ticket is issued."""
    return {"ticket": create_stream_ticket(token_data)}


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

        login_url = build_login_url(
            settings.app_base_url,
            org_slug=org_for_link.slug if org_for_link else None,
            is_superadmin=user.is_superadmin,
        )

        # Dispatch the email in the background so the response isn't blocked by
        # the SMTP round-trip. Errors are swallowed there — the caller cannot
        # distinguish "no account" from "email server broken" by design.
        _dispatch_reset_email(user.email, new_password, login_url, recipient_name=user.full_name)

    # Constant-ish response time (matches /auth/org-lookup pattern)
    await asyncio.sleep(0.3)
    return response


# ── MFA Setup ─────────────────────────────────────────────────────────────────

class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


@router.post(
    "/mfa/setup",
    response_model=MfaSetupResponse,
    dependencies=[Depends(rate_limit("mfa-setup", max_attempts=10, window_seconds=300))],
)
async def mfa_setup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new TOTP secret for the authenticated user.
    The secret is stored (unconfirmed) and the provisioning URI for a QR code is returned.
    MFA is NOT active until /mfa/confirm succeeds."""
    _reject_demo_user(current_user)
    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA ist bereits aktiv. Bitte zuerst MFA deaktivieren (/auth/mfa/disable).",
        )
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


@router.post(
    "/mfa/confirm",
    dependencies=[Depends(rate_limit("mfa-confirm", max_attempts=10, window_seconds=300))],
)
async def mfa_confirm(
    data: MfaConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify the first TOTP code to activate MFA."""
    _reject_demo_user(current_user)
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


@router.post(
    "/mfa/disable",
    dependencies=[Depends(rate_limit("mfa-disable", max_attempts=10, window_seconds=300))],
)
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


# ── Demo session ──────────────────────────────────────────────────────────────

def _humanize_wait(seconds: int) -> str:
    """Wartezeit für die Fehlermeldung: „23 Stunden" statt „82.740 Sekunden"."""
    if seconds >= 3600:
        hours = max(1, round(seconds / 3600))
        return "einer Stunde" if hours == 1 else f"{hours} Stunden"
    minutes = max(1, round(seconds / 60))
    return "einer Minute" if minutes == 1 else f"{minutes} Minuten"


class DemoSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    org_slug: str
    expires_at: str  # ISO-8601 UTC


@router.get("/demo-status")
async def demo_status(db: AsyncSession = Depends(get_db)):
    """Public: whether demo sessions are currently available, so the landing page
    only shows the demo button when the superadmin has enabled the demo mode."""
    return {
        "enabled": await demo_svc.is_demo_enabled(db),
        "session_hours": await demo_svc.get_demo_session_hours(db),
    }


@router.get("/demo-session/info")
async def demo_session_info(
    token_data: TokenData = Depends(get_token_data),
    db: AsyncSession = Depends(get_db),
):
    """Current expiry of the caller's demo session (the superadmin may have
    extended it, so the JWT payload is not authoritative)."""
    if not token_data.org_id:
        raise HTTPException(status_code=404, detail="Keine Demo-Sitzung")
    org = await db.get(Organization, token_data.org_id)
    if not org or not org.is_demo:
        raise HTTPException(status_code=404, detail="Keine Demo-Sitzung")
    hours = await demo_svc.get_demo_session_hours(db)
    return {"expires_at": demo_svc.effective_expiry(org, hours).isoformat()}


@router.post(
    "/demo-session",
    response_model=DemoSessionResponse,
    dependencies=[Depends(rate_limit("demo", max_attempts=10, window_seconds=3600, count_attempts=True))],
)
async def create_demo_session(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create an ephemeral demo organisation + user and return a short-lived token.

    Requires the demo mode to be enabled (admin-panel toggle; the DEMO_ENABLED
    env var is the fallback). The session is deleted by the retention job once
    its expiry (admin-configurable lifetime, extendable per session) passes.

    One session per client IP and cooldown window (default 24 h): the gate is
    the `demo_origins` table, not the in-process limiter, so it survives a
    backend restart and outlives the demo org itself."""
    if not await demo_svc.is_demo_enabled(db):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Demo nicht verfügbar")

    client_ip = audit.client_ip(request)
    cooldown_hours = await demo_svc.get_demo_ip_cooldown_hours(db)
    retry_after = await demo_svc.claim_ip(db, client_ip, cooldown_hours)
    if retry_after is not None:
        await audit.record(
            db, "demo.session.rejected", request=request,
            detail={"reason": "ip_cooldown", "cooldown_hours": cooldown_hours},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Pro IP-Adresse ist alle {cooldown_hours} Stunden eine Demo-Sitzung möglich. "
                f"Bitte in {_humanize_wait(retry_after)} erneut versuchen — oder eine "
                "persönliche Vorführung anfragen."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    import secrets as _secrets

    # Find a unique slug (collision extremely unlikely but retry to be safe)
    slug = None
    for _ in range(5):
        candidate = "demo-" + _secrets.token_hex(3)  # e.g. demo-a3f9c2
        existing = await db.execute(select(Organization).where(Organization.slug == candidate))
        if not existing.scalar_one_or_none():
            slug = candidate
            break
    if not slug:
        raise HTTPException(status_code=500, detail="Demo-Sitzung konnte nicht erstellt werden")

    uid = uuid.uuid4()
    email = f"demo-{uid.hex}@demo.local"
    password = _secrets.token_urlsafe(24)
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    demo_user = User(id=uid, email=email, hashed_password=hashed, is_demo=True)
    db.add(demo_user)
    await db.flush()

    session_hours = await demo_svc.get_demo_session_hours(db)
    expire = datetime.now(timezone.utc) + timedelta(hours=session_hours)
    demo_org = Organization(
        name=f"Demo {slug[-6:].upper()}", slug=slug, owner_id=demo_user.id,
        is_demo=True, demo_expires_at=expire, demo_created_ip=client_ip,
    )
    db.add(demo_org)
    await db.flush()

    db.add(UserOrganization(user_id=demo_user.id, organization_id=demo_org.id, role="planer"))
    await db.commit()

    # Rough geo location for the admin panel ("welche Demo gehört zu wem") —
    # resolved after the response so a slow geo API never delays demo creation.
    background_tasks.add_task(geoip.resolve_demo_origin, demo_org.id, client_ip)

    # The JWT gets a generous ceiling so an admin-extended session keeps working;
    # the real cutoff is enforced server-side — the retention job deletes the
    # demo user at demo_expires_at and every request re-checks the DB.
    token_expire = datetime.now(timezone.utc) + timedelta(
        hours=max(session_hours, demo_svc.MAX_SESSION_HOURS)
    )
    token = _jwt.encode(
        {
            "sub": str(demo_user.id),
            "exp": token_expire,
            "typ": "access",
            "is_superadmin": False,
            "org_id": str(demo_org.id),
            "org_slug": slug,
            "role": "planer",
            "tv": 0,
            "is_demo": True,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    await audit.record(
        db, "demo.session.created", request=request,
        actor_id=demo_user.id, actor_email=email, org_id=demo_org.id,
        detail={"slug": slug, "expires_at": expire.isoformat()},
    )

    return DemoSessionResponse(access_token=token, org_slug=slug, expires_at=expire.isoformat())
