"""Der Organisations-Export: vollständig, ohne Geheimnisse, nur die eigene Organisation.

Auf den Export stützt sich die Rückgabezusage des AV-Vertrags (§ 11). Die Tests
laufen deshalb gegen die echte Datenbank und prüfen nicht nur, *dass* etwas
herauskommt, sondern dass nichts fehlt, nichts Fremdes dabei ist und kein
Geheimnis die Installation verlässt.
"""

import io
import json
import uuid
import zipfile
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.api.routes import admin as admin_routes
from app.api.routes import organizations as org_routes
from app.database import AsyncSessionLocal, Base, engine
from app.models.api_key import SCOPE_ORGANIZATION, ApiKey
from app.models.audit_log import AuditLog
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.share_link import ConvoyShareLink
from app.models.system_metric import UserActivityDay
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waypoint import Waypoint
from app.services import org_export
from tests.fake_request import fake_request

PASSWORT_HASH = "$2b$12$geheim-passwort-hash-000000000000000000000000000"
MFA_GEHEIMNIS = "gAAAAA-mfa-geheimnis"
KEY_HASH = "sha256$geheimer-schluessel-hash"
LINK_PASSWORT = "$2b$12$geheimes-link-passwort-00000000000000000000000000"


@pytest.fixture(autouse=True)
async def reset_db_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def zwei_orgs():
    """Org A mit allem, was exportiert wird — und Org B, die nicht darin auftauchen darf."""
    m = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        inhaber = User(
            email=f"inhaber-{m}@test.invalid", hashed_password=PASSWORT_HASH, is_active=True,
            first_name="Ina", last_name="Inhaber", mfa_secret=MFA_GEHEIMNIS, mfa_enabled=True,
        )
        planer = User(email=f"planer-{m}@test.invalid", hashed_password=PASSWORT_HASH, is_active=True)
        fremd = User(email=f"fremd-{m}@test.invalid", hashed_password=PASSWORT_HASH, is_active=True)
        db.add_all([inhaber, planer, fremd])
        await db.flush()
        org_a = Organization(
            name=f"A {m}", slug=f"a-{m}", owner_id=inhaber.id,
            branding=json.dumps({"logo_main": f"logo-{m}.png", "logo_horizontal": "../../etc/passwd"}),
        )
        org_b = Organization(name=f"B {m}", slug=f"b-{m}", owner_id=fremd.id)
        db.add_all([org_a, org_b])
        await db.flush()
        db.add_all([
            UserOrganization(user_id=inhaber.id, organization_id=org_a.id, role="admin"),
            UserOrganization(user_id=planer.id, organization_id=org_a.id, role="planer"),
            UserOrganization(user_id=fremd.id, organization_id=org_b.id, role="admin"),
        ])
        elw = Vehicle(name="ELW", callsign="Florian 1/11", owner_id=inhaber.id, org_id=org_a.id)
        # Leihfahrzeug ohne Organisation, fährt aber im Konvoi von A mit.
        leih = Vehicle(name="Leih-LF", callsign="Florian 9/44", owner_id=planer.id)
        fremd_fz = Vehicle(name="Fremd-RTW", owner_id=fremd.id, org_id=org_b.id)
        konvoi = Convoy(name=f"Verband {m}", owner_id=inhaber.id, organization_id=org_a.id)
        fremd_konvoi = Convoy(name=f"Fremd {m}", owner_id=fremd.id, organization_id=org_b.id)
        db.add_all([elw, leih, fremd_fz, konvoi, fremd_konvoi])
        await db.flush()
        db.add_all([
            ConvoyVehicle(convoy_id=konvoi.id, vehicle_id=elw.id, position=0),
            ConvoyVehicle(convoy_id=konvoi.id, vehicle_id=leih.id, position=1),
            Waypoint(
                convoy_id=konvoi.id, name="Bereitstellungsraum", order_index=0,
                location="SRID=4326;POINT(13.4 52.5)",
            ),
            Route(convoy_id=konvoi.id, geometry="SRID=4326;LINESTRING(13.4 52.5, 13.5 52.6)"),
            ConvoyShareLink(
                convoy_id=konvoi.id, slug=f"s{m}", scope="driver", created_by_id=inhaber.id,
                password_hash=LINK_PASSWORT,
            ),
            ApiKey(
                organization_id=org_a.id, scope=SCOPE_ORGANIZATION, name="Leitstellenanbindung",
                prefix=f"cp_{m}", key_hash=KEY_HASH, role="planer", created_by_id=inhaber.id,
            ),
            UserActivityDay(
                user_id=planer.id, org_id=org_a.id, day=date(2026, 9, 1),
                first_seen_at=datetime(2026, 9, 1, 8, tzinfo=timezone.utc),
                last_seen_at=datetime(2026, 9, 1, 17, tzinfo=timezone.utc), requests=12,
            ),
            AuditLog(action="convoy.created", actor_id=inhaber.id, org_id=org_a.id, ip="203.0.113.7"),
            AuditLog(action="convoy.created", actor_id=fremd.id, org_id=org_b.id, ip="198.51.100.9"),
        ])
        await db.commit()
        ids = {
            "m": m, "org_a": org_a.id, "org_b": org_b.id,
            "inhaber": inhaber.id, "planer": planer.id, "fremd": fremd.id,
            "konvoi": konvoi.id, "fremd_konvoi": fremd_konvoi.id,
            "elw": elw.id, "leih": leih.id, "fremd_fz": fremd_fz.id,
        }
    yield ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AuditLog).where(AuditLog.org_id.in_([ids["org_a"], ids["org_b"]])))
        await db.execute(delete(UserActivityDay).where(UserActivityDay.org_id == ids["org_a"]))
        await db.execute(delete(Organization).where(Organization.id.in_([ids["org_a"], ids["org_b"]])))
        await db.execute(delete(Vehicle).where(Vehicle.id == ids["leih"]))
        await db.execute(
            delete(User).where(User.id.in_([ids["inhaber"], ids["planer"], ids["fremd"]]))
        )
        await db.commit()


