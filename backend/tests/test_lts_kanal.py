"""Der LTS-Update-Kanal — Linie, Ziel-Release und Freischaltung per Lizenz.

Eine LTS-Linie ist ein Branch ``lts/<JAHR>.<MASTER>``; der Kanal folgt dem
neuesten Release der höchsten Linie. Er gehört zum Wartungsvertrag und ist nur
wählbar, solange der Lizenzschlüssel ``lts_until`` trägt und das Datum nicht
überschritten ist.
"""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, require_superadmin
from app.main import app
import app.services.license as lic_mod
from app.services.update_check import lts_line, newest_release_on_line
from tests.test_license import _make_key, _sign_payload, _valid_payload

MORGEN = (date.today() + timedelta(days=1)).isoformat()
GESTERN = (date.today() - timedelta(days=1)).isoformat()


# ── Linie und Ziel ────────────────────────────────────────────────────────────

def test_hoechste_linie_zaehlt_numerisch():
    refs = [
        "refs/heads/lts/2025.9",
        "refs/heads/lts/2026.10",
        "refs/heads/lts/2026.7",
        "refs/heads/lts/kaputt",
        "refs/heads/main",
    ]
    assert lts_line(refs) == "2026.10"


def test_ohne_lts_branch_keine_linie():
    assert lts_line(["refs/heads/main"]) is None
    assert lts_line([]) is None


def test_neuestes_release_der_linie():
    releases = [
        {"tag_name": "v2026.11.0"},
        {"tag_name": "v2026.10.9"},
        {"tag_name": "v2026.10.10"},
        {"tag_name": "v2026.10.11-beta.1", "prerelease": True},
        {"tag_name": "v2026.10.12", "draft": True},
        {"tag_name": "v2026.100.3"},
        {"tag_name": "v2026.1.0"},
    ]
    assert newest_release_on_line(releases, "2026.10") == "v2026.10.10"


def test_linie_ohne_release():
    assert newest_release_on_line([{"tag_name": "v2026.11.0"}], "2026.10") is None


# ── Lizenz ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("valid", "lts_until", "erwartet"),
    [
        (True, MORGEN, True),
        (True, date.today().isoformat(), True),   # der letzte Tag zählt noch
        (True, GESTERN, False),
        (True, "", False),
        (True, "irgendwann", False),
        (False, MORGEN, False),                    # ungültige Lizenz schaltet nichts frei
    ],
)
def test_lts_freigabe(valid, lts_until, erwartet):
    assert lic_mod.LicenseInfo(valid=valid, lts_until=lts_until).lts_active is erwartet


def test_lizenzschluessel_traegt_lts_until(monkeypatch):
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)
    payload = {**_valid_payload(), "lts_until": MORGEN}
    info = lic_mod.validate_license(_sign_payload(payload, priv))
    assert info.valid
    assert info.lts_until == MORGEN
    assert info.lts_active


def test_alter_lizenzschluessel_ohne_lts(monkeypatch):
    priv, pub_b64 = _make_key()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)
    info = lic_mod.validate_license(_sign_payload(_valid_payload(), priv))
    assert info.valid
    assert not info.lts_active


# ── Admin-Endpunkte ───────────────────────────────────────────────────────────

@pytest.fixture
def admin_client(monkeypatch):
    superadmin = MagicMock(id="00000000-0000-0000-0000-000000000001", email="sa@test.invalid")
    app.dependency_overrides[require_superadmin] = lambda: superadmin
    db = AsyncMock()
    leer = MagicMock()
    leer.scalar_one_or_none.return_value = None
    db.execute.return_value = leer

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    geschrieben: list[str] = []
    monkeypatch.setattr("app.api.routes.admin._write_channel_file", geschrieben.append)
    monkeypatch.setattr("app.api.routes.admin.audit.record", AsyncMock())
    yield geschrieben
    app.dependency_overrides.clear()


def _lizenz(lts_until: str):
    return AsyncMock(return_value=lic_mod.LicenseInfo(valid=True, lts_until=lts_until))


async def test_lts_ohne_freigabe_abgelehnt(admin_client, monkeypatch):
    monkeypatch.setattr("app.api.routes.admin._current_license", _lizenz(""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.put("/api/admin/settings/update-channel", json={"channel": "lts"})
    assert r.status_code == 403
    assert admin_client == []   # der Updater hat nichts davon erfahren


async def test_lts_mit_freigabe_gesetzt(admin_client, monkeypatch):
    monkeypatch.setattr("app.api.routes.admin._current_license", _lizenz(MORGEN))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.put("/api/admin/settings/update-channel", json={"channel": "lts"})
    assert r.status_code == 204
    assert admin_client == ["lts"]


async def test_kanal_zeigt_lts_freigabe(admin_client, monkeypatch):
    monkeypatch.setattr("app.api.routes.admin._current_license", _lizenz(MORGEN))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/admin/settings/update-channel")
    assert r.status_code == 200
    assert r.json()["lts_available"] is True
    assert r.json()["lts_until"] == MORGEN


async def test_update_status_folgt_der_lts_linie(admin_client):
    """Das Ziel ist das neueste Release der höchsten Linie — nicht /releases/latest."""
    abgefragt: list[str] = []

    async def _get(url, **kwargs):
        abgefragt.append(url)
        resp = MagicMock(status_code=200, is_success=True)
        if "matching-refs/heads/lts" in url:
            resp.json.return_value = [{"ref": "refs/heads/lts/2026.7"}]
        elif "/releases?" in url:
            resp.json.return_value = [
                {"tag_name": "v2026.8.0"},
                {"tag_name": "v2026.7.4"},
                {"tag_name": "v2026.7.3"},
            ]
        elif "/commits/" in url:
            resp.json.return_value = {"sha": "eee5555abcdef"}
        elif "/compare/" in url:
            resp.json.return_value = {"status": "behind"}
        return resp

    client_mock = MagicMock()
    client_mock.get = _get
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client_mock)
    ctx.__aexit__ = AsyncMock(return_value=False)

    status = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-09-30T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status)), \
         patch("os.makedirs"), \
         patch("app.services.update_check.settings.update_channel", "lts"), \
         patch("app.services.update_check.httpx.AsyncClient", return_value=ctx):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["channel"] == "lts"
    assert data["latest_release"] == "v2026.7.4"
    assert data["remote_sha"] == "eee5555"
    assert data["update_available"] is True
    assert not any("releases/latest" in url for url in abgefragt)
