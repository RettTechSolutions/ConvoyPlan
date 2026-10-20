"""Aktionsseite: ``/ab`` — die Presse terminiert einen Beitrag später, nie früher.

Plan § 3.5. Erst das Lesen der Zeit ohne Datenbank (deutsche Ortszeit, das
nächste 18:00, höchstens sieben Tage), dann durch den Bot und den Org-Admin:
nur die Presse dieser Seite, nur vor der Veröffentlichung, und eine Zeit vor
der Regelzeit ist kein Fehler, sondern einfach die Regelzeit.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.public_tracker import PublicTrackerPost
from app.services import aktionsseite_telegram as tg
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

# Ein Wintertag in Berlin: 16:00 Uhr Ortszeit (MEZ, UTC+1).
JETZT = datetime(2026, 12, 27, 15, 0, tzinfo=timezone.utc)


def _ortszeit(t: datetime) -> str:
    return t.astimezone(tg.ZEITZONE).strftime("%d.%m.%Y %H:%M")


# ── Lesen ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("arg, erwartet", [
    ("18:00", "27.12.2026 18:00"),
    ("18.30", "27.12.2026 18:30"),
    ("18:00 Uhr", "27.12.2026 18:00"),
    # Schon vorbei heute: das nächste, also morgen.
    ("08:00", "28.12.2026 08:00"),
    ("29.12. 09:15", "29.12.2026 09:15"),
    ("2.1.2027 10:00", "02.01.2027 10:00"),
])
def test_termin_in_ortszeit(arg, erwartet):
    assert _ortszeit(tg.termin_lesen(arg, JETZT)) == erwartet


def test_jahreswechsel_ohne_jahr():
    silvester = datetime(2026, 12, 31, 20, 0, tzinfo=timezone.utc)
    assert _ortszeit(tg.termin_lesen("2.1. 10:00", silvester)) == "02.01.2027 10:00"


@pytest.mark.parametrize("arg", ["morgen", "25:00", "31.2. 10:00", "10.1.2027 10:00", ""])
def test_unlesbar_oder_zu_weit(arg):
    with pytest.raises(tg.TerminFehler):
        tg.termin_lesen(arg, JETZT)


def test_strich_nimmt_den_termin_weg():
    assert tg.termin_lesen("-", JETZT) is None


# ── Durch den Bot ──────────────────────────────────────────────────────────


async def _foto_mit_karte(aktion, seite_id, vor_min: int = 30) -> PublicTrackerPost:
    await _verbunden(aktion, seite_id)
    t = datetime.now(timezone.utc) - timedelta(minutes=vor_min)
    await _update("message", _foto(caption="Grenze", date=int(t.timestamp())))
    return (await _beitraege(seite_id))[-1]


def _ab(post, arg: str, von: int) -> dict:
    return _nachricht(f"/ab {arg}", von=von, reply_to_message={"message_id": post.card_message_id})


async def test_presse_terminiert_und_die_karte_sagt_es(aktion, seite, telegram):
    post = await _foto_mit_karte(aktion, seite)
    await _presse(seite, von=900)
    await _update("callback_query", _knopf(post, "frei", von=900))
    termin = (datetime.now(timezone.utc) + timedelta(hours=5)).astimezone(tg.ZEITZONE)
    await _update("message", _ab(post, termin.strftime("%d.%m.%Y %H:%M"), von=900))
    [post] = await _beitraege(seite)
    assert post.not_before == termin.replace(second=0, microsecond=0)
    assert "Termin gesetzt" in telegram.gesendet("sendMessage")[-1]["text"]
    karte = telegram.gesendet("editMessageText")[-1]["text"]
    # Mit Datum, wenn der Termin nicht heute ist — wie die Karte selbst rechnet.
    assert f"erscheint frühestens {tg._uhrzeit(termin, datetime.now(timezone.utc))}" in karte
    assert "Termin der Presse" in karte
    async with AsyncSessionLocal() as db:
        eintrag = (await db.execute(
            select(AuditLog).where(AuditLog.action == tg.AUDIT_TERMIN)
        )).scalars().all()
    assert eintrag and eintrag[-1].detail["name"] == "Person900"

    await _update("message", _ab(post, "-", von=900))
    [post] = await _beitraege(seite)
    assert post.not_before is None


async def test_frueher_als_die_regeln_ist_die_regelzeit(aktion, seite, telegram):
    post = await _foto_mit_karte(aktion, seite)
    await _presse(seite, von=900)
    # Verzögerung 120 min, Foto vor 30 min: frühestens in 90 Minuten.
    bald = (datetime.now(timezone.utc) + timedelta(minutes=20)).astimezone(tg.ZEITZONE)
    await _update("message", _ab(post, bald.strftime("%d.%m.%Y %H:%M"), von=900))
    [post] = await _beitraege(seite)
    assert post.not_before is None
    assert "Früher als die Verzögerung geht nicht" in telegram.gesendet("sendMessage")[-1]["text"]


async def test_nur_die_presse_und_nur_vor_der_veroeffentlichung(aktion, seite, telegram):
    post = await _foto_mit_karte(aktion, seite)
    await _update("message", _ab(post, "23:59", von=7))
    assert (await _beitraege(seite))[0].not_before is None
    assert telegram.gesendet("sendMessage")[-1]["text"] == "Terminieren darf nur die Presse."

    await _presse(seite, von=900)
    async with AsyncSessionLocal() as db:
        p = await db.get(PublicTrackerPost, post.id)
        p.status, p.public_since = "freigegeben", datetime.now(timezone.utc)
        await db.commit()
    await _update("message", _ab(post, "23:59", von=900))
    assert (await _beitraege(seite))[0].not_before is None
    assert "schon öffentlich" in telegram.gesendet("sendMessage")[-1]["text"]


async def test_ohne_antwort_auf_einen_beitrag_gibt_es_die_anleitung(aktion, seite, telegram):
    await _verbunden(aktion, seite)
    await _presse(seite, von=900)
    await _update("message", _nachricht("/ab 18:00", von=900))
    assert telegram.gesendet("sendMessage")[-1]["text"] == tg.TEXT_AB_HILFE


# ── Hinaus und im Org-Admin ────────────────────────────────────────────────


async def test_terminierter_beitrag_bleibt_draussen_bis_zum_termin(aktion, client, seite, telegram):
    jetzt = datetime.now(timezone.utc)
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 300))
    async with AsyncSessionLocal() as db:
        post = PublicTrackerPost(
            public_id=uuid.uuid4().hex[:22], tracker_id=seite, convoy_id=aktion.convoy_id,
            taken_at=jetzt - timedelta(hours=3), status="freigegeben", text_public="Pressekonferenz",
            link_url="https://www.instagram.com/p/Abc/", link_dienst="instagram",
        )
        db.add(post)
        await db.commit()
        post_id = post.id
    r = await client.post(f"/api/org/aktionsseiten/{seite}/token", headers=h(aktion.admin))
    slug, token = r.json()["slug"], r.json()["fetch_token"]

    async def texte():
        a = await client.get(f"/api/public/aktion/{slug}", headers=h(token))
        return [p["text"] for p in a.json()["convoys"][0]["posts"]]

    assert await texte() == ["Pressekonferenz"]
    # Terminieren im Org-Admin wirkt sofort, nicht erst nach dem Zwischenspeicher.
    spaeter = (jetzt + timedelta(hours=2)).isoformat()
    r = await client.put(
        f"/api/org/aktionsseiten/{seite}/beitraege/{post_id}",
        json={"not_before": spaeter}, headers=h(aktion.admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["not_before"] is not None
    assert await texte() == []
    r = await client.put(
        f"/api/org/aktionsseiten/{seite}/beitraege/{post_id}",
        json={"not_before": None}, headers=h(aktion.admin),
    )
    assert await texte() == ["Pressekonferenz"]


async def test_org_admin_grenzen(aktion, client, seite, telegram):
    post = await _foto_mit_karte(aktion, seite)
    pfad = f"/api/org/aktionsseiten/{seite}/beitraege/{post.id}"
    weit = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()
    assert (await client.put(pfad, json={"not_before": weit}, headers=h(aktion.admin))).status_code == 422
    frueh = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    r = await client.put(pfad, json={"not_before": frueh}, headers=h(aktion.admin))
    assert r.status_code == 200 and r.json()["not_before"] is None
    async with AsyncSessionLocal() as db:
        p = await db.get(PublicTrackerPost, post.id)
        p.status, p.public_since = "freigegeben", datetime.now(timezone.utc)
        await db.commit()
    spaeter = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    assert (await client.put(pfad, json={"not_before": spaeter}, headers=h(aktion.admin))).status_code == 409
