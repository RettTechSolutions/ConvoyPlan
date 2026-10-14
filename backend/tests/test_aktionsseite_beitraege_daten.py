"""Aktionsseite: was die Datenbank für Beiträge zusagt.

Beiträge, Gruppen und Codes hängen am Konvoi einer Seite. Das heißt zweierlei:
Fällt ein Konvoi aus der Seite, fallen seine Beiträge mit — und **nur** dann.
Ein neuer Titel der Seite darf nichts löschen; bis Schritt 2 hat das
Bearbeiten alle Konvoi-Zeilen ersetzt, was mit Beiträgen daran genau das
getan hätte. Dazu die Regeln, die nicht vom Code abhängen sollen: ein Chat
gehört einem Konvoi, eine Nachricht ergibt einen Beitrag, und die Retention
räumt nach ihren Fristen.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.models.public_tracker import (
    PublicTrackerChat,
    PublicTrackerCode,
    PublicTrackerPhoto,
    PublicTrackerPhotoData,
    PublicTrackerPost,
    PublicTrackerPresse,
)
from app.services import retention
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    h,
    reset_db_engine,
    seite_anlegen,
)

JETZT = datetime.now(timezone.utc)


def _pid() -> str:
    return secrets.token_urlsafe(16)


async def _anhaengen(seite_id, convoy_id, **post) -> uuid.UUID:
    """Ein Beitrag mit Bild und Bytes, eine Gruppe, ein Presse-Eintrag und ein
    Code zum Verbinden — alles, was an einer Seite hängen kann."""
    async with AsyncSessionLocal() as db:
        p = PublicTrackerPost(
            public_id=_pid(), tracker_id=seite_id, convoy_id=convoy_id,
            taken_at=post.pop("taken_at", JETZT), **post,
        )
        p.photos.append(PublicTrackerPhoto(public_id=_pid(), position=0, width=4, height=3))
        db.add(p)
        await db.flush()
        db.add(PublicTrackerPhotoData(photo_id=p.photos[0].id, gross=b"g", klein=b"k"))
        await db.commit()
        return p.id


async def _zahlen(seite_id) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        async def n(stmt):
            return (await db.execute(stmt)).scalar_one()

        return {
            "beitraege": await n(
                select(func.count()).select_from(PublicTrackerPost)
                .where(PublicTrackerPost.tracker_id == seite_id)
            ),
            "bilder": await n(
                select(func.count()).select_from(PublicTrackerPhoto)
                .join(PublicTrackerPost).where(PublicTrackerPost.tracker_id == seite_id)
            ),
            "bytes": await n(
                select(func.count()).select_from(PublicTrackerPhotoData)
                .join(PublicTrackerPhoto).join(PublicTrackerPost)
                .where(PublicTrackerPost.tracker_id == seite_id)
            ),
            "gruppen": await n(
                select(func.count()).select_from(PublicTrackerChat)
                .where(PublicTrackerChat.tracker_id == seite_id)
            ),
            "presse": await n(
                select(func.count()).select_from(PublicTrackerPresse)
                .where(PublicTrackerPresse.tracker_id == seite_id)
            ),
            "codes": await n(
                select(func.count()).select_from(PublicTrackerCode)
                .where(PublicTrackerCode.tracker_id == seite_id)
            ),
        }


async def _alles_an_die_seite(seite_id, convoy_id):
    await _anhaengen(seite_id, convoy_id, chat_id=-100123, message_id=1)
    async with AsyncSessionLocal() as db:
        db.add_all([
            PublicTrackerChat(tracker_id=seite_id, convoy_id=convoy_id, chat_id=-100123),
            PublicTrackerPresse(tracker_id=seite_id, telegram_user_id=4711, display_name="Anna"),
            PublicTrackerCode(
                code_hash=secrets.token_hex(32), tracker_id=seite_id, convoy_id=convoy_id,
                art="verbinden", expires_at=JETZT + timedelta(minutes=15),
            ),
        ])
        await db.commit()


def _seite_body(aktion, **felder):
    return {
        "title": "Weihnachtskonvois 2026",
        "theme": "weihnachten",
        "delay_minutes": 120,
        "convoys": [{"convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Bosnien"}],
        **felder,
    }


# ── Was an einer Seite hängt ───────────────────────────────────────────────


async def test_seite_bearbeiten_laesst_beitraege_und_gruppen_stehen(aktion, client):
    seite = await seite_anlegen(client, aktion)
    sid = uuid.UUID(seite["id"])
    await _alles_an_die_seite(sid, aktion.convoy_id)

    r = await client.put(
        f"/api/org/aktionsseiten/{sid}",
        json=_seite_body(aktion, title="Neuer Titel", convoys=[
            {"convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Tuzla", "color": "#ff8a65"},
        ]),
        headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["convoys"][0]["display_name"] == "Konvoi Tuzla"
    assert await _zahlen(sid) == {
        "beitraege": 1, "bilder": 1, "bytes": 1, "gruppen": 1, "presse": 1, "codes": 1,
    }


async def test_konvoi_aus_der_seite_nimmt_seine_beitraege_mit(aktion, client):
    seite = await seite_anlegen(client, aktion)
    sid = uuid.UUID(seite["id"])
    await _alles_an_die_seite(sid, aktion.convoy_id)

    r = await client.put(
        f"/api/org/aktionsseiten/{sid}", json=_seite_body(aktion, convoys=[]),
        headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text
    # Die Presse gehört der Seite, nicht dem Konvoi — sie bleibt.
    assert await _zahlen(sid) == {
        "beitraege": 0, "bilder": 0, "bytes": 0, "gruppen": 0, "presse": 1, "codes": 0,
    }


async def test_seite_loeschen_nimmt_alles_mit(aktion, client):
    seite = await seite_anlegen(client, aktion)
    sid = uuid.UUID(seite["id"])
    await _alles_an_die_seite(sid, aktion.convoy_id)

    r = await client.delete(f"/api/org/aktionsseiten/{sid}", headers=h(aktion.admin))
    assert r.status_code == 204
    assert set((await _zahlen(sid)).values()) == {0}


# ── Was die Datenbank selbst ablehnt ───────────────────────────────────────


async def _scheitert(*zeilen):
    async with AsyncSessionLocal() as db:
        db.add_all(zeilen)
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_ein_chat_gehoert_genau_einem_konvoi(aktion, client):
    a = uuid.UUID((await seite_anlegen(client, aktion))["id"])
    b = uuid.UUID((await seite_anlegen(client, aktion, title="Zweite Seite"))["id"])
    async with AsyncSessionLocal() as db:
        db.add(PublicTrackerChat(tracker_id=a, convoy_id=aktion.convoy_id, chat_id=-1001))
        # Dieselbe Gruppe, aber zwei Themen — das geht, auch für zwei Seiten.
        db.add(PublicTrackerChat(tracker_id=b, convoy_id=aktion.convoy_id, chat_id=-1002, thread_id=7))
        await db.commit()
    # Dieselbe ganze Gruppe ein zweites Mal …
    await _scheitert(PublicTrackerChat(tracker_id=b, convoy_id=aktion.convoy_id, chat_id=-1001))
    # … dasselbe Thema ein zweites Mal …
    await _scheitert(
        PublicTrackerChat(tracker_id=a, convoy_id=aktion.convoy_id, chat_id=-1002, thread_id=7)
    )
    # … und ein zweiter Chat für denselben Konvoi derselben Seite.
    await _scheitert(PublicTrackerChat(tracker_id=a, convoy_id=aktion.convoy_id, chat_id=-1003))


async def test_eine_nachricht_ergibt_einen_beitrag(aktion, client):
    """Telegram liefert unter Umständen doppelt, ein Album als mehrere Updates."""
    sid = uuid.UUID((await seite_anlegen(client, aktion))["id"])
    await _anhaengen(sid, aktion.convoy_id, chat_id=-1001, message_id=10)
    await _anhaengen(sid, aktion.convoy_id, chat_id=-1001, message_id=11, media_group_id="album-1")

    def neu(**kw):
        return PublicTrackerPost(
            public_id=_pid(), tracker_id=sid, convoy_id=aktion.convoy_id, taken_at=JETZT, **kw
        )

    await _scheitert(neu(chat_id=-1001, message_id=10))
    await _scheitert(neu(chat_id=-1001, message_id=12, media_group_id="album-1"))


async def test_unbekannter_status_und_zu_langer_text_scheitern(aktion, client):
    sid = uuid.UUID((await seite_anlegen(client, aktion))["id"])

    def neu(**kw):
        return PublicTrackerPost(
            public_id=_pid(), tracker_id=sid, convoy_id=aktion.convoy_id, taken_at=JETZT, **kw
        )

    await _scheitert(neu(status="oeffentlich"))
    await _scheitert(neu(text_public="x" * 501))


async def test_verbinden_braucht_einen_konvoi_presse_keinen(aktion, client):
    sid = uuid.UUID((await seite_anlegen(client, aktion))["id"])
    bald = JETZT + timedelta(minutes=15)

    def code(**kw):
        return PublicTrackerCode(code_hash=secrets.token_hex(32), tracker_id=sid, expires_at=bald, **kw)

    await _scheitert(code(art="verbinden"))
    await _scheitert(code(art="presse", convoy_id=aktion.convoy_id))
    await _scheitert(code(art="egal"))


# ── Retention ──────────────────────────────────────────────────────────────


async def test_retention_raeumt_nach_ihren_fristen(aktion, client):
    sid = uuid.UUID((await seite_anlegen(client, aktion))["id"])
    cid = aktion.convoy_id
    tage = timedelta(days=1)
    weg = [
        # Älter als der Verlauf, nach dem er platziert würde.
        await _anhaengen(sid, cid, status="freigegeben", taken_at=JETZT - 50 * tage),
        await _anhaengen(sid, cid, status="abgelehnt", updated_at=JETZT - 8 * tage),
        await _anhaengen(sid, cid, status="zurueckgezogen", updated_at=JETZT - 8 * tage),
        await _anhaengen(sid, cid, status="wartet", created_at=JETZT - 31 * tage),
    ]
    bleibt = [
        await _anhaengen(sid, cid, status="freigegeben", taken_at=JETZT - 10 * tage),
        await _anhaengen(sid, cid, status="abgelehnt", updated_at=JETZT - 2 * tage),
        await _anhaengen(sid, cid, status="wartet", created_at=JETZT - 5 * tage),
    ]
    async with AsyncSessionLocal() as db:
        db.add_all([
            PublicTrackerCode(
                code_hash="a" * 64, tracker_id=sid, art="presse", expires_at=JETZT - tage
            ),
            PublicTrackerCode(
                code_hash="b" * 64, tracker_id=sid, art="presse", expires_at=JETZT + tage
            ),
        ])
        await db.commit()

    async with AsyncSessionLocal() as db:
        assert await retention.purge_old_beitraege(db, 45) >= len(weg)
        assert await retention.purge_expired_beitrag_codes(db) >= 1
        await db.commit()

    async with AsyncSessionLocal() as db:
        uebrig = set(
            (await db.execute(
                select(PublicTrackerPost.id).where(PublicTrackerPost.tracker_id == sid)
            )).scalars().all()
        )
        codes = set(
            (await db.execute(
                select(PublicTrackerCode.code_hash).where(PublicTrackerCode.tracker_id == sid)
            )).scalars().all()
        )
    assert uebrig == set(bleibt)
    assert codes == {"b" * 64}
    # Bilder und Bytes fallen mit ihrem Beitrag.
    assert (await _zahlen(sid))["bytes"] == len(bleibt)
