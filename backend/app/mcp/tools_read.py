"""Die lesenden Werkzeuge des MCP-Servers.

Jedes Werkzeug holt sich über ``mcp_context()`` Benutzer, Organisation und
Rolle, erzwingt seinen Scope und greift dann auf dieselben Modelle und
Dienste zu wie die REST-Routen — nicht über HTTP auf die eigene API.

Die Antworten sind bewusst schmal gehalten. Ein Sprachmodell liest sie als
Text, also kostet jedes überflüssige Feld Kontext und jede rohe UUID ohne
Bedeutung stiftet Verwirrung. Zeiten gehen als ISO-8601 raus, Entfernungen
in Metern, Dauern in Sekunden — benannt, damit die Einheit nicht geraten
werden muss.

Die Werkzeuge geben ``dict[str, Any]`` zurück und nicht ``dict``. Der
Unterschied ist nicht kosmetisch: nur mit der genaueren Angabe leitet das SDK
ein Ausgabeschema ab und liefert die Antwort zusätzlich als
``structuredContent`` — als Struktur statt nur als Text. Clients mit
Oberfläche lesen genau das (siehe ``app/mcp/widgets.py``), und ein Modell
bekommt die Felder benannt statt sie aus einem Textblock zu fischen. Der
Textteil bleibt daneben bestehen, ein Client ohne Schema verliert also
nichts.
"""
import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.mcp import WRITE_TOOLS
from app.mcp import subscriptions as live
from app.mcp.context import McpError, mcp_context
from app.mcp import annotations, widgets
from app.mcp.scopes import SCOPE_LABELS, SCOPE_READ, TOOL_SCOPES, satisfies
from app.middleware.license_guard import is_licensed
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.route import Route
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.models.waypoint import Waypoint
from app.services import geometry as geo_svc


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# Wie viele Konvois eine Auflistung höchstens zurückgibt. Kein Sicherheits-,
# sondern ein Kontextlimit: was darüber hinausgeht, liest kein Modell mehr
# sinnvoll, es verdrängt nur den Gesprächsverlauf.
MAX_TREFFER = 200


def _zeitpunkt(raw: str, feld: str, *, tagesende: bool = False) -> datetime:
    """Eine Zeitangabe aus einem Werkzeugaufruf in einen Zeitpunkt übersetzen.

    Erlaubt ist ISO-8601, mit oder ohne Uhrzeit. Ein reines Datum meint bei
    der oberen Grenze das **Ende** des Tages — „bis 21.09." ohne diesen
    Griff schlösse den 21. aus, und niemand meint das so.

    Eine Zonenangabe wird abgeschnitten, nicht umgerechnet: ``start_time``
    ist in ConvoyPlan die Ortszeit der Instanz (siehe ``models/convoy.py``).
    Ein Modell, das gewohnheitsmäßig ein „Z" anhängt, soll damit nicht die
    Marschzeiten um zwei Stunden verschieben."""
    text = raw.strip()
    try:
        wert = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise McpError(
            f"„{raw}“ ist für {feld} keine lesbare Zeitangabe. Erwartet wird "
            "ISO-8601, also etwa 2026-09-21 oder 2026-09-21T06:30."
        )
    wert = wert.replace(tzinfo=None)
    # Ein reines Datum kommt als Mitternacht an; nur dann greift die
    # Ausdehnung auf das Tagesende — bei 2026-09-21T00:00 wäre sie falsch,
    # aber unterscheidbar ist das nur am Text.
    if tagesende and len(text) <= 10:
        wert = datetime.combine(wert.date(), time.max)
    return wert


def _convoy_brief(convoy: Convoy) -> dict:
    return {
        "id": str(convoy.id),
        "name": convoy.name,
        "status": convoy.status,
        "start_zeit": _iso(convoy.start_time),
        "fahrzeuge_anzahl": len(convoy.convoy_vehicles),
        "wegpunkte_anzahl": len(convoy.waypoints),
        "ist_unterkonvoi": convoy.parent_convoy_id is not None,
    }


