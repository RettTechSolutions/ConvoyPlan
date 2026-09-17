"""MCP-Richtlinie je Organisation.

Eine Zeile je Organisation, die die KI-Schnittstelle benutzen darf — keine
Zeile heißt aus. Der Ausgangszustand für alles Neue ist damit „deaktiviert",
ohne dass dafür irgendwo ein Wert gesetzt werden müsste.

**Bestehende Verbindungen laufen weiter.** Die Migration legt für jede
Organisation, an der eine aktive Verbindung hängt, eine eingeschaltete Zeile
an — mit genau den Bereichen und Scopes, die dort bereits in Gebrauch sind.
Das ist kein aufgeweichter Standard: ohne diesen Schritt bräche ein Update
eine laufende Anbindung wortlos, und der Org-Admin erführe es von seinem
Assistenten statt vom Portal. Wer sie nicht mehr will, schaltet sie ab —
sichtbar, an derselben Stelle, an der sie jetzt steht.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

# Ausgeschrieben statt aus app.mcp importiert: eine Migration beschreibt den
# Stand von damals. Zieht jemand später einen Bereich zusammen oder benennt
# einen Scope um, soll diese Datei weiterhin das tun, was sie am Tag ihrer
# Entstehung tat — und nicht etwas anderes, weil der Code weitergewandert ist.
BEREICHE = "konvois fahrzeuge wegpunkte routen status"


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "organization_mcp_policies" not in existing:
        op.create_table(
            "organization_mcp_policies",
            sa.Column(
                "organization_id",
                sa.UUID(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("scopes", sa.String(255), nullable=False, server_default=""),
            sa.Column("bereiche", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_by_id",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # Bestandsschutz — nur für Organisationen mit einer *aktiven* Verbindung.
    # Eine abgelaufene oder widerrufene zählt nicht: sie ist kein Zugang, den
    # dieses Update brechen könnte.
    if "oauth_refresh_tokens" in existing:
        op.execute(
            sa.text(
                f"""
                INSERT INTO organization_mcp_policies
                    (organization_id, enabled, scopes, bereiche)
                SELECT
                    x.organization_id,
                    true,
                    -- Die Vereinigung der tatsächlich erteilten Scopes. Mehr
                    -- freizugeben als in Gebrauch ist, wäre eine stille
                    -- Ausweitung; weniger bräche die Verbindung. Zerlegt und
                    -- neu zusammengesetzt, weil die Spalte je Verbindung
                    -- mehrere Scopes in einer Zeichenkette trägt.
                    string_agg(DISTINCT x.scope, ' ' ORDER BY x.scope),
                    '{BEREICHE}'
                FROM (
                    SELECT
                        t.organization_id,
                        unnest(string_to_array(t.scopes, ' ')) AS scope
                    FROM oauth_refresh_tokens t
                    WHERE t.revoked = false
                      AND t.rotated_at IS NULL
                      AND t.expires_at > now()
                ) x
                WHERE x.scope <> ''
                GROUP BY x.organization_id
                ON CONFLICT (organization_id) DO NOTHING
                """
            )
        )


def downgrade() -> None:
    op.drop_table("organization_mcp_policies")
