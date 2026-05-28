"""email template defaults in system_settings

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_DEFAULT_SUBJECT = "Deine Zugangsdaten für {app_name}"

_DEFAULT_HTML = """<!DOCTYPE html>
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

_DEFAULTS = {
    "email.template.subject": _DEFAULT_SUBJECT,
    "email.template.html": _DEFAULT_HTML,
}


def upgrade() -> None:
    conn = op.get_bind()
    for key, value in _DEFAULTS.items():
        conn.execute(
            sa.text(
                "INSERT INTO system_settings (key, value) VALUES (:key, :value) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for key in _DEFAULTS:
        conn.execute(
            sa.text("DELETE FROM system_settings WHERE key = :key"),
            {"key": key},
        )