def _convoy_full(convoy: Convoy) -> dict:
    data = _convoy_brief(convoy)
    data.update(
        {
            "marschform": convoy.marschform,
            "startpunkt": geo_svc.wkb_to_point(convoy.start_point),
            "zielpunkt": geo_svc.wkb_to_point(convoy.end_point),
            "geschwindigkeit_innerorts_kmh": convoy.speed_urban_kmh,
            "geschwindigkeit_ausserorts_kmh": convoy.speed_rural_kmh,
            "abstand_innerorts_m": convoy.spacing_urban_m,
            "abstand_ausserorts_m": convoy.spacing_rural_m,
            "abstand_autobahn_m": convoy.spacing_motorway_m,
            "strassenpraeferenz": convoy.road_preference,
            # Die Resource, die sich abonnieren lässt. Sie steht hier, weil
            # der Client die Organisation in der URI sonst nicht kennt —
            # und ohne sie kein Abo aufmachen kann.
            "live_uri": live.live_uri(convoy.organization_id, convoy.id),
            # Die sieben Abschnitte des Marschbefehls. Genau dafür wird ein
            # Modell hier am ehesten gebraucht, also gehören sie mit hinein.
            "marschbefehl": {
                "lage": convoy.lage,
                "auftrag": convoy.auftrag,
                "ablaufpunkt": convoy.ablaufpunkt,
                "ablaufzeit": _iso(convoy.ablaufzeit),
                "ablauffuehrer": convoy.ablaufführer,
                "versorgung": convoy.versorgung,
                "funkgruppe": convoy.funkgruppe,
                "anlagen": convoy.anlagen,
            },
            "fahrzeuge": [
                {
                    "position": cv.position,
                    "fahrzeug_id": str(cv.vehicle_id),
                    "name": cv.vehicle.name if cv.vehicle else None,
                    "funkrufname": cv.vehicle.callsign if cv.vehicle else None,
                    "kennzeichen": cv.vehicle.license_plate if cv.vehicle else None,
                    "status": cv.vehicle_status,
                    "status_stufe": cv.status_level,
                    "status_notiz": cv.status_note,
                    "sonderfunktion": cv.sonderfunktion,
                }
                for cv in sorted(convoy.convoy_vehicles, key=lambda c: c.position)
            ],
        }
    )
    return data


def _vehicle(vehicle: Vehicle) -> dict:
    data = {
        "id": str(vehicle.id),
        "name": vehicle.name,
        "funkrufname": vehicle.callsign,
        "kennzeichen": vehicle.license_plate,
        "rolle_im_konvoi": vehicle.convoy_role,
        "hoehe_cm": vehicle.height_cm,
        "laenge_cm": vehicle.length_cm,
        "gewicht_kg": vehicle.weight_kg,
        "antrieb": vehicle.propulsion,
    }
    # Nur die Felder der tatsächlichen Antriebsart mitschicken — ein
    # E-Fahrzeug mit "tank_kapazitaet_l: null" lädt nur zu Fehlschlüssen ein.
    if vehicle.propulsion == "electric":
        data.update(
            {
                "akku_kapazitaet_kwh": vehicle.battery_capacity_kwh,
                "verbrauch_kwh_100km": vehicle.consumption_kwh_100km,
                "ladestand_kwh": vehicle.current_charge_kwh,
            }
        )
    else:
        data.update(
            {
                "tank_kapazitaet_l": vehicle.tank_capacity_l,
                "verbrauch_l_100km": vehicle.fuel_consumption_l100km,
                "tankstand_l": vehicle.current_fuel_l,
            }
        )
    return data


async def _positionen(ctx, convoy: Convoy) -> list[dict]:
    """Die zuletzt gemeldeten Positionen eines Konvois.

    Ausgelagert, weil sowohl ``fahrzeugpositionen_abrufen`` als auch die
    Live-Resource (``app/mcp/subscriptions.py``) dieselbe Antwort liefern
    müssen — zwei Formen derselben Auskunft wären zwei Wahrheiten."""
    rows = (
        await ctx.db.execute(
            select(VehiclePosition)
            .where(VehiclePosition.convoy_id == convoy.id)
            .options(selectinload(VehiclePosition.vehicle))
            .order_by(VehiclePosition.recorded_at.desc())
        )
    ).scalars().all()
    return [
        {
            "fahrzeug_id": str(p.vehicle_id),
            "name": p.vehicle.name if p.vehicle else None,
            "funkrufname": p.vehicle.callsign if p.vehicle else None,
            "lat": p.lat,
            "lon": p.lon,
            "geschwindigkeit_kmh": p.speed_kmh,
            "kurs": p.heading,
            "gemeldet_um": _iso(p.recorded_at),
        }
        for p in rows
    ]


