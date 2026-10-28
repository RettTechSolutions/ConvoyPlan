"""Übernommene Halte nach einer neuen Route neu verteilen.

Gemeldet: Nach einer Umplanung (Höhe und Gewicht sperrten den alten Weg) stand
jede übernommene Empfehlung noch dort, wo sie für die *alte* Route fällig war.
Weil der neue Weg bis dorthin länger ist, kam jeder dieser Halte zu spät, und
die Empfehlung legte einen neuen davor — zwei Tagesruhezeiten 45 km
auseinander, 11 h Stillstand für nichts. Die Zusagen:

- ein übernommener Vorschlag trägt seine Herkunft, bis jemand Name, Art, Lage,
  Dauer oder Grund ändert; Notiz und Reihenfolge zählen nicht;
- die Analyse meldet in ``neu_verteilen``, welche übernommenen Halte nicht mehr
  zur frischen Empfehlung passen — und nichts, solange sie passen;
- neu verteilt wird nur auf Knopfdruck, und dann nur, was unberührt und
  veraltet ist; eigene Halte bleiben stehen;
- die neuen Halte kommen als Vorschläge, ohne Kilometer im Namen, und werden
  von der nächsten Berechnung einsortiert.
"""
import uuid
from types import SimpleNamespace

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import LineString, Point
from sqlalchemy import delete, select

from app.api.deps import OrgCtx, get_current_user, get_org_context  # noqa: F401
from app.api.routes import routing
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.waypoint import Waypoint
from app.services import halte_vorschlag
from app.services.fuel import haversine_m

# ── Die Regel, ohne Datenbank ────────────────────────────────────────────────


def _halt(kind, km):
    return {"kind": kind, "stop_km": km}


def test_passende_vorschlaege_sind_nicht_veraltet():
    frisch = [_halt("tech", 126), _halt("break", 252), _halt("daily_rest", 535)]
    uebernommen = [
        halte_vorschlag.Uebernommen("a", "tech", 130),
        halte_vorschlag.Uebernommen("b", "break", 250),
        halte_vorschlag.Uebernommen("c", "daily_rest", 535),
    ]
    assert halte_vorschlag.abgleich(frisch, uebernommen, 16) == ([], [])


def test_der_gemeldete_fall_nach_der_umplanung():
    """Der neue Weg ist bis Bologna ~65 km länger: jeder alte Halt liegt jetzt
    zu weit hinten, die frische Empfehlung früher."""
    frisch = [_halt("tech", 126.5), _halt("break", 284.7), _halt("daily_rest", 569.4)]
    uebernommen = [
        halte_vorschlag.Uebernommen("th-alt", "tech", 190),
        halte_vorschlag.Uebernommen("lp-alt", "break", 318),
        halte_vorschlag.Uebernommen("tr-alt", "daily_rest", 602),
    ]
    veraltet, fehlend = halte_vorschlag.abgleich(frisch, uebernommen, 16)
    assert veraltet == ["th-alt", "lp-alt", "tr-alt"]
    assert [h["kind"] for h in fehlend] == ["tech", "break", "daily_rest"]


def test_nur_dieselbe_art_passt():
    veraltet, fehlend = halte_vorschlag.abgleich(
        [_halt("break", 250)], [halte_vorschlag.Uebernommen("a", "tech", 250)], 16
    )
    assert veraltet == ["a"] and [h["kind"] for h in fehlend] == ["break"]


def test_jeder_vorschlag_passt_hoechstens_einmal():
    frisch = [_halt("tech", 100), _halt("tech", 110)]
    veraltet, fehlend = halte_vorschlag.abgleich(
        frisch, [halte_vorschlag.Uebernommen("a", "tech", 105)], 16
    )
    assert veraltet == [] and [h["stop_km"] for h in fehlend] == [110]


def test_toleranz_ist_fahrzeit():
    # 15 min bei 64 km/h
    assert halte_vorschlag.toleranz_km(640, 10 * 3600) == pytest.approx(16)
    assert halte_vorschlag.toleranz_km(640, 0) == 0


def _vorschlag(**kw):
    return SimpleNamespace(**{
        "vorschlag_art": "break", "name": "Lenkpause", "type": "technical_stop",
        "hold_duration_min": 45, "halt_purpose": "rest", **kw,
    })


def test_das_formular_schickt_alles_mit_unveraendert_bleibt_vorschlag():
    wp = _vorschlag()
    alles = {"name": "Lenkpause", "type": "technical_stop", "hold_duration_min": 45,
             "halt_purpose": "rest", "notes": "Parkplatz hinten"}
    assert halte_vorschlag.bleibt_vorschlag(wp, alles, None, (47.0, 11.0))
    assert halte_vorschlag.bleibt_vorschlag(wp, {}, (47.0, 11.0), (47.0, 11.0))


