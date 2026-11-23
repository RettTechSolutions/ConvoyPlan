"""Marschbefehl nach dem Muster der FwDV 100, Anlage 4.

Die Zusagen:

- Das PDF bildet Kopf, Hauptziffern 1–5 mit ihren Unterpunkten, Anlagen,
  Verteiler und Unterschrift in der Reihenfolge und mit den Begriffen der
  Dienstvorschrift ab. „Die Reihenfolge der Hauptziffern ist aber immer
  einzuhalten“ — deshalb steht jeder Punkt auch dann da, wenn nichts
  angeordnet ist (mit „-“), statt samt Nummer zu verschwinden.
- Anlagen und Verteiler tragen keine Hauptziffer; die Unterschrift fragt nach
  Name und Dienststellung.
- Was die App ableitet — Schließende/r, Platz der Führungskraft, ärztliche
  Versorgung, theoretische Durchschnittsgeschwindigkeit, die Aufteilung der
  Marschpausen in Technische Halte und Raste —, ist im PDF und in der
  Word-Vorlage derselbe Wert.
- Ein im Formular geleertes Feld wird gelöscht und bleibt nicht stehen.
"""
import io
from datetime import datetime
from types import SimpleNamespace

import pytest
from docx import Document

from app.services import marschbefehl_vorlage as mv
from app.services import pdf as pdf_svc
from tests.aktionsseite_fixtures import (  # noqa: F401 — Fixtures, per Import aktiviert
    aktion,
    client,
    h,
    reset_db_engine,
)

# Die FwDV-Punkte in der Reihenfolge der Anlage 4.
FWDV_REIHENFOLGE = [
    "Befehl für den Marsch in den Raum",
    "Karte:",
    "1. Lage",
    "Gefahren- / Schadenlage:",
    "Eigene Lage:",
    "2. Auftrag",
    "Zuteilung, Unterstellung und Abgabe von Kräften:",
    "Erhaltener Auftrag:",
    "3. Durchführung",
    "Marschziel:",
    "Marschweg:",
    "Marschentfernung:",
    "Marschform:",
    "Marschfolge:",
    "Marschführer/in:",
    "Führer/innen der Einzelgruppen:",
    "Schließende/r:",
    "Marschabstand:",
    "Fahrzeugabstand:",
    "Ablaufpunkt:",
    "Ablaufzeit:",
    "Ablaufführer/in:",
    "Marschgeschwindigkeit:",
    "Beleuchtung:",
    "Marschüberwachung und Verkehrssicherung:",
    "Marschpausen:",
    "a) Technische Halte",
    "b) Raste",
    "Besondere Einzelheiten je nach Lage:",
    "4. Versorgung",
    "Verpflegung:",
    "Betriebsstoff:",
    "Instandsetzungsdienst:",
    "Ärztliche Versorgung:",
    "5. Führung und Verbindung",
    "Kommunikationsverbindungen während des Marsches:",
    "Sonstige Verbindungen, Lotsenstellen und Verkehrsleitpunkte:",
    "Platz der Führungskraft:",
    "Anlagen",
    "Verteiler",
    "Unterschrift",
    "(Name, Dienststellung)",
]


@pytest.fixture
def gedruckt(monkeypatch):
    """Jeder Text, den das PDF setzt, in Reihenfolge."""
    texte: list[str] = []
    cell, multi_cell = pdf_svc._PDF.cell, pdf_svc._PDF.multi_cell

    def _cell(self, w=None, h=None, text="", *a, **k):
        texte.append(str(text).strip())
        return cell(self, w, h, text, *a, **k)

    def _multi_cell(self, w, h=None, text="", *a, **k):
        texte.append(str(text).strip())
        return multi_cell(self, w, h, text, *a, **k)

    monkeypatch.setattr(pdf_svc._PDF, "cell", _cell)
    monkeypatch.setattr(pdf_svc._PDF, "multi_cell", _multi_cell)
    return texte


def _leerer_konvoi(**felder):
    werte = dict(
        name="Leer", organization=None, start_time=None, lage=None, auftrag=None, marschform=None,
        ablaufpunkt=None, ablaufzeit=None, ablaufführer=None, speed_urban_kmh=40, speed_rural_kmh=65,
        spacing_urban_m=15, spacing_rural_m=50, spacing_motorway_m=100, versorgung=None,
        funkgruppe=None, anlagen=None,
    )
    werte.update(felder)
    return SimpleNamespace(**werte)


