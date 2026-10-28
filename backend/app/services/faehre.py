"""Fähren: Die Überfahrt ist Reisezeit, keine Lenkzeit.

Gemeldet: Auf einer Route München → Shkodër über Bari–Durrës lag ein
Technischer Halt mitten in der Adria, die Tagesruhe kurz vor dem Fährhafen und
eine Lenkpause kurz nach der Ankunft. Die Konvoi-Fahrzeit
(``routing.convoy_duration_s``) rechnete die gut 200 km über See wie Landstraße
mit dem Tempo außerorts, und die Halteempfehlung verteilte Halte linear über
die ganze Strecke.

GraphHopper kennt die Fähre: ``road_environment`` ist ``ferry``, und die Zeit
der Fährkanten kommt aus dem OSM-Tag ``duration`` der Fährlinie. Daraus
entstehen hier die Abschnitte (``abschnitte``) und eine ``Zeitachse``, die
Strecke, Lenkzeit und Reisezeit zueinander in Beziehung setzt:

- Auf See vergeht Reisezeit, aber keine Lenkzeit. Ein Halt, der in die
  Überfahrt fiele, liegt am Hafen davor (``meter_bei_lenkzeit``).
- Die Überfahrt selbst ist ein Halt: ab 45 min eine Lenkpause, ab 9 h eine
  Tagesruhe. 9 h ist die reduzierte Tagesruhezeit (VO (EG) 561/2006 Art. 4 g),
  und Art. 9 erlaubt, sie an Bord zu nehmen, wenn eine Schlafkabine da ist.
  Ohne Kabine gilt das nicht — das weiß die Planung nicht, die Besatzung schon;
  die Oberfläche sagt es deshalb dazu.

Passt die Zeit aus GraphHopper nicht zu einer Fähre (fehlt, oder schneller als
``PLAUSIBEL_KMH``), wird mit ``ERSATZ_KMH`` geschätzt und das vermerkt.
"""
from __future__ import annotations

from typing import Any, Iterable

from app.services.fuel import haversine_m

FERRY = "ferry"

ERSATZ_KMH = 25.0
PLAUSIBEL_KMH = (2.0, 60.0)

# Ab dieser Dauer zählt eine Überfahrt als Tagesruhe (reduzierte Tagesruhezeit).
TAGESRUHE_AB_MIN = 9 * 60


def _kumuliert(coords: list[list[float]]) -> list[float]:
    cum = [0.0]
    for i in range(len(coords) - 1):
        cum.append(cum[-1] + haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]))
    return cum


def _faehr_bereiche(env_details: Iterable) -> list[tuple[int, int]]:
    bereiche: list[tuple[int, int]] = []
    for von, bis, wert in sorted(env_details or [], key=lambda d: d[0]):
        if str(wert).lower() != FERRY or bis <= von:
            continue
        if bereiche and von <= bereiche[-1][1]:
            bereiche[-1] = (bereiche[-1][0], max(bis, bereiche[-1][1]))
        else:
            bereiche.append((von, bis))
    return bereiche


def abschnitte(env_details: Iterable, time_details: Iterable, coords: list[list[float]]) -> list[dict[str, Any]]:
    """Die Fährabschnitte einer Route, in Fahrtrichtung.

    *env_details* und *time_details* sind die Path-Details ``road_environment``
    und ``time`` aus GraphHopper (``[von_index, bis_index, wert]``, die Zeit in
    ms). Zurück je Abschnitt Lage, Länge und Dauer der Überfahrt.
    """
    if len(coords) < 2:
        return []
    cum = _kumuliert(coords)
    zeiten = list(time_details or [])
    out: list[dict[str, Any]] = []
    for von, bis in _faehr_bereiche(env_details):
        bis = min(bis, len(coords) - 1)
        von_m, bis_m = cum[von], cum[bis]
        laenge_m = bis_m - von_m
        ms = 0.0
        for t_von, t_bis, t_ms in zeiten:
            t_von_m, t_bis_m = cum[min(t_von, len(cum) - 1)], cum[min(t_bis, len(cum) - 1)]
            ueberlapp = min(bis_m, t_bis_m) - max(von_m, t_von_m)
            if ueberlapp > 0 and t_bis_m > t_von_m and t_ms:
                ms += float(t_ms) * ueberlapp / (t_bis_m - t_von_m)
        dauer_s = ms / 1000
        kmh = laenge_m / 1000 / (dauer_s / 3600) if dauer_s > 0 else 0.0
        geschaetzt = not (PLAUSIBEL_KMH[0] <= kmh <= PLAUSIBEL_KMH[1])
        if geschaetzt:
            dauer_s = laenge_m / 1000 / ERSATZ_KMH * 3600
        out.append({
            "km": round(von_m / 1000, 1),
            "von_m": round(von_m),
            "bis_m": round(bis_m),
            "laenge_km": round(laenge_m / 1000, 1),
            "dauer_s": int(round(dauer_s)),
            "lat": coords[von][1], "lon": coords[von][0],
            "ziel_lat": coords[bis][1], "ziel_lon": coords[bis][0],
            "geschaetzt": geschaetzt,
        })
    return out


