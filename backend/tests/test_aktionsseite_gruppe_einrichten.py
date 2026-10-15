"""Aktionsseite: der Bot richtet die Gruppe ein und holt die Leute ab.

Gegen die gestellte Bot-API aus ``test_aktionsseite_telegram.py``. Zusagen:

- Nach ``/verbinden`` stehen Beschreibung und Gruppenbild, die Anleitung ist
  angeheftet. Den Titel fasst der Bot nicht an, ein Thema richtet er nicht ein.
- Fehlen Rechte, sagt er welche, und holt es nach, sobald er Admin wird.
- Kommt er in eine fremde Gruppe, erklärt er, wie man ihn verbindet.
- Neue Mitglieder erfahren, was mit ihren Fotos geschieht — einmal, nicht bei
  jedem Beitritt, und die vorige Begrüßung verschwindet.
"""
import io

from PIL import Image

from app.services import aktionsseite_gruppe as gruppe
from app.services import aktionsseite_telegram as tg
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    reset_db_engine,
    seite_anlegen,
)
from tests.test_aktionsseite_telegram import (  # noqa: F401 — Fixtures und Helfer
    GRUPPE,
    _nachricht,
    _update,
    _verbunden,
    seite,
    telegram,
)

KEINE_RECHTE = (400, "Bad Request: not enough rights to change chat description")


def _mitglied(vorher: str, jetzt: str, chat: int = GRUPPE) -> dict:
    return {
        "chat": {"id": chat, "type": "supergroup", "title": "Weihnachtskonvoi 2026"},
        "from": {"id": 7, "is_bot": False, "first_name": "Person7"},
        "date": 0,
        "old_chat_member": {"status": vorher, "user": {"id": 42, "is_bot": True}},
        "new_chat_member": {"status": jetzt, "user": {"id": 42, "is_bot": True}},
    }


def _texte(telegram) -> list[str]:
    return [d["text"] for d in telegram.gesendet("sendMessage")]


# ── Ohne Telegram ──────────────────────────────────────────────────────────


def test_beschreibung_passt_auch_mit_langen_namen():
    text_ = gruppe.beschreibung("W" * 120, "K" * 100, 120)
    assert len(text_) <= gruppe.BESCHREIBUNG_MAX
    assert "mindestens 120 Minuten" in text_


def test_kuerzel_laesst_das_fuellwort_weg():
    assert gruppe.kuerzel("Konvoi Albanien") == "A"
    assert gruppe.kuerzel("Hilfskonvoi Rumänien Süd") == "RS"
    assert gruppe.kuerzel("Konvoi") == "K"
    assert gruppe.kuerzel("—") == "?"


def test_gruppenbild_ist_ein_quadrat_in_der_konvoifarbe():
    bild = Image.open(io.BytesIO(gruppe.gruppenbild("Konvoi Albanien", "#1E6FD9")))
    assert bild.format == "JPEG" and bild.size == (640, 640)
    r, g, b = bild.getpixel((10, 10))
    assert abs(r - 0x1E) < 8 and abs(g - 0x6F) < 8 and abs(b - 0xD9) < 8
    # Ungültige Farbe: die Vorgabe statt eines Fehlers.
    Image.open(io.BytesIO(gruppe.gruppenbild("X", "rot")))


# ── Beim Verbinden ─────────────────────────────────────────────────────────


