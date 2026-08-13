"""Export der Systemberichte als CSV und PDF.

Die Datengrundlage liefert ``app.services.system_metrics.monthly_report`` bzw.
``query_series``; hier wird sie nur noch in ein Ausgabeformat gegossen. CSV
verwendet Semikolon als Trennzeichen und Komma als Dezimaltrenner, weil die
Berichte in aller Regel in einem deutschsprachigen Excel landen — mit Punkt und
Komma vertauscht macht Excel aus „12.5" sonst ein Datum.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fpdf import FPDF

_FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

_ACCENT = (26, 39, 68)

# Spalten des Tagesteils: (Schlüssel, Überschrift, Nachkommastellen)
_DAY_COLUMNS: list[tuple[str, str, int | None]] = [
    ("t", "Tag", None),
    ("cpu_percent", "CPU Ø %", 1),
    ("cpu_percent_max", "CPU max %", 1),
    ("mem_percent", "RAM Ø %", 1),
    ("mem_percent_max", "RAM max %", 1),
    ("disk_percent", "Platte %", 1),
    ("psi_io_avg10", "I/O-Druck Ø %", 2),
    ("psi_io_max", "I/O-Druck max %", 2),
    ("unique_users", "Nutzer", 0),
    ("active_users_max", "Gleichzeitig max", 0),
    ("logins", "Anmeldungen", 0),
    ("requests", "Requests", 0),
    ("request_errors", "Fehler", 0),
    ("avg_response_ms", "Antwort Ø ms", 1),
    ("containers_unhealthy", "Container ungesund", 0),
]

_SUMMARY_ROWS: list[tuple[str, str, str]] = [
    ("cpu_percent_avg", "CPU-Auslastung Ø", "percent"),
    ("cpu_percent_max", "CPU-Auslastung Spitze", "percent"),
    ("mem_percent_avg", "Arbeitsspeicher Ø", "percent"),
    ("mem_percent_max", "Arbeitsspeicher Spitze", "percent"),
    ("disk_percent_avg", "Plattenbelegung Ø", "percent"),
    ("disk_percent_max", "Plattenbelegung Spitze", "percent"),
    ("disk_used_start_bytes", "Belegt am Monatsanfang", "bytes"),
    ("disk_used_end_bytes", "Belegt am Monatsende", "bytes"),
    ("psi_io_avg", "I/O-Druck Ø", "percent"),
    ("psi_io_max", "I/O-Druck Spitze", "percent"),
    ("db_size_start_bytes", "Datenbank am Monatsanfang", "bytes"),
    ("db_size_end_bytes", "Datenbank am Monatsende", "bytes"),
    ("unique_users", "Eindeutige Benutzer", "int"),
    ("active_users_avg", "Gleichzeitig aktiv Ø", "float"),
    ("active_users_max", "Gleichzeitig aktiv Spitze", "int"),
    ("logins", "Anmeldungen", "int"),
    ("requests", "API-Requests", "int"),
    ("request_errors", "Serverfehler (5xx)", "int"),
    ("avg_response_ms", "Antwortzeit Ø (ms)", "float"),
    ("containers_unhealthy_max", "Ungesunde Container (Spitze)", "int"),
    ("days_with_unhealthy_containers", "Tage mit Container-Störung", "int"),
    ("busiest_day", "Stärkster Tag", "raw"),
    ("busiest_day_users", "Benutzer am stärksten Tag", "int"),
]

_MONTH_NAMES = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def month_label(month: str) -> str:
    """``2026-08`` → ``August 2026``; unbekannte Formate unverändert."""
    try:
        year, mon = month.split("-")
        return f"{_MONTH_NAMES[int(mon) - 1]} {year}"
    except (ValueError, IndexError):
        return month


def format_bytes(value: Any) -> str:
    if value is None:
        return "-"
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return f"{size:.1f} TB"


def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "-"
    if kind == "bytes":
        return format_bytes(value)
    if kind == "percent":
        return f"{float(value):.1f} %".replace(".", ",")
    if kind == "int":
        return f"{int(value):,}".replace(",", ".")
    if kind == "float":
        return f"{float(value):.2f}".replace(".", ",")
    return str(value)


def _decimal(value: Any, places: int | None) -> str:
    """Zahl mit deutschem Dezimaltrenner für die CSV-Ausgabe."""
    if value is None:
        return ""
    if places is None:
        return str(value)
    try:
        return f"{float(value):.{places}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(value)


# ── CSV ──────────────────────────────────────────────────────────────────────

def monthly_report_csv(report: dict[str, Any]) -> str:
    """Monatsbericht als CSV: Kopf, Zusammenfassung, Tagestabelle."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")

    writer.writerow(["ConvoyPlan — Systembericht"])
    writer.writerow(["Monat", month_label(report.get("month", ""))])
    writer.writerow(["Zeitraum", f"{report.get('from', '')} bis {report.get('to', '')}"])
    writer.writerow(["Erstellt", report.get("generated_at", "")])
    writer.writerow(["Erfasste Tage", report.get("days_covered", 0)])
    writer.writerow([])

    writer.writerow(["Zusammenfassung"])
    summary = report.get("summary") or {}
    for key, label, kind in _SUMMARY_ROWS:
        writer.writerow([label, _fmt(summary.get(key), kind)])
    writer.writerow([])

    writer.writerow(["Tageswerte"])
    writer.writerow([label for _, label, _ in _DAY_COLUMNS])
    for day in report.get("days") or []:
        writer.writerow([_decimal(day.get(key), places) for key, _, places in _DAY_COLUMNS])

    return buffer.getvalue()