@pytest.mark.parametrize("aenderung", [
    {"name": "Lenkpause Brennersee"},
    {"type": "stop"},
    {"hold_duration_min": 60},
    {"halt_purpose": "fuel"},
])
def test_wer_den_halt_aendert_macht_ihn_zu_seinem(aenderung):
    assert not halte_vorschlag.bleibt_vorschlag(_vorschlag(), aenderung, None, (47.0, 11.0))


def test_verschoben_ist_angefasst():
    assert not halte_vorschlag.bleibt_vorschlag(_vorschlag(), {}, (47.1, 11.0), (47.0, 11.0))


def test_ohne_marke_bleibt_es_ohne():
    assert not halte_vorschlag.bleibt_vorschlag(_vorschlag(vorschlag_art=None), {}, None, None)


# ── In der Analyse, auf einer geraden Strecke ────────────────────────────────

# Gerade Strecke nach Osten, 10 h Fahrt: die Lage eines Wegpunkts ist seine Zeit.
COORDS = [[9.0 + i * 0.01, 50.0] for i in range(1000)]
DAUER_S = 10 * 3600
ROUTE_M = haversine_m(9.0, 50.0, COORDS[-1][0], 50.0)


def _bei(stunden: float) -> tuple[float, float]:
    return (50.0, 9.0 + (COORDS[-1][0] - 9.0) * stunden * 3600 / DAUER_S)


@pytest.fixture
def lage(monkeypatch):
    lage: dict = {}
    monkeypatch.setattr(routing, "_waypoint_latlon", lambda wp: lage.get(wp.id))
    return lage


def _wp(lage, stunden, art, dauer, grund=None):
    wp = SimpleNamespace(id=uuid.uuid4(), type="technical_stop", halt_purpose=grund,
                         hold_duration_min=dauer, vorschlag_art=art)
    lage[wp.id] = _bei(stunden)
    return wp


def _frisch():
    halte, _ = routing.fuel_svc.halteplan(ROUTE_M / 1000, DAUER_S, COORDS, 0, [])
    return halte


def test_uebernommene_empfehlung_passt(lage):
    wps = [_wp(lage, h["after_drive_s"] / 3600, h["kind"], h["duration_min"]) for h in _frisch()]
    analyse = routing._halteanalyse(SimpleNamespace(waypoints=wps, convoy_vehicles=[]),
                                    ROUTE_M, COORDS, DAUER_S)
    assert analyse["neu_verteilen"] is None
    assert analyse["duration_halts"] == []


def test_verschobene_empfehlung_ist_veraltet(lage):
    """Jeder übernommene Halt eine Stunde zu spät — wie nach einem längeren Weg."""
    wps = [_wp(lage, h["after_drive_s"] / 3600 + 1, h["kind"], h["duration_min"]) for h in _frisch()]
    analyse = routing._halteanalyse(SimpleNamespace(waypoints=wps, convoy_vehicles=[]),
                                    ROUTE_M, COORDS, DAUER_S)
    assert analyse["neu_verteilen"]["veraltet"]
    assert set(analyse["neu_verteilen"]["veraltet"]) <= {str(w.id) for w in wps}
    assert analyse["neu_verteilen"]["neu"] > 0


def test_eigene_halte_zaehlen_beim_abgleich_mit(lage):
    """Ein selbst gesetzter Tankhalt ersetzt den ersten TH — ein übernommener TH
    an derselben Stelle wäre dann zu viel, aber er ist nicht veraltet: die frische
    Empfehlung rechnet mit dem Tankhalt und kennt den TH dort gar nicht."""
    tank = _wp(lage, 2, None, 20, "fuel")
    analyse = routing._halteanalyse(SimpleNamespace(waypoints=[tank], convoy_vehicles=[]),
                                    ROUTE_M, COORDS, DAUER_S)
    assert analyse["neu_verteilen"] is None


