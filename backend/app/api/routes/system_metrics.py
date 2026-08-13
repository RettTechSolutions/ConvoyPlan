"""Systemübersicht — Live-Zustand, Verlauf und Monatsberichte.

Alle Endpunkte liegen unter ``/api/admin/system`` und erfordern einen
Superadmin (Bearer-Token). Sie sind bewusst als normale REST-Endpunkte
ausgeführt, damit die Daten nicht nur im Admin-Portal, sondern auch von einem
Monitoring-System, einem Skript oder einer Tabellenkalkulation abgeholt werden
können — Swagger dokumentiert sie unter dem Tag ``system-metrics``.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_superadmin
from app.models.user import User
from app.services import activity, docker_stats, system_metrics, system_report

router = APIRouter(prefix="/admin/system", tags=["system-metrics"])

# Vorgefertigte Zeiträume der Admin-Oberfläche.
_RANGES = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "365d": timedelta(days=365),
}

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_month(month: str) -> tuple[int, int]:
    match = _MONTH_RE.match(month.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Monat muss im Format JJJJ-MM angegeben werden.")
    year, mon = int(match.group(1)), int(match.group(2))
    if not 1 <= mon <= 12 or not 2000 <= year <= 2200:
        raise HTTPException(status_code=400, detail="Ungültiger Monat.")
    return year, mon


def _resolve_window(
    range_key: str | None, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    """Zeitfenster aus ``range`` bzw. ``from``/``to`` bestimmen (UTC)."""
    now = datetime.now(timezone.utc)
    if start or end:
        window_end = (end or now)
        window_start = start or (window_end - timedelta(days=1))
    else:
        delta = _RANGES.get(range_key or "24h")
        if delta is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unbekannter Zeitraum. Erlaubt: {', '.join(_RANGES)} — oder from/to angeben.",
            )
        window_end, window_start = now, now - delta
    # Naive Zeitstempel (z. B. "2026-08-01T00:00:00") als UTC lesen, statt sie
    # gegen aware Spaltenwerte laufen zu lassen — das wäre ein TypeError.
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    if window_start >= window_end:
        raise HTTPException(status_code=400, detail="'from' muss vor 'to' liegen.")
    return window_start, window_end


@router.get(
    "/overview",
    summary="Live-Zustand des Systems",
    description=(
        "Frisch gemessene Momentaufnahme: CPU, Arbeitsspeicher, Plattenbelegung und "
        "-druck (PSI), Container-Zustände aus der Docker-Engine, Datenbankgröße sowie "
        "die aktuelle Portalnutzung."
    ),
)
async def overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    return await system_metrics.live_snapshot(db)


@router.get(
    "/containers",
    summary="Container-Zustände",
    description=(
        "Alle Container des Stacks mit Status, Healthcheck und — sofern aktiviert — "
        "CPU-/RAM-Verbrauch. Ist die Docker-API nicht erreichbar, meldet die Antwort "
        "`available: false` mit Begründung."
    ),
)
async def containers(
    with_stats: bool = Query(True, description="CPU/RAM je Container mitliefern"),
    _: User = Depends(require_superadmin),
):
    report = await docker_stats.collect(with_stats=with_stats)
    return report.as_dict()


@router.get(
    "/history",
    summary="Verlauf der Systemkennzahlen",
    description=(
        "Zeitreihe über den gewählten Zeitraum. `resolution=auto` wählt automatisch "
        "zwischen Rohstichproben, Stundenmitteln und Tagesaggregaten, sodass die "
        "Antwort handlich bleibt. Tageswerte reichen so weit zurück wie die "
        "Aggregat-Aufbewahrung (Standard 3 Jahre), Rohdaten 90 Tage."
    ),
)
async def history(
    range: str | None = Query(None, alias="range", description="1h, 6h, 24h, 7d, 30d, 90d, 365d"),
    from_: datetime | None = Query(None, alias="from", description="ISO-Zeitstempel (UTC)"),
    to: datetime | None = Query(None, description="ISO-Zeitstempel (UTC)"),
    resolution: str = Query("auto", pattern="^(auto|raw|hour|day)$"),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    start, end = _resolve_window(range, from_, to)
    series = await system_metrics.query_series(db, start, end, resolution)
    if format == "csv":
        filename = f"convoyplan-verlauf-{start.date()}-bis-{end.date()}.csv"
        return Response(
            content=system_report.series_csv(series),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return series


@router.get(
    "/usage",
    summary="Portalnutzung je Tag",
    description=(
        "Wie viele Benutzer je Tag im Portal aktiv waren — getrennt nach regulären "
        "Portalnutzern (`users`), Demo-Besuchern (`demo_users`) und Superadmins im "
        "Admin-Portal (`admin_users`). `unique_users` zählt nur reguläre Nutzer, damit "
        "Probesitzungen und die eigene Administration die Kennzahl nicht aufblähen. "
        "Grundlage ist die Tagesaktivität, die unabhängig von den Hardware-Stichproben "
        "geführt wird."
    ),
)
async def usage(
    days: int = Query(30, ge=1, le=1095),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    rows = await system_metrics.user_activity_days(db, start, today)
    return {
        "from": start.isoformat(),
        "to": today.isoformat(),
        "unique_users": await system_metrics.unique_users_between(db, start, today),
        "unique_demo_users": await system_metrics.unique_users_between(
            db, start, today, activity.KIND_DEMO
        ),
        "unique_admin_users": await system_metrics.unique_users_between(
            db, start, today, activity.KIND_ADMIN
        ),
        "days": rows,
    }


@router.get(
    "/reports/months",
    summary="Verfügbare Monatsberichte",
    description="Monate (JJJJ-MM), für die verdichtete Tageswerte vorliegen — neueste zuerst.",
)
async def report_months(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    months = await system_metrics.available_months(db)
    current = datetime.now(timezone.utc).strftime("%Y-%m")
    # Der laufende Monat ist auch dann abrufbar, wenn er noch kein Aggregat hat —
    # der Bericht verdichtet den heutigen Tag beim Abruf selbst.
    if current not in months:
        months.insert(0, current)
    return {"months": months, "current": current}


@router.get(
    "/reports/monthly",
    summary="Monatsbericht",
    description=(
        "Monatsbericht mit Kennzahlen zu Auslastung, Speicher, Plattendruck, "
        "Container-Störungen und Portalnutzung. `format=json` für die "
        "Weiterverarbeitung, `csv` für die Tabellenkalkulation, `pdf` zum Ablegen."
    ),
)
async def monthly_report(
    month: str = Query(..., description="Monat im Format JJJJ-MM, z. B. 2026-07"),
    format: str = Query("json", pattern="^(json|csv|pdf)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    year, mon = _parse_month(month)
    report = await system_metrics.monthly_report(db, year, mon)

    if format == "json":
        return report

    filename = f"convoyplan-systembericht-{year:04d}-{mon:02d}"
    if format == "csv":
        return Response(
            content=system_report.monthly_report_csv(report),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )

    # PDF-Erzeugung ist CPU-gebunden und blockierend — wie beim Marschbefehl in
    # den Thread-Pool auslagern, damit der Event-Loop frei bleibt.
    loop = asyncio.get_running_loop()
    pdf_bytes = await loop.run_in_executor(None, system_report.monthly_report_pdf, report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.post(
    "/sample",
    status_code=202,
    summary="Stichprobe sofort erfassen",
    description=(
        "Erzwingt außerhalb des Sampling-Intervalls eine Messung. Nützlich direkt "
        "nach der Einrichtung, damit die Verlaufscharts nicht erst nach dem ersten "
        "Intervall etwas anzeigen."
    ),
)
async def sample_now(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_superadmin),
):
    sample = await system_metrics.collect_sample(db)
    return {"status": "ok", "captured_at": sample.captured_at.isoformat()}
