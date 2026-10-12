"""Geräteschlüssel und Bake: die Prüfwerte aus dem Protokoll, dann die Kennungen für die App.

Was hier zugesagt wird:

- Teilschlüssel, Kennung, Bake-Kennung und beide Signaturen ergeben **genau** die
  Prüfwerte aus ``docs/PROTOKOLL.md`` im Tracker-Repo („Prüfwerte"). Firmware, Simulator
  und Begleit-App rechnen gegen dieselben Werte; weicht einer ab, findet ihn dieser Test.
- Eine Signatur wird über die Bytes verglichen; ein Rahmen, an dem irgendetwas geändert
  ist, gilt nicht.
- Ein Schlüssel, der nicht mehr zu lesen ist, gilt als fehlend, nicht als Fehler.
- ``GET /api/track/{slug}/baken`` gibt je Fahrzeug des Konvois mit Tracker die Kennungen
  für voriges, laufendes und nächstes Fenster — nur am Fahrer-Link, nur Tracker der
  eigenen Organisation, ohne Gerätekennung.
"""
import base64
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models.convoy import ConvoyVehicle
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.share_link import ConvoyShareLink
from app.services import tracker_ble as tb
from tests.aktionsseite_fixtures import client, h, reset_db_engine  # noqa: F401
from tests.test_tracker_geraete import _anlegen, _einloesen, org  # noqa: F401

# ── Prüfwerte (PROTOKOLL.md) ───────────────────────────────────────────────

SCHLUESSEL = bytes(range(32))
INSTANZ = "https://einsatz.example.org"
GERAET = "5e0c8a52-6c1e-4b8e-9d3a-2f1e7c9b0a11"
KOERPER = (
    '{"netz":"ble","akku_prozent":84,"extern":false,'
    '"fixes":[{"t":"2026-10-12T08:14:10Z","lat":47.7981,"lon":11.0632}]}'
)
ANTWORT_KOERPER = {
    "angenommen": 1, "verworfen": 0, "modus": "senden", "intervall_s": 10, "buendel_s": 15,
    "nachfrage_s": 300, "lebenszeichen_s": 43200, "serverzeit": "2026-10-12T08:14:40Z", "firmware": None,
}


def _rahmen(**anders) -> tb.Rahmen:
    felder = {
        "geraet": GERAET, "seq": 4294967297, "art": "positionen", "instanz": INSTANZ,
        "nutzlast": base64.b64encode(KOERPER.encode()).decode(), "mac": "",
    }
    felder.update(anders)
    return tb.Rahmen(**felder)


class TestPruefwerte:
    def test_schluessel_als_base64(self):
        assert tb.als_base64(SCHLUESSEL) == "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="

    def test_kennung(self):
        assert tb.kennung(SCHLUESSEL) == "630dcd2966c43366"

    @pytest.mark.parametrize(
        "zweck,erwartet",
        [
            ("buendel", "39702700180f6f7d0372823510bf58d3212010f9b596ad00c1f2a327c1118729"),
            ("anweisung", "9b68280583e3f24961b4515939e2870383effcae39cc4097c5f2feef5de18dc0"),
            ("bake", "81220fcab2eb25df7076af7cf10c566c68968cf102f408f58536c416dd2b94e4"),
        ],
    )
    def test_teilschluessel(self, zweck, erwartet):
        assert tb.teilschluessel(SCHLUESSEL, zweck).hex() == erwartet

    def test_bake(self):
        zeit = datetime.fromtimestamp(1791800000, tz=timezone.utc)
        assert tb.fenster(zeit) == 1990888
        assert tb.bake_kennung(SCHLUESSEL, 1990888) == "475f44ce3e44c481"
        # Drei Fenster, das laufende in der Mitte.
        kennungen = tb.bake_kennungen(SCHLUESSEL, zeit)
        assert kennungen[1] == "475f44ce3e44c481"
        assert kennungen == [tb.bake_kennung(SCHLUESSEL, f) for f in (1990887, 1990888, 1990889)]

    def test_instanz_kurz(self):
        assert tb.instanz_kurz(INSTANZ) == "c41a"

    def test_rahmen_mac(self):
        assert tb.rahmen_mac(SCHLUESSEL, _rahmen()) == "qQYR+GMCUAB60CkvlFkuiuwNBhYwRChKAc+lSADbqjs="

    def test_antwort_mac(self):
        kodiert = tb.antwort_kodieren(200, ANTWORT_KOERPER)
        # Kompakt, ohne Leerzeichen — signiert wird genau dieser Text.
        assert base64.b64decode(kodiert).decode() == json.dumps(
            {"status": 200, "koerper": ANTWORT_KOERPER}, separators=(",", ":")
        )
        assert tb.antwort_mac(SCHLUESSEL, GERAET, 4294967297, kodiert) == "5A5Osnqq/jxzu9+JN2rseWRb6KDttJtEViRDbF2mE1k="
        antwort = tb.antwort(SCHLUESSEL, _rahmen(), 200, ANTWORT_KOERPER)
        assert antwort == {"seq": 4294967297, "antwort": kodiert, "mac": "5A5Osnqq/jxzu9+JN2rseWRb6KDttJtEViRDbF2mE1k="}


