"""Sammeln, Verdichten und Abfragen der Systemkennzahlen.

Aufgabenteilung
---------------
``collect_sample``    schreibt eine Stichprobe (der Collector-Loop ruft sie im
                      Sampling-Intervall auf).
``live_snapshot``     misst frisch für die Live-Ansicht, ohne zu speichern.
``query_series``      liefert Verlaufsdaten in der gewünschten Auflösung.
``rollup_day``        verdichtet einen Tag zu einer Zeile in system_metrics_daily.
``purge_old``         wirft Rohdaten/Aggregate außerhalb der Aufbewahrung weg.
``monthly_report``    baut den Monatsbericht (aus Tagesaggregaten).

Die Rohstichproben (Standard alle 5 min, 90 Tage Aufbewahrung) tragen die
Detailcharts; die Tagesaggregate (Standard 3 Jahre) tragen die Monatsberichte.
Ein Monatsbericht funktioniert dadurch auch dann noch, wenn die Rohdaten des
Monats längst gelöscht sind.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.convoy import Convoy
from app.models.organization import Organization
from app.models.system_metric import SystemMetricDaily, SystemMetricSample, UserActivityDay
from app.models.user import User
from app.services import activity, audit, docker_stats, host_metrics

logger = logging.getLogger(__name__)

# Zustand zwischen zwei Stichproben: CPU- und I/O-Zähler sind kumulativ, die
# Rate ergibt sich erst aus der Differenz zweier Messpunkte.
_last_cpu: host_metrics.CpuTimes | None = None
_last_io: host_metrics.DiskIoCounters | None = None
_last_sample_at: datetime | None = None

# Auflösungen der Verlaufsabfrage.
RESOLUTIONS = ("raw", "hour", "day")


def disk_paths() -> list[str]:
    return [p.strip() for p in settings.system_metrics_disk_paths.split(",") if p.strip()]


# ── Erhebung ─────────────────────────────────────────────────────────────────

async def _safe_scalar(db: AsyncSession, statement) -> Any:
    """Eine Abfrage ausführen, deren Fehlschlag die Erfassung nicht kippen darf.

    Wichtig ist das ``rollback()``: In PostgreSQL bricht ein fehlgeschlagenes
    Statement die gesamte Transaktion ab — ohne Rollback würde jede folgende
    Abfrage und am Ende das ``commit()`` mit „current transaction is aborted"
    scheitern. Ein einzelner Ausreißer (fehlende Tabelle, fehlendes Recht auf
    pg_stat_activity) kostet so nur diesen einen Kennwert.
    """
    try:
        return (await db.execute(statement)).scalar()
    except Exception:
        logger.debug("Optionale Metrikabfrage fehlgeschlagen", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def _db_stats(db: AsyncSession) -> tuple[int | None, int | None]:
    """(Datenbankgröße in Bytes, offene Verbindungen). PostgreSQL-spezifisch —
    schlägt es fehl (z. B. andere Engine im Test), sind beide Werte None."""
    size = await _safe_scalar(db, text("SELECT pg_database_size(current_database())"))
    connections = await _safe_scalar(
        db, text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
    )
    return size, connections


async def _count_logins_since(db: AsyncSession, since: datetime) -> int:
    """Erfolgreiche Anmeldungen seit ``since`` — aus dem Audit-Log, damit die
    Zahl auch einen Neustart des Backends übersteht."""
    value = await _safe_scalar(
        db,
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == audit.LOGIN_SUCCESS, AuditLog.created_at >= since),
    )
    return int(value or 0)


async def _active_convoys(db: AsyncSession) -> int | None:
    value = await _safe_scalar(
        db, select(func.count()).select_from(Convoy).where(Convoy.status.in_(("active", "running")))
    )
    return None if value is None else int(value)


def _host_snapshot(
    *, cpu_percent: float | None, io_rates: tuple[float | None, float | None, float | None]
) -> dict[str, Any]:
    """Alle procfs-Werte zu einem Dict zusammenfassen."""
    mem = host_metrics.read_memory()
    load = host_metrics.load_average()
    disks = host_metrics.disk_usage(disk_paths())
    psi_cpu = host_metrics.read_pressure("cpu") or {}
    psi_mem = host_metrics.read_pressure("memory") or {}
    psi_io = host_metrics.read_pressure("io") or {}
    read_rate, write_rate, util = io_rates
    primary = disks[0] if disks else None

    return {
        "cpu_percent": cpu_percent,
        "cpu_count": host_metrics.cpu_count(),
        "load1": load[0] if load else None,
        "load5": load[1] if load else None,
        "load15": load[2] if load else None,
        "uptime_seconds": host_metrics.uptime_seconds(),
        "mem_total_bytes": mem.total_bytes if mem else None,
        "mem_used_bytes": mem.used_bytes if mem else None,
        "mem_available_bytes": mem.available_bytes if mem else None,
        "mem_percent": mem.percent if mem else None,
        "swap_total_bytes": mem.swap_total_bytes if mem else None,
        "swap_used_bytes": mem.swap_used_bytes if mem else None,
        "disk_total_bytes": primary.total_bytes if primary else None,
        "disk_used_bytes": primary.used_bytes if primary else None,
        "disk_percent": primary.percent if primary else None,
        "disk_read_bytes_s": read_rate,
        "disk_write_bytes_s": write_rate,
        "disk_util_percent": util,
        "psi_cpu_avg10": psi_cpu.get("avg10"),
        "psi_mem_avg10": psi_mem.get("avg10"),
        "psi_io_avg10": psi_io.get("avg10"),
        "psi_io_avg60": psi_io.get("avg60"),
        "disks": [d.as_dict() for d in disks],
    }


async def collect_sample(db: AsyncSession) -> SystemMetricSample:
    """Eine Stichprobe erheben, speichern und zurückgeben."""
    global _last_cpu, _last_io, _last_sample_at

    now = datetime.now(timezone.utc)
    interval = int((now - _last_sample_at).total_seconds()) if _last_sample_at else 0

    cpu_now = host_metrics.read_cpu_times()
    io_now = host_metrics.read_disk_io()
    cpu_percent = host_metrics.cpu_percent_between(_last_cpu, cpu_now)
    io_rates = host_metrics.disk_io_rates(_last_io, io_now)
    _last_cpu, _last_io = cpu_now, io_now

    host = _host_snapshot(cpu_percent=cpu_percent, io_rates=io_rates)
    docker = await docker_stats.collect()
    db_size, db_connections = await _db_stats(db)

    counters, pending_users = activity.drain()
    active = activity.active_users()
    logins = await _count_logins_since(db, _last_sample_at or now - timedelta(seconds=interval or 0))

    sample = SystemMetricSample(
        captured_at=now,
        interval_s=interval,
        cpu_percent=host["cpu_percent"],
        cpu_count=host["cpu_count"],
        load1=host["load1"],
        load5=host["load5"],
        load15=host["load15"],
        mem_total_bytes=host["mem_total_bytes"],
        mem_used_bytes=host["mem_used_bytes"],
        mem_available_bytes=host["mem_available_bytes"],
        mem_percent=host["mem_percent"],
        swap_total_bytes=host["swap_total_bytes"],
        swap_used_bytes=host["swap_used_bytes"],
        disk_total_bytes=host["disk_total_bytes"],
        disk_used_bytes=host["disk_used_bytes"],
        disk_percent=host["disk_percent"],
        disk_read_bytes_s=host["disk_read_bytes_s"],
        disk_write_bytes_s=host["disk_write_bytes_s"],
        disk_util_percent=host["disk_util_percent"],
        psi_cpu_avg10=host["psi_cpu_avg10"],
        psi_mem_avg10=host["psi_mem_avg10"],
        psi_io_avg10=host["psi_io_avg10"],
        psi_io_avg60=host["psi_io_avg60"],
        db_size_bytes=db_size,
        db_connections=db_connections,
        containers_total=docker.total if docker.available else None,
        containers_running=docker.running if docker.available else None,
        containers_unhealthy=docker.unhealthy if docker.available else None,
        active_users=len(active),
        active_orgs=len({e.org_id for e in active if e.org_id is not None}),
        logins=logins,
        requests=counters.requests,
        request_errors=counters.errors,
        avg_response_ms=counters.avg_response_ms,
        active_convoys=await _active_convoys(db),
        disks=host["disks"],
        containers=[c.as_dict() for c in docker.containers] if docker.available else None,
    )
    # Erst die Nutzeraktivität (reine Selects + Inserts), dann die Stichprobe
    # anhängen: Sollte eine der Abfragen scheitern und die Transaktion
    # zurückrollen, ist die Stichprobe noch nicht angehängt und geht damit
    # nicht mit verloren.
    await _persist_user_activity(db, pending_users)
    db.add(sample)
    await db.commit()
    _last_sample_at = now
    return sample


async def _persist_user_activity(db: AsyncSession, pending: Iterable[activity.UserActivity]) -> None:
    """Tagesaktivität je Benutzer fortschreiben (eine Zeile pro Nutzer und Tag).

    Wird nicht als Bulk-Upsert formuliert, weil die Menge klein ist (Anzahl
    gleichzeitig aktiver Nutzer je Intervall) und ein SELECT+UPDATE ohne
    dialektspezifisches ``ON CONFLICT`` auskommt.
    """
    for entry in pending:
        day = entry.last_seen.astimezone(timezone.utc).date()
        try:
            existing = (
                await db.execute(
                    select(UserActivityDay).where(
                        UserActivityDay.user_id == entry.user_id, UserActivityDay.day == day
                    )
                )
            ).scalar_one_or_none()
        except Exception:
            logger.warning("Nutzeraktivität konnte nicht gelesen werden", exc_info=True)
            try:
                await db.rollback()
            except Exception:
                pass
            return
        if existing is None:
            db.add(
                UserActivityDay(
                    user_id=entry.user_id,
                    org_id=entry.org_id,
                    day=day,
                    first_seen_at=entry.first_seen,
                    last_seen_at=entry.last_seen,
                    requests=entry.requests,
                )
            )
        else:
            existing.last_seen_at = entry.last_seen
            existing.requests = (existing.requests or 0) + entry.requests
            if entry.org_id is not None:
                existing.org_id = entry.org_id


async def live_snapshot(db: AsyncSession) -> dict[str, Any]:
    """Frisch gemessene Momentaufnahme für die Übersichtsseite.

    Für die CPU-Auslastung wird kurz zweimal gemessen (200 ms Abstand), weil
    /proc/stat nur kumulative Ticks kennt und ein Einzelwert daher nichts über
    die *aktuelle* Last aussagt.
    """
    cpu_before = host_metrics.read_cpu_times()
    io_before = host_metrics.read_disk_io()
    await asyncio.sleep(0.2)
    cpu_after = host_metrics.read_cpu_times()
    io_after = host_metrics.read_disk_io()

    host = _host_snapshot(
        cpu_percent=host_metrics.cpu_percent_between(cpu_before, cpu_after),
        io_rates=host_metrics.disk_io_rates(io_before, io_after),
    )
    docker = await docker_stats.collect()
    db_size, db_connections = await _db_stats(db)

    counts: dict[str, int | None] = {}
    for key, model in (("users", User), ("organizations", Organization), ("convoys", Convoy)):
        value = await _safe_scalar(db, select(func.count()).select_from(model))
        counts[key] = None if value is None else int(value)

    today = datetime.now(timezone.utc).date()
    users_today = await unique_users_between(db, today, today)
    logins_24h = await _count_logins_since(db, datetime.now(timezone.utc) - timedelta(hours=24))

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "collector": {
            "enabled": settings.system_metrics_enabled,
            "interval_s": settings.system_metrics_interval,
            "last_sample_at": _last_sample_at.isoformat() if _last_sample_at else None,
            "raw_retention_days": settings.system_metrics_retention_days,
            "daily_retention_days": settings.system_metrics_daily_retention_days,
        },
        "host": host,
        "docker": docker.as_dict(),
        "database": {
            "size_bytes": db_size,
            "connections": db_connections,
            **counts,
        },
        "usage": {
            **activity.snapshot(),
            "unique_users_today": users_today,
            "logins_24h": logins_24h,
        },
    }


# ── Abfragen ─────────────────────────────────────────────────────────────────

# Messwerte (Zustandsgrößen): über ein Zeitfenster gemittelt.
_GAUGE_FIELDS = (
    "cpu_percent",
    "load1",
    "mem_percent",
    "mem_used_bytes",
    "disk_percent",
    "disk_used_bytes",
    "disk_read_bytes_s",
    "disk_write_bytes_s",
    "disk_util_percent",
    "psi_cpu_avg10",
    "psi_mem_avg10",
    "psi_io_avg10",
    "db_size_bytes",
    "containers_running",
    "containers_unhealthy",
    "active_users",
    "avg_response_ms",
)

# Zähler: über ein Zeitfenster aufsummiert. Würden sie gemittelt, zeigte
# dieselbe Kurve bei Stundenauflösung „Requests je Stichprobe" und bei
# Tagesauflösung (die in system_metrics_daily summiert) „Requests je Tag" —
# derselbe Chart mit zwei verschiedenen Einheiten.
_COUNTER_FIELDS = ("requests", "request_errors", "logins")

_SERIES_FIELDS = _GAUGE_FIELDS + _COUNTER_FIELDS


def choose_resolution(start: datetime, end: datetime, requested: str) -> str:
    """Auflösung bestimmen. ``auto`` wählt so, dass nie mehr als ~750 Punkte
    entstehen — genug für flüssige Charts, wenig genug für schnelle Abfragen."""
    if requested in RESOLUTIONS:
        return requested
    span_hours = max(1.0, (end - start).total_seconds() / 3600.0)
    raw_points = span_hours * 3600.0 / max(60, settings.system_metrics_interval)
    if raw_points <= 750:
        return "raw"
    return "hour" if span_hours <= 24 * 45 else "day"


async def query_series(
    db: AsyncSession, start: datetime, end: datetime, resolution: str = "auto"
) -> dict[str, Any]:
    """Verlaufsdaten zwischen ``start`` und ``end``.

    ``raw``  — Stichproben unverändert
    ``hour`` — Stundenmittel (Maxima für die Spitzenwerte) aus den Rohdaten
    ``day``  — Tagesaggregate aus system_metrics_daily
    """
    resolution = choose_resolution(start, end, resolution)

    if resolution == "day":
        rows = (
            await db.execute(
                select(SystemMetricDaily)
                .where(SystemMetricDaily.day >= start.date(), SystemMetricDaily.day <= end.date())
                .order_by(SystemMetricDaily.day)
            )
        ).scalars().all()
        return {
            "resolution": "day",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "points": [_daily_point(r) for r in rows],
        }

    if resolution == "hour":
        bucket = func.date_trunc("hour", SystemMetricSample.captured_at).label("bucket")
        stmt = (
            select(
                bucket,
                func.count().label("samples"),
                *[func.avg(getattr(SystemMetricSample, f)).label(f) for f in _GAUGE_FIELDS],
                *[func.sum(getattr(SystemMetricSample, f)).label(f) for f in _COUNTER_FIELDS],
                func.max(SystemMetricSample.cpu_percent).label("cpu_percent_max"),
                func.max(SystemMetricSample.mem_percent).label("mem_percent_max"),
                func.max(SystemMetricSample.active_users).label("active_users_max"),
                func.max(SystemMetricSample.psi_io_avg10).label("psi_io_max"),
            )
            .where(SystemMetricSample.captured_at >= start, SystemMetricSample.captured_at <= end)
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        points = []
        for row in rows:
            mapping = row._mapping
            point = {"t": mapping["bucket"].isoformat() if mapping["bucket"] else None, "samples": mapping["samples"]}
            for f in _SERIES_FIELDS:
                point[f] = _round(mapping[f])
            for extra in ("cpu_percent_max", "mem_percent_max", "active_users_max", "psi_io_max"):
                point[extra] = _round(mapping[extra])
            points.append(point)
        return {"resolution": "hour", "from": start.isoformat(), "to": end.isoformat(), "points": points}

    rows = (
        await db.execute(
            select(SystemMetricSample)
            .where(SystemMetricSample.captured_at >= start, SystemMetricSample.captured_at <= end)
            .order_by(SystemMetricSample.captured_at)
        )
    ).scalars().all()
    return {
        "resolution": "raw",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "points": [
            {"t": r.captured_at.isoformat(), **{f: getattr(r, f) for f in _SERIES_FIELDS}}
            for r in rows
        ],
    }


def _round(value: Any) -> Any:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return value


def _daily_point(row: SystemMetricDaily) -> dict[str, Any]:
    return {
        "t": row.day.isoformat(),
        "samples": row.samples,
        "cpu_percent": _round(row.cpu_avg),
        "cpu_percent_max": _round(row.cpu_max),
        "load1": _round(row.load_avg),
        "mem_percent": _round(row.mem_percent_avg),
        "mem_percent_max": _round(row.mem_percent_max),
        "mem_used_bytes": row.mem_used_max_bytes,
        "disk_percent": _round(row.disk_percent_avg),
        "disk_percent_max": _round(row.disk_percent_max),
        "disk_used_bytes": row.disk_used_max_bytes,
        "disk_read_bytes_s": _round(row.disk_read_bytes_s_avg),
        "disk_write_bytes_s": _round(row.disk_write_bytes_s_avg),
        "psi_io_avg10": _round(row.psi_io_avg),
        "psi_io_max": _round(row.psi_io_max),
        "psi_cpu_avg10": _round(row.psi_cpu_avg),
        "psi_mem_avg10": _round(row.psi_mem_avg),
        "db_size_bytes": row.db_size_max_bytes,
        "containers_unhealthy": row.containers_unhealthy_max,
        "containers_running": row.containers_running_min,
        "active_users": _round(row.active_users_avg),
        "active_users_max": row.active_users_max,
        "unique_users": row.unique_users,
        "logins": row.logins,
        "requests": row.requests,
        "request_errors": row.request_errors,
        "avg_response_ms": _round(row.avg_response_ms),
    }


async def unique_users_between(db: AsyncSession, start_day: date, end_day: date) -> int:
    """Eindeutige Benutzer, die im Zeitraum im Portal aktiv waren."""
    value = await _safe_scalar(
        db,
        select(func.count(func.distinct(UserActivityDay.user_id))).where(
            UserActivityDay.day >= start_day, UserActivityDay.day <= end_day
        ),
    )
    return int(value or 0)


async def user_activity_days(db: AsyncSession, start_day: date, end_day: date) -> list[dict]:
    """Nutzung je Tag: eindeutige Nutzer, Organisationen und Requests."""
    stmt = (
        select(
            UserActivityDay.day,
            func.count(func.distinct(UserActivityDay.user_id)).label("users"),
            func.count(func.distinct(UserActivityDay.org_id)).label("orgs"),
            func.sum(UserActivityDay.requests).label("requests"),
        )
        .where(UserActivityDay.day >= start_day, UserActivityDay.day <= end_day)
        .group_by(UserActivityDay.day)
        .order_by(UserActivityDay.day)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "day": r._mapping["day"].isoformat(),
            "users": int(r._mapping["users"] or 0),
            "orgs": int(r._mapping["orgs"] or 0),
            "requests": int(r._mapping["requests"] or 0),
        }
        for r in rows
    ]


# ── Verdichtung & Aufbewahrung ───────────────────────────────────────────────

async def rollup_day(db: AsyncSession, day: date) -> SystemMetricDaily | None:
    """Einen Tag zu einer Aggregatzeile verdichten (idempotent)."""
    start = datetime.combine(day, dtime.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    row = (
        await db.execute(
            select(
                func.count().label("samples"),
                func.avg(SystemMetricSample.cpu_percent).label("cpu_avg"),
                func.max(SystemMetricSample.cpu_percent).label("cpu_max"),
                func.avg(SystemMetricSample.load1).label("load_avg"),
                func.max(SystemMetricSample.load1).label("load_max"),
                func.avg(SystemMetricSample.mem_percent).label("mem_percent_avg"),
                func.max(SystemMetricSample.mem_percent).label("mem_percent_max"),
                func.max(SystemMetricSample.mem_used_bytes).label("mem_used_max_bytes"),
                func.avg(SystemMetricSample.disk_percent).label("disk_percent_avg"),
                func.max(SystemMetricSample.disk_percent).label("disk_percent_max"),
                func.max(SystemMetricSample.disk_used_bytes).label("disk_used_max_bytes"),
                func.avg(SystemMetricSample.disk_read_bytes_s).label("disk_read_bytes_s_avg"),
                func.avg(SystemMetricSample.disk_write_bytes_s).label("disk_write_bytes_s_avg"),
                func.avg(SystemMetricSample.psi_io_avg10).label("psi_io_avg"),
                func.max(SystemMetricSample.psi_io_avg10).label("psi_io_max"),
                func.avg(SystemMetricSample.psi_cpu_avg10).label("psi_cpu_avg"),
                func.avg(SystemMetricSample.psi_mem_avg10).label("psi_mem_avg"),
                func.max(SystemMetricSample.db_size_bytes).label("db_size_max_bytes"),
                func.max(SystemMetricSample.containers_unhealthy).label("containers_unhealthy_max"),
                func.min(SystemMetricSample.containers_running).label("containers_running_min"),
                func.avg(SystemMetricSample.active_users).label("active_users_avg"),
                func.max(SystemMetricSample.active_users).label("active_users_max"),
                func.sum(SystemMetricSample.logins).label("logins"),
                func.sum(SystemMetricSample.requests).label("requests"),
                func.sum(SystemMetricSample.request_errors).label("request_errors"),
                func.avg(SystemMetricSample.avg_response_ms).label("avg_response_ms"),
            ).where(SystemMetricSample.captured_at >= start, SystemMetricSample.captured_at < end)
        )
    ).one()
    values = dict(row._mapping)
    if not values.get("samples"):
        return None

    values["unique_users"] = await unique_users_between(db, day, day)

    existing = (
        await db.execute(select(SystemMetricDaily).where(SystemMetricDaily.day == day))
    ).scalar_one_or_none()
    if existing is None:
        existing = SystemMetricDaily(day=day)
        db.add(existing)
    for key, value in values.items():
        setattr(existing, key, _to_number(value, key))
    return existing


_INT_FIELDS = {
    "samples",
    "mem_used_max_bytes",
    "disk_used_max_bytes",
    "db_size_max_bytes",
    "containers_unhealthy_max",
    "containers_running_min",
    "active_users_max",
    "unique_users",
    "logins",
    "requests",
    "request_errors",
}


def _to_number(value: Any, key: str) -> Any:
    """Numerische Aggregatwerte in den Spaltentyp überführen. ``avg()`` liefert
    in PostgreSQL ein ``Decimal``, das SQLAlchemy sonst in Float-Spalten kippt."""
    if value is None:
        return None
    try:
        return int(value) if key in _INT_FIELDS else float(value)
    except (TypeError, ValueError):
        return None


async def rollup_pending(db: AsyncSession, *, max_days: int = 40) -> int:
    """Alle abgeschlossenen Tage verdichten, für die noch kein Aggregat existiert.

    Der laufende Tag wird bewusst ausgelassen (er ist noch unvollständig) —
    Ausnahme: er wird beim nächsten Lauf nach Mitternacht nachgeholt. ``max_days``
    begrenzt die Nacharbeit nach längerem Stillstand.
    """
    today = datetime.now(timezone.utc).date()
    oldest = (
        await db.execute(select(func.min(SystemMetricSample.captured_at)))
    ).scalar()
    if oldest is None:
        return 0
    first_day = max(oldest.date(), today - timedelta(days=max_days))

    existing_days = set(
        (
            await db.execute(
                select(SystemMetricDaily.day).where(SystemMetricDaily.day >= first_day)
            )
        ).scalars().all()
    )

    written = 0
    day = first_day
    while day < today:
        if day not in existing_days and await rollup_day(db, day) is not None:
            written += 1
        day += timedelta(days=1)
    if written:
        await db.commit()
    return written


async def purge_old(db: AsyncSession) -> dict[str, int]:
    """Stichproben und Aggregate außerhalb der Aufbewahrungsfristen löschen."""
    now = datetime.now(timezone.utc)
    raw_cutoff = now - timedelta(days=settings.system_metrics_retention_days)
    daily_cutoff = (now - timedelta(days=settings.system_metrics_daily_retention_days)).date()

    raw = await db.execute(delete(SystemMetricSample).where(SystemMetricSample.captured_at < raw_cutoff))
    daily = await db.execute(delete(SystemMetricDaily).where(SystemMetricDaily.day < daily_cutoff))
    # Die Nutzungshistorie folgt der Aufbewahrung der Tagesaggregate — sie ist
    # die Grundlage der „eindeutige Nutzer"-Zahl in denselben Berichten.
    users = await db.execute(delete(UserActivityDay).where(UserActivityDay.day < daily_cutoff))
    await db.commit()
    counts = {
        "samples": raw.rowcount or 0,
        "daily": daily.rowcount or 0,
        "user_activity": users.rowcount or 0,
    }
    if any(counts.values()):
        logger.info("Metrik-Aufbewahrung: %s", counts)
    return counts


# ── Monatsbericht ────────────────────────────────────────────────────────────

async def available_months(db: AsyncSession) -> list[str]:
    """Monate (``YYYY-MM``), für die Tagesaggregate vorliegen — neueste zuerst."""
    rows = (await db.execute(select(SystemMetricDaily.day))).scalars().all()
    return sorted({f"{d.year:04d}-{d.month:02d}" for d in rows}, reverse=True)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


async def monthly_report(db: AsyncSession, year: int, month: int) -> dict[str, Any]:
    """Monatsbericht aus den Tagesaggregaten.

    Ist der laufende Monat gemeint, wird der heutige (noch nicht verdichtete)
    Tag vorher nachverdichtet, damit der Bericht nicht bei gestern endet.
    """
    first, last = month_bounds(year, month)
    today = datetime.now(timezone.utc).date()
    if first <= today <= last:
        await rollup_day(db, today)
        await db.commit()

    rows = (
        await db.execute(
            select(SystemMetricDaily)
            .where(SystemMetricDaily.day >= first, SystemMetricDaily.day <= last)
            .order_by(SystemMetricDaily.day)
        )
    ).scalars().all()

    days = [_daily_point(r) for r in rows]

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    def _collect(attr: str) -> list[float]:
        return [float(getattr(r, attr)) for r in rows if getattr(r, attr) is not None]

    cpu_avgs, cpu_maxes = _collect("cpu_avg"), _collect("cpu_max")
    mem_avgs, mem_maxes = _collect("mem_percent_avg"), _collect("mem_percent_max")
    disk_avgs, disk_maxes = _collect("disk_percent_avg"), _collect("disk_percent_max")
    psi_avgs, psi_maxes = _collect("psi_io_avg"), _collect("psi_io_max")

    unique_users = await unique_users_between(db, first, last)
    busiest = max(days, key=lambda d: d["unique_users"] or 0, default=None)
    peak_cpu_day = max(rows, key=lambda r: r.cpu_max or -1, default=None)

    return {
        "month": f"{year:04d}-{month:02d}",
        "from": first.isoformat(),
        "to": last.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days_covered": len(rows),
        "summary": {
            "cpu_percent_avg": _avg(cpu_avgs),
            "cpu_percent_max": max(cpu_maxes) if cpu_maxes else None,
            "mem_percent_avg": _avg(mem_avgs),
            "mem_percent_max": max(mem_maxes) if mem_maxes else None,
            "disk_percent_avg": _avg(disk_avgs),
            "disk_percent_max": max(disk_maxes) if disk_maxes else None,
            "disk_used_end_bytes": rows[-1].disk_used_max_bytes if rows else None,
            "disk_used_start_bytes": rows[0].disk_used_max_bytes if rows else None,
            "psi_io_avg": _avg(psi_avgs),
            "psi_io_max": max(psi_maxes) if psi_maxes else None,
            "db_size_end_bytes": rows[-1].db_size_max_bytes if rows else None,
            "db_size_start_bytes": rows[0].db_size_max_bytes if rows else None,
            "unique_users": unique_users,
            "active_users_max": max((r.active_users_max or 0) for r in rows) if rows else None,
            "active_users_avg": _avg(_collect("active_users_avg")),
            "logins": sum((r.logins or 0) for r in rows),
            "requests": sum((r.requests or 0) for r in rows),
            "request_errors": sum((r.request_errors or 0) for r in rows),
            "avg_response_ms": _avg(_collect("avg_response_ms")),
            "containers_unhealthy_max": max((r.containers_unhealthy_max or 0) for r in rows) if rows else None,
            "days_with_unhealthy_containers": sum(
                1 for r in rows if (r.containers_unhealthy_max or 0) > 0
            ),
            "busiest_day": busiest["t"] if busiest else None,
            "busiest_day_users": busiest["unique_users"] if busiest else None,
            "peak_cpu_day": peak_cpu_day.day.isoformat() if peak_cpu_day else None,
        },
        "days": days,
        "usage_by_day": await user_activity_days(db, first, last),
    }
