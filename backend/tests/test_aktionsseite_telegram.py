"""Aktionsseite: Beiträge aus Telegram — verbinden, annehmen, freigeben.

Gegen eine gestellte Bot-API (``httpx.MockTransport``), mit echter Datenbank.
Die Zusagen hier sind die aus dem Plan § 2–3: Nur verbundene Gruppen zählen,
Weitergeleitetes nicht; ein Album ist ein Beitrag; freigeben darf nur die Presse
**dieser** Seite; „Text ändern“ zählt nur die Antwort dessen, der gedrückt hat;
und ein Fahrer kann einen freigegebenen Text nicht nachträglich austauschen.
"""
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.public_tracker import (
    PublicTrackerChat,
    PublicTrackerCode,
    PublicTrackerPhotoData,
    PublicTrackerPost,
    PublicTrackerPresse,
    PublicTrackerTelegram,
)
from app.services import aktionsseite_telegram as tg
from app.services.crypto import decrypt_secret, encrypt_secret
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    h,
    reset_db_engine,
    seite_anlegen,
)

TOKEN = "123456:ABCdefGhIJKlmnoPQRstuVWXyz_0123456"
BOT = "AktionsBot"
GRUPPE = -100777
JETZT = datetime.now(timezone.utc)


def _jpeg_mit_gps() -> bytes:
    exif = Image.Exif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (48.0, 8.0, 30.0), "E", (11.0, 34.0, 10.0)
    puffer = io.BytesIO()
    Image.new("RGB", (640, 480), (30, 90, 160)).save(puffer, format="JPEG", exif=exif)
    return puffer.getvalue()


class FalscheBotApi:
    """Was der Bot an Telegram schickt, und was Telegram antwortet."""

    def __init__(self):
        self.aufrufe: list[tuple[str, dict]] = []
        self.naechste_id = 5000
        self.updates: list[dict] = []
        self.fehler: dict[str, tuple[int, str]] = {}
        self.liest_alles = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        pfad = request.url.path
        if pfad.startswith("/file/"):
            return httpx.Response(200, content=_jpeg_mit_gps())
        methode = pfad.rsplit("/", 1)[-1]
        if request.headers.get("content-type", "").startswith("multipart/"):
            daten = {"multipart": request.content}  # hochgeladene Datei, roh
        else:
            daten = json.loads(request.content or b"{}")
        self.aufrufe.append((methode, daten))
        if methode in self.fehler:
            code, text_ = self.fehler[methode]
            return httpx.Response(code, json={"ok": False, "error_code": code, "description": text_})
        if methode == "getMe":
            r = {"id": 42, "is_bot": True, "username": BOT,
                 "can_read_all_group_messages": self.liest_alles}
        elif methode == "getUpdates":
            r = [u for u in self.updates if u["update_id"] >= daten.get("offset", 0)]
        elif methode == "sendMessage":
            self.naechste_id += 1
            r = {"message_id": self.naechste_id, "chat": {"id": daten["chat_id"]}}
        elif methode == "getFile":
            r = {"file_id": daten["file_id"], "file_size": 1000, "file_path": "photos/a.jpg"}
        else:
            r = True
        return httpx.Response(200, json={"ok": True, "result": r})

    def gesendet(self, methode: str) -> list[dict]:
        return [d for m, d in self.aufrufe if m == methode]


@pytest.fixture
def telegram(monkeypatch):
    falsch = FalscheBotApi()
    monkeypatch.setattr(tg, "transport", httpx.MockTransport(falsch))
    tg.vergessen()
    return falsch


@pytest.fixture
async def seite(aktion, client):
    """Eine Aktionsseite mit dem Konvoi des Fixtures und ein Bot der Organisation."""
    s = await seite_anlegen(client, aktion)
    async with AsyncSessionLocal() as db:
        db.add(PublicTrackerTelegram(
            organization_id=aktion.org_id, bot_token_enc=encrypt_secret(TOKEN),
            bot_username=BOT, status="bereit",
        ))
        await db.commit()
    return uuid.UUID(s["id"])


_uid = iter(range(1, 10_000))
_mid = iter(range(100, 100_000))


