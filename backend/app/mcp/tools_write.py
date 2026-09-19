"""Die schreibenden Werkzeuge des MCP-Servers.

**Kein Werkzeug löscht Daten.** Die einzige Ausnahme von der reinen
Anlegen-und-Ändern-Regel ist ``fahrzeug_aus_konvoi_entfernen``: der
``DELETE``-Pfad dahinter löst nur die Zuordnung, Fahrzeug und Konvoi bleiben
bestehen.

Diese Werkzeuge rufen **dieselben Funktionen auf, die auch hinter der
REST-API stehen** — nicht über HTTP, sondern direkt. Das ist die wichtigste
Entscheidung dieser Datei: die Schreiblogik existiert genau einmal. Würde sie
hier nachgebaut, liefen die beiden Kopien beim ersten Fehler auseinander, den
jemand nur an einer Stelle behebt — und in den Routen steckt Logik, die man
beim Nachbauen nicht errät (die lückenlose Marschposition, das Umsortieren
der Wegpunkte entlang der vorherigen Route).

Die Werkzeugschicht steuert bei, was die Route nicht wissen kann: Scope-
Prüfung, Kontingente, Audit-Eintrag mit Quelle ``mcp`` und eine Antwort, die
ein Modell lesen kann.
"""
import uuid
from typing import Any

from fastapi import HTTPException

from app.api.routes import convoys as convoy_routes
from app.api.routes import routing as routing_routes
from app.api.routes import tracking as tracking_routes
from app.api.routes import vehicles as vehicle_routes
from app.config import settings
from app.mcp import annotations
from app.mcp.context import McpContext, McpError, mcp_context, translate
from app.mcp.scopes import SCOPE_FLEET_STATUS, SCOPE_WRITE
from app.mcp.tools_read import _load_convoy, _vehicle
from app.schemas.convoy import (
    AddVehicleRequest,
    ConvoyCreate,
    ConvoyUpdate,
    ConvoyVehicleReorderItem,
)
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.schemas.waypoint import WaypointCreate, WaypointReorderItem, WaypointUpdate
from app.services import staerke as staerke_svc


