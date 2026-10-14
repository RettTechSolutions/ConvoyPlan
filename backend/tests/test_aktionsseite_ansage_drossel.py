"""Aktionsseite: was der Bot sagt, wenn er nichts annimmt, und was er nachholt,
wenn Telegram ihn drosselt.

Gegen die gestellte Bot-API aus ``test_aktionsseite_telegram.py``. Zwei Zusagen:

- **Nicht still verwerfen.** Ist die Seite nicht aktiv oder die Tagesgrenze
  erreicht, sagt der Bot es der Gruppe — einmal, nicht auf jedes Foto eines
  Albums; sonst posten die Fahrer weiter und wundern sich.
- **Keine Karte geht verloren.** Antwortet Telegram mit 429 (oder ist gestört),
  kommt der Beitrag in die Warteschlange und die Karte später — gebaut aus dem
  Stand von dann. Ohne Karte könnte die Presse in Telegram nicht freigeben.
"""
from datetime import datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models.public_tracker import PublicTracker, PublicTrackerPost
from app.services import aktionsseite_telegram as tg
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    reset_db_engine,
    seite_anlegen,
)
from tests.test_aktionsseite_telegram import (  # noqa: F401 — Fixtures und Helfer
    TOKEN,
    _beitraege,
    _foto,
    _knopf,
    _nachricht,
    _presse,
    _update,
    _verbunden,
    seite,
    telegram,
)


def _texte(telegram) -> list[str]:
    return [d["text"] for d in telegram.gesendet("sendMessage")]


async def _seite_aus(seite_id) -> None:
    async with AsyncSessionLocal() as db:
        t = await db.get(PublicTracker, seite_id)
        t.valid_until = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.commit()


# ── Ansage ─────────────────────────────────────────────────────────────────


async def test_seite_nicht_aktiv_sagt_es_einmal(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _seite_aus(seite)
    vorher = len(_texte(telegram))
    for _ in range(3):  # ein Album aus drei Bildern
        await _update("message", _foto(caption="Grenze", media_group_id="album-1"))
    await _update("message", _nachricht("https://www.instagram.com/p/Abc/"))
    neu = _texte(telegram)[vorher:]
    assert len(neu) == 1
    assert "„Weihnachtskonvois 2026“ ist gerade nicht aktiv" in neu[0]
    assert "nicht gespeichert" in neu[0]
    assert await _beitraege(seite) == []
    # Als Antwort auf das Foto, damit klar ist, worum es geht.
    assert telegram.gesendet("sendMessage")[-1]["reply_parameters"]["message_id"]


async def test_tagesgrenze_sagt_es_einmal(aktion, seite, telegram, monkeypatch):
    monkeypatch.setattr(tg, "BILDER_JE_TAG", 1)
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="eins"))
    vorher = len(_texte(telegram))
    await _update("message", _foto(caption="zwei"))
    await _update("message", _foto(caption="drei"))
    neu = _texte(telegram)[vorher:]
    assert len(neu) == 1 and "keine weiteren Fotos" in neu[0]
    assert len(await _beitraege(seite)) == 1


async def test_ein_anderer_grund_wird_wieder_angesagt(aktion, seite, telegram, monkeypatch):
    monkeypatch.setattr(tg, "BILDER_JE_TAG", 0)
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="eins"))
    await _seite_aus(seite)
    await _update("message", _foto(caption="zwei"))
    texte = _texte(telegram)
    assert "keine weiteren Fotos" in texte[-2]
    assert "nicht aktiv" in texte[-1]


async def test_fremde_gruppe_bekommt_keine_antwort(aktion, seite, telegram):
    vorher = len(_texte(telegram))
    await _update("message", _foto(caption="Hallo", chat=-100999))
    assert len(_texte(telegram)) == vorher


# ── Warteschlange bei 429 ──────────────────────────────────────────────────


async def _nachholen(aktion, jetzt: datetime) -> int:
    async with AsyncSessionLocal() as db:
        return await tg.karten_nachholen(db, tg.api_fuer(TOKEN), aktion.org_id, jetzt)


