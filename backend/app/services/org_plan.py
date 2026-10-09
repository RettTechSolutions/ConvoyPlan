"""Pläne je Organisation — Katalog, Zustand, Sperre nach Ablauf.

Wo das hingehört, steht in ``models/org_plan.py``: der Schlüssel gilt für die
Instanz, ein Paket für eine Organisation. Hier steht, was aus einem Paket
folgt, und zwar in zwei deutlich verschiedenen Stärken:

**Grenzen sind weich.** Mehr Fahrzeuge, Planer oder Tracker als gebucht werden nicht
abgewiesen. Der Org-Admin sieht einen Hinweis, der Betreiber die
Überschreitung in seiner Übersicht, und abgerechnet wird kaufmännisch
(nächste Stufe, anteilig). Eine Absage beim Anlegen des 26. Fahrzeugs träfe
genau den Moment, in dem jemand während einer Lage ein Fahrzeug nachträgt —
das ist für eine BOS-Anwendung kein Vertragsdetail, sondern ein Fehler.

**Ablauf wird wirksam, aber nicht über Nacht.** Nach ``valid_until`` laufen
``KULANZ_TAGE`` weiter wie gehabt, mit Hinweis. Danach ist die Organisation
nur noch lesend — dieselbe Semantik wie der Demo-Modus der Instanz: nichts
wird gelöscht, Fahrer-Links senden weiter, nur Planen geht nicht mehr.
Durchgesetzt wird das in ``api/deps.get_org_context`` (REST) und in
``mcp/context.mcp_context`` (schreibende Werkzeuge).

Die Rechenregeln (``zustand``) stehen ohne Datenbank und Uhr und werden von
``tests/test_org_plan_grenzen.py`` so geprüft.
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_plan import OrganizationPlan
from app.models.organization import UserOrganization
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.vehicle import Vehicle

# Wer als Planer zählt. Fahrer und Beobachter sind in jedem Paket frei —
# gerade damit niemand Zugänge teilt, um unter einer Grenze zu bleiben.
PLANER_ROLLEN = ("admin", "planer")

KULANZ_TAGE = 14


@dataclass(frozen=True)
class Katalogplan:
    schluessel: str
    label: str
    max_fahrzeuge: int | None
    max_planer: int | None
    # Feste Laufzeit ab Setzen; None = Vertrag, läuft bis auf Weiteres.
    laufzeit_tage: int | None = None
    # Tracker sind in keinem Paket begrenzt, solange es dafür keine Preise
    # gibt; ein Angebot setzt die Grenze je Organisation.
    max_tracker: int | None = None


# Ausgangswerte beim Setzen eines Plans. Die geltenden Werte stehen in der
# Zeile, damit ein Angebot abweichen darf und eine Änderung hier keine
# bestehenden Verträge umschreibt. Preise gehören nicht hierher.
KATALOG: dict[str, Katalogplan] = {
    p.schluessel: p
    for p in (
        Katalogplan("hosting_s", "Hosting S", 25, 5),
        Katalogplan("hosting_m", "Hosting M", 150, 20),
        Katalogplan("hosting_l", "Hosting L", None, None),
        Katalogplan("einsatz", "Einsatz-Paket", 50, 10, laufzeit_tage=30),
        Katalogplan("individuell", "Individuell", None, None),
    )
}


@dataclass(frozen=True)
class Nutzung:
    fahrzeuge: int
    planer: int
    # Gezählt werden Tracker, die senden dürfen (``aktiv``). Ein gesperrtes
    # Gerät bekommt 401 und belegt nichts — wer eines ausmustert, sperrt es
    # und muss es nicht erst löschen, um unter die Grenze zu kommen.
    tracker: int = 0


@dataclass(frozen=True)
class Zustand:
    """Was ein Plan für eine Organisation gerade bedeutet."""

    fahrzeuge_ueber: bool = False
    planer_ueber: bool = False
    tracker_ueber: bool = False
    # valid_until überschritten (Kulanz läuft oder ist vorbei)
    abgelaufen: bool = False
    # abgelaufen und Kulanz vorbei: nur noch lesend
    gesperrt: bool = False
    # Tage bis valid_until (negativ = seit Ablauf); None ohne Ablaufdatum
    tage_bis_ablauf: int | None = None
    # letzter Tag vor der Sperre; None ohne Ablaufdatum
    sperre_ab: date | None = None


def _ueber(anzahl: int, grenze: int | None) -> bool:
    return grenze is not None and anzahl > grenze


def zustand(
    zeile: OrganizationPlan | None, nutzung: Nutzung, heute: date
) -> Zustand:
    """Die Rechenregel. Keine Zeile → kein Plan, keine Grenzen, nie gesperrt."""
    if zeile is None:
        return Zustand()
    tage = sperre_ab = None
    abgelaufen = gesperrt = False
    if zeile.valid_until is not None:
        tage = (zeile.valid_until - heute).days
        # Gesperrt ab dem Tag NACH Ablauf der Kulanz: valid_until ist der
        # letzte gebuchte Tag, danach folgen KULANZ_TAGE volle Tage.
        sperre_ab = zeile.valid_until + timedelta(days=KULANZ_TAGE + 1)
        abgelaufen = heute > zeile.valid_until
        gesperrt = heute >= sperre_ab
    return Zustand(
        fahrzeuge_ueber=_ueber(nutzung.fahrzeuge, zeile.max_vehicles),
        planer_ueber=_ueber(nutzung.planer, zeile.max_planners),
        tracker_ueber=_ueber(nutzung.tracker, zeile.max_trackers),
        abgelaufen=abgelaufen,
        gesperrt=gesperrt,
        tage_bis_ablauf=tage,
        sperre_ab=sperre_ab,
    )


def heute() -> date:
    return datetime.now(timezone.utc).date()


async def fuer_org(db: AsyncSession, org_id: uuid.UUID) -> OrganizationPlan | None:
    return await db.get(OrganizationPlan, org_id)


async def nutzung(db: AsyncSession, org_id: uuid.UUID) -> Nutzung:
    fahrzeuge = (
        await db.execute(
            select(func.count(Vehicle.id)).where(Vehicle.org_id == org_id)
        )
    ).scalar_one()
    planer = (
        await db.execute(
            select(func.count(UserOrganization.user_id)).where(
                UserOrganization.organization_id == org_id,
                UserOrganization.role.in_(PLANER_ROLLEN),
            )
        )
    ).scalar_one()
    tracker = (
        await db.execute(
            select(func.count(Ortungsgeraet.id)).where(
                Ortungsgeraet.organization_id == org_id, Ortungsgeraet.aktiv.is_(True)
            )
        )
    ).scalar_one()
    return Nutzung(fahrzeuge=fahrzeuge, planer=planer, tracker=tracker)


async def nutzung_alle(db: AsyncSession) -> dict[uuid.UUID, Nutzung]:
    """Nutzung aller Organisationen in drei Abfragen statt drei je Zeile."""
    fahrzeuge = dict(
        (
            await db.execute(
                select(Vehicle.org_id, func.count(Vehicle.id))
                .where(Vehicle.org_id.is_not(None))
                .group_by(Vehicle.org_id)
            )
        ).all()
    )
    planer = dict(
        (
            await db.execute(
                select(UserOrganization.organization_id, func.count(UserOrganization.user_id))
                .where(UserOrganization.role.in_(PLANER_ROLLEN))
                .group_by(UserOrganization.organization_id)
            )
        ).all()
    )
    tracker = dict(
        (
            await db.execute(
                select(Ortungsgeraet.organization_id, func.count(Ortungsgeraet.id))
                .where(Ortungsgeraet.aktiv.is_(True))
                .group_by(Ortungsgeraet.organization_id)
            )
        ).all()
    )
    return {
        org_id: Nutzung(
            fahrzeuge=fahrzeuge.get(org_id, 0),
            planer=planer.get(org_id, 0),
            tracker=tracker.get(org_id, 0),
        )
        for org_id in set(fahrzeuge) | set(planer) | set(tracker)
    }


async def ist_gesperrt(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Ob die Organisation nur noch lesen darf.

    Liest frisch und ohne Nutzung zu zählen — das kostet genau eine Abfrage
    nach Primärschlüssel und steht deshalb vor jedem schreibenden Aufruf."""
    zeile = await fuer_org(db, org_id)
    if zeile is None or zeile.valid_until is None:
        return False
    return zustand(zeile, Nutzung(0, 0), heute()).gesperrt


GESPERRT_TEXT = (
    "Der Zeitraum dieses Pakets ist abgelaufen. Die Organisation ist nur noch "
    "lesbar; alle Daten bleiben erhalten. Zum Verlängern bitte "
    "anfrage@convoyplan.de kontaktieren."
)
