"""
Async email service backed by SMTP settings stored in system_settings.

Settings keys:
  smtp.host        — SMTP server hostname
  smtp.port        — port (default: 587)
  smtp.username    — login username (leave empty for anonymous)
  smtp.password    — login password
  smtp.from_email  — From address
  smtp.from_name   — From display name (default: ConvoyPlan)
  smtp.use_tls     — "true" = STARTTLS on port 587 (default), "ssl" = SSL on port 465, "false" = plaintext

Template keys (stored in system_settings, editable by superadmin):
  email.template.subject   — subject line template
  email.template.html      — HTML body template
"""

from __future__ import annotations

import html
import logging
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSetting

logger = logging.getLogger(__name__)


# ── Default email template ─────────────────────────────────────────────────────

DEFAULT_EMAIL_TEMPLATE_SUBJECT = "Deine Zugangsdaten für {app_name}"

DEFAULT_EMAIL_TEMPLATE_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
</head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f4f5f7;padding:40px 16px;">
    <tr><td align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:520px;">

        <!-- Header mit Logo -->
        <tr>
          <td style="background:{color_primary};border-radius:10px 10px 0 0;padding:28px 40px;text-align:center;">
            {logo_block}
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="background:#ffffff;padding:36px 40px;">
            <p style="margin:0 0 8px;font-size:22px;font-weight:700;color:#1a1a2e;">&#128272; Deine Zugangsdaten</p>
            <p style="margin:0 0 20px;font-size:15px;color:#444;line-height:1.6;">
              Hallo{recipient_name_greeting},<br/>
              dein Konto f&#252;r <strong>{app_name}</strong> wurde eingerichtet (oder dein Passwort wurde zur&#252;ckgesetzt).
            </p>

            <!-- Credentials box -->
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
                   style="background:#f8f9fa;border:1px solid #e0e0e8;border-radius:8px;margin-bottom:28px;">
              <tr><td style="padding:20px 24px;">
                <p style="margin:0 0 4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#888;">&#128231; E-Mail</p>
                <p style="margin:0 0 16px;font-size:15px;color:#1a1a2e;">{email}</p>
                <p style="margin:0 0 4px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#888;">&#128273; Passwort</p>
                <code style="font-size:20px;font-weight:700;color:{color_primary};letter-spacing:.06em;font-family:'Menlo','Consolas','Monaco',monospace;">{password}</code>
              </td></tr>
            </table>

            <p style="margin:0 0 28px;font-size:14px;color:#666;line-height:1.5;">
              &#9888;&#65039; Bitte &#228;ndere dein Passwort nach dem ersten Login. Bewahre deine Zugangsdaten sicher auf.
            </p>

            <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
              <tr><td align="center">
                <a href="{login_url}"
                   style="display:inline-block;background:{color_primary};color:#ffffff;text-decoration:none;
                          font-size:15px;font-weight:600;padding:13px 36px;border-radius:7px;">
                  &#128640; Jetzt anmelden &#8594;
                </a>
              </td></tr>
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f0f1f3;border-radius:0 0 10px 10px;padding:20px 40px;text-align:center;">
            <p style="margin:0;font-size:12px;color:#999;line-height:1.6;">
              Diese E-Mail wurde automatisch von {app_name} versandt.<br/>
              Falls du diese E-Mail nicht erwartet hast, kannst du sie ignorieren.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── SMTP config helper ────────────────────────────────────────────────────────

async def _get_smtp_settings(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_([
                "smtp.host", "smtp.port", "smtp.username", "smtp.password",
                "smtp.from_email", "smtp.from_name", "smtp.use_tls",
            ])
        )
    )
    rows = result.scalars().all()
    return {r.key: r.value for r in rows}


async def save_smtp_settings(db: AsyncSession, settings: dict[str, str]) -> None:
    """Upsert SMTP settings into system_settings."""
    for key, value in settings.items():
        existing = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
        row = existing.scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.commit()


