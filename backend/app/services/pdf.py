from datetime import datetime
from io import BytesIO
from typing import Any

from fpdf import FPDF

from app.services import durchfahrtshoehe as hoehe_svc
from app.services import gewichtsgrenzen as gewicht_svc
from app.services import route_steps as route_steps_svc

MARSCHFORM_LABELS = {
    "geschlossener_verband": "Geschlossener Gesamtverband",
    "einzelgruppen": "Einzelgruppen",
    "individuell": "Individuelle Anreise",
}

SONDERFUNKTION_LABELS = {
    "spitzenführer": "Spitzenführer",
    "schließender": "Schließender (Ablaufführer)",
    "sanitaet": "Sanitätsdienstliche Absicherung",
    "ablaufführer": "Ablaufführer",
    "führungsfahrzeug": "Führungsfahrzeug",
}

TYPE_LABELS = {
    "waypoint": "Wegpunkt",
    "stop": "Halt",
    "checkpoint": "Kontrollpunkt / Durchlaufpunkt",
    "technical_stop": "Technischer Halt",
}

PURPOSE_LABELS = {
    "fuel": "Betriebsstoff",
    "rest": "Rast",
    "maintenance": "Wartung",
    "other": "Sonstiges",
}

HALT_KIND_LABELS = {
    "tech": "Technischer Halt (WOLKE)",
    "break": "Lenkpause",
    "daily_rest": "Tagesruhezeit",
}


def halt_vermerk(zusammengelegt: list[dict] | None, hold_min: int | None) -> str:
    """„zugleich Technischer Halt (WOLKE), empfohlen 30 min" — oder leer.

    Ein fälliger Halt, der in einem geplanten aufging (``fuel.halteplan``),
    darf auf dem Ausdruck nicht verschwinden: die Besatzung am Tankhalt muss
    wissen, dass dort auch die WOLKE-Prüfung ansteht. Die empfohlene Dauer
    steht nur dabei, wenn der Halt kürzer geplant ist.
    """
    teile = []
    for z in zusammengelegt or []:
        text = HALT_KIND_LABELS.get(z.get("kind", ""), "Halt")
        if z.get("duration_min") and z["duration_min"] > (hold_min or 0):
            text += f", empfohlen {z['duration_min']} min"
        teile.append(text)
    return f"zugleich {'; '.join(teile)}" if teile else ""


_FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


class _PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("DV", "", _FONT_REGULAR)
        self.add_font("DV", "B", _FONT_BOLD)

    def header(self):
        self.set_font("DV", "B", 16)
        self.cell(0, 9, "MARSCHBEFEHL", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(26, 39, 68)
        self.set_line_width(0.8)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-12)
        self.set_font("DV", "", 7)
        self.set_text_color(120, 120, 120)
        self.cell(
            0, 5,
            f"Erstellt mit ConvoyPlan  |  {datetime.now().strftime('%d.%m.%Y %H:%M')} Uhr  |  Seite {self.page_no()}",
            align="C",
        )
        self.set_text_color(0, 0, 0)


