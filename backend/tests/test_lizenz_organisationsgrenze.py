"""Wie viele Organisationen eine Installation anlegen darf.

Die Zusagen, um die es geht:

- Ein Altschlüssel (ohne ``v``) erlaubt weiter beliebig viele — ausgestellte
  Schlüssel behalten, was sie erlaubt haben.
- ``max_orgs`` aus einem v2-Schlüssel greift beim **Anlegen**, auf allen
  Wegen (Superadmin, Benutzer, Ersteinrichtung), und nicht beim Betrieb.
- Nach dem Vertragsende fällt nur das Anlegen auf eine Organisation zurück;
  die Instanz bleibt lizenziert.
- Demo-Organisationen zählen nicht.

Zuerst die Rechenregel ohne Datenbank, danach der Weg durch die echte App.
"""
import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.organization import Organization, UserOrganization
from app.models.user import User
import app.services.license as lic_mod
from app.services import org_kontingent

HEUTE = date(2026, 9, 30)


def _v2(**felder) -> lic_mod.LicenseInfo:
    info = lic_mod.LicenseInfo(valid=True, version=2, contract="free", max_orgs=1)
    for k, v in felder.items():
        setattr(info, k, v)
    return info


# ── Rechenregel ──────────────────────────────────────────────────────────


def test_altschluessel_ist_unbegrenzt():
    assert org_kontingent.grenze(lic_mod.LicenseInfo(valid=True), HEUTE) is None


def test_v2_grenze_kommt_aus_dem_schluessel():
    assert org_kontingent.grenze(_v2(max_orgs=5), HEUTE) == 5
    assert org_kontingent.grenze(_v2(max_orgs=None), HEUTE) is None


def test_ohne_gueltige_lizenz_genau_eine():
    assert org_kontingent.grenze(lic_mod.LicenseInfo(valid=False), HEUTE) == 1


def test_nach_vertragsende_eine_davor_die_vereinbarte():
    assert org_kontingent.grenze(_v2(max_orgs=5, contract_until="2026-09-29"), HEUTE) == 1
    # Der letzte Vertragstag zählt noch.
    assert org_kontingent.grenze(_v2(max_orgs=5, contract_until="2026-09-30"), HEUTE) == 5


def test_unlesbares_vertragsende_sperrt_nichts():
    info = _v2(max_orgs=5, contract_until="30.09.2026")
    assert not org_kontingent.vertrag_beendet(info, HEUTE)
    assert org_kontingent.grenze(info, HEUTE) == 5


def test_darf_anlegen():
    assert org_kontingent.darf_anlegen(0, 1)
    assert not org_kontingent.darf_anlegen(1, 1)
    assert org_kontingent.darf_anlegen(10_000, None)


# ── Schlüssel v2 lesen ───────────────────────────────────────────────────


def _signieren(payload: dict, monkeypatch) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", base64.b64encode(pub).decode())
    # Dieselbe Form wie der Lizenzmanager: sortierte Schlüssel.
    roh = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    return f"{b64(roh)}.{b64(priv.sign(roh))}"


def test_v2_schluessel_traegt_vertrag_und_grenze(monkeypatch):
    key = _signieren(
        {
            "v": 2,
            "instance_id": "inst-1",
            "expires": "2056-09-30",
            "customer": "FF Musterstadt",
            "contract": "wartung_plus",
            "max_orgs": 5,
            "contract_until": "2027-09-29",
        },
        monkeypatch,
    )
    info = lic_mod.validate_license(key, "inst-1")
    assert info.valid
    assert (info.version, info.contract, info.max_orgs) == (2, "wartung_plus", 5)
    assert info.contract_until == "2027-09-29"


def test_v2_null_heisst_unbegrenzt(monkeypatch):
    key = _signieren(
        {"v": 2, "instance_id": "i", "expires": "2056-01-01", "contract": "hosting", "max_orgs": 0},
        monkeypatch,
    )
    assert lic_mod.validate_license(key, "i").max_orgs is None


def test_altschluessel_bleibt_legacy(monkeypatch):
    key = _signieren({"instance_id": "i", "expires": "2100-05-27"}, monkeypatch)
    info = lic_mod.validate_license(key, "i")
    assert info.valid
    assert (info.version, info.contract, info.max_orgs) == (1, "legacy", None)