def _status(convoy: Convoy) -> tuple[dict[str, int], list[dict]]:
    """Zusammenfassung und Einzelstatus der Fahrzeuge eines Konvois."""
    zusammenfassung: dict[str, int] = {}
    fahrzeuge = []
    for cv in sorted(convoy.convoy_vehicles, key=lambda c: c.position):
        zusammenfassung[cv.vehicle_status] = zusammenfassung.get(cv.vehicle_status, 0) + 1
        fahrzeuge.append(
            {
                "position": cv.position,
                "fahrzeug_id": str(cv.vehicle_id),
                "name": cv.vehicle.name if cv.vehicle else None,
                "funkrufname": cv.vehicle.callsign if cv.vehicle else None,
                "status": cv.vehicle_status,
                "status_stufe": cv.status_level,
                "status_notiz": cv.status_note,
                "status_seit": _iso(cv.status_changed_at),
            }
        )
    return zusammenfassung, fahrzeuge


def _convoy_query(org_id: uuid.UUID):
    return (
        select(Convoy)
        .where(Convoy.organization_id == org_id)
        .options(
            selectinload(Convoy.convoy_vehicles).selectinload(ConvoyVehicle.vehicle),
            selectinload(Convoy.waypoints),
        )
    )


async def _load_convoy(ctx, convoy_id: str) -> Convoy:
    """Einen Konvoi der eigenen Organisation laden.

    Die Einschränkung auf ``organization_id`` ist die Mandantentrennung: ein
    Konvoi einer fremden Organisation ist über dieses Token nicht auffindbar,
    und die Fehlermeldung unterscheidet nicht zwischen „gibt es nicht" und
    „gehört jemand anderem" — sonst ließe sich über die Antwort feststellen,
    welche IDs anderswo existieren."""
    try:
        parsed = uuid.UUID(convoy_id)
    except ValueError:
        raise McpError(f"„{convoy_id}“ ist keine gültige Konvoi-ID.")

    convoy = (
        await ctx.db.execute(_convoy_query(ctx.organization.id).where(Convoy.id == parsed))
    ).scalar_one_or_none()
    if convoy is None:
        raise McpError(
            f"Kein Konvoi mit der ID {convoy_id} in der Organisation "
            f"„{ctx.organization.name}“."
        )
    # Dem Veröffentlicher der Live-Abos die Organisation dieses Konvois
    # bekannt machen — siehe app/mcp/subscriptions.py.
    live.merke_konvoi(convoy.id, convoy.organization_id)
    return convoy


