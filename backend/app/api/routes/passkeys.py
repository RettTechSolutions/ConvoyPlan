"""Passkeys: anlegen, auflisten, löschen — und damit anmelden.

Die Regeln stehen in ``services/passkey.py``; hier die Verdrahtung.

**Anmelden** geht ohne E-Mail-Adresse: der Browser bietet die Passkeys an,
die er für diese Domain kennt (auffindbare Zugangsdaten), und die Antwort
nennt den Passkey selbst. Danach gelten dieselben Bedingungen wie beim
Passwort — aktives Konto, Mitglied der Organisation, ohne Organisation nur
Superadmin — und dieselbe Antwort, wenn eine davon fehlt. Die Pfade liegen
unter ``/api/auth/login``, weil der Lizenzwächter genau dieses Präfix
durchlässt: angemeldet werden muss man auch im Demo-Modus.

**Anlegen** verlangt das Passwort noch einmal. Ein Passkey ist ein Zugang,
der bleibt, wenn das Passwort geändert wird; wer eine Sitzung kurz in die
Hand bekommt — ein offener Rechner in der Wache —, soll sich darüber keinen
dauerhaften eigenen verschaffen können.

**Löschen** verlangt nichts weiter: es nimmt einen Zugang weg und gibt keinen.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import options_to_json_dict
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.api import cookies
from app.api.deps import get_current_user
from app.api.routes.auth import LoginResponse, _checkpw, _reject_demo_user, create_token
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.models.passkey import Passkey
from app.models.user import User
from app.services import audit
from app.services import passkey as pk
from app.services.password import MAX_PASSWORD_LENGTH
from app.services.rate_limit import rate_limit, register_failure

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_UNGUELTIG = "Invalid credentials"


def _transports(werte: list[str]) -> list[AuthenticatorTransport]:
    bekannt = {t.value for t in AuthenticatorTransport}
    return [AuthenticatorTransport(t) for t in werte if t in bekannt]


def _raw_id(credential: dict[str, Any]) -> bytes | None:
    try:
        return base64url_to_bytes(str(credential.get("rawId") or credential.get("id") or ""))
    except Exception:
        return None


# ── Anmelden ──────────────────────────────────────────────────────────────────


class PasskeyOptionsResponse(BaseModel):
    challenge_id: str
    options: dict[str, Any]


class PasskeyLoginRequest(BaseModel):
    challenge_id: str = Field(max_length=64)
    credential: dict[str, Any]
    org_slug: str | None = None


@router.post(
    "/login/passkey/options",
    response_model=PasskeyOptionsResponse,
    dependencies=[Depends(rate_limit("passkey-login", max_attempts=10, window_seconds=300))],
)
async def passkey_login_options():
    """Optionen für ``navigator.credentials.get`` — ohne Benutzer.

    Keine ``allowCredentials``: der Browser wählt selbst unter den Passkeys
    für diese Domain. Eine Liste hier setzte voraus, dass man vorher weiß,
    wer sich anmeldet, und verriete auf Nachfrage, welche Konten Passkeys
    haben."""
    kennung, challenge = pk.ausstellen(pk.LOGIN)
    optionen = generate_authentication_options(
        rp_id=pk.rp_id(),
        challenge=challenge,
        timeout=pk.TIMEOUT_MS,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return PasskeyOptionsResponse(challenge_id=kennung, options=options_to_json_dict(optionen))


@router.post(
    "/login/passkey",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limit("passkey-login", max_attempts=10, window_seconds=300))],
)
async def passkey_login(
    data: PasskeyLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Eine signierte Challenge gegen eine Sitzung tauschen.

    Kein zweiter Schritt mit TOTP, auch wenn MFA eingeschaltet ist: der
    Passkey hat Besitz und PIN/Biometrie schon belegt (siehe
    ``services/passkey``)."""
    user: User | None = None
    try:
        challenge = pk.einloesen(data.challenge_id, pk.LOGIN)
        if challenge is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Anmeldung abgelaufen — bitte erneut versuchen")

        raw_id = _raw_id(data.credential)
        eintrag = None
        if raw_id:
            eintrag = (
                await db.execute(select(Passkey).where(Passkey.credential_id == raw_id))
            ).scalar_one_or_none()
        if eintrag is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNGUELTIG)

        try:
            geprueft = verify_authentication_response(
                credential=data.credential,
                expected_challenge=challenge,
                expected_rp_id=pk.rp_id(),
                expected_origin=pk.origin(),
                credential_public_key=eintrag.public_key,
                credential_current_sign_count=eintrag.sign_count,
                require_user_verification=True,
            )
        except Exception as exc:
            logger.info("Passkey-Anmeldung abgelehnt: %s", exc)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNGUELTIG)

        # Die Bibliothek prüft den Zähler selbst nur, wenn er gezählt wird —
        # hier noch einmal ausdrücklich, damit die Regel an einer Stelle steht,
        # die ein Test ohne Gerät erreicht.
        if not pk.zaehler_ok(eintrag.sign_count, geprueft.new_sign_count):
            logger.warning("Passkey %s: Signaturzähler rückläufig — möglicher Klon", eintrag.id)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNGUELTIG)

        user = await db.get(User, eintrag.user_id)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNGUELTIG)
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account deactivated")

        org: Organization | None = None
        membership: UserOrganization | None = None
        if data.org_slug:
            org = (
                await db.execute(select(Organization).where(Organization.slug == data.org_slug))
            ).scalar_one_or_none()
            if org is not None:
                membership = (
                    await db.execute(
                        select(UserOrganization).where(
                            UserOrganization.user_id == user.id,
                            UserOrganization.organization_id == org.id,
                        )
                    )
                ).scalar_one_or_none()
            if org is None or membership is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNGUELTIG)
        elif not user.is_superadmin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Superadmin required")

        eintrag.sign_count = geprueft.new_sign_count
        eintrag.backed_up = geprueft.credential_backed_up
        eintrag.last_used_at = datetime.now(timezone.utc)
        await db.commit()

        if org is not None and membership is not None:
            token = create_token(str(user.id), False, str(org.id), org.slug, membership.role, user.token_version)
            await audit.record(
                db, audit.LOGIN_SUCCESS, request=request, actor_id=user.id,
                actor_email=user.email, org_id=org.id, detail={"scope": "org", "passkey": True},
            )
            cookies.set_session_cookie(response, token, org.slug)
        else:
            token = create_token(str(user.id), True, token_version=user.token_version)
            await audit.record(
                db, audit.LOGIN_SUCCESS, request=request, actor_id=user.id,
                actor_email=user.email, detail={"scope": "superadmin", "passkey": True},
            )
            cookies.set_session_cookie(response, token)
        return LoginResponse(access_token=token)

    except HTTPException as exc:
        register_failure(request, "passkey-login")
        await audit.record(
            db, audit.LOGIN_FAILURE, request=request,
            actor_id=user.id if user else None, actor_email=user.email if user else None,
            detail={"reason": exc.detail, "org_slug": data.org_slug, "passkey": True},
        )
        raise