async def _export(org_id) -> dict:
    async with AsyncSessionLocal() as db:
        org = await db.get(Organization, org_id)
        return await org_export.build_org_export(db, org)


def _ids(rows) -> set:
    return {r["id"] for r in rows}


# ── Inhalt ────────────────────────────────────────────────────────────────────

async def test_export_enthaelt_alles_der_organisation(zwei_orgs):
    b = await _export(zwei_orgs["org_a"])
    assert b["format"] == "convoyplan-organisation" and b["version"] == 1
    assert b["organization"]["id"] == zwei_orgs["org_a"]
    assert _ids(b["users"]) == {zwei_orgs["inhaber"], zwei_orgs["planer"]}
    assert {m["role"] for m in b["memberships"]} == {"admin", "planer"}
    # Das Leihfahrzeug ist dabei, weil es im Konvoi fährt.
    assert _ids(b["vehicles"]) == {zwei_orgs["elw"], zwei_orgs["leih"]}
    assert _ids(b["convoys"]) == {zwei_orgs["konvoi"]}
    assert len(b["convoy_vehicles"]) == 2
    assert len(b["waypoints"]) == 1 and len(b["routes"]) == 1 and len(b["share_links"]) == 1
    assert len(b["api_keys"]) == 1 and len(b["activity_days"]) == 1
    assert [a["ip"] for a in b["audit_log"]] == ["203.0.113.7"]


async def test_nichts_von_anderen_organisationen(zwei_orgs):
    text = json.dumps(org_export.jsonable_encoder(await _export(zwei_orgs["org_a"])))
    for fremd in ("org_b", "fremd", "fremd_konvoi", "fremd_fz"):
        assert str(zwei_orgs[fremd]) not in text, fremd
    assert "198.51.100.9" not in text


