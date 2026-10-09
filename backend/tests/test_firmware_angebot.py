"""Firmware für Tracker: Manifest lesen, Angebot entscheiden, Image prüfen und verteilen.

Erst ohne Netz (Manifest, Angebot, Versionsordnung), dann die Ablage mit einem
``httpx.MockTransport`` und am Ende der Weg durch die App: ``hallo`` bietet an,
der Download kommt von der Instanz, mit ``Range``, nur mit Gerätetoken.
"""
import hashlib
import json

import httpx
import pytest

from app.services import firmware_angebot as fa
from app.services.firmware_angebot import Ablage, Manifest, angebot, manifest_lesen, version_tupel
from tests.aktionsseite_fixtures import client, h, reset_db_engine  # noqa: F401
from tests.test_tracker_geraete import _eingerichtet, org  # noqa: F401

BASIS = "https://firmware.example.org"
IMAGE = bytes(range(256)) * 16  # 4 KiB
SHA = hashlib.sha256(IMAGE).hexdigest()


def manifest(**felder) -> dict:
    return {"version": "0.2.0", "sha256": SHA, "groesse": len(IMAGE), "image": "0.2.0.bin", **felder}


# ── Ohne Netz ────────────────────────────────────────────────────────────────


def test_versionsordnung():
    assert version_tupel("0.1.0") < version_tupel("0.2.0-beta.1") < version_tupel("0.2.0-beta.2")
    assert version_tupel("0.2.0-beta.2") < version_tupel("0.2.0") < version_tupel("0.10.0")
    assert version_tupel("kaputt") < version_tupel("0.0.1")


def test_manifest_lesen_relativ_und_absolut():
    m = manifest_lesen(manifest(), f"{BASIS}/stable/")
    assert m == Manifest("0.2.0", SHA, len(IMAGE), f"{BASIS}/stable/0.2.0.bin", None)
    m = manifest_lesen(manifest(image="https://cdn.example.org/fw.bin", hardware="nrf9151-v1"), f"{BASIS}/stable")
    assert m.url == "https://cdn.example.org/fw.bin" and m.hardware == ("nrf9151-v1",)


@pytest.mark.parametrize(
    "roh",
    [
        manifest(version="2"),
        manifest(sha256="abc"),
        manifest(groesse=0),
        manifest(groesse=fa.MAX_IMAGE_BYTES + 1),
        manifest(groesse=True),
        manifest(image="http://unsicher.example.org/fw.bin"),
        manifest(image=""),
        manifest(hardware=[]),
        manifest(hardware=["ok", "../böse"]),
        "kein dict",
    ],
)
def test_unbrauchbare_manifeste(roh):
    assert manifest_lesen(roh, f"{BASIS}/stable/") is None


def test_angebot_nur_wenn_neuer_und_passend():
    m = manifest_lesen(manifest(hardware=["nrf9151-v1"]), f"{BASIS}/beta/")
    instanz = "https://einsatz.example.org/"
    a = angebot(m, "0.1.0", "nrf9151-v1", instanz, "beta")
    assert a == {
        "version": "0.2.0",
        "url": "https://einsatz.example.org/api/geraete/firmware/beta/0.2.0.bin",
        "sha256": SHA,
        "groesse": len(IMAGE),
    }
    assert angebot(m, "0.2.0", "nrf9151-v1", instanz, "beta") is None  # gleich alt
    assert angebot(m, "0.3.0", "nrf9151-v1", instanz, "beta") is None  # Gerät ist weiter
    assert angebot(m, "0.1.0", "simulator", instanz, "beta") is None  # andere Hardware
    assert angebot(m, None, "nrf9151-v1", instanz, "beta") is None  # Stand unbekannt
    assert angebot(None, "0.1.0", "nrf9151-v1", instanz, "beta") is None
    offen = manifest_lesen(manifest(), f"{BASIS}/beta/")
    assert angebot(offen, "0.1.0", "irgendwas", instanz, "beta") is not None


# ── Die Ablage ───────────────────────────────────────────────────────────────


class Ablagen:
    """Ein ``MockTransport`` mit Manifest und Image je Kanal, der mitzählt."""

    def __init__(self):
        self.dateien: dict[str, bytes] = {}
        self.aufrufe: list[str] = []
        self.kaputt = False

    def manifest(self, kanal: str, **felder):
        self.dateien[f"/{kanal}/manifest.json"] = json.dumps(manifest(**felder)).encode()
        self.dateien[f"/{kanal}/{felder.get('version', '0.2.0')}.bin"] = IMAGE

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.aufrufe.append(request.url.path)
        if self.kaputt:
            raise httpx.ConnectError("Ablage weg")
        inhalt = self.dateien.get(request.url.path)
        return httpx.Response(200, content=inhalt) if inhalt is not None else httpx.Response(404)


@pytest.fixture
def ablage(tmp_path):
    srv = Ablagen()
    uhr = [0.0]
    a = Ablage(BASIS, verzeichnis=tmp_path, uhr=lambda: uhr[0], transport=httpx.MockTransport(srv.handler))
    a.srv, a.uhr = srv, uhr
    return a


async def test_manifest_wird_eine_stunde_zwischengespeichert(ablage):
    ablage.srv.manifest("stable")
    assert (await ablage.manifest("stable")).version == "0.2.0"
    ablage.uhr[0] += fa.MANIFEST_TTL_S - 1
    await ablage.manifest("stable")
    assert ablage.srv.aufrufe.count("/stable/manifest.json") == 1
    ablage.uhr[0] += 2
    await ablage.manifest("stable")
    assert ablage.srv.aufrufe.count("/stable/manifest.json") == 2


