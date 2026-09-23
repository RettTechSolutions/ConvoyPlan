"""Die Betriebsstoffmeldung über den echten Fahrer-WebSocket.

Die Tests in ``test_betriebsstoff.py`` rufen die Verarbeitung direkt auf. Das
reicht nicht: Beim Zusammenführen mit #536 wurde die Variable der Frame-Weiche
umbenannt, der Betriebsstoff-Zweig las weiter die alte — jeder solche Frame
hätte die Verbindung mit einem ``NameError`` gekappt, und kein Test sah es.
Hier geht der Frame deshalb durch ``track_ws`` selbst — mit und ohne
Quittung.
"""

from app.database import AsyncSessionLocal
from app.models.convoy import ConvoyVehicle
from tests.test_track_ws_ack import (  # noqa: F401 — Fixtures, per Import aktiviert
    _sprich,
    _status,
    frische_belegungen,
    frische_quittungen,
    gesendet,
    reset_db_engine,
    verband,
)


def _betriebsstoff(ids, **werte) -> dict:
    return {"type": "betriebsstoff", "vehicle_id": str(ids.vehicle_id), **werte}


async def _cv(ids) -> ConvoyVehicle:
    async with AsyncSessionLocal() as db:
        return await db.get(ConvoyVehicle, (ids.convoy_id, ids.vehicle_id))


async def test_die_meldung_kommt_ueber_den_fahrer_link_an(verband, gesendet):
    # Danach noch ein Status: Die Verbindung muss die Betriebsstoffmeldung
    # überstehen, sonst ginge alles Folgende verloren.
    ws = await _sprich(
        verband.fahrer,
        [_betriebsstoff(verband, verbrauch=30, tank=200, fuellstand=40), _status(verband)],
    )

    cv = await _cv(verband)
    assert (cv.betriebsstoff_verbrauch, cv.betriebsstoff_tank, cv.betriebsstoff_fuellstand) == (30.0, 200, 40)
    assert [f["type"] for f in gesendet] == ["betriebsstoff_update", "status_update"]
    assert [a["frame"] for a in ws.acks()] == ["status"]


async def test_ein_fremd_belegtes_fahrzeug_meldet_keinen_betriebsstoff(verband, gesendet):
    await _sprich(verband.fahrer, [_status(verband, client_id="a")], client="geraet-anderes")
    gesendet.clear()

    ws = await _sprich(verband.fahrer, [_betriebsstoff(verband, fuellstand=10)])

    assert {"type": "belegung_abgelehnt", "vehicle_id": str(verband.vehicle_id)} in ws.sent
    assert gesendet == []
    assert (await _cv(verband)).betriebsstoff_fuellstand is None


async def test_ein_lese_link_meldet_keinen_betriebsstoff(verband, gesendet):
    await _sprich(verband.leser, [_betriebsstoff(verband, fuellstand=10)])

    assert gesendet == []
    assert (await _cv(verband)).betriebsstoff_fuellstand is None


# ── Quittung ─────────────────────────────────────────────────────────────────


async def test_der_server_kuendigt_die_betriebsstoff_quittung_eigens_an(verband, gesendet):
    """Nicht nur „ack": Ein Server, der Status und Stärke quittiert, den
    Betriebsstoff aber nicht kennt, sagte das auch — und die App wartete auf
    eine Quittung, die nie kommt."""
    ws = await _sprich(verband.fahrer, [])

    [hello] = [f for f in ws.sent if f.get("type") == "hello"]
    assert "ack-betriebsstoff" in hello["features"]


async def test_die_meldung_wird_dem_absender_quittiert(verband, gesendet):
    ws = await _sprich(
        verband.fahrer,
        [_betriebsstoff(verband, verbrauch=28.46, tank=200, fuellstand=40, client_id="b1")],
    )

    [ack] = ws.acks()
    assert (ack["client_id"], ack["frame"], ack["result"]) == ("b1", "betriebsstoff", "ok")
    # Was angekommen ist, wie der Server es abgelegt hat — samt Rundung.
    assert ack["applied"] == {"verbrauch": 28.5, "tank": 200, "fuellstand": 40}
    assert ack["ts"]
    # Die Quittung geht nur an den Absender; der Broadcast bleibt, wie er war.
    assert [f["type"] for f in gesendet] == ["betriebsstoff_update"]


async def test_eine_unplausible_meldung_wird_mit_grund_abgelehnt(verband, gesendet):
    ws = await _sprich(verband.fahrer, [_betriebsstoff(verband, fuellstand=140, client_id="b2")])

    assert ws.acks() == [{"type": "ack", "client_id": "b2", "frame": "betriebsstoff",
                          "result": "rejected", "reason": "invalid-betriebsstoff"}]
    assert gesendet == []


async def test_eine_wiederholte_meldung_wird_nicht_zweimal_verarbeitet(verband, gesendet):
    frame = _betriebsstoff(verband, fuellstand=40, client_id="b3")
    ws = await _sprich(verband.fahrer, [frame, dict(frame)])

    assert [a["result"] for a in ws.acks()] == ["ok", "ok"]
    assert [f["type"] for f in gesendet] == ["betriebsstoff_update"]


async def test_ohne_client_id_bleibt_es_beim_echo(verband, gesendet):
    ws = await _sprich(verband.fahrer, [_betriebsstoff(verband, fuellstand=40)])

    assert ws.acks() == []
    assert [f["type"] for f in gesendet] == ["betriebsstoff_update"]