async def test_verbinden_richtet_die_gruppe_ein(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    [beschreibung] = telegram.gesendet("setChatDescription")
    assert beschreibung["chat_id"] == GRUPPE
    assert "Weihnachtskonvois 2026" in beschreibung["description"]
    [bild] = telegram.gesendet("setChatPhoto")
    assert b"\xff\xd8\xff" in bild["multipart"]  # ein JPEG, hochgeladen
    [anheften] = telegram.gesendet("pinChatMessage")
    anleitung = [m for m in telegram.gesendet("sendMessage") if m["text"].startswith("Verbunden mit")]
    assert anheften["disable_notification"] is True
    # Angeheftet wird die Anleitung, also die Antwort auf /verbinden.
    assert anheften["message_id"] == telegram.naechste_id and len(anleitung) == 1
    assert telegram.gesendet("setChatTitle") == []
    assert not any("Adminrechte" in t for t in _texte(telegram))


async def test_ein_thema_wird_nicht_eingerichtet(aktion, seite, telegram):
    await _verbunden(aktion, seite, thema=55)
    for methode in ("setChatDescription", "setChatPhoto", "pinChatMessage"):
        assert telegram.gesendet(methode) == []


async def test_ohne_rechte_sagt_er_welche_und_holt_es_als_admin_nach(aktion, seite, telegram):
    for methode in ("setChatDescription", "setChatPhoto"):
        telegram.fehler[methode] = KEINE_RECHTE
    telegram.fehler["pinChatMessage"] = (400, "Bad Request: not enough rights to manage pinned messages in the chat")
    await _verbunden(aktion, seite)
    hinweis = _texte(telegram)[-1]
    assert "Adminrechte (Gruppeninfo ändern, Nachrichten anheften)" in hinweis

    telegram.fehler.clear()
    await _update("my_chat_member", _mitglied("member", "administrator"))
    assert _texte(telegram)[-1].startswith("Verbunden mit")
    assert len(telegram.gesendet("setChatDescription")) == 2
    assert telegram.gesendet("pinChatMessage")[-1]["message_id"] == telegram.naechste_id


async def test_andere_fehler_halten_das_verbinden_nicht_auf(aktion, seite, telegram):
    telegram.fehler["setChatPhoto"] = (429, "Too Many Requests: retry after 5")
    await _verbunden(aktion, seite)
    assert any(t.startswith("Verbunden mit") for t in _texte(telegram))
    assert telegram.gesendet("pinChatMessage")
    assert not any("Adminrechte" in t for t in _texte(telegram))


async def test_admin_in_einer_unverbundenen_gruppe_aendert_nichts(aktion, seite, telegram):
    await _update("my_chat_member", _mitglied("member", "administrator", chat=-100999))
    assert telegram.gesendet("setChatDescription") == []
    assert telegram.gesendet("sendMessage") == []


# ── Abholen ────────────────────────────────────────────────────────────────


async def test_in_einer_neuen_gruppe_erklaert_er_das_verbinden(aktion, seite, telegram):
    telegram.liest_alles = False
    await _update("my_chat_member", _mitglied("left", "member", chat=-100999))
    [text_] = _texte(telegram)
    assert "/verbinden CODE" in text_ and "Org-Admin" in text_
    assert "/setprivacy" in text_


async def test_als_admin_hinzugefuegt_braucht_es_keinen_privacy_hinweis(aktion, seite, telegram):
    telegram.liest_alles = False
    await _update("my_chat_member", _mitglied("left", "administrator", chat=-100999))
    assert "/setprivacy" not in _texte(telegram)[-1]


async def test_neue_mitglieder_werden_begruesst_einmal_je_minute(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    neu = [{"id": 11, "is_bot": False, "first_name": "Anna"}, {"id": 12, "is_bot": True, "first_name": "Bot"}]
    await _update("message", _nachricht(new_chat_members=neu))
    begruessung = _texte(telegram)[-1]
    assert begruessung.startswith("Willkommen, Anna!")
    assert "„Weihnachtskonvois 2026“" in begruessung and "Wer das nicht möchte" in begruessung
    erste = telegram.naechste_id

    vorher = len(_texte(telegram))
    await _update("message", _nachricht(new_chat_members=[{"id": 13, "is_bot": False, "first_name": "Ben"}]))
    assert len(_texte(telegram)) == vorher

    # Eine Minute später: neue Begrüßung, die alte verschwindet.
    zeit, mid = tg._willkommen[GRUPPE]
    tg._willkommen[GRUPPE] = (zeit - 61, mid)
    await _update("message", _nachricht(new_chat_members=[{"id": 14, "is_bot": False, "first_name": "Cem"}]))
    assert _texte(telegram)[-1].startswith("Willkommen, Cem!")
    assert telegram.gesendet("deleteMessage") == [{"chat_id": GRUPPE, "message_id": erste}]


async def test_ohne_verbindung_keine_begruessung(aktion, seite, telegram):
    await _update("message", _nachricht(new_chat_members=[{"id": 11, "is_bot": False, "first_name": "Anna"}]))
    assert telegram.gesendet("sendMessage") == []
