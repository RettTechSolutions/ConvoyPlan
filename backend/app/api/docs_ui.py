"""Die interaktive API-Dokumentation und ihr Türsteher.

``/docs``, ``/redoc`` und ``/openapi.json`` sind in Produktion abgeschaltet.
Wer sie braucht, setzt ``DOCS_API_KEY`` — dann werden sie ausgeliefert, aber
nur gegen diesen Schlüssel.

**Warum kein ``?key=…`` mehr.** Der Schlüssel ließ sich früher als
Query-Parameter mitgeben. Das ist bequem und der schwächste denkbare
Transportweg: Query-Strings landen im Access-Log des Reverse Proxy, in der
Browser-History, in Lesezeichen und — bei jeder externen Ressource, die eine
der Docs-Seiten nachlädt — potenziell im ``Referer``. Der Vergleich selbst war
nie das Problem, der Weg dorthin schon. Akzeptiert werden deshalb nur noch:

* der Header ``X-API-Key`` (programmatischer Zugriff), und
* das HttpOnly-Cookie, das ``POST /docs/session`` nach erfolgreicher Eingabe
  setzt (Browser-Einstieg über das Formular auf ``/docs/login``).

Das Cookie trägt nicht den Schlüssel, sondern ein kurzlebiges, mit
``JWT_SECRET`` signiertes Zeugnis — der Schlüssel selbst verlässt den Server
nie wieder.

``POST /docs/session`` ist wie der Login ratenbegrenzt (zehn Fehlversuche je
fünf Minuten und IP). Ohne das wäre das Formular ein offener Brute-Force-Pfad
auf einen Wert, den niemand rotiert.
"""

from datetime import datetime, timedelta, timezone
from html import escape
import secrets

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
import jwt as _jwt
from jwt.exceptions import InvalidTokenError

from app.api import cookies
from app.config import settings
from app.services import rate_limit

COOKIE_NAME = "convoyplan_docs_key"
COOKIE_TTL = timedelta(hours=8)
OPENAPI_URL = "/openapi.json"
LOGIN_URL = "/docs/login"
SESSION_URL = "/docs/session"

# Dieselben Parameter wie POST /api/auth/login — es ist derselbe Angriff auf
# ein anderes Geheimnis.
_RATE_LIMIT_BUCKET = "docs-session"
_RATE_LIMIT_MAX_ATTEMPTS = 10
_RATE_LIMIT_WINDOW_SECONDS = 300

_DEV_ENVS = {"dev", "development", "local", "test", "testing"}


def docs_enabled() -> bool:
    """Ob die Docs-Routen überhaupt montiert werden.

    Ein gesetzter ``DOCS_API_KEY`` impliziert sie (sonst wäre der Schlüssel
    ohne Wirkung), ``ENABLE_DOCS`` schaltet sie offen frei, und in der
    Entwicklung sind sie immer da.
    """
    return (
        settings.enable_docs
        or bool(settings.docs_api_key)
        or settings.app_env.lower() in _DEV_ENVS
    )


