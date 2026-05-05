from datetime import datetime
from io import BytesIO
from typing import Any

from fpdf import FPDF


class _PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 18)
        self.cell(0, 10, "MARSCHBEFEHL", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(26, 39, 68)
        self.set_line_width(0.8)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')} Uhr  |  MarschPlan", align="C")


def _row(pdf: _PDF, label: str, value: str, bold_label: bool = True):
    pdf.set_font("Helvetica", "B" if bold_label else "", 9)
    pdf.cell(50, 6, label)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")


def _section(pdf: _PDF, title: str):
    pdf.ln(3)
    pdf.set_fill_color(26, 39, 68)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


def generate_marschbefehl(convoy: Any, waypoints: list[dict], vehicles: list[dict], route: Any | None) -> bytes:
    pdf = _PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # --- Convoy-Info ---
    _section(pdf, "Verbandsinfo")
    _row(pdf, "Marschverband:", convoy.name)
    _row(pdf, "Organisation:", convoy.organization or "–")
    _row(pdf, "Startzeit:", convoy.start_time.strftime("%d.%m.%Y %H:%M Uhr") if convoy.start_time else "–")
    _row(pdf, "Status:", convoy.status.upper())
    _row(pdf, "Geschwindigkeit:", f"{convoy.speed_urban_kmh} km/h (innerorts) / {convoy.speed_rural_kmh} km/h (außerorts)")
    if route:
        dist_km = (route.distance_m or 0) / 1000
        dur_s = route.duration_s or 0
        h, m = divmod(dur_s // 60, 60)
        _row(pdf, "Strecke:", f"{dist_km:.1f} km")
        _row(pdf, "Fahrzeit:", f"{h} h {m:02d} min (Fahrzeit ohne Halte)")

    # --- Fahrzeuge ---
    _section(pdf, f"Fahrzeuge ({len(vehicles)} Fahrzeuge)")
    col_w = [10, 45, 35, 22, 22, 45]
    headers = ["Nr", "Name / Rufname", "Kennzeichen", "Höhe", "Gewicht", "Funktion"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(220, 225, 235)
    for w, h_txt in zip(col_w, headers):
        pdf.cell(w, 6, h_txt, border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    fill = False
    pdf.set_fill_color(245, 246, 250)
    for v in vehicles:
        pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.cell(col_w[0], 6, str(v["position"] + 1), border=1, fill=fill)
        label = v["name"]
        if v.get("callsign"):
            label += f' ({v["callsign"]})'
        pdf.cell(col_w[1], 6, label[:28], border=1, fill=fill)
        pdf.cell(col_w[2], 6, v.get("license_plate") or "–", border=1, fill=fill)
        pdf.cell(col_w[3], 6, f'{v["height_cm"] / 100:.2f} m' if v.get("height_cm") else "–", border=1, fill=fill)
        pdf.cell(col_w[4], 6, f'{v["weight_kg"]:,} kg' if v.get("weight_kg") else "–", border=1, fill=fill)
        pdf.cell(col_w[5], 6, (v.get("convoy_role") or "–")[:25], border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
        fill = not fill

    # --- Wegpunkte & Zeitplan ---
    _section(pdf, "Marschroute & Zeitplan")
    wp_col = [10, 55, 30, 25, 25, 25, 19]
    wp_headers = ["Nr", "Bezeichnung", "Typ", "Ankunft", "Abfahrt", "Halt", "Zweck"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(220, 225, 235)
    for w, h_txt in zip(wp_col, wp_headers):
        pdf.cell(w, 6, h_txt, border=1, fill=True)
    pdf.ln()

    type_labels = {
        "waypoint": "Wegpunkt", "stop": "Halt", "checkpoint": "Kontrollpunkt",
        "technical_stop": "Techn. Halt",
    }
    purpose_labels = {"fuel": "Tanken", "rest": "Pause", "maintenance": "Wartung", "other": "Sonstiges"}

    pdf.set_font("Helvetica", "", 8)
    fill = False
    for i, wp in enumerate(waypoints):
        pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)

        def fmt_time(iso):
            if not iso:
                return "–"
            try:
                return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%H:%M")
            except Exception:
                return "–"

        hold = f'{wp["hold_duration_min"]} min' if wp.get("hold_duration_min") else "–"
        pdf.cell(wp_col[0], 6, str(i + 1), border=1, fill=fill)
        pdf.cell(wp_col[1], 6, wp["name"][:30], border=1, fill=fill)
        pdf.cell(wp_col[2], 6, type_labels.get(wp.get("type", ""), wp.get("type", "")), border=1, fill=fill)
        pdf.cell(wp_col[3], 6, fmt_time(wp.get("planned_arrival")), border=1, fill=fill)
        pdf.cell(wp_col[4], 6, fmt_time(wp.get("planned_departure")), border=1, fill=fill)
        pdf.cell(wp_col[5], 6, hold, border=1, fill=fill)
        pdf.cell(wp_col[6], 6, purpose_labels.get(wp.get("halt_purpose", ""), "–"), border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
        fill = not fill

    # --- Unterschrift ---
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(80, 6, "Ort, Datum: ________________________")
    pdf.cell(0, 6, "Unterschrift Einsatzleitung: ________________________", new_x="LMARGIN", new_y="NEXT")

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
