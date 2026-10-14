"""Aktionsseite: Beiträge — Fotos aus Telegram, freigegeben von der Presse.

Sieben Tabellen. ``public_tracker_telegram`` ist der Bot einer Organisation
(Token verschlüsselt), ``public_tracker_chats`` bindet eine Gruppe oder ein
Thema an einen Konvoi einer Seite, ``public_tracker_presse`` sagt, wer dort
freigeben darf, ``public_tracker_codes`` hält Einmal- und Presse-Codes als
Hash. ``public_tracker_posts`` sind die Beiträge, ``public_tracker_photos``
ihre Bilder, ``public_tracker_photo_data`` deren Bytes — getrennt, damit eine
Liste nie Bilder lädt. Ein Beitrag kann statt Bildern einen Link tragen
(``link_url``/``link_dienst``, § 11). ``karte_faellig_ab`` ist die
Warteschlange für Karten, die Telegram gedrosselt hat. Bestehende Daten gibt es nicht, die
Migration legt nur an. Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md.

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

_KONVOI_DER_SEITE = (
    ["tracker_id", "convoy_id"],
    ["public_tracker_convoys.tracker_id", "public_tracker_convoys.convoy_id"],
)


def upgrade() -> None:
    op.create_table(
        "public_tracker_telegram",
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bot_token_enc", sa.Text(), nullable=False),
        sa.Column("bot_username", sa.String(64), nullable=True),
        sa.Column("update_offset", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ungeprueft"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "public_tracker_chats",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tracker_id", sa.UUID(), nullable=False),
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=True),
        sa.Column("chat_title", sa.String(255), nullable=True),
        sa.Column("ansage_grund", sa.String(20), nullable=True),
        sa.Column("ansage_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(*_KONVOI_DER_SEITE, ondelete="CASCADE"),
        sa.UniqueConstraint("tracker_id", "convoy_id", name="uq_public_tracker_chats_konvoi"),
    )
    # NULL ist in einem UNIQUE nicht gleich NULL — deshalb zwei Teilindizes.
    op.create_index(
        "uq_public_tracker_chats_gruppe", "public_tracker_chats", ["chat_id"],
        unique=True, postgresql_where=sa.text("thread_id IS NULL"),
    )
    op.create_index(
        "uq_public_tracker_chats_thema", "public_tracker_chats", ["chat_id", "thread_id"],
        unique=True, postgresql_where=sa.text("thread_id IS NOT NULL"),
    )
    op.create_table(
        "public_tracker_presse",
        sa.Column(
            "tracker_id",
            sa.UUID(),
            sa.ForeignKey("public_trackers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "public_tracker_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column(
            "tracker_id",
            sa.UUID(),
            sa.ForeignKey("public_trackers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("convoy_id", sa.UUID(), nullable=True),
        sa.Column("art", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(*_KONVOI_DER_SEITE, ondelete="CASCADE"),
        sa.CheckConstraint("art IN ('verbinden', 'presse')", name="ck_public_tracker_codes_art"),
        sa.CheckConstraint(
            "(art = 'verbinden') = (convoy_id IS NOT NULL)", name="ck_public_tracker_codes_konvoi"
        ),
    )
    op.create_table(
        "public_tracker_posts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("public_id", sa.String(32), nullable=False, unique=True),
        sa.Column("tracker_id", sa.UUID(), nullable=False),
        sa.Column("convoy_id", sa.UUID(), nullable=False),
        sa.Column("quelle", sa.String(20), nullable=False, server_default="telegram"),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("media_group_id", sa.String(64), nullable=True),
        sa.Column("card_message_id", sa.BigInteger(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="wartet"),
        sa.Column("text_raw", sa.Text(), nullable=True),
        sa.Column("text_public", sa.Text(), nullable=True),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column("link_dienst", sa.String(20), nullable=True),
        sa.Column("text_edited_by_presse", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sender_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("reviewed_by_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "reviewed_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("public_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("karte_faellig_ab", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(*_KONVOI_DER_SEITE, ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('wartet', 'freigegeben', 'abgelehnt', 'zurueckgezogen')",
            name="ck_public_tracker_posts_status",
        ),
        sa.CheckConstraint(
            "char_length(text_public) <= 500", name="ck_public_tracker_posts_text"
        ),
        # Beide oder keins; NULL in einer der Vergleiche lässt den CHECK passieren.
        sa.CheckConstraint(
            "(link_url IS NULL) = (link_dienst IS NULL) AND char_length(link_url) <= 300 AND "
            "link_dienst IN ('instagram', 'youtube', 'facebook', 'tiktok')",
            name="ck_public_tracker_posts_link",
        ),
    )
    op.create_index(
        "ix_public_tracker_posts_konvoi_zeit", "public_tracker_posts",
        ["tracker_id", "convoy_id", "taken_at"],
    )
    op.create_index(
        "uq_public_tracker_posts_nachricht", "public_tracker_posts", ["chat_id", "message_id"],
        unique=True, postgresql_where=sa.text("chat_id IS NOT NULL"),
    )
    op.create_index(
        "uq_public_tracker_posts_album", "public_tracker_posts", ["chat_id", "media_group_id"],
        unique=True, postgresql_where=sa.text("media_group_id IS NOT NULL"),
    )
    op.create_table(
        "public_tracker_photos",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "post_id",
            sa.UUID(),
            sa.ForeignKey("public_tracker_posts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("public_id", sa.String(32), nullable=False, unique=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.UniqueConstraint("post_id", "position", name="uq_public_tracker_photos_platz"),
        sa.CheckConstraint(
            "position >= 0 AND position < 10", name="ck_public_tracker_photos_platz"
        ),
    )
    op.create_table(
        "public_tracker_photo_data",
        sa.Column(
            "photo_id",
            sa.UUID(),
            sa.ForeignKey("public_tracker_photos.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("gross", sa.LargeBinary(), nullable=False),
        sa.Column("klein", sa.LargeBinary(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("public_tracker_photo_data")
    op.drop_table("public_tracker_photos")
    op.drop_index("uq_public_tracker_posts_album", table_name="public_tracker_posts")
    op.drop_index("uq_public_tracker_posts_nachricht", table_name="public_tracker_posts")
    op.drop_index("ix_public_tracker_posts_konvoi_zeit", table_name="public_tracker_posts")
    op.drop_table("public_tracker_posts")
    op.drop_table("public_tracker_codes")
    op.drop_table("public_tracker_presse")
    op.drop_index("uq_public_tracker_chats_thema", table_name="public_tracker_chats")
    op.drop_index("uq_public_tracker_chats_gruppe", table_name="public_tracker_chats")
    op.drop_table("public_tracker_chats")
    op.drop_table("public_tracker_telegram")
