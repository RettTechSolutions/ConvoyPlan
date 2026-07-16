import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import decode_stream_token, get_db, require_superadmin
from app.config import settings
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.convoy import Convoy
from app.models.organization import Organization, UserOrganization
from app.models.settings import SystemSetting
from app.models.share_link import ConvoyShareLink
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse
from app.models.vehicle import Vehicle
from app.schemas.user import AdminUserCreate, AdminUserResponse, AdminUserUpdate, AdminUserOrgInfo
from app.services import api_key as api_key_svc
from app.services import audit
from app.services.update_check import (
    VALID_CHANNELS,
    VALID_MODES,
    env_channel as _env_channel,
    env_mode as _env_mode,
    fetch_update_state,
    resolve_channel as _resolve_channel,
    resolve_mode as _resolve_mode,
    resolve_notify_on_auto as _resolve_notify_on_auto,
    write_channel_file as _write_channel_file,
    write_mode_file as _write_mode_file,
)
from app.services import demo as demo_svc
from app.services import smartmaps as smartmaps_svc
from app.services import traffic_flow as traffic_flow_svc
from app.services.email import save_smtp_settings, send_password_email, test_smtp_connection
from app.services.password import assert_password_not_breached, generate_password, validate_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

TRIGGER_FILE = "/update_status/trigger"
LOG_FILE = "/update_status/update.log"


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.org_memberships).selectinload(UserOrganization.organization))
        .order_by(User.created_at)
    )
    users = result.scalars().all()
    out = []
    for u in users:
        orgs = [
            AdminUserOrgInfo(id=m.organization.id, name=m.organization.name, role=m.role)
            for m in u.org_memberships
            if m.organization is not None
        ]
        out.append(AdminUserResponse(
            id=u.id,
            email=u.email,
            first_name=u.first_name,
            last_name=u.last_name,
            is_active=u.is_active,
            is_superadmin=u.is_superadmin,
            is_demo=u.is_demo,
            mfa_enabled=u.mfa_enabled,
            created_at=u.created_at,
            orgs=orgs,
        ))
    return out


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def create_user(
    data: AdminUserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    validate_password(data.password)
    await assert_password_not_breached(data.password)
    user = User(
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        is_superadmin=data.is_superadmin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit.record(
        db, audit.USER_CREATED, request=request, actor_id=current.id,
        actor_email=current.email, target_type="user", target_id=user.id,
        detail={"email": user.email, "name": user.full_name or None,
                "is_superadmin": user.is_superadmin},
    )
    return AdminUserResponse(id=user.id, email=user.email,
                             first_name=user.first_name, last_name=user.last_name,
                             is_active=user.is_active,
                             is_superadmin=user.is_superadmin, mfa_enabled=user.mfa_enabled,
                             created_at=user.created_at, orgs=[])


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.org_memberships).selectinload(UserOrganization.organization))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == current.id:
        if data.is_superadmin is False or data.is_active is False:
            raise HTTPException(400, "Cannot demote or deactivate your own account")
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_superadmin is not None:
        user.is_superadmin = data.is_superadmin
    # Names are nullable: only fields explicitly present in the PATCH are
    # applied, so sending an empty string clears while omitting keeps the value.
    if "first_name" in data.model_fields_set:
        user.first_name = data.first_name
    if "last_name" in data.model_fields_set:
        user.last_name = data.last_name
    if data.email is not None:
        conflict = await db.execute(select(User).where(User.email == data.email, User.id != user_id))
        if conflict.scalar_one_or_none():
            raise HTTPException(400, "Email already in use")
        user.email = data.email
    if data.password is not None:
        validate_password(data.password)
        await assert_password_not_breached(data.password)
        user.hashed_password = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
        user.token_version += 1  # revoke the user's existing sessions
    await db.commit()
    await db.refresh(user)
    await audit.record(
        db, audit.USER_UPDATED, request=request, actor_id=current.id,
        actor_email=current.email, target_type="user", target_id=user.id,
        detail=data.model_dump(exclude_unset=True, exclude={"password"}),
    )
    orgs = [
        AdminUserOrgInfo(id=m.organization.id, name=m.organization.name, role=m.role)
        for m in user.org_memberships
        if m.organization is not None
    ]
    return AdminUserResponse(id=user.id, email=user.email,
                             first_name=user.first_name, last_name=user.last_name,
                             is_active=user.is_active,
                             is_superadmin=user.is_superadmin, is_demo=user.is_demo,
                             mfa_enabled=user.mfa_enabled,
                             created_at=user.created_at, orgs=orgs)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    if user_id == current.id:
        raise HTTPException(400, "Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    deleted_email = user.email
    await db.delete(user)
    await db.commit()
    await audit.record(
        db, audit.USER_DELETED, request=request, actor_id=current.id,
        actor_email=current.email, target_type="user", target_id=user_id,
        detail={"email": deleted_email},
    )


@router.get("/update-status")
async def get_update_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Update-Status für den aktiven Kanal (Anzeige im Admin-Panel).

    Die eigentliche Logik lebt in app.services.update_check, damit der
    Update-Benachrichtigungs-Task exakt dieselbe Bewertung nutzt.
    """
    return await fetch_update_state(db)


@router.get("/settings/github-token-set")
async def github_token_is_set(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Returns whether a GitHub token is configured (DB or env), without revealing it."""
    if settings.github_token:
        return {"set": True, "source": "env"}
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "github.token"))
    setting = result.scalar_one_or_none()
    if setting and setting.value:
        return {"set": True, "source": "db"}
    return {"set": False, "source": None}


