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
"""

from __future__ import annotations

import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSetting


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


# ── HTML email template ───────────────────────────────────────────────────────

def _render_password_email(
    recipient_name: str,
    email: str,
    password: str,
    login_url: str,
    app_name: str = "ConvoyPlan",
) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    subject = f"Deine Zugangsdaten für {app_name}"
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#f4f5f7;padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:520px;">

          <!-- Header -->
          <tr>
            <td style="background:#E23D28;border-radius:10px 10px 0 0;padding:32px 40px 28px;text-align:center;">
              <span style="font-size:26px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;">{app_name}</span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="background:#ffffff;padding:36px 40px;">
              <p style="margin:0 0 20px;font-size:16px;color:#1a1a2e;line-height:1.5;">
                Hallo{(' ' + recipient_name) if recipient_name else ''},
              </p>
              <p style="margin:0 0 24px;font-size:15px;color:#444;line-height:1.6;">
                dein Konto für <strong>{app_name}</strong> wurde eingerichtet (oder dein Passwort wurde zurückgesetzt). Hier sind deine Zugangsdaten:
              </p>

              <!-- Credentials box -->
              <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
                     style="background:#f8f9fa;border:1px solid #e0e0e8;border-radius:8px;margin-bottom:28px;">
                <tr>
                  <td style="padding:20px 24px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                      <tr>
                        <td style="padding-bottom:12px;">
                          <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#888;">E-Mail</span><br/>
                          <span style="font-size:15px;color:#1a1a2e;">{email}</span>
                        </td>
                      </tr>
                      <tr>
                        <td>
                          <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#888;">Passwort</span><br/>
                          <code style="font-size:18px;font-weight:700;color:#E23D28;letter-spacing:.06em;font-family:'Menlo','Consolas','Monaco',monospace;">{password}</code>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 28px;font-size:14px;color:#666;line-height:1.5;">
                Bitte ändere dein Passwort nach dem ersten Login. Bewahre deine Zugangsdaten sicher auf.
              </p>

              <!-- CTA button -->
              <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center">
                    <a href="{login_url}"
                       style="display:inline-block;background:#E23D28;color:#ffffff;text-decoration:none;
                              font-size:15px;font-weight:600;padding:13px 36px;border-radius:7px;
                              letter-spacing:.01em;">
                      Jetzt anmelden →
                    </a>
                  </td>
                </tr>
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
      </td>
    </tr>
  </table>
</body>
</html>"""
    return subject, html


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

    subject, html_body = _render_password_email(
        recipient_name=recipient_name,
        email=recipient_email,
        password=password,
        login_url=login_url,
        app_name=app_name,
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
        return {"ok": False, "error": str(exc)}