async def test_ausfall_der_ablage_behaelt_den_letzten_stand(ablage):
    ablage.srv.manifest("stable")
    await ablage.manifest("stable")
    ablage.uhr[0] += fa.MANIFEST_TTL_S + 1
    ablage.srv.kaputt = True
    assert (await ablage.manifest("stable")).version == "0.2.0"
    # … und fragt nicht bei jedem Gerät erneut.
    await ablage.manifest("stable")
    assert ablage.srv.aufrufe.count("/stable/manifest.json") == 2


async def test_kanal_ohne_image_ist_kein_fehler(ablage):
    assert await ablage.manifest("beta") is None
    assert await ablage.manifest("unbekannt") is None
    assert not Ablage("").aktiv and await Ablage("").manifest("stable") is None


async def test_image_wird_geholt_geprueft_und_nur_einmal_geladen(ablage):
    ablage.srv.manifest("stable")
    pfad = await ablage.datei("stable", "0.2.0")
    assert pfad is not None and pfad.read_bytes() == IMAGE
    assert await ablage.datei("stable", "0.2.0") == pfad
    assert ablage.srv.aufrufe.count("/stable/0.2.0.bin") == 1
    # Nur, was das Manifest nennt.
    assert await ablage.datei("stable", "0.9.9") is None


async def test_falsche_pruefsumme_wird_nicht_bereitgestellt(ablage):
    ablage.srv.manifest("stable", sha256="0" * 64)
    assert await ablage.datei("stable", "0.2.0") is None
    assert list(ablage.verzeichnis.rglob("*")) == [ablage.verzeichnis / "stable"] or not list(
        ablage.verzeichnis.rglob("*.bin")
    )


async def test_falsche_groesse_wird_nicht_bereitgestellt(ablage):
    ablage.srv.manifest("stable", groesse=len(IMAGE) - 1)
    assert await ablage.datei("stable", "0.2.0") is None
    ablage.leeren()
    ablage.srv.manifest("stable", groesse=len(IMAGE) + 1)
    assert await ablage.datei("stable", "0.2.0") is None


# ── Durch die App ────────────────────────────────────────────────────────────


@pytest.fixture
def instanz_ablage(ablage, monkeypatch):
    monkeypatch.setattr(fa, "ablage", ablage)
    monkeypatch.setattr(fa.settings, "app_base_url", "https://einsatz.example.org")
    return ablage


async def test_hallo_bietet_neuere_firmware_von_dieser_instanz_an(client, org, instanz_ablage):
    instanz_ablage.srv.manifest("stable", hardware=["nrf9151-v1", "simulator"])
    geraet, kopf = await _eingerichtet(client, org)
    r = await client.post("/api/geraete/hallo", json={"firmware": "0.1.0"}, headers=kopf)
    assert r.json()["firmware"] == {
        "version": "0.2.0",
        "url": "https://einsatz.example.org/api/geraete/firmware/stable/0.2.0.bin",
        "sha256": SHA,
        "groesse": len(IMAGE),
    }
    # Der Org-Admin sieht, was angeboten wird.
    zeile = (await client.get("/api/org/geraete", headers=h(org.admin))).json()[0]
    assert zeile["angebot_version"] == "0.2.0"
    # Mit dem neuen Stand gibt es nichts mehr.
    r = await client.post("/api/geraete/hallo", json={"firmware": "0.2.0"}, headers=kopf)
    assert r.json()["firmware"] is None


async def test_anderer_kanal_anderes_angebot(client, org, instanz_ablage):
    instanz_ablage.srv.manifest("beta", version="0.3.0-beta.1")
    geraet, kopf = await _eingerichtet(client, org)
    assert (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()["firmware"] is None
    r = await client.put(
        f"/api/org/geraete/{geraet['id']}",
        json={"name": "Tracker HLF", "vehicle_id": str(org.hlf), "kanal": "beta", "aktiv": True},
        headers=h(org.admin),
    )
    assert r.status_code == 200
    r = await client.post("/api/geraete/hallo", json={}, headers=kopf)
    assert r.json()["firmware"]["version"] == "0.3.0-beta.1"


async def test_download_nur_mit_token_mit_range_und_nur_bekannte_version(client, org, instanz_ablage):
    instanz_ablage.srv.manifest("stable")
    _, kopf = await _eingerichtet(client, org)
    assert (await client.get("/api/geraete/firmware/stable/0.2.0.bin")).status_code == 401
    r = await client.get("/api/geraete/firmware/stable/0.2.0.bin", headers=kopf)
    assert r.status_code == 200 and r.content == IMAGE
    assert r.headers["accept-ranges"] == "bytes"
    r = await client.get("/api/geraete/firmware/stable/0.2.0.bin", headers={**kopf, "Range": "bytes=1024-2047"})
    assert r.status_code == 206 and r.content == IMAGE[1024:2048]
    for pfad in ("stable/0.9.9.bin", "alpha/0.2.0.bin", "stable/..%2F..%2Fetc.bin"):
        r = await client.get(f"/api/geraete/firmware/{pfad}", headers=kopf)
        assert r.status_code == 404, pfad


async def test_ohne_ablage_kein_angebot(client, org, monkeypatch):
    monkeypatch.setattr(fa, "ablage", Ablage(""))
    _, kopf = await _eingerichtet(client, org)
    r = await client.post("/api/geraete/hallo", json={"firmware": "0.0.1"}, headers=kopf)
    assert r.status_code == 200 and r.json()["firmware"] is None