class GithubTokenUpdate(BaseModel):
    token: str


@router.put("/settings/github-token", status_code=204)
async def set_github_token(
    data: GithubTokenUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Store (or clear) the GitHub API token in system_settings."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "github.token"))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = data.token
    else:
        db.add(SystemSetting(key="github.token", value=data.token))
    await db.commit()


# ── Live-Verkehrslage (HERE / TomTom) ───────────────────────────────────────


class TrafficKeyState(BaseModel):
    set: bool
    source: str | None  # "db" | "env" | None


class TrafficKeysResponse(BaseModel):
    here: TrafficKeyState
    tomtom: TrafficKeyState
    provider: str | None      # aktuell wirksamer Anbieter (oder None)
    forced: str               # erzwungener Anbieter ("", "here", "tomtom")


class TrafficKeysUpdate(BaseModel):
    # Optionale Felder: nur gesetzte werden aktualisiert. Leerer String löscht.
    here_key: str | None = None
    tomtom_key: str | None = None
    provider: str | None = Field(None, description="'', 'here' oder 'tomtom'")


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    return row.value if row is not None else None


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


def _key_state(db_value: str | None, env_value: str) -> TrafficKeyState:
    if db_value:
        return TrafficKeyState(set=True, source="db")
    if env_value:
        return TrafficKeyState(set=True, source="env")
    return TrafficKeyState(set=False, source=None)


@router.get("/settings/traffic-keys", response_model=TrafficKeysResponse)
async def get_traffic_keys(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Konfigurationsstatus der Verkehrslage-Keys (ohne die Werte preiszugeben)."""
    cfg = await traffic_flow_svc.resolve_config(db)
    here_db = await _get_setting(db, traffic_flow_svc.KEY_HERE)
    tomtom_db = await _get_setting(db, traffic_flow_svc.KEY_TOMTOM)
    return TrafficKeysResponse(
        here=_key_state(here_db, settings.here_traffic_api_key),
        tomtom=_key_state(tomtom_db, settings.tomtom_traffic_api_key),
        provider=cfg.provider,
        forced=cfg.forced or "",
    )


@router.put("/settings/traffic-keys", status_code=204)
async def set_traffic_keys(
    data: TrafficKeysUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """HERE-/TomTom-Keys und Anbieterwahl in system_settings ablegen.

    Nur übergebene Felder werden geändert; ein leerer String löscht den Wert
    (DB-Eintrag hat Vorrang vor der ENV-Konfiguration).
    """
    if data.provider is not None and data.provider not in ("", "here", "tomtom"):
        raise HTTPException(status_code=422, detail="provider muss '', 'here' oder 'tomtom' sein")
    if data.here_key is not None:
        await _set_setting(db, traffic_flow_svc.KEY_HERE, data.here_key.strip())
    if data.tomtom_key is not None:
        await _set_setting(db, traffic_flow_svc.KEY_TOMTOM, data.tomtom_key.strip())
    if data.provider is not None:
        await _set_setting(db, traffic_flow_svc.KEY_PROVIDER, data.provider.strip())
    await db.commit()
    await audit.record(
        db, "admin.settings.traffic_keys_changed", request=request, actor_id=current.id,
    )


# ── SmartMaps-Basemap (YellowMap) ───────────────────────────────────────────


class SmartmapsKeyResponse(BaseModel):
    api_key: TrafficKeyState  # gesetzt? Quelle "db"/"env"/None (der Wert bleibt geheim)


class SmartmapsKeyUpdate(BaseModel):
    # Optionales Feld: nur wenn gesetzt wird geschrieben. Leerer String löscht.
    api_key: str | None = None


@router.get("/settings/smartmaps-key", response_model=SmartmapsKeyResponse)
async def get_smartmaps_key(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Konfigurationsstatus des SmartMaps-Keys (ohne den Wert preiszugeben)."""
    api_db = await _get_setting(db, smartmaps_svc.KEY_API)
    return SmartmapsKeyResponse(
        api_key=_key_state(api_db, settings.smartmaps_api_key),
    )


@router.put("/settings/smartmaps-key", status_code=204)
async def set_smartmaps_key(
    data: SmartmapsKeyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """SmartMaps-Key in system_settings ablegen (überschreibt die ENV-Konfiguration).

    Nur ein übergebenes Feld wird geändert; ein leerer String löscht den Wert
    (DB-Eintrag hat Vorrang vor ``SMARTMAPS_API_KEY``).
    """
    if data.api_key is not None:
        await _set_setting(db, smartmaps_svc.KEY_API, data.api_key.strip())
    await db.commit()
    await audit.record(
        db, "admin.settings.smartmaps_key_changed", request=request, actor_id=current.id,
    )


# ── Update-Channel (stable / beta / nightly) ────────────────────────────────


class UpdateChannelResponse(BaseModel):
    channel: str             # effective channel ("stable" | "beta" | "nightly")
    source: str              # "db" | "env" — where the effective value comes from
    env_channel: str         # the UPDATE_CHANNEL env fallback


class UpdateChannelUpdate(BaseModel):
    channel: str = Field(..., description="Release channel: 'stable', 'beta' or 'nightly'")


@router.get("/settings/update-channel", response_model=UpdateChannelResponse)
async def get_update_channel(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    channel, source = await _resolve_channel(db)
    # Keep the shared file in sync on read too, so the updater picks up the
    # current value even if it was only ever set via the env var.
    _write_channel_file(channel)
    return UpdateChannelResponse(channel=channel, source=source, env_channel=_env_channel())


@router.put("/settings/update-channel", status_code=204)
async def set_update_channel(
    data: UpdateChannelUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """Store the release channel in system_settings and mirror it to the shared
    volume so the updater switches between tracking published releases (stable),
    numbered pre-releases (beta) or every main commit (nightly)."""
    if data.channel not in VALID_CHANNELS:
        raise HTTPException(422, "channel must be 'stable', 'beta' or 'nightly'")
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "update.channel"))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = data.channel
    else:
        db.add(SystemSetting(key="update.channel", value=data.channel))
    await db.commit()
    _write_channel_file(data.channel)
    await audit.record(
        db, "admin.settings.update_channel_changed", request=request, actor_id=current.id,
        detail={"channel": data.channel},
    )


# ── Update-Modus (auto / notify) ─────────────────────────────────────────────


class UpdateModeResponse(BaseModel):
    mode: str                # effective mode ("auto" | "notify")
    source: str              # "db" | "env" — where the effective value comes from
    env_mode: str            # the UPDATE_MODE env fallback
    notify_on_auto: bool     # email superadmins after automatic installs (mode "auto")


class UpdateModeUpdate(BaseModel):
    mode: str = Field(..., description="Update mode: 'auto' (install automatically) or 'notify' (email superadmins only)")
    notify_on_auto: bool | None = Field(
        None,
        description="Optional: also email superadmins after an automatic install (mode 'auto'). Omit to keep the current value.",
    )


@router.get("/settings/update-mode", response_model=UpdateModeResponse)
async def get_update_mode(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    mode, source = await _resolve_mode(db)
    notify_on_auto, _src = await _resolve_notify_on_auto(db)
    # Keep the shared file in sync on read too, so the updater picks up the
    # current value even if it was only ever set via the env var.
    _write_mode_file(mode)
    return UpdateModeResponse(
        mode=mode, source=source, env_mode=_env_mode(), notify_on_auto=notify_on_auto
    )


@router.put("/settings/update-mode", status_code=204)
async def set_update_mode(
    data: UpdateModeUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """Store the update mode in system_settings and mirror it to the shared
    volume: 'auto' lets the updater install channel updates by itself,
    'notify' disables automatic installs — superadmins get an email instead
    and update manually via the admin panel. The optional notify_on_auto flag
    additionally emails the superadmins AFTER an automatic install."""
    if data.mode not in VALID_MODES:
        raise HTTPException(422, "mode must be 'auto' or 'notify'")
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "update.mode"))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = data.mode
    else:
        db.add(SystemSetting(key="update.mode", value=data.mode))

    if data.notify_on_auto is not None:
        value = "true" if data.notify_on_auto else "false"
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == "update.notify_on_auto")
        )
        flag = result.scalar_one_or_none()
        if flag:
            flag.value = value
        else:
            db.add(SystemSetting(key="update.notify_on_auto", value=value))

    await db.commit()
    _write_mode_file(data.mode)
    detail: dict = {"mode": data.mode}
    if data.notify_on_auto is not None:
        detail["notify_on_auto"] = data.notify_on_auto
    await audit.record(
        db, "admin.settings.update_mode_changed", request=request, actor_id=current.id,
        detail=detail,
    )


# ── Demo-Modus ────────────────────────────────────────────────────────────────


class DemoSettingsResponse(BaseModel):
    enabled: bool            # effective state (DB setting wins, env is fallback)
    source: str              # "db" | "env"
    env_enabled: bool        # value of the DEMO_ENABLED env var
    session_hours: int


class DemoSettingsUpdate(BaseModel):
    enabled: bool
    session_hours: int | None = Field(
        None, ge=demo_svc.MIN_SESSION_HOURS, le=demo_svc.MAX_SESSION_HOURS,
        description="Laufzeit neuer Demo-Sitzungen in Stunden",
    )


@router.get("/settings/demo", response_model=DemoSettingsResponse)
async def get_demo_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    db_value = await demo_svc.get_demo_enabled_setting(db)
    return DemoSettingsResponse(
        enabled=db_value == "true" if db_value is not None else settings.demo_enabled,
        source="db" if db_value is not None else "env",
        env_enabled=settings.demo_enabled,
        session_hours=await demo_svc.get_demo_session_hours(db),
    )


@router.put("/settings/demo", response_model=DemoSettingsResponse)
async def update_demo_settings(
    data: DemoSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    if data.session_hours is not None:
        await demo_svc.set_demo_session_hours(db, data.session_hours)
    await demo_svc.set_demo_enabled(db, data.enabled)
    await audit.record(
        db, "admin.settings.demo_updated", request=request, actor_id=current.id,
        actor_email=current.email,
        detail={"enabled": data.enabled, "session_hours": data.session_hours},
    )
    return DemoSettingsResponse(
        enabled=data.enabled,
        source="db",
        env_enabled=settings.demo_enabled,
        session_hours=await demo_svc.get_demo_session_hours(db),
    )


class DemoSessionInfo(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    expires_at: datetime
    convoy_count: int


@router.get("/demo-sessions", response_model=list[DemoSessionInfo])
async def list_demo_sessions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """All currently open demo sessions (one ephemeral org per session)."""
    result = await db.execute(
        select(Organization)
        .where(Organization.is_demo.is_(True))
        .order_by(Organization.created_at.desc())
    )
    orgs = result.scalars().all()
    if not orgs:
        return []

    counts_result = await db.execute(
        select(Convoy.organization_id, func.count(Convoy.id))
        .where(Convoy.organization_id.in_([o.id for o in orgs]))
        .group_by(Convoy.organization_id)
    )
    convoy_counts = dict(counts_result.all())

    fallback_hours = await demo_svc.get_demo_session_hours(db)
    return [
        DemoSessionInfo(
            id=o.id,
            name=o.name,
            slug=o.slug,
            created_at=o.created_at,
            expires_at=demo_svc.effective_expiry(o, fallback_hours),
            convoy_count=convoy_counts.get(o.id, 0),
        )
        for o in orgs
    ]


class DemoExtendRequest(BaseModel):
    hours: int = Field(24, ge=1, le=demo_svc.MAX_SESSION_HOURS)


@router.post("/demo-sessions/{org_id}/extend", response_model=DemoSessionInfo)
async def extend_demo_session(
    org_id: uuid.UUID,
    data: DemoExtendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """Extend a demo session: pushes the expiry *hours* beyond its current
    expiry (or beyond now, if it would otherwise already be in the past)."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.is_demo.is_(True))
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Demo-Sitzung nicht gefunden")

    fallback_hours = await demo_svc.get_demo_session_hours(db)
    now = datetime.now(timezone.utc)
    base = max(demo_svc.effective_expiry(org, fallback_hours), now)
    org.demo_expires_at = base + timedelta(hours=data.hours)
    await db.commit()
    await db.refresh(org)

    await audit.record(
        db, "admin.demo_session.extended", request=request, actor_id=current.id,
        actor_email=current.email, org_id=org.id, target_type="organization",
        target_id=org.id,
        detail={"slug": org.slug, "hours": data.hours, "expires_at": org.demo_expires_at.isoformat()},
    )

    convoy_count = (await db.execute(
        select(func.count(Convoy.id)).where(Convoy.organization_id == org.id)
    )).scalar_one()
    return DemoSessionInfo(
        id=org.id, name=org.name, slug=org.slug, created_at=org.created_at,
        expires_at=org.demo_expires_at, convoy_count=convoy_count,
    )


@router.delete("/demo-sessions/{org_id}", status_code=204)
async def terminate_demo_session(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """End a demo session immediately: delete its convoys, org and demo user.

    Same deletion order as the retention purge — convoys before the org
    (FK SET NULL would orphan them), org before its owner user."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id, Organization.is_demo.is_(True))
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Demo-Sitzung nicht gefunden")

    detail = {"name": org.name, "slug": org.slug}
    owner_id = org.owner_id
    await db.execute(delete(Convoy).where(Convoy.organization_id == org_id))
    await db.execute(delete(Organization).where(Organization.id == org_id))
    # Guard on is_demo so a (mis)assigned regular account can never be deleted here.
    await db.execute(delete(User).where(User.id == owner_id, User.is_demo.is_(True)))
    await db.commit()

    await audit.record(
        db, "admin.demo_session.terminated", request=request, actor_id=current.id,
        actor_email=current.email, org_id=org_id, target_type="organization",
        target_id=org_id, detail=detail,
    )


class AdminOrgAssign(BaseModel):
    org_id: uuid.UUID
    role: str = "beobachter"


@router.post("/users/{user_id}/orgs", status_code=201)
async def admin_add_user_to_org(
    user_id: uuid.UUID,
    data: AdminOrgAssign,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    if not user_result.scalar_one_or_none():
        raise HTTPException(404, "User not found")

    org_result = await db.execute(select(Organization).where(Organization.id == data.org_id))
    if not org_result.scalar_one_or_none():
        raise HTTPException(404, "Organization not found")

    existing = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.organization_id == data.org_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "User is already a member of this organization")

    db.add(UserOrganization(user_id=user_id, organization_id=data.org_id, role=data.role))
    await db.commit()
    return {"status": "added"}


@router.delete("/users/{user_id}/orgs/{org_id}", status_code=204)
async def admin_remove_user_from_org(
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == user_id,
            UserOrganization.organization_id == org_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership:
        await db.delete(membership)
        await db.commit()


class AdminOrgCreate(BaseModel):
    name: str
    slug: str


@router.post("/organizations", status_code=201)
async def admin_create_organization(
    data: AdminOrgCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    slug = data.slug.strip().lower()
    # Validate slug chars
    import re as _re
    slug = _re.sub(r"[^a-z0-9-]+", "", slug).strip("-")[:8]
    if not slug:
        raise HTTPException(400, "Invalid slug")

    existing = await db.execute(select(Organization).where(Organization.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Slug already in use")

    org = Organization(name=data.name.strip(), slug=slug, owner_id=current.id)
    db.add(org)
    await db.flush()
    membership = UserOrganization(user_id=current.id, organization_id=org.id, role="admin")
    db.add(membership)
    await db.commit()
    await db.refresh(org)
    await audit.record(
        db, audit.ORG_CREATED, request=request, actor_id=current.id,
        actor_email=current.email, org_id=org.id, target_type="organization",
        target_id=org.id, detail={"name": org.name, "slug": org.slug},
    )
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "owner_email": current.email,
        "member_count": 1,
    }


@router.get("/organizations")
async def list_all_organizations(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(Organization)
        .options(selectinload(Organization.members), selectinload(Organization.owner))
        .order_by(Organization.name)
    )
    orgs = result.scalars().all()
    return [
        {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "owner_email": org.owner.email if org.owner else None,
            "member_count": len(org.members),
            "is_demo": org.is_demo,
        }
        for org in orgs
    ]


class AdminOrgUpdate(BaseModel):
    owner_id: uuid.UUID


@router.patch("/organizations/{org_id}", status_code=200)
async def admin_update_organization(
    org_id: uuid.UUID,
    data: AdminOrgUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(Organization).where(Organization.id == org_id).options(selectinload(Organization.owner))
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")

    new_owner = await db.get(User, data.owner_id)
    if not new_owner:
        raise HTTPException(404, "User not found")

    org.owner_id = data.owner_id
    await db.commit()
    await db.refresh(org)
    await audit.record(
        db, "admin.org.updated",
        request=request, actor_id=current.id, actor_email=current.email,
        org_id=org.id, target_type="organization", target_id=org.id,
        detail={"owner_id": str(data.owner_id), "owner_email": new_owner.email},
    )
    return {
        "id": str(org.id),
        "name": org.name,
        "slug": org.slug,
        "owner_id": str(org.owner_id),
        "owner_email": new_owner.email,
    }


@router.delete("/organizations/{org_id}", status_code=204)
async def admin_delete_organization(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(404, "Organization not found")
    deleted = {"name": org.name, "slug": org.slug}
    await db.delete(org)
    await db.commit()
    await audit.record(
        db, audit.ORG_DELETED, request=request, actor_id=current.id,
        actor_email=current.email, org_id=org_id, target_type="organization",
        target_id=org_id, detail=deleted,
    )


# ── Organization-scoped API keys ───────────────────────────────────────────────

@router.get("/organizations/{org_id}/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    result = await db.execute(
        select(ApiKey).where(ApiKey.organization_id == org_id).order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/organizations/{org_id}/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=201,
)
async def create_api_key(
    org_id: uuid.UUID,
    data: ApiKeyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Name darf nicht leer sein")

    generated = api_key_svc.generate_key()
    api_key = ApiKey(
        organization_id=org_id,
        name=name,
        prefix=generated.prefix,
        key_hash=generated.key_hash,
        role=data.role,
        created_by_id=current.id,
        expires_at=data.expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    await audit.record(
        db, audit.API_KEY_CREATED, request=request, actor_id=current.id,
        actor_email=current.email, org_id=org_id, target_type="api_key",
        target_id=api_key.id, detail={"name": name, "role": data.role, "prefix": generated.prefix},
    )
    base = ApiKeyResponse.model_validate(api_key)
    return ApiKeyCreatedResponse(**base.model_dump(), key=generated.full_key)


@router.delete("/organizations/{org_id}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    api_key = await db.get(ApiKey, key_id)
    if not api_key or api_key.organization_id != org_id:
        raise HTTPException(404, "API key not found")
    if not api_key.revoked:
        api_key.revoked = True
        await db.commit()
        await audit.record(
            db, audit.API_KEY_REVOKED, request=request, actor_id=current.id,
            actor_email=current.email, org_id=org_id, target_type="api_key",
            target_id=key_id, detail={"name": api_key.name, "prefix": api_key.prefix},
        )


@router.post("/trigger-update", status_code=202)
async def trigger_update(
    _: User = Depends(require_superadmin),
):
    if os.path.exists(TRIGGER_FILE):
        raise HTTPException(409, "Update already triggered")
    # Write initial message so the SSE terminal shows something immediately
    # (updater may be sleeping up to INTERVAL seconds before it picks up the trigger)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "w") as f:
            f.write(f"[{ts}] Manuelles Update ausgelöst — warte auf Updater…\n")
    except OSError:
        pass
    # The backend runs as a non-root user; the shared /update_status volume is
    # owned by the updater. If the volume is not writable (e.g. an old, root-owned
    # volume that predates the non-root switch), surface a clear error instead of
    # a bare 500 — the updater chowns the volume to the backend user on its next
    # cycle, which heals this automatically.
    try:
        os.makedirs(os.path.dirname(TRIGGER_FILE), exist_ok=True)
        with open(TRIGGER_FILE, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except OSError as exc:
        logger.error("Cannot write update trigger file %s: %s", TRIGGER_FILE, exc)
        raise HTTPException(
            503,
            "Update konnte nicht ausgelöst werden: Das Update-Volume ist nicht "
            "beschreibbar. Der Updater repariert die Rechte automatisch beim "
            "nächsten Lauf — bitte in wenigen Minuten erneut versuchen.",
        ) from exc
    return {"status": "triggered"}


@router.get("/update-log")
async def stream_update_log(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream of the live updater log.

    Uses a token query-param because browser EventSource cannot set headers.
    The token must be a valid superadmin JWT.
    """
    # Validate token — require superadmin.  Re-check the DB so a revoked or
    # demoted admin cannot keep streaming after token_version is bumped or the
    # is_superadmin flag is cleared.
    # decode_stream_token rejects mfa_pending tokens and accepts a short-lived
    # stream ticket; the DB re-check below still ensures the account is active,
    # is (still) superadmin and the token version is current.
    token_data = decode_stream_token(token)
    if not token_data.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    db_result = await db.execute(select(User).where(User.id == token_data.user_id))
    db_user = db_result.scalar_one_or_none()
    if not db_user or not db_user.is_active:
        raise HTTPException(401, "Invalid token")
    if not db_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    if token_data.token_version != db_user.token_version:
        raise HTTPException(401, "Session expired — please log in again")

    async def log_generator():
        offset = 0
        # Stream for at most 15 minutes
        deadline = asyncio.get_event_loop().time() + 900
        done_phrases = ("Update complete", "Update failed", "Deploy failed", "update failed")

        yield "retry: 2000\n\n"  # reconnect interval hint

        # Keep the connection alive — send a comment every 20s if quiet
        last_activity = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() < deadline:
            try:
                with open(LOG_FILE, "r", errors="replace") as f:
                    f.seek(offset)
                    chunk = f.read()
                    if chunk:
                        offset += len(chunk.encode("utf-8", errors="replace"))
                        last_activity = asyncio.get_event_loop().time()
                        for line in chunk.splitlines():
                            # Send every non-empty line (skip truly blank lines)
                            if line.strip():
                                yield f"data: {line}\n\n"
                            # Signal end when a terminal phrase appears
                            if any(p in line for p in done_phrases):
                                yield "event: done\ndata: \n\n"
                                return
            except FileNotFoundError:
                pass

            # Keep-alive comment if silent for > 20s (prevents proxy timeouts)
            if asyncio.get_event_loop().time() - last_activity > 20:
                yield ": keepalive\n\n"
                last_activity = asyncio.get_event_loop().time()

            await asyncio.sleep(0.5)

        yield "event: done\ndata: timeout\n\n"

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx/Caddy buffering
        },
    )


# ── SMTP Settings ─────────────────────────────────────────────────────────────

SMTP_KEYS = ["smtp.host", "smtp.port", "smtp.username", "smtp.password",
             "smtp.from_email", "smtp.from_name", "smtp.use_tls"]


class SmtpConfig(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "ConvoyPlan"
    use_tls: str = "starttls"   # "starttls" | "ssl" | "false"


class SmtpConfigResponse(BaseModel):
    host: str
    port: int
    username: str
    password_set: bool          # never expose actual password
    from_email: str
    from_name: str
    use_tls: str
    configured: bool


@router.get("/settings/smtp", response_model=SmtpConfigResponse)
async def get_smtp_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key.in_(SMTP_KEYS))
    )
    rows = {r.key: r.value for r in result.scalars().all()}
    host = rows.get("smtp.host", "")
    return SmtpConfigResponse(
        host=host,
        port=int(rows.get("smtp.port", "587")),
        username=rows.get("smtp.username", ""),
        password_set=bool(rows.get("smtp.password", "")),
        from_email=rows.get("smtp.from_email", ""),
        from_name=rows.get("smtp.from_name", "ConvoyPlan"),
        use_tls=rows.get("smtp.use_tls", "starttls"),
        configured=bool(host),
    )


@router.put("/settings/smtp", status_code=204)
async def update_smtp_settings(
    data: SmtpConfig,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    await save_smtp_settings(db, {
        "smtp.host": data.host,
        "smtp.port": str(data.port),
        "smtp.username": data.username,
        "smtp.password": data.password,
        "smtp.from_email": data.from_email,
        "smtp.from_name": data.from_name,
        "smtp.use_tls": data.use_tls,
    })


@router.post("/settings/smtp/test")
async def smtp_test(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    result = await test_smtp_connection(db)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return {"status": "ok"}


# ── Send password email ───────────────────────────────────────────────────────


@router.post("/users/{user_id}/send-password", status_code=202)
async def send_user_password(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Generate a new password, update the user, and email credentials."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.org_memberships).selectinload(UserOrganization.organization))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    new_password = generate_password()
    user.hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    user.token_version += 1  # revoke the user's existing sessions
    await db.commit()

    # Pick login URL: first org login page if member, else superadmin login
    base_url = settings.app_base_url.rstrip("/")
    if user.org_memberships:
        first_org = user.org_memberships[0].organization
        login_url = f"{base_url}/o/{first_org.slug}/login" if first_org else f"{base_url}/login"
    else:
        login_url = f"{base_url}/login"

    try:
        await send_password_email(
            db=db,
            recipient_email=user.email,
            recipient_name=user.full_name,
            password=new_password,
            login_url=login_url,
        )
    except ValueError as e:
        logger.warning("Password email validation error: %s", e)
        raise HTTPException(400, "E-Mail-Konfiguration ungültig")
    except Exception as e:
        logger.warning("Failed to send password email: %s", e)
        logger.error("Failed to send password e-mail to user %s: %s", user.id, e)
        raise HTTPException(502, "E-Mail konnte nicht gesendet werden")

    return {"status": "sent", "email": user.email}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Generate a new password, update the user, and return the plaintext password
    so the admin can communicate it manually (without sending an email)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    new_password = generate_password()
    user.hashed_password = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    user.token_version += 1  # revoke the user's existing sessions
    await db.commit()

    return {"password": new_password, "email": user.email}


@router.post("/users/{user_id}/reset-mfa")
async def reset_user_mfa(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    """Clear MFA secret and disable MFA so a locked-out user can log in again."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    user.mfa_enabled = False
    user.mfa_secret = None
    user.token_version += 1  # revoke the user's existing sessions
    await db.commit()
    return {"status": "reset"}


# ── Audit log ─────────────────────────────────────────────────────────────────


class AuditLogEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    actor_email: str | None
    org_id: uuid.UUID | None
    target_type: str | None
    target_id: str | None
    ip: str | None
    detail: dict | None


@router.get("/audit-log", response_model=list[AuditLogEntry])
async def list_audit_log(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
    action: str | None = Query(None, description="Filter by action, e.g. auth.login.failure"),
    limit: int = Query(100, ge=1, le=500),
):
    """Return the most recent audit-log entries (newest first), superadmin only."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = select(AuditLog).where(AuditLog.action == action).order_by(
            AuditLog.created_at.desc()
        ).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        AuditLogEntry(
            id=r.id, created_at=r.created_at, action=r.action, actor_email=r.actor_email,
            org_id=r.org_id, target_type=r.target_type, target_id=r.target_id,
            ip=r.ip, detail=r.detail,
        )
        for r in rows
    ]


# ── Betroffenenrechte (DSGVO Art. 15 / 17) ──────────────────────────────────────


@router.get("/users/{user_id}/export")
async def export_user_data(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """Export all personal data held about a user as a JSON bundle (Art. 15).
    Secrets (password hash, MFA secret, tokens) are deliberately omitted."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.org_memberships).selectinload(UserOrganization.organization))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    vehicles = (await db.execute(select(Vehicle).where(Vehicle.owner_id == user_id))).scalars().all()
    convoys = (await db.execute(select(Convoy).where(Convoy.owner_id == user_id))).scalars().all()
    share_links = (
        await db.execute(select(ConvoyShareLink).where(ConvoyShareLink.created_by_id == user_id))
    ).scalars().all()
    audit_rows = (
        await db.execute(
            select(AuditLog).where(AuditLog.actor_id == user_id).order_by(AuditLog.created_at.desc())
        )
    ).scalars().all()

    bundle = {
        "exported_at": datetime.now(timezone.utc),
        "user": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "is_superadmin": user.is_superadmin,
            "mfa_enabled": user.mfa_enabled,
            "created_at": user.created_at,
        },
        "organizations": [
            {"org_id": m.organization.id, "name": m.organization.name, "role": m.role}
            for m in user.org_memberships if m.organization is not None
        ],
        "vehicles": [
            {
                "id": v.id, "name": v.name, "callsign": v.callsign,
                "license_plate": v.license_plate, "convoy_role": v.convoy_role,
                "height_cm": v.height_cm, "weight_kg": v.weight_kg, "length_cm": v.length_cm,
                "org_id": v.org_id,
            }
            for v in vehicles
        ],
        "convoys": [
            {
                "id": c.id, "name": c.name, "organization": c.organization,
                "organization_id": c.organization_id, "status": c.status,
                "start_time": c.start_time, "created_at": c.created_at,
            }
            for c in convoys
        ],
        "share_links_created": [
            {
                "id": s.id, "convoy_id": s.convoy_id, "slug": s.slug, "scope": s.scope,
                "created_at": s.created_at, "last_accessed_at": s.last_accessed_at,
                "access_count": s.access_count, "revoked": s.revoked,
            }
            for s in share_links
        ],
        "audit_log": [
            {
                "id": a.id, "created_at": a.created_at, "action": a.action,
                "target_type": a.target_type, "target_id": a.target_id,
                "ip": a.ip, "detail": a.detail,
            }
            for a in audit_rows
        ],
    }

    await audit.record(
        db, "user.data_exported", request=request, actor_id=current.id,
        actor_email=current.email, target_type="user", target_id=user_id,
    )
    return bundle


@router.delete("/users/{user_id}/data", status_code=204)
async def erase_user_data(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_superadmin),
):
    """Erase a user (Art. 17): delete the user + cascaded data, but *pseudonymise*
    the append-only audit trail instead of deleting it (security evidence is kept
    under the retention policy; see docs/iso-t5-retention-plan.md)."""
    if user_id == current.id:
        raise HTTPException(400, "Cannot erase yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    # Pseudonymise the user's audit entries (keep actor_id reference + actions).
    await db.execute(
        update(AuditLog)
        .where(AuditLog.actor_id == user_id)
        .values(actor_email=None, ip=None, user_agent=None)
    )
    await db.delete(user)
    await db.commit()

    await audit.record(
        db, "user.data_erased", request=request, actor_id=current.id,
        actor_email=current.email, target_type="user", target_id=user_id,
        detail={"audit_pseudonymized": True},
    )
