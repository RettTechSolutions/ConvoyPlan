"""
Deploy-Alert-Benachrichtigung (Hintergrund-Task).

Der Updater (``docker/updater/update-images.sh`` / ``update.sh``) und der
Backend-Entrypoint (``backend/docker-entrypoint.sh``) legen bei einem
problematischen Deploy eine Alert-Datei auf dem geteilten Volume ab
(``/update_status/deploy_alert.json``):

* ``deploy_rolled_back``        — ein neues Backend-Image wurde nicht gesund und
                                  der Updater hat automatisch auf die vorige
                                  Version zurückgerollt (Self-Healing).
* ``deploy_failed``             — nicht gesund UND Rollback fehlgeschlagen.
* ``boot_image_older_than_db``  — der Entrypoint hat den Start abgebrochen, weil
                                  das Image älter ist als das DB-Schema.
* ``boot_migration_failed``     — eine Migration ist beim Start fehlgeschlagen.

Dieser Task liest die Datei, benachrichtigt alle Superadmins per E-Mail und
merkt sich die Alert-ID in ``system_settings``, sodass pro Ereignis genau eine
Mail rausgeht — auch über Backend-Neustarts und den Rollback hinweg (der wieder
gesunde Backend-Container verschickt die Mail über den fehlgeschlagenen Deploy).

Bewusst kein Gate auf ``update_check_enabled``: der Alert ist ein Betriebs-/
Störungshinweis, kein Update-Check. Ist SMTP nicht konfiguriert, wird der Merker
NICHT gesetzt und der nächste Lauf versucht es erneut.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.settings import SystemSetting
from app.models.user import User
from app.services.email import send_update_notification

logger = logging.getLogger(__name__)

ALERT_FILE = "/update_status/deploy_alert.json"
_LAST_ALERT_KEY = "deploy.last_alert_id"
_POLL_INTERVAL = 60  # seconds

_EVENT_TITLES = {
    "deploy_rolled_back": "Automatischer Rollback nach fehlgeschlagenem Update",
    "deploy_failed": "Update fehlgeschlagen — manueller Eingriff nötig",
    "boot_image_older_than_db": "Backend-Start abgebrochen: Image älter als DB-Schema",
    "boot_migration_failed": "Backend-Start abgebrochen: Migration fehlgeschlagen",
}


async def deploy_alert_loop() -> None:
    """Background loop started from the app lifespan. Sleeps first so short-lived
    processes and tests never touch SMTP on startup."""
    while True:
        await asyncio.sleep(_POLL_INTERVAL)
        try:
            async with AsyncSessionLocal() as db:
                await check_deploy_alert_once(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Deploy-Alert-Prüfung fehlgeschlagen — nächster Versuch in %ss", _POLL_INTERVAL)


def _read_alert() -> dict | None:
    """Read and validate the alert marker; None when absent or malformed."""
    try:
        with open(ALERT_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("deploy_alert.json unlesbar (%s) — ignoriert", exc)
        return None
    if isinstance(data, dict) and data.get("id"):
        return data
    return None


async def check_deploy_alert_once(db: AsyncSession) -> bool:
    """One pass. Returns True when an email was sent for a new alert."""
    alert = _read_alert()
    if not alert:
        return False

    alert_id = str(alert.get("id"))
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == _LAST_ALERT_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting and setting.value == alert_id:
        return False  # für dieses Ereignis wurde bereits benachrichtigt

    subject, body = _render_alert(alert)
    sent = await _send_to_superadmins(db, subject, body)
    if sent == 0:
        # Nichts zugestellt (z. B. SMTP nicht konfiguriert) → Merker nicht
        # setzen, damit der nächste Lauf es erneut versucht.
        return False

    if setting:
        setting.value = alert_id
    else:
        db.add(SystemSetting(key=_LAST_ALERT_KEY, value=alert_id))
    await db.commit()
    logger.info("Deploy-Alert %s an %d Superadmin(s) versendet", alert_id, sent)
    return True


async def _send_to_superadmins(db: AsyncSession, subject: str, body: str) -> int:
    """Send to every active superadmin; returns the delivered count."""
    result = await db.execute(
        select(User).where(User.is_superadmin.is_(True), User.is_active.is_(True))
    )
    recipients = [u.email for u in result.scalars().all() if u.email]
    if not recipients:
        logger.warning("Deploy-Alert, aber kein Superadmin mit E-Mail-Adresse vorhanden")
        return 0

    sent = 0
    for email_addr in recipients:
        try:
            await send_update_notification(db, email_addr, subject, body)
            sent += 1
        except Exception as exc:
            logger.warning("Deploy-Alert-Mail an %s fehlgeschlagen: %s", email_addr, exc)
    return sent


def _render_alert(alert: dict) -> tuple[str, str]:
    """(subject, html_body) for a deploy-alert email."""
    event = str(alert.get("event", ""))
    title = _EVENT_TITLES.get(event, "ConvoyPlan Deploy-Hinweis")
    detail = html.escape(str(alert.get("detail", "")))
    at = html.escape(str(alert.get("at", "")))
    failed = html.escape(str(alert.get("failed_image") or alert.get("image") or "unbekannt"))
    restored = html.escape(str(alert.get("restored_image") or ""))
    base_url = settings.app_base_url.rstrip("/")

    restored_row = ""
    if restored:
        restored_row = (
            '<tr><td style="padding:.2rem .75rem .2rem 0;">Wiederhergestellt:</td>'
            f"<td><code>{restored}</code></td></tr>"
        )

    subject = f"ConvoyPlan: {title}"
    body = f"""\
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;">
  <h2 style="margin-bottom:.25rem;">{html.escape(title)}</h2>
  <p>{detail}</p>
  <table style="border-collapse:collapse;">
    <tr><td style="padding:.2rem .75rem .2rem 0;">Zeitpunkt:</td>
        <td><code>{at}</code></td></tr>
    <tr><td style="padding:.2rem .75rem .2rem 0;">Betroffenes Image:</td>
        <td><code>{failed}</code></td></tr>
    {restored_row}
  </table>
  <p>Details und Update-Log im Admin-Bereich unter
     <a href="{html.escape(base_url)}/admin">Software-Update</a>.</p>
  <p style="color:#777;font-size:12px;">Diese Mail wird pro Ereignis genau einmal
     an alle Superadmins versendet.</p>
</body></html>"""
    return subject, body
