"""ConvoyPlan als OAuth-2.1-Authorization-Server für den MCP-Endpunkt.

Eine On-Prem-Installation hat keinen externen Identitätsanbieter, und
Benutzer, Passwörter, MFA, Organisationen und die Rollenhierarchie liegen
ohnehin in der eigenen Datenbank. Also ist die Instanz beides: Resource
Server *und* Authorization Server. Die Spec lässt das ausdrücklich zu.

Das SDK liefert die Endpunkte (``/authorize``, ``/token``, ``/register``,
``/revoke``) samt PKCE-Prüfung, ``redirect_uri``-Abgleich und Ablaufkontrolle
mit. Hier steht nur, was ConvoyPlan-spezifisch ist: wo die Daten liegen und
wer zustimmen darf.

**Die Zustimmung ist nicht Teil des ``authorize``-Aufrufs.** Der Provider
legt die Anfrage nur in einem signierten, kurzlebigen Umschlag ab und
schickt den Browser auf den Consent-Screen des Frontends. Erst wenn sich
dort ein Benutzer angemeldet (inklusive MFA), eine Organisation gewählt und
zugestimmt hat, entsteht ein Autorisierungscode. Damit hängt jedes MCP-Token
an einer bewussten Handlung eines Menschen, nicht an einer Registrierung.
"""
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import jwt as _jwt
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db_session
from app.mcp import scopes as scope_svc
from app.models.oauth_client import AUTH_METHOD_NONE, OAuthClient
from app.models.oauth_code import OAuthCode
from app.models.oauth_refresh_token import OAuthRefreshToken
from app.models.user import User
from app.services import crypto, mcp_config, oauth_tokens, safe_fetch

logger = logging.getLogger(__name__)

# Typ des signierten Umschlags, der eine angefangene Autorisierung trägt.
# Eigener Typ, damit er an keiner anderen Stelle als Token durchgeht.
_AUTHZ_REQUEST_TYPE = "mcp_authz"


# ── Redirect-URI-Prüfung ─────────────────────────────────────────────────


def validate_redirect_uri(raw: str) -> None:
    """Eine bei der Registrierung angegebene Redirect-URI prüfen.

    Zugelassen sind HTTPS-URLs und — für lokal laufende Clients wie Claude
    Desktop, die keinen öffentlichen Endpunkt haben — HTTP auf Loopback.
    Alles andere fliegt raus: ``http://`` auf eine fremde Adresse würde den
    Autorisierungscode im Klartext übers Netz schicken.

    Kein Wildcard, kein Präfix-Match, kein Fragment. Der Abgleich beim
    Autorisieren ist exakter Zeichenvergleich (das erledigt das SDK), und
    diese Prüfung stellt sicher, dass gar nicht erst etwas registriert wird,
    dessen exakter Vergleich gefährlich wäre."""
    try:
        parsed = urlparse(raw)
    except ValueError:
        raise RegistrationError("invalid_redirect_uri", f"Ungültige Redirect-URI: {raw}")

    if parsed.fragment:
        raise RegistrationError(
            "invalid_redirect_uri", "Redirect-URIs dürfen kein Fragment enthalten"
        )
    if "*" in raw:
        raise RegistrationError("invalid_redirect_uri", "Platzhalter sind nicht zulässig")

    if parsed.scheme == "https":
        if not parsed.hostname:
            raise RegistrationError("invalid_redirect_uri", "Redirect-URI ohne Host")
        return

    if parsed.scheme == "http":
        # Loopback-Ausnahme (RFC 8252 §7.3). "localhost" ist mitgemeint, weil
        # die verbreiteten MCP-Clients es so schreiben.
        if parsed.hostname in ("127.0.0.1", "::1", "localhost"):
            return
        raise RegistrationError(
            "invalid_redirect_uri",
            "HTTP ist nur für Loopback-Adressen zulässig — sonst HTTPS verwenden",
        )

    raise RegistrationError(
        "invalid_redirect_uri", f"Nicht unterstütztes Schema: {parsed.scheme or '(keines)'}"
    )


# ── Signierter Umschlag für eine angefangene Autorisierung ───────────────