async def test_keine_geheimnisse(zwei_orgs):
    b = await _export(zwei_orgs["org_a"])
    text = json.dumps(org_export.jsonable_encoder(b))
    for geheim in (PASSWORT_HASH, MFA_GEHEIMNIS, KEY_HASH, LINK_PASSWORT, f"s{zwei_orgs['m']}"):
        assert geheim not in text
    for spalte in ("hashed_password", "mfa_secret", "token_version", "key_hash", "password_hash", "slug"):
        assert f'"{spalte}"' not in text.replace('"slug": "a-', "")  # der Org-Slug darf bleiben
    # Ob MFA an ist, ist keine Geheimnis — das Geheimnis selbst schon.
    inhaber = next(u for u in b["users"] if u["id"] == zwei_orgs["inhaber"])
    assert inhaber["mfa_enabled"] is True


async def test_geometrien_als_geojson(zwei_orgs):
    b = await _export(zwei_orgs["org_a"])
    assert b["waypoints"][0]["location"] == {"type": "Point", "coordinates": (13.4, 52.5)}
    assert b["routes"][0]["geometry"]["type"] == "LineString"


async def test_jede_spalte_ausser_geheimnissen(zwei_orgs):
    """Vollständigkeit auf Spaltenebene: nichts wird von Hand ausgelassen."""
    b = await _export(zwei_orgs["org_a"])
    for schluessel, tabelle in (
        ("users", "users"), ("vehicles", "vehicles"), ("convoys", "convoys"),
        ("api_keys", "api_keys"), ("share_links", "convoy_share_links"),
    ):
        spalten = {c.key for c in Base.metadata.tables[tabelle].columns}
        erwartet = spalten - org_export._GEHEIM.get(tabelle, frozenset())
        assert set(b[schluessel][0]) == erwartet, tabelle


def test_keine_tabelle_mit_organisationsbezug_faellt_durch():
    """Jede Tabelle, die an einer Organisation oder einem Konvoi hängt, ist
    entweder im Export oder ausdrücklich ausgenommen. Eine neue Tabelle, die
    keiner der beiden Mengen zugeordnet ist, lässt diesen Test scheitern."""
    bezug = set()
    for name, tabelle in Base.metadata.tables.items():
        ziele = {fk.column.table.name for fk in tabelle.foreign_keys}
        if ziele & {"organizations", "convoys"} or "org_id" in tabelle.columns:
            bezug.add(name)
    bezug.discard("organizations")
    nicht_zugeordnet = bezug - org_export.EXPORTIERT - org_export.NICHT_EXPORTIERT
    assert not nicht_zugeordnet, (
        f"Tabellen ohne Entscheidung für den Organisations-Export: {sorted(nicht_zugeordnet)} "
        "— in app/services/org_export.py in EXPORTIERT aufnehmen oder in NICHT_EXPORTIERT begründen."
    )
    assert not org_export.EXPORTIERT & org_export.NICHT_EXPORTIERT


# ── ZIP ───────────────────────────────────────────────────────────────────────

async def test_zip_mit_logo_und_ohne_pfadausbruch(zwei_orgs, tmp_path):
    (tmp_path / f"logo-{zwei_orgs['m']}.png").write_bytes(b"\x89PNG-test")
    inhalt = org_export.export_zip(await _export(zwei_orgs["org_a"]), logos_dir=tmp_path)
    with zipfile.ZipFile(io.BytesIO(inhalt)) as zf:
        assert sorted(zf.namelist()) == sorted(
            ["organisation.json", f"logos/logo-{zwei_orgs['m']}.png"]
        )
        doc = json.loads(zf.read("organisation.json"))
    # "../../etc/passwd" aus dem Branding wurde gar nicht erst angefasst.
    assert doc["logos"] == [f"logo-{zwei_orgs['m']}.png"]
    assert doc["logos_missing"] == []


async def test_fehlendes_logo_bricht_den_export_nicht(zwei_orgs, tmp_path):
    inhalt = org_export.export_zip(await _export(zwei_orgs["org_a"]), logos_dir=tmp_path)
    with zipfile.ZipFile(io.BytesIO(inhalt)) as zf:
        assert zf.namelist() == ["organisation.json"]
        assert json.loads(zf.read("organisation.json"))["logos_missing"] == [f"logo-{zwei_orgs['m']}.png"]


# ── Endpunkte ─────────────────────────────────────────────────────────────────

