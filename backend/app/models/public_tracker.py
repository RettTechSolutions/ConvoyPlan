"""Öffentliche Aktionsseite und Positionsverlauf.

Eine Aktionsseite zeigt ausgewählte Konvois einer Organisation öffentlich —
verzögert, vergröbert und ohne Einsatzdetails. Ausgeliefert wird sie nicht
von hier, sondern von einer eigenen Anwendung (Convoyplan-EventTracker), die
``GET /api/public/aktion/{slug}`` mit dem Abruf-Token abholt. Was diese
Antwort enthalten darf, steht in ``services/aktionsseite.py``.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PublicTracker(Base):
    __tablename__ = "public_trackers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Freitext der Organisation („12 Lkw, rund 6 000 Päckchen") — nicht
    # berechnet, damit niemand aus der Seite die Ladung ableitet.
    facts: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme: Mapped[str] = mapped_column(String(20), default="neutral")
    delay_minutes: Mapped[int] = mapped_column(Integer)
    # Zielort als Punkt zeigen (vergröbert) — sonst nur der Text.
    show_destination: Mapped[bool] = mapped_column(Boolean, default=False)
    # Danach gibt es die Seite nicht mehr, und es wird nicht mehr aufgezeichnet.
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # SHA-256 des Abruf-Tokens. Das Token selbst sieht man nur beim Anlegen
    # und beim Erneuern; es ist zufällig und lang genug, dass ein schneller
    # Hash reicht (anders als ein Passwort).
    fetch_token_hash: Mapped[str] = mapped_column(String(64))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    convoys: Mapped[list["PublicTrackerConvoy"]] = relationship(
        back_populates="tracker",
        cascade="all, delete-orphan",
        order_by="PublicTrackerConvoy.position",
    )


class PublicTrackerConvoy(Base):
    __tablename__ = "public_tracker_convoys"

    tracker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_trackers.id", ondelete="CASCADE"), primary_key=True
    )
    convoy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("convoys.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # Öffentlicher Name. Intern heißt so etwas „KV 3 / Los B", draußen
    # „Konvoi Bosnien" — der Konvoiname geht nie hinaus.
    display_name: Mapped[str] = mapped_column(String(100))
    destination_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Eigener Zielpunkt. Ohne ihn gilt der letzte Wegpunkt — der ist oft nur
    # die Fähre oder die Grenze, nicht das Ziel (Migration 0069).
    destination_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    destination_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    color: Mapped[str | None] = mapped_column(String(9), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    tracker: Mapped[PublicTracker] = relationship(back_populates="convoys")


class VehiclePositionTrail(Base):
    """Verlauf der Positionen, ausgedünnt — nur für Konvois an einer aktiven
    Aktionsseite. Geschrieben ausschließlich von ``positionsverlauf.aufzeichnen``."""

    __tablename__ = "vehicle_position_trail"

    convoy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("convoys.id", ondelete="CASCADE"), primary_key=True
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


# ── Beiträge: Fotos aus Telegram ───────────────────────────────────────────
#
# Plan: docs/superpowers/plans/2026-10-13-fotos-auf-der-aktionsseite.md, § 7.
# Wo ein Beitrag liegt und ob er hinausgeht, entscheidet
# ``services/aktionsseite.py`` (``beitrag_position``, ``beitrag_sichtbar``);
# hier steht nur, was gespeichert wird.

BEITRAG_STATUS = ("wartet", "freigegeben", "abgelehnt", "zurueckgezogen")
BEITRAG_TEXT_MAX = 500
BILDER_JE_BEITRAG = 10
# Link-Beiträge (§ 11): nur diese Dienste, Regeln in ``services/aktionsseite_link.py``.
LINK_DIENSTE = ("instagram", "youtube", "facebook", "tiktok")
LINK_MAX = 300


class PublicTrackerTelegram(Base):
    """Der Telegram-Bot einer Organisation — einer für alle ihre Seiten."""

    __tablename__ = "public_tracker_telegram"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    # Verschlüsselt über ``services/crypto.py``; angezeigt wird er nie wieder.
    bot_token_enc: Mapped[str] = mapped_column(Text)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Letzte verarbeitete ``update_id`` + 1 — Telegram liefert sonst alles
    # noch einmal.
    update_offset: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ungeprueft")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicTrackerChat(Base):
    """Eine Telegram-Gruppe oder ein Thema darin, gebunden an genau einen
    Konvoi einer Aktionsseite. ``thread_id`` leer heißt: die ganze Gruppe."""

    __tablename__ = "public_tracker_chats"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tracker_id", "convoy_id"],
            ["public_tracker_convoys.tracker_id", "public_tracker_convoys.convoy_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tracker_id", "convoy_id", name="uq_public_tracker_chats_konvoi"),
        # Ein Chat (oder ein Thema) gehört genau einem Konvoi. Zwei Indizes, weil
        # NULL in einem UNIQUE nicht gleich NULL ist.
        Index(
            "uq_public_tracker_chats_gruppe", "chat_id", unique=True,
            postgresql_where=text("thread_id IS NULL"),
        ),
        Index(
            "uq_public_tracker_chats_thema", "chat_id", "thread_id", unique=True,
            postgresql_where=text("thread_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tracker_id: Mapped[uuid.UUID] = mapped_column()
    convoy_id: Mapped[uuid.UUID] = mapped_column()
    chat_id: Mapped[int] = mapped_column(BigInteger)
    thread_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Nur intern, für die Zeile im Org-Admin.
    chat_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicTrackerPresse(Base):
    """Wer in Telegram freigeben darf — je Aktionsseite, an der Telegram-ID.

    Die ID kommt bei Long Polling von Telegram selbst und lässt sich nicht
    fälschen; der Anzeigename schon, er dient nur der Anzeige."""

    __tablename__ = "public_tracker_presse"

    tracker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_trackers.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicTrackerCode(Base):
    """Einmalcode zum Verbinden einer Gruppe, Presse-Code zum Eintragen.

    Nur als SHA-256, wie das Abruf-Token. ``verbinden`` nennt den Konvoi,
    ``presse`` nicht."""

    __tablename__ = "public_tracker_codes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tracker_id", "convoy_id"],
            ["public_tracker_convoys.tracker_id", "public_tracker_convoys.convoy_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("art IN ('verbinden', 'presse')", name="ck_public_tracker_codes_art"),
        CheckConstraint(
            "(art = 'verbinden') = (convoy_id IS NOT NULL)",
            name="ck_public_tracker_codes_konvoi",
        ),
    )

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tracker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_trackers.id", ondelete="CASCADE"), index=True
    )
    convoy_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    art: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicTrackerPost(Base):
    """Ein Beitrag: eine Nachricht mit Foto oder ein Album, samt Text.

    ``text_raw`` ist die Bildunterschrift aus Telegram und geht nie hinaus;
    hinaus geht ``text_public``, den die Presse freigegeben hat. Absender und
    Prüfer sind intern — für die Karte in der Gruppe und das Audit-Log."""

    __tablename__ = "public_tracker_posts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tracker_id", "convoy_id"],
            ["public_tracker_convoys.tracker_id", "public_tracker_convoys.convoy_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('wartet', 'freigegeben', 'abgelehnt', 'zurueckgezogen')",
            name="ck_public_tracker_posts_status",
        ),
        CheckConstraint(
            f"char_length(text_public) <= {BEITRAG_TEXT_MAX}",
            name="ck_public_tracker_posts_text",
        ),
        CheckConstraint(
            "(link_url IS NULL) = (link_dienst IS NULL) AND "
            f"char_length(link_url) <= {LINK_MAX} AND "
            "link_dienst IN (" + ", ".join(f"'{d}'" for d in LINK_DIENSTE) + ")",
            name="ck_public_tracker_posts_link",
        ),
        Index("ix_public_tracker_posts_konvoi_zeit", "tracker_id", "convoy_id", "taken_at"),
        # Telegram liefert eine Nachricht unter Umständen zweimal; ein Album
        # kommt als mehrere Updates. Beides darf nur einen Beitrag ergeben.
        Index(
            "uq_public_tracker_posts_nachricht", "chat_id", "message_id", unique=True,
            postgresql_where=text("chat_id IS NOT NULL"),
        ),
        Index(
            "uq_public_tracker_posts_album", "chat_id", "media_group_id", unique=True,
            postgresql_where=text("media_group_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Zufällig, geht hinaus — die Datenbank-Kennung nicht.
    public_id: Mapped[str] = mapped_column(String(32), unique=True)
    tracker_id: Mapped[uuid.UUID] = mapped_column()
    convoy_id: Mapped[uuid.UUID] = mapped_column()
    quelle: Mapped[str] = mapped_column(String(20), default="telegram")
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Die eine Nachricht des Bots je Beitrag, die er bei jedem Wechsel bearbeitet.
    card_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # ``message.date`` — nicht EXIF, das stellt jedes Handy anders und lässt
    # sich frei setzen.
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Späterer Termin der Presse (``/ab``); nie früher als die Regeln.
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="wartet")
    text_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_public: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Link-Beitrag statt Fotos (§ 11): bereinigte Adresse eines bekannten
    # Dienstes. Steht fest, sobald der Beitrag angelegt ist — eine Bearbeitung
    # in Telegram ändert nur den Text.
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_dienst: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Hat die Presse den Text geändert, ersetzt eine Bearbeitung in Telegram
    # ihn nicht mehr — nach der Freigabe ohnehin nie.
    text_edited_by_presse: Mapped[bool] = mapped_column(Boolean, default=False)
    sender_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    public_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    photos: Mapped[list["PublicTrackerPhoto"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="PublicTrackerPhoto.position",
    )


class PublicTrackerPhoto(Base):
    """Ein Bild eines Beitrags. Die Bytes liegen in ``public_tracker_photo_data``,
    damit eine Liste von Beiträgen nie Bilder lädt."""

    __tablename__ = "public_tracker_photos"
    __table_args__ = (
        UniqueConstraint("post_id", "position", name="uq_public_tracker_photos_platz"),
        CheckConstraint(
            f"position >= 0 AND position < {BILDER_JE_BEITRAG}",
            name="ck_public_tracker_photos_platz",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_tracker_posts.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    public_id: Mapped[str] = mapped_column(String(32), unique=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)

    post: Mapped[PublicTrackerPost] = relationship(back_populates="photos")


class PublicTrackerPhotoData(Base):
    """Die Bytes eines Bildes, neu kodiert und ohne Metadaten
    (``services/aktionsseite_bild.py``). In der Datenbank statt im
    Dateisystem: Sie liegen damit im vorhandenen Backup."""

    __tablename__ = "public_tracker_photo_data"

    photo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_tracker_photos.id", ondelete="CASCADE"), primary_key=True
    )
    gross: Mapped[bytes] = mapped_column(LargeBinary)
    klein: Mapped[bytes] = mapped_column(LargeBinary)
