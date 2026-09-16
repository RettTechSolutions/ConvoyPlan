"""Middleware, die Portalnutzung für die Systemübersicht mitschreibt.

Pro Request werden zwei Dinge festgehalten: Antwortzeit/Statuscode (für die
Last- und Fehlerkurve) und — sofern eine Sitzung mitkommt — die Benutzer-ID
samt Nutzergruppe (für „wie viele Nutzer waren im Portal"). Beides landet nur in
einem Prozess-Dictionary; geschrieben wird erst durch den Metrik-Collector.

Die Sitzung wird über ``deps.credential_from_request()`` geholt, also aus dem
``Authorization``-Header **oder** dem Sitzungs-Cookie. Das ist nicht kosmetisch:
seit die Anmeldung im HttpOnly-Cookie liegt, schickt das Portal keinen Header
mehr, und eine Middleware, die nur den Header liest, zählt jede Portalnutzung
als anonym — die Kurve „aktive Nutzer" stünde dauerhaft auf null.

Die Gruppe ergibt sich aus dem Token: `is_demo` kennzeichnet eine Demo-Sitzung,
`is_superadmin` (immer ohne Organisation ausgestellt) das Admin-Portal, alles
übrige ist regulärer Portalbetrieb. Meldet sich ein Superadmin zusätzlich an
einer Organisation an, trägt dieses Token keine Superadmin-Kennung — die
Arbeit im Kundenportal zählt dann korrekt als reguläre Nutzung.

Der Token wird lokal verifiziert (HS256, kein Datenbankzugriff). Ist er
ungültig oder fehlt er, wird der Request schlicht anonym gezählt — die
Middleware trifft ausdrücklich **keine** Autorisierungsentscheidung, das
bleibt Sache der Endpunkt-Dependencies.
"""

from __future__ import annotations

import time
import uuid

import jwt as _jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.api import deps
from app.config import settings
from app.services import activity

# Endpunkte, die keine Benutzeraktivität darstellen: Healthchecks von Docker,
# statische Uploads und die Systemübersicht selbst (die sich beim Aufruf sonst
# permanent selbst als Last mitzählt und die Kurven verzerrt).
_IGNORED_PREFIXES = (
    "/health",
    "/uploads",
    "/api/admin/system/",
)


def _user_from_token(request: Request) -> tuple[uuid.UUID, uuid.UUID | None, str] | None:
    # Dieselbe Quelle wie die Endpunkt-Dependencies: Header oder Cookie. Der
    # CSRF-Kopf wird hier ausdrücklich nicht verlangt — diese Middleware
    # entscheidet nichts, sie zählt nur, und eine Anfrage, die der Endpunkt
    # gleich mit 403 abweist, hat trotzdem stattgefunden.
    token = deps.credential_from_request(request)
    if not token:
        return None
    try:
        payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        return None
    # Halbauthentifizierte MFA-Tokens sind keine Portalnutzung.
    if payload.get("mfa_pending"):
        return None
    # Ebensowenig ein MCP-Token: es ist mit demselben Schlüssel signiert und
    # trägt ein sub, würde hier also als Portalbesuch durchgehen. Ein Modell,
    # das im Minutentakt Werkzeuge aufruft, stünde dann in der Kurve
    # „aktive Nutzer" — die zählt Menschen im Portal.
    if payload.get("typ") not in (None, "access"):
        return None
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    raw_org = payload.get("org_id")
    try:
        org_id = uuid.UUID(raw_org) if raw_org else None
    except (TypeError, ValueError):
        org_id = None

    if payload.get("is_demo"):
        kind = activity.KIND_DEMO
    elif payload.get("is_superadmin"):
        kind = activity.KIND_ADMIN
    else:
        kind = activity.KIND_MEMBER
    return user_id, org_id, kind


class ActivityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(_IGNORED_PREFIXES):
            return await call_next(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Eine durchgereichte Exception wird vom Server zu einer 500 —
            # in der Fehlerquote muss sie deshalb auch als solche auftauchen.
            activity.record_request(
                status_code=500, duration_ms=(time.perf_counter() - started) * 1000.0
            )
            raise

        activity.record_request(
            status_code=response.status_code,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
        identity = _user_from_token(request)
        if identity is not None:
            activity.touch(*identity)
        return response
