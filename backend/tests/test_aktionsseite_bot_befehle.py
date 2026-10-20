"""Aktionsseite: der Bot bringt seine Befehle mit.

Nach dem Einrichten bietet Telegram beim Tippen von „/“ genau die Befehle an,
die der Bot dort versteht: ``/presse`` im Privatchat, ``/verbinden`` und
``/ab`` in der Gruppe. Gesetzt wird beim Eintragen im Org-Admin und beim Start
der Abholschleife (für Bots von vor dieser Fassung). Scheitert das, bleibt das
Einrichten trotzdem gelungen — getippt gehen die Befehle auch so.
"""
import re

from app.services import aktionsseite_telegram as tg
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    h,
    reset_db_engine,
    seite_anlegen,
)
from tests.test_aktionsseite_telegram import (  # noqa: F401 — Fixtures und Helfer
    TOKEN,
    seite,
    telegram,
)


def _befehle(telegram) -> dict[str, list[str]]:
    return {
        d["scope"]["type"]: [c["command"] for c in d["commands"]]
        for d in telegram.gesendet("setMyCommands")
    }


def test_befehle_sind_gueltig_fuer_telegram():
    for befehle in tg.BEFEHLE.values():
        for name, text_ in befehle:
            assert re.fullmatch(r"[a-z0-9_]{1,32}", name), name
            assert 3 <= len(text_) <= 256, name


async def test_eintragen_legt_die_befehle_je_ort_ab(aktion, client, telegram):
    r = await client.put("/api/org/aktionsseiten/telegram", json={"token": TOKEN}, headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    assert _befehle(telegram) == {
        "all_private_chats": ["presse"],
        "all_group_chats": ["verbinden", "ab"],
    }


async def test_angebotene_befehle_versteht_der_bot_auch(aktion, seite, telegram):
    """Ein Befehl in der Liste, den der Bot nicht kennt, wäre schlimmer als keine Liste."""
    from tests.test_aktionsseite_telegram import _nachricht, _update

    await _update("message", _nachricht("/presse", chat=901, von=901, typ="private"))
    assert "unbekannt oder abgelaufen" in telegram.gesendet("sendMessage")[-1]["text"]
    await _update("message", _nachricht("/verbinden"))
    assert "unbekannt oder abgelaufen" in telegram.gesendet("sendMessage")[-1]["text"]
    await _update("message", _nachricht("/ab 18:00"))
    assert telegram.gesendet("sendMessage")[-1]["text"] == tg.TEXT_AB_HILFE


async def test_scheitern_der_befehle_haelt_das_einrichten_nicht_auf(aktion, client, telegram):
    telegram.fehler["setMyCommands"] = (400, "Bad Request: BOT_COMMAND_INVALID")
    r = await client.put("/api/org/aktionsseiten/telegram", json={"token": TOKEN}, headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "bereit"


async def test_bestehender_bot_bekommt_sie_beim_start(aktion, seite, telegram):
    assert _befehle(telegram) == {}
    await tg._befehle_fuer(aktion.org_id)
    assert set(_befehle(telegram)) == {"all_private_chats", "all_group_chats"}
