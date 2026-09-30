"""
Ablauf des Lizenzschlüssels ankündigen (Hintergrund-Task).

Nach ``expires`` fällt die Instanz in den Demo-Modus, und schreiben kann dann
niemand mehr — mitten im Betrieb. Bisher merkte das erst, wer den Banner sah.
Der Schlüssel trägt sein Ablaufdatum aber selbst; die Instanz kann also
vorher Bescheid sagen, ohne irgendwo nachzufragen.

Drei Stufen, jede genau einmal je Schlüssel an alle Superadmins:

- ``30``: noch höchstens 30 Tage,
- ``7``: noch höchstens 7 Tage (der letzte gültige Tag zählt mit),
- ``abgelaufen``: seit dem Ablauf, aber nur in den ersten 30 Tagen danach —
  eine Instanz, die seit Monaten im Demo-Modus steht, bekommt nach einem
  Update keine späte Mail.

Wer erst kurz vor Ablauf startet, bekommt nur die aktuelle Stufe, nicht die
verpassten davor. Der Merker in ``system_settings`` hängt am Ablaufdatum: ein
neuer Schlüssel hat ein neues Datum und fängt wieder von vorn an. Wie bei
``update_notify``: schlägt der Versand fehl (kein SMTP), bleibt der Merker
stehen und der nächste Lauf versucht es erneut.

Die Entscheidung (``faellige_stufe``) steht getrennt von Datenbank und
Versand und wird ohne beides geprüft.
"""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.settings import SystemSetting
from app.models.user import User
from app.services.email import send_update_notification
from app.services.license import LicenseInfo

logger = logging.getLogger(__name__)

MERKER_KEY = "license.expiry_notified"

# Ab wann gewarnt wird. Muss zu WARN_TAGE im Frontend passen (Admin-Portal,
# Banner), sonst kommt die Mail vor oder nach dem Hinweis auf der Seite.
WARN_TAGE = 30
DRINGEND_TAGE = 7
# Wie lange nach dem Ablauf die Stufe „abgelaufen“ noch gemeldet wird.
NACHLAUF_TAGE = 30

_RANG = {"30": 1, "7": 2, "abgelaufen": 3}


def ablaufdatum(info: LicenseInfo) -> date | None:
    """Ablaufdatum eines Schlüssels, der für diese Instanz gilt oder nur wegen
    seines Ablaufs nicht mehr gilt. Sonst None — ein Schlüssel mit falscher
    Signatur oder für eine andere Installation hat kein Ablaufdatum, das hier
    jemanden interessiert."""
    ablauf = info.expires_date
    if ablauf is None:
        return None
    if not info.valid and not info.expired:
        return None
    return ablauf


def tage_bis_ablauf(info: LicenseInfo, heute: date) -> int | None:
    """Tage bis zum letzten gültigen Tag; 0 = heute letzter Tag, negativ = abgelaufen."""
    ablauf = ablaufdatum(info)
    return None if ablauf is None else (ablauf - heute).days


def stufe(ablauf: date, heute: date) -> str | None:
    """Welche Warnstufe gerade gilt; None = (noch/nicht mehr) keine."""
    tage = (ablauf - heute).days
    if tage < 0:
        return "abgelaufen" if -tage <= NACHLAUF_TAGE else None
    if tage <= DRINGEND_TAGE:
        return "7"
    if tage <= WARN_TAGE:
        return "30"
    return None


def faellige_stufe(merker: str | None, ablauf: date, heute: date) -> str | None:
    """Die Stufe, die jetzt zu melden ist, oder None.

    ``merker`` ist der gespeicherte Stand ``<ablaufdatum>:<stufe>``. Gemeldet
    wird nur, was für dieses Ablaufdatum noch nicht (oder nur schwächer)
    gemeldet wurde."""
    aktuell = stufe(ablauf, heute)
    if aktuell is None:
        return None
    if merker:
        datum, _, gemeldet = merker.partition(":")
        if datum == ablauf.isoformat() and _RANG.get(gemeldet, 0) >= _RANG[aktuell]:
            return None
    return aktuell


