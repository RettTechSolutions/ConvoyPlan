"""MCP-Resources und Prompt-Vorlagen des ConvoyPlan-Servers.

Resources liefern das, was ohnehin schon exportierbar ist: den Marschbefehl
als PDF, die Route als GPX, den Konvoi als JSON. Erzeugt werden sie über
**dieselben Funktionen wie die REST-Exporte** — der Marschbefehl ist ein
amtliches Format, und zwei Erzeuger davon wären zwei Formate.

Die Zugriffsprüfung ist dieselbe wie bei den Werkzeugen: ``mcp_context()``
löst Benutzer, Organisation und Rolle auf, ``_load_convoy`` schränkt auf die
eigene Organisation ein. Eine Resource ist kein Nebeneingang.
"""
import base64
import logging

from fastapi import HTTPException

from app.api.routes import routing as routing_routes
from app.mcp import areas
from app.mcp.context import mcp_context, translate
from app.mcp.scopes import SCOPE_READ
from app.mcp.tools_read import _load_convoy

logger = logging.getLogger(__name__)


async def _export(konvoi_id: str, fn, bereich: str) -> tuple[bytes, str]:
    """Einen Export über die vorhandene Route erzeugen.

    Gibt (Inhalt, Konvoiname) zurück. Die Route liefert eine
    Starlette-Response; gebraucht wird nur ihr Rumpf.

    ``bereich`` ist der Bereich, den die Organisation dafür freigegeben haben
    muss. Er steht hier und nicht in der Resource-Funktion, damit keine
    Resource ihn vergessen kann: ohne die Angabe lässt sich der Export nicht
    aufrufen."""
    async with mcp_context() as ctx:
        ctx.require(SCOPE_READ)
        ctx.require_bereich(bereich)
        convoy = await _load_convoy(ctx, konvoi_id)
        try:
            response = await fn(
                convoy_id=convoy.id, db=ctx.db, current_user=ctx.user
            )
        except HTTPException as exc:
            raise translate(exc) from exc
        return response.body, convoy.name


def register(mcp) -> None:
    """Resources und Prompts am Server anmelden."""

    @mcp.resource(
        "convoyplan://konvoi/{konvoi_id}/marschbefehl.pdf",
        name="Marschbefehl (PDF)",
        description=(
            "Der vollständige Marschbefehl eines Konvois im amtlichen "
            "Sieben-Abschnitte-Format, als PDF — dasselbe Dokument, das das "
            "Portal ausgibt."
        ),
        mime_type="application/pdf",
    )
    async def marschbefehl_pdf(konvoi_id: str) -> str:
        content, _name = await _export(konvoi_id, routing_routes.export_pdf, areas.BEREICH_KONVOIS)
        # Binär, also Base64 — so verlangt es das Protokoll für blob-Inhalte.
        return base64.b64encode(content).decode()

    @mcp.resource(
        "convoyplan://konvoi/{konvoi_id}/route.gpx",
        name="Route (GPX)",
        description=(
            "Die berechnete Route eines Konvois als GPX, mit den Wegpunkten. "
            "Setzt voraus, dass die Route bereits berechnet wurde."
        ),
        mime_type="application/gpx+xml",
    )
    async def route_gpx(konvoi_id: str) -> str:
        content, _name = await _export(konvoi_id, routing_routes.export_gpx, areas.BEREICH_ROUTEN)
        return content.decode()

    @mcp.resource(
        "convoyplan://konvoi/{konvoi_id}/konvoi.json",
        name="Konvoi (JSON)",
        description=(
            "Konvoi, Wegpunkte und Fahrzeuge als JSON-Export — der "
            "vollständige Datensatz zum Weiterverarbeiten."
        ),
        mime_type="application/json",
    )
    async def konvoi_json(konvoi_id: str) -> str:
        content, _name = await _export(konvoi_id, routing_routes.export_json, areas.BEREICH_KONVOIS)
        return content.decode()

    @mcp.prompt(
        name="marschbefehl_erstellen",
        title="Marschbefehl erstellen",
        description=(
            "Führt Schritt für Schritt durch das Ausfüllen eines "
            "Marschbefehls für einen bestehenden Konvoi."
        ),
    )
    def marschbefehl_erstellen(konvoi_id: str) -> str:
        """Eine Vorlage, die die sieben Abschnitte in der richtigen
        Reihenfolge abarbeitet.

        Args:
            konvoi_id: Die ID des Konvois, für den der Marschbefehl entsteht.
        """
        return (
            f"Erstelle den Marschbefehl für den Konvoi {konvoi_id}.\n\n"
            "Gehe so vor:\n"
            f"1. Rufe `konvoi_details` für {konvoi_id} auf und sieh nach, "
            "welche der sieben Abschnitte schon gefüllt sind.\n"
            "2. Rufe `wegpunkte_auflisten` und `route_abrufen` auf, um "
            "Marschweg und Zeiten zu kennen.\n"
            "3. Frage gezielt nur nach dem, was fehlt — nicht nach allem.\n"
            "4. Trage das Ergebnis mit `konvoi_aktualisieren` ein.\n\n"
            "Wichtig: Lage und Auftrag sind Führungsaussagen. Formuliere sie "
            "nicht selbst, sondern übernimm, was die Einsatzleitung vorgibt, "
            "und frage nach, wenn es fehlt. Erfinde keine Zeiten, "
            "Funkgruppen oder Ablaufpunkte — ein Marschbefehl mit "
            "plausibel klingenden, aber ausgedachten Angaben ist gefährlicher "
            "als einer mit sichtbaren Lücken."
        )