def _fz(pos, rufname, sonder=None, kennzeichen=None):
    return {
        "name": f"Fz {pos}", "callsign": rufname, "license_plate": kennzeichen, "height_cm": None,
        "weight_kg": None, "convoy_role": None, "position": pos, "sonderfunktion": sonder,
        "mobile_phone": None,
    }


def _index(texte: list[str], marke: str) -> int:
    for i, t in enumerate(texte):
        if t.startswith(marke) or f"  {marke}" in t or t == marke:
            return i
    raise AssertionError(f"„{marke}“ fehlt im PDF")


# ── Gliederung ───────────────────────────────────────────────────────────


def test_pdf_folgt_der_gliederung_der_fwdv(gedruckt):
    """Auch der leere Konvoi zeigt jeden Punkt, in FwDV-Reihenfolge."""
    assert pdf_svc.generate_marschbefehl(_leerer_konvoi(), [], [], None).startswith(b"%PDF-")
    texte = [t.strip() for t in gedruckt]
    positionen = [_index(texte, m) for m in FWDV_REIHENFOLGE]
    assert positionen == sorted(positionen), [
        (m, p) for m, p in zip(FWDV_REIHENFOLGE, positionen)
    ]


def test_anlagen_und_verteiler_ohne_hauptziffer(gedruckt):
    pdf_svc.generate_marschbefehl(_leerer_konvoi(anlagen="Roadbook"), [], [], None)
    text = "\n".join(gedruckt)
    assert "6. Anlagen" not in text
    assert "Anlagen" in gedruckt and "Verteiler" in gedruckt
    assert "Roadbook" in text
    # Die alte Zeile gibt es nicht mehr.
    assert "Unterschrift Marschverbandsführer/in" not in text
    assert "Marschstrecke" not in text


def test_kopf_nennt_abgang_raum_und_karte(gedruckt):
    konvoi = _leerer_konvoi(organization="KBI Musterstadt", abgangsort="Musterstadt", karte="TK 1:50 000")
    wegpunkte = [{"name": "Feuerwache", "type": "waypoint"}, {"name": "BR Grafschaft", "type": "stop"}]
    pdf_svc.generate_marschbefehl(konvoi, wegpunkte, [], None, jetzt=datetime(2026, 11, 13, 18, 5))
    text = "\n".join(gedruckt)
    assert "KBI Musterstadt" in text
    assert "Musterstadt, 13.11.2026, 18:05 Uhr" in text
    # Ohne eigenen Raum gilt das Marschziel.
    assert "Befehl für den Marsch in den Raum BR Grafschaft" in text
    assert "Karte: TK 1:50 000" in text


def test_freitexte_stehen_unter_ihrem_fwdv_punkt(gedruckt):
    konvoi = _leerer_konvoi(
        lage="Hochwasser", lage_eigene="Zug einsatzbereit", kraefte="Unterstellt EL Ahr",
        auftrag="Verlegung", marschfuehrer="BI Muster", marschueberwachung="Lotse AS 12",
        verpflegung="EPa", instandsetzung="WLF", verbindungen="Lotsenstelle AS 12",
        verteiler="Alle Fahrzeugführer", unterschrift_name="M. Muster",
        unterschrift_dienststellung="Kreisbrandinspektor", versorgung="Altbestand",
    )
    pdf_svc.generate_marschbefehl(konvoi, [], [], None)
    texte = gedruckt
    for punkt, wert in [
        ("Gefahren- / Schadenlage:", "Hochwasser"),
        ("Eigene Lage:", "Zug einsatzbereit"),
        ("Zuteilung, Unterstellung und Abgabe von Kräften:", "Unterstellt EL Ahr"),
        ("Erhaltener Auftrag:", "Verlegung"),
        ("Marschführer/in:", "BI Muster"),
        ("Marschüberwachung und Verkehrssicherung:", "Lotse AS 12"),
        ("Verpflegung:", "EPa"),
        ("Instandsetzungsdienst:", "WLF"),
        ("Sonstige Verbindungen, Lotsenstellen und Verkehrsleitpunkte:", "Lotsenstelle AS 12"),
        ("Verteiler", "Alle Fahrzeugführer"),
        ("Ergänzend:", "Altbestand"),
    ]:
        assert texte[_index(texte, punkt) + 1] == wert, punkt
    assert "M. Muster, Kreisbrandinspektor" in texte


