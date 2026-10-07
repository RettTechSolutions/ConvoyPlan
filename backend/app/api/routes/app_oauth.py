"""Anmeldung der Begleit-App über den Browser: aus der Sitzung einen Code machen.

``/authorize`` (SDK, ``services/oauth_provider._authorize_app``) schickt den
Browser auf ``/oauth/app`` im Frontend, mit einem signierten Ticket. Die Seite
fragt hier nach, und hier fällt die Entscheidung:

* **Keine Sitzung für die Organisation des Tickets** → 401; die Seite schickt
  auf die normale Anmeldeseite (``/o/<slug>/login?redirect=…``) — mit Passwort,
  MFA oder Passkey — und kommt danach zurück.
* **Kein Mitglied** → zurück an die App mit ``access_denied``. Eine andere
  Organisation wird nicht angeboten.
* **Sitzung erst in diesem Ablauf entstanden** → Code, ohne Rückfrage.
* **Ältere Sitzung** → 409; die Seite fragt einmal nach. Ohne diesen Klick
  könnte jede fremde Seite den Browser eines angemeldeten Menschen auf
  ``/authorize`` schicken und den Code an die App leiten lassen, die sich auf
  dem Gerät das Schema genommen hat (``services/app_client.py``).

Gelesen wird **nur** das Sitzungs-Cookie der Organisation aus dem Ticket,
nicht ``get_current_person``: wer sich in einer anderen Organisation
angemeldet hat, ist für diese hier nicht angemeldet.
"""
import logging
from datetime import datetime, timezone

import jwt as _jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from mcp.server.auth.provider import construct_redirect_uri
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import cookies
from app.api.deps import _benutzer_zum_token, _csrf_pruefen, _decode_token
from app.config import settings
from app.database import get_db
from app.models.organization import Organization, UserOrganization
from app.services import app_client, audit, oauth_provider, oauth_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth/app", tags=["auth"])

APP_GRANTED = "auth.app.granted"
APP_DENIED = "auth.app.denied"


class AnfrageInfo(BaseModel):
    org_slug: str
    org_name: str
    expires_at: datetime


class Entscheidung(BaseModel):
    request: str = Field(max_length=4096)
    # Der eine Klick bei einer älteren Sitzung. Ohne ihn antwortet der Server
    # mit 409, nicht mit einem Code.
    bestaetigt: bool = False
    abbrechen: bool = False


class Weiterleitung(BaseModel):
    redirect_url: str


def _aktiv_oder_404() -> None:
    if not app_client.aktiv():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Die App-Anmeldung ist auf dieser Instanz abgeschaltet")


def _ticket_oder_400(roh: str) -> dict:
    authz = oauth_provider.decode_app_request(roh)
    # Die Zieladresse steht im Ticket, das der Server signiert hat — und muss
    # trotzdem die eine sein. Eine Weiterleitung auf dem Bildschirm, auf dem
    # Zugriff entsteht, hängt nicht an einer Eigenschaft drei Dateien weiter.
    if authz is None or authz.get("redirect_uri") != app_client.REDIRECT_URI:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Die Anmeldeanfrage ist ungültig oder abgelaufen — bitte in der App neu starten",
        )
    return authz


def _zurueck(authz: dict, **params: str | None) -> Weiterleitung:
    return Weiterleitung(
        redirect_url=construct_redirect_uri(
            authz["redirect_uri"],
            state=authz.get("state"),
            # RFC 9207, auch im Fehlerfall — wie beim MCP-Zustimmungsschirm.
            iss=oauth_tokens.issuer_url(),
            **params,
        )
    )


@router.get("/anfrage", response_model=AnfrageInfo)
async def anfrage_lesen(request: str, db: AsyncSession = Depends(get_db)) -> AnfrageInfo:
    """Für welche Organisation die App anfragt — die Seite braucht den Slug für
    die Anmeldung und den Namen für die Anzeige. Ohne Anmeldung lesbar: der
    Name steht auch auf der Anmeldeseite (``/api/auth/org-lookup``)."""
    _aktiv_oder_404()
    authz = _ticket_oder_400(request)
    org = (
        await db.execute(select(Organization).where(Organization.slug == authz["org_slug"]))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unbekannte Organisation")
    return AnfrageInfo(
        org_slug=org.slug,
        org_name=org.name,
        expires_at=datetime.fromtimestamp(authz["exp"], tz=timezone.utc),
    )


@router.post("/anfrage", response_model=Weiterleitung)
async def anfrage_entscheiden(
    data: Entscheidung,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> Weiterleitung:
    _aktiv_oder_404()
    authz = _ticket_oder_400(data.request)
    slug = authz["org_slug"]

    if data.abbrechen:
        return _zurueck(authz, error="access_denied", error_description="Anmeldung abgebrochen")

    roh = http_request.cookies.get(cookies.cookie_name(slug))
    if not roh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    _csrf_pruefen(http_request)
    token_data = _decode_token(roh)
    if token_data.org_slug != slug:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    user = await _benutzer_zum_token(token_data, db)

    org = (
        await db.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none()
    mitglied = None
    if org is not None:
        mitglied = (
            await db.execute(
                select(UserOrganization).where(
                    UserOrganization.user_id == user.id,
                    UserOrganization.organization_id == org.id,
                )
            )
        ).scalar_one_or_none()
    if org is None or mitglied is None:
        await audit.record(
            db, APP_DENIED, request=http_request, actor_id=user.id, actor_email=user.email,
            target_type="oauth_client", target_id=app_client.CLIENT_ID,
            detail={"org_slug": slug, "grund": "kein Mitglied"},
        )
        await db.commit()
        return _zurueck(
            authz, error="access_denied", error_description="Kein Mitglied dieser Organisation"
        )

    sitzung_iat = _jwt.decode(
        roh, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"verify_aud": False}
    ).get("iat")
    if not data.bestaetigt and not app_client.frisch_angemeldet(sitzung_iat, authz.get("iat")):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "bestaetigen": True,
                "email": user.email,
                "org_name": org.name,
            },
        )

    await app_client.zeile_sicherstellen(db)
    code = await oauth_provider.mint_authorization_code(
        db,
        request={**authz, "resource": authz.get("resource") or app_client.api_resource_url()},
        user_id=user.id,
        organization_id=org.id,
        scopes=[],
    )
    await audit.record(
        db, APP_GRANTED, request=http_request, actor_id=user.id, actor_email=user.email,
        org_id=org.id, target_type="oauth_client", target_id=app_client.CLIENT_ID,
        detail={"bestaetigt": data.bestaetigt},
    )
    await db.commit()
    return _zurueck(authz, code=code)
