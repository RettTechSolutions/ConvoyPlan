"""Die Instanz kündigt den Ablauf ihres Lizenzschlüssels an.

Die Zusagen:

- 30 und 7 Tage vor dem Ablauf und beim Ablauf geht je **eine** Mail an die
  Superadmins — nicht jeden Durchgang wieder, auch nicht nach einem Neustart.
- Wer erst in der 7-Tage-Stufe startet, bekommt die verpasste 30-Tage-Mail
  nicht nachgereicht.
- Ein neuer Schlüssel fängt von vorn an.
- Ohne Zustellung (kein SMTP) gilt nichts als gemeldet.
- Ein Schlüssel für eine andere Instanz oder mit falscher Signatur löst nichts aus.
- ``/api/license/status`` sagt dem Portal, ob es warnen soll.

Zuerst die Entscheidung ohne Datenbank, danach der Durchgang mit Datenbank
und der Weg durch die App.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.settings import SystemSetting
from app.models.user import User
from app.services import lizenz_ablauf
from app.services.license import LicenseInfo

HEUTE = date(2026, 9, 30)


def _info(ablauf: date, **felder) -> LicenseInfo:
    info = LicenseInfo(valid=ablauf >= datetime.now(timezone.utc).date(), expires=ablauf.isoformat())
    for k, v in felder.items():
        setattr(info, k, v)
    return info


# ── Stufen ───────────────────────────────────────────────────────────────


def test_stufen_nach_restlaufzeit():
    s = lizenz_ablauf.stufe
    assert s(HEUTE + timedelta(days=31), HEUTE) is None
    assert s(HEUTE + timedelta(days=30), HEUTE) == "30"
    assert s(HEUTE + timedelta(days=8), HEUTE) == "30"
    assert s(HEUTE + timedelta(days=7), HEUTE) == "7"
    # Der letzte gültige Tag ist noch kein Ablauf.
    assert s(HEUTE, HEUTE) == "7"
    assert s(HEUTE - timedelta(days=1), HEUTE) == "abgelaufen"


def test_lange_abgelaufen_meldet_nichts_mehr():
    assert lizenz_ablauf.stufe(HEUTE - timedelta(days=30), HEUTE) == "abgelaufen"
    assert lizenz_ablauf.stufe(HEUTE - timedelta(days=31), HEUTE) is None


def test_jede_stufe_einmal():
    ablauf = HEUTE + timedelta(days=20)
    f = lizenz_ablauf.faellige_stufe
    assert f(None, ablauf, HEUTE) == "30"
    assert f(f"{ablauf}:30", ablauf, HEUTE) is None
    assert f(f"{ablauf}:30", ablauf, ablauf - timedelta(days=5)) == "7"
    assert f(f"{ablauf}:7", ablauf, ablauf - timedelta(days=5)) is None
    assert f(f"{ablauf}:7", ablauf, ablauf + timedelta(days=1)) == "abgelaufen"
    assert f(f"{ablauf}:abgelaufen", ablauf, ablauf + timedelta(days=2)) is None


def test_verpasste_stufe_wird_nicht_nachgereicht():
    ablauf = HEUTE + timedelta(days=3)
    assert lizenz_ablauf.faellige_stufe(None, ablauf, HEUTE) == "7"
    # Nach der 7er-Mail kommt keine 30er mehr hinterher.
    assert lizenz_ablauf.faellige_stufe(f"{ablauf}:7", ablauf, HEUTE) is None


def test_neuer_schluessel_faengt_von_vorn_an():
    alt = HEUTE + timedelta(days=2)
    neu = HEUTE + timedelta(days=25)
    assert lizenz_ablauf.faellige_stufe(f"{alt}:7", neu, HEUTE) == "30"


def test_fremder_oder_kaputter_schluessel_hat_kein_ablaufdatum():
    fremd = LicenseInfo(valid=False, expires="2026-10-10", error="License is not valid for this installation")
    assert lizenz_ablauf.ablaufdatum(fremd) is None
    assert lizenz_ablauf.ablaufdatum(LicenseInfo(valid=False, error="Invalid license signature")) is None


def test_abgelaufener_schluessel_behaelt_sein_datum():
    info = LicenseInfo(valid=False, expires="2026-09-01", error="License expired on 2026-09-01")
    assert lizenz_ablauf.ablaufdatum(info) == date(2026, 9, 1)
    assert lizenz_ablauf.tage_bis_ablauf(info, HEUTE) == -29


def test_altschluessel_mit_zeitstempel():
    ts = int(datetime(2026, 10, 10, 12, tzinfo=timezone.utc).timestamp())
    info = LicenseInfo(valid=True, expires=str(ts))
    assert lizenz_ablauf.tage_bis_ablauf(info, HEUTE) == 10


# ── Durchgang mit Datenbank ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool nach jedem Test schließen (siehe mcp_fixtures)."""
    yield
    await engine.dispose()


@pytest.fixture
async def superadmin():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"lizenzablauf-{marker}@test.invalid",
            hashed_password="x",
            is_active=True,
            is_superadmin=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    yield user
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()


