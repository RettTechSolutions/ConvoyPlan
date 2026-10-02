"""Aktionsseite: was hinausgeht, ist mindestens ``delay_minutes`` alt.

Die Zusagen:

- Kein ausgelieferter Punkt ist jünger als die Stichzeit — auch nicht in der
  gefahrenen Linie, auch nicht in der Vorschau des Org-Admins.
- Weniger als 60 Minuten lassen sich nicht einstellen.
- Unbekannt, abgeschaltet, abgelaufen, ohne oder mit falschem Token: dieselbe
  404. Keine Antwort verrät, dass es den Slug gibt.
- Ein erneuertes Token gilt sofort, das alte nicht mehr — auch nicht aus dem
  Zwischenspeicher.
"""
from datetime import datetime, timedelta, timezone

from app.services import aktionsseite as a
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    fahrt,
    h,
    reset_db_engine,
    seite_anlegen,
    verlauf,
)


def test_stichzeit_hat_eine_untergrenze():
    jetzt = datetime(2026, 12, 27, 18, 0, tzinfo=timezone.utc)
    assert a.stichzeit(jetzt, 120) == jetzt - timedelta(minutes=120)
    # Was immer in der Zeile steht: unter einer Stunde wird nicht geliefert.
    assert a.stichzeit(jetzt, 5) == jetzt - timedelta(minutes=60)


async def test_kein_punkt_ist_juenger_als_die_verzoegerung(aktion, client):
    seite = await seite_anlegen(client, aktion, delay_minutes=120)
    jetzt = datetime.now(timezone.utc)
    # Drei Stunden Fahrt bis eben: die letzten zwei dürfen nicht hinaus.
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 180))

    r = await client.get(f"/api/public/aktion/{seite['slug']}", headers=h(seite["fetch_token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    stich = datetime.fromisoformat(body["as_of"])
    assert datetime.fromisoformat(body["generated_at"]) - stich == timedelta(minutes=120)

    k = body["convoys"][0]
    assert datetime.fromisoformat(k["position"]["at"]) <= stich
    # Die Linie reicht nicht weiter nach Osten als der Punkt zur Stichzeit:
    # die Fahrt läuft stetig nach Osten, ein jüngerer Punkt läge weiter rechts.
    letzter_erlaubter = max(
        lon for _, t, _, lon in fahrt(aktion.spitze, jetzt, 180) if t <= stich
    )
    assert max(lon for lon, _ in k["trail"]) <= letzter_erlaubter + 1e-6
    assert k["position"]["lon"] <= letzter_erlaubter + 1e-6


async def test_vorschau_zeigt_dieselbe_verzoegerung(aktion, client):
    seite = await seite_anlegen(client, aktion, delay_minutes=60)
    jetzt = datetime.now(timezone.utc)
    await verlauf(aktion, fahrt(aktion.spitze, jetzt, 90))

    r = await client.get(f"/api/org/aktionsseiten/{seite['id']}/vorschau", headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    body = r.json()
    k = body["convoys"][0]
    erzeugt = datetime.fromisoformat(body["generated_at"])
    assert erzeugt - datetime.fromisoformat(k["position"]["at"]) >= timedelta(minutes=60)


async def test_unter_einer_stunde_laesst_sich_nicht_einstellen(aktion, client):
    r = await client.post(
        "/api/org/aktionsseiten",
        json={"title": "Zu schnell", "delay_minutes": 59},
        headers=h(aktion.admin),
    )
    assert r.status_code == 422


async def test_nur_org_admins_verwalten_seiten(aktion, client):
    r = await client.get("/api/org/aktionsseiten", headers=h(aktion.fahrer))
    assert r.status_code == 403


async def test_fremder_konvoi_wird_abgewiesen(aktion, client):
    import uuid

    r = await client.post(
        "/api/org/aktionsseiten",
        json={"title": "X", "convoys": [{"convoy_id": str(uuid.uuid4()), "display_name": "Y"}]},
        headers=h(aktion.admin),
    )
    assert r.status_code == 422


async def test_alle_absagen_sehen_gleich_aus(aktion, client):
    seite = await seite_anlegen(client, aktion)
    url = f"/api/public/aktion/{seite['slug']}"
    absagen = [
        await client.get("/api/public/aktion/gibtesnicht", headers=h(seite["fetch_token"])),
        await client.get(url),
        await client.get(url, headers=h("falsches-token")),
    ]
    put = {
        "title": seite["title"], "delay_minutes": 120, "enabled": False,
        "convoys": [{"convoy_id": str(aktion.convoy_id), "display_name": "Konvoi Bosnien"}],
    }
    r = await client.put(f"/api/org/aktionsseiten/{seite['id']}", json=put, headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    absagen.append(await client.get(url, headers=h(seite["fetch_token"])))

    put.update(enabled=True, valid_until=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    r = await client.put(f"/api/org/aktionsseiten/{seite['id']}", json=put, headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    absagen.append(await client.get(url, headers=h(seite["fetch_token"])))

    assert {r.status_code for r in absagen} == {404}
    assert len({r.text for r in absagen}) == 1


async def test_erneuertes_token_gilt_sofort_das_alte_nicht_mehr(aktion, client):
    seite = await seite_anlegen(client, aktion)
    url = f"/api/public/aktion/{seite['slug']}"
    assert (await client.get(url, headers=h(seite["fetch_token"]))).status_code == 200

    r = await client.post(f"/api/org/aktionsseiten/{seite['id']}/token", headers=h(aktion.admin))
    assert r.status_code == 200, r.text
    neu = r.json()["fetch_token"]

    assert (await client.get(url, headers=h(seite["fetch_token"]))).status_code == 404
    assert (await client.get(url, headers=h(neu))).status_code == 200


async def test_token_steht_nur_in_der_antwort_beim_anlegen(aktion, client):
    seite = await seite_anlegen(client, aktion)
    liste = (await client.get("/api/org/aktionsseiten", headers=h(aktion.admin))).json()
    assert "fetch_token" not in liste[0]
    assert seite["fetch_token"] not in str(liste)