def _nachricht(text_=None, *, chat=GRUPPE, von=7, typ="supergroup", **mehr) -> dict:
    n = {
        "message_id": next(_mid), "date": int(JETZT.timestamp()),
        "chat": {"id": chat, "type": typ, "title": "Weihnachtskonvoi 2026"},
        "from": {"id": von, "is_bot": False, "first_name": f"Person{von}"},
        **mehr,
    }
    if text_ is not None:
        n["text"] = text_
    return n


def _foto(**mehr) -> dict:
    return _nachricht(photo=[{"file_id": "klein", "width": 90}, {"file_id": "gross", "width": 1280}], **mehr)


async def _update(art: str, inhalt: dict) -> None:
    async with AsyncSessionLocal() as db:
        bot = (await db.execute(select(PublicTrackerTelegram))).scalars().first()
        api = tg.api_fuer(TOKEN)
        await tg.verarbeiten(db, bot, await api.ich(), api, {"update_id": next(_uid), art: inhalt})


async def _code(seite_id, art, convoy_id=None) -> str:
    code = tg.code_erzeugen()
    async with AsyncSessionLocal() as db:
        db.add(PublicTrackerCode(
            code_hash=tg.code_hash(code), tracker_id=seite_id, convoy_id=convoy_id, art=art,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ))
        await db.commit()
    return code


async def _verbunden(aktion, seite_id, thema=None):
    code = await _code(seite_id, "verbinden", aktion.convoy_id)
    extra = {"message_thread_id": thema, "is_topic_message": True} if thema else {}
    await _update("message", _nachricht(f"/verbinden@{BOT} {code.lower()}", **extra))


async def _presse(seite_id, von: int):
    code = await _code(seite_id, "presse")
    await _update("message", _nachricht(f"/presse {code}", chat=von, von=von, typ="private"))


async def _beitraege(seite_id) -> list[PublicTrackerPost]:
    async with AsyncSessionLocal() as db:
        return list((await db.execute(
            select(PublicTrackerPost).where(PublicTrackerPost.tracker_id == seite_id)
            .options(selectinload(PublicTrackerPost.photos))
            .order_by(PublicTrackerPost.created_at)
        )).scalars().all())


def _knopf(post, aktion: str, von: int, chat=GRUPPE) -> dict:
    return {
        "id": f"cq{next(_uid)}", "from": {"id": von, "first_name": f"Person{von}"},
        "data": tg.callback(post.id, aktion),
        "message": {"message_id": post.card_message_id, "chat": {"id": chat}},
    }


# ── Verbinden ──────────────────────────────────────────────────────────────


