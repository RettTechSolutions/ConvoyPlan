"""
Update-Benachrichtigung für den Modus "notify".

Steht der Update-Modus (Admin → Software-Update) auf "Nur benachrichtigen",
installiert der Updater nichts automatisch. Stattdessen prüft dieser
Hintergrund-Task periodisch den Update-Status des aktiven Kanals und schickt
allen Superadmins einmalig eine E-Mail, sobald ein neues Update verfügbar ist.

Dedupliziert über system_settings["update.last_notified_target"]
("<kanal>:<sha>") — pro Update-Ziel genau eine Mail, auch über
Backend-Neustarts hinweg. Schlägt der Versand fehl (z. B. SMTP nicht
konfiguriert), wird der Merker NICHT gesetzt und der nächste Lauf versucht es
erneut.
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
from app.services.update_check import fetch_update_state, resolve_mode

logger = logging.getLogger(__name__)

_LAST_NOTIFIED_KEY = "update.last_notified_target"


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
    if mode != "notify":
        return False

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

    result = await db.execute(
        select(User).where(User.is_superadmin.is_(True), User.is_active.is_(True))
    )
    recipients = [u.email for u in result.scalars().all() if u.email]
    if not recipients:
        logger.warning("Update verfügbar (%s), aber kein Superadmin mit E-Mail-Adresse vorhanden", target)
        return False

    subject, body = _render(state)
    sent = 0
    for email_addr in recipients:
        try:
            await send_update_notification(db, email_addr, subject, body)
            sent += 1
        except Exception as exc:
            # Ein Empfänger darf die übrigen nicht blockieren; Details nur ins Log.
            logger.warning("Update-Mail an %s fehlgeschlagen: %s", email_addr, exc)

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


def _render(state: dict) -> tuple[str, str]:
    """(subject, html_body) for the notification email."""
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
