"""Die Oberflächen, die ein Client zu einem Werkzeugergebnis anzeigen kann.

Anders als der Rest der MCP-Tests kommt das hier ohne Datenbank aus: geprüft
wird die Registrierung, nicht der Zugriff. Die Widgets tragen keine Daten in
sich, sie bekommen sie erst beim Aufruf — und der geht durch dieselben
Prüfungen wie jeder andere.

Zwei Zusagen stehen hier im Mittelpunkt, weil beide still brechen würden:
ein Verweis auf eine Oberfläche, die es nicht gibt (der Client zeigt dann
nichts und sagt nicht warum), und ein Nachladen von außen (das fiele
niemandem auf, es säße nur plötzlich ein Dritter in der Sichtlinie).
"""
import re

import pytest
from mcp.server import MCPServer

from app.mcp import tools_read, tools_write, widgets


def _server() -> MCPServer:
    server = MCPServer(name="convoyplan-widget-tests")
    tools_read.register(server)
    tools_write.register(server)
    widgets.register(server)
    return server


@pytest.mark.asyncio
async def test_jedes_werkzeug_verweist_auf_eine_oberflaeche_die_es_gibt():
    """Der Verweis und die Resource sind zwei Stellen derselben Wahrheit.

    Läuft eine URI auseinander, gibt es keine Fehlermeldung — der Client
    zeigt einfach nichts an."""
    server = _server()
    vorhanden = {str(r.uri) for r in await server.list_resources()}

    verweise = 0
    for tool in await server.list_tools():
        if not tool.meta or "openai/outputTemplate" not in tool.meta:
            continue
        verweise += 1
        ziel = tool.meta["openai/outputTemplate"]
        assert ziel in vorhanden, f"{tool.name} zeigt auf {ziel}, das es nicht gibt"
        # Beide Schreibweisen müssen dasselbe meinen: die der MCP-Apps-Spec
        # und die von ChatGPT gelesene.
        assert tool.meta["ui"]["resourceUri"] == ziel

    assert verweise == len(widgets._WIDGETS)


@pytest.mark.asyncio
async def test_oberflaechen_tragen_den_medientyp_der_spezifikation():
    """Ohne den Typ hält ein Client die Resource für eine Datei zum Anzeigen."""
    server = _server()
    ui = [r for r in await server.list_resources() if str(r.uri).startswith("ui://")]
    assert ui, "keine Oberflächen registriert"
    for resource in ui:
        assert resource.mime_type == "text/html;profile=mcp-app"


@pytest.mark.asyncio
async def test_keine_oberflaeche_laedt_etwas_von_aussen_nach():
    """Die Zusage aus ``app/mcp/widgets.py``, als Test.

    Das Fenster spannt ein fremder Client auf, die Daten darin gehören einer
    BOS-Organisation. Ein Skript, ein Zeichensatz oder ein Bild von einer
    fremden Adresse säße als dritte Partei in genau dieser Sichtlinie — und
    das fiele beim Lesen des Diffs leichter auf als im Betrieb."""
    for uri in widgets._WIDGETS:
        html = widgets.html_fuer(uri)
        for verdaechtig in ("http://", "https://", "//cdn", "@import"):
            assert verdaechtig not in html, f"{uri} lädt {verdaechtig} nach"


@pytest.mark.asyncio
async def test_jede_oberflaeche_bringt_ihre_zeichenfunktion_mit():
    """Rahmen und Widget werden zusammengesetzt; fehlt eines von beidem,
    bleibt die Fläche leer, ohne dass irgendwo etwas fehlschlägt."""
    for uri in widgets._WIDGETS:
        html = widgets.html_fuer(uri)
        # Der Rahmen ruft sie auf, das Widget setzt sie.
        assert html.count("CONVOYPLAN_ZEICHNEN") >= 2
        assert "openai:set_globals" in html
        # Der Platzhalter muss ersetzt sein und nicht bloß danebenstehen.
        assert "/* __WIDGET__ */" not in html


@pytest.mark.asyncio
async def test_die_zeichenfunktion_steht_bevor_der_rahmen_sie_ruft():
    """Der Rahmen zeichnet sofort, nicht erst auf Zuruf.

    ChatGPT setzt die Globals, bevor das Dokument läuft; der erste Aufruf
    von ``neu()`` ist dann schon der echte. Steht das Widget im HTML
    dahinter, gibt es die Zeichenfunktion zu diesem Zeitpunkt noch nicht —
    und weil der Rahmen den Fehler auffängt, sieht man davon nur eine
    Fläche mit einer Entschuldigung."""
    for uri in widgets._WIDGETS:
        html = widgets.html_fuer(uri)
        assert html.index("CONVOYPLAN_ZEICHNEN =") < html.index("neu();"), uri