async def test_gruppe_per_code_verbinden(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    async with AsyncSessionLocal() as db:
        chat = (await db.execute(select(PublicTrackerChat))).scalars().all()
        codes = (await db.execute(
            select(PublicTrackerCode).where(PublicTrackerCode.tracker_id == seite)
        )).scalars().all()
    assert [(c.chat_id, c.thread_id, c.convoy_id) for c in chat if c.tracker_id == seite] == [
        (GRUPPE, None, aktion.convoy_id)
    ]
    assert codes == []  # einmalig
    antwort = telegram.gesendet("sendMessage")[-1]["text"]
    assert "Konvoi Bosnien" in antwort and "120 Minuten" in antwort


async def test_thema_einer_gruppe_verbinden(aktion, seite, telegram):
    await _verbunden(aktion, seite, thema=11)
    async with AsyncSessionLocal() as db:
        chat = (await db.execute(
            select(PublicTrackerChat).where(PublicTrackerChat.tracker_id == seite)
        )).scalar_one()
    assert (chat.chat_id, chat.thread_id) == (GRUPPE, 11)
    assert telegram.gesendet("sendMessage")[-1]["message_thread_id"] == 11


async def test_unbekannter_code_verbindet_nichts(aktion, seite, telegram):
    await _update("message", _nachricht("/verbinden ABC-DEF"))
    async with AsyncSessionLocal() as db:
        assert not (await db.execute(
            select(PublicTrackerChat).where(PublicTrackerChat.tracker_id == seite)
        )).scalars().all()
    assert "unbekannt oder abgelaufen" in telegram.gesendet("sendMessage")[-1]["text"]


async def test_befehl_an_einen_anderen_bot_zaehlt_nicht(aktion, seite, telegram):
    code = await _code(seite, "verbinden", aktion.convoy_id)
    await _update("message", _nachricht(f"/verbinden@AndererBot {code}"))
    async with AsyncSessionLocal() as db:
        assert not (await db.execute(
            select(PublicTrackerChat).where(PublicTrackerChat.tracker_id == seite)
        )).scalars().all()


# ── Beiträge ───────────────────────────────────────────────────────────────


async def test_foto_aus_unverbundener_gruppe_wird_verworfen(aktion, seite, telegram):
    await _update("message", _foto(caption="Hallo"))
    assert await _beitraege(seite) == []
    assert telegram.gesendet("sendMessage") == []


async def test_foto_wird_beitrag_mit_karte_und_ohne_exif(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="Grenze geschafft!", von=7))
    [post] = await _beitraege(seite)
    assert post.status == "wartet"
    assert post.text_public == "Grenze geschafft!"
    assert post.sender_name == "Person7"
    assert len(post.photos) == 1
    async with AsyncSessionLocal() as db:
        daten = await db.get(PublicTrackerPhotoData, post.photos[0].id)
    assert b"Exif" not in daten.gross
    karte = telegram.gesendet("sendMessage")[-1]
    assert "Wartet auf Presse" in karte["text"]
    knoepfe = [k["text"] for k in karte["reply_markup"]["inline_keyboard"][0]]
    assert knoepfe == ["✅ Freigeben", "✏️ Text ändern", "❌ Ablehnen"]
    assert post.card_message_id == telegram.naechste_id


async def test_weitergeleitetes_foto_wird_verworfen(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _update("message", _foto(forward_origin={"type": "user", "date": 1}))
    assert await _beitraege(seite) == []


async def test_album_ist_ein_beitrag(aktion, seite, telegram):
    """Telegram schickt ein Album als einzelne Updates; die Unterschrift trägt
    nicht unbedingt das erste."""
    await _verbunden(aktion, seite)
    await _update("message", _foto(media_group_id="alb1"))
    await _update("message", _foto(media_group_id="alb1", caption="Drei Bilder vom Zoll"))
    await _update("message", _foto(media_group_id="alb1"))
    [post] = await _beitraege(seite)
    assert [f.position for f in post.photos] == [0, 1, 2]
    assert post.text_public == "Drei Bilder vom Zoll"
    assert len(telegram.gesendet("sendMessage")) == 2  # Verbunden + eine Karte
    assert "3 Bilder" in telegram.gesendet("editMessageText")[-1]["text"]


# ── Presse und Knöpfe ──────────────────────────────────────────────────────


async def test_knopf_ohne_presse_aendert_nichts(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="x"))
    [post] = await _beitraege(seite)
    await _update("callback_query", _knopf(post, "frei", von=99))
    [post] = await _beitraege(seite)
    assert post.status == "wartet"
    alarm = telegram.gesendet("answerCallbackQuery")[-1]
    assert alarm["show_alert"] is True and "nur die Presse" in alarm["text"]


async def test_presse_einer_anderen_seite_zaehlt_nicht(aktion, seite, client, telegram):
    andere = uuid.UUID((await seite_anlegen(client, aktion, title="Andere Seite"))["id"])
    await _presse(andere, von=55)
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="x"))
    [post] = await _beitraege(seite)
    await _update("callback_query", _knopf(post, "frei", von=55))
    [post] = await _beitraege(seite)
    assert post.status == "wartet"


