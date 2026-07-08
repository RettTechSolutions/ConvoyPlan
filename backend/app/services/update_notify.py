"""
Update-Benachrichtigungen (Hintergrund-Task).

Zwei Fälle, je nach Update-Modus (Admin → Software-Update):

1. Modus "notify": Der Updater installiert nichts automatisch. Dieser Task
   prüft periodisch den Update-Status des aktiven Kanals und schickt allen
   Superadmins einmalig eine E-Mail, sobald ein neues Update VERFÜGBAR ist.
2. Modus "auto" + Option "notify_on_auto": Updates werden automatisch
   installiert; die Superadmins erhalten einmalig eine E-Mail, NACHDEM eine
   neue Version installiert wurde (erkannt am Wechsel der deployten Version,
   ganz ohne GitHub-Aufrufe).

Beide Fälle deduplizieren über system_settings — pro Ziel bzw. installiertem
Stand genau eine Mail, auch über Backend-Neustarts hinweg. Schlägt der Versand
fehl (z. B. SMTP nicht konfiguriert), wird der Merker NICHT gesetzt und der
nächste Lauf versucht es erneut.
"""

from __future__ import annotations

import asyncio
import html
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.settings import SystemSetting
from app.models.user import User
from app.services.email import send_update_notification
from app.services.update_check import (
    fetch_update_state,
    read_deployed,
    resolve_mode,
    resolve_notify_on_auto,
)

logger = logging.getLogger(__name__)

_LAST_NOTIFIED_KEY = "update.last_notified_target"
_LAST_INSTALLED_KEY = "update.last_installed_notified"


