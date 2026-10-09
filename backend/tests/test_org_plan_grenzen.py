"""Pläne je Organisation: weiche Grenzen, harte Sperre nach Ablauf und Kulanz.

Die Zusagen:

- Ohne Plan keine Grenzen — der Normalfall jeder selbst betriebenen
  Installation darf durch ein Update nicht „Grenze erreicht" melden.
- Mehr Fahrzeuge, Planer oder Tracker als gebucht werden **nicht**
  abgewiesen, nur gemeldet. Anlegen klappt immer.
- Nach ``valid_until`` laufen 14 Tage Kulanz, danach ist die Organisation nur
  noch lesend: schreiben 402, lesen 200. Nichts wird gelöscht.
- Fahrer und Beobachter zählen nicht als Planer, gesperrte Tracker nicht
  als Tracker.
- Ein Plan von vor der Tracker-Grenze bleibt ohne sie: kein Update meldet
  plötzlich eine Überschreitung.

Zuerst die Rechenregel ohne Datenbank und Uhr, danach der Weg durch die App.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.org_plan import OrganizationPlan
from app.models.organization import Organization, UserOrganization
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import org_plan

HEUTE = date(2026, 9, 30)


def _zeile(**felder) -> OrganizationPlan:
    return OrganizationPlan(
        plan=felder.pop("plan", "hosting_s"),
        max_vehicles=felder.pop("max_vehicles", 25),
        max_planners=felder.pop("max_planners", 5),
        max_trackers=felder.pop("max_trackers", None),
        valid_until=felder.pop("valid_until", None),
    )


# ── Rechenregel ──────────────────────────────────────────────────────────


def test_ohne_plan_nie_eine_grenze_und_nie_gesperrt():
    z = org_plan.zustand(None, org_plan.Nutzung(fahrzeuge=10_000, planer=10_000), HEUTE)
    assert not (z.fahrzeuge_ueber or z.planer_ueber or z.abgelaufen or z.gesperrt)


def test_grenze_erreicht_ist_nicht_ueberschritten():
    z = org_plan.zustand(_zeile(), org_plan.Nutzung(fahrzeuge=25, planer=5), HEUTE)
    assert not z.fahrzeuge_ueber and not z.planer_ueber
    z = org_plan.zustand(_zeile(), org_plan.Nutzung(fahrzeuge=26, planer=6), HEUTE)
    assert z.fahrzeuge_ueber and z.planer_ueber
    # Überschreiten sperrt nichts — die Grenzen sind weich.
    assert not z.gesperrt


def test_tracker_ueber_der_grenze():
    z = org_plan.zustand(_zeile(max_trackers=2), org_plan.Nutzung(0, 0, tracker=2), HEUTE)
    assert not z.tracker_ueber
    z = org_plan.zustand(_zeile(max_trackers=2), org_plan.Nutzung(0, 0, tracker=3), HEUTE)
    assert z.tracker_ueber and not z.gesperrt
    # Ein Plan ohne Tracker-Grenze (auch jeder von vor Migration 0062) kennt kein Über.
    z = org_plan.zustand(_zeile(), org_plan.Nutzung(0, 0, tracker=500), HEUTE)
    assert not z.tracker_ueber


def test_unbegrenzt_kennt_kein_ueber():
    z = org_plan.zustand(
        _zeile(max_vehicles=None, max_planners=None), org_plan.Nutzung(10_000, 10_000), HEUTE
    )
    assert not z.fahrzeuge_ueber and not z.planer_ueber


@pytest.mark.parametrize(
    ("tage_nach_ablauf", "abgelaufen", "gesperrt"),
    [
        (-1, False, False),  # noch gebucht
        (0, False, False),  # letzter gebuchter Tag
        (1, True, False),  # erster Kulanztag
        (14, True, False),  # letzter Kulanztag
        (15, True, True),  # ab hier nur noch lesend
    ],
)
def test_ablauf_und_kulanz(tage_nach_ablauf, abgelaufen, gesperrt):
    ende = HEUTE - timedelta(days=tage_nach_ablauf)
    z = org_plan.zustand(_zeile(valid_until=ende), org_plan.Nutzung(0, 0), HEUTE)
    assert (z.abgelaufen, z.gesperrt) == (abgelaufen, gesperrt)
    assert z.tage_bis_ablauf == -tage_nach_ablauf
    assert z.sperre_ab == ende + timedelta(days=org_plan.KULANZ_TAGE + 1)


def test_katalog_entspricht_der_preisliste():
    """Die Grenzen, die ein Angebot verspricht. Ändert sich die Preisliste,
    ändert sich dieser Test mit — bewusst und nicht nebenbei."""
    k = org_plan.KATALOG
    assert (k["hosting_s"].max_fahrzeuge, k["hosting_s"].max_planer) == (25, 5)
    assert (k["hosting_m"].max_fahrzeuge, k["hosting_m"].max_planer) == (150, 20)
    assert (k["hosting_l"].max_fahrzeuge, k["hosting_l"].max_planer) == (None, None)
    assert (k["einsatz"].max_fahrzeuge, k["einsatz"].max_planer) == (50, 10)
    assert k["einsatz"].laufzeit_tage == 30
    # Tracker hat kein Paket begrenzt; die Grenze setzt das Angebot.
    assert all(p.max_tracker is None for p in k.values())


# ── Durch die App ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


def _token(user_id, tv: int, **extra) -> str:
    claims = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "typ": "access",
        "tv": tv,
        **extra,
    }
    return _jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def org():
    """Organisation mit Admin, Planer, Fahrer und Beobachter plus Superadmin."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        chef = User(email=f"plan-su-{marker}@test.invalid", hashed_password="x", is_superadmin=True)
        admin = User(email=f"plan-ad-{marker}@test.invalid", hashed_password="x")
        planer = User(email=f"plan-pl-{marker}@test.invalid", hashed_password="x")
        fahrer = User(email=f"plan-fa-{marker}@test.invalid", hashed_password="x")
        beob = User(email=f"plan-be-{marker}@test.invalid", hashed_password="x")
        db.add_all([chef, admin, planer, fahrer, beob])
        await db.flush()
        o = Organization(name=f"Plan {marker}", slug=f"p{marker[:7]}", owner_id=admin.id)
        db.add(o)
        await db.flush()
        for u, rolle in [(admin, "admin"), (planer, "planer"), (fahrer, "fahrer"), (beob, "beobachter")]:
            db.add(UserOrganization(user_id=u.id, organization_id=o.id, role=rolle))
        await db.commit()
        ids = SimpleNamespace(
            org_id=o.id,
            org_slug=o.slug,
            chef=_token(chef.id, chef.token_version, is_superadmin=True),
            admin=_token(
                admin.id, admin.token_version, org_id=str(o.id), org_slug=o.slug, role="admin"
            ),
            users=[chef.id, admin.id, planer.id, fahrer.id, beob.id],
        )
    yield ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Ortungsgeraet).where(Ortungsgeraet.organization_id == ids.org_id))
        await db.execute(delete(Vehicle).where(Vehicle.org_id == ids.org_id))
        await db.execute(delete(OrganizationPlan).where(OrganizationPlan.organization_id == ids.org_id))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id))
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id.in_(ids.users)))
        await db.commit()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_ohne_plan_sieht_die_organisation_nichts(org, client):
    r = await client.get("/api/org/plan", headers=_h(org.admin))
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] is None and not body["locked"]
    # Admin und Planer zählen, Fahrer und Beobachter nicht.
    assert body["planners"] == 2


