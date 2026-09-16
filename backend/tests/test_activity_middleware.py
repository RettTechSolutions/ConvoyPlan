"""Wer als Portalnutzung zählt — und wer nicht.

Diese Datei ist das Ergebnis einer Nachlese. Die Umstellung der Anmeldung auf
das HttpOnly-Cookie hat **zwei** Stellen übersehen, die sich ihr Token selbst
aus dem ``Authorization``-Header zogen: ``require_system_read`` (in #475
behoben) und diese Middleware. Beide hörten still auf zu funktionieren, weil
das Portal seither keinen Header mehr schickt — hier mit dem Ergebnis, dass
jede Portalnutzung als anonym gezählt wurde und die Kurve „aktive Nutzer"
dauerhaft auf null stand.

Der letzte Test unten prüft deshalb nicht diesen einen Fall, sondern die
Klasse: dass niemand im Backend mehr selbst am Header hängt.
"""
import pathlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt as _jwt

from app.config import settings
from app.middleware.activity import _user_from_token
from app.services import activity
from tests.fake_request import fake_request


def _token(typ: str = "access", **extra) -> str:
    payload = {
        "sub": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "typ": typ,
        "is_superadmin": False,
        "org_id": str(uuid.uuid4()),
        "tv": 0,
        **extra,
    }
    return _jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ── Beide Wege zählen ────────────────────────────────────────────────────


def test_bearer_header_wird_gezaehlt():
    """Der Weg von API-Clients und Skripten — unverändert."""
    req = fake_request(headers={"Authorization": f"Bearer {_token()}"})
    assert _user_from_token(req) is not None


def test_sitzungs_cookie_wird_gezaehlt():
    """Der Weg des Portals, seit die Anmeldung im HttpOnly-Cookie liegt.

    Ohne das zählte jede Portalnutzung als anonym."""
    req = fake_request(
        headers={"X-Org-Slug": "orga"}, cookies={"cp_session__orga": _token()}
    )
    identity = _user_from_token(req)
    assert identity is not None
    assert identity[2] == activity.KIND_MEMBER


def test_globale_sitzung_zaehlt_als_admin():
    req = fake_request(cookies={"cp_session": _token(is_superadmin=True, org_id=None)})
    identity = _user_from_token(req)
    assert identity is not None
    assert identity[2] == activity.KIND_ADMIN


def test_demo_sitzung_zaehlt_als_demo():
    req = fake_request(
        headers={"X-Org-Slug": "demo-x"}, cookies={"cp_session__demo-x": _token(is_demo=True)}
    )
    identity = _user_from_token(req)
    assert identity is not None
    assert identity[2] == activity.KIND_DEMO


def test_ohne_alles_ist_anonym():
    assert _user_from_token(fake_request()) is None


# ── Was nicht zählt ──────────────────────────────────────────────────────


def test_mcp_token_ist_keine_portalnutzung():
    """MCP-Tokens sind mit demselben Schlüssel signiert und tragen ein `sub`.

    Ohne die Typprüfung stünde ein Modell, das im Minutentakt Werkzeuge
    aufruft, in der Kurve „aktive Nutzer" — die zählt Menschen im Portal."""
    req = fake_request(headers={"Authorization": f"Bearer {_token(typ='mcp')}"})
    assert _user_from_token(req) is None


def test_stream_ticket_ist_keine_portalnutzung():
    req = fake_request(headers={"Authorization": f"Bearer {_token(typ='stream')}"})
    assert _user_from_token(req) is None


def test_halb_authentifiziertes_mfa_token_zaehlt_nicht():
    """Nach dem Passwort, vor dem zweiten Faktor — noch niemand im Portal."""
    req = fake_request(
        headers={"Authorization": f"Bearer {_token(mfa_pending=True)}"}
    )
    assert _user_from_token(req) is None


def test_kaputtes_token_ist_anonym_statt_fehler():
    """Die Middleware darf an einem Token nicht scheitern — sie zählt nur."""
    req = fake_request(headers={"Authorization": "Bearer nicht.wirklich.ein.jwt"})
    assert _user_from_token(req) is None


def test_fremd_signiertes_token_zaehlt_nicht():
    fremd = _jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "access",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "ein-ganz-anderes-geheimnis",
        algorithm="HS256",
    )
    req = fake_request(headers={"Authorization": f"Bearer {fremd}"})
    assert _user_from_token(req) is None


# ── Die Lücke als Klasse ─────────────────────────────────────────────────


def test_niemand_liest_den_authorization_kopf_mehr_selbst():
    """Der eigentliche Punkt dieser Datei.

    Zweimal hat dieselbe Lücke zugeschlagen: eine Stelle zog sich das Token
    selbst aus dem ``Authorization``-Header und hörte still auf zu
    funktionieren, als die Anmeldung ins Cookie wanderte. Ein Test für den
    Einzelfall hätte den zweiten nicht verhindert.

    Erlaubt bleibt der Zugriff in ``deps.py`` selbst — dort gehört er hin —
    und das *Setzen* eines Headers für ausgehende Anfragen (GitHub-API):
    ``headers["Authorization"] = …`` ist eine Zuweisung, kein Leser, und
    wird deshalb ausdrücklich nicht getroffen."""
    wurzel = pathlib.Path(__file__).resolve().parents[1] / "app"
    muster = re.compile(
        r"""headers\s*\.get\(\s*["']authorization["']"""      # .get("authorization")
        r"""|headers\s*\[\s*["']authorization["']\s*\](?!\s*=[^=])""",  # […] ohne Zuweisung
        re.I,
    )

    treffer: list[str] = []
    for datei in wurzel.rglob("*.py"):
        if datei.name == "deps.py" and datei.parent.name == "api":
            continue
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            if muster.search(zeile):
                treffer.append(f"{datei.relative_to(wurzel)}:{nr}: {zeile.strip()}")

    assert not treffer, (
        "Diese Stellen holen sich die Anmeldung selbst aus dem Header und "
        "übersehen damit das Sitzungs-Cookie. Stattdessen "
        "deps.credential_from_request() (nur lesen) oder get_token_data() "
        "(autorisieren) verwenden:\n  " + "\n  ".join(treffer)
    )
