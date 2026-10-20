"""Aktionsseite: freigegebene Beiträge in der öffentlichen Antwort.

Durch die App, mit Datenbank. Die Regeln selbst prüft
``test_aktionsseite_beitraege.py`` ohne Datenbank; hier geht es darum, dass
genau sie gelten: In der Antwort steht nur, was freigegeben **und** sichtbar
ist, mit der Position aus dem Verlauf und ohne Absender oder Telegram-Text.
Ein Bild gibt es nur, solange sein Beitrag in dieser Antwort steht — wer die
Kennung kennt, bekommt es vorher trotzdem nicht.
"""
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.public_tracker import (
    PublicTrackerPhoto,
    PublicTrackerPhotoData,
    PublicTrackerPost,
    PublicTrackerTelegram,
)
from app.services import aktionsseite_telegram as tg
from app.services.crypto import encrypt_secret
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    fahrt,
    h,
    reset_db_engine,
    seite_anlegen,
    verlauf,
)

GRUPPE = -100777


class Telegram:
    def __init__(self):
        self.aufrufe: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        methode = request.url.path.rsplit("/", 1)[-1]
        self.aufrufe.append((methode, json.loads(request.content or b"{}")))
        return httpx.Response(200, json={"ok": True, "result": True})

    def karten(self) -> list[str]:
        return [d["text"] for m, d in self.aufrufe if m == "editMessageText"]


@pytest.fixture
def telegram(monkeypatch):
    t = Telegram()
    monkeypatch.setattr(tg, "transport", httpx.MockTransport(t))
    return t


async def _beitrag(seite_id, convoy_id, t: datetime, status="freigegeben", text="Grenze geschafft",
                   **mehr) -> tuple[PublicTrackerPost, str]:
    async with AsyncSessionLocal() as db:
        p = PublicTrackerPost(
            public_id=secrets.token_urlsafe(16), tracker_id=seite_id, convoy_id=convoy_id,
            taken_at=t, status=status, text_raw="Wir stehen an der A3 bei Würzburg",
            text_public=text, sender_telegram_id=4711, sender_name="Jonas Fahrer",
            chat_id=GRUPPE, message_id=secrets.randbelow(10**9), card_message_id=99, **mehr,
        )
        foto = PublicTrackerPhoto(public_id=secrets.token_urlsafe(16), position=0, width=4, height=3)
        p.photos.append(foto)
        db.add(p)
        await db.flush()
        db.add(PublicTrackerPhotoData(photo_id=foto.id, gross=b"RIFFgross", klein=b"RIFFklein"))
        await db.commit()
        return p, foto.public_id


@pytest.fixture
async def lage(aktion, client):
    """Eine Seite, 5 h Fahrt nach Osten bis jetzt, und vier Beiträge:
    freigegeben vor 3 h (sichtbar), freigegeben vor 1 h (noch zu jung),
    wartend und abgelehnt (beide vor 3 h)."""
    seite = await seite_anlegen(client, aktion)
    sid = uuid.UUID(seite["id"])
    jetzt = datetime.now(timezone.utc)
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 300))
    vor3 = jetzt - timedelta(hours=3)
    sichtbar = await _beitrag(sid, aktion.convoy_id, vor3)
    zu_jung = await _beitrag(sid, aktion.convoy_id, jetzt - timedelta(hours=1))
    wartend = await _beitrag(sid, aktion.convoy_id, vor3, status="wartet")
    abgelehnt = await _beitrag(sid, aktion.convoy_id, vor3, status="abgelehnt")
    return {
        "seite": seite, "id": sid, "jetzt": jetzt, "vor3": vor3, "sichtbar": sichtbar,
        "zu_jung": zu_jung, "wartend": wartend, "abgelehnt": abgelehnt,
    }


async def _abruf(client, seite):
    r = await client.get(
        f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"])
    )
    assert r.status_code == 200, r.text
    return r


async def _bild(client, seite, bild_id, token=None, groesse="gross"):
    return await client.get(
        f"/api/public/aktion/{seite['slug']}/bild/{bild_id}/{groesse}.webp",
        headers=h(token or seite["fetch_token"]),
    )


# ── Öffentliche Antwort ────────────────────────────────────────────────────


async def test_nur_freigegeben_und_sichtbar_mit_position_aus_dem_verlauf(aktion, client, lage):
    r = await _abruf(client, lage["seite"])
    [konvoi] = r.json()["convoys"]
    [beitrag] = konvoi["posts"]
    post, bild_id = lage["sichtbar"]
    assert beitrag["id"] == post.public_id
    assert beitrag["text"] == "Grenze geschafft"
    assert beitrag["photos"] == [{"id": bild_id, "width": 4, "height": 3}]
    assert beitrag["coarse"] is False
    # Auf der Fahrt nach Osten: vor 3 h, also 180 Punkte vor dem letzten.
    assert beitrag["position"]["lat"] == pytest.approx(48.5)
    assert beitrag["position"]["lon"] == pytest.approx(12.1 + 119 * 0.01, abs=0.02)


async def test_nichts_aus_telegram_geht_hinaus(aktion, client, lage):
    text_ = (await _abruf(client, lage["seite"])).text
    for geheim in ("Jonas", "A3 bei Würzburg", "4711", str(lage["sichtbar"][0].id), str(GRUPPE)):
        assert geheim not in text_, geheim