async def _audit_eintraege(org_id) -> list:
    async with AsyncSessionLocal() as db:
        return list((await db.execute(
            select(AuditLog).where(AuditLog.org_id == org_id, AuditLog.action == "org.exported")
        )).scalars().all())


async def _org_export_als(user_id, org_id, rolle, api_key=None, pfad_org=None):
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        org = await db.get(Organization, org_id)
        return await org_routes.export_organization(
            pfad_org or org_id, fake_request(), api_key, (user, org, rolle), db,
        )


async def test_admin_der_organisation_zieht_den_export(zwei_orgs):
    resp = await _org_export_als(zwei_orgs["planer"], zwei_orgs["org_a"], "admin")
    assert resp.media_type == "application/zip"
    assert f"convoyplan-a-{zwei_orgs['m']}-" in resp.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.body)) as zf:
        assert "organisation.json" in zf.namelist()
    [eintrag] = await _audit_eintraege(zwei_orgs["org_a"])
    assert eintrag.actor_id == zwei_orgs["planer"]


@pytest.mark.parametrize("rolle", ["planer", "fahrer", "beobachter"])
async def test_ohne_adminrolle_kein_export(zwei_orgs, rolle):
    with pytest.raises(HTTPException) as fehler:
        await _org_export_als(zwei_orgs["planer"], zwei_orgs["org_a"], rolle)
    assert fehler.value.status_code == 403
    assert await _audit_eintraege(zwei_orgs["org_a"]) == []


async def test_api_key_bekommt_keinen_export(zwei_orgs):
    """Auch ein Schlüssel mit Admin-Rolle nicht — der Export ist Menschen vorbehalten."""
    with pytest.raises(HTTPException) as fehler:
        await _org_export_als(zwei_orgs["inhaber"], zwei_orgs["org_a"], "admin", api_key="cp_irgendwas")
    assert fehler.value.status_code == 403
    assert await _audit_eintraege(zwei_orgs["org_a"]) == []


async def test_fremde_organisation_im_pfad(zwei_orgs):
    """Angemeldet in A, im Pfad die ID von B: 404, nicht der Export von A oder B."""
    with pytest.raises(HTTPException) as fehler:
        await _org_export_als(
            zwei_orgs["inhaber"], zwei_orgs["org_a"], "admin", pfad_org=zwei_orgs["org_b"],
        )
    assert fehler.value.status_code == 404


async def test_superadmin_zieht_jeden_export(zwei_orgs):
    async with AsyncSessionLocal() as db:
        superadmin = await db.get(User, zwei_orgs["fremd"])
        resp = await admin_routes.admin_export_organization(
            zwei_orgs["org_a"], fake_request(), db, superadmin,
        )
    with zipfile.ZipFile(io.BytesIO(resp.body)) as zf:
        doc = json.loads(zf.read("organisation.json"))
    assert doc["organization"]["id"] == str(zwei_orgs["org_a"])


# ── Über HTTP: Routen und Abhängigkeiten wirklich verdrahtet ──────────────────

async def test_endpunkte_ueber_http(zwei_orgs):
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_org_context, require_superadmin
    from app.main import app

    async with AsyncSessionLocal() as db:
        admin = await db.get(User, zwei_orgs["inhaber"])
        org = await db.get(Organization, zwei_orgs["org_a"])
    app.dependency_overrides[get_org_context] = lambda: (admin, org, "admin")
    app.dependency_overrides[require_superadmin] = lambda: admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            ok = await client.get(f"/api/organizations/{zwei_orgs['org_a']}/export")
            mit_key = await client.get(
                f"/api/organizations/{zwei_orgs['org_a']}/export", headers={"X-API-Key": "cp_x"},
            )
            als_superadmin = await client.get(f"/api/admin/organizations/{zwei_orgs['org_a']}/export")
            unbekannt = await client.get(f"/api/admin/organizations/{uuid.uuid4()}/export")
    finally:
        app.dependency_overrides.clear()
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(ok.content)).namelist() == ["organisation.json"]
    assert mit_key.status_code == 403
    assert als_superadmin.status_code == 200
    assert unbekannt.status_code == 404
