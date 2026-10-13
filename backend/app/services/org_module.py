"""Module je Organisation: was der Betreiber einer Organisation freischaltet.

Auf dem Hosting-Server bucht eine Organisation nicht jede Funktion mit — ein
Tracker-Paket, eine Aktionsseite für einen Hilfskonvoi, die KI-Schnittstelle
sind Zusagen des Betreibers (Betrieb, Support, Datenschutzprüfung), keine
Selbstverständlichkeit. Der Superadmin schaltet sie deshalb je Organisation
frei; erst dann ist der Reiter im Org-Admin bedienbar.

**Keine Zeile heißt Standard der Betriebsart** (``standard``): selbst gehostet
frei, auf dem Hosting-Server gesperrt. Selbst gehostet ist der Betreiber
meist auch der Org-Admin, und unter AGPL wäre eine Sperre dort ohnehin nur
ein Zaun für Ehrliche — der Schalter ist da, aber er steht offen. Die
Migration (``0068``) schreibt für jede bestehende Organisation jedes Modul
ausdrücklich frei: ein Update nimmt keiner Organisation etwas weg, auch nicht
auf dem Hosting-Server. **Demo-Organisationen** bekommen immer alles — sie
sind zum Zeigen da.

Ein gesperrtes Modul wirkt nicht nur auf den Reiter. Maßgeblich ist das
Backend, sonst wäre die Sperre einen Klick in den Entwicklertools entfernt:

- ``org_router`` des Moduls antwortet 403 (``api/deps.require_modul``).
- ``tracker``: Geräte bekommen ``schweigen`` (``geraete._anweisung``), wie bei
  der Plansperre; die Konvoi-Ansicht zeigt keine Tracker.
- ``aktionsseiten``: die öffentliche Seite ist dieselbe 404 wie abgeschaltet,
  und es wird kein Positionsverlauf mehr aufgezeichnet.
- ``branding``: die Organisation erscheint im Plattform-Branding. Ihre
  Einstellungen bleiben gespeichert und gelten nach der Freigabe wieder.
- ``ki``: die MCP-Richtlinie gilt als aus (``org_mcp_policy.fuer_org``),
  bestehende Verbindungen kommen beim nächsten Aufruf nicht mehr weiter.

Gelöscht wird beim Sperren nichts. Mitglieder, GPS-Freigaben, Leitstellen und
der Datenexport sind keine Module: ohne sie lässt sich nicht planen, und der
Export ist ein Recht der Organisation, kein Paket.

Die Regel (``gilt``) steht ohne Datenbank und wird von
``tests/test_org_module.py`` so geprüft.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_module import OrganizationModule
from app.models.organization import Organization
from app.services import betriebsart


@dataclass(frozen=True)
class Modul:
    schluessel: str
    label: str
    beschreibung: str


TRACKER = "tracker"
AKTIONSSEITEN = "aktionsseiten"
BRANDING = "branding"
KI = "ki"

MODULE: dict[str, Modul] = {
    m.schluessel: m
    for m in (
        Modul(TRACKER, "Tracker", "Feste Ortungsgeräte an Fahrzeugen"),
        Modul(AKTIONSSEITEN, "Aktionsseiten", "Konvois öffentlich zeigen (verzögert, vergröbert)"),
        Modul(BRANDING, "Branding", "Eigenes Logo und eigene Farben"),
        Modul(KI, "KI-Zugriff", "Zugriff über die MCP-Schnittstelle"),
    )
}


def standard(art: str | None = None) -> bool:
    """Was ohne Entscheidung des Betreibers gilt."""
    return (art or betriebsart.aktuell()) != betriebsart.HOSTING


def gilt(gespeichert: bool | None, *, demo: bool = False, art: str | None = None) -> bool:
    """Die Regel: Demo immer frei, sonst die Zeile, sonst der Standard."""
    if demo:
        return True
    if gespeichert is not None:
        return gespeichert
    return standard(art)


async def fuer_org(db: AsyncSession, org_id: uuid.UUID) -> dict[str, bool]:
    """Alle Module einer Organisation, je Schlüssel frei oder gesperrt."""
    return (await fuer_orgs(db, [org_id])).get(org_id, {m: standard() for m in MODULE})


async def fuer_orgs(
    db: AsyncSession, org_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, bool]]:
    """Die Module mehrerer Organisationen in zwei Abfragen statt zwei je Zeile."""
    if not org_ids:
        return {}
    demo = dict(
        (
            await db.execute(
                select(Organization.id, Organization.is_demo).where(Organization.id.in_(org_ids))
            )
        ).all()
    )
    zeilen = (
        await db.execute(
            select(OrganizationModule).where(OrganizationModule.organization_id.in_(org_ids))
        )
    ).scalars().all()
    gespeichert: dict[tuple[uuid.UUID, str], bool] = {
        (z.organization_id, z.modul): z.freigegeben for z in zeilen
    }
    art = betriebsart.aktuell()
    return {
        org_id: {
            m: gilt(gespeichert.get((org_id, m)), demo=bool(demo.get(org_id)), art=art)
            for m in MODULE
        }
        for org_id in org_ids
    }


async def freigegeben(db: AsyncSession, org_id: uuid.UUID, modul: str) -> bool:
    """Ob *modul* für die Organisation frei ist. Liest frisch — ein Entzug wirkt sofort."""
    return (await fuer_org(db, org_id))[modul]


async def setzen(
    db: AsyncSession,
    org_id: uuid.UUID,
    werte: dict[str, bool],
    actor_id: uuid.UUID | None = None,
) -> None:
    """Entscheidungen des Betreibers schreiben. Committet nicht.

    Unbekannte Schlüssel fallen still heraus, wie bei der MCP-Richtlinie.
    Geschrieben wird immer ausdrücklich, auch wenn der Wert dem Standard
    entspricht: wer auf dem Hosting-Server freigibt, meint diese
    Organisation, nicht „was auch immer die Betriebsart morgen sagt"."""
    vorhanden = {
        z.modul: z
        for z in (
            await db.execute(
                select(OrganizationModule).where(OrganizationModule.organization_id == org_id)
            )
        ).scalars().all()
    }
    for modul, wert in werte.items():
        if modul not in MODULE:
            continue
        zeile = vorhanden.get(modul)
        if zeile is None:
            zeile = OrganizationModule(organization_id=org_id, modul=modul)
            db.add(zeile)
        zeile.freigegeben = bool(wert)
        zeile.updated_by_id = actor_id


def gesperrt_text(modul: str) -> str:
    label = MODULE[modul].label if modul in MODULE else modul
    return (
        f"Das Modul „{label}“ ist für diese Organisation nicht freigeschaltet. "
        "Freischalten kann es der Betreiber dieser Instanz."
    )
