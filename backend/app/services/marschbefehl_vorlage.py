"""Marschbefehl aus einer Word-Vorlage der Organisation.

Der eingebaute Marschbefehl (``services/pdf.py``) ist fest gesetzt. Viele
Organisationen haben aber ein eigenes Formular: Kopf mit Wappen, eigene
Gliederung, eigene Textbausteine. Deshalb kann der Org-Admin eine
``.docx``-Vorlage hochladen, in der Platzhalter stehen; ConvoyPlan füllt sie
beim Export aus (``docxtpl``, Jinja2 im Word-Dokument).

Die Beispielvorlage wird hier **erzeugt**, nicht als Datei mitgeliefert: Sie
entsteht aus ``FELDER`` und ``beispiel_kontext()``, also aus denselben Quellen
wie der echte Export. Ein neues Feld steht so ohne weiteres Zutun in der
Feldübersicht der Beispieldatei. ``tests/test_marschbefehl_vorlage.py`` hält
``FELDER`` und ``kontext()`` deckungsgleich.

Drei Dinge, die man kennen muss:

- **Die Vorlage ist fremder Code.** Jinja2 wertet Ausdrücke aus; eine
  hochgeladene Vorlage läuft deshalb in einer Sandbox (``_Sandbox``) ohne
  ``range``, ohne Formatierer mit Breitenangabe und mit gedeckelter
  Vervielfachung — sonst legte ein Org-Admin mit ``{{ "x" * 10**10 }}`` den
  gemeinsamen Hosting-Server lahm. Gegen Rechenzeit hilft keine Sandbox
  (rekursive Makros, verschachtelte Schleifen); dafür läuft das Füllen in
  einem eigenen Prozess mit Frist und Speicherdeckel (``fuellen``).
- **Tippfehler fallen beim Hochladen auf**, nicht beim Export:
  ``StrictUndefined`` und ein Probelauf gegen ``beispiel_kontext()``, in dem
  jede Liste Einträge hat. Was den Probelauf besteht, besteht jeden Export,
  weil der echte Kontext dieselben Schlüssel trägt.
- **Werte sind fertige Texte**, deutsch formatiert, fehlende als ``""``.
  So kann die Vorlage ``{% if konvoi.lage %}`` schreiben, und niemand muss in
  Word Zahlen formatieren. Zeilenumbrüche in Freitexten werden zu
  Umbrüchen in Word (``docxtpl.resolve_listing``).
"""

from __future__ import annotations

import io
import multiprocessing
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from jinja2 import StrictUndefined, TemplateError, UndefinedError
from jinja2.sandbox import ImmutableSandboxedEnvironment, SecurityError

from app.services import durchfahrtshoehe as hoehe_svc
from app.services import gewichtsgrenzen as gewicht_svc
from app.services.pdf import (
    MARSCHFORM_LABELS,
    PURPOSE_LABELS,
    SONDERFUNKTION_LABELS,
    TYPE_LABELS,
    _build_marschweg,
    halt_vermerk,
)

MAX_BYTES = 5 * 1024 * 1024
# Entpackt darf eine Vorlage nicht beliebig wachsen (Zip-Bombe): python-docx
# liest jeden Teil vollständig in den Speicher.
MAX_ENTPACKT = 40 * 1024 * 1024
MAX_EINTRAEGE = 1000

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_HAUPTDOKUMENT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"

# Füllen läuft in einem eigenen Prozess (``fuellen``): so lange höchstens und
# mit so viel Adressraum. Ein Export dauert sonst unter einer Sekunde, davon
# das meiste für den Start des Prozesses.
FRIST_S = 20.0
SPEICHER_BYTES = 1536 * 1024 * 1024

# Längster Text, den ``*`` oder ``**`` in einer Vorlage erzeugen darf.
_MAX_PRODUKT = 10_000
# Zeichen, die in XML 1.0 nicht vorkommen dürfen — ein Freitext mit einem
# davon machte das erzeugte Dokument unlesbar. \a und \f fallen mit weg:
# docxtpl machte daraus Absatz- und Seitenumbrüche.
_STEUERZEICHEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class VorlageFehler(ValueError):
    """Die Vorlage ist kein brauchbares Word-Dokument oder enthält einen Fehler.
    Die Meldung geht an den Org-Admin."""


# ── Felder ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Feld:
    name: str
    beschreibung: str


@dataclass(frozen=True)
class Liste:
    name: str
    beschreibung: str
    felder: tuple[Feld, ...]