class TestRahmen:
    def test_echter_rahmen_gilt(self):
        r = _rahmen(mac="qQYR+GMCUAB60CkvlFkuiuwNBhYwRChKAc+lSADbqjs=")
        assert tb.rahmen_echt(SCHLUESSEL, r)
        assert tb.nutzlast_lesen(r) == json.loads(KOERPER)

    @pytest.mark.parametrize(
        "anders",
        [
            {"seq": 4294967298},
            {"art": "hallo"},
            {"instanz": "https://andere.example.org"},
            {"geraet": "5e0c8a52-6c1e-4b8e-9d3a-2f1e7c9b0a12"},
            {"nutzlast": base64.b64encode(KOERPER.replace("84", "85").encode()).decode()},
        ],
    )
    def test_jede_aenderung_bricht_die_signatur(self, anders):
        r = _rahmen(mac="qQYR+GMCUAB60CkvlFkuiuwNBhYwRChKAc+lSADbqjs=", **anders)
        assert not tb.rahmen_echt(SCHLUESSEL, r)

    @pytest.mark.parametrize("mac", ["", "kein base64!", base64.b64encode(b"\0" * 32).decode()])
    def test_falsche_signatur(self, mac):
        assert not tb.rahmen_echt(SCHLUESSEL, _rahmen(mac=mac))

    def test_anderer_schluessel(self):
        r = _rahmen(mac="qQYR+GMCUAB60CkvlFkuiuwNBhYwRChKAc+lSADbqjs=")
        assert not tb.rahmen_echt(bytes(32), r)

    @pytest.mark.parametrize(
        "roh",
        [
            None, [], "x",
            {"geraet": GERAET, "seq": "1", "art": "positionen", "instanz": INSTANZ, "nutzlast": "", "mac": ""},
            {"geraet": GERAET, "seq": True, "art": "positionen", "instanz": INSTANZ, "nutzlast": "", "mac": ""},
            {"geraet": GERAET, "seq": -1, "art": "positionen", "instanz": INSTANZ, "nutzlast": "", "mac": ""},
            {"geraet": GERAET, "seq": 2**53, "art": "positionen", "instanz": INSTANZ, "nutzlast": "", "mac": ""},
            {"geraet": GERAET, "seq": 1, "art": "firmware/ergebnis", "instanz": INSTANZ, "nutzlast": "", "mac": ""},
            {"geraet": GERAET, "seq": 1, "art": "einloesen", "instanz": INSTANZ, "nutzlast": "", "mac": ""},
            {"geraet": GERAET, "seq": 1, "art": "positionen", "instanz": INSTANZ, "nutzlast": "A" * 20000, "mac": ""},
            {"geraet": GERAET, "seq": 1, "art": "positionen", "instanz": INSTANZ, "mac": ""},
        ],
    )
    def test_unbrauchbare_rahmen(self, roh):
        assert tb.rahmen_lesen(roh) is None

    @pytest.mark.parametrize("nutzlast", ["kein base64!", base64.b64encode(b"[1,2]").decode(), base64.b64encode(b"\xff").decode()])
    def test_unbrauchbare_nutzlast(self, nutzlast):
        assert tb.nutzlast_lesen(_rahmen(nutzlast=nutzlast)) is None


class TestSchluessel:
    def test_ablegen_und_lesen(self):
        s = tb.schluessel_erzeugen()
        assert len(s) == 32
        abgelegt = tb.ablegen(s)
        # Nicht im Klartext in der Datenbank.
        assert tb.als_base64(s) not in abgelegt
        assert tb.schluessel_lesen(abgelegt) == s

    @pytest.mark.parametrize("abgelegt", [None, "", "kaputt", tb.als_base64(b"zu kurz")])
    def test_unlesbar_gilt_als_fehlend(self, abgelegt):
        assert tb.schluessel_lesen(abgelegt) is None

    @pytest.mark.parametrize(
        "daten,schluessel,erwartet",
        [
            ({}, None, False),  # alte Firmware: nie
            ({}, SCHLUESSEL, False),
            ({"schluessel_kennung": None}, SCHLUESSEL, False),
            ({"schluessel_kennung": ""}, SCHLUESSEL, True),  # Gerät ohne Schlüssel
            ({"schluessel_kennung": "0000000000000000"}, SCHLUESSEL, True),  # neu eingerichtet
            ({"schluessel_kennung": "630dcd2966c43366"}, SCHLUESSEL, False),  # passt
            ({"schluessel_kennung": ""}, None, True),
        ],
    )
    def test_angebot(self, daten, schluessel, erwartet):
        assert tb.angebot_noetig(tb.kennung_gemeldet(daten), schluessel) is erwartet