def series_csv(series: dict[str, Any]) -> str:
    """Rohe/aggregierte Verlaufsdaten als CSV (alle Felder der Punkte)."""
    points = series.get("points") or []
    buffer = io.StringIO()
    if not points:
        return "Zeitpunkt\r\n"
    # Union aller Schlüssel, "t" immer zuerst — die Punkte einer Auflösung sind
    # gleich aufgebaut, aggregierte tragen aber Zusatzspalten (…_max).
    keys = ["t"] + [k for k in points[0].keys() if k != "t"]
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(keys)
    for point in points:
        writer.writerow([_decimal(point.get(k), 2 if k != "t" else None) for k in keys])
    return buffer.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────────────

class _ReportPDF(FPDF):
    def __init__(self, title: str):
        super().__init__(orientation="L")  # Querformat — die Tagestabelle ist breit
        self._title = title
        self.add_font("DV", "", _FONT_REGULAR)
        self.add_font("DV", "B", _FONT_BOLD)
        self.set_auto_page_break(auto=True, margin=16)

    def header(self):
        self.set_font("DV", "B", 15)
        self.cell(0, 9, "SYSTEMBERICHT", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("DV", "", 10)
        self.cell(0, 5, self._title, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*_ACCENT)
        self.set_line_width(0.8)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(5)

    def footer(self):
        self.set_y(-12)
        self.set_font("DV", "", 7)
        self.set_text_color(120, 120, 120)
        self.cell(
            0,
            5,
            f"Erstellt mit ConvoyPlan  |  {datetime.now().strftime('%d.%m.%Y %H:%M')} Uhr  |  Seite {self.page_no()}",
            align="C",
        )
        self.set_text_color(0, 0, 0)


def _section(pdf: _ReportPDF, title: str) -> None:
    pdf.ln(2)
    pdf.set_fill_color(*_ACCENT)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DV", "B", 10)
    pdf.cell(0, 7, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


def monthly_report_pdf(report: dict[str, Any]) -> bytes:
    """Monatsbericht als PDF (Querformat: Kennzahlen + Tagestabelle)."""
    summary = report.get("summary") or {}
    days = report.get("days") or []

    pdf = _ReportPDF(month_label(report.get("month", "")))
    pdf.add_page()

    _section(pdf, "Zusammenfassung")
    # Zwei Spalten Kennzahlen nebeneinander — spart Seiten und liest sich besser.
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    col_w = usable / 2
    label_w, value_w = col_w * 0.62, col_w * 0.38
    pdf.set_font("DV", "", 9)
    for index in range(0, len(_SUMMARY_ROWS), 2):
        for key, label, kind in _SUMMARY_ROWS[index:index + 2]:
            pdf.set_font("DV", "", 9)
            pdf.cell(label_w, 5.5, label, border="B")
            pdf.set_font("DV", "B", 9)
            pdf.cell(value_w, 5.5, _fmt(summary.get(key), kind), border="B", align="R")
        pdf.ln()

    pdf.ln(3)
    _section(pdf, "Tageswerte")
    if not days:
        pdf.set_font("DV", "", 9)
        pdf.cell(0, 6, "Für diesen Monat liegen keine verdichteten Tageswerte vor.",
                 new_x="LMARGIN", new_y="NEXT")
    else:
        # Erste Spalte (Datum) breiter, der Rest gleichmäßig verteilt.
        first_w = 22.0
        rest_w = (usable - first_w) / (len(_DAY_COLUMNS) - 1)
        widths = [first_w] + [rest_w] * (len(_DAY_COLUMNS) - 1)

        def _head() -> None:
            pdf.set_font("DV", "B", 6.5)
            pdf.set_fill_color(220, 225, 235)
            for width, (_, label, _places) in zip(widths, _DAY_COLUMNS):
                pdf.cell(width, 6, label, border=1, fill=True, align="C")
            pdf.ln()

        _head()
        pdf.set_font("DV", "", 6.5)
        for row_index, day in enumerate(days):
            if pdf.get_y() > pdf.h - 24:
                pdf.add_page()
                _head()
                pdf.set_font("DV", "", 6.5)
            pdf.set_fill_color(248, 249, 252)
            fill = row_index % 2 == 1
            for width, (key, _label, places) in zip(widths, _DAY_COLUMNS):
                value = day.get(key)
                text = str(value) if key == "t" else (_decimal(value, places) or "-")
                pdf.cell(width, 5, text, border=1, align="C", fill=fill)
            pdf.ln()

    return bytes(pdf.output())