async def test_gedrosselte_karte_kommt_spaeter(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    telegram.fehler["sendMessage"] = (429, "Too Many Requests: retry after 30")
    await _update("message", _foto(caption="Grenze"))
    [post] = await _beitraege(seite)
    assert post.card_message_id is None
    assert post.karte_faellig_ab is not None
    assert post.karte_faellig_ab > datetime.now(timezone.utc) + timedelta(seconds=20)

    # Zu früh: nichts. Danach: die Karte, als Antwort auf das Foto.
    del telegram.fehler["sendMessage"]
    assert await _nachholen(aktion, datetime.now(timezone.utc)) == 0
    assert await _nachholen(aktion, datetime.now(timezone.utc) + timedelta(minutes=1)) == 1
    [post] = await _beitraege(seite)
    assert post.card_message_id is not None and post.karte_faellig_ab is None
    karte = telegram.gesendet("sendMessage")[-1]
    assert karte["reply_parameters"]["message_id"] == post.message_id
    assert karte["reply_markup"]["inline_keyboard"][0][0]["text"] == "✅ Freigeben"


async def test_nachgeholt_wird_der_stand_von_dann(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _presse(seite, von=900)
    await _update("message", _foto(caption="Grenze"))
    [post] = await _beitraege(seite)
    telegram.fehler["editMessageText"] = (429, "Too Many Requests: retry after 5")
    await _update("callback_query", _knopf(post, "frei", von=900))
    [post] = await _beitraege(seite)
    assert post.status == "freigegeben"
    assert post.karte_faellig_ab is not None

    # Inzwischen zieht die Presse ihn im Org-Admin zurück — nachgeholt wird dieser Stand.
    async with AsyncSessionLocal() as db:
        p = await db.get(PublicTrackerPost, post.id)
        p.status = "zurueckgezogen"
        await db.commit()
    del telegram.fehler["editMessageText"]
    assert await _nachholen(aktion, datetime.now(timezone.utc) + timedelta(minutes=1)) == 1
    assert "↩️ Zurückgezogen" in telegram.gesendet("editMessageText")[-1]["text"]
    [post] = await _beitraege(seite)
    assert post.karte_faellig_ab is None


async def test_wieder_gedrosselt_endet_der_durchgang(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    telegram.fehler["sendMessage"] = (429, "Too Many Requests")
    await _update("message", _foto(caption="eins"))
    await _update("message", _foto(caption="zwei"))
    bearbeitet = len(telegram.gesendet("sendMessage"))
    assert await _nachholen(aktion, datetime.now(timezone.utc) + timedelta(minutes=1)) == 0
    # Ein Versuch, nicht zwei: Telegram hat gerade gesagt, dass es zu viel ist.
    assert len(telegram.gesendet("sendMessage")) == bearbeitet + 1
    assert all(p.card_message_id is None and p.karte_faellig_ab for p in await _beitraege(seite))


async def test_bot_aus_der_gruppe_geworfen_wird_nicht_nachgeholt(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    telegram.fehler["sendMessage"] = (403, "Forbidden: bot was kicked from the supergroup chat")
    await _update("message", _foto(caption="Grenze"))
    [post] = await _beitraege(seite)
    assert post.card_message_id is None and post.karte_faellig_ab is None


async def test_die_abholschleife_holt_faellige_karten_nach(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    telegram.fehler["sendMessage"] = (429, "Too Many Requests")
    await _update("message", _foto(caption="Grenze"))
    [post] = await _beitraege(seite)
    async with AsyncSessionLocal() as db:
        p = await db.get(PublicTrackerPost, post.id)
        p.karte_faellig_ab = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    del telegram.fehler["sendMessage"]
    assert await tg.einmal_abholen(aktion.org_id, warten=0) is True
    [post] = await _beitraege(seite)
    assert post.card_message_id is not None and post.karte_faellig_ab is None