def _section(pdf: _PDF, number: str | None, title: str):
    """Hauptziffer; ``number=None`` für Anlagen und Verteiler, die in der FwDV
    keine Ziffer tragen."""
    pdf.ln(3)
    pdf.set_fill_color(26, 39, 68)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DV", "B", 10)
    titel = f"{number}. {title}" if number else title
    pdf.cell(0, 7, f"  {titel}", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


def _subsection(pdf: _PDF, title: str):
    pdf.set_font("DV", "B", 9)
    pdf.cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _kv(pdf: _PDF, label: str, value: str, label_w: int = 55):
    pdf.set_font("DV", "B", 9)
    pdf.cell(label_w, 5, label)
    pdf.set_font("DV", "", 9)
    remaining = pdf.w - pdf.r_margin - pdf.get_x()
    pdf.multi_cell(remaining, 5, value or "-", align="L", new_x="LMARGIN", new_y="NEXT")


def _textblock(pdf: _PDF, text: str | None):
    pdf.set_font("DV", "", 9)
    pdf.set_fill_color(248, 249, 252)
    pdf.multi_cell(0, 5, text or "-", fill=True, border=1)
    pdf.ln(2)


def _fmt_time(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(iso)


def _fmt_time_short(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return "-"


def _table_header(pdf: _PDF, cols: list[tuple[int, str]]):
    pdf.set_font("DV", "B", 8)
    pdf.set_fill_color(220, 225, 235)
    pdf.set_text_color(0, 0, 0)
    for w, label in cols:
        pdf.cell(w, 6, label, border=1, fill=True)
    pdf.ln()


_STUFE_LABELS = {
    "eng": "ENG – vor Ort prüfen",
    "knapp": "knapp",
    "unbekannt": "Fahrzeughöhe fehlt",
    "frei": "",
}


def _durchfahrtshoehen(
    pdf: _PDF,
    eintraege: list[dict],
    vehicles: list[dict],
    fahrzeughoehe_m: float | None,
    total_w: float,
    bruecken: dict | None = None,
) -> None:
    """Höhenbeschränkungen mit wenig Spielraum (services/durchfahrtshoehe.py).

    Gedruckt wird, was nicht ``frei`` ist; der Rest steht als Zahl darunter —
    eine Autobahnfahrt mit zwanzig Tunneln à 4,50 m soll den Befehl nicht füllen.

    ``fahrzeughoehe_m`` ist die Höhe, mit der die Route berechnet wurde
    (``routing_params``) — dieselbe, aus der der Spielraum stammt, auch wenn
    sich die Fahrzeugliste seither geändert hat.
    """
    _subsection(pdf, "Durchfahrtshöhen")
    ohne = sum(1 for v in vehicles if not v.get("height_cm"))
    pdf.set_font("DV", "", 9)
    if fahrzeughoehe_m:
        text = f"  • Höchstes Fahrzeug: {fahrzeughoehe_m:.2f} m".replace(".", ",")
    else:
        text = "  • Keine Fahrzeughöhe erfasst – die Route meidet keine Höhenbeschränkung"
    if ohne and fahrzeughoehe_m:
        text += f" ({ohne} Fahrzeug{'e' if ohne != 1 else ''} ohne Höhenangabe)"
    pdf.multi_cell(0, 5, text, new_x="LMARGIN", new_y="NEXT")

    zeigen = hoehe_svc.hinweispflichtig(eintraege)
    if zeigen:
        cols = [(25, "km"), (30, "Höhe"), (30, "Spielraum"), (0, "Hinweis")]
        cols[-1] = (total_w - sum(c[0] for c in cols[:-1]), "Hinweis")
        _table_header(pdf, cols)
        pdf.set_font("DV", "", 8)
        fill = False
        for e in zeigen:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            sp = e.get("spielraum_m")
            pdf.cell(cols[0][0], 6, f"{e.get('km', 0):.1f} km", border=1, fill=fill)
            pdf.cell(cols[1][0], 6, f"{e.get('hoehe_m', 0):.1f} m".replace(".", ","), border=1, fill=fill)
            pdf.cell(cols[2][0], 6, "-" if sp is None else f"{sp * 100:+.0f} cm", border=1, fill=fill)
            hinweis = ", ".join(t for t in (
                route_steps_svc.abschnitt_text(e.get("laenge_m")), _STUFE_LABELS.get(e.get("stufe", ""), ""),
            ) if t)
            pdf.cell(cols[3][0], 6, hinweis, border=1, fill=fill,
                     new_x="LMARGIN", new_y="NEXT")
            fill = not fill
    rest = len(eintraege) - len(zeigen)
    pdf.set_font("DV", "", 7.5)
    pdf.set_text_color(80, 80, 80)
    if not eintraege:
        pdf.multi_cell(0, 4, "Keine Höhenbeschränkung auf der Strecke bekannt.", new_x="LMARGIN", new_y="NEXT")
    elif rest:
        pdf.multi_cell(
            0, 4,
            f"{rest} weitere Höhenbeschränkung{'en' if rest != 1 else ''} mit mindestens "
            f"{hoehe_svc.KNAPP_M * 100:.0f} cm Spielraum.",
            new_x="LMARGIN", new_y="NEXT",
        )
    pdf.set_text_color(0, 0, 0)

    # Brücken über der Route, für die OSM keine Höhe kennt (services/bruecken.py).
    pdf.ln(1)
    pdf.set_font("DV", "B", 8.5)
    pdf.cell(0, 5, "Brücken ohne Höhenangabe", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DV", "", 7.5)
    pdf.set_text_color(80, 80, 80)
    if bruecken is None:
        pdf.multi_cell(
            0, 4, "Nicht gesucht – Route in der Planungsansicht öffnen, die Suche läuft dort.",
            new_x="LMARGIN", new_y="NEXT",
        )
    else:
        alle = bruecken.get("eintraege") or []
        einzeln = [b for b in alle if not b.get("schnellstrasse")]
        schnell = len(alle) - len(einzeln)
        pdf.set_text_color(0, 0, 0)
        if einzeln:
            cols = [(25, "km"), (50, "Bauwerk"), (0, "Name")]
            cols[-1] = (total_w - sum(c[0] for c in cols[:-1]), "Name")
            _table_header(pdf, cols)
            pdf.set_font("DV", "", 8)
            fill = False
            for b in einzeln:
                pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
                pdf.cell(cols[0][0], 6, f"{b.get('km', 0):.1f} km", border=1, fill=fill)
                pdf.cell(cols[1][0], 6, str(b.get("art", ""))[:30], border=1, fill=fill)
                pdf.cell(cols[2][0], 6, str(b.get("name") or "-")[:60], border=1, fill=fill,
                         new_x="LMARGIN", new_y="NEXT")
                fill = not fill
        pdf.set_font("DV", "", 7.5)
        pdf.set_text_color(80, 80, 80)
        zeilen = []
        if not alle:
            zeilen.append("Keine Brücke ohne Höhenangabe über der Route gefunden.")
        if schnell:
            zeilen.append(
                f"{schnell} {'weitere ' if einzeln else ''}auf Autobahn- oder Kraftfahrstraßenabschnitten, "
                "nicht einzeln aufgeführt."
            )
        if zeilen:
            pdf.multi_cell(0, 4, "\n".join(zeilen), new_x="LMARGIN", new_y="NEXT")

    pdf.multi_cell(
        0, 4,
        "Angaben aus OpenStreetMap, Höhen auf 10 cm gerundet. Maßgeblich ist die Beschilderung vor Ort.",
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


_GEWICHT_LABELS = {
    "ueberschritten": "ÜBER DER GRENZE",
    "knapp": "knapp",
    "unbekannt": "Fahrzeuggewicht fehlt",
    "frei": "",
}


def _gewichtsgrenzen(
    pdf: _PDF,
    eintraege: list[dict],
    vehicles: list[dict],
    fahrzeuggewicht_t: float | None,
    total_w: float,
    achslast_t: float | None = None,
) -> None:
    """Gewichts- und Achslastgrenzen mit wenig Reserve (services/gewichtsgrenzen.py).

    Das Gewicht stammt wie die Höhe aus ``routing_params`` — dem Stand, mit dem
    die Route berechnet wurde.
    """
    _subsection(pdf, "Gewichtsgrenzen")
    ohne = sum(1 for v in vehicles if not v.get("weight_kg"))
    pdf.set_font("DV", "", 9)
    if fahrzeuggewicht_t:
        text = f"  • Schwerstes Fahrzeug: {fahrzeuggewicht_t:.1f} t".replace(".", ",")
        if ohne:
            text += f" ({ohne} Fahrzeug{'e' if ohne != 1 else ''} ohne Gewichtsangabe)"
    else:
        text = "  • Kein Fahrzeuggewicht erfasst – die Route meidet keine Gewichtsgrenze"
    if achslast_t:
        text += f"\n  • Größte Achslast: {achslast_t:.1f} t".replace(".", ",")
    pdf.multi_cell(0, 5, text, new_x="LMARGIN", new_y="NEXT")

    zeigen = gewicht_svc.hinweispflichtig(eintraege)
    if zeigen:
        cols = [(25, "km"), (25, "Grenze"), (25, "Reserve"), (40, "Ausnahme"), (0, "Hinweis")]
        cols[-1] = (total_w - sum(c[0] for c in cols[:-1]), "Hinweis")
        _table_header(pdf, cols)
        pdf.set_font("DV", "", 8)
        fill = False
        for e in zeigen:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            r = e.get("reserve_t")
            pdf.cell(cols[0][0], 6, f"{e.get('km', 0):.1f} km", border=1, fill=fill)
            grenze = f"{e.get('grenze_t', 0):.1f} t".replace(".", ",")
            if e.get("art") == "achslast":
                grenze = f"Achse {grenze}"
            pdf.cell(cols[1][0], 6, grenze, border=1, fill=fill)
            pdf.cell(cols[2][0], 6, "-" if r is None else f"{r:+.1f} t".replace(".", ","), border=1, fill=fill)
            pdf.cell(cols[3][0], 6, gewicht_svc.AUSNAHMEN.get(e.get("ausnahme") or "", "-"), border=1, fill=fill)
            hinweis = ", ".join(t for t in (
                route_steps_svc.abschnitt_text(e.get("laenge_m")), _GEWICHT_LABELS.get(e.get("stufe", ""), ""),
            ) if t)
            pdf.cell(cols[4][0], 6, hinweis, border=1, fill=fill,
                     new_x="LMARGIN", new_y="NEXT")
            fill = not fill
    rest = len(eintraege) - len(zeigen)
    pdf.set_font("DV", "", 7.5)
    pdf.set_text_color(80, 80, 80)
    zeilen = []
    if not eintraege:
        zeilen.append("Keine Gewichtsgrenze auf der Strecke bekannt.")
    elif rest:
        zeilen.append(
            f"{rest} weitere Grenze{'n' if rest != 1 else ''} mit ausreichender Reserve "
            f"(Gewicht ab {gewicht_svc.KNAPP_T:.0f} t, Achslast ab {gewicht_svc.KNAPP_ACHSE_T:.0f} t)."
        )
    zeilen.append(
        "Angaben aus OpenStreetMap (auch Lkw-Durchfahrtsverbote), Gewicht auf 0,1 t, Achslast auf 0,5 t "
        "gerundet; verglichen mit dem schwersten Fahrzeug bzw. der größten Achslast im Verband. "
        "Maßgeblich ist die Beschilderung vor Ort."
    )
    pdf.multi_cell(0, 4, "\n".join(zeilen), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


def _build_marschweg(waypoints: list[dict]) -> str:
    """Build 'von X über Y, Z nach W' route description from waypoints."""
    names = [w["name"] for w in waypoints if w.get("name")]
    if not names:
        return "-"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"von {names[0]} nach {names[-1]}"
    middle = ", ".join(names[1:-1])
    return f"von {names[0]} über {middle} nach {names[-1]}"


# ── Ableitungen für den Marschbefehl ──────────────────────────────────────
# PDF und Word-Vorlage (services/marschbefehl_vorlage.py) bekommen dieselben
# Werte: was hier abgeleitet oder vorbelegt wird, steht in beiden gleich.

BETRIEBSSTOFF_STANDARD = "Alle Fahrzeuge haben sich grundsätzlich vollgetankt am Ablaufpunkt einzufinden."

BELEUCHTUNG_STANDARD = (
    "Alle Fahrzeuge: Abblendlicht einschalten, auch am Tag.\n"
    "Fahrzeuge des Katastrophenschutzes: blaues Blinklicht ohne Einsatzhorn."
)

BEFLAGGUNG = (
    "Erstes bis vorletztes Fahrzeug (außer Krad): vorne links BLAUE Flagge (40×40 cm)",
    "Letztes Fahrzeug (Schließende/r): vorne links GRÜNE Flagge (40×40 cm)",
    "Liegengebliebene Fahrzeuge: vorne links GELBE Flagge (40×40 cm)",
)

# Marschpausen nach FwDV: a) Technische Halte, b) Raste. Ein Tank- oder
# Wartungshalt ist der Sache nach ein Technischer Halt; jeder andere Halt
# (Rast, Lenkpause, Sonstiges) steht unter den Rasten, damit keiner fehlt.
_TH_ZWECKE = frozenset({"fuel", "maintenance"})


def feld(convoy: Any, name: str) -> str:
    """Ein Freitextfeld des Konvois, getrimmt; fehlend oder leer ``""``."""
    wert = getattr(convoy, name, None)
    return str(wert).strip() if wert else ""


def fahrzeug_kurz(v: dict) -> str:
    """„Pos. 6 – Florian Musterstadt 66/1 (MU-FW 661)“."""
    text = f"Pos. {v.get('position', 0) + 1} – {v.get('callsign') or v.get('name') or 'Fahrzeug'}"
    if v.get("license_plate"):
        text += f" ({v['license_plate']})"
    return text


def schliessender(vehicles: list[dict]) -> str:
    """Schließende/r: das Fahrzeug mit dieser Sonderfunktion, sonst das letzte
    der Marschfolge — dasselbe, das die grüne Flagge führt."""
    markiert = [v for v in vehicles if v.get("sonderfunktion") == "schließender"]
    if markiert:
        return "; ".join(fahrzeug_kurz(v) for v in markiert)
    if vehicles:
        return f"{fahrzeug_kurz(max(vehicles, key=lambda v: v.get('position', 0)))} (letztes Fahrzeug)"
    return ""


def platz_fuehrung(convoy: Any, vehicles: list[dict]) -> str:
    """Eingetragen, sonst das Führungsfahrzeug aus der Marschfolge, sonst leer —
    geraten wird nicht."""
    if text := feld(convoy, "platz_fuehrung"):
        return text
    fuehrung = [v for v in vehicles if v.get("sonderfunktion") == "führungsfahrzeug"]
    return "; ".join(f"im Führungsfahrzeug, {fahrzeug_kurz(v)}" for v in fuehrung)


def aerztliche_versorgung(convoy: Any, vehicles: list[dict]) -> str:
    """Eingetragen, sonst die Fahrzeuge mit sanitätsdienstlicher Absicherung."""
    if text := feld(convoy, "aerztliche_versorgung"):
        return text
    san = [v for v in vehicles if v.get("sonderfunktion") == "sanitaet"]
    if san:
        return "Sanitätsdienstliche Absicherung: " + "; ".join(fahrzeug_kurz(v) for v in san)
    return ""


def durchschnitt_kmh(route: Any | None) -> int | None:
    """Theoretische Durchschnittsgeschwindigkeit (FwDV): Marschentfernung durch
    reine Fahrzeit des Verbands (``route.duration_s`` = ``convoy_duration_s``,
    ohne Halte)."""
    dist = getattr(route, "distance_m", None) if route else None
    dauer = getattr(route, "duration_s", None) if route else None
    if not dist or not dauer:
        return None
    return round(dist / dauer * 3.6)


def ist_technischer_halt(w: dict) -> bool:
    return w.get("type") == "technical_stop" or (
        w.get("type") == "stop" and w.get("halt_purpose") in _TH_ZWECKE
    )


def marschpausen(waypoints: list[dict]) -> tuple[list[dict], list[dict]]:
    """(Technische Halte, Raste) in Reihenfolge der Route."""
    halte = [w for w in waypoints if w.get("type") in ("stop", "technical_stop")]
    return [w for w in halte if ist_technischer_halt(w)], [w for w in halte if not ist_technischer_halt(w)]


def marschraum(convoy: Any, waypoints: list[dict]) -> str:
    """„Befehl für den Marsch in den Raum …“ — eingetragen, sonst das Marschziel."""
    return feld(convoy, "marschraum") or (waypoints[-1].get("name") or "" if waypoints else "")


# ── Bausteine ─────────────────────────────────────────────────────────────

_LEER = "-"


def _punkt(pdf: _PDF, label: str, value: str | None):
    """Ein Unterpunkt der FwDV. Kurze Bezeichnung und Wert in einer Zeile,
    lange Bezeichnung als eigene Zeile mit eingerücktem Wert darunter."""
    wert = (value or "").strip() or _LEER
    pdf.set_font("DV", "B", 9)
    if pdf.get_string_width(f"{label}:") <= 62 and "\n" not in wert:
        _kv(pdf, f"{label}:", wert, label_w=64)
        return
    pdf.set_font("DV", "B", 9)
    pdf.multi_cell(0, 5, f"{label}:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DV", "", 9)
    pdf.set_x(pdf.l_margin + 6)
    pdf.multi_cell(0, 5, wert, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(0.5)


def _punkt_titel(pdf: _PDF, label: str):
    """Bezeichnung eines Unterpunkts, dem eine Tabelle oder Liste folgt —
    nicht allein am Seitenende."""
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()
    pdf.ln(1)
    pdf.set_font("DV", "B", 9)
    pdf.cell(0, 5, f"{label}:", new_x="LMARGIN", new_y="NEXT")


def _stichpunkte(pdf: _PDF, zeilen: list[str] | tuple[str, ...]):
    pdf.set_font("DV", "", 9)
    pdf.multi_cell(0, 5, "\n".join(f"  • {z}" for z in zeilen), new_x="LMARGIN", new_y="NEXT")


def _hinweis(pdf: _PDF, text: str):
    pdf.set_font("DV", "", 7.5)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(0, 4, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _halte_tabelle(pdf: _PDF, halte: list[dict], total_w: float):
    if not halte:
        pdf.set_font("DV", "", 9)
        pdf.cell(0, 5, "  keine geplant", new_x="LMARGIN", new_y="NEXT")
        return
    cols = [(0, "Ort"), (50, "Art"), (25, "Ankunft"), (25, "Dauer")]
    cols[0] = (total_w - sum(c[0] for c in cols[1:]), "Ort")
    _table_header(pdf, cols)
    pdf.set_font("DV", "", 8)
    fill = False
    for w in halte:
        pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
        art = TYPE_LABELS.get(w.get("type", ""), w.get("type", ""))
        if w.get("halt_purpose"):
            art += f" ({PURPOSE_LABELS.get(w['halt_purpose'], w['halt_purpose'])})"
        dur = f"{w['hold_duration_min']} min" if w.get("hold_duration_min") else "-"
        pdf.cell(cols[0][0], 6, (w.get("name") or "-")[:45], border=1, fill=fill)
        pdf.cell(cols[1][0], 6, art[:30], border=1, fill=fill)
        pdf.cell(cols[2][0], 6, _fmt_time_short(w.get("planned_arrival")), border=1, fill=fill)
        pdf.cell(cols[3][0], 6, dur, border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
        if vermerk := halt_vermerk(w.get("zusammengelegt"), w.get("hold_duration_min")):
            pdf.set_font("DV", "B", 8)
            pdf.cell(total_w, 6, f"  ↳ {vermerk}", border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("DV", "", 8)
        fill = not fill


def generate_marschbefehl(
    convoy: Any,
    waypoints: list[dict],
    vehicles: list[dict],
    route: Any | None,
    kanalwechsel: list[dict] | None = None,
    durchfahrtshoehen: list[dict] | None = None,
    bruecken: dict | None = None,
    gewichtsgrenzen: list[dict] | None = None,
    jetzt: datetime | None = None,
) -> bytes:
    """Marschbefehl nach dem Muster der FwDV 100, Anlage 4.

    Kopf, die Hauptziffern 1–5 mit ihren Unterpunkten, dann Anlagen,
    Verteiler und Unterschrift — in Reihenfolge und mit den Begriffen der
    Dienstvorschrift („Die Reihenfolge der Hauptziffern ist aber immer
    einzuhalten“). Jeder Punkt wird gedruckt, ein leerer mit „-“: Nicht zu
    jedem Punkt muss etwas angeordnet werden, aber wer den Befehl liest, soll
    sehen, dass nichts vergessen wurde.

    Was ConvoyPlan darüber hinaus weiß — Geschwindigkeit und Abstände nach
    Straßenart, Beflaggung, Durchlaufpunkte, Fahrzeugmaße, Durchfahrtshöhen,
    Gewichtsgrenzen, Kanalwechsel —, steht an der passenden FwDV-Stelle:
    unter dem jeweiligen Punkt oder unter 3. „Besondere Einzelheiten je nach
    Lage“ bzw. 5. „Kommunikationsverbindungen während des Marsches“.

    Abgangsdatum und -zeit sind der Zeitpunkt des Exports (``jetzt``): der
    Befehl geht mit dem Ausdruck hinaus. Der Beginn des Marsches steht unter
    „Ablaufzeit“.
    """
    jetzt = jetzt or datetime.now()
    pdf = _PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    total_w = pdf.w - pdf.l_margin - pdf.r_margin

    # ── Kopf ──────────────────────────────────────────────────────────────────
    abgang = f"{feld(convoy, 'abgangsort') or '______________'}, {jetzt.strftime('%d.%m.%Y, %H:%M')} Uhr"
    pdf.set_font("DV", "B", 10)
    pdf.cell(105, 5, (feld(convoy, "organization") or "Befehlende Stelle")[:60], new_x="RIGHT", new_y="TOP")
    pdf.set_font("DV", "", 9)
    pdf.cell(0, 5, abgang, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DV", "", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(105, 4, "(Befehlende Stelle, taktische Bezeichnung)", new_x="RIGHT", new_y="TOP")
    pdf.cell(0, 4, "(Abgangsort, Abgangsdatum, Abgangszeit)", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("DV", "", 9)
    pdf.cell(0, 5, f"Marschverband: {convoy.name}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("DV", "B", 11)
    pdf.multi_cell(
        0, 6, f"Befehl für den Marsch in den Raum {marschraum(convoy, waypoints) or '______________'}",
        align="C", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_font("DV", "", 9)
    pdf.cell(0, 5, f"Karte: {feld(convoy, 'karte') or _LEER}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # ── 1. Lage ───────────────────────────────────────────────────────────────
    _section(pdf, "1", "Lage")
    _punkt(pdf, "Gefahren- / Schadenlage", feld(convoy, "lage"))
    _punkt(pdf, "Eigene Lage", feld(convoy, "lage_eigene"))

    # ── 2. Auftrag ────────────────────────────────────────────────────────────
    _section(pdf, "2", "Auftrag")
    _punkt(pdf, "Zuteilung, Unterstellung und Abgabe von Kräften", feld(convoy, "kraefte"))
    _punkt(pdf, "Erhaltener Auftrag", feld(convoy, "auftrag"))

    # ── 3. Durchführung ───────────────────────────────────────────────────────
    _section(pdf, "3", "Durchführung")
    dist_km = (route.distance_m or 0) / 1000 if route else 0
    _punkt(pdf, "Marschziel", waypoints[-1]["name"] if waypoints else "")
    _punkt(pdf, "Marschweg", _build_marschweg(waypoints) if waypoints else "")
    _punkt(pdf, "Marschentfernung", f"{dist_km:.1f} km".replace(".", ",") if dist_km else "")
    _punkt(pdf, "Marschform", MARSCHFORM_LABELS.get(convoy.marschform or "", convoy.marschform or ""))

    _punkt_titel(pdf, "Marschfolge")
    cols_mf = [(12, "Pos."), (45, "Funkrufname"), (35, "KFZ-Kennzeichen"), (35, "Mobiltelefon"), (0, "Sonderfunktion")]
    cols_mf[-1] = (total_w - sum(c[0] for c in cols_mf[:-1]), "Sonderfunktion")
    if vehicles:
        _table_header(pdf, cols_mf)
        pdf.set_font("DV", "", 8)
        fill = False
        for v in vehicles:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            sonder = SONDERFUNKTION_LABELS.get(v.get("sonderfunktion") or "", v.get("sonderfunktion") or "-")
            pdf.cell(cols_mf[0][0], 6, str(v["position"] + 1), border=1, fill=fill)
            pdf.cell(cols_mf[1][0], 6, (v.get("callsign") or "-")[:22], border=1, fill=fill)
            pdf.cell(cols_mf[2][0], 6, (v.get("license_plate") or "-")[:18], border=1, fill=fill)
            pdf.cell(cols_mf[3][0], 6, (v.get("mobile_phone") or "-")[:18], border=1, fill=fill)
            pdf.cell(cols_mf[4][0], 6, sonder[:28], border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            fill = not fill
    else:
        pdf.set_font("DV", "", 9)
        pdf.cell(0, 5, "  keine Fahrzeuge eingeteilt", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    _punkt(pdf, "Marschführer/in", feld(convoy, "marschfuehrer"))
    _punkt(pdf, "Führer/innen der Einzelgruppen", feld(convoy, "einzelgruppen_fuehrer"))
    _punkt(pdf, "Schließende/r", schliessender(vehicles))
    _punkt(pdf, "Marschabstand", feld(convoy, "marschabstand"))
    _punkt(
        pdf, "Fahrzeugabstand",
        f"innerorts {getattr(convoy, 'spacing_urban_m', 15)} m, "
        f"außerorts {getattr(convoy, 'spacing_rural_m', 50)} m, "
        f"Autobahn {getattr(convoy, 'spacing_motorway_m', 100)} m",
    )
    _punkt(pdf, "Ablaufpunkt", feld(convoy, "ablaufpunkt"))
    _punkt(pdf, "Ablaufzeit", _fmt_time(str(convoy.ablaufzeit)) if convoy.ablaufzeit else "")
    _punkt(pdf, "Ablaufführer/in", feld(convoy, "ablaufführer"))

    schnitt = durchschnitt_kmh(route)
    _punkt(
        pdf, "Marschgeschwindigkeit",
        f"Ø {schnitt} km/h (theoretische Durchschnittsgeschwindigkeit)" if schnitt else "",
    )
    _stichpunkte(pdf, (
        f"Höchstens innerorts {convoy.speed_urban_kmh} km/h, außerorts {convoy.speed_rural_kmh} km/h",
        "Die jeweils gültige Höchstgeschwindigkeit darf nicht überschritten werden",
        "Marschverzögerungen dürfen nicht durch höhere Geschwindigkeit aufgeholt werden",
    ))
    _punkt(pdf, "Beleuchtung", feld(convoy, "beleuchtung") or BELEUCHTUNG_STANDARD)
    _punkt(pdf, "Marschüberwachung und Verkehrssicherung", feld(convoy, "marschueberwachung"))

    technische_halte, raste = marschpausen(waypoints)
    _punkt_titel(pdf, "Marschpausen")
    pdf.set_font("DV", "B", 8.5)
    pdf.cell(0, 5, "  a) Technische Halte", new_x="LMARGIN", new_y="NEXT")
    _halte_tabelle(pdf, technische_halte, total_w)
    pdf.set_font("DV", "B", 8.5)
    pdf.cell(0, 5, "  b) Raste", new_x="LMARGIN", new_y="NEXT")
    _halte_tabelle(pdf, raste, total_w)
    _hinweis(
        pdf,
        "Technischer Halt: KFZ überprüfen, ggf. leichte Schäden beseitigen, ggf. Betriebsstoff nachfüllen. "
        "Nach Fahrzeit von ca. 2 Stunden, Verbleib auf Marschstraße (Parkplatz). Dauer: 20-30 Minuten.\n"
        "Rast: Nur bei längeren Märschen, nach 5-6 Std. Marschzeit, abseits der Marschstraße. Dauer: 2-3 Stunden.",
    )

    # Besondere Einzelheiten: der Freitext, dann was ConvoyPlan zur Strecke weiß.
    _punkt(pdf, "Besondere Einzelheiten je nach Lage", feld(convoy, "besonderes"))

    _subsection(pdf, "Beflaggung")
    _stichpunkte(pdf, BEFLAGGUNG)
    pdf.ln(2)

    checkpoints = [w for w in waypoints if w.get("type") in ("checkpoint", "waypoint")]
    if checkpoints:
        _subsection(pdf, "Durchlaufpunkte")
        cols_dp = [(0, "Durchlaufpunkt"), (40, "Geplante Durchlaufzeit"), (50, "Anmerkungen")]
        cols_dp[0] = (total_w - cols_dp[1][0] - cols_dp[2][0], "Durchlaufpunkt")
        _table_header(pdf, cols_dp)
        pdf.set_font("DV", "", 8)
        fill = False
        for w in checkpoints:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(cols_dp[0][0], 6, w["name"][:35], border=1, fill=fill)
            pdf.cell(cols_dp[1][0], 6, _fmt_time_short(w.get("planned_arrival")), border=1, fill=fill)
            pdf.cell(cols_dp[2][0], 6, (w.get("notes") or "")[:28], border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            fill = not fill
        pdf.ln(3)

    if vehicles:
        _subsection(pdf, "Fahrzeuge im Verband")
        cols_kfz = [(10, "Pos"), (50, "Fahrzeug / Rufname"), (30, "Kennzeichen"), (22, "Höhe"), (25, "Gewicht"), (0, "")]
        cols_kfz[-1] = (total_w - sum(c[0] for c in cols_kfz[:-1]), "Aufgabe / Rolle")
        _table_header(pdf, cols_kfz)
        pdf.set_font("DV", "", 8)
        fill = False
        for v in vehicles:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            label = v["name"]
            if v.get("callsign"):
                label += f' ({v["callsign"]})'
            sonder = SONDERFUNKTION_LABELS.get(v.get("sonderfunktion") or "", v.get("convoy_role") or "-")
            pdf.cell(cols_kfz[0][0], 6, str(v["position"] + 1), border=1, fill=fill)
            pdf.cell(cols_kfz[1][0], 6, label[:28], border=1, fill=fill)
            pdf.cell(cols_kfz[2][0], 6, (v.get("license_plate") or "-")[:16], border=1, fill=fill)
            pdf.cell(cols_kfz[3][0], 6, f'{v["height_cm"]/100:.2f} m' if v.get("height_cm") else "-", border=1, fill=fill)
            pdf.cell(cols_kfz[4][0], 6, f'{v["weight_kg"]:,} kg' if v.get("weight_kg") else "-", border=1, fill=fill)
            pdf.cell(cols_kfz[5][0], 6, sonder[:25], border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            fill = not fill
        pdf.ln(3)

    # Durchfahrtshöhen — None: Route vor der Auswertung berechnet, dann nichts.
    params = getattr(route, "routing_params", None) or {}
    if durchfahrtshoehen is not None:
        _durchfahrtshoehen(pdf, durchfahrtshoehen, vehicles, params.get("max_height_m"), total_w, bruecken)
    # Gewichtsgrenzen — None: nicht ermittelt, dann nichts.
    if gewichtsgrenzen is not None:
        _gewichtsgrenzen(
            pdf, gewichtsgrenzen, vehicles, params.get("max_weight_t"), total_w, params.get("max_axle_load_t")
        )

    # ── 4. Versorgung ─────────────────────────────────────────────────────────
    _section(pdf, "4", "Versorgung")
    _punkt(pdf, "Verpflegung", feld(convoy, "verpflegung"))
    _punkt(pdf, "Betriebsstoff", feld(convoy, "betriebsstoff") or BETRIEBSSTOFF_STANDARD)
    _punkt(pdf, "Instandsetzungsdienst", feld(convoy, "instandsetzung"))
    _punkt(pdf, "Ärztliche Versorgung", aerztliche_versorgung(convoy, vehicles))
    # Der Freitext von vor der FwDV-Gliederung (Migration 0076) — er lässt
    # sich nicht auf die vier Punkte aufteilen und steht deshalb dahinter.
    if ergaenzend := feld(convoy, "versorgung"):
        _punkt(pdf, "Ergänzend", ergaenzend)

    # ── 5. Führung und Verbindung ─────────────────────────────────────────────
    _section(pdf, "5", "Führung und Verbindung")
    _punkt(
        pdf, "Kommunikationsverbindungen während des Marsches",
        f"Funkgruppe: {feld(convoy, 'funkgruppe')}" if feld(convoy, "funkgruppe") else "",
    )
    if kanalwechsel:
        _subsection(pdf, "Kanalwechsel")
        kw_aktionen = {"abmelden": "Abmelden", "convoy_anmeldung": "Convoy Anmeldung"}
        kw_cols = [
            (25, "km"),
            (36, "Aktion"),
            (total_w - 25 - 36 - 40, "Leitstelle"),
            (40, "Anrufgruppe"),
        ]
        _table_header(pdf, kw_cols)
        pdf.set_font("DV", "", 8)
        fill = False
        for kw in kanalwechsel:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            aktion = kw_aktionen.get(kw.get("typ"), "Anmelden")
            pdf.cell(kw_cols[0][0], 6, f"{kw.get('km', 0):.1f} km", border=1, fill=fill)
            pdf.cell(kw_cols[1][0], 6, aktion, border=1, fill=fill)
            pdf.cell(kw_cols[2][0], 6, str(kw.get("leitstelle_name", ""))[:35], border=1, fill=fill)
            pdf.cell(kw_cols[3][0], 6, str(kw.get("anrufgruppe", "")), border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            # Weitere hinterlegte Funkgruppen der Leitstelle als Zusatzzeile
            # (nur beim Anmelden — beim Abmelden ist die Info nicht mehr relevant).
            zusatz = kw.get("zusatz_kanaele") or []
            if zusatz and kw.get("typ") != "abmelden":
                zusatz_text = "  •  ".join(
                    f"{z.get('name', 'Kanal')}: {z.get('kanal', '')}" for z in zusatz if isinstance(z, dict)
                )
                if zusatz_text:
                    pdf.set_font("DV", "", 7)
                    pdf.cell(kw_cols[0][0], 5, "", border=1, fill=fill)
                    pdf.cell(
                        total_w - kw_cols[0][0], 5, f"Zusatzkanäle: {zusatz_text}"[:110],
                        border=1, fill=fill, new_x="LMARGIN", new_y="NEXT",
                    )
                    pdf.set_font("DV", "", 8)
            fill = not fill
        pdf.ln(2)
    _punkt(pdf, "Sonstige Verbindungen, Lotsenstellen und Verkehrsleitpunkte", feld(convoy, "verbindungen"))
    _punkt(pdf, "Platz der Führungskraft", platz_fuehrung(convoy, vehicles))

    # ── Anlagen, Verteiler (ohne Hauptziffer) ────────────────────────────────
    _section(pdf, None, "Anlagen")
    _textblock(pdf, feld(convoy, "anlagen") or _LEER)
    _section(pdf, None, "Verteiler")
    _textblock(pdf, feld(convoy, "verteiler") or _LEER)

    # ── Unterschrift (Name, Dienststellung) ──────────────────────────────────
    if pdf.get_y() > pdf.h - 50:
        pdf.add_page()
    x = pdf.l_margin + total_w / 2
    breite = total_w / 2
    pdf.ln(4)
    pdf.set_x(x)
    pdf.set_font("DV", "B", 9)
    pdf.cell(breite, 5, "Unterschrift", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(12)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.3)
    pdf.line(x, pdf.get_y(), x + breite, pdf.get_y())
    pdf.ln(1)
    unterzeichner = ", ".join(
        t for t in (feld(convoy, "unterschrift_name"), feld(convoy, "unterschrift_dienststellung")) if t
    )
    if unterzeichner:
        pdf.set_x(x)
        pdf.set_font("DV", "", 9)
        pdf.cell(breite, 5, unterzeichner[:70], new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(x)
    pdf.set_font("DV", "", 7)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(breite, 4, "(Name, Dienststellung)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
