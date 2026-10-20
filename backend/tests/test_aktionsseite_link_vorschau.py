"""Aktionsseite: Vorschaubilder für Link-Beiträge (Plan § 11.2).

Einmal beim Eingang geholt, nur von festen Hosts, neu kodiert und dann wie
ein Foto ausgeliefert — aber nur zusammen mit dem Link. Jeder Fehler heißt
„ohne Vorschau", nie „ohne Beitrag". YouTube und TikTok sind gestellt.
"""
import io
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.public_tracker import PublicTrackerPhoto, PublicTrackerPhotoData, PublicTrackerPost
from app.services import aktionsseite_vorschau as av
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
    _jpeg_mit_gps,
    _nachricht,
    _update,
    _verbunden,
    seite,
    telegram,
)

THUMB = "https://p16-sign-va.tiktokcdn.com/obj/vorschau.jpeg?x-expires=1"


class Dienste:
    """YouTube und TikTok, so wie sie antworten — oder eben nicht."""

    def __init__(self):
        self.abrufe: list[str] = []
        self.antworten: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.abrufe.append(url)
        for anfang, antwort in self.antworten.items():
            if url.startswith(anfang):
                return antwort
        return httpx.Response(404)


@pytest.fixture
def dienste(monkeypatch):
    d = Dienste()
    monkeypatch.setattr(av, "transport", httpx.MockTransport(d))
    monkeypatch.setattr(settings, "link_vorschau_enabled", True)
    return d


def _jpeg(farbe=(200, 30, 30)) -> httpx.Response:
    puffer = io.BytesIO()
    Image.new("RGB", (1280, 720), farbe).save(puffer, format="JPEG")
    return httpx.Response(200, content=puffer.getvalue(), headers={"content-type": "image/jpeg"})


async def _links(seite_id) -> list[PublicTrackerPost]:
    return [p for p in await _beitraege(seite_id) if p.link_url]


# ── Video-Kennung ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("url, kennung", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/@konvoi", None),
    ("https://www.youtube.com/watch?v=kurz", None),
    ("https://youtu.be/../../etwas", None),
])
def test_youtube_kennung(url, kennung):
    assert av.youtube_kennung(url) == kennung


# ── Beim Eingang ───────────────────────────────────────────────────────────


async def test_youtube_link_bekommt_vorschau_ohne_metadaten(aktion, seite, telegram, dienste):
    gps = httpx.Response(200, content=_jpeg_mit_gps(), headers={"content-type": "image/jpeg"})
    dienste.antworten["https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"] = gps
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("Im Fernsehen! https://youtu.be/dQw4w9WgXcQ?si=geteilt"))
    [post] = await _links(seite)
    [foto] = post.photos
    # maxresdefault fehlt (404), hqdefault gibt es immer.
    assert dienste.abrufe == [
        "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
        "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    ]
    async with AsyncSessionLocal() as db:
        daten = await db.get(PublicTrackerPhotoData, foto.id)
    bild = Image.open(io.BytesIO(daten.gross))
    assert bild.format == "WEBP"
    assert not bild.getexif() and "exif" not in bild.info
    karte = telegram.gesendet("sendMessage")[-1]["text"]
    assert "🖼 mit Vorschaubild des Dienstes" in karte


async def test_tiktok_ueber_oembed(aktion, seite, telegram, dienste):
    dienste.antworten["https://www.tiktok.com/oembed?"] = httpx.Response(
        200, json={"thumbnail_url": THUMB, "author_name": "konvoi"},
    )
    dienste.antworten[THUMB] = _jpeg()
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("https://www.tiktok.com/@konvoi/video/7300000000000000000"))
    [post] = await _links(seite)
    assert len(post.photos) == 1
    assert "url=https%3A%2F%2Fwww.tiktok.com%2F%40konvoi%2Fvideo%2F7300000000000000000" in dienste.abrufe[0]


@pytest.mark.parametrize("fremd", [
    "https://169.254.169.254/latest/meta-data",
    "http://p16-sign-va.tiktokcdn.com/obj/vorschau.jpeg",
    "https://tiktokcdn.com.example.org/vorschau.jpeg",
    "https://p16.tiktokcdn.com:8443/vorschau.jpeg",
])
async def test_tiktok_bild_nur_von_seinen_hosts(aktion, seite, telegram, dienste, fremd):
    """Die Adresse aus oEmbed ist fremdbestimmt: Sonst ließe sich der Server
    über eine Antwort von TikTok in das eigene Netz schicken."""
    dienste.antworten["https://www.tiktok.com/oembed?"] = httpx.Response(200, json={"thumbnail_url": fremd})
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("https://www.tiktok.com/@konvoi/video/1"))
    [post] = await _links(seite)
    assert post.photos == []
    assert len(dienste.abrufe) == 1


