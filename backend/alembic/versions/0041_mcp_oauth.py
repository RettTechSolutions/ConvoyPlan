"""OAuth-Tabellen für den MCP-Server.

Drei Tabellen: registrierte Clients (DCR), kurzlebige Autorisierungscodes und
rotierende Refresh-Tokens. Access-Tokens stehen bewusst in keiner Tabelle —
sie sind zustandslose JWTs wie die übrigen Tokens der Anwendung.

Codes und Refresh-Tokens liegen nur als SHA-256-Hash vor. Anders als bei
Passwörtern ist das hier richtig: die Werte sind 256-Bit-Zufall, gegen Raten
hilft die Entropie, und der Token-Endpunkt muss sie in einem Zugriff finden.

Das Client-Secret dagegen ist Fernet-verschlüsselt statt gehasht — es wird im
Klartext zurückgebraucht, weil das MCP-SDK es am Token-Endpunkt selbst
vergleicht. Gleiches Muster wie bei den MFA-Geheimnissen.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "oauth_clients" not in existing:
        op.create_table(
            "oauth_clients",
            sa.Column("client_id", sa.String(64), primary_key=True),
            sa.Column("client_secret_encrypted", sa.String(255), nullable=True),
            sa.Column("client_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("redirect_uris", sa.JSON(), nullable=False),
            sa.Column("grant_types", sa.JSON(), nullable=False),
            sa.Column(
                "token_endpoint_auth_method", sa.String(40), nullable=False, server_default="none"
            ),
            sa.Column("scope", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("client_secret_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        )

    if "oauth_codes" not in existing:
        op.create_table(
            "oauth_codes",
            sa.Column("code_hash", sa.String(64), primary_key=True),
            sa.Column(
                "client_id",
                sa.String(64),
                sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
                nullable=False,
            ),
            # CASCADE: verschwindet der Benutzer oder die Organisation, ist der
            # Code gegenstandslos — er trägt nur deren Zustimmung.
            sa.Column(
                "user_id",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                sa.UUID(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scopes", sa.String(255), nullable=False, server_default=""),
            sa.Column("code_challenge", sa.String(255), nullable=False),
            sa.Column("redirect_uri", sa.Text(), nullable=False),
            sa.Column(
                "redirect_uri_provided_explicitly",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column("resource", sa.Text(), nullable=True),
            sa.Column("family_id", sa.UUID(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_oauth_codes_client_id", "oauth_codes", ["client_id"])
        # Der Aufräumjob sucht über den Ablaufzeitpunkt.
        op.create_index("ix_oauth_codes_expires_at", "oauth_codes", ["expires_at"])

    if "oauth_refresh_tokens" not in existing:
        op.create_table(
            "oauth_refresh_tokens",
            sa.Column("token_hash", sa.String(64), primary_key=True),
            sa.Column("family_id", sa.UUID(), nullable=False),
            sa.Column(
                "client_id",
                sa.String(64),
                sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.UUID(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                sa.UUID(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scopes", sa.String(255), nullable=False, server_default=""),
            sa.Column("resource", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        )
        # Ein Diebstahlsignal widerruft die ganze Familie — der Index trägt
        # genau diese Abfrage.
        op.create_index(
            "ix_oauth_refresh_tokens_family_id", "oauth_refresh_tokens", ["family_id"]
        )
        op.create_index(
            "ix_oauth_refresh_tokens_client_id", "oauth_refresh_tokens", ["client_id"]
        )
        # Das Admin-Portal listet aktive Verbindungen je Benutzer und Org.
        op.create_index("ix_oauth_refresh_tokens_user_id", "oauth_refresh_tokens", ["user_id"])
        op.create_index(
            "ix_oauth_refresh_tokens_organization_id",
            "oauth_refresh_tokens",
            ["organization_id"],
        )
        op.create_index(
            "ix_oauth_refresh_tokens_expires_at", "oauth_refresh_tokens", ["expires_at"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    # Umgekehrte Reihenfolge: die Kinder tragen Fremdschlüssel auf oauth_clients.
    if "oauth_refresh_tokens" in existing:
        for idx in (
            "ix_oauth_refresh_tokens_expires_at",
            "ix_oauth_refresh_tokens_organization_id",
            "ix_oauth_refresh_tokens_user_id",
            "ix_oauth_refresh_tokens_client_id",
            "ix_oauth_refresh_tokens_family_id",
        ):
            op.drop_index(idx, table_name="oauth_refresh_tokens")
        op.drop_table("oauth_refresh_tokens")

    if "oauth_codes" in existing:
        op.drop_index("ix_oauth_codes_expires_at", table_name="oauth_codes")
        op.drop_index("ix_oauth_codes_client_id", table_name="oauth_codes")
        op.drop_table("oauth_codes")

    if "oauth_clients" in existing:
        op.drop_table("oauth_clients")
