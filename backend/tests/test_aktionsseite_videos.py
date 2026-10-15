"""Aktionsseite: Videos von unterwegs (Plan § 15).

Ein Video aus der Gruppe geht durch den Medien-Container (hier gestellt; was
der echte mit GPS, Drehung und Länge macht, prüft docker/medien/tests),
liegt danach als Datei auf dem Upload-Volume und sein Standbild als Bild des
Beitrags. Hinaus geht es wie ein Foto: erst nach Freigabe, Verzögerung und
Platzierung, und nur, solange es in der Antwort steht. Was keine Zeile mehr
hat, räumt ``aufraeumen`` weg.
"""
import base64
import io
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.public_tracker import (
    PublicTrackerPhoto,
    PublicTrackerPhotoData,
    PublicTrackerPost,
    PublicTrackerVideo,
)
from app.services import aktionsseite_telegram as tg
from app.services import aktionsseite_video as av
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    fahrt,
    h,
    reset_db_engine,
    seite_anlegen,
    verlauf,
)
from tests.test_aktionsseite_telegram import (  # noqa: F401 — Fixtures und Helfer
    _beitraege,
    _nachricht,
    _update,
    _verbunden,
    seite,
    telegram,
)

MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 2000


def _jpeg() -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (1280, 720), (30, 90, 160)).save(puffer, format="JPEG")
    return puffer.getvalue()


class Medien:
    """Der Medien-Container, so wie er antwortet — oder ablehnt."""

    def __init__(self):
        self.aufrufe: list[httpx.Request] = []
        self.antwort: httpx.Response | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.aufrufe.append(request)
        if self.antwort is not None:
            return self.antwort
        return httpx.Response(200, json={
            "breite": 1280, "hoehe": 720, "sekunden": 42.3, "ton": True,
            "video": base64.b64encode(MP4).decode(), "poster": base64.b64encode(_jpeg()).decode(),
        })


@pytest.fixture
def medien(monkeypatch, tmp_path):
    m = Medien()
    monkeypatch.setattr(av, "transport", httpx.MockTransport(m))
    monkeypatch.setattr(av, "VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(settings, "medien_url", "http://medien:8090")
    return m


def _video(**mehr) -> dict:
    return _nachricht(video={"file_id": "film", "duration": 42, "file_size": 5_000_000,
                             "width": 1920, "height": 1080, "mime_type": "video/mp4"}, **mehr)


async def _videos(seite_id) -> list[PublicTrackerPost]:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(PublicTrackerPost)
            .where(PublicTrackerPost.tracker_id == seite_id, PublicTrackerPost.video.has())
            .options(selectinload(PublicTrackerPost.photos))
        )).scalars().all()


async def _eintrag(post_id) -> PublicTrackerVideo:
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(PublicTrackerVideo).where(PublicTrackerVideo.post_id == post_id)
        )).scalar_one()


# ── Beim Eingang ───────────────────────────────────────────────────────────