# ── Verwalten ─────────────────────────────────────────────────────────────────


class PasskeyInfo(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    backed_up: bool


class PasskeyRegisterOptionsRequest(BaseModel):
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class PasskeyRegisterRequest(BaseModel):
    challenge_id: str = Field(max_length=64)
    credential: dict[str, Any]
    name: str | None = Field(default=None, max_length=100)


def _info(p: Passkey) -> PasskeyInfo:
    return PasskeyInfo(
        id=p.id, name=p.name, created_at=p.created_at,
        last_used_at=p.last_used_at, backed_up=p.backed_up,
    )


@router.get("/passkeys", response_model=list[PasskeyInfo])
async def list_passkeys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Passkey).where(Passkey.user_id == current_user.id).order_by(Passkey.created_at)
        )
    ).scalars().all()
    return [_info(p) for p in rows]


@router.post(
    "/passkeys/register/options",
    response_model=PasskeyOptionsResponse,
    dependencies=[Depends(rate_limit("passkey-register", max_attempts=10, window_seconds=300))],
)
async def passkey_register_options(
    data: PasskeyRegisterOptionsRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Optionen für ``navigator.credentials.create`` — nach erneuter
    Passworteingabe (siehe Modulkopf)."""
    _reject_demo_user(current_user)
    if not _checkpw(data.password, current_user):
        register_failure(request, "passkey-register")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passwort ist falsch")

    vorhandene = (
        await db.execute(select(Passkey).where(Passkey.user_id == current_user.id))
    ).scalars().all()
    if len(vorhandene) >= pk.MAX_PASSKEYS_JE_BENUTZER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Höchstens {pk.MAX_PASSKEYS_JE_BENUTZER} Passkeys je Konto — bitte zuerst einen entfernen",
        )

    kennung, challenge = pk.ausstellen(pk.REGISTRIERUNG, str(current_user.id))
    optionen = generate_registration_options(
        rp_id=pk.rp_id(),
        rp_name=pk.RP_NAME,
        # Die Benutzerkennung im Passkey ist die UUID, nicht die E-Mail: sie
        # landet auf dem Gerät und gegebenenfalls in dessen Cloud, und eine
        # Adresse ändert sich, die Kennung nicht.
        user_id=current_user.id.bytes,
        user_name=current_user.email,
        user_display_name=current_user.full_name or current_user.email,
        challenge=challenge,
        timeout=pk.TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        # Dasselbe Gerät nicht zweimal — der Browser meldet es dann selbst.
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=p.credential_id, transports=_transports(p.transports or []))
            for p in vorhandene
        ],
    )
    return PasskeyOptionsResponse(challenge_id=kennung, options=options_to_json_dict(optionen))


@router.post(
    "/passkeys/register",
    response_model=PasskeyInfo,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("passkey-register", max_attempts=10, window_seconds=300))],
)
async def passkey_register(
    data: PasskeyRegisterRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _reject_demo_user(current_user)
    challenge = pk.einloesen(data.challenge_id, pk.REGISTRIERUNG, str(current_user.id))
    if challenge is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Einrichtung abgelaufen — bitte erneut starten")

    try:
        geprueft = verify_registration_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=pk.rp_id(),
            expected_origin=pk.origin(),
            require_user_verification=True,
        )
    except Exception as exc:
        logger.info("Passkey-Registrierung abgelehnt: %s", exc)
        register_failure(request, "passkey-register")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passkey konnte nicht geprüft werden")

    schon_da = (
        await db.execute(select(func.count()).select_from(Passkey).where(Passkey.credential_id == geprueft.credential_id))
    ).scalar_one()
    if schon_da:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dieser Passkey ist bereits eingerichtet")

    antwort = data.credential.get("response")
    roh = antwort.get("transports") if isinstance(antwort, dict) else None
    transports = [t for t in roh if isinstance(t, str)][:10] if isinstance(roh, list) else []

    name = (data.name or "").strip() or pk.standardname(transports, geprueft.credential_backed_up)
    eintrag = Passkey(
        user_id=current_user.id,
        credential_id=geprueft.credential_id,
        public_key=geprueft.credential_public_key,
        sign_count=geprueft.sign_count,
        transports=transports,
        name=name,
        backed_up=geprueft.credential_backed_up,
    )
    db.add(eintrag)
    await db.commit()
    await db.refresh(eintrag)
    await audit.record(
        db, audit.PASSKEY_ADDED, request=request, actor_id=current_user.id,
        actor_email=current_user.email, target_type="passkey", target_id=str(eintrag.id),
        detail={"name": eintrag.name},
    )
    return _info(eintrag)


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_passkey(
    passkey_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    eintrag = await db.get(Passkey, passkey_id)
    # Ein fremder Passkey ist für diesen Aufrufer nicht da — dieselbe 404.
    if eintrag is None or eintrag.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Passkey nicht gefunden")
    name = eintrag.name
    await db.delete(eintrag)
    await db.commit()
    await audit.record(
        db, audit.PASSKEY_REMOVED, request=request, actor_id=current_user.id,
        actor_email=current_user.email, target_type="passkey", target_id=str(passkey_id),
        detail={"name": name},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