def index_bereiche(env_details: Iterable) -> list[tuple[int, int]]:
    """Die Koordinaten-Indizes der Fährabschnitte — für ``convoy_duration_s``."""
    return _faehr_bereiche(env_details)


def dauer_gesamt_s(faehren: Iterable[dict] | None) -> int:
    return sum(int(f.get("dauer_s") or 0) for f in faehren or [])


def als_halt_min(faehre: dict) -> int:
    """Wie lang die Überfahrt für die Halteempfehlung zählt.

    Ab ``TAGESRUHE_AB_MIN`` als volle Tagesruhe — die Halteempfehlung kennt nur
    die 11 h, und eine 9-h-Überfahrt mit Kabine ist eine (reduzierte) Tagesruhe.
    """
    minuten = int(round((faehre.get("dauer_s") or 0) / 60))
    from app.services.fuel import DAILY_REST_MIN

    return DAILY_REST_MIN if minuten >= TAGESRUHE_AB_MIN else minuten


class Zeitachse:
    """Strecke, Lenkzeit und Reisezeit einer Route.

    An Land vergeht Lenkzeit gleichmäßig über die Strecke — wie bisher, nur
    ohne die Meter auf See. Auf einer Fähre vergeht Reisezeit, aber keine
    Lenkzeit. Ohne Fähren ist die Achse die alte lineare Umrechnung.
    """

    def __init__(self, route_m: float, lenkzeit_s: float, faehren: Iterable[dict] | None = None):
        self.route_m = max(0.0, float(route_m))
        self.lenkzeit_s = max(0.0, float(lenkzeit_s))
        self.faehren = sorted(
            ({"von": float(f["von_m"]), "bis": float(f["bis_m"]), "dauer": float(f["dauer_s"])}
             for f in faehren or []),
            key=lambda f: f["von"],
        )
        land_m = self.route_m - sum(f["bis"] - f["von"] for f in self.faehren)
        self._s_je_m = self.lenkzeit_s / land_m if land_m > 0 else 0.0

    def lenkzeit(self, m: float) -> float:
        """Lenkzeit vom Start bis Meter *m*."""
        see = sum(max(0.0, min(m, f["bis"]) - f["von"]) for f in self.faehren)
        return max(0.0, m - see) * self._s_je_m

    def meter_bei_lenkzeit(self, s: float) -> float:
        """Wo man nach *s* Lenkzeit steht — an einer Fähre der Hafen davor."""
        if self._s_je_m <= 0:
            return 0.0
        pos, t = 0.0, 0.0
        for f in self.faehren:
            stueck = (f["von"] - pos) * self._s_je_m
            # Toleranz: genau am Anleger fällig heißt davor, nicht nach der Überfahrt.
            if t + stueck >= s - 1e-6:
                return pos + (s - t) / self._s_je_m
            t += stueck
            pos = f["bis"]
        return min(self.route_m, pos + (s - t) / self._s_je_m)

    def reisezeit(self, m: float) -> float:
        """Lenkzeit plus Überfahrten vom Start bis Meter *m*."""
        zeit = self.lenkzeit(m)
        for f in self.faehren:
            if m >= f["bis"]:
                zeit += f["dauer"]
            elif m > f["von"]:
                zeit += f["dauer"] * (m - f["von"]) / (f["bis"] - f["von"])
        return zeit

    def abschnittszeiten(self, kumuliert_m: Iterable[float]) -> list[int]:
        """Reisezeit je Teilstück Start → WP1 → WP2 …, für den Zeitplan."""
        out, vorher = [], 0.0
        for m in kumuliert_m:
            jetzt = self.reisezeit(m)
            out.append(max(0, round(jetzt - vorher)))
            vorher = jetzt
        return out
