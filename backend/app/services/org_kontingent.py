"""Wie viele Organisationen auf dieser Instanz angelegt werden dürfen.

Der Lizenzschlüssel trägt ab Payload v2 ``max_orgs``. Das ist die einzige
harte Grenze, die ein Schlüssel zieht, und sie greift nur an **einer** Stelle:
beim Anlegen einer Organisation. Eine bestehende Organisation läuft immer
weiter, auch wenn die Instanz inzwischen über der Grenze liegt — das Anlegen
ist nie dringend, der Betrieb einer Organisation im Einsatz schon.

Die Entscheidung (``grenze``, ``darf_anlegen``) steht getrennt von Datenbank
und Lizenzprüfung und wird von ``tests/test_lizenz_organisationsgrenze.py``
ohne beides geprüft.

Welche Grenze gilt:

- **Altschlüssel** (ohne ``v``) — unbegrenzt. Sie wurden ausgestellt, bevor
  es die Grenze gab, und „bereits ausgestellte Schlüssel bleiben gültig"
  heißt auch: mit dem, was sie bisher erlaubt haben.
- **v2 mit ``max_orgs``** — genau das; ``0`` im Schlüssel heißt unbegrenzt.
- **Vertragsende überschritten** (``contract_until``) — für *neue*
  Organisationen fällt die Instanz auf eine zurück, die kostenlose Stufe.
  Kein Demo-Modus, nichts wird abgeschaltet.
- **Keine gültige Lizenz** — eine. Das trifft praktisch nur die
  Ersteinrichtung (``/api/setup`` ist vom Lizenzwächter ausgenommen); jedes
  andere Anlegen scheitert im Demo-Modus schon am Wächter.

Demo-Organisationen (``is_demo``) zählen nicht: sie entstehen je Besucher
und verschwinden wieder, und die öffentliche Demo darf nicht die Organisation
eines Kunden verdrängen.
"""
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.services.instance import aktuelle_lizenz
from app.services.license import LicenseInfo

# Die kostenlose Stufe: eine Produktivinstallation je Organisation.
KOSTENLOS = 1


def _datum(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def vertrag_beendet(info: LicenseInfo, heute: date) -> bool:
    """Ob das Vertragsende im Schlüssel überschritten ist.

    Ein unlesbares Datum zählt als *nicht* beendet. Es kann nur aus dem
    eigenen Lizenzmanager stammen, und wer sich dort vertippt, soll seinem
    Kunden nicht das Anlegen sperren."""
    ende = _datum(info.contract_until)
    return ende is not None and ende < heute


def grenze(info: LicenseInfo, heute: date) -> int | None:
    """Höchstzahl an Organisationen; None = unbegrenzt."""
    if not info.valid:
        return KOSTENLOS
    if vertrag_beendet(info, heute):
        return KOSTENLOS
    return info.max_orgs


def darf_anlegen(vorhanden: int, max_orgs: int | None) -> bool:
    return max_orgs is None or vorhanden < max_orgs


async def anzahl(db: AsyncSession) -> int:
    """Organisationen, die gegen die Grenze zählen."""
    return (
        await db.execute(
            select(func.count(Organization.id)).where(Organization.is_demo.is_(False))
        )
    ).scalar_one()


def _heute() -> date:
    return datetime.now(timezone.utc).date()


async def stand(db: AsyncSession) -> tuple[int, int | None]:
    """(vorhanden, grenze) — für die Anzeige im Adminportal."""
    return await anzahl(db), grenze(await aktuelle_lizenz(db), _heute())


async def pruefe_anlegen(db: AsyncSession) -> None:
    """Vor dem Anlegen einer Organisation aufrufen; wirft 402 bei voller Grenze.

    402 wie der Demo-Modus: es ist eine Frage der Lizenz, nicht der Rechte,
    und das Frontend behandelt beide gleich."""
    vorhanden, max_orgs = await stand(db)
    if darf_anlegen(vorhanden, max_orgs):
        return
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"Die Lizenz dieser Installation erlaubt {max_orgs} "
            f"Organisation{'en' if max_orgs != 1 else ''}, angelegt "
            f"{'sind' if vorhanden != 1 else 'ist'} {vorhanden}. Für weitere "
            "Organisationen bitte einen erweiterten Lizenzschlüssel anfragen "
            "(anfrage@convoyplan.de)."
        ),
    )