def _issue_cookie() -> str:
    """Ein kurzlebiges, signiertes Zeugnis für den Browser. Es markiert ihn als
    berechtigt — der API-Key selbst wird nie clientseitig abgelegt."""
    expire = datetime.now(timezone.utc) + COOKIE_TTL
    return _jwt.encode(
        {"docs": True, "exp": expire}, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


def _cookie_valid(token: str) -> bool:
    try:
        payload = _jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except InvalidTokenError:
        return False
    return bool(payload.get("docs"))


def _set_cookie(response: Response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _issue_cookie(),
        max_age=int(COOKIE_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        # Nicht aus request.url.scheme: hinter dem Reverse Proxy spricht das
        # Backend unverschlüsselt und uvicorn läuft ohne --proxy-headers, das
        # Schema wäre in Produktion also immer "http" und das Cookie nie
        # Secure. Dieselbe Ableitung wie beim Sitzungs-Cookie.
        secure=cookies.cookie_secure(),
    )


def _authorized(request: Request) -> bool:
    """Darf diese Anfrage die Docs sehen?

    Ohne konfigurierten Schlüssel sind die Docs ungeschützt (Dev-Bequemlich-
    keit). Sonst zählt der Header oder das Cookie — und sonst nichts. Ein
    ``?key=…`` wird bewusst nicht mehr gelesen.
    """
    expected = settings.docs_api_key
    if not expected:
        return True
    raw = request.headers.get("x-api-key")
    if raw and secrets.compare_digest(raw, expected):
        return True
    cookie = request.cookies.get(COOKIE_NAME)
    return bool(cookie and _cookie_valid(cookie))


def _login_page(*, error: str | None = None) -> str:
    hint = (
        f'<p class="error">{escape(error)}</p>'
        if error
        else '<p class="hint">Programmatischer Zugriff: Header '
        '<code>X-API-Key</code>.</p>'
    )
    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex, nofollow">
<title>ConvoyPlan API-Dokumentation — Anmeldung</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         display: flex; min-height: 100vh; margin: 0; align-items: center;
         justify-content: center; background: Canvas; color: CanvasText; }}
  main {{ width: min(24rem, 90vw); }}
  h1 {{ font-size: 1.25rem; margin: 0 0 .25rem; }}
  p {{ margin: 0 0 1rem; font-size: .9rem; line-height: 1.5; }}
  .error {{ color: #b3261e; font-weight: 600; }}
  label {{ display: block; font-size: .85rem; margin-bottom: .35rem; }}
  input, button {{ width: 100%; box-sizing: border-box; font: inherit;
                   padding: .6rem .7rem; border-radius: .4rem;
                   border: 1px solid #8884; }}
  button {{ margin-top: .75rem; cursor: pointer; border: 0;
            background: #1f6feb; color: #fff; font-weight: 600; }}
  code {{ font-size: .85em; }}
</style>
</head>
<body>
<main>
  <h1>ConvoyPlan API-Dokumentation</h1>
  {hint}
  <form method="post" action="{SESSION_URL}" autocomplete="off">
    <label for="key">API-Key</label>
    <input id="key" name="key" type="password" required autofocus
           autocomplete="current-password" spellcheck="false">
    <button type="submit">Anmelden</button>
  </form>
</main>
</body>
</html>"""


def _unauthorized_html() -> HTMLResponse:
    """401 *mit* dem Formular im Rumpf: Der Statuscode bleibt ehrlich (kein
    stiller 200 auf eine unberechtigte Anfrage), und wer im Browser landet,
    sieht trotzdem sofort, wie es weitergeht."""
    return HTMLResponse(
        _login_page(error="Anmeldung erforderlich."),
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


def register(app: FastAPI) -> None:
    """Montiert die Docs-Routen samt Türsteher auf ``app``."""

    @app.get(LOGIN_URL, include_in_schema=False)
    async def _docs_login(request: Request) -> Response:
        if not settings.docs_api_key:
            # Ungeschützt — ein Formular wäre hier eine Lüge.
            return RedirectResponse("/docs", status_code=status.HTTP_303_SEE_OTHER)
        if _authorized(request):
            return RedirectResponse("/docs", status_code=status.HTTP_303_SEE_OTHER)
        return HTMLResponse(_login_page())

    @app.post(
        SESSION_URL,
        include_in_schema=False,
        dependencies=[
            Depends(
                rate_limit.rate_limit(
                    _RATE_LIMIT_BUCKET,
                    max_attempts=_RATE_LIMIT_MAX_ATTEMPTS,
                    window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
                )
            )
        ],
    )
    async def _docs_session(request: Request, key: str = Form(...)) -> Response:
        expected = settings.docs_api_key
        if not expected:
            raise HTTPException(status_code=404)

        if not secrets.compare_digest(key, expected):
            rate_limit.register_failure(request, _RATE_LIMIT_BUCKET)
            return HTMLResponse(
                _login_page(error="Falscher API-Key."),
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        resp = RedirectResponse("/docs", status_code=status.HTTP_303_SEE_OTHER)
        _set_cookie(resp)
        return resp

    @app.get(OPENAPI_URL, include_in_schema=False)
    async def _openapi(request: Request) -> Response:
        if not _authorized(request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Docs-Zugriff erfordert einen gültigen API-Key: Header "
                    f"X-API-Key, oder einmalig über {LOGIN_URL} anmelden."
                ),
            )
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    async def _docs(request: Request) -> Response:
        if not _authorized(request):
            return _unauthorized_html()
        return get_swagger_ui_html(
            openapi_url=OPENAPI_URL, title="ConvoyPlan API — Swagger UI"
        )

    @app.get("/redoc", include_in_schema=False)
    async def _redoc(request: Request) -> Response:
        if not _authorized(request):
            return _unauthorized_html()
        return get_redoc_html(openapi_url=OPENAPI_URL, title="ConvoyPlan API — ReDoc")