async def test_video_wird_beitrag_mit_datei_standbild_und_karte(aktion, seite, telegram, medien):
    await _verbunden(aktion, seite)
    await _update("message", _video(caption="Über den Tauern"))
    [post] = await _videos(seite)
    assert (post.status, post.text_public) == ("wartet", "Über den Tauern")
    [standbild] = post.photos
    assert (standbild.width, standbild.height) == (1280, 720)
    eintrag = await _eintrag(post.id)
    assert (eintrag.width, eintrag.height, eintrag.seconds, eintrag.sound) == (1280, 720, 42.3, True)
    assert av.pfad(eintrag.public_id).read_bytes() == MP4
    # Der Container bekam die Bytes aus Telegram und die Grenze von 60 s.
    [anfrage] = medien.aufrufe
    assert anfrage.url.params["max_sekunden"] == "60"
    assert anfrage.content[:3] == b"\xff\xd8\xff"  # was die gestellte Bot-API als Datei liefert
    karte = telegram.gesendet("sendMessage")[-1]["text"]
    assert karte.startswith("🎬 Video · Konvoi Bosnien · 0:42")
    assert "🔊 mit Ton — vor dem Freigeben anhören" in karte
    assert telegram.gesendet("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0][0]["text"] == "✅ Freigeben"


async def test_ohne_ton_sagt_die_karte_das(aktion, seite, telegram, medien):
    medien.antwort = httpx.Response(200, json={
        "breite": 720, "hoehe": 1280, "sekunden": 9.0, "ton": False,
        "video": base64.b64encode(MP4).decode(), "poster": base64.b64encode(_jpeg()).decode(),
    })
    await _verbunden(aktion, seite)
    await _update("message", _video())
    assert "🔇 ohne Ton" in telegram.gesendet("sendMessage")[-1]["text"]


async def test_auch_als_datei_geschickt(aktion, seite, telegram, medien):
    await _verbunden(aktion, seite)
    await _update("message", _nachricht(document={"file_id": "doc", "mime_type": "video/quicktime",
                                                  "file_size": 9_000_000}))
    assert len(await _videos(seite)) == 1


async def test_zu_lang_oder_zu_gross_fragt_niemanden(aktion, seite, telegram, medien):
    await _verbunden(aktion, seite)
    await _update("message", _nachricht(video={"file_id": "lang", "duration": 75, "file_size": 1000}))
    await _update("message", _nachricht(video={"file_id": "gross", "duration": 30, "file_size": 30_000_000}))
    antworten = [d["text"] for d in telegram.gesendet("sendMessage")[-2:]]
    assert antworten == [tg.TEXT_VIDEO_ZU_LANG, tg.TEXT_VIDEO_ZU_GROSS]
    assert medien.aufrufe == []
    assert telegram.gesendet("getFile") == []
    assert await _videos(seite) == []


async def test_abgelehnt_sagt_der_bot_warum_und_legt_nichts_ab(aktion, seite, telegram, medien):
    medien.antwort = httpx.Response(422, json={"grund": "Das Video ist länger als 60 Sekunden."})
    await _verbunden(aktion, seite)
    await _update("message", _video())
    assert telegram.gesendet("sendMessage")[-1]["text"] == "Das Video ist länger als 60 Sekunden."
    assert await _videos(seite) == []
    assert not av.VIDEOS_DIR.exists() or list(av.VIDEOS_DIR.iterdir()) == []


@pytest.mark.parametrize("antwort", [
    # Was der Container schickt, wird geprüft, nicht geglaubt.
    httpx.Response(200, json={"breite": 1280, "hoehe": 720, "sekunden": 4, "ton": True,
                              "video": base64.b64encode(b"<html>").decode(),
                              "poster": base64.b64encode(_jpeg()).decode()}),
    httpx.Response(200, json={"breite": 4000, "hoehe": 720, "sekunden": 4, "ton": True,
                              "video": base64.b64encode(MP4).decode(),
                              "poster": base64.b64encode(_jpeg()).decode()}),
    httpx.Response(200, json={"breite": 1280, "hoehe": 720, "sekunden": 4, "ton": True,
                              "video": base64.b64encode(MP4).decode(), "poster": "kein base64!"}),
    httpx.Response(500, text="kaputt"),
])
async def test_unbrauchbare_antwort_ergibt_keinen_beitrag(aktion, seite, telegram, medien, antwort):
    medien.antwort = antwort
    await _verbunden(aktion, seite)
    await _update("message", _video())
    assert await _videos(seite) == []
    assert "Video" in telegram.gesendet("sendMessage")[-1]["text"]


async def test_container_weg(aktion, seite, telegram, monkeypatch, tmp_path):
    def weg(request):
        raise httpx.ConnectError("kein medien", request=request)
    monkeypatch.setattr(av, "transport", httpx.MockTransport(weg))
    monkeypatch.setattr(av, "VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(settings, "medien_url", "http://medien:8090")
    await _verbunden(aktion, seite)
    await _update("message", _video())
    assert "später noch einmal" in telegram.gesendet("sendMessage")[-1]["text"]
    assert await _videos(seite) == []


async def test_ohne_medien_container_sagt_der_bot_es_einmal(aktion, seite, telegram, medien, monkeypatch):
    monkeypatch.setattr(settings, "medien_url", "")
    await _verbunden(aktion, seite)
    vorher = len(telegram.gesendet("sendMessage"))
    await _update("message", _video())
    await _update("message", _video())
    neu = [d["text"] for d in telegram.gesendet("sendMessage")[vorher:]]
    assert neu == [tg.TEXT_VIDEO_AUS]
    assert medien.aufrufe == []


# ── Hinaus ─────────────────────────────────────────────────────────────────


async def _video_beitrag(seite_id, convoy_id, t, status="freigegeben", ordner=None) -> tuple[str, str]:
    async with AsyncSessionLocal() as db:
        p = PublicTrackerPost(
            public_id=secrets.token_urlsafe(16), tracker_id=seite_id, convoy_id=convoy_id,
            taken_at=t, status=status, text_public="Über den Tauern",
        )
        foto = PublicTrackerPhoto(public_id=secrets.token_urlsafe(16), position=0, width=1280, height=720)
        p.photos.append(foto)
        p.video = PublicTrackerVideo(public_id=secrets.token_urlsafe(16), width=1280, height=720,
                                     seconds=42.3, sound=True, bytes=len(MP4))
        db.add(p)
        await db.flush()
        db.add(PublicTrackerPhotoData(photo_id=foto.id, gross=b"RIFFgross", klein=b"RIFFklein"))
        await db.commit()
        av.ablegen(p.video.public_id, MP4)
        return p.video.public_id, foto.public_id


async def test_video_geht_nur_freigegeben_und_mit_standbild_hinaus(aktion, client, medien):
    seite = await seite_anlegen(client, aktion)
    sid = uuid.UUID(seite["id"])
    jetzt = datetime.now(timezone.utc)
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 300))
    frei, standbild = await _video_beitrag(sid, aktion.convoy_id, jetzt - timedelta(hours=3))
    wartend, _ = await _video_beitrag(sid, aktion.convoy_id, jetzt - timedelta(hours=3), status="wartet")
    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    assert r.status_code == 200, r.text
    [beitrag] = r.json()["convoys"][0]["posts"]
    # Das Standbild ist kein Foto von unterwegs: Es steht am Video.
    assert beitrag["photos"] == []
    assert beitrag["video"] == {
        "id": frei, "width": 1280, "height": 720, "seconds": 42.3, "sound": True,
        "poster": {"id": standbild, "width": 1280, "height": 720},
    }
    basis = f"/api/public/aktion/{seite['slug']}"
    v = await client.get(f"{basis}/video/{frei}.mp4", headers=h(seite["fetch_token"]))
    assert (v.status_code, v.headers["content-type"], v.content) == (200, "video/mp4", MP4)
    b = await client.get(f"{basis}/bild/{standbild}/klein.webp", headers=h(seite["fetch_token"]))
    assert b.status_code == 200
    for adresse, token in (
        (f"{basis}/video/{wartend}.mp4", seite["fetch_token"]),
        (f"{basis}/video/{frei}.mp4", "falsch"),
        (f"{basis}/video/..%2F..%2Fetc%2Fpasswd.mp4", seite["fetch_token"]),
    ):
        assert (await client.get(adresse, headers=h(token))).status_code == 404, adresse


