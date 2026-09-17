"""Ausstellen und Prüfen der Tokens des MCP-Servers.

Zwei Sorten, bewusst unterschiedlich gebaut:

**Access-Tokens** sind zustandslose JWTs mit ``typ="mcp"`` und kurzer
Laufzeit. Sie stehen in keiner Tabelle. Der Typ ist die Trennlinie zur
übrigen Anwendung: ``app/api/deps.py::_decode_token`` akzeptiert nur
``typ in ("access", "stream")``, damit ist ein MCP-Token an der REST-API
strukturell wertlos — und umgekehrt weist ``verify_access_token`` hier alles
zurück, was nicht ``typ="mcp"`` ist. Keine der beiden Richtungen hängt an
einer Konvention, beide an einer Prüfung.

**Refresh-Tokens** sind Zufallswerte, von denen nur der SHA-256-Hash
gespeichert wird, und sie rotieren: jeder Einlöseversuch gibt ein neues aus
und entwertet das alte. Taucht ein bereits rotiertes Token erneut auf, hat es
jemand mitgelesen — dann stirbt die ganze Familie.
"""
import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt as _jwt
from jwt.exceptions import InvalidTokenError
from pydantic import AnyHttpUrl
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.mcp import scopes as scope_svc
from app.models.oauth_refresh_token import OAuthRefreshToken
from app.models.organization import UserOrganization
from app.models.user import User

logger = logging.getLogger(__name__)

# Der Token-Typ, der ein MCP-Token von einem ConvoyPlan-Token unterscheidet.
TOKEN_TYPE = "mcp"


def token_hash(raw: str) -> str:
    """SHA-256-Hex eines Codes oder Refresh-Tokens.

    Absichtlich nicht bcrypt wie bei ``ApiKey``: die Werte sind
    256-Bit-Zufall, kein Passwort. Gegen Raten hilft die Entropie, und der
    Token-Endpunkt muss den Wert in einem Zugriff finden können."""
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def public_resource_url() -> str:
    """Die kanonische Resource-URI dieser Instanz (RFC 8707).

    Ohne abschließenden Schrägstrich — die Spec empfiehlt diese Form, und die
    aud-Claim der ausgestellten Tokens muss exakt dazu passen."""
    if settings.mcp_public_url:
        return settings.mcp_public_url.rstrip("/")
    return settings.app_base_url.rstrip("/") + "/mcp"


def issuer_url() -> str:
    """Der Issuer des Authorization Servers — die Instanz selbst.

    In genau der Schreibweise, die auch im Metadatendokument steht, und
    deshalb über ``AnyHttpUrl`` normalisiert: Das Dokument entsteht aus
    ``AuthSettings.issuer_url`` (siehe ``app/mcp/mount.py``), und Pydantic
    hängt einer nackten Domain dort einen Schrägstrich an. Ohne diese Zeile
    weist die Instanz ``https://host/`` aus und schickt im
    ``iss``-Parameter ``https://host`` — zwei verschiedene Zeichenketten für
    denselben Aussteller.

    Das ist kein Schönheitsfehler. RFC 9207 verlangt vom Client, ``iss``
    **zeichengenau** gegen den Aussteller aus der Metadata zu halten und die
    Anmeldung sonst abzubrechen; wir kündigen mit
    ``authorization_response_iss_parameter_supported`` ausdrücklich an, dass
    er sich darauf verlassen kann. Ein nachsichtiger Client übersieht die
    Abweichung, ein strenger bricht ab — und beides sieht von außen gleich
    aus, bis jemand einen strengen benutzt.
    """
    return str(AnyHttpUrl(settings.app_base_url.rstrip("/")))


# ── Access-Tokens ────────────────────────────────────────────────────────


def mint_access_token(
    *,
    user: User,
    organization_id: uuid.UUID,
    client_id: str,
    scopes: list[str],
    resource: str | None = None,
) -> tuple[str, int]:
    """Ein Access-Token ausstellen. Gibt (Token, Gültigkeit in Sekunden)."""
    ttl = timedelta(minutes=settings.mcp_access_token_ttl_minutes)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "iss": issuer_url(),
        # RFC 8707 / MCP-Spec: das Token gilt ausdrücklich nur für diese
        # Instanz. Ein Token von Instanz A ist an Instanz B wertlos.
        "aud": resource or public_resource_url(),
        "exp": now + ttl,
        "iat": now,
        "typ": TOKEN_TYPE,
        "org_id": str(organization_id),
        "client_id": client_id,
        "scope": " ".join(scopes),
        # Ein Bump von token_version (Passwortwechsel, "überall abmelden")
        # entwertet auch MCP-Tokens. Das ist gewollt.
        "tv": user.token_version,
    }
    return (
        _jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm),
        int(ttl.total_seconds()),
    )