def _uuid(raw: str, was: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (TypeError, ValueError):
        raise McpError(f"„{raw}“ ist keine gültige {was}.")


async def _run(coro):
    """Eine wiederverwendete Route ausführen und ihre Fehler übersetzen."""
    try:
        return await coro
    except HTTPException as exc:
        raise translate(exc) from exc


def _kurzfassung(convoy) -> dict:
    return {
        "id": str(convoy.id),
        "name": convoy.name,
        "status": convoy.status,
    }


async def _quittung(ctx: McpContext, konvoi_id: str, text: str) -> dict:
    """Eine Antwort, die sagt, was geschehen ist.

    Ein blosses ``{"status": "ok"}`` lässt ein Modell im Unklaren darüber, was
    es gerade angerichtet hat — und den Menschen im Gesprächsverlauf erst
    recht."""
    convoy = await _load_convoy(ctx, konvoi_id)
    return {"ergebnis": text, "konvoi": _kurzfassung(convoy)}


def register(mcp) -> None:
    """Die schreibenden Werkzeuge am Server anmelden."""

    # ── Konvois ──────────────────────────────────────────────────────────

    @mcp.tool(annotations=annotations.schreibend("Konvoi anlegen", idempotent=False))
    async def konvoi_anlegen(
        name: str,
        start_lat: float | None = None,
        start_lon: float | None = None,
        ziel_lat: float | None = None,
        ziel_lon: float | None = None,
        marschform: str | None = None,
        auftrag: str | None = None,
    ) -> dict[str, Any]:
        """Legt einen neuen Konvoi (Marschkolonne) in der Organisation an.

        Start- und Zielpunkt sind optional, werden aber für `route_berechnen`
        gebraucht. Weitere Felder des Marschbefehls lassen sich anschließend
        mit `konvoi_aktualisieren` ergänzen.

        Args:
            name: Bezeichnung des Konvois, z. B. „Marschverband Nord".
            start_lat: Breitengrad des Startpunkts.
            start_lon: Längengrad des Startpunkts.
            ziel_lat: Breitengrad des Zielpunkts.
            ziel_lon: Längengrad des Zielpunkts.
            marschform: geschlossener_verband | einzelgruppen | individuell.
            auftrag: Auftrag im Sinne des Marschbefehls.
        """
        async with mcp_context("konvoi_anlegen") as ctx:
            ctx.require(SCOPE_WRITE)
            payload: dict = {"name": name, "marschform": marschform, "auftrag": auftrag}
            if start_lat is not None and start_lon is not None:
                payload["start_point"] = {"lat": start_lat, "lon": start_lon}
            if ziel_lat is not None and ziel_lon is not None:
                payload["end_point"] = {"lat": ziel_lat, "lon": ziel_lon}
            data = ConvoyCreate(**{k: v for k, v in payload.items() if v is not None})

            result = await _run(
                convoy_routes.create_convoy(
                    data=data, request=None, ctx=ctx.org_ctx, db=ctx.db
                )
            )
            await ctx.audit(
                "konvoi_anlegen",
                target_type="convoy",
                target_id=str(result["id"]),
                detail={"name": name},
            )
            await ctx.db.commit()
            return {
                "ergebnis": f"Konvoi „{name}“ angelegt.",
                "konvoi": {"id": str(result["id"]), "name": result["name"]},
            }

    @mcp.tool(annotations=annotations.schreibend("Konvoi ändern", idempotent=True))
    async def konvoi_aktualisieren(
        konvoi_id: str,
        name: str | None = None,
        status: str | None = None,
        marschform: str | None = None,
        lage: str | None = None,
        auftrag: str | None = None,
        ablaufpunkt: str | None = None,
        versorgung: str | None = None,
        funkgruppe: str | None = None,
        anlagen: str | None = None,
        start_lat: float | None = None,
        start_lon: float | None = None,
        ziel_lat: float | None = None,
        ziel_lon: float | None = None,
    ) -> dict[str, Any]:
        """Ändert Stammdaten und Marschbefehl eines Konvois.

        Nur die angegebenen Felder werden geändert; alles andere bleibt, wie
        es ist.

        Args:
            konvoi_id: Die ID des Konvois.
            name: Neue Bezeichnung.
            status: planning | active | completed.
            marschform: geschlossener_verband | einzelgruppen | individuell.
            lage: Abschnitt „Lage" des Marschbefehls.
            auftrag: Abschnitt „Auftrag".
            ablaufpunkt: Ablaufpunkt der Kolonne.
            versorgung: Abschnitt „Versorgung".
            funkgruppe: Zugewiesene Funkgruppe.
            anlagen: Abschnitt „Anlagen".
            start_lat: Breitengrad des Startpunkts.
            start_lon: Längengrad des Startpunkts.
            ziel_lat: Breitengrad des Zielpunkts.
            ziel_lon: Längengrad des Zielpunkts.
        """
        async with mcp_context("konvoi_aktualisieren") as ctx:
            ctx.require(SCOPE_WRITE)
            felder = {
                "name": name, "status": status, "marschform": marschform,
                "lage": lage, "auftrag": auftrag, "ablaufpunkt": ablaufpunkt,
                "versorgung": versorgung, "funkgruppe": funkgruppe, "anlagen": anlagen,
            }
            payload = {k: v for k, v in felder.items() if v is not None}
            if start_lat is not None and start_lon is not None:
                payload["start_point"] = {"lat": start_lat, "lon": start_lon}
            if ziel_lat is not None and ziel_lon is not None:
                payload["end_point"] = {"lat": ziel_lat, "lon": ziel_lon}
            if not payload:
                raise McpError("Es wurde kein zu änderndes Feld angegeben.")

            await _run(
                convoy_routes.update_convoy(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    data=ConvoyUpdate(**payload),
                    request=None,
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "konvoi_aktualisieren",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"felder": sorted(payload)},
            )
            await ctx.db.commit()
            return await _quittung(
                ctx, konvoi_id, f"Geändert: {', '.join(sorted(payload))}."
            )

    # ── Fahrzeuge ────────────────────────────────────────────────────────

    @mcp.tool(annotations=annotations.schreibend("Fahrzeug anlegen", idempotent=False))
    async def fahrzeug_anlegen(
        name: str,
        funkrufname: str | None = None,
        kennzeichen: str | None = None,
        hoehe_cm: int | None = None,
        laenge_cm: int | None = None,
        gewicht_kg: int | None = None,
        antrieb: str = "combustion",
    ) -> dict[str, Any]:
        """Legt ein Fahrzeug im Bestand der Organisation an.

        Das Fahrzeug gehört danach der Organisation, ist aber noch keinem
        Konvoi zugeordnet — dafür `fahrzeug_zu_konvoi_hinzufuegen`.

        Args:
            name: Bezeichnung, z. B. „ELW 1".
            funkrufname: Funkrufname, z. B. „Florian München 1/11/1".
            kennzeichen: Amtliches Kennzeichen.
            hoehe_cm: Fahrzeughöhe in Zentimetern (für Durchfahrten).
            laenge_cm: Fahrzeuglänge in Zentimetern (für die Kolonnenlänge).
            gewicht_kg: Zulässiges Gesamtgewicht in Kilogramm.
            antrieb: combustion (Verbrenner) oder electric (E-Fahrzeug).
        """
        async with mcp_context("fahrzeug_anlegen") as ctx:
            ctx.require(SCOPE_WRITE)
            data = VehicleCreate(
                name=name, callsign=funkrufname, license_plate=kennzeichen,
                height_cm=hoehe_cm, length_cm=laenge_cm, weight_kg=gewicht_kg,
                propulsion=antrieb,
            )
            result = await _run(
                vehicle_routes.create_vehicle(data=data, ctx=ctx.org_ctx, db=ctx.db)
            )
            fahrzeug_id = str(getattr(result, "id", None) or result["id"])
            await ctx.audit(
                "fahrzeug_anlegen",
                target_type="vehicle",
                target_id=fahrzeug_id,
                detail={"name": name},
            )
            await ctx.db.commit()
            return {
                "ergebnis": f"Fahrzeug „{name}“ angelegt.",
                "fahrzeug_id": fahrzeug_id,
            }

    @mcp.tool(annotations=annotations.schreibend("Fahrzeug ändern", idempotent=True))
    async def fahrzeug_aktualisieren(
        fahrzeug_id: str,
        name: str | None = None,
        funkrufname: str | None = None,
        kennzeichen: str | None = None,
        hoehe_cm: int | None = None,
        laenge_cm: int | None = None,
        gewicht_kg: int | None = None,
    ) -> dict[str, Any]:
        """Ändert die Stammdaten eines Fahrzeugs.

        Args:
            fahrzeug_id: Die ID aus `fahrzeuge_auflisten`.
            name: Neue Bezeichnung.
            funkrufname: Neuer Funkrufname.
            kennzeichen: Neues Kennzeichen.
            hoehe_cm: Fahrzeughöhe in Zentimetern.
            laenge_cm: Fahrzeuglänge in Zentimetern.
            gewicht_kg: Zulässiges Gesamtgewicht in Kilogramm.
        """
        async with mcp_context("fahrzeug_aktualisieren") as ctx:
            ctx.require(SCOPE_WRITE)
            felder = {
                "name": name, "callsign": funkrufname, "license_plate": kennzeichen,
                "height_cm": hoehe_cm, "length_cm": laenge_cm, "weight_kg": gewicht_kg,
            }
            payload = {k: v for k, v in felder.items() if v is not None}
            if not payload:
                raise McpError("Es wurde kein zu änderndes Feld angegeben.")

            result = await _run(
                vehicle_routes.update_vehicle(
                    vehicle_id=_uuid(fahrzeug_id, "Fahrzeug-ID"),
                    data=VehicleUpdate(**payload),
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "fahrzeug_aktualisieren",
                target_type="vehicle",
                target_id=fahrzeug_id,
                detail={"felder": sorted(payload)},
            )
            await ctx.db.commit()
            return {
                "ergebnis": f"Geändert: {', '.join(sorted(payload))}.",
                "fahrzeug": _vehicle(result) if hasattr(result, "name") else result,
            }

    # ── Zuordnung und Marschfolge ────────────────────────────────────────

    @mcp.tool(annotations=annotations.schreibend("Fahrzeug zuordnen", idempotent=False))
    async def fahrzeug_zu_konvoi_hinzufuegen(
        konvoi_id: str,
        fahrzeug_id: str,
        sonderfunktion: str | None = None,
        mobiltelefon: str | None = None,
    ) -> dict[str, Any]:
        """Ordnet ein Fahrzeug einem Konvoi zu, ans Ende der Marschfolge.

        Args:
            konvoi_id: Die ID des Konvois.
            fahrzeug_id: Die ID des Fahrzeugs aus `fahrzeuge_auflisten`.
            sonderfunktion: spitzenfuehrer | schliessender | sanitaet | ablauffuehrer.
            mobiltelefon: Erreichbarkeit der Besatzung unterwegs.
        """
        async with mcp_context("fahrzeug_zu_konvoi_hinzufuegen") as ctx:
            ctx.require(SCOPE_WRITE)
            await _run(
                convoy_routes.add_vehicle_to_convoy(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    data=AddVehicleRequest(
                        vehicle_id=_uuid(fahrzeug_id, "Fahrzeug-ID"),
                        sonderfunktion=sonderfunktion,
                        mobile_phone=mobiltelefon,
                    ),
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "fahrzeug_zu_konvoi_hinzufuegen",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"fahrzeug_id": fahrzeug_id},
            )
            await ctx.db.commit()
            return await _quittung(ctx, konvoi_id, "Fahrzeug zugeordnet.")

    @mcp.tool(annotations=annotations.schreibend("Fahrzeugzuordnung lösen", idempotent=True))
    async def fahrzeug_aus_konvoi_entfernen(konvoi_id: str, fahrzeug_id: str) -> dict[str, Any]:
        """Löst die Zuordnung eines Fahrzeugs zu einem Konvoi.

        **Das Fahrzeug wird nicht gelöscht.** Es bleibt im Bestand der
        Organisation und lässt sich mit `fahrzeug_zu_konvoi_hinzufuegen`
        jederzeit wieder zuordnen — allerdings am Ende der Marschfolge, die
        bisherige Position geht verloren.

        Args:
            konvoi_id: Die ID des Konvois.
            fahrzeug_id: Die ID des Fahrzeugs, dessen Zuordnung gelöst wird.
        """
        async with mcp_context("fahrzeug_aus_konvoi_entfernen") as ctx:
            ctx.require(SCOPE_WRITE)
            # Vorher nachsehen, damit die Quittung sagen kann, *was* gelöst
            # wurde — nicht nur, dass etwas gelöst wurde.
            convoy = await _load_convoy(ctx, konvoi_id)
            fahrzeug_uuid = _uuid(fahrzeug_id, "Fahrzeug-ID")
            zuordnung = next(
                (cv for cv in convoy.convoy_vehicles if cv.vehicle_id == fahrzeug_uuid),
                None,
            )
            if zuordnung is None:
                raise McpError(
                    f"Das Fahrzeug {fahrzeug_id} ist dem Konvoi „{convoy.name}“ "
                    "nicht zugeordnet."
                )
            bezeichnung = (
                zuordnung.vehicle.callsign or zuordnung.vehicle.name
                if zuordnung.vehicle
                else fahrzeug_id
            )

            await _run(
                convoy_routes.remove_vehicle_from_convoy(
                    convoy_id=convoy.id,
                    vehicle_id=fahrzeug_uuid,
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "fahrzeug_aus_konvoi_entfernen",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"fahrzeug_id": fahrzeug_id, "bezeichnung": bezeichnung},
            )
            await ctx.db.commit()
            return {
                "ergebnis": (
                    f"„{bezeichnung}“ ist nicht mehr dem Konvoi „{convoy.name}“ "
                    "zugeordnet. Das Fahrzeug selbst bleibt im Bestand."
                ),
                "fahrzeug_id": fahrzeug_id,
                "fahrzeug": bezeichnung,
                "konvoi": _kurzfassung(convoy),
                "rueckgaengig_mit": "fahrzeug_zu_konvoi_hinzufuegen",
            }

    @mcp.tool(annotations=annotations.schreibend("Marschordnung ändern", idempotent=True))
    async def konvoi_fahrzeuge_umsortieren(
        konvoi_id: str, fahrzeug_ids_in_reihenfolge: list[str]
    ) -> dict[str, Any]:
        """Setzt die Marschfolge eines Konvois neu.

        Es müssen **alle** Fahrzeuge des Konvois genannt werden, in der
        gewünschten Reihenfolge — sonst wird nichts geändert.

        Args:
            konvoi_id: Die ID des Konvois.
            fahrzeug_ids_in_reihenfolge: Alle Fahrzeug-IDs, erstes zuerst.
        """
        async with mcp_context("konvoi_fahrzeuge_umsortieren") as ctx:
            ctx.require(SCOPE_WRITE)
            items = [
                ConvoyVehicleReorderItem(
                    vehicle_id=_uuid(fid, "Fahrzeug-ID"), position=index
                )
                for index, fid in enumerate(fahrzeug_ids_in_reihenfolge)
            ]
            await _run(
                convoy_routes.reorder_convoy_vehicles(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    items=items,
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "konvoi_fahrzeuge_umsortieren",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"anzahl": len(items)},
            )
            await ctx.db.commit()
            return await _quittung(
                ctx, konvoi_id, f"Marschfolge für {len(items)} Fahrzeuge gesetzt."
            )

    # ── Wegpunkte ────────────────────────────────────────────────────────

    @mcp.tool(annotations=annotations.schreibend("Wegpunkt anlegen", idempotent=False))
    async def wegpunkt_anlegen(
        konvoi_id: str,
        name: str,
        lat: float,
        lon: float,
        art: str = "waypoint",
        haltedauer_min: int = 0,
        haltegrund: str | None = None,
        notiz: str | None = None,
    ) -> dict[str, Any]:
        """Fügt einem Konvoi einen Wegpunkt hinzu, ans Ende der Reihenfolge.

        Args:
            konvoi_id: Die ID des Konvois.
            name: Bezeichnung des Wegpunkts.
            lat: Breitengrad.
            lon: Längengrad.
            art: waypoint | stop | checkpoint | technical_stop.
            haltedauer_min: Geplante Haltedauer in Minuten.
            haltegrund: fuel | rest | maintenance | other.
            notiz: Freitext zum Wegpunkt.
        """
        async with mcp_context("wegpunkt_anlegen") as ctx:
            ctx.require(SCOPE_WRITE)
            convoy = await _load_convoy(ctx, konvoi_id)
            naechster = max((w.order_index for w in convoy.waypoints), default=-1) + 1
            result = await _run(
                convoy_routes.create_waypoint(
                    convoy_id=convoy.id,
                    data=WaypointCreate(
                        name=name, lat=lat, lon=lon, type=art,
                        hold_duration_min=haltedauer_min, halt_purpose=haltegrund,
                        notes=notiz, order_index=naechster,
                    ),
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "wegpunkt_anlegen",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"name": name, "art": art},
            )
            await ctx.db.commit()
            return {
                "ergebnis": f"Wegpunkt „{name}“ angelegt (Position {naechster}).",
                "wegpunkt_id": str(result["id"]),
                "konvoi": _kurzfassung(convoy),
            }

    @mcp.tool(annotations=annotations.schreibend("Wegpunkt ändern", idempotent=True))
    async def wegpunkt_aktualisieren(
        konvoi_id: str,
        wegpunkt_id: str,
        name: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        art: str | None = None,
        haltedauer_min: int | None = None,
        haltegrund: str | None = None,
        notiz: str | None = None,
    ) -> dict[str, Any]:
        """Ändert einen Wegpunkt.

        Args:
            konvoi_id: Die ID des Konvois.
            wegpunkt_id: Die ID des Wegpunkts aus `wegpunkte_auflisten`.
            name: Neue Bezeichnung.
            lat: Neuer Breitengrad (nur zusammen mit lon).
            lon: Neuer Längengrad (nur zusammen mit lat).
            art: waypoint | stop | checkpoint | technical_stop.
            haltedauer_min: Geplante Haltedauer in Minuten.
            haltegrund: fuel | rest | maintenance | other.
            notiz: Freitext zum Wegpunkt.
        """
        async with mcp_context("wegpunkt_aktualisieren") as ctx:
            ctx.require(SCOPE_WRITE)
            if (lat is None) != (lon is None):
                raise McpError(
                    "Breiten- und Längengrad müssen zusammen angegeben werden."
                )
            felder = {
                "name": name, "type": art, "hold_duration_min": haltedauer_min,
                "halt_purpose": haltegrund, "notes": notiz, "lat": lat, "lon": lon,
            }
            payload = {k: v for k, v in felder.items() if v is not None}
            if not payload:
                raise McpError("Es wurde kein zu änderndes Feld angegeben.")

            await _run(
                convoy_routes.update_waypoint(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    waypoint_id=_uuid(wegpunkt_id, "Wegpunkt-ID"),
                    data=WaypointUpdate(**payload),
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "wegpunkt_aktualisieren",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"wegpunkt_id": wegpunkt_id, "felder": sorted(payload)},
            )
            await ctx.db.commit()
            return await _quittung(
                ctx, konvoi_id, f"Wegpunkt geändert: {', '.join(sorted(payload))}."
            )

    @mcp.tool(annotations=annotations.schreibend("Wegpunkte umsortieren", idempotent=True))
    async def wegpunkte_umsortieren(
        konvoi_id: str, wegpunkt_ids_in_reihenfolge: list[str]
    ) -> dict[str, Any]:
        """Setzt die Reihenfolge der Wegpunkte eines Konvois neu.

        Args:
            konvoi_id: Die ID des Konvois.
            wegpunkt_ids_in_reihenfolge: Alle Wegpunkt-IDs, erster zuerst.
        """
        async with mcp_context("wegpunkte_umsortieren") as ctx:
            ctx.require(SCOPE_WRITE)
            items = [
                WaypointReorderItem(id=_uuid(wid, "Wegpunkt-ID"), order_index=index)
                for index, wid in enumerate(wegpunkt_ids_in_reihenfolge)
            ]
            await _run(
                convoy_routes.reorder_waypoints(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    items=items,
                    ctx=ctx.org_ctx,
                    db=ctx.db,
                )
            )
            await ctx.audit(
                "wegpunkte_umsortieren",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"anzahl": len(items)},
            )
            await ctx.db.commit()
            return await _quittung(
                ctx, konvoi_id, f"Reihenfolge für {len(items)} Wegpunkte gesetzt."
            )

    # ── Route ────────────────────────────────────────────────────────────

    @mcp.tool(annotations=annotations.schreibend("Route berechnen", idempotent=True))
    async def route_berechnen(konvoi_id: str) -> dict[str, Any]:
        """Berechnet die Route des Konvois über die Wegpunkte neu.

        Braucht einen gesetzten Start- und Zielpunkt. Die Berechnung kostet
        Rechenzeit auf dem Routing-Dienst der Instanz und unterliegt deshalb
        einem stündlichen Kontingent.

        Args:
            konvoi_id: Die ID des Konvois.
        """
        async with mcp_context("route_berechnen") as ctx:
            ctx.require(SCOPE_WRITE)
            # Dasselbe Kontingent wie an der REST-API — gezählt wird hier nur,
            # weil die FastAPI-Dependency im MCP-Pfad nicht greift.
            ctx.spend("routing", settings.quota_routing_per_hour)
            result = await _run(
                routing_routes.calculate_route(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    db=ctx.db,
                    current_user=ctx.user,
                )
            )
            await ctx.audit(
                "route_berechnen", target_type="convoy", target_id=konvoi_id
            )
            await ctx.db.commit()
            strecke = result.get("distance_m") if isinstance(result, dict) else None
            dauer = result.get("duration_s") if isinstance(result, dict) else None
            return {
                "ergebnis": "Route berechnet.",
                "strecke_m": strecke,
                "fahrzeit_s": dauer,
            }

    # ── Marschstatus ─────────────────────────────────────────────────────

    @mcp.tool(annotations=annotations.schreibend("Mannschaftsstärke melden", idempotent=True))
    async def fahrzeugstaerke_melden(
        konvoi_id: str,
        fahrzeug_id: str,
        fuehrer: int = 0,
        unterfuehrer: int = 0,
        mannschaften: int = 0,
    ) -> dict[str, Any]:
        """Meldet die Mannschaftsstärke eines Fahrzeugs im Konvoi.

        Notation Führer/Unterführer/Mannschaften//Gesamt, also etwa 0/1/8//9.
        Die Gesamtzahl wird gerechnet und darf nicht mitgegeben werden.

        Eine Meldung mit lauter Nullen heißt „Fahrzeug fährt unbesetzt" und ist
        etwas anderes als gar keine Meldung. Wer die Stärke nicht kennt, meldet
        sie nicht, statt Nullen zu schicken.

        Args:
            konvoi_id: Die ID des Konvois.
            fahrzeug_id: Die ID des Fahrzeugs.
            fuehrer: Anzahl Führer an Bord (0–99).
            unterfuehrer: Anzahl Unterführer an Bord (0–99).
            mannschaften: Anzahl Mannschaften an Bord (0–99).
        """
        async with mcp_context("fahrzeugstaerke_melden") as ctx:
            ctx.require(SCOPE_FLEET_STATUS)
            await _run(
                tracking_routes.update_vehicle_staerke(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    vehicle_id=_uuid(fahrzeug_id, "Fahrzeug-ID"),
                    data=tracking_routes.StaerkeUpdate(
                        fuehrer=fuehrer, unterfuehrer=unterfuehrer, mannschaften=mannschaften
                    ),
                    db=ctx.db,
                    current_user=ctx.user,
                )
            )
            gesamt = staerke_svc.gesamt(fuehrer, unterfuehrer, mannschaften)
            await ctx.audit(
                "fahrzeugstaerke_melden",
                target_type="convoy",
                target_id=konvoi_id,
                detail={
                    "fahrzeug_id": fahrzeug_id,
                    "staerke": f"{fuehrer}/{unterfuehrer}/{mannschaften}",
                },
            )
            await ctx.db.commit()
            return {
                "ergebnis": f"Stärke {fuehrer}/{unterfuehrer}/{mannschaften}//{gesamt} gemeldet.",
                "fahrzeug_id": fahrzeug_id,
                "fuehrer": fuehrer,
                "unterfuehrer": unterfuehrer,
                "mannschaften": mannschaften,
                "gesamt": gesamt,
            }

    @mcp.tool(annotations=annotations.schreibend("Fahrzeugstatus melden", idempotent=True))
    async def fahrzeugstatus_setzen(
        konvoi_id: str,
        fahrzeug_id: str,
        status: str,
        stufe: str | None = None,
        notiz: str | None = None,
    ) -> dict[str, Any]:
        """Meldet den Marschstatus eines Fahrzeugs im Konvoi.

        Technische Halte und Ausfälle lösen einen Alarm an die Konvoiführung
        aus — dieser Aufruf ist also unmittelbar sichtbar.

        Args:
            konvoi_id: Die ID des Konvois.
            fahrzeug_id: Die ID des Fahrzeugs.
            status: planned | en_route | arrived | technical_halt | breakdown.
            stufe: Bei technical_halt: standard | dringend | sehr_dringend.
                Bei breakdown: total | limited.
            notiz: Kurze Erläuterung, z. B. „Reifenschaden".
        """
        async with mcp_context("fahrzeugstatus_setzen") as ctx:
            ctx.require(SCOPE_FLEET_STATUS)
            await _run(
                tracking_routes.update_vehicle_status(
                    convoy_id=_uuid(konvoi_id, "Konvoi-ID"),
                    vehicle_id=_uuid(fahrzeug_id, "Fahrzeug-ID"),
                    data=tracking_routes.VehicleStatusUpdate(
                        vehicle_status=status, status_level=stufe, status_note=notiz
                    ),
                    db=ctx.db,
                    current_user=ctx.user,
                )
            )
            await ctx.audit(
                "fahrzeugstatus_setzen",
                target_type="convoy",
                target_id=konvoi_id,
                detail={"fahrzeug_id": fahrzeug_id, "status": status, "stufe": stufe},
            )
            await ctx.db.commit()
            return {
                "ergebnis": f"Status auf „{status}“ gesetzt.",
                "fahrzeug_id": fahrzeug_id,
                "status": status,
                "stufe": stufe,
            }