# ── Ableitungen ──────────────────────────────────────────────────────────


def test_schliessender_markiert_sonst_das_letzte_fahrzeug():
    markiert = [_fz(0, "Spitze"), _fz(1, "Schluss", "schließender", "MU-1"), _fz(2, "Dahinter")]
    assert pdf_svc.schliessender(markiert) == "Pos. 2 – Schluss (MU-1)"
    ohne = [_fz(1, "Zweiter"), _fz(0, "Erster")]
    assert pdf_svc.schliessender(ohne) == "Pos. 2 – Zweiter (letztes Fahrzeug)"
    assert pdf_svc.schliessender([]) == ""


def test_platz_der_fuehrungskraft_und_aerztliche_versorgung():
    fz = [_fz(0, "ELW", "führungsfahrzeug"), _fz(1, "RTW", "sanitaet")]
    leer = _leerer_konvoi()
    assert pdf_svc.platz_fuehrung(leer, fz) == "im Führungsfahrzeug, Pos. 1 – ELW"
    assert pdf_svc.aerztliche_versorgung(leer, fz) == "Sanitätsdienstliche Absicherung: Pos. 2 – RTW"
    # Eingetragenes geht vor, und ohne passende Sonderfunktion wird nicht geraten.
    eigen = _leerer_konvoi(platz_fuehrung="Mitte", aerztliche_versorgung="Notarzt")
    assert pdf_svc.platz_fuehrung(eigen, fz) == "Mitte"
    assert pdf_svc.aerztliche_versorgung(eigen, fz) == "Notarzt"
    assert pdf_svc.platz_fuehrung(leer, [_fz(0, "LF")]) == ""


def test_durchschnittsgeschwindigkeit_aus_fahrzeit_ohne_halte():
    assert pdf_svc.durchschnitt_kmh(SimpleNamespace(distance_m=412_300, duration_s=25_600)) == 58
    assert pdf_svc.durchschnitt_kmh(SimpleNamespace(distance_m=1000, duration_s=None)) is None
    assert pdf_svc.durchschnitt_kmh(None) is None


def test_marschpausen_in_technische_halte_und_raste():
    wegpunkte = [
        {"name": "Start", "type": "waypoint"},
        {"name": "TH", "type": "technical_stop"},
        {"name": "Tanken", "type": "stop", "halt_purpose": "fuel"},
        {"name": "Werkstatt", "type": "stop", "halt_purpose": "maintenance"},
        {"name": "Rast", "type": "stop", "halt_purpose": "rest"},
        {"name": "Sonstiges", "type": "stop"},
        {"name": "Kontrolle", "type": "checkpoint"},
    ]
    th, raste = pdf_svc.marschpausen(wegpunkte)
    assert [w["name"] for w in th] == ["TH", "Tanken", "Werkstatt"]
    # Kein Halt fällt heraus: alles, was kein Technischer Halt ist, steht unter b).
    assert [w["name"] for w in raste] == ["Rast", "Sonstiges"]


def test_pdf_druckt_die_ableitungen(gedruckt):
    fz = [_fz(0, "ELW 1/1", "führungsfahrzeug"), _fz(1, "GW-L 1/2")]
    wegpunkte = [
        {"name": "Wache", "type": "waypoint"},
        {"name": "Tankhof", "type": "stop", "halt_purpose": "fuel", "hold_duration_min": 30},
        {"name": "Autohof", "type": "stop", "halt_purpose": "rest", "hold_duration_min": 120},
        {"name": "Ziel", "type": "waypoint"},
    ]
    route = SimpleNamespace(distance_m=120_000, duration_s=7200, routing_params={})
    pdf_svc.generate_marschbefehl(_leerer_konvoi(), wegpunkte, fz, route)
    texte = gedruckt
    assert texte[_index(texte, "Marschentfernung:") + 1] == "120,0 km"
    assert texte[_index(texte, "Marschgeschwindigkeit:") + 1].startswith("Ø 60 km/h")
    assert texte[_index(texte, "Schließende/r:") + 1] == "Pos. 2 – GW-L 1/2 (letztes Fahrzeug)"
    assert texte[_index(texte, "Platz der Führungskraft:") + 1] == "im Führungsfahrzeug, Pos. 1 – ELW 1/1"
    assert texte[_index(texte, "Betriebsstoff:") + 1] == pdf_svc.BETRIEBSSTOFF_STANDARD
    a, b, besonders = _index(texte, "a) Technische Halte"), _index(texte, "b) Raste"), _index(texte, "Besondere")
    assert a < texte.index("Tankhof") < b < texte.index("Autohof") < besonders
    # Die App-Ergänzungen stehen unter „Besondere Einzelheiten“, vor 4.
    versorgung = _index(texte, "4. Versorgung")
    assert besonders < _index(texte, "Beflaggung") < _index(texte, "Fahrzeuge im Verband") < versorgung