def register(mcp) -> None:
    """Die lesenden Werkzeuge am Server anmelden."""

    @mcp.tool(
        meta=widgets.meta(
            widgets.URI_KONVOI_LISTE,
            laeuft="Konvois werden gesucht …",
            fertig="Konvois gefunden",
        ),
        annotations=annotations.lesend("Konvois auflisten"),
    )
    async def konvois_auflisten(
        von: str | None = None,
        bis: str | None = None,
        status: str | None = None,
        suche: str | None = None,
        nur_hauptkonvois: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Listet die Konvois (Marschkolonnen) der Organisation.

        Ohne Angaben kommen die zuletzt angelegten Konvois, neueste zuerst.
        Die Filter sind dafür da, dass eine Frage nach einem Zeitraum nicht
        über den gesamten Bestand beantwortet werden muss: „Welche Konvois
        stehen nächste Woche an?" ist `von`/`bis`, nicht alles abrufen und
        selbst aussortieren.

        Gibt je Konvoi eine Kurzfassung zurück. Für Wegpunkte, Marschbefehl
        und die Fahrzeugliste anschließend `konvoi_details` aufrufen.

        Args:
            von: Nur Konvois, die ab diesem Zeitpunkt starten (ISO-8601,
                Datum genügt). Konvois ohne Startzeit fallen bei jeder
                Zeitangabe heraus — sie sind zeitlich nicht eingeplant.
            bis: Nur Konvois, die bis zu diesem Zeitpunkt starten. Ein reines
                Datum meint den ganzen Tag.
            status: planning | active | completed.
            suche: Textteil im Namen des Konvois, Groß-/Kleinschreibung egal.
            nur_hauptkonvois: Unterkonvois (Teilkolonnen) auslassen.
            limit: Höchstzahl der Treffer, Standard 50, Obergrenze 200.
        """
        async with mcp_context("konvois_auflisten") as ctx:
            ctx.require(SCOPE_READ)
            query = _convoy_query(ctx.organization.id)
            zeitlich = False

            if von is not None:
                query = query.where(Convoy.start_time >= _zeitpunkt(von, "von"))
                zeitlich = True
            if bis is not None:
                query = query.where(
                    Convoy.start_time <= _zeitpunkt(bis, "bis", tagesende=True)
                )
                zeitlich = True
            if status is not None:
                query = query.where(Convoy.status == status)
            if suche:
                query = query.where(Convoy.name.ilike(f"%{suche}%"))
            if nur_hauptkonvois:
                query = query.where(Convoy.parent_convoy_id.is_(None))

            # Nach einem Zeitraum gefragt heißt: in zeitlicher Reihenfolge
            # geantwortet. „Was steht an?" will den nächsten Marsch zuerst,
            # nicht den zuletzt angelegten.
            query = query.order_by(
                Convoy.start_time.asc() if zeitlich else Convoy.created_at.desc()
            )

            grenze = max(1, min(limit, MAX_TREFFER))
            # Einen über die Grenze hinaus holen, um „da ist noch mehr"
            # sagen zu können, ohne zweimal zu zählen.
            rows = (
                await ctx.db.execute(query.limit(grenze + 1))
            ).scalars().all()
            weitere = len(rows) > grenze
            rows = rows[:grenze]

            for c in rows:
                live.merke_konvoi(c.id, c.organization_id)
            antwort = {
                "organisation": ctx.organization.name,
                "anzahl": len(rows),
                "konvois": [_convoy_brief(c) for c in rows],
            }
            if weitere:
                antwort["hinweis"] = (
                    f"Es gibt mehr als {grenze} Treffer; angezeigt werden die "
                    "ersten. Filter enger setzen oder limit erhöhen "
                    f"(höchstens {MAX_TREFFER})."
                )
            return antwort

    @mcp.tool(annotations=annotations.lesend("Organisation und Rechte"))
    async def organisation_details() -> dict[str, Any]:
        """Mit welcher Organisation diese Verbindung arbeitet und was sie darf.

        Beantwortet zwei Fragen, die sonst nur durch Ausprobieren zu klären
        sind: auf wessen Daten die Werkzeuge zugreifen — eine Verbindung gilt
        für **genau eine** Organisation, auch wenn der Benutzer mehreren
        angehört — und welche Werkzeuge mit den erteilten Rechten überhaupt
        durchgehen.

        Vor einem schreibenden Aufruf lohnt sich der Blick: fehlt das Recht,
        steht das hier, statt dass der Aufruf daran scheitert.
        """
        async with mcp_context("organisation_details") as ctx:
            ctx.require(SCOPE_READ)
            konvois = (
                await ctx.db.execute(
                    select(Convoy.id).where(Convoy.organization_id == ctx.organization.id)
                )
            ).scalars().all()
            fahrzeuge = (
                await ctx.db.execute(
                    select(Vehicle.id).where(Vehicle.org_id == ctx.organization.id)
                )
            ).scalars().all()
            # Die Werkzeuge, die mit diesen Scopes durchgehen. Gelesen aus
            # derselben Tabelle, die die Transportschicht benutzt — eine
            # zweite Liste hier liefe beim nächsten neuen Werkzeug auseinander.
            #
            # Die Lizenz kommt dazu, weil ``tools/list`` ohne sie die
            # schreibenden Werkzeuge gar nicht erst zeigt (``mount.py``).
            # Sie hier trotzdem aufzuzählen hieße, einem Modell etwas
            # anzubieten, das es nirgends findet.
            lizenziert = await is_licensed()
            erlaubt = sorted(
                name
                for name, scope in TOOL_SCOPES.items()
                if satisfies(ctx.scopes, scope)
                and (lizenziert or name not in WRITE_TOOLS)
            )
            return {
                "organisation": ctx.organization.name,
                "eigene_rolle": ctx.role,
                "erteilte_rechte": [
                    {"scope": s, "bedeutung": SCOPE_LABELS.get(s, s)} for s in ctx.scopes
                ],
                "verfuegbare_werkzeuge": erlaubt,
                "konvois_anzahl": len(konvois),
                "fahrzeuge_anzahl": len(fahrzeuge),
                "hinweis": (
                    "Diese Verbindung gilt nur für diese Organisation. Kein "
                    "Werkzeug löscht Daten; jeder schreibende Aufruf wird "
                    "protokolliert."
                ),
            }

    @mcp.tool(
        meta=widgets.meta(
            widgets.URI_KONVOI_UEBERSICHT,
            laeuft="Konvoi wird geladen …",
            fertig="Konvoi geladen",
        ),
        annotations=annotations.lesend("Konvoi ansehen"),
    )
    async def konvoi_details(konvoi_id: str) -> dict[str, Any]:
        """Alle Stammdaten eines Konvois: Marschbefehl, Fahrzeuge, Eckdaten.

        Args:
            konvoi_id: Die ID aus `konvois_auflisten`.
        """
        async with mcp_context("konvoi_details") as ctx:
            ctx.require(SCOPE_READ)
            return _convoy_full(await _load_convoy(ctx, konvoi_id))

    @mcp.tool(annotations=annotations.lesend("Unterkonvois auflisten"))
    async def unterkonvois_auflisten(konvoi_id: str) -> dict[str, Any]:
        """Listet die Unterkonvois (Teilkolonnen) eines Konvois.

        Args:
            konvoi_id: Die ID des übergeordneten Konvois.
        """
        async with mcp_context("unterkonvois_auflisten") as ctx:
            ctx.require(SCOPE_READ)
            parent = await _load_convoy(ctx, konvoi_id)
            rows = (
                await ctx.db.execute(
                    _convoy_query(ctx.organization.id)
                    .where(Convoy.parent_convoy_id == parent.id)
                    .order_by(Convoy.created_at)
                )
            ).scalars().all()
            return {
                "konvoi": parent.name,
                "anzahl": len(rows),
                "unterkonvois": [_convoy_brief(c) for c in rows],
            }

    @mcp.tool(annotations=annotations.lesend("Fahrzeuge auflisten"))
    async def fahrzeuge_auflisten() -> dict[str, Any]:
        """Listet den Fahrzeugbestand der Organisation.

        Das sind die Stammdaten, unabhängig davon, ob ein Fahrzeug gerade
        einem Konvoi zugeordnet ist.
        """
        async with mcp_context("fahrzeuge_auflisten") as ctx:
            ctx.require(SCOPE_READ)
            rows = (
                await ctx.db.execute(
                    select(Vehicle)
                    .where(Vehicle.org_id == ctx.organization.id)
                    .order_by(Vehicle.order_index, Vehicle.name)
                )
            ).scalars().all()
            return {
                "organisation": ctx.organization.name,
                "anzahl": len(rows),
                "fahrzeuge": [_vehicle(v) for v in rows],
            }

    @mcp.tool(annotations=annotations.lesend("Fahrzeug ansehen"))
    async def fahrzeug_details(fahrzeug_id: str) -> dict[str, Any]:
        """Stammdaten eines einzelnen Fahrzeugs.

        Args:
            fahrzeug_id: Die ID aus `fahrzeuge_auflisten`.
        """
        async with mcp_context("fahrzeug_details") as ctx:
            ctx.require(SCOPE_READ)
            try:
                parsed = uuid.UUID(fahrzeug_id)
            except ValueError:
                raise McpError(f"„{fahrzeug_id}“ ist keine gültige Fahrzeug-ID.")
            vehicle = (
                await ctx.db.execute(
                    select(Vehicle).where(
                        Vehicle.id == parsed, Vehicle.org_id == ctx.organization.id
                    )
                )
            ).scalar_one_or_none()
            if vehicle is None:
                raise McpError(
                    f"Kein Fahrzeug mit der ID {fahrzeug_id} in der Organisation "
                    f"„{ctx.organization.name}“."
                )
            return _vehicle(vehicle)

    @mcp.tool(annotations=annotations.lesend("Wegpunkte auflisten"))
    async def wegpunkte_auflisten(konvoi_id: str) -> dict[str, Any]:
        """Die Wegpunkte eines Konvois in Marschreihenfolge.

        Args:
            konvoi_id: Die ID des Konvois.
        """
        async with mcp_context("wegpunkte_auflisten") as ctx:
            ctx.require(SCOPE_READ)
            convoy = await _load_convoy(ctx, konvoi_id)
            rows = (
                await ctx.db.execute(
                    select(Waypoint)
                    .where(Waypoint.convoy_id == convoy.id)
                    .order_by(Waypoint.order_index)
                )
            ).scalars().all()
            return {
                "konvoi": convoy.name,
                "anzahl": len(rows),
                "wegpunkte": [
                    {
                        "id": str(w.id),
                        "reihenfolge": w.order_index,
                        "name": w.name,
                        "art": w.type,
                        "koordinaten": geo_svc.waypoint_coords(w),
                        "ankunft_geplant": _iso(w.planned_arrival),
                        "abfahrt_geplant": _iso(w.planned_departure),
                        "haltedauer_min": w.hold_duration_min,
                        "haltegrund": w.halt_purpose,
                        "notiz": w.notes,
                    }
                    for w in rows
                ],
            }

    @mcp.tool(annotations=annotations.lesend("Route abrufen"))
    async def route_abrufen(konvoi_id: str, mit_geometrie: bool = False) -> dict[str, Any]:
        """Die gespeicherte Route eines Konvois.

        Berechnet nichts — liefert nur, was zuletzt berechnet wurde. Ist noch
        keine Route vorhanden, sagt die Antwort das ausdrücklich.

        Args:
            konvoi_id: Die ID des Konvois.
            mit_geometrie: Den vollständigen Linienzug als GeoJSON mitliefern.
                Standardmäßig aus, weil er sehr lang wird und für die meisten
                Fragen (Dauer, Länge) nicht gebraucht wird.
        """
        async with mcp_context("route_abrufen") as ctx:
            ctx.require(SCOPE_READ)
            convoy = await _load_convoy(ctx, konvoi_id)
            route = (
                await ctx.db.execute(select(Route).where(Route.convoy_id == convoy.id))
            ).scalar_one_or_none()
            if route is None:
                return {
                    "konvoi": convoy.name,
                    "route_vorhanden": False,
                    "hinweis": "Für diesen Konvoi wurde noch keine Route berechnet.",
                }
            data = {
                "konvoi": convoy.name,
                "route_vorhanden": True,
                "strecke_m": route.distance_m,
                "fahrzeit_s": route.duration_s,
                "kanalwechsel": route.kanalwechsel,
            }
            if mit_geometrie:
                data["geometrie_geojson"] = geo_svc.linestring_to_geojson(route.geometry)
            return data

    @mcp.tool(annotations=annotations.lesend("Fahrzeugpositionen abrufen"))
    async def fahrzeugpositionen_abrufen(konvoi_id: str) -> dict[str, Any]:
        """Die zuletzt gemeldeten Positionen der Fahrzeuge eines Konvois.

        Args:
            konvoi_id: Die ID des Konvois.
        """
        async with mcp_context("fahrzeugpositionen_abrufen") as ctx:
            ctx.require(SCOPE_READ)
            convoy = await _load_convoy(ctx, konvoi_id)
            positionen = await _positionen(ctx, convoy)
            return {
                "konvoi": convoy.name,
                "anzahl": len(positionen),
                "positionen": positionen,
            }

    @mcp.tool(
        meta=widgets.meta(
            widgets.URI_KONVOI_STATUS,
            laeuft="Marschstatus wird abgefragt …",
            fertig="Marschstatus abgefragt",
        ),
        annotations=annotations.lesend("Marschstatus ansehen"),
    )
    async def konvoi_status(konvoi_id: str) -> dict[str, Any]:
        """Der Marschstatus eines Konvois, je Fahrzeug und zusammengefasst.

        Zeigt, welche Fahrzeuge unterwegs, angekommen, im technischen Halt
        oder ausgefallen sind — die Frage, die unterwegs am häufigsten
        gestellt wird.

        Args:
            konvoi_id: Die ID des Konvois.
        """
        async with mcp_context("konvoi_status") as ctx:
            ctx.require(SCOPE_READ)
            convoy = await _load_convoy(ctx, konvoi_id)
            zusammenfassung, fahrzeuge = _status(convoy)
            return {
                "konvoi": convoy.name,
                "konvoi_status": convoy.status,
                "zusammenfassung": zusammenfassung,
                "fahrzeuge": fahrzeuge,
            }