# ── Branding helper ────────────────────────────────────────────────────────────

async def _get_branding_settings(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key.like("branding.%"))
    )
    rows = result.scalars().all()
    defaults = {
        "branding.app_name": "ConvoyPlan",
        "branding.logo_main": "",
        "branding.color_primary": "#E23D28",
        "branding.color_primary_hover": "#C23020",
    }
    stored = {r.key: r.value for r in rows}
    return {**defaults, **stored}


def _build_logo_block(logo_main: str, app_name: str, base_url: str = "") -> str:
    """Return the logo HTML block for email header."""
    safe_name = html.escape(app_name)
    if logo_main:
        safe_logo = html.escape(logo_main)
        return (
            f'<img src="{base_url}/uploads/logos/{safe_logo}" '
            f'height="50" alt="{safe_name}" style="display:block;margin:0 auto;"/>'
        )
    return (
        f'<span style="font-size:26px;font-weight:700;color:#ffffff;">'
        f"{safe_name}</span>"
    )


# ── Template rendering ─────────────────────────────────────────────────────────

async def _render_password_email_async(
    db: AsyncSession,
    recipient_name: str,
    email: str,
    password: str,
    login_url: str,
    base_url: str = "",
) -> tuple[str, str]:
    """Render the password email from DB template or default. Returns (subject, html_body)."""
    # Load branding settings
    branding = await _get_branding_settings(db)
    app_name = branding.get("branding.app_name", "ConvoyPlan")
    color_primary = branding.get("branding.color_primary", "#E23D28")
    color_primary_hover = branding.get("branding.color_primary_hover", "#C23020")
    logo_main = branding.get("branding.logo_main", "")

    # Load custom template from DB (if set)
    result = await db.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_(["email.template.subject", "email.template.html"])
        )
    )
    rows = {r.key: r.value for r in result.scalars().all()}
    subject_tpl = rows.get("email.template.subject") or DEFAULT_EMAIL_TEMPLATE_SUBJECT
    html_tpl = rows.get("email.template.html") or DEFAULT_EMAIL_TEMPLATE_HTML

    # Build computed fragments
    logo_block = _build_logo_block(logo_main, app_name, base_url)
    # HTML-escape user-controlled values to prevent HTML injection when a
    # custom template is used or a user sets a malicious display name.
    safe_name = html.escape(recipient_name)
    recipient_name_greeting = f" {safe_name}" if recipient_name else ""

    html_vars = {
        "recipient_name": safe_name,
        "recipient_name_greeting": recipient_name_greeting,
        "email": html.escape(email),
        "password": html.escape(password),
        "login_url": login_url,
        "app_name": app_name,
        "logo_block": logo_block,
        "color_primary": color_primary,
        "color_primary_hover": color_primary_hover,
    }
    # Subject is plain text — use raw (unescaped) values so &amp; never appears.
    plain_vars = {**html_vars, "app_name": app_name}

    try:
        subject = subject_tpl.format_map(plain_vars)
        html_body = html_tpl.format_map(html_vars)
    except (KeyError, ValueError):
        # Fall back to default template if custom template has rendering issues
        subject = DEFAULT_EMAIL_TEMPLATE_SUBJECT.format_map(plain_vars)
        html_body = DEFAULT_EMAIL_TEMPLATE_HTML.format_map(html_vars)

    return subject, html_body


# ── Legacy sync helper (kept for backwards compat) ─────────────────────────────

def _render_password_email(
    recipient_name: str,
    email: str,
    password: str,
    login_url: str,
    app_name: str = "ConvoyPlan",
) -> tuple[str, str]:
    """Synchronous fallback renderer using the default template.

    Prefer _render_password_email_async when a DB session is available.
    """
    subject = DEFAULT_EMAIL_TEMPLATE_SUBJECT.format(app_name=app_name)
    logo_block = _build_logo_block("", app_name)
    safe_name = html.escape(recipient_name)
    recipient_name_greeting = f" {safe_name}" if recipient_name else ""
    html_body = DEFAULT_EMAIL_TEMPLATE_HTML.format(
        recipient_name=safe_name,
        recipient_name_greeting=recipient_name_greeting,
        email=html.escape(email),
        password=html.escape(password),
        login_url=login_url,
        app_name=app_name,
        logo_block=logo_block,
        color_primary="#E23D28",
        color_primary_hover="#C23020",
    )
    return subject, html_body