async def test_einsatz_paket_bekommt_laufzeit_und_grenzen_aus_dem_katalog(org, client):
    r = await client.put(
        f"/api/admin/plans/organizations/{org.org_id}",
        json={"plan": "einsatz"},
        headers=_h(org.chef),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["max_vehicles"], body["max_planners"]) == (50, 10)
    heute = datetime.now(timezone.utc).date()
    assert body["valid_until"] == (heute + timedelta(days=29)).isoformat()
    assert body["days_left"] == 29


async def test_ausdruecklich_null_heisst_unbegrenzt(org, client):
    r = await client.put(
        f"/api/admin/plans/organizations/{org.org_id}",
        json={"plan": "hosting_s", "max_vehicles": None, "max_planners": 7},
        headers=_h(org.chef),
    )
    assert r.status_code == 200, r.text
    assert (r.json()["max_vehicles"], r.json()["max_planners"]) == (None, 7)


async def test_unbekannter_plan_wird_abgewiesen(org, client):
    r = await client.put(
        f"/api/admin/plans/organizations/{org.org_id}",
        json={"plan": "gold"},
        headers=_h(org.chef),
    )
    assert r.status_code == 422


async def test_nur_der_superadmin_setzt_plaene(org, client):
    r = await client.put(
        f"/api/admin/plans/organizations/{org.org_id}",
        json={"plan": "hosting_l"},
        headers=_h(org.admin),
    )
    assert r.status_code == 403


async def test_ueberschreitung_wird_gemeldet_nicht_verhindert(org, client):
    await client.put(
        f"/api/admin/plans/organizations/{org.org_id}",
        json={"plan": "hosting_s", "max_vehicles": 1},
        headers=_h(org.chef),
    )
    for name in ("LF 1", "LF 2"):
        r = await client.post("/api/vehicles/", json={"name": name}, headers=_h(org.admin))
        assert r.status_code == 201, r.text

    eigen = (await client.get("/api/org/plan", headers=_h(org.admin))).json()
    assert eigen["vehicles"] == 2 and eigen["vehicles_over"] is True

    liste = (await client.get("/api/admin/plans/organizations", headers=_h(org.chef))).json()
    zeile = next(z for z in liste if z["organization_id"] == str(org.org_id))
    assert zeile["vehicles_over"] is True
    # Überschreitungen stehen oben.
    erste_ohne = next((i for i, z in enumerate(liste) if not (z["vehicles_over"] or z["planners_over"] or z["expired"])), len(liste))
    assert liste.index(zeile) < erste_ohne