async def test_presse_gibt_frei_und_die_karte_sagt_wann(aktion, seite, telegram):
    await _presse(seite, von=55)
    assert "frei" in telegram.gesendet("sendMessage")[-1]["text"]
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="x"))
    [post] = await _beitraege(seite)
    await _update("callback_query", _knopf(post, "frei", von=55))
    [post] = await _beitraege(seite)
    assert post.status == "freigegeben"
    assert post.reviewed_by_telegram_id == 55
    karte = telegram.gesendet("editMessageText")[-1]
    assert "Freigegeben von Person55" in karte["text"]
    assert "erscheint frühestens" in karte["text"]
    async with AsyncSessionLocal() as db:
        eintraege = (await db.execute(
            select(AuditLog).where(
                AuditLog.action == "org.aktionsseite.beitrag_freigegeben",
                AuditLog.target_id == str(post.id),
            )
        )).scalars().all()
    assert eintraege and eintraege[0].detail["telegram_user_id"] == 55
    # Zweimal freigeben geht nicht: „Schon erledigt“.
    await _update("callback_query", _knopf(post, "frei", von=55))
    assert "Schon erledigt" in telegram.gesendet("answerCallbackQuery")[-1]["text"]


async def test_knopf_aus_einer_anderen_gruppe_zaehlt_nicht(aktion, seite, telegram):
    await _presse(seite, von=55)
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="x"))
    [post] = await _beitraege(seite)
    await _update("callback_query", _knopf(post, "frei", von=55, chat=-100999))
    [post] = await _beitraege(seite)
    assert post.status == "wartet"


async def test_text_aendern_zaehlt_nur_die_antwort_dessen_der_drueckte(aktion, seite, telegram):
    await _presse(seite, von=55)
    await _presse(seite, von=56)
    await _verbunden(aktion, seite)
    await _update("message", _foto(caption="Wir stehen an der A3 bei Würzburg"))
    [post] = await _beitraege(seite)
    await _update("callback_query", _knopf(post, "text", von=55))
    frage = telegram.gesendet("sendMessage")[-1]
    assert frage["reply_markup"] == {"force_reply": True, "selective": True}
    frage_id = telegram.naechste_id
    antwort_auf = {"message_id": frage_id, "chat": {"id": GRUPPE}}
    # Jemand anderes — auch Presse — antwortet: zählt nicht.
    await _update("message", _nachricht("Eingeschmuggelt", von=56, reply_to_message=antwort_auf))
    [post] = await _beitraege(seite)
    assert post.text_public == "Wir stehen an der A3 bei Würzburg"
    await _update("message", _nachricht("Unterwegs nach Süden", von=55, reply_to_message=antwort_auf))
    [post] = await _beitraege(seite)
    assert post.text_public == "Unterwegs nach Süden"
    assert post.text_edited_by_presse is True
    assert post.text_raw == "Wir stehen an der A3 bei Würzburg"


async def test_fahrer_tauscht_freigegebenen_text_aus(aktion, seite, telegram):
    """Vor der Freigabe ersetzt eine Bearbeitung in Telegram den Vorschlag,
    danach nie: sonst ließe sich ein freigegebener Text still austauschen."""
    await _presse(seite, von=55)
    await _verbunden(aktion, seite)
    foto = _foto(caption="Erster Text", von=7)
    await _update("message", foto)
    await _update("edited_message", {**foto, "caption": "Zweiter Text"})
    [post] = await _beitraege(seite)
    assert post.text_public == "Zweiter Text"

    await _update("callback_query", _knopf(post, "frei", von=55))
    await _update("edited_message", {**foto, "caption": "Wir stehen auf dem Autohof Würzburg"})
    [post] = await _beitraege(seite)
    assert post.text_public == "Zweiter Text"
    assert post.text_raw == "Wir stehen auf dem Autohof Würzburg"
    assert "öffentlich bleibt der freigegebene" in telegram.gesendet("editMessageText")[-1]["text"]


# ── Abholen ────────────────────────────────────────────────────────────────


async def test_abholen_schreibt_den_offset_fort(aktion, seite, telegram):
    code = await _code(seite, "verbinden", aktion.convoy_id)
    telegram.updates = [{"update_id": 900, "message": _nachricht(f"/verbinden {code}")}]
    assert await tg.einmal_abholen(aktion.org_id, warten=0) is True
    async with AsyncSessionLocal() as db:
        bot = await db.get(PublicTrackerTelegram, aktion.org_id)
    assert bot.update_offset == 901
    assert bot.status == "bereit"
    assert telegram.gesendet("getUpdates")[-1]["offset"] == 0


