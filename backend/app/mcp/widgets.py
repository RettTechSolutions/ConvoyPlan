"""Die Widgets des MCP-Servers — Oberflächen für Clients, die welche zeigen.

ChatGPT kann zu einem Werkzeugergebnis eine eigene Oberfläche einblenden
statt nur Text (Apps SDK). Ein Werkzeug verweist dafür in seinem ``_meta``
auf eine Resource, die HTML liefert; der Client lädt sie in ein eigenes
Fenster und reicht ihr die Antwort des Werkzeugs hinein.

Drei Entscheidungen, die den Zuschnitt erklären:

**Der MCP-Server bleibt ohne Widgets vollständig.** Sie hängen an ``_meta``
und an einer zusätzlichen Resource — ein Client, der beides nicht kennt,
bekommt unverändert dieselbe Antwort wie bisher. Es gibt kein Werkzeug, das
ohne Oberfläche nicht ginge, und keines, dessen Ergebnis nur im Widget
steht.

**Nichts wird nachgeladen.** Kein Skript, kein Zeichensatz, kein Bild von
einer fremden Adresse. Das Fenster spannt ChatGPT auf, und die Daten darin
gehören einer BOS-Organisation; was hier nachgeladen würde, säße als dritte
Partei in genau dieser Sichtlinie. Deshalb auch kein Bauschritt und kein
Framework: die Widgets sind Handarbeit in einer Datei.

**Der Rahmen ist geteilt, die Widgets sind es nicht.** Das Auspacken der
Antwort und das Maskieren fremder Texte stehen in ``widgets/rahmen.html``
und damit genau einmal da. Beides ist die Stelle, an der ein Fehler nicht
auffällt, sondern nur eine leere Fläche oder eine Lücke hinterlässt.

Die Versionsnummer in der URI ist der Zwischenspeicher-Schlüssel des
Clients: Wer ein Widget unverträglich ändert, zählt sie hoch. Wer nur einen
Text ändert, lässt sie stehen.
"""
import functools
import pathlib

# Der Medientyp der MCP-Apps-Spezifikation. ChatGPT erkennt daran, dass die
# Resource eine Oberfläche ist und keine Datei zum Anzeigen.
WIDGET_MIME = "text/html;profile=mcp-app"

_ORDNER = pathlib.Path(__file__).parent / "widgets"

# Die Resource-URIs. ``ui://`` ist das Schema der Spezifikation für
# Oberflächen; es zeigt nirgendwohin, der Client löst es über die Resource
# auf, nicht über das Netz.
URI_KONVOI_LISTE = "ui://convoyplan/konvoi-liste/v1.html"
URI_KONVOI_UEBERSICHT = "ui://convoyplan/konvoi-uebersicht/v1.html"
URI_KONVOI_STATUS = "ui://convoyplan/konvoi-status/v1.html"

# Welches Widget aus welcher Datei entsteht, und wie es heißt.
_WIDGETS: dict[str, tuple[str, str, str]] = {
    URI_KONVOI_LISTE: (
        "konvoi_liste.js",
        "Konvoi-Liste",
        "Die Konvois der Organisation mit Abmarschzeit, Umfang und Status.",
    ),
    URI_KONVOI_UEBERSICHT: (
        "konvoi_uebersicht.js",
        "Konvoi-Übersicht",
        "Ein Konvoi mit Marschbefehl und den Fahrzeugen in Marschordnung.",
    ),
    URI_KONVOI_STATUS: (
        "konvoi_status.js",
        "Marschstatus",
        "Der Status je Fahrzeug und zusammengefasst; was klemmt, steht oben.",
    ),
}


@functools.lru_cache(maxsize=None)
def html_fuer(uri: str) -> str:
    """Das fertige HTML eines Widgets.

    Zwischengespeichert, weil die Dateien sich zur Laufzeit nicht ändern —
    ein Widget wird bei jeder Sitzung eines jeden Clients abgerufen."""
    datei, _name, _beschreibung = _WIDGETS[uri]
    rahmen = (_ORDNER / "rahmen.html").read_text(encoding="utf-8")
    widget = (_ORDNER / datei).read_text(encoding="utf-8")
    return rahmen.replace("/* __WIDGET__ */", widget)


def meta(uri: str, *, laeuft: str, fertig: str) -> dict:
    """Das ``_meta`` eines Werkzeugs, das dieses Widget anzeigt.

    Zwei Schreibweisen für dieselbe Angabe, beide absichtlich:
    ``ui.resourceUri`` ist die Form der MCP-Apps-Spezifikation,
    ``openai/outputTemplate`` die von ChatGPT gelesene. Ein Client, der nur
    eine davon kennt, findet seine — und keiner von beiden stört sich an der
    anderen.

    ``laeuft``/``fertig`` sind die Zeilen, die ChatGPT während und nach dem
    Aufruf zeigt. Ohne sie steht dort ein technischer Werkzeugname."""
    return {
        "ui": {"resourceUri": uri, "prefersBorder": True},
        "openai/outputTemplate": uri,
        "openai/toolInvocation/invoking": laeuft,
        "openai/toolInvocation/invoked": fertig,
    }


def register(mcp) -> None:
    """Die Widget-Resources am Server anmelden.

    Sie tragen **keine** Zugriffsprüfung, und das ist kein Versehen: Was hier
    ausgeliefert wird, ist eine leere Vorlage. Die Daten kommen erst aus dem
    Werkzeugaufruf, und der geht unverändert durch ``mcp_context()`` samt
    Scope- und Organisationsprüfung. In der Vorlage steht nichts, was nicht
    auch im Quelltext dieses Repositorys steht."""
    for uri, (_datei, name, beschreibung) in _WIDGETS.items():
        mcp.resource(
            uri,
            name=name,
            description=beschreibung,
            mime_type=WIDGET_MIME,
            meta={"ui": {"prefersBorder": True}},
        )(_ausliefern(uri))


def _ausliefern(uri: str):
    """Einen Handler für genau diese URI bauen.

    Eine Fabrik und kein Vorgabewert am Parameter: Das SDK liest die
    Signatur des Handlers und gleicht sie mit den Platzhaltern der URI ab.
    Ein zusätzlicher Parameter — auch ein belegter — gilt ihm als Platzhalter,
    den die URI nicht hat, und die Registrierung scheitert. Die Schließung
    trägt die URI, die Signatur bleibt leer."""

    async def _widget() -> str:
        return html_fuer(uri)

    return _widget