def test_word_vorlage_bekommt_dieselben_ableitungen():
    fz = [_fz(0, "ELW", "führungsfahrzeug"), _fz(1, "RTW", "sanitaet")]
    wegpunkte = [{"name": "A", "type": "waypoint"}, {"name": "TH", "type": "technical_stop"},
                 {"name": "Rast", "type": "stop", "halt_purpose": "rest"}]
    route = SimpleNamespace(distance_m=100_000, duration_s=6000, routing_params={})
    konvoi = _leerer_konvoi()
    k = mv.kontext(konvoi, wegpunkte, fz, route)
    assert k["konvoi"]["schliessender"] == pdf_svc.schliessender(fz)
    assert k["konvoi"]["platz_fuehrung"] == pdf_svc.platz_fuehrung(konvoi, fz)
    assert k["konvoi"]["aerztliche_versorgung"] == pdf_svc.aerztliche_versorgung(konvoi, fz)
    assert k["konvoi"]["durchschnittsgeschwindigkeit"] == "60 km/h"
    assert k["konvoi"]["marschentfernung"] == k["konvoi"]["marschstrecke"] == "100,0 km"
    assert k["konvoi"]["marschraum"] == "Rast"
    assert k["konvoi"]["betriebsstoff"] == pdf_svc.BETRIEBSSTOFF_STANDARD
    assert [p["ort"] for p in k["technische_halte"]] == ["TH"]
    assert [p["ort"] for p in k["raste"]] == ["Rast"]


def test_beispielvorlage_folgt_der_fwdv():
    doc = Document(io.BytesIO(mv.fuellen(mv.beispielvorlage(), mv.beispiel_kontext())))
    absaetze = [p.text for p in doc.paragraphs]
    marken = ["Befehl für den Marsch in den Raum", "1. Lage", "Gefahren- / Schadenlage", "Eigene Lage",
              "2. Auftrag", "Zuteilung, Unterstellung", "Erhaltener Auftrag", "3. Durchführung", "Marschziel",
              "Marschentfernung", "Marschführer/in", "Schließende/r", "Marschabstand", "Ablaufführer/in",
              "Marschgeschwindigkeit", "Beleuchtung", "Marschüberwachung", "a) Technische Halte",
              "b) Raste", "Besondere Einzelheiten", "4. Versorgung", "Verpflegung", "Betriebsstoff",
              "Instandsetzungsdienst", "Ärztliche Versorgung", "5. Führung und Verbindung",
              "Kommunikationsverbindungen", "Sonstige Verbindungen", "Platz der Führungskraft", "Anlagen",
              "Verteiler", "(Name, Dienststellung)"]
    pos = [next(i for i, a in enumerate(absaetze) if a.startswith(m)) for m in marken]
    assert pos == sorted(pos)
    assert "M. Muster, Kreisbrandinspektor" in absaetze
    assert "6. Anlagen" not in absaetze


# ── Speichern ────────────────────────────────────────────────────────────


async def test_geleertes_feld_wird_geloescht(client, aktion):  # noqa: F811
    a = aktion
    url = f"/api/convoys/{a.convoy_id}"
    r = await client.put(url, json={"verteiler": "Alle", "lage": "Hochwasser"}, headers=h(a.admin))
    assert r.status_code == 200, r.text
    assert r.json()["verteiler"] == "Alle"

    # Das Formular schickt ein geleertes Feld als null.
    r = await client.put(url, json={"verteiler": None}, headers=h(a.admin))
    assert r.status_code == 200, r.text
    assert r.json()["verteiler"] is None
    # Was nicht mitgeschickt wird, bleibt.
    assert r.json()["lage"] == "Hochwasser"
    # Nicht nullbare Felder ignorieren null weiterhin.
    r = await client.put(url, json={"name": None}, headers=h(a.admin))
    assert r.status_code == 200 and r.json()["name"]