KONVOI_FELDER: tuple[Feld, ...] = (
    Feld("name", "Name des Konvois / Marschverbands"),
    Feld("befehlende_stelle", "Befehlende Stelle (sonst Name der Organisation)"),
    Feld("datum", "Datum des Marschbeginns (sonst heute)"),
    Feld("uhrzeit", "Uhrzeit des Marschbeginns"),
    Feld("lage", "1. Lage (Freitext, mehrzeilig)"),
    Feld("auftrag", "2. Auftrag (Freitext, mehrzeilig)"),
    Feld("marschziel", "Name des letzten Wegpunkts"),
    Feld("marschweg", "„von A über B nach C“ aus den Wegpunkten"),
    Feld("marschstrecke", "Länge der berechneten Route, z. B. „412,3 km“"),
    Feld("marschform", "Marschform"),
    Feld("ablaufpunkt", "Ablaufpunkt"),
    Feld("ablaufzeit", "Ablaufzeit (Datum und Uhrzeit)"),
    Feld("ablauffuehrer", "Ablaufführer/in"),
    Feld("geschwindigkeit_innerorts", "Marschgeschwindigkeit innerorts, z. B. „40 km/h“"),
    Feld("geschwindigkeit_ausserorts", "Marschgeschwindigkeit außerorts"),
    Feld("abstand_innerorts", "Fahrzeugabstand innerorts, z. B. „15 m“"),
    Feld("abstand_ausserorts", "Fahrzeugabstand außerorts"),
    Feld("abstand_autobahn", "Fahrzeugabstand auf der Autobahn"),
    Feld("versorgung", "4. Versorgung (Freitext, mehrzeilig)"),
    Feld("funkgruppe", "Funkgruppe"),
    Feld("anlagen", "6. Anlagen (Freitext, mehrzeilig)"),
    Feld("anzahl_fahrzeuge", "Zahl der Fahrzeuge im Verband"),
    Feld("hoechstes_fahrzeug", "Höhe des höchsten Fahrzeugs, mit der die Route berechnet wurde"),
    Feld("schwerstes_fahrzeug", "Gewicht des schwersten Fahrzeugs, mit dem die Route berechnet wurde"),
)

ORGANISATION_FELDER: tuple[Feld, ...] = (
    Feld("name", "Name der Organisation in ConvoyPlan"),
)

ERSTELLT_FELDER: tuple[Feld, ...] = (
    Feld("datum", "Tag des Exports"),
    Feld("uhrzeit", "Uhrzeit des Exports"),
)

LISTEN: tuple[Liste, ...] = (
    Liste("fahrzeuge", "Marschfolge, ein Eintrag je Fahrzeug", (
        Feld("pos", "Position in der Marschfolge (1, 2, …)"),
        Feld("name", "Fahrzeugname"),
        Feld("funkrufname", "Funkrufname"),
        Feld("kennzeichen", "KFZ-Kennzeichen"),
        Feld("mobiltelefon", "Mobiltelefon im Fahrzeug"),
        Feld("sonderfunktion", "Sonderfunktion (Spitzenführer, Schließender, …)"),
        Feld("rolle", "Aufgabe / Rolle des Fahrzeugs"),
        Feld("hoehe", "Höhe, z. B. „3,40 m“"),
        Feld("gewicht", "Gewicht, z. B. „14.500 kg“"),
    )),
    Liste("wegpunkte", "Alle Wegpunkte in Reihenfolge", (
        Feld("nr", "Laufende Nummer"),
        Feld("name", "Name"),
        Feld("art", "Wegpunkt, Halt, Kontrollpunkt, Technischer Halt"),
        Feld("ankunft", "Geplante Ankunft (Uhrzeit)"),
        Feld("abfahrt", "Geplante Abfahrt (Uhrzeit)"),
        Feld("dauer", "Haltedauer, z. B. „30 min“"),
        Feld("anmerkung", "Anmerkungen"),
        Feld("vermerk", "Zusammengelegter Halt, z. B. „zugleich Technischer Halt (WOLKE)“"),
    )),
    Liste("durchlaufpunkte", "Wegpunkte und Kontrollpunkte ohne Halt", (
        Feld("name", "Durchlaufpunkt"),
        Feld("zeit", "Geplante Durchlaufzeit"),
        Feld("anmerkung", "Anmerkungen"),
    )),
    Liste("marschpausen", "Halte und Technische Halte", (
        Feld("ort", "Ort"),
        Feld("art", "Art, mit Zweck (Betriebsstoff, Rast, …)"),
        Feld("dauer", "Dauer"),
        Feld("ankunft", "Geplante Ankunft"),
        Feld("vermerk", "Zusammengelegter Halt"),
    )),
    Liste("kanalwechsel", "Funk-Kanalwechsel entlang der Route", (
        Feld("km", "Kilometer, z. B. „87,4 km“"),
        Feld("aktion", "Anmelden, Abmelden, Convoy Anmeldung"),
        Feld("leitstelle", "Leitstelle"),
        Feld("anrufgruppe", "Anrufgruppe"),
        Feld("zusatzkanaele", "Weitere Kanäle der Leitstelle"),
    )),
    Liste("durchfahrtshoehen", "Höhenbeschränkungen mit wenig Spielraum", (
        Feld("km", "Kilometer"),
        Feld("hoehe", "Durchfahrtshöhe"),
        Feld("spielraum", "Spielraum zum höchsten Fahrzeug"),
        Feld("hinweis", "ENG – vor Ort prüfen, knapp, …"),
    )),
    Liste("gewichtsgrenzen", "Gewichts- und Achslastgrenzen mit wenig Reserve", (
        Feld("km", "Kilometer"),
        Feld("grenze", "Grenze, z. B. „7,5 t“ oder „Achse 10,0 t“"),
        Feld("reserve", "Reserve zum schwersten Fahrzeug"),
        Feld("ausnahme", "Ausnahme (Anlieger frei, …)"),
        Feld("hinweis", "ÜBER DER GRENZE, knapp, …"),
    )),
)

GRUPPEN: tuple[tuple[str, str, tuple[Feld, ...]], ...] = (
    ("konvoi", "Konvoi und Marschbefehl", KONVOI_FELDER),
    ("organisation", "Organisation", ORGANISATION_FELDER),
    ("erstellt", "Zeitpunkt des Exports", ERSTELLT_FELDER),
)


