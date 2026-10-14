"""Aktionsseite: Link-Beiträge (Plan § 11) — Instagram & Co. als Link.

Erst die Erkennung ohne Datenbank: nur bekannte Dienste, bereinigt, keine
ähnlich klingenden Domains. Dann durch den Bot (gestellte Bot-API) und hinaus:
ein Link ist ein Beitrag wie ein Foto, mit derselben Freigabe und denselben
Regeln — als Antwort auf ein Foto mit dessen Zeit und damit dessen Ort.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.models.public_tracker import LINK_DIENSTE, PublicTrackerPost
from app.services import aktionsseite_link as al
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
    GRUPPE,
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

# ── Erkennung ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("roh, url, dienst", [
    ("https://www.instagram.com/p/Cx1aBc/?igsh=MWQ1&utm_source=ig_web_copy_link",
     "https://www.instagram.com/p/Cx1aBc/", "instagram"),
    ("http://instagram.com/reel/abc", "https://instagram.com/reel/abc", "instagram"),
    ("https://youtu.be/dQw4w9WgXcQ?si=Teilerkennung&t=42", "https://youtu.be/dQw4w9WgXcQ?t=42", "youtube"),
    ("https://m.youtube.com/watch?v=abc&feature=share", "https://m.youtube.com/watch?v=abc", "youtube"),
    ("https://www.facebook.com/share/v/1AbC/?mibextid=x", "https://www.facebook.com/share/v/1AbC/", "facebook"),
    ("https://www.tiktok.com/@konvoi/video/123#kommentare", "https://www.tiktok.com/@konvoi/video/123", "tiktok"),
])
def test_bekannte_dienste_bereinigt(roh, url, dienst):
    assert al.bereinigen(roh) == al.Link(url=url, dienst=dienst)


@pytest.mark.parametrize("roh", [
    "https://instagram.com.example.org/p/1",
    "https://fakeinstagram.com/p/1",
    "https://user:pass@instagram.com/p/1",
    "https://instagram.com:8443/p/1",
    "ftp://instagram.com/p/1",
    "https://example.org/?u=https%3A%2F%2Finstagram.com",
    "https://instagram.com/" + "a" * 400,
])
def test_alles_andere_ist_kein_link_beitrag(roh):
    assert al.bereinigen(roh) is None


def test_finden_nimmt_den_ersten_bekannten_und_laesst_den_text():
    link, rest = al.finden(
        "Unser Reel vom Grenzübergang: https://www.instagram.com/reel/XyZ/?igsh=abc. Danke!"
    )
    assert link.url == "https://www.instagram.com/reel/XyZ/"
    assert rest == "Unser Reel vom Grenzübergang: Danke!"
    assert al.finden("nur Text") is None
    assert al.finden("https://example.org/irgendwas") is None


def test_dienste_wie_im_check_der_datenbank():
    assert tuple(al.DIENSTE) == LINK_DIENSTE
    assert set(al.NAMEN) == set(LINK_DIENSTE)


# ── Durch den Bot ──────────────────────────────────────────────────────────


async def _links(seite_id) -> list[PublicTrackerPost]:
    return [p for p in await _beitraege(seite_id) if p.link_url]


async def test_link_wird_beitrag_mit_karte(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("Schaut mal https://www.instagram.com/p/Abc/?igsh=geteilt-von-jonas"))
    [post] = await _links(seite)
    assert (post.link_url, post.link_dienst, post.status) == ("https://www.instagram.com/p/Abc/", "instagram", "wartet")
    assert post.text_public == "Schaut mal"
    assert post.photos == []
    karte = telegram.gesendet("sendMessage")[-1]
    assert karte["text"].startswith("🔗 Link · Konvoi Bosnien · Instagram")
    assert "https://www.instagram.com/p/Abc/" in karte["text"]
    assert "igsh" not in karte["text"]
    assert karte["reply_markup"]["inline_keyboard"][0][0]["text"] == "✅ Freigeben"


async def test_fremde_adresse_und_weitergeleitetes_ergeben_nichts(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _update("message", _nachricht("https://example.org/instagram.com/p/1"))
    await _update("message", _nachricht(
        "https://www.instagram.com/p/Abc/", forward_origin={"type": "user"}
    ))
    await _update("message", _nachricht("Wir sind in Ungarn"))
    assert await _links(seite) == []


async def test_als_antwort_auf_ein_foto_mit_dessen_zeit(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    vorher = datetime.now(timezone.utc) - timedelta(hours=2)
    foto = _foto(caption="Grenze", date=int(vorher.timestamp()))
    await _update("message", foto)
    [bild] = await _beitraege(seite)
    # Auf die Karte des Bots geantwortet zählt wie auf das Foto selbst.
    for bezug in (foto["message_id"], bild.card_message_id):
        await _update("message", _nachricht(
            "https://youtu.be/xyz", reply_to_message={"message_id": bezug, "chat": {"id": GRUPPE}}
        ))
    links = await _links(seite)
    assert len(links) == 2
    assert all(p.taken_at == bild.taken_at for p in links)


async def test_freigegebener_link_bleibt_wie_er_ist(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _presse(seite, von=900)
    n = _nachricht("Konvoi im Fernsehen https://www.youtube.com/watch?v=abc")
    await _update("message", n)
    [post] = await _links(seite)
    await _update("callback_query", _knopf(post, "frei", von=900))
    await _update("edited_message", {**n, "text": "Ganz anders https://www.tiktok.com/@x/video/1"})
    [post] = await _links(seite)
    assert post.status == "freigegeben"
    assert post.link_url == "https://www.youtube.com/watch?v=abc"
    assert post.text_public == "Konvoi im Fernsehen"
    assert post.text_raw == "Ganz anders"  # intern, für den Hinweis auf der Karte


async def test_datenbank_nimmt_keinen_fremden_dienst(aktion, seite):
    async with AsyncSessionLocal() as db:
        db.add(PublicTrackerPost(
            public_id=uuid.uuid4().hex, tracker_id=seite, convoy_id=aktion.convoy_id,
            taken_at=datetime.now(timezone.utc), status="wartet",
            link_url="https://example.org/", link_dienst="example",
        ))
        with pytest.raises(IntegrityError):
            await db.commit()


# ── Hinaus ─────────────────────────────────────────────────────────────────


async def test_freigegebener_link_geht_hinaus_ohne_bilder(aktion, client, seite, telegram):
    jetzt = datetime.now(timezone.utc)
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 300))
    async with AsyncSessionLocal() as db:
        for status, minuten in (("freigegeben", 180), ("wartet", 180), ("freigegeben", 30)):
            db.add(PublicTrackerPost(
                public_id=uuid.uuid4().hex[:22], tracker_id=seite, convoy_id=aktion.convoy_id,
                taken_at=jetzt - timedelta(minutes=minuten), status=status, text_public="Im Radio",
                text_raw="Im Radio, sagt Jonas", sender_name="Jonas Fahrer",
                link_url="https://www.instagram.com/p/Abc/", link_dienst="instagram",
            ))
        await db.commit()
    slug, token = await _slug_und_token(client, aktion, seite)
    r = await client.get(f"/api/public/aktion/{slug}", headers=h(token))
    assert r.status_code == 200, r.text
    [beitrag] = r.json()["convoys"][0]["posts"]
    assert beitrag["link"] == {"url": "https://www.instagram.com/p/Abc/", "dienst": "instagram"}
    assert beitrag["photos"] == []
    assert beitrag["position"] is not None
    assert "Jonas" not in r.text


async def _slug_und_token(client, aktion, seite_id):
    """Das Fixture `seite` gibt nur die Kennung; Slug und Token kommen mit einem neuen Token."""
    r = await client.post(f"/api/org/aktionsseiten/{seite_id}/token", headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    return r.json()["slug"], r.json()["fetch_token"]