def encode_authorize_request(client_id: str, params: AuthorizationParams) -> str:
    """Die Autorisierungsanfrage in ein kurzlebiges, signiertes Ticket packen.

    Zustandslos statt in einer Tabelle: die Anfrage lebt nur die Minuten
    zwischen Weiterleitung und Zustimmung, sie enthält nichts Geheimes (der
    ``code_challenge`` ist öffentlich, das ist der Punkt an PKCE), und ohne
    Zeile gibt es auch nichts aufzuräumen. Die Signatur verhindert, dass
    jemand sich selbst eine Anfrage baut — etwa mit einer redirect_uri, die
    nie registriert wurde."""
    now = datetime.now(timezone.utc)
    return _jwt.encode(
        {
            "typ": _AUTHZ_REQUEST_TYPE,
            "client_id": client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "scopes": params.scopes or [],
            "state": params.state,
            "resource": params.resource,
            "exp": now + timedelta(minutes=settings.mcp_authorize_request_ttl_minutes),
            "iat": now,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_authorize_request(ticket: str) -> dict | None:
    """Ein Autorisierungsticket auspacken; None heißt ungültig oder abgelaufen."""
    try:
        payload = _jwt.decode(ticket, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError:
        return None
    if payload.get("typ") != _AUTHZ_REQUEST_TYPE:
        return None
    return payload


# ── Client ID Metadata Documents ─────────────────────────────────────────
#
# Der in der MCP-Revision 2026-07-28 vorgesehene Nachfolger der dynamischen
# Registrierung: statt sich beim Server einzutragen, veröffentlicht ein
# Programm seine Angaben unter einer HTTPS-URL — und **diese URL ist die
# client_id**. Der Vorteil: nichts wird gespeichert, was nicht der
# Betreiber des Clients selbst kontrolliert, und ein zurückgezogenes
# Dokument entzieht dem Client den Zugang von seiner Seite aus.
#
# Der Preis: der Server ruft eine Adresse ab, die der Anfragende bestimmt.
# Deshalb ausschließlich über ``safe_fetch`` und standardmäßig abgeschaltet.

# Abgerufene Dokumente im Speicher, damit nicht jede Autorisierung einen
# Netzzugriff auslöst. Prozessweit und flüchtig — ein Neustart leert ihn, und
# genau das ist bei einem Cache für fremde Angaben richtig.
_cimd_cache: dict[str, tuple[float, OAuthClientInformationFull]] = {}


def _cimd_cache_gueltig(eintrag: tuple[float, OAuthClientInformationFull]) -> bool:
    alter = time.time() - eintrag[0]
    return alter < settings.mcp_cimd_cache_minutes * 60


def reset_cimd_cache() -> None:
    """Den Cache leeren. Für Tests und für den Fall, dass ein Betreiber eine
    zurückgezogene Registrierung sofort wirksam machen will."""
    _cimd_cache.clear()


def ist_cimd_client_id(client_id: str) -> bool:
    """Ob eine client_id als Metadatendokument zu verstehen ist.

    Die Spec unterscheidet an genau einem Merkmal: eine client_id, die wie
    eine HTTPS-URL aussieht, *ist* eine. Alles andere ist ein registrierter
    Bezeichner."""
    return client_id.startswith("https://")


async def loese_cimd_auf(client_id: str) -> OAuthClientInformationFull | None:
    """Ein Client ID Metadata Document abrufen und prüfen.

    Gibt None zurück, wenn es nicht abrufbar oder nicht stimmig ist — der
    Aufrufer behandelt das wie einen unbekannten Client. Die Gründe stehen
    im Log, nicht in der Antwort: einem Anfragenden zu erklären, warum genau
    sein Dokument abgelehnt wurde, hilft vor allem beim Sondieren."""
    # Der *geltende* Zustand, nicht allein die Umgebungsvariable: der
    # Schalter sitzt im Admin-Portal und soll ohne Neustart wirken. Wird er
    # zugedreht, während ein Dokument im Zwischenspeicher liegt, ist die
    # Abfrage hier trotzdem die erste — der Cache wird gar nicht erreicht.
    async with get_db_session() as db:
        if not await mcp_config.is_cimd_allowed(db):
            return None

    zwischengespeichert = _cimd_cache.get(client_id)
    if zwischengespeichert is not None and _cimd_cache_gueltig(zwischengespeichert):
        return zwischengespeichert[1]

    try:
        dokument = await safe_fetch.fetch_json(client_id)
    except safe_fetch.UnsafeUrlError as exc:
        logger.warning("MCP: CIMD %s abgelehnt: %s", client_id, exc)
        return None

    # Das Dokument muss sich selbst als das ausweisen, was abgerufen wurde.
    # Ohne diese Prüfung könnte ein Dokument unter der eigenen Adresse eine
    # fremde client_id behaupten und damit deren Zustimmungen erben.
    if dokument.get("client_id") != client_id:
        logger.warning(
            "MCP: CIMD %s abgelehnt — das Dokument nennt sich %r",
            client_id, dokument.get("client_id"),
        )
        return None

    redirect_uris = dokument.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        logger.warning("MCP: CIMD %s abgelehnt — keine redirect_uris", client_id)
        return None
    try:
        for uri in redirect_uris:
            validate_redirect_uri(str(uri))
    except RegistrationError as exc:
        logger.warning("MCP: CIMD %s abgelehnt — %s", client_id, exc.error_description)
        return None

    try:
        client = OAuthClientInformationFull(
            client_id=client_id,
            # Ein CIMD-Client ist per Konstruktion öffentlich: es gibt
            # niemanden, der ihm ein Secret hätte ausstellen können.
            client_secret=None,
            token_endpoint_auth_method="none",
            client_name=str(dokument.get("client_name") or "")[:255] or None,
            redirect_uris=[str(u) for u in redirect_uris],
            grant_types=list(dokument.get("grant_types") or
                             ["authorization_code", "refresh_token"]),
            scope=str(dokument.get("scope") or "") or None,
        )
    except ValidationError as exc:
        logger.warning("MCP: CIMD %s abgelehnt — unbrauchbare Angaben: %s", client_id, exc)
        return None

    _cimd_cache[client_id] = (time.time(), client)
    logger.info("MCP: CIMD %s aufgelöst (Name laut Dokument: %r)",
                client_id, client.client_name)
    return client


# ── Provider ─────────────────────────────────────────────────────────────


class ConvoyPlanOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    # ---- Clients ----

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        # Eine HTTPS-client_id ist ein Metadatendokument, kein Bezeichner in
        # der Datenbank — dort steht sie gar nicht.
        if ist_cimd_client_id(client_id):
            return await loese_cimd_auf(client_id)

        async with get_db_session() as db:
            row = await db.get(OAuthClient, client_id)
            if row is None or row.revoked:
                return None
            if (
                row.client_secret_expires_at is not None
                and row.client_secret_expires_at <= datetime.now(timezone.utc)
            ):
                return None
            return _to_client_information(row)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not settings.mcp_allow_dcr:
            raise RegistrationError(
                "invalid_client_metadata",
                "Dynamische Client-Registrierung ist auf dieser Instanz abgeschaltet",
            )
        if not client_info.redirect_uris:
            raise RegistrationError(
                "invalid_redirect_uri", "Mindestens eine Redirect-URI ist erforderlich"
            )
        for uri in client_info.redirect_uris:
            validate_redirect_uri(str(uri))

        # Das SDK mintet das Secret und vergleicht es später selbst im
        # Klartext, also muss es zurückholbar sein: Fernet statt Hash, genau
        # wie bei den MFA-Geheimnissen. Ein Angreifer mit reinem Lesezugriff
        # auf die Datenbank kommt damit nicht an die Secrets, solange
        # MFA_ENCRYPTION_KEY getrennt verwahrt wird.
        secret_encrypted = None
        if client_info.client_secret:
            secret_encrypted = crypto.encrypt_secret(client_info.client_secret)

        async with get_db_session() as db:
            db.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    client_secret_encrypted=secret_encrypted,
                    # Selbstauskunft des Anfragenden. Wird auf dem
                    # Consent-Screen als unbestätigt gekennzeichnet.
                    client_name=(client_info.client_name or "")[:255],
                    redirect_uris=[str(u) for u in client_info.redirect_uris],
                    grant_types=list(client_info.grant_types or []),
                    token_endpoint_auth_method=(
                        client_info.token_endpoint_auth_method or AUTH_METHOD_NONE
                    ),
                    scope=(client_info.scope or "")[:255],
                    client_secret_expires_at=_ts_to_datetime(
                        client_info.client_secret_expires_at
                    ),
                )
            )
            await db.commit()
        logger.info(
            "MCP: Client registriert (%s, Name laut Anfrage: %r)",
            client_info.client_id,
            client_info.client_name,
        )

    # ---- Autorisierung ----

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        # Der *geltende* Zustand — Datenbank schlägt Umgebungsvariable. Stand
        # hier ``settings.mcp_enabled``, war es derselbe Fehler wie zuvor im
        # Consent-Router (siehe ``routes/mcp_consent.py``), nur eine Station
        # früher: Auf einer Instanz mit ``MCP_ENABLED=false`` und dem Schalter
        # im Portal auf „an" sind die Routen montiert, ``/register`` und die
        # Well-Known-Dokumente antworten — und ``/authorize`` schickte jeden
        # Client mit ``temporarily_unavailable`` zurück. Sichtbar war davon
        # nur, dass sich Registrierungen häuften, zu denen nie eine
        # Zustimmung entstand.
        async with get_db_session() as db:
            aktiv = await mcp_config.is_mcp_enabled(db)
        if not aktiv:
            raise AuthorizeError(
                "temporarily_unavailable", "Der MCP-Zugang ist auf dieser Instanz abgeschaltet"
            )

        # RFC 8707: Ein Token, das für eine andere Resource gedacht ist,
        # stellen wir nicht aus. Ohne diese Prüfung könnte ein Client sich
        # hier ein Token für eine fremde Instanz holen lassen.
        expected = oauth_tokens.public_resource_url()
        if params.resource and params.resource.rstrip("/") != expected:
            raise AuthorizeError(
                "invalid_target",
                f"Diese Instanz stellt nur Tokens für {expected} aus",
            )

        # Angefragte Scopes gegen den bekannten Vorrat prüfen. Die endgültige
        # Zuteilung macht die Consent-Strecke anhand der Rolle des Benutzers —
        # hier fällt nur auf, wenn jemand etwas Unbekanntes verlangt.
        # Ohne Angabe bleibt es beim Minimum. ``SCOPES_SUPPORTED`` wäre hier
        # falsch: das weist aus, was die Resource versteht, und ein Client,
        # der nichts verlangt, soll nicht alles bekommen.
        requested = params.scopes or list(scope_svc.REQUIRED_SCOPES)
        unknown = [s for s in requested if s not in scope_svc.ALL_SCOPES]
        if unknown:
            raise AuthorizeError("invalid_scope", f"Unbekannte Scopes: {', '.join(unknown)}")

        ticket = encode_authorize_request(client.client_id, params)
        base = settings.app_base_url.rstrip("/")
        return f"{base}/oauth/consent?request={ticket}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with get_db_session() as db:
            row = (
                await db.execute(
                    select(OAuthCode).where(
                        OAuthCode.code_hash == oauth_tokens.token_hash(authorization_code)
                    )
                )
            ).scalar_one_or_none()
            if row is None or row.client_id != client.client_id:
                return None

            if row.consumed_at is not None:
                # Der rechtmäßige Client löst einen Code genau einmal ein.
                # Ein zweites Mal heißt: jemand hat ihn abgefangen. Dann
                # stirbt auch alles, was aus dem ersten Einlösen entstanden
                # ist — sonst behielte der Angreifer sein Refresh-Token.
                await oauth_tokens.revoke_family(
                    db, row.family_id, reason="Autorisierungscode erneut vorgelegt"
                )
                await db.commit()
                return None

            return AuthorizationCode(
                code=authorization_code,
                scopes=row.scopes.split(),
                expires_at=row.expires_at.timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=row.redirect_uri,
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                resource=row.resource,
                subject=str(row.user_id),
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code_hash = oauth_tokens.token_hash(authorization_code.code)
        now = datetime.now(timezone.utc)

        async with get_db_session() as db:
            # Einmalverwendung in einem Schritt: nur wer die Zeile von
            # "unverbraucht" auf "verbraucht" dreht, bekommt sie. Zwei
            # gleichzeitige Einlöseversuche können so nicht beide gewinnen.
            claimed = await db.execute(
                update(OAuthCode)
                .where(OAuthCode.code_hash == code_hash, OAuthCode.consumed_at.is_(None))
                .values(consumed_at=now)
                .returning(
                    OAuthCode.user_id,
                    OAuthCode.organization_id,
                    OAuthCode.scopes,
                    OAuthCode.resource,
                    OAuthCode.family_id,
                )
            )
            claim = claimed.first()
            if claim is None:
                raise TokenError("invalid_grant", "Autorisierungscode bereits eingelöst")

            user_id, org_id, scopes_raw, resource, family_id = claim
            user = await db.get(User, user_id)
            if user is None or not user.is_active:
                await db.commit()
                raise TokenError("invalid_grant", "Benutzerkonto nicht mehr aktiv")

            scopes = scopes_raw.split()
            access_token, expires_in = oauth_tokens.mint_access_token(
                user=user,
                organization_id=org_id,
                client_id=client.client_id,
                scopes=scopes,
                resource=resource,
            )
            refresh = await oauth_tokens.mint_refresh_token(
                db,
                family_id=family_id,
                client_id=client.client_id,
                user_id=user_id,
                organization_id=org_id,
                scopes=scopes,
                resource=resource,
            )
            await db.execute(
                update(OAuthClient)
                .where(OAuthClient.client_id == client.client_id)
                .values(last_used_at=now)
            )
            await db.commit()

        return OAuthToken(
            access_token=access_token,
            expires_in=expires_in,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    # ---- Refresh ----

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with get_db_session() as db:
            row = await oauth_tokens.load_refresh_token(db, refresh_token)
            if row is None or row.client_id != client.client_id:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=row.scopes.split(),
                expires_at=int(row.expires_at.timestamp()),
                resource=row.resource,
                subject=str(row.user_id),
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        now = datetime.now(timezone.utc)
        async with get_db_session() as db:
            # Rotation in einem Schritt, aus demselben Grund wie beim Code:
            # zwei gleichzeitige Versuche dürfen nicht beide gewinnen.
            rotated = await db.execute(
                update(OAuthRefreshToken)
                .where(
                    OAuthRefreshToken.token_hash == oauth_tokens.token_hash(refresh_token.token),
                    OAuthRefreshToken.rotated_at.is_(None),
                    OAuthRefreshToken.revoked.is_(False),
                )
                .values(rotated_at=now, last_used_at=now)
                .returning(
                    OAuthRefreshToken.family_id,
                    OAuthRefreshToken.user_id,
                    OAuthRefreshToken.organization_id,
                    OAuthRefreshToken.scopes,
                    OAuthRefreshToken.resource,
                )
            )
            claim = rotated.first()
            if claim is None:
                raise TokenError("invalid_grant", "Refresh-Token ungültig oder bereits verwendet")

            family_id, user_id, org_id, granted_raw, resource = claim
            granted = granted_raw.split()

            # Eine Verengung ist erlaubt, eine Ausweitung nie: ein Client darf
            # sich über den Refresh nicht mehr holen, als ihm zugestimmt wurde.
            requested = scopes or granted
            widened = [s for s in requested if not scope_svc.satisfies(granted, s)]
            if widened:
                await db.commit()
                raise TokenError(
                    "invalid_scope",
                    f"Nicht zugestimmte Scopes: {', '.join(widened)}",
                )
            effective = [s for s in granted if s in set(requested)] or granted

            user = await db.get(User, user_id)
            if user is None or not user.is_active:
                await db.commit()
                raise TokenError("invalid_grant", "Benutzerkonto nicht mehr aktiv")

            access_token, expires_in = oauth_tokens.mint_access_token(
                user=user,
                organization_id=org_id,
                client_id=client.client_id,
                scopes=effective,
                resource=resource,
            )
            new_refresh = await oauth_tokens.mint_refresh_token(
                db,
                family_id=family_id,
                client_id=client.client_id,
                user_id=user_id,
                organization_id=org_id,
                scopes=effective,
                resource=resource,
            )
            await db.commit()

        return OAuthToken(
            access_token=access_token,
            expires_in=expires_in,
            scope=" ".join(effective),
            refresh_token=new_refresh,
        )

    # ---- Access-Tokens und Widerruf ----

    async def load_access_token(self, token: str) -> AccessToken | None:
        async with get_db_session() as db:
            verified = await oauth_tokens.verify_access_token(db, token)
        if verified is None:
            return None
        return AccessToken(
            token=token,
            client_id=verified.client_id,
            scopes=verified.scopes,
            expires_at=verified.expires_at,
            resource=verified.resource,
            subject=str(verified.user_id),
            # Die Organisation reist in den Claims mit — die Werkzeuge
            # brauchen sie, und ein erneutes Dekodieren des JWT bei jedem
            # Tool-Aufruf wäre Arbeit für dieselbe Antwort.
            claims={"org_id": str(verified.organization_id)},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Ein Token widerrufen (RFC 7009).

        Bei einem Refresh-Token stirbt die ganze Familie: wer eine Verbindung
        trennt, will sie getrennt haben, nicht nur ein Glied der Kette.

        Ein Access-Token ist ein zustandsloses JWT und lässt sich nicht
        einzeln zurückholen. Der Widerruf ist hier deshalb ein no-op, und die
        kurze Laufzeit (``MCP_ACCESS_TOKEN_TTL_MINUTES``) ist der Ersatz. Das
        ist dokumentiert, nicht stillschweigend."""
        if isinstance(token, AccessToken):
            return
        async with get_db_session() as db:
            row = (
                await db.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.token_hash == oauth_tokens.token_hash(token.token)
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return
            await oauth_tokens.revoke_family(db, row.family_id, reason="Widerruf durch den Client")
            await db.commit()


# ── Hilfen ───────────────────────────────────────────────────────────────


def _ts_to_datetime(value: int | None) -> datetime | None:
    """0 heißt in RFC 7591 "läuft nie ab", nicht "1970"."""
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _to_client_information(row: OAuthClient) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=row.client_id,
        # Im Klartext, weil das SDK am Token-Endpunkt selbst vergleicht.
        # In der Datenbank liegt es verschlüsselt.
        client_secret=(
            crypto.decrypt_secret(row.client_secret_encrypted)
            if row.client_secret_encrypted
            else None
        ),
        client_name=row.client_name or None,
        redirect_uris=list(row.redirect_uris or []),
        grant_types=list(row.grant_types or ["authorization_code", "refresh_token"]),
        token_endpoint_auth_method=row.token_endpoint_auth_method,
        scope=row.scope or None,
        client_id_issued_at=int(row.created_at.timestamp()) if row.created_at else None,
        client_secret_expires_at=(
            int(row.client_secret_expires_at.timestamp())
            if row.client_secret_expires_at
            else None
        ),
    )


async def mint_authorization_code(
    db: AsyncSession,
    *,
    request: dict,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    scopes: list[str],
) -> str:
    """Nach der Zustimmung den Autorisierungscode ausstellen.

    Aufgerufen von der Consent-Route, nicht vom SDK — deshalb steht die
    Funktion hier und nicht als Methode am Provider."""
    raw = oauth_tokens.generate_secret()
    db.add(
        OAuthCode(
            code_hash=oauth_tokens.token_hash(raw),
            client_id=request["client_id"],
            user_id=user_id,
            organization_id=organization_id,
            scopes=" ".join(scopes),
            code_challenge=request["code_challenge"],
            redirect_uri=request["redirect_uri"],
            redirect_uri_provided_explicitly=bool(
                request.get("redirect_uri_provided_explicitly", True)
            ),
            resource=request.get("resource"),
            family_id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=settings.mcp_code_ttl_seconds),
        )
    )
    return raw


def authorization_code_expired(code: AuthorizationCode) -> bool:
    return code.expires_at < time.time()
