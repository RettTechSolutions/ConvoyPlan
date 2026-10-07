"""OAuth-Client der Begleit-App: Token-Version an den Refresh-Tokens.

Eine Spalte: ``oauth_refresh_tokens.token_version``. Ein Refresh-Token merkt
sich die ``token_version`` des Benutzers beim Ausstellen; weicht sie beim
Einlösen ab, ist die Kette zu Ende. Bestehende Tokens bekommen NULL und
werden nicht nachträglich geprüft — sie laufen mit ihrer Laufzeit aus.

Die Zeile des App-Clients in ``oauth_clients`` legt die Migration **nicht**
an: der Client ist im Code beschrieben (``services/app_client.py``), die
Zeile braucht es nur für die Fremdschlüssel und entsteht beim ersten Code.

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_refresh_tokens", sa.Column("token_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_refresh_tokens", "token_version")
