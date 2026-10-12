"""Exporte mit Konvoinamen außerhalb von Latin-1.

Starlette kodiert Header als Latin-1. Ein Konvoi namens „DEMO – Übungsmarsch
Nord" (Gedankenstrich U+2013) ließ GPX, JSON, Marschbefehl und Roadbook mit
500 scheitern, bevor ein Byte ausgeliefert war.
"""
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.responses import PlainTextResponse, Response

from app.api.routes import routing

NAMEN = [
    "DEMO – Übungsmarsch Nord",
    "Hilfskonvoi 🚒 Ukraine",
    'Zug "Süd"/2\\a',
    "Übung Nord",
]


@pytest.mark.parametrize("name", NAMEN)
def test_der_header_laesst_sich_bauen(name):
    headers = routing._attachment(f"{name}.gpx")

    # Genau hier stand vorher der UnicodeEncodeError.
    PlainTextResponse("x", headers=headers)
    Response(b"x", headers=headers)


@pytest.mark.parametrize("name", NAMEN)
def test_der_echte_name_steht_in_filename_stern(name):
    wert = routing._attachment(f"{name}.gpx")["Content-Disposition"]

    ascii_teil, stern_teil = wert.split("; filename*=UTF-8''")
    assert ascii_teil.startswith('attachment; filename="')
    assert ascii_teil.endswith('.gpx"')
    assert ascii_teil.isascii()
    # Kein Anführungszeichen und kein Pfadtrenner aus dem Namen im Header.
    assert ascii_teil.count('"') == 2
    assert unquote(stern_teil) == routing._safe_filename(f"{name}.gpx")


def test_kein_export_baut_den_header_selbst():
    quelle = Path(routing.__file__).read_text(encoding="utf-8")

    # Nur _attachment schreibt Content-Disposition; ein fünfter Export, der den
    # Kopf wieder von Hand baut, bekommt den Fehler zurück.
    assert quelle.count('"Content-Disposition"') == 1