async def test_instagram_und_facebook_fragen_gar_nicht(aktion, seite, telegram, dienste):
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("https://www.instagram.com/p/Abc/"))
    await _update("message", _nachricht("https://www.facebook.com/share/v/1AbC/"))
    assert [p.photos for p in await _links(seite)] == [[], []]
    assert dienste.abrufe == []
    karte = telegram.gesendet("sendMessage")[-1]["text"]
    assert "ohne Vorschaubild" in karte


@pytest.mark.parametrize("antwort", [
    httpx.Response(200, content=b"<html>kein Bild</html>", headers={"content-type": "text/html"}),
    httpx.Response(200, content=b"\xff" * (av.MAX_BYTES + 1), headers={"content-type": "image/jpeg"}),
    httpx.Response(302, headers={"location": "https://i.ytimg.com/anderswo.jpg"}),
])
async def test_kaputte_vorschau_laesst_den_link_stehen(aktion, seite, telegram, dienste, antwort):
    dienste.antworten["https://i.ytimg.com/"] = antwort
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("https://youtu.be/dQw4w9WgXcQ"))
    [post] = await _links(seite)
    assert post.photos == []


async def test_ohne_netz_ohne_vorschau(aktion, seite, telegram, monkeypatch):
    def weg(request):
        raise httpx.ConnectError("kein Netz", request=request)
    monkeypatch.setattr(av, "transport", httpx.MockTransport(weg))
    monkeypatch.setattr(settings, "link_vorschau_enabled", True)
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("https://youtu.be/dQw4w9WgXcQ"))
    [post] = await _links(seite)
    assert post.photos == []


async def test_abgeschaltet_fragt_niemanden(aktion, seite, telegram, dienste, monkeypatch):
    monkeypatch.setattr(settings, "link_vorschau_enabled", False)
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("https://youtu.be/dQw4w9WgXcQ"))
    assert dienste.abrufe == []


# ── Hinaus ─────────────────────────────────────────────────────────────────


async def _link_mit_vorschau(seite_id, convoy_id, t, status="freigegeben") -> str:
    async with AsyncSessionLocal() as db:
        p = PublicTrackerPost(
            public_id=secrets.token_urlsafe(16), tracker_id=seite_id, convoy_id=convoy_id,
            taken_at=t, status=status, text_public="Im Fernsehen",
            link_url="https://youtu.be/dQw4w9WgXcQ", link_dienst="youtube",
        )
        foto = PublicTrackerPhoto(public_id=secrets.token_urlsafe(16), position=0, width=1280, height=720)
        p.photos.append(foto)
        db.add(p)
        await db.flush()
        db.add(PublicTrackerPhotoData(photo_id=foto.id, gross=b"RIFFgross", klein=b"RIFFklein"))
        await db.commit()
        return foto.public_id


async def test_vorschau_geht_nur_am_link_hinaus(aktion, client):
    seite = await seite_anlegen(client, aktion)
    sid = uuid.UUID(seite["id"])
    jetzt = datetime.now(timezone.utc)
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 300))
    frei = await _link_mit_vorschau(sid, aktion.convoy_id, jetzt - timedelta(hours=3))
    wartend = await _link_mit_vorschau(sid, aktion.convoy_id, jetzt - timedelta(hours=3), status="wartet")
    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    assert r.status_code == 200, r.text
    [beitrag] = r.json()["convoys"][0]["posts"]
    # Kein Foto von unterwegs: Fällt der Link, fällt das Bild mit.
    assert beitrag["photos"] == []
    assert beitrag["link"] == {
        "url": "https://youtu.be/dQw4w9WgXcQ", "dienst": "youtube",
        "vorschau": {"id": frei, "width": 1280, "height": 720},
    }
    for bild_id, status in ((frei, 200), (wartend, 404)):
        b = await client.get(
            f"/api/public/aktion/{seite['slug']}/bild/{bild_id}/klein.webp", headers=h(seite["fetch_token"])
        )
        assert b.status_code == status, bild_id