async def test_privacy_mode_steht_im_status(aktion, seite, telegram):
    telegram.liest_alles = False
    await tg.einmal_abholen(aktion.org_id, warten=0)
    async with AsyncSessionLocal() as db:
        assert (await db.get(PublicTrackerTelegram, aktion.org_id)).status == "privat"


async def test_zweiter_abholer_und_ungueltiger_token(aktion, seite, telegram):
    telegram.fehler["getUpdates"] = (409, "Conflict: terminated by other getUpdates request")
    assert await tg.einmal_abholen(aktion.org_id, warten=0, pause_bei_fehler=0) is True
    async with AsyncSessionLocal() as db:
        assert (await db.get(PublicTrackerTelegram, aktion.org_id)).status == "konflikt"
    telegram.fehler["getMe"] = (401, "Unauthorized")
    assert await tg.einmal_abholen(aktion.org_id, warten=0) is False
    async with AsyncSessionLocal() as db:
        bot = await db.get(PublicTrackerTelegram, aktion.org_id)
    assert bot.status == "ungueltig"
    assert TOKEN not in (bot.last_error or "")


# ── Org-Admin ──────────────────────────────────────────────────────────────


async def test_bot_eintragen_token_nie_wieder_sichtbar(aktion, client, telegram):
    r = await client.put(
        "/api/org/aktionsseiten/telegram", json={"token": TOKEN}, headers=h(aktion.admin)
    )
    assert r.status_code == 200, r.text
    assert r.json()["bot_username"] == BOT and r.json()["status"] == "bereit"
    assert TOKEN not in r.text
    r = await client.get("/api/org/aktionsseiten/telegram", headers=h(aktion.admin))
    assert r.json()["eingerichtet"] is True and TOKEN not in r.text
    async with AsyncSessionLocal() as db:
        bot = await db.get(PublicTrackerTelegram, aktion.org_id)
    assert bot.bot_token_enc != TOKEN and decrypt_secret(bot.bot_token_enc) == TOKEN


async def test_unbekannter_token_wird_abgewiesen(aktion, client, telegram):
    telegram.fehler["getMe"] = (401, "Unauthorized")
    r = await client.put(
        "/api/org/aktionsseiten/telegram", json={"token": TOKEN}, headers=h(aktion.admin)
    )
    assert r.status_code == 422


async def test_codes_gruppen_und_presse_im_org_admin(aktion, seite, client, telegram):
    basis = f"/api/org/aktionsseiten/{seite}"
    r = await client.post(f"{basis}/konvois/{aktion.convoy_id}/telegram-code", headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    await _update("message", _nachricht(f"/verbinden {code}"))
    r = await client.post(f"{basis}/presse-code", headers=h(aktion.admin))
    await _update("message", _nachricht(f"/presse {r.json()['code']}", chat=55, von=55, typ="private"))

    stand = (await client.get(f"{basis}/telegram", headers=h(aktion.admin))).json()
    assert stand["gruppen"] == [
        {"convoy_id": str(aktion.convoy_id), "chat_title": "Weihnachtskonvoi 2026", "thema": False}
    ]
    assert [p["telegram_user_id"] for p in stand["presse"]] == [55]

    assert (await client.delete(f"{basis}/presse/55", headers=h(aktion.admin))).status_code == 204
    assert (await client.delete(
        f"{basis}/konvois/{aktion.convoy_id}/telegram", headers=h(aktion.admin)
    )).status_code == 204
    stand = (await client.get(f"{basis}/telegram", headers=h(aktion.admin))).json()
    assert stand == {"gruppen": [], "presse": []}
    async with AsyncSessionLocal() as db:
        assert await db.get(PublicTrackerPresse, (seite, 55)) is None


async def test_ohne_adminrolle_nichts(aktion, seite, client, telegram):
    for methode, pfad in [
        ("get", "/api/org/aktionsseiten/telegram"),
        ("put", "/api/org/aktionsseiten/telegram"),
        ("post", f"/api/org/aktionsseiten/{seite}/presse-code"),
        ("get", f"/api/org/aktionsseiten/{seite}/telegram"),
    ]:
        r = await client.request(methode, pfad, json={"token": TOKEN}, headers=h(aktion.fahrer))
        assert r.status_code == 403, (methode, pfad)