async def update_notify_loop() -> None:
    """Background loop started from the app lifespan. Sleeps first, so tests
    and short-lived processes never hit GitHub or SMTP on startup."""
    if not settings.update_check_enabled:
        return
    interval = max(60, settings.update_notify_interval)
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                await check_and_notify_once(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Update-Benachrichtigung fehlgeschlagen — nächster Versuch in %ss", interval)


async def check_and_notify_once(db: AsyncSession) -> bool:
    """One notification pass. Returns True when an email was sent."""
    mode, _ = await resolve_mode(db)
    if mode == "notify":
        return await _notify_update_available(db)

    # Modus "auto": optional über erfolgte automatische Installation informieren.
    notify_on_auto, _src = await resolve_notify_on_auto(db)
    if notify_on_auto:
        return await _notify_update_installed(db)
    return False


async def _notify_update_available(db: AsyncSession) -> bool:
    """Modus "notify": E-Mail, sobald ein Update VERFÜGBAR ist (einmal pro Ziel)."""
    state = await fetch_update_state(db)
    if not (state.get("update_available") and state.get("remote_sha")):
        return False

    target = f"{state['channel']}:{state['remote_sha']}"
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == _LAST_NOTIFIED_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting and setting.value == target:
        return False  # für dieses Ziel wurde bereits benachrichtigt

    subject, body = _render(state)
    sent = await _send_to_superadmins(db, subject, body, context=f"Update verfügbar ({target})")
    if sent == 0:
        # Nichts zugestellt (z. B. SMTP nicht konfiguriert) → Merker nicht
        # setzen, damit der nächste Lauf es erneut versucht.
        return False

    if setting:
        setting.value = target
    else:
        db.add(SystemSetting(key=_LAST_NOTIFIED_KEY, value=target))
    await db.commit()
    logger.info("Update-Benachrichtigung für %s an %d Superadmin(s) versendet", target, sent)
    return True


async def _notify_update_installed(db: AsyncSession) -> bool:
    """Modus "auto" + notify_on_auto: E-Mail, nachdem ein Update INSTALLIERT
    wurde — erkannt am Wechsel der deployten Version (status.json des
    Updaters), ohne GitHub-Aufrufe. Einmal pro installiertem Stand."""
    deployed_sha, deployed_at = read_deployed()
    if not deployed_sha:
        return False

    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == _LAST_INSTALLED_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        # Erstlauf (Option gerade aktiviert): aktuellen Stand still als
        # Basislinie vermerken — keine Mail für ein längst installiertes Update.
        db.add(SystemSetting(key=_LAST_INSTALLED_KEY, value=deployed_sha))
        await db.commit()
        return False
    if setting.value == deployed_sha:
        return False  # nichts Neues installiert

    subject, body = _render_installed(
        previous=setting.value, deployed=deployed_sha, deployed_at=deployed_at
    )
    sent = await _send_to_superadmins(
        db, subject, body, context=f"Update installiert ({deployed_sha[:7]})"
    )
    if sent == 0:
        return False  # nächster Lauf versucht es erneut

    setting.value = deployed_sha
    await db.commit()
    logger.info(
        "Installations-Benachrichtigung für %s an %d Superadmin(s) versendet",
        deployed_sha[:7], sent,
    )
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
            logger.warning("Update-Mail an %s fehlgeschlagen: %s", email_addr, exc)
    return sent


def _render(state: dict) -> tuple[str, str]:
    """(subject, html_body) for the update-available notification email."""
    channel = state.get("channel", "stable")
    if channel == "beta" or not state.get("latest_release"):
        available = state.get("remote_sha") or "unbekannt"
    else:
        available = f"{state['latest_release']} ({state.get('remote_sha')})"

    subject = f"ConvoyPlan-Update verfügbar: {available}"
    deployed = state.get("deployed_sha") or "unbekannt"
    base_url = settings.app_base_url.rstrip("/")

    body = f"""\
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;">
  <h2 style="margin-bottom:.25rem;">Neues Update verf&uuml;gbar</h2>
  <p>F&uuml;r diese ConvoyPlan-Instanz steht im Kanal
     <strong>{html.escape(channel)}</strong> ein Update bereit:</p>
  <table style="border-collapse:collapse;">
    <tr><td style="padding:.2rem .75rem .2rem 0;">Installiert:</td>
        <td><code>{html.escape(str(deployed)[:7])}</code></td></tr>
    <tr><td style="padding:.2rem .75rem .2rem 0;">Verf&uuml;gbar:</td>
        <td><code>{html.escape(str(available))}</code></td></tr>
  </table>
  <p>Der Update-Modus dieser Instanz steht auf <strong>&bdquo;Nur
     benachrichtigen&ldquo;</strong> &mdash; es wird nichts automatisch
     installiert. Zum Installieren im Admin-Bereich unter
     <a href="{html.escape(base_url)}/admin">Software-Update</a>
     auf &bdquo;Jetzt updaten&ldquo; klicken.</p>
  <p style="color:#777;font-size:12px;">Diese Mail wird pro Update-Ziel genau
     einmal an alle Superadmins versendet.</p>
</body></html>"""
    return subject, body


def _render_installed(previous: str, deployed: str, deployed_at: str | None) -> tuple[str, str]:
    """(subject, html_body) for the update-installed notification email."""
    subject = f"ConvoyPlan-Update installiert: {deployed[:7]}"
    base_url = settings.app_base_url.rstrip("/")
    version = settings.app_version or ""
    version_row = ""
    if version:
        version_row = (
            '<tr><td style="padding:.2rem .75rem .2rem 0;">Version:</td>'
            f"<td><code>{html.escape(version)}</code></td></tr>"
        )
    when = f" ({html.escape(deployed_at)})" if deployed_at else ""

    body = f"""\
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;">
  <h2 style="margin-bottom:.25rem;">Update automatisch installiert</h2>
  <p>Diese ConvoyPlan-Instanz wurde automatisch aktualisiert{when}:</p>
  <table style="border-collapse:collapse;">
    {version_row}
    <tr><td style="padding:.2rem .75rem .2rem 0;">Neuer Stand:</td>
        <td><code>{html.escape(deployed[:7])}</code></td></tr>
    <tr><td style="padding:.2rem .75rem .2rem 0;">Vorher:</td>
        <td><code>{html.escape(previous[:7])}</code></td></tr>
  </table>
  <p>Details und Log im Admin-Bereich unter
     <a href="{html.escape(base_url)}/admin">Software-Update</a>.</p>
  <p style="color:#777;font-size:12px;">Diese Mail wird pro installiertem Stand
     genau einmal an alle Superadmins versendet (Option &bdquo;Bei
     automatischen Updates benachrichtigen&ldquo;).</p>
</body></html>"""
    return subject, body