@pytest.fixture
async def ohne_merker():
    async def _weg():
        async with AsyncSessionLocal() as db:
            await db.execute(delete(SystemSetting).where(SystemSetting.key == lizenz_ablauf.MERKER_KEY))
            await db.commit()

    await _weg()
    yield
    await _weg()


def _lizenz(monkeypatch, info: LicenseInfo) -> None:
    async def _aktuell(_db):
        return info

    # lizenz_ablauf importiert spät aus instance, also dort ersetzen.
    monkeypatch.setattr("app.services.instance.aktuelle_lizenz", _aktuell)


async def _durchgang(heute: date) -> bool:
    async with AsyncSessionLocal() as db:
        return await lizenz_ablauf.pruefen_und_melden(db, heute=heute)


async def _merker() -> str | None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(SystemSetting.value).where(SystemSetting.key == lizenz_ablauf.MERKER_KEY))
        return r.scalar_one_or_none()


async def test_durchgang_meldet_jede_stufe_einmal(superadmin, ohne_merker, monkeypatch):
    heute = datetime.now(timezone.utc).date()
    ablauf = heute + timedelta(days=20)
    _lizenz(monkeypatch, _info(ablauf, customer="FF Musterstadt"))
    send = AsyncMock()
    monkeypatch.setattr(lizenz_ablauf, "send_update_notification", send)

    assert await _durchgang(heute)
    empfaenger = [c.args[1] for c in send.await_args_list]
    assert superadmin.email in empfaenger
    betreff, text = send.await_args_list[0].args[2:4]
    assert "in 20 Tagen" in betreff
    assert "FF Musterstadt" in text
    assert await _merker() == f"{ablauf}:30"

    send.reset_mock()
    assert not await _durchgang(heute)
    assert not await _durchgang(heute + timedelta(days=1))
    send.assert_not_awaited()

    assert await _durchgang(ablauf - timedelta(days=7))
    assert await _merker() == f"{ablauf}:7"


async def test_neuer_schluessel_meldet_wieder(superadmin, ohne_merker, monkeypatch):
    heute = datetime.now(timezone.utc).date()
    send = AsyncMock()
    monkeypatch.setattr(lizenz_ablauf, "send_update_notification", send)

    _lizenz(monkeypatch, _info(heute + timedelta(days=5)))
    assert await _durchgang(heute)

    # Verlängert, aber der neue läuft auch schon in 30 Tagen ab.
    _lizenz(monkeypatch, _info(heute + timedelta(days=30)))
    assert await _durchgang(heute)
    assert await _merker() == f"{heute + timedelta(days=30)}:30"


async def test_ohne_zustellung_gilt_nichts_als_gemeldet(superadmin, ohne_merker, monkeypatch):
    heute = datetime.now(timezone.utc).date()
    _lizenz(monkeypatch, _info(heute + timedelta(days=10)))
    monkeypatch.setattr(
        lizenz_ablauf, "send_update_notification", AsyncMock(side_effect=RuntimeError("SMTP not configured"))
    )

    assert not await _durchgang(heute)
    assert await _merker() is None


async def test_langer_schluessel_meldet_nichts(superadmin, ohne_merker, monkeypatch):
    heute = datetime.now(timezone.utc).date()
    _lizenz(monkeypatch, _info(heute + timedelta(days=365 * 30)))
    send = AsyncMock()
    monkeypatch.setattr(lizenz_ablauf, "send_update_notification", send)

    assert not await _durchgang(heute)
    send.assert_not_awaited()


# ── Durch die App ────────────────────────────────────────────────────────


def _token(user: User) -> str:
    claims = {
        "sub": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "typ": "access",
        "tv": user.token_version,
        "is_superadmin": True,
    }
    return _jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _status(user: User, monkeypatch, info: LicenseInfo) -> dict:
    from app.main import app

    async def _aktuell(_db):
        return info

    monkeypatch.setattr("app.api.routes.license.aktuelle_lizenz", _aktuell)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/license/status", headers={"Authorization": f"Bearer {_token(user)}"})
    assert r.status_code == 200
    return r.json()


@pytest.mark.parametrize(
    ("tage", "warnen"),
    [(400, False), (31, False), (30, True), (0, True)],
)
async def test_status_sagt_ob_gewarnt_wird(superadmin, monkeypatch, tage, warnen):
    heute = datetime.now(timezone.utc).date()
    data = await _status(superadmin, monkeypatch, _info(heute + timedelta(days=tage)))
    assert data["expires_in_days"] == tage
    assert data["expiry_warning"] is warnen


async def test_status_abgelaufen_ist_demo_und_keine_vorwarnung(superadmin, monkeypatch):
    heute = datetime.now(timezone.utc).date()
    abgelaufen = LicenseInfo(valid=False, expires=(heute - timedelta(days=3)).isoformat(), error="License expired")
    data = await _status(superadmin, monkeypatch, abgelaufen)
    # Dafür gibt es den Demo-Banner; die Vorwarnung wäre dann nur doppelt.
    assert data["demo_mode"] is True
    assert data["expires_in_days"] == -3
    assert data["expiry_warning"] is False
