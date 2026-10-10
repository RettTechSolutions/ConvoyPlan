"""Die Instanz verteilt Wurzelzertifikate an ihre Tracker (E13 im Tracker-Plan).

Erst die Regeln ohne Datenbank (``services/tracker_wurzeln.py``): was als Bündel
gilt, wie der Fingerabdruck entsteht, wann angeboten wird. Dann der Weg durch die
App: ``hallo`` mit und ohne Fingerabdruck, und die Tracker-Liste im Org-Admin.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.config import settings
from app.services import tracker_wurzeln as tw
from tests.aktionsseite_fixtures import client, h, reset_db_engine  # noqa: F401
from tests.test_tracker_geraete import _eingerichtet, org  # noqa: F401


def _zert(name: str, ca: bool = True) -> tuple[str, bytes]:
    schluessel = ec.generate_private_key(ec.SECP256R1())
    subjekt = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    jetzt = datetime.now(timezone.utc)
    zert = (
        x509.CertificateBuilder()
        .subject_name(subjekt)
        .issuer_name(subjekt)
        .public_key(schluessel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(jetzt - timedelta(days=1))
        .not_valid_after(jetzt + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(schluessel, hashes.SHA256())
    )
    return zert.public_bytes(serialization.Encoding.PEM).decode(), zert.public_bytes(serialization.Encoding.DER)


ALT_PEM, ALT_DER = _zert("Alte Einsatz-CA")
NEU_PEM, NEU_DER = _zert("Neue Einsatz-CA")
LEER = hashlib.sha256(b"").hexdigest()


class TestBuendel:
    def test_fingerabdruck_haengt_nicht_an_reihenfolge_oder_schreibweise(self):
        a = tw.lesen(ALT_PEM + NEU_PEM)
        b = tw.lesen("\n\n" + NEU_PEM.replace("\n", "\r\n") + "\n" + ALT_PEM)
        assert a.sha256 == b.sha256
        erwartet = hashlib.sha256(
            "\n".join(sorted(hashlib.sha256(d).hexdigest() for d in (ALT_DER, NEU_DER))).encode()
        ).hexdigest()
        assert a.sha256 == erwartet

    def test_leere_datei_heisst_keine_eigenen_wurzeln(self):
        b = tw.lesen("")
        assert b.pem == () and b.sha256 == LEER

    @pytest.mark.parametrize(
        ("text", "meldung"),
        [
            (ALT_PEM + NEU_PEM + _zert("c")[0] + _zert("d")[0], "höchstens 3"),
            (_zert("Server", ca=False)[0], "keine Zertifizierungsstelle"),
            (ALT_PEM + ALT_PEM, "doppelt"),
            (ALT_PEM + "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n", "etwas anderes"),
            ("-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n", "nicht lesbar"),
        ],
    )
    def test_ungueltig(self, text, meldung):
        with pytest.raises(ValueError, match=meldung):
            tw.lesen(text)


class TestAngebot:
    def test_nur_bei_abweichung(self):
        b = tw.lesen(ALT_PEM)
        assert tw.angebot(b.sha256, b) is None
        angebot = tw.angebot(LEER, b)
        assert angebot == {"sha256": b.sha256, "pem": list(b.pem)}

    def test_nie_ohne_gemeldeten_fingerabdruck(self):
        # Alte Firmware kennt das Feld nicht; ihr 12 KB anzuhängen, hülfe niemandem.
        assert tw.angebot(None, tw.lesen(ALT_PEM)) is None

    def test_nie_ohne_einstellung(self):
        assert tw.angebot(LEER, None) is None

    def test_aktuell(self):
        b = tw.lesen(ALT_PEM)
        assert tw.aktuell(b.sha256, b) is True
        assert tw.aktuell(None, b) is False
        assert tw.aktuell(LEER, None) is None

    @pytest.mark.parametrize("wert", [None, 42, "", "abc", "g" * 64, LEER + "0"])
    def test_unbrauchbarer_fingerabdruck_gilt_als_nicht_gemeldet(self, wert):
        assert tw.gemeldet_lesen({"wurzeln_sha256": wert}) is None

    def test_grossbuchstaben_werden_angenommen(self):
        assert tw.gemeldet_lesen({"wurzeln_sha256": LEER.upper()}) == LEER


@pytest.fixture
def datei(tmp_path, monkeypatch):
    pfad = tmp_path / "tracker-wurzeln.pem"
    monkeypatch.setattr(settings, "tracker_wurzeln", str(pfad))
    yield pfad
    monkeypatch.setattr(settings, "tracker_wurzeln", "")
    tw.gewuenscht()


class TestEinstellung:
    def test_nicht_gesetzt(self, monkeypatch):
        monkeypatch.setattr(settings, "tracker_wurzeln", "")
        assert tw.gewuenscht() is None

    def test_datei_wird_bei_aenderung_neu_gelesen(self, datei):
        datei.write_text(ALT_PEM)
        assert tw.gewuenscht().sha256 == tw.lesen(ALT_PEM).sha256
        datei.write_text(ALT_PEM + NEU_PEM)
        assert tw.gewuenscht().sha256 == tw.lesen(ALT_PEM + NEU_PEM).sha256

    def test_ungueltige_oder_fehlende_datei_verteilt_nichts(self, datei, caplog):
        assert tw.gewuenscht() is None
        datei.write_text(_zert("Server", ca=False)[0])
        assert tw.gewuenscht() is None
        assert "keine Wurzeln verteilt" in caplog.text


class TestDurchDieApp:
    async def test_hallo_bietet_an_bis_das_geraet_uebernimmt(self, client, org, datei):
        datei.write_text(ALT_PEM + NEU_PEM)
        soll = tw.lesen(ALT_PEM + NEU_PEM)
        geraet, kopf = await _eingerichtet(client, org)

        async def zeile() -> dict:
            liste = (await client.get("/api/org/geraete", headers=h(org.admin))).json()
            return next(z for z in liste if z["id"] == geraet["id"])

        assert (await zeile())["wurzeln_aktuell"] is False

        r = await client.post("/api/geraete/hallo", json={"wurzeln_sha256": LEER}, headers=kopf)
        assert r.status_code == 200
        assert r.json()["wurzeln"] == {"sha256": soll.sha256, "pem": list(soll.pem)}
        assert (await zeile())["wurzeln_aktuell"] is False

        r = await client.post("/api/geraete/hallo", json={"wurzeln_sha256": soll.sha256}, headers=kopf)
        assert r.json()["wurzeln"] is None
        assert (await zeile())["wurzeln_aktuell"] is True

        # Ein Bündel ohne Fingerabdruck ändert am gemerkten Stand nichts, und
        # `positionen` trägt nie ein Angebot.
        r = await client.post("/api/geraete/positionen", json={"fixes": []}, headers=kopf)
        assert "wurzeln" not in r.json()
        await client.post("/api/geraete/hallo", json={"grund": "lebenszeichen"}, headers=kopf)
        assert (await zeile())["wurzeln_aktuell"] is True

        # Zweiter Schritt des Wechsels: das Bündel wird gekürzt, das Gerät ist
        # wieder veraltet, bis es {neu} übernommen hat.
        datei.write_text(NEU_PEM)
        assert (await zeile())["wurzeln_aktuell"] is False
        r = await client.post("/api/geraete/hallo", json={"wurzeln_sha256": soll.sha256}, headers=kopf)
        assert r.json()["wurzeln"]["sha256"] == tw.lesen(NEU_PEM).sha256

    async def test_ohne_einstellung_bleibt_alles_wie_bisher(self, client, org, monkeypatch):
        monkeypatch.setattr(settings, "tracker_wurzeln", "")
        geraet, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/hallo", json={"wurzeln_sha256": LEER}, headers=kopf)
        assert r.json()["wurzeln"] is None
        liste = (await client.get("/api/org/geraete", headers=h(org.admin))).json()
        assert next(z for z in liste if z["id"] == geraet["id"])["wurzeln_aktuell"] is None