# ── Kennungen für die App ──────────────────────────────────────────────────


async def _link(convoy_id, user_id, scope: str = "driver", **extra) -> str:
    async with AsyncSessionLocal() as db:
        link = ConvoyShareLink(
            convoy_id=convoy_id, slug=f"b{uuid.uuid4().hex[:7]}", scope=scope, created_by_id=user_id, **extra
        )
        db.add(link)
        await db.commit()
        return link.slug


@pytest.fixture
async def links(org):  # noqa: F811
    yield org
    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyShareLink).where(ConvoyShareLink.convoy_id.in_([org.konvoi, org.zweiter])))
        await db.commit()


async def _schluessel(geraet_id) -> bytes:
    async with AsyncSessionLocal() as db:
        abgelegt = (await db.execute(select(Ortungsgeraet.schluessel).where(Ortungsgeraet.id == uuid.UUID(geraet_id)))).scalar_one()
    return tb.schluessel_lesen(abgelegt)


class TestBaken:
    async def test_kennungen_je_fahrzeug_mit_tracker(self, client, links):
        org = links
        geraet = await _anlegen(client, org)
        eingeloest = await _einloesen(client, geraet["code"])
        slug = await _link(org.konvoi, org.users[0])
        r = await client.get(f"/api/track/{slug}/baken")
        assert r.status_code == 200, r.text
        antwort = r.json()
        assert antwort["fenster_s"] == 900
        (bake,) = antwort["baken"]
        assert set(bake) == {"vehicle_id", "kennungen"}
        assert bake["vehicle_id"] == str(org.hlf)
        schluessel = base64.b64decode(eingeloest["schluessel"])
        assert await _schluessel(geraet["id"]) == schluessel
        jetzt = tb.fenster(datetime.now(timezone.utc))
        erlaubt = {tb.bake_kennung(schluessel, f) for f in range(jetzt - 2, jetzt + 3)}
        assert len(bake["kennungen"]) == 3 and set(bake["kennungen"]) <= erlaubt

    async def test_nur_eingerichtete_freigegebene_tracker_im_konvoi(self, client, links):
        org = links
        slug = await _link(org.konvoi, org.users[0])
        # Angelegt, aber nicht eingelöst: kein Schlüssel, keine Bake.
        geraet = await _anlegen(client, org)
        assert (await client.get(f"/api/track/{slug}/baken")).json()["baken"] == []
        await _einloesen(client, geraet["code"])
        assert len((await client.get(f"/api/track/{slug}/baken")).json()["baken"]) == 1
        # Gesperrt: weg.
        r = await client.put(
            f"/api/org/geraete/{geraet['id']}",
            json={"name": "Tracker HLF", "vehicle_id": str(org.hlf), "aktiv": False},
            headers=h(org.admin),
        )
        assert r.status_code == 200, r.text
        assert (await client.get(f"/api/track/{slug}/baken")).json()["baken"] == []

    async def test_fahrzeug_ausserhalb_des_konvois_fehlt(self, client, links):
        org = links
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == org.konvoi, ConvoyVehicle.vehicle_id == org.hlf))
            await db.commit()
        geraet = await _anlegen(client, org)
        await _einloesen(client, geraet["code"])
        slug = await _link(org.konvoi, org.users[0])
        assert (await client.get(f"/api/track/{slug}/baken")).json()["baken"] == []

    async def test_nur_am_fahrer_link(self, client, links):
        org = links
        geraet = await _anlegen(client, org)
        await _einloesen(client, geraet["code"])
        nur_sehen = await _link(org.konvoi, org.users[0], scope="track")
        widerrufen = await _link(org.konvoi, org.users[0], revoked=True)
        for slug in (nur_sehen, widerrufen, "gibtsnicht"):
            r = await client.get(f"/api/track/{slug}/baken")
            assert r.status_code == 404, slug

    async def test_passwort_braucht_das_sitzungstoken(self, client, links):
        from app.services import share_links as sl

        org = links
        geraet = await _anlegen(client, org)
        await _einloesen(client, geraet["code"])
        slug = await _link(org.konvoi, org.users[0], password_hash=sl.hash_password("geheim123"))
        assert (await client.get(f"/api/track/{slug}/baken")).status_code == 404
        r = await client.get(f"/api/track/{slug}/baken", headers={"X-Track-Token": sl.issue_session_token(slug)})
        assert r.status_code == 200 and len(r.json()["baken"]) == 1
        # Das Token eines anderen Links gilt hier nicht.
        r = await client.get(f"/api/track/{slug}/baken", headers={"X-Track-Token": sl.issue_session_token("anderer")})
        assert r.status_code == 404