async def test_ohne_datei_404_statt_500(aktion, client, medien):
    seite = await seite_anlegen(client, aktion)
    jetzt = datetime.now(timezone.utc)
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 300))
    frei, _ = await _video_beitrag(uuid.UUID(seite["id"]), aktion.convoy_id, jetzt - timedelta(hours=3))
    av.loeschen(frei)
    r = await client.get(f"/api/public/aktion/{seite['slug']}/video/{frei}.mp4", headers=h(seite["fetch_token"]))
    assert r.status_code == 404


async def test_org_admin_sieht_und_hoert_vor_der_freigabe(aktion, client, medien):
    seite = await seite_anlegen(client, aktion)
    sid = uuid.UUID(seite["id"])
    await _video_beitrag(sid, aktion.convoy_id, datetime.now(timezone.utc), status="wartet")
    r = await client.get(f"/api/org/aktionsseiten/{sid}/beitraege", headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    [zeile] = r.json()
    assert zeile["video"]["seconds"] == 42.3 and zeile["video"]["sound"] is True
    assert len(zeile["photos"]) == 1
    v = await client.get(f"/api/org/aktionsseiten/{sid}/videos/{zeile['video']['id']}.mp4", headers=h(aktion.admin))
    assert (v.status_code, v.content) == (200, MP4)
    fremd = await client.get(f"/api/org/aktionsseiten/{sid}/videos/{uuid.uuid4()}.mp4", headers=h(aktion.admin))
    assert fremd.status_code == 404


# ── Aufräumen ──────────────────────────────────────────────────────────────


async def test_aufraeumen_loescht_nur_dateien_ohne_beitrag(aktion, client, medien):
    seite = await seite_anlegen(client, aktion)
    bleibt, _ = await _video_beitrag(uuid.UUID(seite["id"]), aktion.convoy_id, datetime.now(timezone.utc))
    av.ablegen("waiseWaiseWaise0000000", MP4)
    av.ablegen("geradeErstGeschrieben0", MP4)
    rest = av.VIDEOS_DIR / "x.mp4.abc.tmp"
    rest.write_bytes(b"halb")
    alt = time.time() - av.AUFRAEUMEN_AB - 60
    for name in (f"{bleibt}.mp4", "waiseWaiseWaise0000000.mp4", "x.mp4.abc.tmp"):
        os.utime(av.VIDEOS_DIR / name, (alt, alt))
    async with AsyncSessionLocal() as db:
        assert await av.aufraeumen(db) == 2
    assert sorted(p.name for p in av.VIDEOS_DIR.iterdir()) == sorted(
        [f"{bleibt}.mp4", "geradeErstGeschrieben0.mp4"]
    )
    # Fällt der Beitrag (Retention, Konvoi aus der Seite), geht beim nächsten Mal die Datei.
    async with AsyncSessionLocal() as db:
        post = (await db.execute(select(PublicTrackerPost).where(PublicTrackerPost.video.has()))).scalar_one()
        await db.delete(post)
        await db.commit()
        assert await av.aufraeumen(db, jetzt=time.time() + av.AUFRAEUMEN_AB + 60) == 2
    assert list(av.VIDEOS_DIR.iterdir()) == []

