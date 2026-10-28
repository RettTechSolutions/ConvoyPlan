"""Landmarks (LM) und das Custom Model je Anfrage.

GraphHopper rechnet seit 2026-10 Landmarks für ``car`` (graphhopper/entrypoint.sh),
weil eine Route Bayern–Albanien ohne jede Beschleunigung an der Frist des
Backends abbrach. LM schätzt die Restkosten mit der Gewichtung, mit der die
Landmarks gerechnet wurden (``car.json``). Das ist nur dann eine untere Schranke,
wenn das Custom Model der Anfrage Gewichte **nicht senkt** — sonst findet die
Suche still eine falsche, nicht nur eine langsamere Route. Die Zusagen:

- jede Regel, die das Backend schickt, erhöht Gewichte oder lässt sie: Priority
  höchstens 1, Geschwindigkeit nur über ``limit_to``, ``distance_influence`` nicht
  unter dem von ``car.json``;
- „kürzeste" fragt ohne LM: gegen ein Gewicht, in dem die Strecke dominiert,
  wurde die Suche mit LM langsamer (gemessen auf Österreich).
"""
import itertools

import pytest

from app.services import routing

PUNKTE = [{"lat": 47.50, "lon": 9.75}, {"lat": 48.21, "lon": 16.37}]
# distance_influence aus GraphHoppers car.json (custom_models im JAR, 10.2) —
# der Wert, mit dem die Landmarks gerechnet sind.
CAR_JSON_DISTANCE_INFLUENCE = 90

FAHRZEUGE = [
    None,
    {"max_height_m": 3.8},
    {"max_height_m": 3.8, "max_weight_t": 18.0, "max_axle_load_t": 11.5},
]
PRAEFERENZEN = list(routing._PRIORITY_RULES)


def _anfragen():
    for pref, fz, gewicht, faehre in itertools.product(PRAEFERENZEN, FAHRZEUGE, (True, False), (True, False)):
        yield pref, routing._payload(PUNKTE, fz, pref, gewicht, faehre)


@pytest.mark.parametrize(("pref", "anfrage"), list(_anfragen()))
def test_das_custom_model_senkt_kein_gewicht(pref, anfrage):
    modell = anfrage.get("custom_model", {})
    for regel in modell.get("priority", []):
        assert set(regel) <= {"if", "else_if", "else", "multiply_by"}, regel
        assert 0 <= float(regel["multiply_by"]) <= 1, regel
    for regel in modell.get("speed", []):
        assert "multiply_by" not in regel or float(regel["multiply_by"]) <= 1, regel
    if "distance_influence" in modell:
        assert modell["distance_influence"] >= CAR_JSON_DISTANCE_INFLUENCE


@pytest.mark.parametrize("fz", FAHRZEUGE)
def test_kuerzeste_fragt_ohne_landmarks(fz):
    assert routing._payload(PUNKTE, fz, "kuerzeste", True, True)["lm.disable"] is True


@pytest.mark.parametrize("pref", ["schnell", "standard"])
@pytest.mark.parametrize("fz", FAHRZEUGE)
def test_schnell_und_standard_nutzen_die_landmarks(pref, fz):
    assert "lm.disable" not in routing._payload(PUNKTE, fz, pref, True, True)
