from datetime import datetime
from io import BytesIO
from typing import Any

from fpdf import FPDF

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


def _section(pdf: _PDF, number: str, title: str):
    pdf.ln(3)
    pdf.set_fill_color(26, 39, 68)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DV", "B", 10)
    pdf.cell(0, 7, f"  {number}. {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
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
    pdf.multi_cell(remaining, 5, value or "-", new_x="LMARGIN", new_y="NEXT")


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


def generate_marschbefehl(
    convoy: Any,
    waypoints: list[dict],
    vehicles: list[dict],
    route: Any | None,
    kanalwechsel: list[dict] | None = None,
) -> bytes:
    pdf = _PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Befehlende Stelle ──────────────────────────────────────────────────────
    pdf.set_font("DV", "B", 10)
    pdf.cell(120, 5, convoy.organization or "Befehlende Stelle", new_x="RIGHT", new_y="TOP")
    pdf.set_font("DV", "", 9)
    issued_at = convoy.start_time or datetime.now()
    pdf.cell(0, 5, issued_at.strftime("%d.%m.%Y"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DV", "", 9)
    pdf.cell(120, 5, f"Marschverband: {convoy.name}", new_x="RIGHT", new_y="TOP")
    pdf.cell(0, 5, issued_at.strftime("%H:%M Uhr"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ── 1. Lage ───────────────────────────────────────────────────────────────
    if convoy.lage:
        _section(pdf, "1", "Lage")
        _textblock(pdf, convoy.lage)

    # ── 2. Auftrag ────────────────────────────────────────────────────────────
    if convoy.auftrag:
        _section(pdf, "2", "Auftrag")
        _textblock(pdf, convoy.auftrag)

    # ── 3. Durchführung ───────────────────────────────────────────────────────
    _section(pdf, "3", "Durchführung")

    # Marschbewegung
    _subsection(pdf, "Marschbewegung")
    dist_km = (route.distance_m or 0) / 1000 if route else 0
    marschform_label = MARSCHFORM_LABELS.get(convoy.marschform or "", convoy.marschform or None)

    _kv(pdf, "Marschziel:", waypoints[-1]["name"] if waypoints else "-")
    _kv(pdf, "Marschweg:", _build_marschweg(waypoints))
    _kv(pdf, "Marschstrecke:", f"{dist_km:.1f} km" if dist_km else "-")
    if marschform_label:
        _kv(pdf, "Marschform:", marschform_label)
    pdf.ln(2)

    # Ablaufpunkt — nur anzeigen wenn mindestens ein Feld gesetzt ist
    has_ablauf = any([convoy.ablaufpunkt, convoy.ablaufzeit, getattr(convoy, "ablaufführer", None)])
    if has_ablauf:
        _subsection(pdf, "Ablaufpunkt")
        if convoy.ablaufpunkt:
            _kv(pdf, "Ablaufpunkt:", convoy.ablaufpunkt)
        if convoy.ablaufzeit:
            _kv(pdf, "Ablaufzeit:", _fmt_time(str(convoy.ablaufzeit)))
        if getattr(convoy, "ablaufführer", None):
            _kv(pdf, "Ablaufführer:", convoy.ablaufführer)
        pdf.ln(2)

    # Marschfolge-Tabelle
    _subsection(pdf, "Marschfolge")
    cols_mf = [(12, "Pos."), (45, "Funkrufname"), (35, "KFZ-Kennzeichen"), (35, "Mobiltelefon"), (0, "Sonderfunktion")]
    # Adjust last col width
    used = sum(c[0] for c in cols_mf[:-1])
    total_w = pdf.w - pdf.l_margin - pdf.r_margin
    cols_mf[-1] = (total_w - used, "Sonderfunktion")

    _table_header(pdf, cols_mf)
    pdf.set_font("DV", "", 8)
    fill = False
    pdf.set_fill_color(245, 246, 250)
    for v in vehicles:
        pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
        sonder = SONDERFUNKTION_LABELS.get(v.get("sonderfunktion") or "", v.get("sonderfunktion") or "-")
        pdf.cell(cols_mf[0][0], 6, str(v["position"] + 1), border=1, fill=fill)
        pdf.cell(cols_mf[1][0], 6, (v.get("callsign") or "-")[:22], border=1, fill=fill)
        pdf.cell(cols_mf[2][0], 6, (v.get("license_plate") or "-")[:18], border=1, fill=fill)
        pdf.cell(cols_mf[3][0], 6, (v.get("mobile_phone") or "-")[:18], border=1, fill=fill)
        pdf.cell(cols_mf[4][0], 6, sonder[:28], border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
        fill = not fill
    pdf.ln(3)

    # Marschgeschwindigkeit
    _subsection(pdf, "Marschgeschwindigkeit")
    pdf.set_font("DV", "", 9)
    pdf.multi_cell(
        0, 5,
        f"  • Innerorts: {convoy.speed_urban_kmh} km/h\n"
        f"  • Außerorts: {convoy.speed_rural_kmh} km/h\n"
        "  • Die jeweils gültige Höchstgeschwindigkeit darf nicht überschritten werden\n"
        "  • Marschverzögerungen dürfen nicht durch höhere Geschwindigkeit aufgeholt werden"
    )
    pdf.ln(2)

    # Fahrzeugabstände
    _subsection(pdf, "Fahrzeugabstände")
    pdf.set_font("DV", "", 9)
    pdf.multi_cell(
        0, 5,
        f"  • Innerorts: {getattr(convoy, 'spacing_urban_m', 15)} m\n"
        f"  • Außerorts: {getattr(convoy, 'spacing_rural_m', 50)} m\n"
        f"  • Autobahn: {getattr(convoy, 'spacing_motorway_m', 100)} m"
    )
    pdf.ln(2)

    # Beflaggung und Beleuchtung
    _subsection(pdf, "Beflaggung und Beleuchtung")
    pdf.set_font("DV", "", 9)
    pdf.multi_cell(
        0, 5,
        "  • Alle KFZ: Abblendlicht einschalten (auch am Tag)\n"
        "  • Alle KFZ (Katastrophenschutz): blaues Blinklicht ohne Einsatzhorn\n"
        "  • Erstes bis vorletztes KFZ (außer Krad): vorne links BLAUE Flagge (40×40 cm)\n"
        "  • Letztes KFZ (Schließender): vorne links GRÜNE Flagge (40×40 cm)\n"
        "  • Liegengebliebene KFZ: vorne links GELBE Flagge (40×40 cm)"
    )
    pdf.ln(2)

    # Durchlaufpunkte (checkpoints)
    checkpoints = [w for w in waypoints if w.get("type") in ("checkpoint", "waypoint")]
    if checkpoints:
        _subsection(pdf, "Durchlaufpunkte")
        cols_dp = [(0, "Durchlaufpunkt"), (40, "Geplante Durchlaufzeit"), (50, "Anmerkungen")]
        used_dp = cols_dp[1][0] + cols_dp[2][0]
        cols_dp[0] = (total_w - used_dp, "Durchlaufpunkt")
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

    # Marschpausen
    pauses = [w for w in waypoints if w.get("type") in ("stop", "technical_stop")]
    if pauses:
        _subsection(pdf, "Marschpausen")
        cols_mp = [(0, "Ort"), (45, "Art"), (40, "Dauer")]
        used_mp = cols_mp[1][0] + cols_mp[2][0]
        cols_mp[0] = (total_w - used_mp, "Ort")
        _table_header(pdf, cols_mp)
        pdf.set_font("DV", "", 8)
        fill = False
        for w in pauses:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            art = TYPE_LABELS.get(w.get("type", ""), w.get("type", ""))
            if w.get("halt_purpose"):
                art += f" ({PURPOSE_LABELS.get(w['halt_purpose'], w['halt_purpose'])})"
            dur = f"{w['hold_duration_min']} min" if w.get("hold_duration_min") else "-"
            pdf.cell(cols_mp[0][0], 6, w["name"][:30], border=1, fill=fill)
            pdf.cell(cols_mp[1][0], 6, art[:28], border=1, fill=fill)
            pdf.cell(cols_mp[2][0], 6, dur, border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            fill = not fill
        pdf.set_font("DV", "", 7.5)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(
            0, 4,
            "Technischer Halt: KFZ überprüfen, ggf. leichte Schäden beseitigen, ggf. Betriebsstoff nachfüllen. "
            "Nach Fahrzeit von ca. 2 Stunden, Verbleib auf Marschstraße (Parkplatz). Dauer: 20-30 Minuten.\n"
            "Rast: Nur bei längeren Märschen, nach 5-6 Std. Marschzeit, abseits der Marschstraße. Dauer: 2-3 Stunden."
        )
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    # Fahrzeugübersicht (Name, Abmessungen)
    _subsection(pdf, "Fahrzeuge im Verband")
    cols_kfz = [(10, "Pos"), (50, "Fahrzeug / Rufname"), (30, "Kennzeichen"), (22, "Höhe"), (25, "Gewicht"), (0, "Aufgabe")]
    used_kfz = sum(c[0] for c in cols_kfz[:-1])
    cols_kfz[-1] = (total_w - used_kfz, "Aufgabe / Rolle")
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

    # ── 4. Versorgung ─────────────────────────────────────────────────────────
    _section(pdf, "4", "Versorgung")
    pdf.set_font("DV", "", 9)
    versorgung_text = convoy.versorgung or ""
    if not versorgung_text:
        versorgung_text = "Verpflegung, Betriebsstoff, Instandsetzungsdienst, ärztliche/sanitätsdienstliche Versorgung."
    versorgung_text += "\n\nAlle Fahrzeuge haben sich grundsätzlich vollgetankt am Ablaufpunkt einzufinden!"
    _textblock(pdf, versorgung_text)

    # ── 5. Führung und Verbindung ─────────────────────────────────────────────
    _section(pdf, "5", "Führung und Verbindung")
    _kv(pdf, "Funkgruppe:", convoy.funkgruppe or "-")
    pdf.set_font("DV", "", 9)
    pdf.multi_cell(
        0, 5,
        "  • Kommunikationsverbindungen während des Marsches (Funkgruppe, Funkbereitschaft ab/bis)\n"
        "  • Kommunikationsverbindungen zur Ablaufstelle\n"
        "  • Kommunikationsverbindungen zu Lotsenstellen / Verkehrsleitpunkten / Meldeköpfen\n"
        "  • Platz der Führungskraft: Führungsfahrzeug an der Spitze"
    )
    pdf.ln(2)

    # ── Kanalwechsel (under section 5) ───────────────────────────────────────
    if kanalwechsel:
        _subsection(pdf, "Kanalwechsel")
        kw_cols = [
            (25, "km"),
            (28, "Aktion"),
            (total_w - 25 - 28 - 40, "Leitstelle"),
            (40, "Anrufgruppe"),
        ]
        _table_header(pdf, kw_cols)
        pdf.set_font("DV", "", 8)
        fill = False
        for kw in kanalwechsel:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            aktion = "Abmelden" if kw.get("typ") == "abmelden" else "Anmelden"
            pdf.cell(kw_cols[0][0], 6, f"{kw.get('km', 0):.1f} km", border=1, fill=fill)
            pdf.cell(kw_cols[1][0], 6, aktion, border=1, fill=fill)
            pdf.cell(kw_cols[2][0], 6, str(kw.get("leitstelle_name", ""))[:35], border=1, fill=fill)
            pdf.cell(kw_cols[3][0], 6, str(kw.get("anrufgruppe", "")), border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            fill = not fill
        pdf.ln(3)

    # ── 6. Anlagen ────────────────────────────────────────────────────────────
    if convoy.anlagen:
        _section(pdf, "6", "Anlagen")
        _textblock(pdf, convoy.anlagen)

    # ── Unterschrift ──────────────────────────────────────────────────────────
    pdf.ln(6)
    pdf.set_font("DV", "", 9)
    pdf.cell(90, 5, "Ort, Datum: ______________________________")
    pdf.cell(0, 5, "Unterschrift Marschverbandsführer/in: ______________________________", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("DV", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "Vor- und Nachname / Funktion", new_x="LMARGIN", new_y="NEXT")

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
