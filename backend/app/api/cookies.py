"""Die Sitzung im HttpOnly-Cookie statt im ``localStorage``.

Vorher lag das Zugriffstoken im ``localStorage`` des Browsers und wurde von
``client.ts`` in jeden ``Authorization``-Header geschrieben. Das ist bequem
und hat einen Preis: **jedes** Stück JavaScript auf der Seite kann es lesen.
Ein einziger XSS — in einer Abhängigkeit, in einem eingebetteten Namen, in
einer Vorschau — genügt, und das Token verlässt den Rechner. Es ist sieben
Tage gültig (``JWT_EXPIRE_MINUTES``) und lässt sich von überall einlösen;
gestohlen ist es damit eine Woche lang eine vollwertige Anmeldung.

Ein ``HttpOnly``-Cookie nimmt dem Angreifer genau das: Skripte kommen nicht
mehr an den Wert heran. Es nimmt ihm **nicht** die Möglichkeit, im Namen des
angemeldeten Benutzers Anfragen zu stellen, solange sein Code auf der Seite
läuft — das ist der Rest, der bleibt, und der ehrlich benannt gehört. Der
Unterschied ist trotzdem erheblich: ein Angriff endet mit der Sitzung im
Browser, statt eine Woche lang von einem fremden Rechner aus weiterzulaufen.

**Eine Anmeldung je Organisation.** ConvoyPlan meldet pro Organisation
getrennt an (E-Mail, Passwort *und* Slug), und jemand kann in zwei Tabs in
zwei Organisationen arbeiten. Ein einzelnes Sitzungs-Cookie würde das
kaputtmachen. Deshalb heißt das Cookie je Organisation
``cp_session__<slug>``; das Frontend sagt mit ``X-Org-Slug``, welche
Organisation gerade gemeint ist. Der Slug ist kein Geheimnis — er steht in
der URL —, er wählt nur aus, und was er auswählt, ist ein signiertes Token,
dessen Organisation erneut geprüft wird.

**CSRF.** Ein Cookie schickt der Browser von sich aus mit, auch wenn eine
fremde Seite die Anfrage auslöst — das Problem, das es mit einem
``Authorization``-Header nicht gab. Dagegen zwei Dinge:

1. ``SameSite=Lax``: bei Unterseiten-Anfragen von fremden Ursprüngen bleibt
   das Cookie zu Hause. ``Strict`` wäre strenger, würde aber jeden Link aus
   einer E-Mail in eine Anmeldemaske führen — für ein Werkzeug, in dem
   Konvoi-Links geteilt werden, der falsche Tausch.
2. Ein fester Kopf ``X-Requested-With: ConvoyPlan`` bei allen ändernden
   Methoden. Einen eigenen Header kann fremdes JavaScript nur nach einem
   CORS-Preflight setzen, und den beantwortet diese Instanz nur für den
   eigenen Ursprung (siehe ``app/main.py``). Ein Formular-POST von einer
   fremden Seite kann ihn gar nicht setzen.

Der ``Authorization: Bearer``-Weg bleibt daneben bestehen — für API-Clients,
Skripte und die Tests. Er ist nicht das Problem gewesen; das Problem war,
das Token dafür im Browser zu lagern.
"""
from fastapi import Request, Response

from app.config import settings

SESSION_COOKIE = "cp_session"
"""Die organisationslose Sitzung (Superadmin)."""

ORG_SLUG_HEADER = "X-Org-Slug"
"""Wählt aus, welche Organisationssitzung gemeint ist."""

CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "ConvoyPlan"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
"""Methoden, die nichts verändern und deshalb keinen CSRF-Schutz brauchen.

Das gilt nur, solange sie tatsächlich nichts verändern — ein ``GET``, das
etwas schreibt, wäre hier die Lücke und nicht diese Liste."""


def cookie_name(org_slug: str | None) -> str:
    """Der Cookie-Name für eine Organisation, oder der globale."""
    if not org_slug:
        return SESSION_COOKIE
    return f"{SESSION_COOKIE}__{org_slug}"


def cookie_secure() -> bool:
    """Ob das Cookie nur über HTTPS gesendet werden darf.

    Abgeleitet aus ``APP_BASE_URL`` und **nicht** aus ``request.url.scheme``:
    hinter dem Reverse Proxy spricht das Backend unverschlüsselt, uvicorn
    läuft ohne ``--proxy-headers``, und das Schema der Anfrage wäre deshalb
    in Produktion immer ``http``. Ein Sitzungs-Cookie, das genau dort nie
    ``Secure`` trägt, wäre der Punkt, an dem diese ganze Umstellung wieder
    zusammenfiele."""
    return settings.app_base_url.strip().lower().startswith("https://")


def set_session_cookie(
    response: Response, token: str, org_slug: str | None = None
) -> None:
    """Die Sitzung setzen. ``org_slug`` leer = die globale Sitzung."""
    response.set_cookie(
        cookie_name(org_slug),
        token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )


def clear_session_cookie(response: Response, org_slug: str | None = None) -> None:
    """Die Sitzung löschen.

    Die Attribute müssen denen beim Setzen entsprechen, sonst löscht der
    Browser ein anderes Cookie als das gemeinte — also gar keines."""
    response.delete_cookie(
        cookie_name(org_slug),
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )


def session_slugs(request: Request) -> list[str]:
    """Die Slugs aller Organisationssitzungen, die der Browser mitschickt."""
    praefix = f"{SESSION_COOKIE}__"
    return [
        name[len(praefix):]
        for name in request.cookies
        if name.startswith(praefix) and len(name) > len(praefix)
    ]


def token_from_cookie(request: Request) -> str | None:
    """Das Sitzungstoken aus dem passenden Cookie, falls vorhanden.

    Die Auswahl trifft der ``X-Org-Slug``-Header; ohne ihn gilt die globale
    Sitzung. Es wird bewusst **nicht** geraten: schickt der Browser mehrere
    Organisationssitzungen und nennt niemand eine, ist die Anfrage
    mehrdeutig — und eine geratene Anmeldung ist schlimmer als gar keine."""
    slug = request.headers.get(ORG_SLUG_HEADER)
    return request.cookies.get(cookie_name(slug))
