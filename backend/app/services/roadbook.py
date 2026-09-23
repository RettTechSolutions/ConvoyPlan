"""Roadbook: die Route zum Ausdrucken — Übersichtskarte und darunter jede
Navigationsanweisung, mit Kilometrierung und den Planzeiten an den Wegpunkten.

Die Anweisungen kommen aus der letzten Routenberechnung (``Route.instructions``,
Migration 0047) und nicht aus einer neuen Anfrage beim Druck: der Ausdruck muss
die Route beschreiben, die auf der Karte und im Zeitplan steht.

GraphHopper nennt einen erreichten Wegpunkt nur „Wegpunkt 2 erreicht". Welcher
das ist, weiß nur die Berechnung — sie kennt die Punkte, die sie geschickt hat.
``link_waypoints()`` hängt deshalb schon dort die ID an, und der Druck setzt
Name und Planzeiten ein. Die Tabellenzeilen entstehen in ``build_rows()``,
getrennt vom PDF, damit ``tests/test_roadbook.py`` sie ohne fpdf prüft.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any, Iterable

from fpdf.fonts import FontFace

from app.services.pdf import PURPOSE_LABELS, TYPE_LABELS, _PDF
from app.services.static_map import END_COLOR, START_COLOR, STOP_COLOR, WAYPOINT_COLOR, Marker

# GraphHopper-Instruction-Signs (com.graphhopper.util.Instruction).
SIGN_REACHED_VIA = 5
SIGN_FINISH = 4

# Pfeile aus DejaVu Sans — dieselbe Schrift wie der Rest des PDFs, deshalb ohne
# eigene Symbolschrift. Wo eine Richtung zwei Signs hat (leicht/halten), sagt der
# Text daneben den Unterschied.
_SYMBOLS: dict[int, str] = {
    -98: "↶",  # Wenden
    -8: "↶",   # Wenden links
    -7: "↖",   # links halten
    -6: "↺",   # Kreisverkehr verlassen (Rechtsverkehr: gegen den Uhrzeigersinn)
    -3: "↙",   # scharf links
    -2: "←",   # links
    -1: "↖",   # leicht links
    0: "↑",    # geradeaus
    1: "↗",    # leicht rechts
    2: "→",    # rechts
    3: "↘",    # scharf rechts
    SIGN_FINISH: "⚑",
    SIGN_REACHED_VIA: "◉",
    6: "↺",    # Kreisverkehr
    7: "↗",    # rechts halten
    8: "↷",    # Wenden rechts
}


def symbol(sign: int) -> str:
    return _SYMBOLS.get(sign, "•")


def link_waypoints(
    instructions: list[dict[str, Any]], waypoint_ids: list[str]
) -> list[dict[str, Any]]:
    """Attach the waypoint id to each "reached via" instruction, in order.

    ``waypoint_ids`` ist die Folge der Zwischenpunkte, wie sie an GraphHopper
    ging. GraphHopper liefert genau eine REACHED_VIA-Anweisung je Zwischenpunkt,
    in derselben Folge.
    """
    ids = iter(waypoint_ids)
    out = []
    for ins in instructions:
        entry = dict(ins)
        if entry.get("sign") == SIGN_REACHED_VIA:
            wp_id = next(ids, None)
            if wp_id is not None:
                entry["waypoint_id"] = wp_id
        out.append(entry)
    return out


@dataclass(frozen=True)
class Row:
    nr: int
    symbol: str
    text: str
    # Kilometrierung, an der das Manöver stattfindet.
    km_at: float
    # Strecke bis zur nächsten Anweisung (0 am Ziel).
    distance_m: float
    kind: str  # "turn" | "waypoint" | "finish"
    detail: str = ""


def fmt_km(km: float) -> str:
    return f"{km:.1f}".replace(".", ",")


def fmt_distance(m: float) -> str:
    if m <= 0:
        return ""
    if m < 1000:
        # Auf 10 m gerundet: genauer liest man keinen Tacho.
        return f"{max(10, round(m / 10) * 10)} m"
    return f"{fmt_km(m / 1000)} km"


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "-"
    h, rest = divmod(int(seconds), 3600)
    return f"{h}:{rest // 60:02d} h"


def _hhmm(dt: datetime | None) -> str | None:
    return dt.strftime("%H:%M") if dt else None


def _waypoint_detail(wp: Any) -> str:
    parts = [TYPE_LABELS.get(wp.type, wp.type or "Wegpunkt")]
    arrival, departure = _hhmm(wp.planned_arrival), _hhmm(wp.planned_departure)
    if arrival:
        parts.append(f"an {arrival}")
    if departure and departure != arrival:
        parts.append(f"ab {departure}")
    if wp.hold_duration_min:
        hold = f"{wp.hold_duration_min} min Halt"
        purpose = PURPOSE_LABELS.get(getattr(wp, "halt_purpose", None) or "")
        parts.append(f"{hold} ({purpose})" if purpose else hold)
    if wp.notes:
        parts.append(wp.notes)
    return " · ".join(parts)


def build_rows(
    instructions: Iterable[dict[str, Any]],
    located: list[Any],
    planned_arrival: datetime | None = None,
) -> list[Row]:
    """Turn stored instructions into printable rows.

    ``located`` sind die Wegpunkte mit Lage, in der Reihenfolge der Liste. Ihre
    Position (ab 1) ist die Nummer im Text — dieselbe trägt ihr Marker auf der
    Karte (``map_markers()``).
    """
    numbers = {str(wp.id): n for n, wp in enumerate(located, start=1)}
    by_id = {str(wp.id): wp for wp in located}

    rows: list[Row] = []
    km = 0.0
    for i, ins in enumerate(instructions, start=1):
        sign = int(ins.get("sign", 0))
        dist = float(ins.get("distance_m") or 0.0)
        text = ins.get("text") or ""
        kind, detail = "turn", ""
        if sign == SIGN_REACHED_VIA:
            kind = "waypoint"
            wp = by_id.get(str(ins.get("waypoint_id")))
            if wp is not None:
                text = f"Wegpunkt {numbers[str(wp.id)]}: {wp.name}"
                detail = _waypoint_detail(wp)
        elif sign == SIGN_FINISH:
            kind = "finish"
            text = "Ziel erreicht"
            if (arrival := _hhmm(planned_arrival)) is not None:
                detail = f"an {arrival}"
        elif ref := ins.get("street_ref"):
            # Die Straßennummer (B 27, A 8) steht auf dem Schild — der Text von
            # GraphHopper nennt oft nur den Namen.
            if ref not in text:
                text = f"{text} ({ref})"
        if dest := ins.get("street_destination"):
            detail = f"Richtung {dest}" if not detail else f"{detail} · Richtung {dest}"
        rows.append(Row(i, symbol(sign), text, km / 1000, dist, kind, detail))
        km += dist
    return rows


_STOP_TYPES = {"stop", "technical_stop"}


def map_markers(
    start: tuple[float, float],
    end: tuple[float, float],
    located: list[tuple[Any, tuple[float, float]]],
) -> list[Marker]:
    """Start „S", Ziel „Z" und die Wegpunkte mit ihrer Nummer aus ``build_rows()``.

    Punkte als ``(lat, lon)``; Halte sind orange, damit man sie auf der Karte
    von bloßen Durchlaufpunkten unterscheidet.
    """
    markers = [
        Marker(lon, lat, str(n), STOP_COLOR if wp.type in _STOP_TYPES else WAYPOINT_COLOR)
        for n, (wp, (lat, lon)) in enumerate(located, start=1)
    ]
    # Start und Ziel zuletzt: sie liegen oben, wenn ein Wegpunkt daneben steht.
    markers.append(Marker(start[1], start[0], "S", START_COLOR))
    markers.append(Marker(end[1], end[0], "Z", END_COLOR))
    return markers


# ── PDF ──────────────────────────────────────────────────────────────────────


class _RoadbookPDF(_PDF):
    def header(self):
        self.set_font("DV", "B", 16)
        self.cell(0, 9, "ROADBOOK", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(26, 39, 68)
        self.set_line_width(0.8)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)


def _kv_pair(pdf: _PDF, label: str, value: str, w: float) -> None:
    pdf.set_font("DV", "B", 9)
    pdf.cell(28, 5, label)
    pdf.set_font("DV", "", 9)
    pdf.cell(w - 28, 5, value)


def generate_roadbook(
    convoy: Any,
    route: Any,
    located: list[Any],
    map_jpeg: bytes | None,
    planned_departure: datetime | None = None,
    planned_arrival: datetime | None = None,
) -> bytes:
    pdf = _RoadbookPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    content_w = pdf.w - pdf.l_margin - pdf.r_margin
    half = content_w / 2

    pdf.set_font("DV", "B", 11)
    pdf.cell(0, 6, convoy.name, new_x="LMARGIN", new_y="NEXT")
    if convoy.organization:
        pdf.set_font("DV", "", 9)
        pdf.cell(0, 5, convoy.organization, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    dist = f"{fmt_km((route.distance_m or 0) / 1000)} km" if route.distance_m else "-"
    _kv_pair(pdf, "Strecke:", dist, half)
    _kv_pair(pdf, "Fahrzeit:", fmt_duration(route.duration_s), half)
    pdf.ln()
    _kv_pair(pdf, "Abmarsch:", planned_departure.strftime("%d.%m.%Y %H:%M") if planned_departure else "-", half)
    _kv_pair(pdf, "Ankunft:", planned_arrival.strftime("%d.%m.%Y %H:%M") if planned_arrival else "-", half)
    pdf.ln(7)

    if map_jpeg:
        map_h = content_w * 1050 / 1600
        pdf.image(BytesIO(map_jpeg), x=pdf.l_margin, w=content_w, h=map_h)
        pdf.ln(3)

    instructions = route.instructions
    if not instructions:
        pdf.set_font("DV", "B", 10)
        pdf.set_fill_color(254, 243, 199)
        pdf.multi_cell(
            0, 6,
            "Für diese Route liegen keine Navigationsanweisungen vor. Sie entstehen "
            "bei der Routenberechnung — bitte die Route in ConvoyPlan neu berechnen. "
            "Eine importierte Route (GPX/GeoJSON) hat keine Anweisungen.",
            fill=True, border=1,
        )
        return bytes(pdf.output())

    rows = build_rows(instructions, located, planned_arrival)

    pdf.set_font("DV", "", 9)
    heading = FontFace(emphasis="BOLD", fill_color=(220, 225, 235))
    waypoint_style = FontFace(emphasis="BOLD", fill_color=(254, 243, 199))
    finish_style = FontFace(emphasis="BOLD", fill_color=(220, 252, 231))
    with pdf.table(
        col_widths=(9, 9, content_w - 9 - 9 - 17 - 19, 17, 19),
        headings_style=heading,
        line_height=4.6,
        text_align=("RIGHT", "CENTER", "LEFT", "RIGHT", "RIGHT"),
        v_align="MIDDLE",
        repeat_headings=1,
        padding=(1.2, 1.5),
    ) as table:
        table.row(["Nr.", "", "Anweisung", "bei km", "dann"])
        for r in rows:
            style = {"waypoint": waypoint_style, "finish": finish_style}.get(r.kind)
            row = table.row(style=style)
            row.cell(str(r.nr))
            row.cell(r.symbol, style=FontFace(size_pt=12, emphasis=style.emphasis if style else None,
                                                fill_color=style.fill_color if style else None))
            row.cell(f"{r.text}\n{r.detail}" if r.detail else r.text)
            row.cell(fmt_km(r.km_at))
            row.cell(fmt_distance(r.distance_m))

    pdf.ln(2)
    pdf.set_font("DV", "", 7)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(
        0, 4,
        "Anweisungen aus der Routenberechnung (GraphHopper, OpenStreetMap). Vor Ort gilt die "
        "Beschilderung. „bei km“: Kilometrierung ab Start; „dann“: Strecke bis zur nächsten Anweisung.",
    )
    pdf.set_text_color(0, 0, 0)
    return bytes(pdf.output())

