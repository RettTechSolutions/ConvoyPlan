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
async def test_alle_werkzeuge_liefern_ein_ausgabeschema():
    """Ohne Schema liefert das SDK kein ``structuredContent``.

    Das ist die Grundlage der Oberflächen — sie lesen genau dieses Feld —
    und gleichzeitig das, was einem Modell die Felder benennt, statt es
    einen Textblock zerlegen zu lassen."""
    for tool in await _server().list_tools():
        assert tool.output_schema, f"{tool.name} hat kein Ausgabeschema"