def feldkatalog() -> dict:
    """Die Felder für die Oberfläche (``GET …/felder``)."""
    return {
        "gruppen": [
            {"name": n, "titel": t, "felder": [{"name": f.name, "beschreibung": f.beschreibung} for f in fs]}
            for n, t, fs in GRUPPEN
        ],
        "listen": [
            {"name": li.name, "titel": li.beschreibung,
             "felder": [{"name": f.name, "beschreibung": f.beschreibung} for f in li.felder]}
            for li in LISTEN
        ],
    }


# ── Kontext ──────────────────────────────────────────────────────────────


def _text(wert: Any) -> str:
    if wert is None:
        return ""
    return _STEUERZEICHEN.sub("", str(wert))


def _komma(zahl: float, stellen: int) -> str:
    return f"{zahl:.{stellen}f}".replace(".", ",")


def _datum(dt: datetime | None) -> str:
    return dt.strftime("%d.%m.%Y") if dt else ""


def _zeit(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else ""


def _iso(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def _km(wert: Any) -> str:
    return f"{_komma(float(wert or 0), 1)} km"


def kontext(
    convoy: Any,
    waypoints: list[dict],
    vehicles: list[dict],
    route: Any | None,
    kanalwechsel: list[dict] | None = None,
    durchfahrtshoehen: list[dict] | None = None,
    gewichtsgrenzen: list[dict] | None = None,
    org_name: str | None = None,
    jetzt: datetime | None = None,
) -> dict:
    """Alle Felder der Vorlage, aus denselben Daten wie ``pdf.generate_marschbefehl``.

    Die Argumente sind genau die des PDF-Exports — so bleibt der Aufbau der
    Daten an einer Stelle (``api/routes/routing.export_pdf``)."""
    jetzt = jetzt or datetime.now()
    beginn = convoy.start_time
    dist_km = (route.distance_m or 0) / 1000 if route else 0
    params = getattr(route, "routing_params", None) or {}
    hoehe_m = params.get("max_height_m")
    gewicht_t = params.get("max_weight_t")

    konvoi = {
        "name": _text(convoy.name),
        "befehlende_stelle": _text(convoy.organization or org_name),
        "datum": _datum(beginn or jetzt),
        "uhrzeit": _zeit(beginn),
        "lage": _text(convoy.lage),
        "auftrag": _text(convoy.auftrag),
        "marschziel": _text(waypoints[-1]["name"]) if waypoints else "",
        "marschweg": _text(_build_marschweg(waypoints)) if waypoints else "",
        "marschstrecke": _km(dist_km) if dist_km else "",
        "marschform": _text(MARSCHFORM_LABELS.get(convoy.marschform or "", convoy.marschform)),
        "ablaufpunkt": _text(convoy.ablaufpunkt),
        "ablaufzeit": f"{_datum(convoy.ablaufzeit)} {_zeit(convoy.ablaufzeit)}".strip(),
        "ablauffuehrer": _text(getattr(convoy, "ablaufführer", None)),
        "geschwindigkeit_innerorts": f"{convoy.speed_urban_kmh} km/h" if convoy.speed_urban_kmh else "",
        "geschwindigkeit_ausserorts": f"{convoy.speed_rural_kmh} km/h" if convoy.speed_rural_kmh else "",
        "abstand_innerorts": f"{convoy.spacing_urban_m} m" if convoy.spacing_urban_m else "",
        "abstand_ausserorts": f"{convoy.spacing_rural_m} m" if convoy.spacing_rural_m else "",
        "abstand_autobahn": f"{convoy.spacing_motorway_m} m" if convoy.spacing_motorway_m else "",
        "versorgung": _text(convoy.versorgung),
        "funkgruppe": _text(convoy.funkgruppe),
        "anlagen": _text(convoy.anlagen),
        "anzahl_fahrzeuge": str(len(vehicles)),
        "hoechstes_fahrzeug": f"{_komma(hoehe_m, 2)} m" if hoehe_m else "",
        "schwerstes_fahrzeug": f"{_komma(gewicht_t, 1)} t" if gewicht_t else "",
    }

    fahrzeuge = [
        {
            "pos": str(v["position"] + 1),
            "name": _text(v.get("name")),
            "funkrufname": _text(v.get("callsign")),
            "kennzeichen": _text(v.get("license_plate")),
            "mobiltelefon": _text(v.get("mobile_phone")),
            "sonderfunktion": _text(SONDERFUNKTION_LABELS.get(v.get("sonderfunktion") or "", v.get("sonderfunktion"))),
            "rolle": _text(v.get("convoy_role")),
            "hoehe": f"{_komma(v['height_cm'] / 100, 2)} m" if v.get("height_cm") else "",
            "gewicht": f"{v['weight_kg']:,} kg".replace(",", ".") if v.get("weight_kg") else "",
        }
        for v in vehicles
    ]

    def _art(w: dict) -> str:
        art = TYPE_LABELS.get(w.get("type") or "", w.get("type") or "")
        if w.get("halt_purpose"):
            art += f" ({PURPOSE_LABELS.get(w['halt_purpose'], w['halt_purpose'])})"
        return _text(art)

    def _dauer(w: dict) -> str:
        return f"{w['hold_duration_min']} min" if w.get("hold_duration_min") else ""

    def _vermerk(w: dict) -> str:
        return _text(halt_vermerk(w.get("zusammengelegt"), w.get("hold_duration_min")))

    wegpunkte = [
        {
            "nr": str(i + 1),
            "name": _text(w.get("name")),
            "art": _art(w),
            "ankunft": _zeit(_iso(w.get("planned_arrival"))),
            "abfahrt": _zeit(_iso(w.get("planned_departure"))),
            "dauer": _dauer(w),
            "anmerkung": _text(w.get("notes")),
            "vermerk": _vermerk(w),
        }
        for i, w in enumerate(waypoints)
    ]
    durchlaufpunkte = [
        {
            "name": _text(w.get("name")),
            "zeit": _zeit(_iso(w.get("planned_arrival"))),
            "anmerkung": _text(w.get("notes")),
        }
        for w in waypoints if w.get("type") in ("checkpoint", "waypoint")
    ]
    marschpausen = [
        {
            "ort": _text(w.get("name")),
            "art": _art(w),
            "dauer": _dauer(w),
            "ankunft": _zeit(_iso(w.get("planned_arrival"))),
            "vermerk": _vermerk(w),
        }
        for w in waypoints if w.get("type") in ("stop", "technical_stop")
    ]

    aktionen = {"abmelden": "Abmelden", "convoy_anmeldung": "Convoy Anmeldung"}
    kanaele = [
        {
            "km": _km(kw.get("km")),
            "aktion": aktionen.get(kw.get("typ"), "Anmelden"),
            "leitstelle": _text(kw.get("leitstelle_name")),
            "anrufgruppe": _text(kw.get("anrufgruppe")),
            "zusatzkanaele": "" if kw.get("typ") == "abmelden" else _text(", ".join(
                f"{z.get('name', 'Kanal')}: {z.get('kanal', '')}"
                for z in kw.get("zusatz_kanaele") or [] if isinstance(z, dict)
            )),
        }
        for kw in kanalwechsel or []
    ]

    stufen_hoehe = {"eng": "ENG – vor Ort prüfen", "knapp": "knapp", "unbekannt": "Fahrzeughöhe fehlt"}
    hoehen = [
        {
            "km": _km(e.get("km")),
            "hoehe": f"{_komma(e.get('hoehe_m') or 0, 1)} m",
            "spielraum": "" if e.get("spielraum_m") is None else f"{e['spielraum_m'] * 100:+.0f} cm",
            "hinweis": stufen_hoehe.get(e.get("stufe") or "", ""),
        }
        for e in hoehe_svc.hinweispflichtig(durchfahrtshoehen or [])
    ]
    stufen_gewicht = {"ueberschritten": "ÜBER DER GRENZE", "knapp": "knapp", "unbekannt": "Fahrzeuggewicht fehlt"}
    gewichte = [
        {
            "km": _km(e.get("km")),
            "grenze": ("Achse " if e.get("art") == "achslast" else "") + f"{_komma(e.get('grenze_t') or 0, 1)} t",
            "reserve": "" if e.get("reserve_t") is None else f"{e['reserve_t']:+.1f} t".replace(".", ","),
            "ausnahme": gewicht_svc.AUSNAHMEN.get(e.get("ausnahme") or "", ""),
            "hinweis": stufen_gewicht.get(e.get("stufe") or "", ""),
        }
        for e in gewicht_svc.hinweispflichtig(gewichtsgrenzen or [])
    ]

    return {
        "konvoi": konvoi,
        "organisation": {"name": _text(org_name)},
        "erstellt": {"datum": _datum(jetzt), "uhrzeit": _zeit(jetzt)},
        "fahrzeuge": fahrzeuge,
        "wegpunkte": wegpunkte,
        "durchlaufpunkte": durchlaufpunkte,
        "marschpausen": marschpausen,
        "kanalwechsel": kanaele,
        "durchfahrtshoehen": hoehen,
        "gewichtsgrenzen": gewichte,
    }


def beispiel_kontext() -> dict:
    """Ein Kontext, in dem jedes Feld gefüllt und jede Liste belegt ist — für
    den Probelauf beim Hochladen und die Vorschau der Beispielvorlage."""
    convoy = SimpleNamespace(
        name="Hilfskonvoi Ahrtal", organization="Kreisbrandinspektion Musterstadt",
        start_time=datetime(2026, 11, 7, 6, 30), lage="Hochwasser im Ahrtal.\nAnforderung über das Land.",
        auftrag="Verlegung des Abrollbehälter-Zugs in den Bereitstellungsraum Grafschaft.",
        marschform="geschlossener_verband", ablaufpunkt="Feuerwache Musterstadt",
        ablaufzeit=datetime(2026, 11, 7, 6, 45), ablaufführer="BI Muster",
        speed_urban_kmh=40, speed_rural_kmh=65, spacing_urban_m=15, spacing_rural_m=50,
        spacing_motorway_m=100, versorgung="Verpflegung am Technischen Halt.",
        funkgruppe="TMO 312_Musterstadt", anlagen="Roadbook, Fahrzeugliste",
    )
    route = SimpleNamespace(distance_m=412_300, routing_params={"max_height_m": 3.4, "max_weight_t": 18.0})
    waypoints = [
        {"name": "Feuerwache Musterstadt", "type": "waypoint", "planned_arrival": "2026-11-07T06:45:00"},
        {"name": "Rastplatz Hösbach", "type": "stop", "halt_purpose": "fuel",
         "hold_duration_min": 30, "planned_arrival": "2026-11-07T08:50:00",
         "planned_departure": "2026-11-07T09:20:00", "zusammengelegt": [{"kind": "tech", "duration_min": 30}]},
        {"name": "AS Montabaur", "type": "checkpoint", "planned_arrival": "2026-11-07T11:05:00",
         "notes": "Meldung an Führung"},
        {"name": "BR Grafschaft", "type": "stop", "hold_duration_min": 60,
         "planned_arrival": "2026-11-07T12:10:00"},
    ]
    vehicles = [
        {"position": 0, "name": "ELW 1", "callsign": "Florian Musterstadt 11/1", "license_plate": "MU-FW 111",
         "mobile_phone": "+49 171 0000000", "sonderfunktion": "spitzenführer", "convoy_role": "Führung",
         "height_cm": 280, "weight_kg": 4600},
        {"position": 1, "name": "WLF", "callsign": "Florian Musterstadt 66/1", "license_plate": "MU-FW 661",
         "mobile_phone": "", "sonderfunktion": "schließender", "convoy_role": "Transport",
         "height_cm": 340, "weight_kg": 18000},
    ]
    kanalwechsel = [
        {"km": 87.4, "typ": "anmelden", "leitstelle_name": "ILS Bayerischer Untermain",
         "anrufgruppe": "TMO 302", "zusatz_kanaele": [{"name": "Betrieb", "kanal": "TMO 303"}]},
    ]
    hoehen = [{"km": 203.5, "hoehe_m": 3.5, "spielraum_m": 0.1, "stufe": "knapp"}]
    gewichte = [{"km": 398.2, "grenze_t": 7.5, "reserve_t": -10.5, "art": "gewicht",
                 "ausnahme": "destination", "stufe": "ueberschritten"}]
    return kontext(
        convoy, waypoints, vehicles, route, kanalwechsel, hoehen, gewichte,
        org_name="Feuerwehr Musterstadt", jetzt=datetime(2026, 11, 6, 18, 0),
    )


# ── Sandbox ──────────────────────────────────────────────────────────────

# Filter, die eine Vorlage braucht. Alles mit Breiten- oder Wiederholungs-
# angabe (center, indent, wordwrap, format, filesizeformat …) bleibt draußen.
_FILTER = frozenset({
    "default", "d", "upper", "lower", "title", "capitalize", "trim", "replace",
    "length", "count", "first", "last", "join", "e", "escape", "string",
    "truncate", "list", "sort", "reverse", "select", "reject", "selectattr",
    "rejectattr", "map", "unique", "int", "round", "abs", "batch", "slice",
})
# Methoden an Zeichenketten mit Breitenangabe.
_VERBOTENE_METHODEN = frozenset({
    "format", "format_map", "center", "ljust", "rjust", "zfill", "expandtabs",
})


class _Sandbox(ImmutableSandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**", "%"})

    def call_binop(self, context, operator, left, right):
        if operator == "%" and isinstance(left, str):
            raise SecurityError("Formatieren mit % ist in Vorlagen nicht erlaubt")
        if operator == "**":
            if abs(left) > 1000 or abs(right) > 64:
                raise SecurityError("Zahl zu groß")
        if operator == "*":
            for seite, andere in ((left, right), (right, left)):
                if isinstance(seite, (str, list, tuple)) and isinstance(andere, int):
                    if len(seite) * andere > _MAX_PRODUKT:
                        raise SecurityError("Text zu lang")
        return super().call_binop(context, operator, left, right)

    # ``str.format`` reicht Jinja an ``is_safe_attribute`` vorbei
    # (``wrap_str_format``), deshalb wird schon beim Zugriff gesperrt.
    def getattr(self, obj, attribute):
        if isinstance(obj, str) and attribute in _VERBOTENE_METHODEN:
            return self.unsafe_undefined(obj, attribute)
        return super().getattr(obj, attribute)

    def getitem(self, obj, argument):
        if isinstance(obj, str) and argument in _VERBOTENE_METHODEN:
            return self.unsafe_undefined(obj, argument)
        return super().getitem(obj, argument)


def _umgebung() -> _Sandbox:
    env = _Sandbox(undefined=StrictUndefined, autoescape=True)
    for name in ("range", "lipsum", "cycler", "joiner"):
        env.globals.pop(name, None)
    env.filters = {k: v for k, v in env.filters.items() if k in _FILTER}
    return env


# ── Prüfen und Füllen ────────────────────────────────────────────────────


def pruefe_datei(daten: bytes) -> None:
    """Ist das ein Word-Dokument, das wir öffnen wollen? Ohne die Vorlage zu
    rendern — das tut ``pruefe`` danach."""
    if len(daten) > MAX_BYTES:
        raise VorlageFehler(f"Die Datei ist zu groß (höchstens {MAX_BYTES // (1024 * 1024)} MB).")
    try:
        zf = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile:
        raise VorlageFehler("Das ist keine .docx-Datei. Bitte in Word als „Word-Dokument (*.docx)“ speichern.")
    with zf:
        eintraege = zf.infolist()
        if len(eintraege) > MAX_EINTRAEGE or sum(e.file_size for e in eintraege) > MAX_ENTPACKT:
            raise VorlageFehler("Die Datei ist entpackt zu groß.")
        namen = {e.filename for e in eintraege}
        if "[Content_Types].xml" not in namen or "word/document.xml" not in namen:
            raise VorlageFehler("Das ist keine .docx-Datei. Bitte in Word als „Word-Dokument (*.docx)“ speichern.")
        typen = zf.read("[Content_Types].xml").decode("utf-8", "replace")
        if any(n.lower().endswith("vbaproject.bin") for n in namen) or "macroEnabled" in typen:
            raise VorlageFehler("Vorlagen mit Makros (.docm) werden nicht angenommen.")
        if _HAUPTDOKUMENT not in typen:
            raise VorlageFehler("Das ist kein Word-Dokument (.docx). Dokumentvorlagen (.dotx) bitte als .docx speichern.")


def _fehlertext(exc: Exception) -> str:
    if isinstance(exc, UndefinedError):
        m = re.search(r"has no attribute '([^']+)'", str(exc)) or re.search(r"'([^']+)' is undefined", str(exc))
        name = m.group(1) if m else str(exc)
        return f"Unbekanntes Feld „{name}“. Die verfügbaren Felder stehen in der Beispielvorlage."
    if isinstance(exc, SecurityError):
        return f"In der Vorlage steht ein Ausdruck, der nicht erlaubt ist: {exc}"
    text = getattr(exc, "message", None) or str(exc)
    zusatz = ""
    kontext_zeilen = [z.strip() for z in getattr(exc, "docx_context", []) or [] if z.strip()]
    if kontext_zeilen:
        zusatz = f" — in der Nähe von: „{' '.join(kontext_zeilen)[:160]}“"
    return f"Fehler in einem Platzhalter: {text}{zusatz}"


def _fuellen(vorlage: bytes, werte: dict) -> bytes:
    from docxtpl import DocxTemplate

    try:
        tpl = DocxTemplate(io.BytesIO(vorlage))
        tpl.render(werte, jinja_env=_umgebung(), autoescape=True)
        aus = io.BytesIO()
        tpl.save(aus)
    except (TemplateError, SecurityError) as exc:
        raise VorlageFehler(_fehlertext(exc)) from exc
    except RecursionError as exc:
        raise VorlageFehler("Die Vorlage ruft sich endlos selbst auf.") from exc
    except MemoryError:
        raise
    except Exception as exc:  # beschädigtes XML, fehlende Teile …
        raise VorlageFehler(f"Die Vorlage lässt sich nicht verarbeiten ({type(exc).__name__}).") from exc
    return aus.getvalue()


def _kind(verbindung, vorlage: bytes, werte: dict, speicher: int) -> None:
    """Läuft im Kindprozess: Speicher deckeln, füllen, Ergebnis zurückschicken."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (speicher, speicher))
    except (ImportError, ValueError, OSError):
        pass  # ohne Deckel bleibt die Frist
    try:
        verbindung.send(("ok", _fuellen(vorlage, werte)))
    except VorlageFehler as exc:
        verbindung.send(("fehler", str(exc)))
    except MemoryError:
        verbindung.send(("fehler", "Die Vorlage braucht beim Füllen zu viel Speicher."))
    finally:
        verbindung.close()


def fuellen(vorlage: bytes, werte: dict, frist_s: float | None = None) -> bytes:
    """Die Vorlage mit ``werte`` (aus ``kontext()``) füllen; das fertige ``.docx``.

    Gefüllt wird in einem eigenen Prozess mit Frist und Speicherdeckel: Die
    Sandbox hält Python-Interna und große Texte fern, aber nicht die Rechenzeit
    — ein Makro, das sich zweimal selbst aufruft, oder fünf verschachtelte
    Schleifen über die Zeichen eines Freitexts liefen ohne Ende. Ein Thread
    ließe sich nicht abbrechen, ein Prozess schon. Blockiert, deshalb aus
    ``run_in_executor`` aufrufen."""
    ctx = multiprocessing.get_context("spawn")
    lesen, schreiben = ctx.Pipe(duplex=False)
    prozess = ctx.Process(target=_kind, args=(schreiben, vorlage, werte, SPEICHER_BYTES), daemon=True)
    prozess.start()
    schreiben.close()
    try:
        if not lesen.poll(FRIST_S if frist_s is None else frist_s):
            raise VorlageFehler(
                "Die Vorlage braucht zu lange zum Füllen — vermutlich eine Schleife oder ein Makro, "
                "das sich zu oft wiederholt."
            )
        art, inhalt = lesen.recv()
    except EOFError:
        # Das Kind ist ohne Antwort gestorben — meist am Speicherdeckel.
        raise VorlageFehler("Die Vorlage ließ sich nicht füllen (zu viel Speicher?).") from None
    finally:
        lesen.close()
        if prozess.is_alive():
            prozess.kill()
        prozess.join(5)
    if art != "ok":
        raise VorlageFehler(inhalt)
    return inhalt


def pruefe(vorlage: bytes) -> None:
    """Datei prüfen und einmal mit dem Beispielkontext füllen. Wirft
    ``VorlageFehler`` mit einer Meldung für den Org-Admin."""
    pruefe_datei(vorlage)
    fuellen(vorlage, beispiel_kontext())


# ── Beispielvorlage ──────────────────────────────────────────────────────


def beispielvorlage() -> bytes:
    """Eine ``.docx`` in der Gliederung des eingebauten Marschbefehls, mit
    Platzhaltern statt Werten und einer Feldübersicht am Ende, die beim
    Export nicht mitgedruckt wird."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    doc = Document()
    stil = doc.styles["Normal"]
    stil.font.name = "Arial"
    stil.font.size = Pt(10)

    def absatz(text: str = "", fett: bool = False, ausrichtung=None):
        p = doc.add_paragraph()
        if text:
            r = p.add_run(text)
            r.bold = fett
        if ausrichtung is not None:
            p.alignment = ausrichtung
        return p

    def steuer(text: str):
        """Eine Steuerzeile wie ``{%p if … %}`` — fällt beim Export samt Absatz weg."""
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        r.font.size = Pt(8)

    def tabelle(spalten: list[tuple[str, str]], liste: str, var: str):
        """Kopfzeile, eine Zeile je Eintrag von ``liste``. Die Zeilen mit
        ``{%tr … %}`` fallen beim Export weg."""
        t = doc.add_table(rows=4, cols=len(spalten))
        t.style = "Table Grid"
        for i, (titel, feld) in enumerate(spalten):
            kopf = t.rows[0].cells[i].paragraphs[0].add_run(titel)
            kopf.bold = True
            t.rows[2].cells[i].text = f"{{{{ {var}.{feld} }}}}"
        t.rows[1].cells[0].text = f"{{%tr for {var} in {liste} %}}"
        t.rows[3].cells[0].text = "{%tr endfor %}"
        for zeile in (1, 3):
            for zelle in t.rows[zeile].cells[1:]:
                zelle.text = ""
        return t

    doc.add_heading("MARSCHBEFEHL", level=0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    absatz("{{ konvoi.befehlende_stelle }}", fett=True)
    absatz("Marschverband: {{ konvoi.name }}")
    absatz("{{ konvoi.datum }} {{ konvoi.uhrzeit }}", ausrichtung=WD_ALIGN_PARAGRAPH.RIGHT)

    steuer("{%p if konvoi.lage %}")
    doc.add_heading("1. Lage", level=1)
    absatz("{{ konvoi.lage }}")
    steuer("{%p endif %}")

    steuer("{%p if konvoi.auftrag %}")
    doc.add_heading("2. Auftrag", level=1)
    absatz("{{ konvoi.auftrag }}")
    steuer("{%p endif %}")

    doc.add_heading("3. Durchführung", level=1)
    doc.add_heading("Marschbewegung", level=2)
    absatz("Marschziel: {{ konvoi.marschziel }}")
    absatz("Marschweg: {{ konvoi.marschweg }}")
    absatz("Marschstrecke: {{ konvoi.marschstrecke }}")
    absatz("Marschform: {{ konvoi.marschform }}")
    steuer("{%p if konvoi.ablaufpunkt %}")
    doc.add_heading("Ablaufpunkt", level=2)
    absatz("Ablaufpunkt: {{ konvoi.ablaufpunkt }}")
    absatz("Ablaufzeit: {{ konvoi.ablaufzeit }}")
    absatz("Ablaufführer: {{ konvoi.ablauffuehrer }}")
    steuer("{%p endif %}")

    doc.add_heading("Marschfolge", level=2)
    tabelle([("Pos.", "pos"), ("Funkrufname", "funkrufname"), ("Kennzeichen", "kennzeichen"),
             ("Mobiltelefon", "mobiltelefon"), ("Sonderfunktion", "sonderfunktion")], "fahrzeuge", "f")

    doc.add_heading("Marschgeschwindigkeit", level=2)
    absatz("Innerorts: {{ konvoi.geschwindigkeit_innerorts }}, außerorts: {{ konvoi.geschwindigkeit_ausserorts }}")
    absatz("Die jeweils gültige Höchstgeschwindigkeit darf nicht überschritten werden.")
    doc.add_heading("Fahrzeugabstände", level=2)
    absatz("Innerorts: {{ konvoi.abstand_innerorts }}, außerorts: {{ konvoi.abstand_ausserorts }}, "
           "Autobahn: {{ konvoi.abstand_autobahn }}")

    steuer("{%p if durchlaufpunkte %}")
    doc.add_heading("Durchlaufpunkte", level=2)
    tabelle([("Durchlaufpunkt", "name"), ("Geplante Durchlaufzeit", "zeit"), ("Anmerkungen", "anmerkung")],
            "durchlaufpunkte", "d")
    steuer("{%p endif %}")

    steuer("{%p if marschpausen %}")
    doc.add_heading("Marschpausen", level=2)
    tabelle([("Ort", "ort"), ("Art", "art"), ("Dauer", "dauer"), ("Hinweis", "vermerk")], "marschpausen", "m")
    steuer("{%p endif %}")

    doc.add_heading("Fahrzeuge im Verband", level=2)
    tabelle([("Pos", "pos"), ("Fahrzeug", "name"), ("Kennzeichen", "kennzeichen"), ("Höhe", "hoehe"),
             ("Gewicht", "gewicht"), ("Aufgabe / Rolle", "rolle")], "fahrzeuge", "f")

    steuer("{%p if durchfahrtshoehen %}")
    doc.add_heading("Durchfahrtshöhen", level=2)
    absatz("Höchstes Fahrzeug: {{ konvoi.hoechstes_fahrzeug }}")
    tabelle([("km", "km"), ("Höhe", "hoehe"), ("Spielraum", "spielraum"), ("Hinweis", "hinweis")],
            "durchfahrtshoehen", "h")
    steuer("{%p endif %}")

    steuer("{%p if gewichtsgrenzen %}")
    doc.add_heading("Gewichtsgrenzen", level=2)
    absatz("Schwerstes Fahrzeug: {{ konvoi.schwerstes_fahrzeug }}")
    tabelle([("km", "km"), ("Grenze", "grenze"), ("Reserve", "reserve"), ("Ausnahme", "ausnahme"),
             ("Hinweis", "hinweis")], "gewichtsgrenzen", "g")
    steuer("{%p endif %}")

    doc.add_heading("4. Versorgung", level=1)
    absatz("{{ konvoi.versorgung }}")
    absatz("Alle Fahrzeuge haben sich grundsätzlich vollgetankt am Ablaufpunkt einzufinden!")

    doc.add_heading("5. Führung und Verbindung", level=1)
    absatz("Funkgruppe: {{ konvoi.funkgruppe }}")
    steuer("{%p if kanalwechsel %}")
    doc.add_heading("Kanalwechsel", level=2)
    tabelle([("km", "km"), ("Aktion", "aktion"), ("Leitstelle", "leitstelle"), ("Anrufgruppe", "anrufgruppe"),
             ("Weitere Kanäle", "zusatzkanaele")], "kanalwechsel", "k")
    steuer("{%p endif %}")

    steuer("{%p if konvoi.anlagen %}")
    doc.add_heading("6. Anlagen", level=1)
    absatz("{{ konvoi.anlagen }}")
    steuer("{%p endif %}")

    absatz()
    absatz("Ort, Datum: ______________________    Unterschrift Marschverbandsführer/in: ______________________")
    absatz("Erstellt mit ConvoyPlan am {{ erstellt.datum }} um {{ erstellt.uhrzeit }} Uhr")

    # Feldübersicht — steht in der Datei, nicht im Export. Im Erklärtext
    # stehen bewusst keine Steuerzeilen ({%p …%}, {%tr …%}): docxtpl schreibt
    # sie vor Jinja um, auch in einem Block, der nie gedruckt wird, und ein
    # {%tr außerhalb einer Tabelle griffe in die Tabelle davor.
    steuer("{%p if false %}")
    doc.add_page_break()
    doc.add_heading("Feldübersicht (wird beim Export nicht gedruckt)", level=1)
    absatz(
        "Diese Seite steht zwischen den beiden grauen Steuerzeilen darüber und am Ende und fällt "
        "beim Export weg. Sie kann gelöscht werden — dann beide Steuerzeilen mit löschen."
    )
    absatz("So funktionieren Platzhalter:", fett=True)
    for zeile in (
        "Ein Feld steht in doppelten geschweiften Klammern, z. B. {{ konvoi.name }}. "
        "Schriftart, Größe und Farbe des Platzhalters gelten auch für den eingesetzten Wert.",
        "Die grauen Steuerzeilen („if“ … „endif“) zeigen einen Abschnitt nur, wenn das Feld gefüllt "
        "ist. Sie stehen in einem eigenen Absatz und fallen beim Export samt Absatz weg.",
        "Tabellen mit einer Zeile je Fahrzeug, Halt usw.: Die Zeile mit „for“ über und die mit "
        "„endfor“ unter der Zeile mit den Feldern stehen lassen; Spalten dürfen hinzu oder weg. "
        "Wie das aussieht, zeigt die Tabelle „Marschfolge“.",
        "Fehlt ein Wert, bleibt das Feld leer. Einen Ersatz setzt {{ konvoi.funkgruppe or '-' }}.",
        "Anführungszeichen in Platzhaltern sind gerade (' oder \"), nicht typografisch — Word ersetzt "
        "sie beim Tippen, das lässt sich mit Strg+Z direkt danach rückgängig machen.",
        "Tippfehler meldet ConvoyPlan schon beim Hochladen.",
    ):
        doc.add_paragraph(zeile, style="List Bullet")

    for gruppe, titel, felder in GRUPPEN:
        doc.add_heading(titel, level=2)
        t = doc.add_table(rows=1, cols=2)
        t.style = "Table Grid"
        t.rows[0].cells[0].text = "Platzhalter"
        t.rows[0].cells[1].text = "Inhalt"
        for f in felder:
            z = t.add_row().cells
            z[0].text = f"{{{{ {gruppe}.{f.name} }}}}"
            z[1].text = f.beschreibung
    for li in LISTEN:
        var = li.name[0]
        doc.add_heading(f"Liste „{li.name}“ — {li.beschreibung}", level=2)
        absatz(f"In der for-Zeile der Tabelle: „for {var} in {li.name}“; "
               f"„{li.name}“ allein in einer if-Zeile heißt: nur, wenn die Liste Einträge hat.")
        t = doc.add_table(rows=1, cols=2)
        t.style = "Table Grid"
        t.rows[0].cells[0].text = "Platzhalter"
        t.rows[0].cells[1].text = "Inhalt"
        for f in li.felder:
            z = t.add_row().cells
            z[0].text = f"{{{{ {var}.{f.name} }}}}"
            z[1].text = f.beschreibung
    steuer("{%p endif %}")

    aus = io.BytesIO()
    doc.save(aus)
    return aus.getvalue()
