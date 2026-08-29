"""Die Gate-Antwort nennt die Rolle des Links, damit ein Client die
Anmeldemaske passend beschriften kann, bevor das Passwort eingegeben wurde."""
import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from app.api.routes import track as track_module
from app.database import get_db
from app.main import app


class _ConvoyNameResult:
    """Ergebnis der einzigen Abfrage, die der Gate-Pfad ausführt."""

    def __init__(self, name: str):
        self._name = name

    def scalar_one_or_none(self):
        return self._name


class _FakeDB:
    def __init__(self, convoy_name: str):
        self._convoy_name = convoy_name

    async def execute(self, *_args, **_kwargs):
        return _ConvoyNameResult(self._convoy_name)


class _FakeLink:
    def __init__(self, scope: str):
        self.id = uuid.uuid4()
        self.convoy_id = uuid.uuid4()
        self.slug = "AbC123Xy"
        self.password_hash = "$2b$12$notarealhash"
        self.scope = scope
        self.revoked = False


def _install(monkeypatch, scope: str, convoy_name: str = "Marschverband Nord"):
    app.dependency_overrides[get_db] = lambda: _FakeDB(convoy_name)

    async def _load_link(_slug, _db):
        return _FakeLink(scope)

    monkeypatch.setattr(track_module, "_load_link", _load_link)


async def _get_gate() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/track/AbC123Xy")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["track", "driver"])
async def test_gate_nennt_den_scope(monkeypatch, scope):
    _install(monkeypatch, scope)
    try:
        body = await _get_gate()
    finally:
        app.dependency_overrides.clear()

    assert body["requires_password"] is True
    assert body["convoy_name"] == "Marschverband Nord"
    assert body["scope"] == scope


@pytest.mark.asyncio
async def test_gate_gibt_kein_konvoi_detail_preis(monkeypatch):
    """Vor der Passworteingabe darf nur Name und Rolle sichtbar sein."""
    _install(monkeypatch, "driver")
    try:
        body = await _get_gate()
    finally:
        app.dependency_overrides.clear()

    assert set(body) == {"requires_password", "convoy_name", "scope"}
