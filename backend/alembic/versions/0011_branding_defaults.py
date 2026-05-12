"""branding defaults in system_settings

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_DEFAULTS = {
    "branding.app_name": "ConvoyPlan",
    "branding.logo_main": "",
    "branding.logo_horizontal": "",
    "branding.color_primary": "#E23D28",
    "branding.color_primary_hover": "#C23020",
    "branding.color_accent": "#3498db",
    "branding.color_bg": "#f5f3ee",
    "branding.color_surface": "#ffffff",
    "branding.color_nav_bg": "#2c3e50",
    "branding.color_nav_text": "#ecf0f1",
    "branding.color_text": "#2c3e50",
    "branding.color_text_muted": "#7f8c8d",
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
