"""Aktionsseite: Absendernamen abschaltbar (Plan § 14.4).

„von Jonas“ auf der Karte des Bots hilft der Presse beim Nachfragen. Wer das
nicht will, schaltet es je Seite ab: dann speichert ConvoyPlan keinen Namen
mehr, und die schon gespeicherten der Seite gehen beim Abschalten.
"""
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    h,
    reset_db_engine,
    seite_anlegen,
)
from tests.test_aktionsseite_telegram import (  # noqa: F401 — Fixtures und Helfer
    _beitraege,
    _foto,
    _nachricht,
    _update,
    _verbunden,
    seite,
    telegram,
)


async def _absender(client, aktion, seite_id, an: bool) -> dict:
    r = await client.put(
        f"/api/org/aktionsseiten/{seite_id}",
        json={
            "title": "Weihnachtskonvois 2026", "theme": "weihnachten", "delay_minutes": 120,
            "show_sender": an,
            "convoys": [{"convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Bosnien"}],
        },
        headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text
    return r.json()


def _karten(telegram) -> list[str]:
    return [d["text"] for d in telegram.gesendet("sendMessage") if "Beitrag" in d["text"] or "Link" in d["text"]]


async def test_standard_nennt_den_absender(aktion, client, seite, telegram):
    r = await client.get("/api/org/aktionsseiten", headers=h(aktion.admin))
    assert r.json()[0]["show_sender"] is True
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="Grenze"))
    [post] = await _beitraege(seite)
    assert post.sender_name == "Person7"
    assert "· von Person7" in _karten(telegram)[-1]


async def test_abgeschaltet_kein_name_und_die_alten_gehen(aktion, client, seite, telegram):
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="vorher"))
    assert (await _beitraege(seite))[0].sender_name == "Person7"

    assert (await _absender(client, aktion, seite, False))["show_sender"] is False
    assert [p.sender_name for p in await _beitraege(seite)] == [None]

    await _update("message", _foto(caption="nachher", von=8))
    await _update("message", _nachricht("https://www.instagram.com/p/Abc/", von=9))
    assert [p.sender_name for p in await _beitraege(seite)] == [None, None, None]
    for karte in _karten(telegram)[-2:]:
        assert "von Person" not in karte
    # Die Beitragsliste im Org-Admin nennt ihn dann auch nicht.
    r = await client.get(f"/api/org/aktionsseiten/{seite}/beitraege", headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    assert {b["sender_name"] for b in r.json()} == {None}


async def test_wieder_an_gilt_nur_fuer_neue(aktion, client, seite, telegram):
    await _absender(client, aktion, seite, False)
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="still"))
    await _absender(client, aktion, seite, True)
    await _update("message", _foto(caption="laut", von=8))
    namen = {p.text_public: p.sender_name for p in await _beitraege(seite)}
    assert namen == {"still": None, "laut": "Person8"}

