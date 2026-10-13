"""Module je Organisation: Freigabe durch den Betreiber.

Eine Zeile je Organisation und Modul, für die der Superadmin entschieden hat;
keine Zeile heißt Standard der Betriebsart (``services/org_module.standard``).

Jede **bestehende** Organisation bekommt jedes Modul ausdrücklich frei — auch
auf dem Hosting-Server, wo der Standard für neue Organisationen „gesperrt" ist.
Ein Update nimmt keiner Organisation einen Reiter weg, den sie gestern noch
benutzt hat; sperren tut der Betreiber, nicht die Migration. Die Liste der
Module steht hier als Stand von heute: kommt später eins dazu, gilt für
Bestandsorganisationen dessen Standard, und das entscheidet dessen Migration.

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

MODULE = ("tracker", "aktionsseiten", "branding", "ki")


def upgrade() -> None:
    op.create_table(
        "organization_modules",
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("modul", sa.String(30), primary_key=True),
        sa.Column("freigegeben", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    for modul in MODULE:
        op.execute(
            sa.text(
                "INSERT INTO organization_modules (organization_id, modul, freigegeben) "
                "SELECT id, :modul, true FROM organizations"
            ).bindparams(modul=modul)
        )


def downgrade() -> None:
    op.drop_table("organization_modules")
