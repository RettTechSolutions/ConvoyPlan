"""Zeitreihen der Systemüberwachung (Admin → Systemübersicht).

Drei Tabellen, bewusst getrennt nach Auflösung und Zweck:

* ``system_metrics``       — Rohstichproben im Sampling-Intervall (Standard 5 min).
                             Kurze Aufbewahrung (Standard 90 Tage) für Detailcharts.
* ``system_metrics_daily`` — Tagesaggregate, die der Collector einmal je Tag
                             verdichtet. Lange Aufbewahrung (Standard 3 Jahre),
                             Grundlage für Monatsberichte weit über das
                             Rohdatenfenster hinaus.
* ``user_activity_days``   — je Benutzer und Tag eine Zeile: „wer war wann im
                             Portal". Überlebt Neustarts (die In-Memory-
                             Aktivitätsliste tut das nicht) und liefert die
                             eindeutigen Nutzerzahlen der Berichte.

Alle Zeitstempel sind UTC. Benutzer-/Org-Referenzen sind bewusst plain UUIDs
ohne Fremdschlüssel, damit die Historie das Löschen eines Kontos übersteht
(gleiche Begründung wie beim Audit-Log).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemMetricSample(Base):
    """Eine Momentaufnahme von Host, Containern, Datenbank und Portalnutzung."""

    __tablename__ = "system_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # Abstand zur vorherigen Stichprobe in Sekunden — macht Raten (Bytes/s,
    # Requests/s) auch dann korrekt, wenn der Collector mal ausgesetzt hat.
    interval_s: Mapped[int] = mapped_column(Integer, default=0)

    # ── CPU / Last ────────────────────────────────────────────────────────────
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    load1: Mapped[float | None] = mapped_column(Float, nullable=True)
    load5: Mapped[float | None] = mapped_column(Float, nullable=True)
    load15: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Arbeitsspeicher ───────────────────────────────────────────────────────
    mem_total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mem_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mem_available_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mem_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    swap_total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    swap_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # ── Massenspeicher ────────────────────────────────────────────────────────
    # Kennzahlen des primären Datenträgers (erster konfigurierter Pfad),
    # Details je Mountpoint in `disks`.
    disk_total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_read_bytes_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_write_bytes_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_util_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Druck (PSI, Linux ≥ 4.20) ─────────────────────────────────────────────
    # "some avg10" in Prozent: Anteil der Zeit, in der mindestens ein Task auf
    # die Ressource warten musste. Der ehrlichste Sättigungsindikator, den der
    # Kernel liefert — bei I/O deutlich aussagekräftiger als reine Auslastung.
    psi_cpu_avg10: Mapped[float | None] = mapped_column(Float, nullable=True)
    psi_mem_avg10: Mapped[float | None] = mapped_column(Float, nullable=True)
    psi_io_avg10: Mapped[float | None] = mapped_column(Float, nullable=True)
    psi_io_avg60: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Datenbank ─────────────────────────────────────────────────────────────
    db_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    db_connections: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Container ─────────────────────────────────────────────────────────────
    containers_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    containers_running: Mapped[int | None] = mapped_column(Integer, nullable=True)
    containers_unhealthy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Portalnutzung ─────────────────────────────────────────────────────────
    # `active_users`/`active_orgs` zählen ausschließlich reguläre Portalnutzer;
    # Demo-Besucher und Superadmins stehen getrennt daneben (siehe
    # app.services.activity), damit die Nutzerkurve nicht durch Probesitzungen
    # oder die eigene Administration verfälscht wird.
    active_users: Mapped[int] = mapped_column(Integer, default=0)
    active_demo_users: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_admin_users: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_orgs: Mapped[int] = mapped_column(Integer, default=0)
    logins: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    request_errors: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_convoys: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Details ───────────────────────────────────────────────────────────────
    # `disks`:      [{"path", "total_bytes", "used_bytes", "free_bytes", "percent"}]
    # `containers`: [{"name", "state", "health", "cpu_percent", "mem_bytes", …}]
    disks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    containers: Mapped[list | None] = mapped_column(JSON, nullable=True)


class SystemMetricDaily(Base):
    """Tagesverdichtung der Rohstichproben — Basis der Monatsberichte."""

    __tablename__ = "system_metrics_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    samples: Mapped[int] = mapped_column(Integer, default=0)

    cpu_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    mem_percent_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_percent_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_used_max_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    disk_percent_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_percent_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_used_max_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_read_bytes_s_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_write_bytes_s_avg: Mapped[float | None] = mapped_column(Float, nullable=True)

    psi_io_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    psi_io_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    psi_cpu_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    psi_mem_avg: Mapped[float | None] = mapped_column(Float, nullable=True)

    db_size_max_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    containers_unhealthy_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    containers_running_min: Mapped[int | None] = mapped_column(Integer, nullable=True)

    active_users_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_users_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_demo_users_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_admin_users_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Eindeutige Benutzer des Tages — aus user_activity_days gezählt, nicht aus
    # den Stichproben ableitbar (dort steht nur die jeweilige Momentanzahl).
    # `unique_users` sind reguläre Portalnutzer; Demo und Admin daneben.
    unique_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unique_demo_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unique_admin_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_errors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class UserActivityDay(Base):
    """Ein Benutzer an einem Tag: erste/letzte Aktivität und Request-Zahl.

    Die Nutzergruppe (``kind``) gehört zum Schlüssel: ein Superadmin, der an
    einem Tag im Admin-Portal *und* in einer Organisation gearbeitet hat, ergibt
    zwei Zeilen — sonst ließe sich die Betreibernutzung nicht herausrechnen.
    """

    __tablename__ = "user_activity_days"
    __table_args__ = (
        UniqueConstraint("user_id", "day", "kind", name="uq_user_activity_user_day_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    # "member" | "demo" | "admin" — siehe app.services.activity.KINDS.
    kind: Mapped[str] = mapped_column(String(16), default="member", server_default="member", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requests: Mapped[int] = mapped_column(Integer, default=0)