# ── Durch die App ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool nach jedem Test schließen (siehe mcp_fixtures)."""
    yield
    await engine.dispose()


def _token(user: User, **extra) -> str:
    claims = {
        "sub": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "typ": "access",
        "tv": user.token_version,
        **extra,
    }
    return _jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def superadmin():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"orggrenze-{marker}@test.invalid",
            hashed_password="x",
            is_active=True,
            is_superadmin=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    yield user
    async with AsyncSessionLocal() as db:
        orgs = select(Organization.id).where(Organization.owner_id == user.id)
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id.in_(orgs)))
        await db.execute(delete(UserOrganization).where(UserOrganization.user_id == user.id))
        await db.execute(delete(Organization).where(Organization.owner_id == user.id))
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()


async def _anzahl() -> int:
    async with AsyncSessionLocal() as db:
        return await org_kontingent.anzahl(db)


def _lizenz(monkeypatch, info: lic_mod.LicenseInfo) -> None:
    async def _aktuell(_db):
        return info

    monkeypatch.setattr(org_kontingent, "aktuelle_lizenz", _aktuell)


async def _anlegen(client: AsyncClient, user: User, slug: str):
    return await client.post(
        "/api/admin/organizations",
        json={"name": f"Org {slug}", "slug": slug},
        headers={"Authorization": f"Bearer {_token(user, is_superadmin=True)}"},
    )


async def test_superadmin_scheitert_an_voller_grenze(superadmin, monkeypatch):
    from app.main import app

    _lizenz(monkeypatch, _v2(max_orgs=await _anzahl()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await _anlegen(client, superadmin, uuid.uuid4().hex[:8])
    assert r.status_code == 402
    assert "Organisation" in r.json()["detail"]


async def test_superadmin_legt_an_solange_platz_ist(superadmin, monkeypatch):
    from app.main import app

    _lizenz(monkeypatch, _v2(max_orgs=await _anzahl() + 1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await _anlegen(client, superadmin, uuid.uuid4().hex[:8])
    assert r.status_code == 201, r.text


async def test_benutzer_scheitert_ebenso(superadmin, monkeypatch):
    """Der zweite Weg — jeder angemeldete Benutzer darf Organisationen anlegen."""
    from app.main import app

    _lizenz(monkeypatch, _v2(max_orgs=await _anzahl()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/organizations/",
            json={"name": "Noch eine"},
            headers={"Authorization": f"Bearer {_token(superadmin)}"},
        )
    assert r.status_code == 402


async def test_demo_organisationen_zaehlen_nicht(superadmin):
    vorher = await _anzahl()
    async with AsyncSessionLocal() as db:
        db.add(
            Organization(
                name="Demo", slug=f"d{uuid.uuid4().hex[:7]}", owner_id=superadmin.id, is_demo=True
            )
        )
        await db.commit()
        gesamt = (await db.execute(select(func.count(Organization.id)))).scalar_one()
    assert await _anzahl() == vorher
    assert gesamt > vorher


async def test_lizenzstatus_nennt_grenze_und_belegung(superadmin, monkeypatch):
    from app.main import app
    import app.services.instance as instance_mod

    info = _v2(max_orgs=5, contract="wartung_plus", contract_until="2020-01-01")

    async def _aktuell(_db):
        return info

    monkeypatch.setattr(org_kontingent, "aktuelle_lizenz", _aktuell)
    monkeypatch.setattr("app.api.routes.license.aktuelle_lizenz", _aktuell)
    monkeypatch.setattr(instance_mod, "aktuelle_lizenz", _aktuell)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            "/api/license/status",
            headers={"Authorization": f"Bearer {_token(superadmin, is_superadmin=True)}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract"] == "wartung_plus"
    assert body["max_orgs"] == 5
    # Vertrag vorbei: fürs Anlegen gilt wieder eine, ohne Demo-Modus.
    assert body["contract_ended"] is True
    assert body["orgs_limit"] == 1
    assert body["demo_mode"] is False
    assert body["orgs_count"] == await _anzahl()
