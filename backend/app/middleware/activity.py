"""Middleware, die Portalnutzung für die Systemübersicht mitschreibt.

Pro Request werden zwei Dinge festgehalten: Antwortzeit/Statuscode (für die
Last- und Fehlerkurve) und — sofern ein Bearer-Token mitkommt — die Benutzer-ID
(für „wie viele Nutzer waren im Portal"). Beides landet nur in einem
Prozess-Dictionary; geschrieben wird erst durch den Metrik-Collector.

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


def _user_from_token(request: Request) -> tuple[uuid.UUID, uuid.UUID | None] | None:
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        return None
    # Halbauthentifizierte MFA-Tokens sind keine Portalnutzung.
    if payload.get("mfa_pending"):
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
    return user_id, org_id


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
            activity.touch(identity[0], identity[1])
        return response