@dataclass
class VerifiedToken:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    client_id: str
    scopes: list[str]
    resource: str
    expires_at: int


async def verify_access_token(db: AsyncSession, raw: str) -> VerifiedToken | None:
    """Ein präsentiertes Access-Token prüfen; None heißt abgelehnt.

    Geprüft wird die Signatur, der Typ, die Audience, der Ablauf — und dann
    noch einmal gegen die Datenbank: ist der Benutzer noch aktiv, ist seine
    Token-Version noch aktuell, und ist er überhaupt noch Mitglied der
    Organisation, für die das Token gilt. Eine Mitgliedschaft, die nach der
    Zustimmung entzogen wurde, macht das Token damit sofort wertlos, ohne dass
    es dafür einen Widerruf braucht.

    Zusätzlich fällt die Scope-Menge auf das zurück, was die *aktuelle* Rolle
    hergibt: wer von planer auf beobachter herabgestuft wird, verliert damit
    das Schreiben, ohne dass sein Token neu ausgestellt werden muss."""
    expected_audience = public_resource_url()
    try:
        payload = _jwt.decode(
            raw,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=expected_audience,
            issuer=issuer_url(),
        )
    except InvalidTokenError:
        return None

    if payload.get("typ") != TOKEN_TYPE:
        return None

    try:
        user_id = uuid.UUID(payload["sub"])
        org_id = uuid.UUID(payload["org_id"])
    except (KeyError, TypeError, ValueError):
        return None

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    if int(payload.get("tv", 0)) != user.token_version:
        return None

    membership = (
        await db.execute(
            select(UserOrganization).where(
                UserOrganization.user_id == user_id,
                UserOrganization.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        return None

    granted = [s for s in payload.get("scope", "").split() if s]
    effective = scope_svc.grantable(granted, membership.role)
    if not effective:
        # Nichts mehr übrig, was die Rolle hergibt — das Token ist tot.
        return None

    return VerifiedToken(
        user_id=user_id,
        organization_id=org_id,
        client_id=str(payload.get("client_id", "")),
        scopes=effective,
        resource=expected_audience,
        expires_at=int(payload.get("exp", 0)),
    )


# ── Refresh-Tokens ───────────────────────────────────────────────────────


async def mint_refresh_token(
    db: AsyncSession,
    *,
    family_id: uuid.UUID,
    client_id: str,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    scopes: list[str],
    resource: str | None,
) -> str:
    """Ein Refresh-Token ausstellen und seinen Hash ablegen."""
    raw = generate_secret()
    db.add(
        OAuthRefreshToken(
            token_hash=token_hash(raw),
            family_id=family_id,
            client_id=client_id,
            user_id=user_id,
            organization_id=organization_id,
            scopes=" ".join(scopes),
            resource=resource,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.mcp_refresh_token_ttl_days),
        )
    )
    return raw


async def revoke_family(db: AsyncSession, family_id: uuid.UUID, *, reason: str) -> int:
    """Alle Tokens einer Familie widerrufen. Gibt die Anzahl zurück."""
    result = await db.execute(
        update(OAuthRefreshToken)
        .where(OAuthRefreshToken.family_id == family_id, OAuthRefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    count = result.rowcount or 0
    if count:
        logger.warning(
            "MCP: Token-Familie %s widerrufen (%d Tokens), Grund: %s", family_id, count, reason
        )
    return count


async def load_refresh_token(db: AsyncSession, raw: str) -> OAuthRefreshToken | None:
    """Ein präsentiertes Refresh-Token auflösen; None heißt abgelehnt.

    Ein **bereits rotiertes** Token ist der interessante Fall: der
    rechtmäßige Client legt ein rotiertes Token nicht noch einmal vor, also
    hat es jemand mitgelesen. Darauf stirbt die ganze Familie — der Angreifer
    verliert den Zugang, der Benutzer muss sich neu verbinden. Das ist die
    richtige Seite des Tauschs."""
    row = (
        await db.execute(
            select(OAuthRefreshToken).where(OAuthRefreshToken.token_hash == token_hash(raw))
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    if row.rotated_at is not None:
        await revoke_family(db, row.family_id, reason="rotiertes Refresh-Token erneut vorgelegt")
        await db.commit()
        return None

    if row.revoked:
        return None
    if row.expires_at <= datetime.now(timezone.utc):
        return None
    return row
