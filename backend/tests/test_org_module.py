"""Module je Organisation: der Betreiber schaltet frei, das Backend setzt durch.

Die Zusagen:

- Selbst gehostet ist alles frei, auf dem Hosting-Server ist eine neue
  Organisation ohne Module. Demo-Organisationen haben immer alles.
- Freischalten darf nur der Superadmin; lesen darf jedes Mitglied.
- Ein gesperrtes Modul ist nicht nur ein ausgegrauter Reiter: sein Router
  antwortet 403, der Tracker schweigt, die öffentliche Aktionsseite ist 404
  und zeichnet nichts auf, das Branding fällt auf die Plattform zurück, die
  KI-Richtlinie gilt als aus.
- Gesperrt wird nichts gelöscht: nach der Freigabe gilt der alte Stand.

Zuerst die Regel ohne Datenbank, danach der Weg durch die App.
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.org_mcp_policy import OrganizationMcpPolicy
from app.models.org_module import OrganizationModule
from app.models.organization import Organization
from app.models.user import User
from app.services import betriebsart, org_mcp_policy, org_module, positionsverlauf
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    _token,
    aktion,
    client,
    h,
    reset_db_engine,
    seite_anlegen,
)

ORG_ROUTEN = {
    org_module.TRACKER: "/api/org/geraete",
    org_module.AKTIONSSEITEN: "/api/org/aktionsseiten",
    org_module.BRANDING: "/api/org/branding",
    org_module.KI: "/api/org/mcp",
}


# ── Regel ────────────────────────────────────────────────────────────────


def test_standard_haengt_an_der_betriebsart():
    assert org_module.standard(betriebsart.SELFHOST) is True
    assert org_module.standard(betriebsart.HOSTING) is False


@pytest.mark.parametrize("art", [betriebsart.SELFHOST, betriebsart.HOSTING])
def test_entscheidung_schlaegt_standard(art):
    assert org_module.gilt(True, art=art) is True
    assert org_module.gilt(False, art=art) is False


def test_demo_hat_immer_alles():
    assert org_module.gilt(False, demo=True, art=betriebsart.HOSTING) is True
    assert org_module.gilt(None, demo=True, art=betriebsart.HOSTING) is True


def test_jede_org_route_hat_ihr_modul():
    assert set(ORG_ROUTEN) == set(org_module.MODULE)


# ── Durch die App ────────────────────────────────────────────────────────


@pytest.fixture
def hosting(monkeypatch):
    monkeypatch.setattr(settings, "instance_mode", "hosting")


@pytest.fixture
async def chef():
    async with AsyncSessionLocal() as db:
        u = User(email=f"modul-su-{datetime.now().timestamp()}@test.invalid", hashed_password="x", is_superadmin=True)
        db.add(u)
        await db.commit()
        token = _token(u.id, u.token_version, is_superadmin=True)
        uid = u.id
    yield token
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _setzen(org_id, **werte: bool) -> None:
    async with AsyncSessionLocal() as db:
        await org_module.setzen(db, org_id, werte)
        await db.commit()
    from app.api.routes import aktionsseite as routen

    routen._cache.clear()
    positionsverlauf.vergessen()


async def test_selbst_gehostet_ist_alles_frei(aktion, client):
    r = await client.get("/api/org/modules", headers=h(aktion.admin))
    assert r.status_code == 200
    assert r.json() == {m: True for m in org_module.MODULE}
    for pfad in ORG_ROUTEN.values():
        assert (await client.get(pfad, headers=h(aktion.admin))).status_code == 200, pfad


async def test_hosting_neue_organisation_hat_nichts(aktion, client, hosting):
    r = await client.get("/api/org/modules", headers=h(aktion.fahrer))
    assert r.json() == {m: False for m in org_module.MODULE}
    for modul, pfad in ORG_ROUTEN.items():
        r = await client.get(pfad, headers=h(aktion.admin))
        assert r.status_code == 403, pfad
        assert org_module.MODULE[modul].label in r.json()["detail"]


async def test_hosting_demo_organisation_hat_alles(aktion, client, hosting):
    async with AsyncSessionLocal() as db:
        org = await db.get(Organization, aktion.org_id)
        org.is_demo = True
        await db.commit()
    r = await client.get("/api/org/modules", headers=h(aktion.admin))
    assert all(r.json().values())


async def test_superadmin_schaltet_frei(aktion, client, chef, hosting):
    r = await client.put(
        f"/api/admin/modules/organizations/{aktion.org_id}",
        json={"tracker": True},
        headers=h(chef),
    )
    assert r.status_code == 200, r.text
    assert r.json()["module"]["tracker"] is True
    assert r.json()["module"]["aktionsseiten"] is False
    assert (await client.get("/api/org/geraete", headers=h(aktion.admin))).status_code == 200
    assert (await client.get("/api/org/aktionsseiten", headers=h(aktion.admin))).status_code == 403

    liste = (await client.get("/api/admin/modules/organizations", headers=h(chef))).json()
    zeile = next(z for z in liste if z["organization_id"] == str(aktion.org_id))
    assert zeile["module"]["tracker"] is True

    katalog = (await client.get("/api/admin/modules/catalog", headers=h(chef))).json()
    assert katalog["standard"] is False and katalog["betriebsart"] == "hosting"


async def test_selbst_gehostet_laesst_sich_sperren(aktion, client, chef):
    r = await client.put(
        f"/api/admin/modules/organizations/{aktion.org_id}",
        json={"branding": False},
        headers=h(chef),
    )
    assert r.status_code == 200
    assert (await client.get("/api/org/branding", headers=h(aktion.admin))).status_code == 403


async def test_nur_der_superadmin_schaltet(aktion, client):
    r = await client.put(
        f"/api/admin/modules/organizations/{aktion.org_id}",
        json={"tracker": True},
        headers=h(aktion.admin),
    )
    assert r.status_code == 403


async def test_unbekanntes_modul_wird_abgewiesen(aktion, client, chef):
    r = await client.put(
        f"/api/admin/modules/organizations/{aktion.org_id}",
        json={"warp": True},
        headers=h(chef),
    )
    assert r.status_code == 422


async def test_gesperrter_tracker_schweigt(aktion):
    from app.api.routes.geraete import _schweigt

    async with AsyncSessionLocal() as db:
        assert await _schweigt(db, aktion.org_id) is False
    await _setzen(aktion.org_id, tracker=False)
    async with AsyncSessionLocal() as db:
        assert await _schweigt(db, aktion.org_id) is True


async def test_gesperrte_aktionsseite_ist_404_und_zeichnet_nichts_auf(aktion, client):
    seite = await seite_anlegen(client, aktion)
    pfad = f"/api/public/aktion/{seite['slug']}"
    assert (await client.get(pfad, headers=h(seite["fetch_token"]))).status_code == 200
    async with AsyncSessionLocal() as db:
        assert aktion.convoy_id in await positionsverlauf.aktive_konvois(db, datetime.now(timezone.utc))

    await _setzen(aktion.org_id, aktionsseiten=False)
    assert (await client.get(pfad, headers=h(seite["fetch_token"]))).status_code == 404
    async with AsyncSessionLocal() as db:
        assert aktion.convoy_id not in await positionsverlauf.aktive_konvois(db, datetime.now(timezone.utc))

    # Nichts gelöscht: nach der Freigabe ist die Seite wieder da.
    await _setzen(aktion.org_id, aktionsseiten=True)
    assert (await client.get(pfad, headers=h(seite["fetch_token"]))).status_code == 200


async def test_gesperrtes_branding_faellt_auf_die_plattform_zurueck(aktion, client):
    async with AsyncSessionLocal() as db:
        org = await db.get(Organization, aktion.org_id)
        org.branding = json.dumps({"app_name": "Florian Einsatzplaner"})
        slug = org.slug
        await db.commit()
    r = await client.get(f"/api/branding/org/{slug}")
    assert r.json()["app_name"] == "Florian Einsatzplaner"

    await _setzen(aktion.org_id, branding=False)
    r = await client.get(f"/api/branding/org/{slug}")
    assert r.json()["app_name"] != "Florian Einsatzplaner"
    async with AsyncSessionLocal() as db:
        assert (await db.get(Organization, aktion.org_id)).branding is not None


async def test_gesperrte_ki_gilt_als_aus(aktion):
    async with AsyncSessionLocal() as db:
        await org_mcp_policy.setzen(
            db, aktion.org_id, enabled=True, scopes=["convoy:read"], bereiche=["konvois"]
        )
        await db.commit()
        assert (await org_mcp_policy.fuer_org(db, aktion.org_id)).enabled is True
    await _setzen(aktion.org_id, ki=False)
    async with AsyncSessionLocal() as db:
        assert (await org_mcp_policy.fuer_org(db, aktion.org_id)).enabled is False
        assert (await org_mcp_policy.fuer_orgs(db, [aktion.org_id]))[aktion.org_id].enabled is False
        await db.execute(
            delete(OrganizationMcpPolicy).where(OrganizationMcpPolicy.organization_id == aktion.org_id)
        )
        await db.execute(
            delete(OrganizationModule).where(OrganizationModule.organization_id == aktion.org_id)
        )
        await db.commit()
