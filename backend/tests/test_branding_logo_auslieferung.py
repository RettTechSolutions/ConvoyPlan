"""Ein hochgeladenes Logo ist unter der URL abrufbar, die die Branding-Antwort nennt.

Gemeldet war „das Branding kommt mit SVG nicht klar": nach dem Speichern zeigte
die Vorschau ein kaputtes Bild. Mit SVG hatte das nichts zu tun — die Antwort
nannte `/uploads/logos/…`, und Caddy reicht nur `/api/*` ans Backend durch. Der
Pfad landete im Frontend und dort im 404, für PNG genauso. Die lokale Vorschau
direkt nach der Dateiauswahl (Object-URL) sah dagegen richtig aus.

Deshalb prüft dieser Test nicht die Route allein, sondern den Weg: die URL aus
der Antwort liegt unter `/api/` und liefert die Datei mit dem richtigen Typ.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import branding
from app.main import app

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.fixture
def logos(tmp_path, monkeypatch):
    monkeypatch.setattr(branding, "LOGOS_DIR", tmp_path)
    return tmp_path


def _db_mit(settings: dict[str, str]):
    zeilen = []
    for key, value in settings.items():
        zeile = MagicMock()
        zeile.key, zeile.value = key, value
        zeilen.append(zeile)
    db = AsyncMock()
    ergebnis = MagicMock()
    ergebnis.scalars.return_value.all.return_value = zeilen
    db.execute = AsyncMock(return_value=ergebnis)
    return db


async def _get(pfad: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(pfad)


@pytest.mark.parametrize(
    ("name", "inhalt", "typ"),
    [("org-1-horizontal.svg", SVG, "image/svg+xml"), ("main.png", PNG, "image/png")],
)
async def test_url_aus_der_antwort_liefert_das_logo(logos, name, inhalt, typ):
    (logos / name).write_bytes(inhalt)
    antwort = await branding.get_branding(db=_db_mit({"branding.logo_main": name}))

    url = antwort.logo_main_url
    # Nur /api/* erreicht hinter Caddy das Backend.
    assert url.startswith("/api/")

    r = await _get(url)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(typ)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content == inhalt


async def test_neuer_upload_bekommt_neue_url(logos):
    """Der Dateiname bleibt beim Ersetzen gleich; ohne Cache-Brecher zeigte der
    Browser das alte Logo weiter."""
    import os

    pfad = logos / "main.svg"
    pfad.write_bytes(SVG)
    os.utime(pfad, (1_000_000, 1_000_000))
    vorher = branding.logo_url("main.svg")
    os.utime(pfad, (2_000_000, 2_000_000))
    assert branding.logo_url("main.svg") != vorher


async def test_svg_direkt_geoeffnet_laeuft_in_der_sandbox(logos):
    (logos / "main.svg").write_bytes(SVG)
    r = await _get("/api/branding/logos/main.svg")
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp
    assert "default-src 'none'" in csp


@pytest.mark.parametrize(
    "name",
    ["..%2Fsecret.png", "%2E%2E%2Ffeedback%2Fx.png", "main.txt", "main.svg.png.html", "nicht-da.png"],
)
async def test_nur_logos_aus_dem_logoverzeichnis(logos, name):
    (logos.parent / "secret.png").write_bytes(PNG)
    (logos / "main.txt").write_bytes(b"x")
    r = await _get(f"/api/branding/logos/{name}")
    assert r.status_code == 404


async def test_uploads_ist_nicht_statisch_gemountet(tmp_path):
    """Unter /uploads liegen auch die Bildschirmfotos aus Meldungen — die gehen
    nur über den Superadmin-Endpunkt hinaus, nie über einen ratbaren Pfad."""
    pfade = {getattr(route, "path", None) for route in app.routes}
    assert "/uploads" not in pfade