async def test_bild_nur_solange_sein_beitrag_in_der_antwort_steht(aktion, client, lage):
    seite = lage["seite"]
    r = await _bild(client, seite, lage["sichtbar"][1])
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert r.content == b"RIFFgross"
    assert (await _bild(client, seite, lage["sichtbar"][1], groesse="klein")).content == b"RIFFklein"
    # Zu jung, wartend, abgelehnt: dieselbe 404 wie für eine erfundene Kennung.
    for _, bild_id in (lage["zu_jung"], lage["wartend"], lage["abgelehnt"]):
        assert (await _bild(client, seite, bild_id)).status_code == 404
    assert (await _bild(client, seite, "erfunden")).status_code == 404
    # Falsches Token: auch das sichtbare nicht.
    assert (await _bild(client, seite, lage["sichtbar"][1], token="falsch")).status_code == 404


async def test_bild_einer_anderen_seite_gibt_es_hier_nicht(aktion, client, lage):
    andere = await seite_anlegen(client, aktion, title="Andere Seite")
    assert (await _bild(client, andere, lage["sichtbar"][1])).status_code == 404


# ── „Öffentlich seit" ──────────────────────────────────────────────────────


async def test_oeffentlich_seit_wird_gesetzt_und_die_karte_sagt_es(aktion, client, lage, telegram):
    async with AsyncSessionLocal() as db:
        db.add(PublicTrackerTelegram(
            organization_id=aktion.org_id, bot_token_enc=encrypt_secret("1:x" * 8), status="bereit",
        ))
        await db.commit()
    assert await tg.oeffentlich_markieren() >= 1
    async with AsyncSessionLocal() as db:
        seit = {
            p.public_id: p.public_since
            for p in (await db.execute(
                select(PublicTrackerPost).where(PublicTrackerPost.tracker_id == lage["id"])
            )).scalars()
        }
    assert seit[lage["sichtbar"][0].public_id] is not None
    assert seit[lage["zu_jung"][0].public_id] is None
    assert seit[lage["wartend"][0].public_id] is None
    assert any("Öffentlich seit" in k for k in telegram.karten())


# ── Org-Admin ──────────────────────────────────────────────────────────────


async def test_beitragsliste_zeigt_alles_mit_internem(aktion, client, lage):
    r = await client.get(f"/api/org/aktionsseiten/{lage['id']}/beitraege", headers=h(aktion.admin))
    assert r.status_code == 200
    assert len(r.json()) == 4
    assert r.json()[0]["sender_name"] == "Jonas Fahrer"
    r = await client.get(
        f"/api/org/aktionsseiten/{lage['id']}/beitraege?status=wartet", headers=h(aktion.admin)
    )
    [wartend] = r.json()
    foto = wartend["photos"][0]["id"]
    r = await client.get(
        f"/api/org/aktionsseiten/{lage['id']}/bilder/{foto}/klein.webp", headers=h(aktion.admin)
    )
    assert r.status_code == 200 and r.content == b"RIFFklein"


async def test_zurueckziehen_im_org_admin_wirkt_sofort(aktion, client, lage, telegram):
    async with AsyncSessionLocal() as db:
        db.add(PublicTrackerTelegram(
            organization_id=aktion.org_id, bot_token_enc=encrypt_secret("1:x" * 8), status="bereit",
        ))
        await db.commit()
    seite = lage["seite"]
    post, bild_id = lage["sichtbar"]
    assert (await _abruf(client, seite)).json()["convoys"][0]["posts"]  # im Zwischenspeicher

    r = await client.put(
        f"/api/org/aktionsseiten/{lage['id']}/beitraege/{post.id}",
        json={"aktion": "zurueck"}, headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "zurueckgezogen"
    # Nicht erst nach der Minute im Zwischenspeicher.
    assert (await _abruf(client, seite)).json()["convoys"][0]["posts"] == []
    assert (await _bild(client, seite, bild_id)).status_code == 404
    assert "Zurückgezogen" in telegram.karten()[-1]

    # Zweimal zurückziehen: Schon erledigt.
    r = await client.put(
        f"/api/org/aktionsseiten/{lage['id']}/beitraege/{post.id}",
        json={"aktion": "zurueck"}, headers=h(aktion.admin),
    )
    assert r.status_code == 409


async def test_text_aendern_und_freigeben_im_org_admin(aktion, client, lage):
    post, _ = lage["wartend"]
    r = await client.put(
        f"/api/org/aktionsseiten/{lage['id']}/beitraege/{post.id}",
        json={"aktion": "frei", "text_public": "Unterwegs nach Süden"}, headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "freigegeben"
    assert r.json()["text_public"] == "Unterwegs nach Süden"
    texte = [p["text"] for p in (await _abruf(client, lage["seite"])).json()["convoys"][0]["posts"]]
    assert "Unterwegs nach Süden" in texte


async def test_beitraege_nur_fuer_org_admins(aktion, client, lage):
    post, _ = lage["wartend"]
    for methode, pfad, body in [
        ("get", f"/api/org/aktionsseiten/{lage['id']}/beitraege", None),
        ("put", f"/api/org/aktionsseiten/{lage['id']}/beitraege/{post.id}", {"aktion": "frei"}),
        ("get", f"/api/org/aktionsseiten/{lage['id']}/bilder/{uuid.uuid4()}/gross.webp", None),
    ]:
        r = await client.request(methode, pfad, json=body, headers=h(aktion.fahrer))
        assert r.status_code == 403, (methode, pfad)