# ── Send helpers ──────────────────────────────────────────────────────────────

async def send_password_email(
    db: AsyncSession,
    recipient_email: str,
    recipient_name: str,
    password: str,
    login_url: str,
    app_name: str = "ConvoyPlan",
) -> None:
    """Send a welcome/password-reset email via configured SMTP."""
    cfg = await _get_smtp_settings(db)

    host = cfg.get("smtp.host", "").strip()
    if not host:
        raise ValueError("SMTP nicht konfiguriert — bitte Host in den Systemeinstellungen hinterlegen")

    port = int(cfg.get("smtp.port", "587"))
    username = cfg.get("smtp.username", "").strip()
    password_smtp = cfg.get("smtp.password", "").strip()
    from_email = cfg.get("smtp.from_email", "").strip() or username
    from_name = cfg.get("smtp.from_name", app_name).strip()
    use_tls = cfg.get("smtp.use_tls", "starttls").strip().lower()

    subject, html_body = await _render_password_email_async(
        db=db,
        recipient_name=recipient_name,
        email=recipient_email,
        password=password,
        login_url=login_url,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = recipient_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    smtp_kwargs: dict = {
        "hostname": host,
        "port": port,
        "timeout": 15,
    }

    if use_tls == "ssl":
        # Direct SSL (port 465)
        smtp_kwargs["use_tls"] = True
        smtp_kwargs["tls_context"] = ssl.create_default_context()
    elif use_tls in ("false", "none", "plain"):
        smtp_kwargs["use_tls"] = False
        smtp_kwargs["start_tls"] = False
    else:
        # STARTTLS (default, port 587)
        smtp_kwargs["use_tls"] = False
        smtp_kwargs["start_tls"] = True
        smtp_kwargs["tls_context"] = ssl.create_default_context()

    async with aiosmtplib.SMTP(**smtp_kwargs) as client:
        if username and password_smtp:
            await client.login(username, password_smtp)
        await client.send_message(msg)


async def test_smtp_connection(db: AsyncSession) -> dict:
    """Check if SMTP is reachable. Returns {ok, error}."""
    cfg = await _get_smtp_settings(db)
    host = cfg.get("smtp.host", "").strip()
    if not host:
        return {"ok": False, "error": "Kein SMTP-Host konfiguriert"}
    port = int(cfg.get("smtp.port", "587"))
    use_tls = cfg.get("smtp.use_tls", "starttls").strip().lower()
    username = cfg.get("smtp.username", "").strip()
    password_smtp = cfg.get("smtp.password", "").strip()

    try:
        smtp_kwargs: dict = {"hostname": host, "port": port, "timeout": 10}
        if use_tls == "ssl":
            smtp_kwargs["use_tls"] = True
            smtp_kwargs["tls_context"] = ssl.create_default_context()
        elif use_tls in ("false", "none", "plain"):
            smtp_kwargs["use_tls"] = False
            smtp_kwargs["start_tls"] = False
        else:
            smtp_kwargs["use_tls"] = False
            smtp_kwargs["start_tls"] = True
            smtp_kwargs["tls_context"] = ssl.create_default_context()

        async with aiosmtplib.SMTP(**smtp_kwargs) as client:
            if username and password_smtp:
                await client.login(username, password_smtp)
        return {"ok": True, "error": None}
    except Exception as exc:
        logger.error("SMTP connection test failed: %s", exc)
        return {"ok": False, "error": "SMTP connection failed"}