# ── Durch die App ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    marker = uuid.uuid4().hex[:8]
    linie = [[9.0 + i * 0.01, 50.0] for i in range(1000)]
    async with AsyncSessionLocal() as db:
        user = User(email=f"hv-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(
            name=f"Verband {marker}", owner_id=user.id, organization_id=org.id,
            start_point=from_shape(Point(*linie[0]), srid=4326),
            end_point=from_shape(Point(*linie[-1]), srid=4326),
        )
        fahrzeuge = [Vehicle(name=f"Fz{i} {marker}", owner_id=user.id) for i in range(3)]
        db.add_all([convoy, *fahrzeuge])
        await db.flush()
        db.add_all([ConvoyVehicle(convoy_id=convoy.id, vehicle_id=v.id, position=i)
                    for i, v in enumerate(fahrzeuge)])
        db.add(Route(convoy_id=convoy.id, distance_m=ROUTE_M, duration_s=DAUER_S,
                     geometry=from_shape(LineString(linie), srid=4326)))
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, org_id=org.id, convoy_id=convoy.id,
                              vehicle_ids=[v.id for v in fahrzeuge])

    nutzer = SimpleNamespace(id=ids.user_id, is_superadmin=False)
    app.dependency_overrides[get_current_user] = lambda: nutzer
    app.dependency_overrides[get_org_context] = lambda: (nutzer, SimpleNamespace(id=ids.org_id), "planer")
    yield ids
    app.dependency_overrides.clear()

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Waypoint).where(Waypoint.convoy_id == ids.convoy_id))
        await db.execute(delete(Route).where(Route.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id.in_(ids.vehicle_ids)))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id))
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _anlegen(client, convoy_id, stunden, art, dauer, grund=None, name=None):
    lat, lon = _bei(stunden)
    r = await client.post(f"/api/convoys/{convoy_id}/waypoints", json={
        "name": name or halte_vorschlag.NAME[art], "type": "technical_stop", "lat": lat, "lon": lon,
        "hold_duration_min": dauer, "halt_purpose": grund, "vorschlag_art": art,
        "pending_placement": True, "order_index": 99,
    })
    assert r.status_code in (200, 201), r.text
    return r.json()


async def test_die_marke_haelt_bis_jemand_den_halt_aendert(verband):
    async with _client() as client:
        wp = await _anlegen(client, verband.convoy_id, 2, "tech", 15)
        assert wp["vorschlag_art"] == "tech"
        url = f"/api/convoys/{verband.convoy_id}/waypoints/{wp['id']}"
        # Das Formular schickt alles mit; nur die Notiz ist neu.
        r = await client.put(url, json={"name": wp["name"], "type": "technical_stop",
                                        "hold_duration_min": 15, "notes": "hinter der Tankstelle"})
        assert r.json()["vorschlag_art"] == "tech"
        r = await client.put(url, json={"hold_duration_min": 30})
        assert r.json()["vorschlag_art"] is None


async def test_neu_verteilen_ersetzt_nur_veraltete_vorschlaege(verband):
    frisch = _frisch()
    async with _client() as client:
        # Alle Empfehlungen eine Stunde zu spät übernommen, dazu ein eigener Halt.
        alt = [await _anlegen(client, verband.convoy_id, h["after_drive_s"] / 3600 + 1, h["kind"],
                              h["duration_min"], "rest" if h["is_rest"] else None) for h in frisch]
        eigen = (await client.post(f"/api/convoys/{verband.convoy_id}/waypoints", json={
            "name": "Mittagessen", "type": "stop", "lat": _bei(9.5)[0], "lon": _bei(9.5)[1],
            "hold_duration_min": 0,
        })).json()

        geladen = (await client.get(f"/api/convoys/{verband.convoy_id}/route")).json()
        meldung = geladen["fuel_analysis"]["neu_verteilen"]
        assert meldung and set(meldung["veraltet"]) <= {w["id"] for w in alt}

        r = await client.post(f"/api/convoys/{verband.convoy_id}/halte/neu-verteilen")
        assert r.status_code == 200, r.text
        assert r.json() == {"entfernt": len(meldung["veraltet"]), "hinzugefuegt": meldung["neu"]}

        geladen = (await client.get(f"/api/convoys/{verband.convoy_id}/route")).json()
        assert geladen["fuel_analysis"]["neu_verteilen"] is None
        assert geladen["fuel_analysis"]["duration_halts"] == []

        # Ein zweiter Klick findet nichts mehr.
        r = await client.post(f"/api/convoys/{verband.convoy_id}/halte/neu-verteilen")
        assert r.json() == {"entfernt": 0, "hinzugefuegt": 0}

    async with AsyncSessionLocal() as db:
        wps = (await db.execute(select(Waypoint).where(Waypoint.convoy_id == verband.convoy_id))).scalars().all()
    namen = {str(w.id): w for w in wps}
    assert eigen["id"] in namen
    neue = [w for w in wps if str(w.id) not in {a["id"] for a in alt} and str(w.id) != eigen["id"]]
    assert neue and all(w.pending_placement and w.vorschlag_art for w in neue)
    assert all("km" not in w.name for w in neue)


async def test_ohne_route_gibt_es_nichts_zu_verteilen(verband):
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Route).where(Route.convoy_id == verband.convoy_id))
        await db.commit()
    async with _client() as client:
        r = await client.post(f"/api/convoys/{verband.convoy_id}/halte/neu-verteilen")
    assert r.status_code == 409


async def test_fremde_organisation_sieht_den_konvoi_nicht(verband):
    nutzer = SimpleNamespace(id=verband.user_id, is_superadmin=False)
    app.dependency_overrides[get_org_context] = lambda: (nutzer, SimpleNamespace(id=uuid.uuid4()), "admin")
    async with _client() as client:
        r = await client.post(f"/api/convoys/{verband.convoy_id}/halte/neu-verteilen")
    assert r.status_code == 404