async def test_tracker_werden_gezaehlt_gesperrte_nicht(org, client):
    r = await client.put(
        f"/api/admin/plans/organizations/{org.org_id}",
        json={"plan": "hosting_s", "max_trackers": 1},
        headers=_h(org.chef),
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_trackers"] == 1
    ids = []
    for name in ("Tracker 1", "Tracker 2", "Tracker 3"):
        r = await client.post("/api/org/geraete", json={"name": name}, headers=_h(org.admin))
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    # Anlegen über der Grenze klappt — gemeldet wird nur.
    eigen = (await client.get("/api/org/plan", headers=_h(org.admin))).json()
    assert (eigen["trackers"], eigen["trackers_over"]) == (3, True)

    for i, geraet_id in enumerate(ids[1:], start=2):
        r = await client.put(
            f"/api/org/geraete/{geraet_id}", json={"name": f"Tracker {i}", "aktiv": False}, headers=_h(org.admin)
        )
        assert r.status_code == 200, r.text
    eigen = (await client.get("/api/org/plan", headers=_h(org.admin))).json()
    assert (eigen["trackers"], eigen["trackers_over"]) == (1, False)

    liste = (await client.get("/api/admin/plans/organizations", headers=_h(org.chef))).json()
    zeile = next(z for z in liste if z["organization_id"] == str(org.org_id))
    assert (zeile["trackers"], zeile["max_trackers"]) == (1, 1)


async def test_ohne_angabe_gilt_der_katalog_auch_fuer_tracker(org, client):
    r = await client.put(
        f"/api/admin/plans/organizations/{org.org_id}",
        json={"plan": "hosting_m"},
        headers=_h(org.chef),
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_trackers"] is None and r.json()["trackers_over"] is False


async def test_nach_kulanz_nur_noch_lesend(org, client):
    async with AsyncSessionLocal() as db:
        db.add(
            OrganizationPlan(
                organization_id=org.org_id,
                plan="einsatz",
                max_vehicles=50,
                max_planners=10,
                valid_until=datetime.now(timezone.utc).date()
                - timedelta(days=org_plan.KULANZ_TAGE + 1),
            )
        )
        await db.commit()

    r = await client.post("/api/vehicles/", json={"name": "HLF"}, headers=_h(org.admin))
    assert r.status_code == 402
    assert "nur noch lesbar" in r.json()["detail"]
    assert (await client.get("/api/vehicles/", headers=_h(org.admin))).status_code == 200
    assert (await client.get("/api/org/plan", headers=_h(org.admin))).json()["locked"] is True

    # Plan entfernen hebt die Sperre sofort auf.
    r = await client.delete(f"/api/admin/plans/organizations/{org.org_id}", headers=_h(org.chef))
    assert r.status_code == 204
    r = await client.post("/api/vehicles/", json={"name": "HLF"}, headers=_h(org.admin))
    assert r.status_code == 201


async def test_in_der_kulanz_geht_alles_weiter(org, client):
    async with AsyncSessionLocal() as db:
        db.add(
            OrganizationPlan(
                organization_id=org.org_id,
                plan="einsatz",
                valid_until=datetime.now(timezone.utc).date() - timedelta(days=3),
            )
        )
        await db.commit()
    r = await client.post("/api/vehicles/", json={"name": "ELW"}, headers=_h(org.admin))
    assert r.status_code == 201
    body = (await client.get("/api/org/plan", headers=_h(org.admin))).json()
    assert body["expired"] is True and body["locked"] is False


# ── Über den Assistenten (MCP) ───────────────────────────────────────────


async def test_mcp_schreibt_nach_kulanz_nicht_mehr_liest_aber_weiter():
    """Dieselbe Regel wie in der REST-API, an der zweiten Tür."""
    from app.mcp import scopes as scope_svc
    from tests.mcp_fixtures import call, connect, mcp_app, mcp_session, purge_clients, seeded

    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(
            client, fx.planer, fx.org_a, scopes=list(scope_svc.ALL_SCOPES)
        )
        session = await mcp_session(client, token["access_token"])
        async with AsyncSessionLocal() as db:
            db.add(
                OrganizationPlan(
                    organization_id=fx.org_a.id,
                    plan="einsatz",
                    valid_until=datetime.now(timezone.utc).date()
                    - timedelta(days=org_plan.KULANZ_TAGE + 1),
                )
            )
            await db.commit()

        schreiben = await call(
            client, token["access_token"], session, "tools/call",
            {"name": "konvoi_anlegen", "arguments": {"name": "Nach Ablauf"}},
        )
        result = schreiben.get("result", {})
        assert result.get("isError") is True, schreiben
        text = " ".join(t.get("text", "") for t in result.get("content", []))
        assert "nur noch lesbar" in text

        lesen = await call(
            client, token["access_token"], session, "tools/call",
            {"name": "konvois_auflisten", "arguments": {}},
        )
        assert lesen.get("result", {}).get("isError") is not True, lesen
        await purge_clients([reg["client_id"]])