# Aufrufe wie ``if (`` oder ``Object.keys(`` sind keine eigenen Funktionen.
_JS_EINGEBAUT = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof",
    "Object", "String", "Number", "Boolean", "Array", "Date", "Math", "JSON",
    "isNaN", "parseInt", "parseFloat",
}


def _aufgerufen(js: str) -> set[str]:
    """Namen, die im Widget als Funktion aufgerufen werden.

    Ohne führenden Punkt: ``f.map(…)`` gehört dem Objekt, ``kennzahl(…)``
    muss das Widget selbst mitbringen."""
    gefunden = re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", js)
    return set(gefunden) - _JS_EINGEBAUT


def _deklariert(js: str) -> set[str]:
    return set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", js)) | set(
        re.findall(r"var\s+([A-Za-z_$][\w$]*)\s*=\s*function", js)
    )


@pytest.mark.asyncio
async def test_jedes_widget_bringt_alles_mit_was_es_aufruft():
    """Ein Widget ist eine Datei, kein Nachbarschaftsverhältnis.

    Gegen den Fall, der einmal genau so passiert ist: Ein Widget ruft eine
    Hilfsfunktion auf, die nur im Nachbar-Widget steht. Beim Lesen des Diffs
    fällt das nicht auf, beim Bauen fällt es nicht auf, und im Betrieb bleibt
    die Fläche leer — der Rahmen fängt die Ausnahme ab.

    Was beide Widgets brauchen, gehört in den Rahmen und kommt über ``w``;
    dort steht es einmal und wird hier nicht verlangt."""
    for uri, (datei, _n, _b) in widgets._WIDGETS.items():
        js = (widgets._ORDNER / datei).read_text(encoding="utf-8")
        fehlend = _aufgerufen(js) - _deklariert(js)
        assert not fehlend, f"{datei} ruft {sorted(fehlend)} auf, ohne es zu kennen"


@pytest.mark.asyncio
async def test_alle_werkzeuge_liefern_ein_ausgabeschema():
    """Ohne Schema liefert das SDK kein ``structuredContent``.

    Das ist die Grundlage der Oberflächen — sie lesen genau dieses Feld —
    und gleichzeitig das, was einem Modell die Felder benennt, statt es
    einen Textblock zerlegen zu lassen."""
    for tool in await _server().list_tools():
        assert tool.output_schema, f"{tool.name} hat kein Ausgabeschema"


# ── Verhaltenszusagen an den Werkzeugen ──────────────────────────────────
#
# Die Annotationen sind unverbindlich — ein Client darf ihnen nicht vertrauen,
# wo es um Rechte geht. Sie sind trotzdem eine Zusage, und eine, die still
# falsch werden kann: Wer ein Werkzeug von lesend auf schreibend umbaut und
# die Annotation stehen lässt, erzählt jedem Client das Gegenteil.


@pytest.mark.asyncio
async def test_jedes_werkzeug_sagt_wie_es_sich_verhaelt():
    for tool in await _server().list_tools():
        assert tool.annotations is not None, f"{tool.name} ohne Annotation"
        assert tool.annotations.title, f"{tool.name} ohne sprechenden Titel"


@pytest.mark.asyncio
async def test_kein_werkzeug_gibt_sich_als_zerstoerend_aus():
    """Die Positivliste in anderer Form.

    Es gibt kein Werkzeug, das einen Konvoi, ein Fahrzeug, einen Wegpunkt oder
    eine Route löscht. Stünde hier eines mit ``destructive_hint``, wäre
    entweder die Annotation falsch oder die Zusage gebrochen — beides gehört
    gesehen."""
    for tool in await _server().list_tools():
        assert tool.annotations.destructive_hint is not True, tool.name


@pytest.mark.asyncio
async def test_lesend_und_schreibend_stimmen_mit_der_positivliste_ueberein():
    """Zwei Quellen derselben Wahrheit, gegeneinander gehalten: die Liste der
    schreibenden Werkzeuge und das, was jedes Werkzeug über sich sagt."""
    from app.mcp import WRITE_TOOLS

    for tool in await _server().list_tools():
        erwartet = tool.name not in WRITE_TOOLS
        assert tool.annotations.read_only_hint is erwartet, (
            f"{tool.name}: read_only_hint={tool.annotations.read_only_hint}, "
            f"steht {'nicht ' if erwartet else ''}in WRITE_TOOLS"
        )
