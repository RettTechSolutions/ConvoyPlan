"""Die Abruf-Adresse im Org-Admin muss mit https:// beginnen.

Sie wird aus ``request.url_for`` gebaut, also aus dem Schema der Anfrage.
Hinter Caddy spricht das Backend unverschlüsselt; https kommt nur über
``X-Forwarded-Proto`` an, und das wertet uvicorn nur aus, wenn der Proxy in
``--forwarded-allow-ips`` steht. Stand dort der Standard 127.0.0.1, zeigte die
Verwaltung ``http://…`` — der EventTracker lief dann in die Umleitung auf
https, Node fetch warf dabei den Authorization-Kopf weg (Origin-Wechsel), und
der Abruf endete in 404.

Die Tests setzen uvicorns ``ProxyHeadersMiddleware`` so vor die App, wie der
Server sie mit dem Wert aus der Compose-Datei startet, und fragen aus dem
Docker-Netz an statt von localhost.
"""
import re
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    h,
    reset_db_engine,
)

_REPO = Path(__file__).resolve().parents[2]
# Eine Adresse, wie Caddy sie im Compose-Netz hat — nicht 127.0.0.1.
_CADDY = ("172.18.0.7", 41234)
_HINTER_CADDY = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"}
_SEITE = {
    "title": "Weihnachtskonvois 2026",
    "delay_minutes": 120,
    "convoys": [],
}


def _compose_wert(name: str) -> str:
    """Standardwert einer Variable im backend-Dienst der Compose-Datei."""
    compose = (_REPO / "docker-compose.yml").read_text()
    backend = compose.split("\n  backend:\n", 1)[1].split("\n  retention:\n", 1)[0]
    treffer = re.search(rf"^\s+{name}: \$\{{{name}:-(.*?)\}}\s*$", backend, re.M)
    assert treffer, f"{name} fehlt im backend-Dienst der docker-compose.yml"
    return treffer.group(1)


def _client(trusted_hosts: str) -> AsyncClient:
    from app.main import app

    hinter_proxy = ProxyHeadersMiddleware(app, trusted_hosts=trusted_hosts)
    return AsyncClient(
        transport=ASGITransport(app=hinter_proxy, client=_CADDY),
        base_url="http://web.convoyplan.test",
    )


async def test_abruf_adresse_beginnt_mit_https(aktion):
    async with _client(_compose_wert("FORWARDED_ALLOW_IPS")) as c:
        r = await c.post(
            "/api/org/aktionsseiten", json=_SEITE, headers={**h(aktion.admin), **_HINTER_CADDY}
        )
        assert r.status_code == 201, r.text
        neu = r.json()
        assert neu["endpoint"] == f"https://web.convoyplan.test/api/public/aktion/{neu['slug']}"

        liste = await c.get("/api/org/aktionsseiten", headers={**h(aktion.admin), **_HINTER_CADDY})
        assert liste.status_code == 200, liste.text
        assert [s["endpoint"] for s in liste.json()] == [neu["endpoint"]]


async def test_ohne_vertrauen_in_den_proxy_bliebe_es_bei_http(aktion):
    """Der Fehler, den die Compose-Einstellung behebt: uvicorns Standard
    127.0.0.1 trifft Caddy aus dem Docker-Netz nie."""
    async with _client("127.0.0.1") as c:
        r = await c.post(
            "/api/org/aktionsseiten", json=_SEITE, headers={**h(aktion.admin), **_HINTER_CADDY}
        )
    assert r.status_code == 201, r.text
    assert r.json()["endpoint"].startswith("http://")


def test_der_entrypoint_reicht_forwarded_allow_ips_an_uvicorn():
    entrypoint = (_REPO / "backend" / "docker-entrypoint.sh").read_text()
    assert '--forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"' in entrypoint


def test_stern_nur_solange_das_backend_keinen_port_veroeffentlicht():
    """"*" ist nur vertretbar, weil allein Caddy das Backend erreicht. Bekommt
    der Dienst einen Port, gehört hier die Adresse des Proxys hin."""
    compose = (_REPO / "docker-compose.yml").read_text()
    backend = compose.split("\n  backend:\n", 1)[1].split("\n  retention:\n", 1)[0]
    if _compose_wert("FORWARDED_ALLOW_IPS") == "*":
        assert not re.search(r"^    ports:", backend, re.M)