async def lizenz_ablauf_loop() -> None:
    """Background loop started from the app lifespan. Sleeps first, so tests
    and short-lived processes never send mail on startup."""
    interval = max(60, settings.license_expiry_check_interval)
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                await pruefen_und_melden(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lizenzablauf-Prüfung fehlgeschlagen — nächster Versuch in %ss", interval)


async def pruefen_und_melden(db: AsyncSession, heute: date | None = None) -> bool:
    """Ein Durchgang. True, wenn eine Mail zugestellt wurde."""
    # Spät importiert wie in instance.aktuelle_lizenz selbst: instance zieht
    # config und Modelle, und dieses Modul wird schon beim App-Start geladen.
    from app.services.instance import aktuelle_lizenz, get_or_create_instance_id

    heute = heute or datetime.now(timezone.utc).date()
    info = await aktuelle_lizenz(db)
    ablauf = ablaufdatum(info)
    if ablauf is None:
        return False

    result = await db.execute(select(SystemSetting).where(SystemSetting.key == MERKER_KEY))
    setting = result.scalar_one_or_none()
    faellig = faellige_stufe(setting.value if setting else None, ablauf, heute)
    if faellig is None:
        return False

    instance_id = await get_or_create_instance_id(db)
    subject, body = _render(info, ablauf, faellig, instance_id, heute)
    sent = await _send_to_superadmins(db, subject, body, context=f"Lizenzablauf {ablauf} ({faellig})")
    if sent == 0:
        return False  # nächster Lauf versucht es erneut

    wert = f"{ablauf.isoformat()}:{faellig}"
    if setting:
        setting.value = wert
    else:
        db.add(SystemSetting(key=MERKER_KEY, value=wert))
    await db.commit()
    logger.info("Lizenzablauf %s (Stufe %s) an %d Superadmin(s) gemeldet", ablauf, faellig, sent)
    return True


async def _send_to_superadmins(db: AsyncSession, subject: str, body: str, context: str) -> int:
    """Send an email to every active superadmin; returns the delivered count."""
    result = await db.execute(
        select(User).where(User.is_superadmin.is_(True), User.is_active.is_(True))
    )
    recipients = [u.email for u in result.scalars().all() if u.email]
    if not recipients:
        logger.warning("%s, aber kein Superadmin mit E-Mail-Adresse vorhanden", context)
        return 0

    sent = 0
    for email_addr in recipients:
        try:
            await send_update_notification(db, email_addr, subject, body)
            sent += 1
        except Exception as exc:
            # Ein Empfänger darf die übrigen nicht blockieren; Details nur ins Log.
            logger.warning("Lizenzablauf-Mail an %s fehlgeschlagen: %s", email_addr, exc)
    return sent


def _datum(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _render(info: LicenseInfo, ablauf: date, faellig: str, instance_id: str, heute: date) -> tuple[str, str]:
    """(subject, html_body) der Mail an die Superadmins."""
    tage = (ablauf - heute).days
    if faellig == "abgelaufen":
        subject = f"ConvoyPlan-Lizenz abgelaufen am {_datum(ablauf)}"
        kopf = "Lizenz abgelaufen"
        lage = (
            f"Der Lizenzschl&uuml;ssel dieser Instanz ist am <strong>{_datum(ablauf)}</strong> "
            "abgelaufen. Die Instanz l&auml;uft jetzt im <strong>Demo-Modus</strong>: "
            "Lesen geht weiter, Schreiben ist gesperrt."
        )
    else:
        wann = "heute" if tage == 0 else "morgen" if tage == 1 else f"in {tage} Tagen"
        subject = f"ConvoyPlan-Lizenz läuft {wann} ab ({_datum(ablauf)})"
        kopf = "Lizenz l&auml;uft bald ab"
        lage = (
            f"Der Lizenzschl&uuml;ssel dieser Instanz gilt bis einschlie&szlig;lich "
            f"<strong>{_datum(ablauf)}</strong> ({html.escape(wann)}). Danach f&auml;llt die "
            "Instanz in den <strong>Demo-Modus</strong>: Lesen geht weiter, Schreiben ist gesperrt."
        )

    base_url = settings.app_base_url.rstrip("/")
    if settings.license_key:
        # LICENSE_KEY aus der Umgebung schlägt den gespeicherten Schlüssel —
        # ein Eintrag im Portal bliebe hier wirkungslos.
        eintragen = (
            "Der Schl&uuml;ssel dieser Instanz steht in der Umgebungsvariable "
            "<code>LICENSE_KEY</code>: dort ersetzen und das Backend neu starten."
        )
    else:
        eintragen = (
            "Den neuen Schl&uuml;ssel im Admin-Bereich unter "
            f'<a href="{html.escape(base_url)}/admin">System &rarr; Lizenz</a> '
            "eintragen &mdash; er gilt sofort, ohne Neustart."
        )
    kunde = ""
    if info.customer:
        kunde = (
            '<tr><td style="padding:.2rem .75rem .2rem 0;">Lizenziert f&uuml;r:</td>'
            f"<td>{html.escape(info.customer)}</td></tr>"
        )

    body = f"""\
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;">
  <h2 style="margin-bottom:.25rem;">{kopf}</h2>
  <p>{lage}</p>
  <table style="border-collapse:collapse;">
    {kunde}
    <tr><td style="padding:.2rem .75rem .2rem 0;">Instance ID:</td>
        <td><code>{html.escape(instance_id)}</code></td></tr>
  </table>
  <p><strong>Was zu tun ist:</strong> beim Anbieter einen neuen Schl&uuml;ssel
     anfordern und dabei die Instance ID angeben. {eintragen}</p>
  <p style="color:#777;font-size:12px;">Diese Mail geht 30 und 7 Tage vor dem
     Ablauf sowie beim Ablauf je einmal an alle Superadmins.</p>
</body></html>"""
    return subject, body
